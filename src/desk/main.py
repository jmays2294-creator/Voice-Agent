"""The loop.

Boot order matters: verify weights, check the interlock, prewarm everything,
then open the key. Joel's first sentence of the day should not be the slow one,
and the daemon should never reach a state where it is listening but not ready.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import sys
import time
from dataclasses import dataclass
from typing import ClassVar

from . import audit as audit_mod
from . import grant, interlock, paths, signals
from .brain import Brain, require_pinned_model
from .config import Config, load
from .ears import Ears

log = logging.getLogger("desk")


@dataclass
class TurnTiming:
    """Timings only. Never content — Rule 4."""
    release_to_text_ms: float = 0.0
    first_token_ms: float = 0.0
    first_sentence_ms: float = 0.0
    first_audio_ms: float = 0.0
    total_ms: float = 0.0
    sentences: int = 0
    tool_calls: int = 0
    barge_in: bool = False
    rebuilt: bool = False


class Desk:
    def __init__(self, cfg: Config, brain: Brain, ears: Ears, mouth,
                 audit: audit_mod.Audit, screen=None) -> None:
        self.cfg = cfg
        self.brain = brain
        self.ears = ears
        self.mouth = mouth
        self.audit = audit
        self.screen = screen
        self.turns = 0
        self.timings: list[TurnTiming] = []
        self._turn_task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    # --- key handling ----------------------------------------------------

    def on_press(self) -> None:
        """Key down. The only thing in the daemon that opens the microphone."""
        if interlock.is_locked():
            # Locked screen: deaf and mute. No queueing, no resume on unlock.
            signals.set_state(signals.DEAF)
            self._screen_status(signals.DEAF)
            return
        if self.mouth.speaking or self._turn_task is not None:
            # Barge-in. Cut the utterance, abandon the turn; settle() drains it
            # before the next question so the stream never goes one turn late.
            self.mouth.barge_in()
            self._cancel_turn()
        self.ears.open()
        signals.set_state(signals.LISTENING)
        self._screen_status(signals.LISTENING)

    def on_release(self) -> None:
        """Key up. Close the device before anything else happens."""
        if not self.ears.is_open:
            return
        self.ears.close()
        signals.set_state(signals.THINKING)
        self._screen_status(signals.THINKING)
        if self._loop is not None:
            asyncio.run_coroutine_threadsafe(self._handle_turn(), self._loop)

    def _cancel_turn(self) -> None:
        task, self._turn_task = self._turn_task, None
        if task is not None and not task.done():
            task.cancel()

    def _screen_status(self, state: str, heard: str = "", said: str = "") -> None:
        """A no-op when there is no screen — the --verbose surface only."""
        if self.screen is not None:
            self.screen.status(state, heard=heard, said=said)

    # --- the turn --------------------------------------------------------

    def _ship_timing(self, timing: TurnTiming) -> None:
        self.audit.turn(
            total_ms=timing.total_ms,
            release_to_text_ms=timing.release_to_text_ms or None,
            first_token_ms=timing.first_token_ms or None,
            first_sentence_ms=timing.first_sentence_ms or None,
            first_audio_ms=timing.first_audio_ms or None,
            sentences=timing.sentences,
            tool_calls=timing.tool_calls,
            barge_in=timing.barge_in,
            rebuilt=timing.rebuilt,
        )

    async def _handle_turn(self) -> None:
        timing = TurnTiming()
        started = time.perf_counter()
        rebuilds_before = self.brain.rebuilds
        try:
            capture = await asyncio.to_thread(self.ears.transcribe)
        except Exception as exc:
            log.exception("transcription failed")
            self.mouth.say_now("I couldn't make that out.")
            self.audit.denial("Transcribe", "stt.error", str(exc), spoken=True)
            signals.set_state(signals.IDLE)
            return

        timing.release_to_text_ms = (time.perf_counter() - started) * 1000
        text = capture.text.strip()
        if not text:
            signals.set_state(signals.IDLE)
            self._screen_status(signals.IDLE)
            return
        self._screen_status(signals.THINKING, heard=text)

        hosts = grant.detect(text, self.cfg.egress_hosts)
        if hosts:
            grant.issue(hosts, self.cfg.web_grant_seconds)

        self.mouth.begin_turn()
        self._turn_task = asyncio.current_task()
        try:
            await self._speak_answer(text, timing)
        except asyncio.CancelledError:
            # Barge-in mid-answer. The turn is abandoned, not consumed.
            timing.barge_in = True
            with contextlib.suppress(Exception):
                await self.brain.settle()
            raise
        finally:
            grant.revoke()
            self._turn_task = None
            await self._speak_denials()
            signals.set_state(signals.IDLE)
            self._screen_status(signals.IDLE)
            timing.total_ms = (time.perf_counter() - started) * 1000
            stats = self.brain.last
            if stats is not None:
                timing.sentences = stats.sentences
                timing.tool_calls = stats.tool_calls
            timing.rebuilt = self.brain.rebuilds > rebuilds_before
            self.timings.append(timing)
            signals.set_metrics(total_ms=timing.total_ms,
                                first_audio_ms=timing.first_audio_ms)
            # Timings go to the dashboard. Shipping is best effort and spools
            # offline; a dropped metric must never cost a turn.
            with contextlib.suppress(Exception):
                await asyncio.to_thread(self._ship_timing, timing)
            self.turns += 1

    async def _speak_answer(self, text: str, timing: TurnTiming) -> None:
        async for sentence in self.brain.ask(text):
            self.mouth.say(sentence)
            self._screen_status(signals.SPEAKING, said=sentence)
            if not timing.first_sentence_ms:
                stats = self.brain.last
                timing.first_token_ms = stats.first_token_ms or 0.0
                timing.first_sentence_ms = stats.first_sentence_ms or 0.0
                timing.first_audio_ms = self.mouth.stats.first_audio_ms or 0.0

    async def _speak_denials(self) -> None:
        """A silent denial teaches Joel nothing (Rule 7)."""
        for record in audit_mod.pending_denials():
            self.mouth.say_now(record.get("say", ""))
            self.audit.denial(record.get("tool", "unknown"), record.get("rule", ""),
                              record.get("say", ""), spoken=True)

    # --- lifecycle -------------------------------------------------------

    #: Per-stage prewarm ceilings. Generous, because the first mlx run compiles
    #: Metal kernels, but finite: a stage that never returns must fail loudly
    #: rather than leave the daemon sitting there looking started.
    PREWARM_TIMEOUTS: ClassVar[dict[str, float]] = {
        "transcriber": 180.0, "voice": 30.0, "model": 90.0}

    async def _stage(self, name: str, coro, timeout: float) -> bool:
        """Run one boot stage, timed and announced. Never raises."""
        log.info("prewarming %s...", name)
        start = time.perf_counter()
        try:
            async with asyncio.timeout(timeout):
                await coro
        except (TimeoutError, asyncio.TimeoutError):
            # No traceback: a TimeoutError's stack says nothing useful here.
            log.error(  # noqa: TRY400
                "prewarming %s timed out after %.3gs — continuing without it. "
                "The first turn will be slow, or that half will not work.", name, timeout)
            return False
        except Exception as exc:
            # A prewarm failure is not fatal, but it must never be silent:
            # return_exceptions=True used to swallow these whole.
            # Traceback wanted: this is the line that tells Joel which of
            # PyObjC, the audio device or the model actually broke.
            log.exception("prewarming %s failed: %s", name, type(exc).__name__)
            return False
        log.info("prewarmed %s in %.0fms", name, (time.perf_counter() - start) * 1000)
        return True

    async def prewarm(self) -> None:
        """Warm every stage so Joel's first sentence of the day is not the slow one.

        Each stage is announced, timed and bounded. The previous version
        gathered all three with return_exceptions=True and discarded the
        results, so one hung stage hung the boot with no output at all and a
        failed stage was swallowed entirely.
        """
        signals.set_state(signals.IDLE)
        log.info("prewarming (first run compiles Metal kernels; this can take a minute)")
        results = await asyncio.gather(
            self._stage("transcriber", asyncio.to_thread(self.ears.transcriber.prewarm),
                        self.PREWARM_TIMEOUTS["transcriber"]),
            self._stage("voice", asyncio.to_thread(self.mouth.prewarm),
                        self.PREWARM_TIMEOUTS["voice"]),
            self._stage("model", self.brain.prewarm(), self.PREWARM_TIMEOUTS["model"]),
        )
        if not all(results):
            log.warning("some stages did not prewarm — Desk still runs, see above")

    async def run(self, ptt) -> None:
        self._loop = asyncio.get_running_loop()
        # Both of these are synchronous HTTPS calls. Off the loop, so a slow
        # network delays the boot log rather than freezing the whole daemon.
        log.info("auth source: %s", _auth_source())
        log.info("opening the audit session...")
        await asyncio.to_thread(self.audit.flush_spool)
        await asyncio.to_thread(self.audit.start_session)
        self.mouth.start()
        log.info("connecting the model session...")
        await self.brain.connect()
        await self.prewarm()
        log.info("Desk ready. Hold the key to talk. (key code %d)", self.cfg.ptt_keycode)
        error = None
        try:
            await asyncio.to_thread(ptt.run)
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            log.exception("daemon loop failed")
        finally:
            await self.shutdown(error)

    async def shutdown(self, error: str | None = None) -> None:
        self.ears.close()
        self.mouth.barge_in()
        self.mouth.stop_worker()
        grant.revoke()
        with contextlib.suppress(Exception):
            self.audit.ship_decision_log()
        actions = sum(t.tool_calls for t in self.timings)
        self.audit.end_session(self.turns, error, actions=actions)
        await self.brain.disconnect()
        signals.set_state(signals.IDLE)


# --- wiring ---------------------------------------------------------------

def _auth_source() -> str:
    """Which credential the model session will use. The NAME only — never the
    value, and never enough of it to reconstruct one.

    This is a threat-model fact, not a curiosity: an API key means commercial
    API terms, while a claude.ai login on a personal plan means consumer terms,
    and the two differ on whether conversation content may be used for
    training. Desk's conversations are Comp Desk material and sometimes client
    material. See docs/FINDINGS.md item 2.
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "ANTHROPIC_API_KEY (commercial API terms; overrides a claude.ai login)"
    if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return "CLAUDE_CODE_OAUTH_TOKEN"
    return "claude.ai login (check the plan — consumer terms differ on training)"


def build(cfg: Config, verbose: bool = False) -> tuple[Desk, object]:
    from . import ptt as ptt_mod
    from . import session
    from .mouth import Mouth
    from .screen import Screen
    from .stt import create as create_stt
    from .tts import create as create_tts

    require_pinned_model(cfg.model)
    paths.ensure_dirs()

    # The screen surface only exists for --verbose: it is a terminal you are
    # watching, not a default-on channel for a headless run.
    screen = Screen() if verbose else None
    transcriber = create_stt(cfg.stt_backend, cfg.stt_model)
    voice = create_tts(cfg.tts_backend, cfg.tts_voice, cfg.tts_rate)
    ears = Ears(transcriber, cfg.sample_rate)
    mouth = Mouth(voice, screen=screen)
    brain = Brain(lambda: session.build_options(cfg))
    audit = audit_mod.Audit(host=cfg.supabase_host, service=cfg.keychain_service)

    desk = Desk(cfg, brain, ears, mouth, audit, screen=screen)
    key = ptt_mod.create(cfg.ptt_keycode, desk.on_press, desk.on_release)
    return desk, key


def verify_boot(cfg: Config) -> list[str]:
    """Checks that must pass before the microphone is ever opened."""
    problems: list[str] = []
    try:
        require_pinned_model(cfg.model)
    except Exception as exc:
        problems.append(str(exc))
    try:
        from .weights import verify
        verify(paths.models_dir())
    except Exception as exc:
        problems.append(str(exc))

    # A pin only means something if the hashed file is the one that gets
    # opened. A hub repo id loads from a cache the pins never saw, so the
    # guarantee would be void while still looking satisfied.
    from .stt import is_local
    if cfg.stt_backend in ("auto", "mlx") and not is_local(cfg.stt_model):
        problems.append(
            f"stt_model is {cfg.stt_model!r}, which loads from a hub cache rather than "
            f"the directory the weight pins cover. Desk would verify one file and open "
            f"another. Use local:<name> and put the model in {paths.models_dir()}."
        )
    return problems


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="desk", description="Desk voice daemon")
    parser.add_argument("--check", action="store_true",
                        help="run boot checks and exit without opening the microphone")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        # Timings, never content.
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    cfg = load()

    problems = verify_boot(cfg)
    if args.check:
        for p in problems:
            print(f"FAIL: {p}", file=sys.stderr)
        print("boot checks passed" if not problems else "boot checks failed")
        return 0 if not problems else 1
    if problems:
        for p in problems:
            print(f"refusing to start: {p}", file=sys.stderr)
        return 1

    desk, key = build(cfg, verbose=args.verbose)
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(desk.run(key))
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
