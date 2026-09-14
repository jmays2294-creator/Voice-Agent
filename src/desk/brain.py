"""The warm session.

One long-lived `ClaudeSDKClient`, connected at boot and kept for the life of
the daemon. Spawning a process and reloading context per turn is the largest
avoidable cost in a voice loop and the most common way to build one badly.

Two traps this file exists to handle:

1. **The shared-stream off-by-one.** The SDK has one message stream and
   `receive_response()` stops at the first `ResultMessage`; there is no
   query/response pairing. Break out of that loop early — which barge-in does,
   by design, on day one — and the rest of that turn stays buffered. The next
   answer then consumes the *old* turn's tail, and every answer after it is one
   turn late for the rest of the session. So every turn is tracked through its
   `ResultMessage`, and an unconsumed turn is interrupted and drained before
   the next query, with a rebuild if the drain does not finish.

2. **The bare model alias.** The SDK resolves aliases through its bundled CLI
   and can quietly land on an older model. Only a pinned full id is accepted.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Callable

from .sentences import SentenceAccumulator
from .stream import extract_text_delta, is_content_block_stop, message_kind

#: Aliases the SDK would happily resolve somewhere unintended.
_ALIASES = frozenset({"sonnet", "opus", "haiku", "default", "fast", "fable",
                      "sonnet[1m]", "opusplan"})

DRAIN_TIMEOUT = 5.0


class ModelPinError(ValueError):
    pass


def require_pinned_model(model: str) -> str:
    if not model or model.strip().lower() in _ALIASES:
        raise ModelPinError(
            f"model {model!r} is a bare alias. The SDK resolves aliases through its "
            f"bundled CLI and can land on an older model; pin the full id."
        )
    return model


@dataclass
class TurnStats:
    started: float = field(default_factory=time.perf_counter)
    first_token_ms: float | None = None
    first_sentence_ms: float | None = None
    sentences: int = 0
    tool_calls: int = 0
    consumed: bool = False
    interrupted: bool = False

    def elapsed_ms(self) -> float:
        return (time.perf_counter() - self.started) * 1000


class Brain:
    """Owns the session, the drain, and the interrupt."""

    def __init__(self, options_factory: Callable[[], object],
                 client_factory: Callable[[object], object] | None = None) -> None:
        self._options_factory = options_factory
        self._client_factory = client_factory
        self._client = None
        #: False whenever a turn was abandoned before its ResultMessage.
        self._turn_consumed = True
        self._rebuilds = 0
        self.last: TurnStats | None = None

    # --- lifecycle -------------------------------------------------------

    def _build_client(self):
        options = self._options_factory()
        if self._client_factory is not None:
            return self._client_factory(options)
        from claude_agent_sdk import ClaudeSDKClient  # imported late: heavy

        return ClaudeSDKClient(options=options)

    async def connect(self) -> None:
        self._client = self._build_client()
        await self._client.connect()
        self._turn_consumed = True

    async def disconnect(self) -> None:
        if self._client is not None:
            try:
                await self._client.disconnect()
            finally:
                self._client = None

    async def rebuild(self) -> None:
        """Last resort when a drain does not finish. Costs the warm context;
        cheaper than answering one turn late forever."""
        self._rebuilds += 1
        await self.disconnect()
        await self.connect()

    @property
    def rebuilds(self) -> int:
        return self._rebuilds

    @property
    def turn_consumed(self) -> bool:
        return self._turn_consumed

    async def prewarm(self) -> None:
        """One trivial query so the first real one is not the slow one."""
        async for _ in self.ask("Say ready.", prewarm=True):
            pass

    # --- the turn --------------------------------------------------------

    async def interrupt(self) -> None:
        if self._client is not None:
            try:
                await self._client.interrupt()
            except Exception:  # noqa: BLE001 - an interrupt that fails still drains
                pass

    async def drain(self, timeout: float = DRAIN_TIMEOUT) -> bool:
        """Consume an abandoned turn up to and including its ResultMessage.

        Returns True if the stream came back in sync. False means rebuild —
        never "carry on and hope", which is the off-by-one.
        """
        if self._turn_consumed or self._client is None:
            return True
        try:
            async with asyncio.timeout(timeout):
                async for message in self._client.receive_messages():
                    if message_kind(message) == "ResultMessage":
                        self._turn_consumed = True
                        return True
        except (TimeoutError, asyncio.TimeoutError):
            return False
        except Exception:  # noqa: BLE001 - a broken stream is a rebuild
            return False
        return False

    async def settle(self) -> None:
        """Make the stream safe to query on. Called before every turn."""
        if self._turn_consumed:
            return
        await self.interrupt()
        if not await self.drain():
            await self.rebuild()

    async def ask(self, prompt: str, prewarm: bool = False) -> AsyncIterator[str]:
        """Yield complete sentences as they stream. Does not await the turn.

        The mouth starts while the thought is still forming, which is where the
        latency budget is actually won.
        """
        await self.settle()
        if self._client is None:
            await self.connect()

        stats = TurnStats()
        self.last = stats
        acc = SentenceAccumulator()
        self._turn_consumed = False

        try:
            await self._client.query(prompt)
            async for message in self._client.receive_response():
                kind = message_kind(message)

                delta = extract_text_delta(message)
                if delta:
                    if stats.first_token_ms is None:
                        stats.first_token_ms = stats.elapsed_ms()
                    for sentence in acc.feed(delta):
                        if stats.first_sentence_ms is None:
                            stats.first_sentence_ms = stats.elapsed_ms()
                        stats.sentences += 1
                        yield sentence
                    continue

                if is_content_block_stop(message):
                    # The filler before a tool call lives here. Flushing now is
                    # what makes it play *during* the tool run.
                    for sentence in acc.flush():
                        if stats.first_sentence_ms is None:
                            stats.first_sentence_ms = stats.elapsed_ms()
                        stats.sentences += 1
                        yield sentence
                    continue

                if kind == "AssistantMessage":
                    stats.tool_calls += _count_tool_uses(message)
                    continue

                if kind == "ResultMessage":
                    for sentence in acc.flush():
                        stats.sentences += 1
                        yield sentence
                    self._turn_consumed = True
                    stats.consumed = True
                    return
        except GeneratorExit:
            # Barge-in: the consumer stopped taking sentences. The turn is now
            # abandoned mid-stream, which is precisely the state that causes the
            # off-by-one, so mark it and let settle() clean up before the next.
            stats.interrupted = True
            raise
        except Exception:
            stats.interrupted = True
            raise


def _count_tool_uses(message) -> int:
    content = getattr(message, "content", None)
    if not isinstance(content, (list, tuple)):
        return 0
    return sum(1 for block in content if type(block).__name__ == "ToolUseBlock")
