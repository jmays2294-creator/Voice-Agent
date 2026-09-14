"""The warm session, the drain, and the off-by-one.

Barge-in is a headline feature, so the abandoned-turn path is hit on day one.
An answer that arrives one turn late is not a crash — it is a daemon that
confidently answers the previous question for the rest of the session.
"""

import pytest
from fake_sdk import FakeClient

from desk.brain import Brain, ModelPinError, require_pinned_model


def make_brain(**kw):
    client = FakeClient(**kw)
    brain = Brain(lambda: {"opts": True}, client_factory=lambda opts: client)
    return brain, client


async def take_all(brain, prompt):
    return [s async for s in brain.ask(prompt)]


async def take_one(brain, prompt):
    """Consume a single sentence and abandon the turn — barge-in."""
    agen = brain.ask(prompt)
    first = await agen.__anext__()
    await agen.aclose()
    return first


# --- model pinning --------------------------------------------------------

@pytest.mark.parametrize("alias", ["sonnet", "opus", "haiku", "default", "", "OPUS"])
def test_bare_aliases_are_refused(alias):
    with pytest.raises(ModelPinError):
        require_pinned_model(alias)


def test_a_pinned_id_is_accepted():
    assert require_pinned_model("claude-opus-5") == "claude-opus-5"


# --- streaming ------------------------------------------------------------

async def test_sentences_stream_before_the_turn_ends():
    brain, client = make_brain()
    await brain.connect()
    out = await take_all(brain, "what happened overnight?")
    assert out == ["Answer to what happened overnight part one.",
                   "Answer to what happened overnight part two."]
    assert brain.turn_consumed is True


async def test_filler_flushes_at_content_block_stop():
    """Without the flush this sits buffered and arrives glued to the answer:
    a long silence, then two thoughts at once."""
    brain, client = make_brain(scripts={"q": ["Let me pull that up"]})
    await brain.connect()
    assert await take_all(brain, "q") == ["Let me pull that up"]


# --- the off-by-one -------------------------------------------------------

async def test_an_abandoned_turn_is_marked_unconsumed():
    brain, client = make_brain()
    await brain.connect()
    await take_one(brain, "first")
    assert brain.turn_consumed is False
    assert client.buffered > 0


async def test_the_next_answer_is_not_one_turn_late():
    """The regression this whole file exists for."""
    brain, client = make_brain()
    await brain.connect()
    await take_one(brain, "first")
    out = await take_all(brain, "second")
    assert all("second" in s for s in out), f"answered the previous question: {out}"
    assert client.interrupts == 1


async def test_twenty_barge_ins_never_desync():
    """Barge-in twenty times, no desync, no one-turn-late answers."""
    brain, client = make_brain()
    await brain.connect()
    for i in range(20):
        await take_one(brain, f"q{i}")
        out = await take_all(brain, f"check{i}")
        assert all(f"check{i}" in s for s in out), f"desynced at iteration {i}: {out}"
        assert brain.turn_consumed is True
    assert client.interrupts == 20
    assert brain.rebuilds == 0


async def test_settle_is_a_no_op_on_a_clean_stream():
    brain, client = make_brain()
    await brain.connect()
    await take_all(brain, "clean")
    await brain.settle()
    assert client.interrupts == 0


async def test_a_drain_that_hangs_rebuilds_rather_than_answering_late():
    """The drain has a timeout for a reason: a stuck stream must cost the warm
    context, not correctness."""
    brain, client = make_brain(hang_on_drain=True)
    await brain.connect()
    await take_one(brain, "first")
    import desk.brain as brain_mod
    original = brain_mod.DRAIN_TIMEOUT
    brain_mod.DRAIN_TIMEOUT = 0.05
    try:
        await brain.settle()
    finally:
        brain_mod.DRAIN_TIMEOUT = original
    assert brain.rebuilds == 1
    assert brain.turn_consumed is True


async def test_drain_consumes_exactly_through_the_result_message():
    brain, client = make_brain()
    await brain.connect()
    await take_one(brain, "first")
    assert await brain.drain() is True
    assert client.buffered == 0


# --- stats ----------------------------------------------------------------

async def test_turn_stats_record_timings_not_content():
    brain, _ = make_brain()
    await brain.connect()
    await take_all(brain, "anything")
    stats = brain.last
    assert stats.first_token_ms is not None and stats.first_token_ms >= 0
    assert stats.first_sentence_ms is not None
    assert stats.sentences == 2 and stats.consumed is True
    assert not any(isinstance(v, str) for v in vars(stats).values())
