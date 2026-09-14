"""Speech in.

An in-memory ring buffer filled only while the key is held, trimmed of leading
and trailing silence, transcribed on-device, then zeroed and dropped.

No file is written at any point. There is no debug ring buffer and no "keep the
last utterance for troubleshooting" path, because that path is how raw audio
ends up at rest on a machine holding privileged material.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from .stt import Transcriber

#: Hard ceiling on a single held-key capture. A key stuck down must not grow a
#: buffer without bound.
MAX_SECONDS = 120


@dataclass
class Capture:
    text: str
    audio_seconds: float
    capture_ms: float
    transcribe_ms: float


class Ears:
    def __init__(self, transcriber: Transcriber, sample_rate: int = 16000,
                 channels: int = 1) -> None:
        self.transcriber = transcriber
        self.sample_rate = sample_rate
        self.channels = channels
        self._frames: list = []
        self._lock = threading.Lock()
        self._stream = None
        self._started_at = 0.0
        self._open = False

    # --- device ----------------------------------------------------------

    @property
    def is_open(self) -> bool:
        """Whether the microphone is currently held open. Rule 4: at rest this
        is False, and a device-level check must agree."""
        return self._open

    def _make_stream(self):  # pragma: no cover - requires a device
        import sounddevice as sd

        def callback(indata, frames, time_info, status):
            with self._lock:
                if not self._open:
                    return
                if len(self._frames) * frames / self.sample_rate > MAX_SECONDS:
                    return
                self._frames.append(indata.copy())

        return sd.InputStream(samplerate=self.sample_rate, channels=self.channels,
                              dtype="float32", blocksize=0, callback=callback)

    def open(self) -> None:
        """Called on key-down, and from nowhere else."""
        if self._open:
            return
        with self._lock:
            self._frames = []
        self._started_at = time.perf_counter()
        self._stream = self._make_stream()
        self._stream.start()
        self._open = True

    def close(self) -> None:
        """Called on key-up. Stops the device before anything else happens."""
        if not self._open:
            return
        self._open = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None

    # --- transcription ---------------------------------------------------

    def _drain_buffer(self):
        """Take the frames and clear the reference under the lock."""
        with self._lock:
            frames, self._frames = self._frames, []
        return frames

    def transcribe(self) -> Capture:
        """Transcribe what was captured, then free the audio.

        The buffer is zeroed before it is dropped, so the samples do not sit in
        a freed-but-unscrubbed page waiting for whatever allocates next.
        """
        capture_ms = (time.perf_counter() - self._started_at) * 1000
        frames = self._drain_buffer()
        if not frames:
            return Capture("", 0.0, capture_ms, 0.0)

        import numpy as np

        audio = np.concatenate(frames, axis=0).reshape(-1).astype("float32")
        for f in frames:
            try:
                f[:] = 0
            except (TypeError, ValueError):
                pass
        frames.clear()

        try:
            trimmed = trim_silence(audio, self.sample_rate)
            seconds = len(trimmed) / self.sample_rate
            start = time.perf_counter()
            text = self.transcriber.transcribe(trimmed, self.sample_rate) if seconds > 0.1 else ""
            transcribe_ms = (time.perf_counter() - start) * 1000
            return Capture(text.strip(), seconds, capture_ms, transcribe_ms)
        finally:
            audio[:] = 0
            del audio


def trim_silence(audio, sample_rate: int, frame_ms: int = 30,
                 padding_ms: int = 150):
    """Trim leading and trailing silence from an already-captured buffer.

    VAD is a *trimmer* here and never a trigger. It only ever sees audio the
    held key already authorised; no code path lets it open the microphone.
    Rule 4 forbids one, and `tests/test_no_always_listening.py` asserts it.
    """
    import numpy as np

    if audio.size == 0:
        return audio
    try:
        import webrtcvad
    except ImportError:
        return audio

    vad = webrtcvad.Vad(2)
    frame_len = int(sample_rate * frame_ms / 1000)
    if frame_len <= 0 or audio.size < frame_len:
        return audio

    pcm = np.clip(audio, -1.0, 1.0)
    pcm16 = (pcm * 32767).astype("<i2")
    n = pcm16.size // frame_len
    voiced = []
    for i in range(n):
        chunk = pcm16[i * frame_len:(i + 1) * frame_len].tobytes()
        try:
            voiced.append(vad.is_speech(chunk, sample_rate))
        except Exception:  # noqa: BLE001 - an unsupported rate means no trim
            return audio
    if not any(voiced):
        return audio[:0]

    pad = max(1, padding_ms // frame_ms)
    first = max(0, voiced.index(True) - pad)
    last = min(n, len(voiced) - voiced[::-1].index(True) + pad)
    return audio[first * frame_len:last * frame_len]
