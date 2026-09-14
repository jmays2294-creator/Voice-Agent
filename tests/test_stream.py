"""Delta extraction across the shapes the SDK has used.

A delta this misses is not an error — it is silence, which is the hardest
failure to notice.
"""
from types import SimpleNamespace

import pytest

from desk.stream import extract_text_delta, is_content_block_stop, is_ping, message_kind


@pytest.mark.parametrize("message,expected", [
    (SimpleNamespace(text_delta="hello"), "hello"),
    (SimpleNamespace(event={"type": "content_block_delta",
                            "delta": {"type": "text_delta", "text": "hi"}}), "hi"),
    ({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "yo"}}, "yo"),
    (SimpleNamespace(event={"type": "content_block_delta", "text_delta": "flat"}), "flat"),
])
def test_text_deltas_are_found_in_every_shape(message, expected):
    assert extract_text_delta(message) == expected


@pytest.mark.parametrize("message", [
    SimpleNamespace(event={"type": "ping"}),
    SimpleNamespace(event={"type": "content_block_stop"}),
    SimpleNamespace(event={"type": "content_block_delta",
                           "delta": {"type": "thinking_delta", "thinking": "hmm"}}),
    SimpleNamespace(event={"type": "content_block_delta",
                           "delta": {"type": "input_json_delta", "partial_json": "{"}}),
    SimpleNamespace(), {}, None, "a string",
])
def test_non_text_events_yield_nothing(message):
    assert extract_text_delta(message) == ""


def test_content_block_stop_is_recognised():
    assert is_content_block_stop(SimpleNamespace(event={"type": "content_block_stop"}))
    assert is_content_block_stop({"type": "content_block_stop"})
    assert not is_content_block_stop(SimpleNamespace(event={"type": "ping"}))


def test_ping_is_liveness_not_a_timeout():
    assert is_ping({"type": "ping"})
    assert not is_ping({"type": "content_block_stop"})


def test_message_kind_classifies_without_importing_the_sdk():
    class ResultMessage:
        pass

    assert message_kind(ResultMessage()) == "ResultMessage"
    assert message_kind({"type": "system"}) == "system"
