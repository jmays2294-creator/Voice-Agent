"""A faithful stand-in for the Agent SDK's shared message stream.

The bug this exists to catch is structural, not incidental: the SDK has ONE
message stream, `receive_response()` stops at the first `ResultMessage`, and
there is no query/response pairing. Abandon a turn mid-stream and its tail stays
buffered, so the next answer consumes the old turn's remainder and every answer
afterwards is one turn late — forever, silently.

So this fake models exactly that. It does not tidy up after an abandoned turn,
and a `Brain` that does not drain will fail these tests the same way the real
SDK would fail in Joel's kitchen.
"""

from __future__ import annotations

import asyncio
from collections import deque


class ResultMessage:
    def __init__(self, turn: int) -> None:
        self.turn = turn


class AssistantMessage:
    def __init__(self, turn: int, content=()) -> None:
        self.turn = turn
        self.content = list(content)


class StreamEvent:
    def __init__(self, event: dict) -> None:
        self.event = event


def _delta(text: str) -> StreamEvent:
    return StreamEvent({"type": "content_block_delta",
                        "delta": {"type": "text_delta", "text": text}})


def _block_stop() -> StreamEvent:
    return StreamEvent({"type": "content_block_stop"})


class FakeClient:
    """One stream, shared across turns, exactly like the real one."""

    def __init__(self, options=None, scripts=None, hang_on_drain: bool = False) -> None:
        self.options = options
        self.connected = False
        self.turn = 0
        self.queries: list[str] = []
        self.interrupts = 0
        self._stream: deque = deque()
        self._scripts = scripts or {}
        self._hang_on_drain = hang_on_drain

    async def connect(self, prompt=None) -> None:
        self.connected = True
        self._stream.clear()

    async def disconnect(self) -> None:
        self.connected = False
        self._stream.clear()

    async def interrupt(self) -> None:
        self.interrupts += 1
        # A real interrupt does not empty the stream; it ends the turn, and the
        # already-queued messages still have to be consumed.

    async def query(self, prompt: str, session_id: str = "default") -> None:
        self.turn += 1
        self.queries.append(prompt)
        # Strip terminal punctuation out of the echo: the splitter would
        # correctly break on a question mark embedded mid-sentence, which is
        # the fixture's problem, not the daemon's.
        tag = prompt.rstrip("?.! ") or "nothing"
        script = self._scripts.get(prompt) or [
            f"Answer to {tag} part one. ",
            f"Answer to {tag} part two. ",
        ]
        for piece in script:
            self._stream.append(_delta(piece))
        self._stream.append(_block_stop())
        self._stream.append(AssistantMessage(self.turn))
        self._stream.append(ResultMessage(self.turn))

    async def receive_messages(self):
        """The raw shared stream. Whatever is buffered comes out here."""
        while self._stream:
            if self._hang_on_drain:
                await asyncio.sleep(3600)
            yield self._stream.popleft()
            await asyncio.sleep(0)

    async def receive_response(self):
        """Stops at the first ResultMessage — including one left over from an
        abandoned turn, which is the whole bug."""
        while self._stream:
            message = self._stream.popleft()
            yield message
            if isinstance(message, ResultMessage):
                return
            await asyncio.sleep(0)

    @property
    def buffered(self) -> int:
        return len(self._stream)
