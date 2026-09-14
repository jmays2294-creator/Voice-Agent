"""Speech out.

A sentence queue feeding on-device synthesis on a worker thread, so the async
side never blocks on audio and barge-in can cut an utterance mid-word.

Barge-in must be instant and must never desync: a key press while speaking
clears the queue, stops the current utterance, and tells the caller the turn was
abandoned so `Brain.settle()` can drain it before the next question.
"""

from __future__ import annotations

import contextlib
import queue
import threading
import time
from dataclasses import dataclass

from . import interlock, signals
from .diction import for_speech

#: Barge-in budget. A cut that takes longer than this is audible as a daemon
#: that did not hear you.
STOP_BUDGET_MS = 100


@dataclass
class MouthStats:
    first_audio_ms: float | None = None
    spoken: int = 0
    dropped: int = 0


class Mouth:
    def __init__(self, voice, check_interlock: bool = True) -> None:
        self.voice = voice
        self.check_interlock = check_interlock
        self._q: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._running = threading.Event()
        self._speaking = threading.Event()
        self._turn_started: float | None = None
        self.stats = MouthStats()
        #: Rule 4.5 — asked once per session, before any case material is spoken.
        self._room_confirmed = False

    # --- lifecycle -------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._running.set()
        self._thread = threading.Thread(target=self._pump, name="desk-mouth", daemon=True)
        self._thread.start()

    def stop_worker(self) -> None:
        self._running.clear()
        self._q.put(None)
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def prewarm(self) -> None:
        """Warm the voice and hold the output stream open, so the first real
        sentence of the day is not the slow one."""
        # An optimisation, not a gate: a voice that cannot warm up still
        # speaks, just slower on the first sentence.
        with contextlib.suppress(Exception):
            self.voice.prewarm()

    # --- the queue -------------------------------------------------------

    def begin_turn(self) -> None:
        self.stats = MouthStats()
        self._turn_started = time.perf_counter()

    def say(self, text: str) -> None:
        """Queue one sentence. Returns immediately — the mouth starts while the
        thought is still forming."""
        if not text or not text.strip():
            return
        if self.check_interlock and interlock.is_locked():
            # Locked screen: deaf and mute. Do not queue for later.
            self.stats.dropped += 1
            return
        self._q.put(for_speech(text))

    def say_now(self, text: str) -> None:
        """Speak without the diction pass — used for denial reasons, which are
        already written for a mouth."""
        if not text or not text.strip():
            return
        if self.check_interlock and interlock.is_locked():
            self.stats.dropped += 1
            return
        self._q.put(text)

    def barge_in(self) -> int:
        """Cut immediately. Returns how many queued sentences were discarded."""
        dropped = 0
        while True:
            try:
                item = self._q.get_nowait()
                self._q.task_done()
                if item is not None:
                    dropped += 1
            except queue.Empty:
                break
        with contextlib.suppress(Exception):
            self.voice.stop()
        self._speaking.clear()
        self.stats.dropped += dropped
        signals.set_state(signals.IDLE)
        return dropped

    def wait_until_quiet(self, timeout: float = 30.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._q.empty() and not self._speaking.is_set():
                return True
            time.sleep(0.01)
        return False

    @property
    def speaking(self) -> bool:
        return self._speaking.is_set()

    # --- Rule 4.5 --------------------------------------------------------

    @property
    def room_confirmed(self) -> bool:
        return self._room_confirmed

    def confirm_room(self) -> None:
        """Joel has said the room is safe. Holds for this session only."""
        self._room_confirmed = True

    def reset_room(self) -> None:
        self._room_confirmed = False

    def case_material_guard(self, headline: str) -> str | None:
        """What to speak when case material is involved.

        Default for privileged material is quiet: the headline aloud, the detail
        on screen. Returns the sentence to speak, or None if the room has not
        been confirmed yet this session.
        """
        if self._room_confirmed:
            return None
        return (
            "Before I read anything case-specific out loud — can you be overheard "
            f"where you are? {headline}"
        )

    # --- worker ----------------------------------------------------------

    def _pump(self) -> None:
        while self._running.is_set():
            item = self._q.get()
            if item is None:
                self._q.task_done()
                continue
            if self.check_interlock and interlock.is_locked():
                self.stats.dropped += 1
                self._q.task_done()
                continue
            self._speaking.set()
            signals.set_state(signals.SPEAKING)
            try:
                if self.stats.first_audio_ms is None and self._turn_started is not None:
                    self.stats.first_audio_ms = (time.perf_counter() - self._turn_started) * 1000
                self.voice.speak(item)
                self.stats.spoken += 1
            except Exception:
                pass
            finally:
                self._speaking.clear()
                self._q.task_done()
                if self._q.empty():
                    signals.set_state(signals.IDLE)
