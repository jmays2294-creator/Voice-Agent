"""Spoken-delivery cleanup.

prompts/desk.md teaches Desk to write for a mouth. This is the mechanical
backstop for when it forgets: a synthesiser reads `**` aloud as "asterisk
asterisk", and one stray markdown table makes an answer unlistenable.

The character lives in prompts/desk.md. This file only handles the medium.
"""

from __future__ import annotations

import re

_CODE_FENCE = re.compile(r"```[\s\S]*?```")
_INLINE_CODE = re.compile(r"`([^`]*)`")
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_BARE_URL = re.compile(r"https?://\S+")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_BLOCKQUOTE = re.compile(r"^\s{0,3}>\s?", re.MULTILINE)
_RULE = re.compile(r"^\s{0,3}([-*_])\s*\1\s*\1[\s\1]*$", re.MULTILINE)
_BULLET = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)
_NUMBERED = re.compile(r"^\s*\d+[.)]\s+", re.MULTILINE)
_EMPHASIS = re.compile(r"(\*{1,3}|_{1,3})(?=\S)(.+?)(?<=\S)\1", re.DOTALL)
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)
_TABLE_SEP = re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]*$", re.MULTILINE)
_WS = re.compile(r"[ \t]{2,}")
_BLANKS = re.compile(r"\n{2,}")

#: Read aloud, not spelled out.
_SPOKEN_FORMS = {
    "WCB": "the Workers' Comp Board",
    "WCL": "the Workers' Comp Law",
    "ALJ": "the law judge",
    "IME": "an independent medical exam",
    "MMI": "maximum medical improvement",
    "SLU": "schedule loss of use",
    "PPD": "permanent partial disability",
    "LMA": "labor market attachment",
    "RPC": "the Rules of Professional Conduct",
    "PR": "pull request",
    "CI": "the test run",
    "p50": "median",
    "p95": "ninety-fifth percentile",
    "TTS": "speech",
    "STT": "transcription",
}

_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
         "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
         "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
         "eighty", "ninety"]


def number_to_words(n: int) -> str:
    """Small integers as words. Beyond a few thousand, digits read fine."""
    if n < 0:
        return "minus " + number_to_words(-n)
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ("" if n % 10 == 0 else "-" + _ONES[n % 10])
    if n < 1000:
        rest = n % 100
        return _ONES[n // 100] + " hundred" + ("" if rest == 0 else " " + number_to_words(rest))
    if n < 1_000_000:
        rest = n % 1000
        return (number_to_words(n // 1000) + " thousand"
                + ("" if rest == 0 else " " + number_to_words(rest)))
    return str(n)


def _speak_numbers(text: str) -> str:
    def repl(m: re.Match[str]) -> str:
        raw = m.group(0)
        digits = raw.replace(",", "")
        if not digits.isdigit() or len(digits) > 6:
            return raw
        return number_to_words(int(digits))
    return re.sub(r"\b\d{1,3}(?:,\d{3})+\b|\b\d+\b", repl, text)


def strip_markdown(text: str) -> str:
    """Remove the parts of markdown a synthesiser would read out loud."""
    out = _CODE_FENCE.sub(" ", text)
    out = _IMAGE.sub(r"\1", out)
    out = _LINK.sub(r"\1", out)
    out = _TABLE_SEP.sub("", out)
    out = _TABLE_ROW.sub(lambda m: m.group(0).strip().strip("|").replace("|", ", "), out)
    out = _RULE.sub("", out)
    out = _HEADING.sub("", out)
    out = _BLOCKQUOTE.sub("", out)
    out = _BULLET.sub("", out)
    out = _NUMBERED.sub("", out)
    out = _EMPHASIS.sub(r"\2", out)
    out = _INLINE_CODE.sub(r"\1", out)
    out = _BARE_URL.sub("a link", out)
    out = _WS.sub(" ", out)
    out = _BLANKS.sub("\n", out)
    return out.strip()


def for_speech(text: str, expand_numbers: bool = True) -> str:
    """The full pass: markdown out, acronyms and numbers into spoken forms."""
    out = strip_markdown(text)
    for abbr, spoken in _SPOKEN_FORMS.items():
        out = re.sub(rf"\b{re.escape(abbr)}\b", spoken, out)
    if expand_numbers:
        out = _speak_numbers(out)
    return out.strip()
