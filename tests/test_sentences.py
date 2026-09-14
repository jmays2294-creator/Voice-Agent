"""Sentence boundaries. Getting these wrong is audible in both directions."""
import pytest

from desk.sentences import SentenceAccumulator, split_complete


def feed_all(chunks):
    acc = SentenceAccumulator()
    out = []
    for c in chunks:
        out.extend(acc.feed(c))
    return out, acc.pending


def test_plain_sentences_emit_as_they_complete():
    out, pending = feed_all(["Three lanes ran. ", "Lane A failed. ", "Nothing waits"])
    assert out == ["Three lanes ran.", "Lane A failed."]
    assert pending == "Nothing waits"


def test_a_sentence_split_across_deltas_emits_once_whole():
    acc = SentenceAccumulator()
    assert acc.feed("Three la") == []
    assert acc.feed("nes ra") == []
    assert acc.feed("n. ") == ["Three lanes ran."]


@pytest.mark.parametrize("text,expected", [
    ("Dr. Ruiz called. ", ["Dr. Ruiz called."]),
    ("The hearing is Sept. 3. ", ["The hearing is Sept. 3."]),
    ("See Ruiz v. Acme. ", ["See Ruiz v. Acme."]),
    ("Filed under W.C.L. 15. ", ["Filed under W.C.L. 15."]),
    ("A stale index.lock blocked it. ", ["A stale index.lock blocked it."]),
    ("It failed at 3.5 hours. ", ["It failed at 3.5 hours."]),
    ("J. Mays approved it. ", ["J. Mays approved it."]),
    ("No. 7 is next. ", ["No. 7 is next."]),
    ("Check e.g. lane A. ", ["Check e.g. lane A."]),
])
def test_abbreviations_do_not_split_a_sentence(text, expected):
    out, _ = feed_all([text])
    assert out == expected


def test_numbered_list_markers_do_not_split():
    out, _ = feed_all(["Two things.\n1. Kick lane A.\n2. Approve item twelve. "])
    assert out == ["Two things.", "1. Kick lane A.", "2. Approve item twelve."]


def test_questions_and_exclamations_are_boundaries():
    out, _ = feed_all(["Did it run? ", "It did! ", "Good"])
    assert out == ["Did it run?", "It did!"]


def test_closing_quote_after_terminal_punctuation():
    out, _ = feed_all(['He said "it failed." ', "Then it stopped. "])
    assert out == ['He said "it failed."', "Then it stopped."]


def test_flush_emits_the_unfinished_tail():
    """The filler before a tool call has no trailing whitespace to close it.
    Without this flush it sits buffered and arrives glued to the answer."""
    acc = SentenceAccumulator()
    assert acc.feed("Let me pull that up") == []
    assert acc.flush() == ["Let me pull that up"]
    assert acc.flush() == []
    assert acc.pending == ""


def test_flush_on_an_empty_buffer_says_nothing():
    assert SentenceAccumulator().flush() == []


def test_reset_drops_a_partial_utterance():
    acc = SentenceAccumulator()
    acc.feed("half a thou")
    acc.reset()
    assert acc.pending == "" and acc.flush() == []


def test_split_complete_returns_the_remainder_verbatim():
    done, rest = split_complete("One. Two. Thre")
    assert done == ["One.", "Two."] and rest == "Thre"
