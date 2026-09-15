"""The screen surface.

Rule 4.5's other half: the headline is spoken, the detail is written here.
stdout only — no file, no network. A rewritable status line carries state,
what was heard and what was said; `write` prints a block of detail below it
and never overwrites what came before.

This module is deliberately dumb, matching signals.py: it holds nothing but
the length of the last status line, so it knows how much to blank before
redrawing it.
"""

from __future__ import annotations

import sys
from typing import TextIO


class Screen:
    def __init__(self, out: TextIO | None = None) -> None:
        self._out = out if out is not None else sys.stdout
        self._status_len = 0

    def status(self, state: str, heard: str = "", said: str = "") -> None:
        """Rewrite the status line in place: state, what was heard, what was said."""
        line = f"[{state}]"
        if heard:
            line += f"  heard: {heard}"
        if said:
            line += f"  said: {said}"
        pad = max(0, self._status_len - len(line))
        self._out.write("\r" + line + (" " * pad))
        self._out.flush()
        self._status_len = len(line)

    def write(self, text: str) -> None:
        """Print one block of written detail. Ends the status line first so
        detail is never clobbered by the next status redraw."""
        if not text:
            return
        if self._status_len:
            self._out.write("\n")
            self._status_len = 0
        self._out.write(text.rstrip("\n") + "\n")
        self._out.flush()
