"""Sentence boundaries for a mouth that starts before the thought is finished.

Desk streams. It does not wait for the turn: text deltas accumulate here and a
sentence leaves as soon as one is complete, so synthesis starts while the model
is still writing. Getting the boundary wrong in either direction is audible —
too eager and Desk says "In re" and stops; too lazy and the first syllable
arrives late.
"""

from __future__ import annotations

import re

#: Tokens that end in a period without ending a sentence. Legal dictation is
#: full of them, which is why this list is longer than it would be elsewhere.
_ABBREVIATIONS = frozenset("""
mr mrs ms dr prof hon esq jr sr st ave rd blvd dept
no nos vs v et al etc eg ie cf ca approx
inc llc llp ltd co corp assn bros
jan feb mar apr jun jul aug sep sept oct nov dec
mon tue tues wed thu thurs fri sat sun
u.s u.s.c n.y n.y.s w.c.l a.d p.m a.m i.e e.g
wcb wcl alj ime lmw mmi ppd ptd slu tth
sec secs art arts para paras pp fig figs vol
""".split())

_MAX_ABBREV_LEN = max(len(a) for a in _ABBREVIATIONS)

#: A boundary candidate: terminal punctuation, optional closing quote/bracket,
#: then whitespace.
_BOUNDARY = re.compile(r'([.!?]+["\'”’)\]]?)(\s+)')

#: Trailing token immediately before the punctuation.
_LAST_WORD = re.compile(r"([A-Za-z][A-Za-z.]*)$")

#: Nouns that take a single-letter label. "Kick lane A." ends a sentence;
#: "J. Mays" does not. Without this, every answer naming a lane sat buffered
#: until the turn ended, which is exactly the dead air streaming exists to
#: avoid.
_LABELLED = frozenset("""
lane item option plan phase part section exhibit appendix schedule track
class type grade tier group batch queue column row step round version
""".split())


def _is_real_boundary(text: str, end: int) -> bool:
    """Is the terminal punctuation at `end` actually the end of a sentence?"""
    head = text[:end]
    stripped = head.rstrip('."\'”’)]!?')

    # A numbered list marker: "1." at the start of a line. Only at the start —
    # "set for Sept. 3." ends a sentence, and treating every trailing digit as a
    # marker left whole answers buffered until the turn ended.
    if stripped and stripped[-1].isdigit():
        line_start = head.rfind("\n") + 1
        if re.fullmatch(r"\s*\d{1,3}", head[line_start:len(stripped)]):
            return False

    m = _LAST_WORD.search(stripped)
    if m:
        word = m.group(1).lower().rstrip(".")
        if word in _ABBREVIATIONS:
            return False
        # A single letter is an initial ("J. Mays") unless it is a label on
        # one of the nouns above ("kick lane A.").
        if len(word) == 1:
            before = stripped[:m.start(1)].rstrip()
            prev = re.search(r"([A-Za-z]+)$", before)
            if not (prev and prev.group(1).lower() in _LABELLED):
                return False
        # Dotted acronym: "U.S.C." — the shape, not the membership.
        if "." in m.group(1) and len(word.replace(".", "")) <= 4:
            return False
    return True


def split_complete(text: str) -> tuple[list[str], str]:
    """Split `text` into complete sentences plus the unfinished remainder.

    The remainder is deliberately kept, never guessed at: it is whatever the
    model has not yet finished saying.
    """
    out: list[str] = []
    start = 0
    for m in _BOUNDARY.finditer(text):
        end = m.end(1)
        if not _is_real_boundary(text, end):
            continue
        piece = text[start:end].strip()
        if piece:
            out.append(piece)
        start = m.end(2)
    return out, text[start:]


class SentenceAccumulator:
    """Feed text deltas in, take complete sentences out.

    `flush()` is the non-obvious half. When Claude says "let me pull that up"
    and then calls a tool, that filler sits in the buffer with no trailing
    whitespace to close it. Flushing at `content_block_stop` is what makes it
    play *during* the tool run instead of arriving glued to the answer — a long
    silence followed by two thoughts at once. Most of the felt responsiveness
    of the whole daemon is in that one call.
    """

    def __init__(self) -> None:
        self._buf = ""

    def feed(self, delta: str) -> list[str]:
        if not delta:
            return []
        self._buf += delta
        done, self._buf = split_complete(self._buf)
        return done

    def flush(self) -> list[str]:
        """Emit whatever is buffered, finished or not."""
        tail = self._buf.strip()
        self._buf = ""
        return [tail] if tail else []

    @property
    def pending(self) -> str:
        return self._buf

    def reset(self) -> None:
        self._buf = ""
