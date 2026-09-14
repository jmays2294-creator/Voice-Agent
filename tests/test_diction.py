"""A synthesiser reads `**` aloud. This is the backstop for when the model
forgets it is writing for a mouth."""
import pytest

from desk.diction import for_speech, number_to_words, strip_markdown


@pytest.mark.parametrize("md,expected", [
    ("**Overnight:** three lanes ran", "Overnight: three lanes ran"),
    ("# Heading\nbody", "Heading\nbody"),
    ("- one\n- two", "one\ntwo"),
    ("see `lane-a`", "see lane-a"),
    ("[the log](https://example.com/x)", "the log"),
    ("https://example.com/x", "a link"),
    ("> quoted", "quoted"),
    ("---", ""),
    ("_emphasis_ and __strong__", "emphasis and strong"),
    ("```\ncode\n```", ""),
])
def test_markdown_is_never_read_aloud(md, expected):
    assert strip_markdown(md) == expected


def test_tables_become_speakable_rows():
    out = strip_markdown("| lane | state |\n| --- | --- |\n| a | failed |")
    assert "|" not in out and "failed" in out


@pytest.mark.parametrize("n,words", [
    (0, "zero"), (7, "seven"), (12, "twelve"), (20, "twenty"),
    (21, "twenty-one"), (95, "ninety-five"), (100, "one hundred"),
    (142, "one hundred forty-two"), (1000, "one thousand"),
    (1200, "one thousand two hundred"),
])
def test_numbers_are_spoken_as_words(n, words):
    assert number_to_words(n) == words


def test_for_speech_expands_acronyms_and_numbers():
    out = for_speech("**3** lanes failed at MMI per WCL.")
    assert "three lanes failed" in out
    assert "maximum medical improvement" in out
    assert "the Workers' Comp Law" in out
    assert "*" not in out


def test_for_speech_leaves_long_digit_strings_alone():
    assert "1234567" in for_speech("case 1234567", expand_numbers=True)
