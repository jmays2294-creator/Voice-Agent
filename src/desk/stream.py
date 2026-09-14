"""Reading the partial-message stream.

Kept separate from `brain` and free of SDK imports so the shapes can be tested
without a live session. The SDK has surfaced deltas in more than one shape
across versions, and a delta this misses is not an error — it is silence, which
is the hardest failure to notice.
"""

from __future__ import annotations

from typing import Any


def _as_dict(obj: Any) -> dict | None:
    if isinstance(obj, dict):
        return obj
    for attr in ("event", "raw", "data"):
        inner = getattr(obj, attr, None)
        if isinstance(inner, dict):
            return inner
    return None


def extract_text_delta(message: Any) -> str:
    """Return the incremental text in a stream event, or "" if it carries none."""
    direct = getattr(message, "text_delta", None)
    if isinstance(direct, str):
        return direct

    event = _as_dict(message)
    if not event:
        return ""
    if event.get("type") not in (None, "content_block_delta"):
        return ""
    delta = event.get("delta")
    if isinstance(delta, dict):
        if delta.get("type") in (None, "text_delta") and isinstance(delta.get("text"), str):
            return delta["text"]
        return ""
    if isinstance(event.get("text_delta"), str):
        return event["text_delta"]
    return ""


def is_content_block_stop(message: Any) -> bool:
    """A block ended.

    This is the flush point. When Claude says "let me pull that up" and then
    calls a tool, that filler has no trailing whitespace to close it as a
    sentence — without flushing here it sits buffered and arrives glued to the
    answer: a long silence, then two thoughts at once. Most of the felt
    responsiveness of the daemon is in noticing this event.
    """
    if getattr(message, "content_block_stop", None):
        return True
    event = _as_dict(message)
    return bool(event and event.get("type") == "content_block_stop")


def is_ping(message: Any) -> bool:
    if getattr(message, "ping", None):
        return True
    event = _as_dict(message)
    return bool(event and event.get("type") == "ping")


def message_kind(message: Any) -> str:
    """Classify a message without importing the SDK's types."""
    name = type(message).__name__
    if name in ("ResultMessage", "AssistantMessage", "UserMessage", "SystemMessage",
                "StreamEvent"):
        return name
    if isinstance(message, dict) and isinstance(message.get("type"), str):
        return message["type"]
    return name
