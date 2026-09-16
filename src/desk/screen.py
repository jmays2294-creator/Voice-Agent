"""The screen: Rule 4.5's on-screen half.

Case material Desk must not read aloud gets its headline spoken and its detail
written here instead. Under launchd there is no TTY, so this file IS the
surface — it must exist in the shipping configuration, not only behind
--verbose.

Privileged, so it lives under state_dir() (mode 0600) via paths.screen_file(),
never signals_dir(): that directory is documented content-free and the owner
dashboard polls it.

Sanitises by Unicode general category rather than an enumerated denylist of
characters. Two prior passes at a denylist each missed a class of hostile
byte (ANSI introducers, then bidi overrides); a third would miss a fourth.
Category membership does not have that failure mode.
"""

from __future__ import annotations

import contextlib
import logging
import os
import unicodedata
from pathlib import Path

from . import paths

log = logging.getLogger("desk.screen")

#: Cc: control characters (ANSI escape introducers live here — ESC is Cc).
#: Cf: format characters, including every bidi override (U+202E and kin).
#: Zl / Zp: line and paragraph separators (U+2028 / U+2029), which are not
#: control or format characters but split a terminal line just the same.
_STRIP_CATEGORIES = frozenset({"Cc", "Cf", "Zl", "Zp"})

#: A screen entry is a headline and a sentence, not a document. Long enough
#: for a case caption and its context; short enough that a runaway string
#: cannot fill the pane or the disk.
MAX_LEN = 4000


def sanitize(text: str) -> str:
    """Strip every character shape hostile to a rendered terminal or pane,
    then cap the length. Oversize input is truncated, never refused — a long
    but honest string should still reach the screen."""
    cleaned = "".join(ch for ch in text if unicodedata.category(ch) not in _STRIP_CATEGORIES)
    return cleaned[:MAX_LEN]


def _tmp_path(path: Path) -> Path:
    return path.with_name(path.name + ".tmp")


def _atomic_write(path: Path, content: str) -> bool:
    """Write content to path via a temp file and an atomic replace, the same
    shape as signals._write_atomic. Never opens `path` itself for writing —
    so a symlink planted at the target is simply replaced, not followed. On
    any failure the staged temp file is removed rather than left behind for
    the next read to find half-written state."""
    tmp = _tmp_path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with open(fd, "w") as fh:
            fh.write(content)
        os.replace(tmp, path)
    except OSError:
        log.exception("screen: atomic write failed")
        with contextlib.suppress(OSError):
            tmp.unlink()
        return False
    return True


class Screen:
    """The on-screen half of Rule 4.5."""

    def __init__(self, verbose: bool = False) -> None:
        self.verbose = verbose

    def write(self, text: str) -> bool:
        """Write sanitised text to the screen file.

        Returns False on refusal, never on silent success: a non-empty input
        that sanitises to nothing is refused rather than written as an empty
        file that would report success while showing nothing. The caller
        still owes a spoken sentence either way — see Rule 4.5's producer.
        """
        cleaned = sanitize(text)
        if text and not cleaned:
            log.warning("screen.write refused: input sanitised to nothing")
            return False
        ok = _atomic_write(paths.screen_file(), cleaned)
        if ok and self.verbose:
            log.info("screen: %s", cleaned)
        return ok

    def clear(self) -> None:
        """Empty the surface. Privileged material must not outlive the
        session it belonged to."""
        _atomic_write(paths.screen_file(), "")


def read() -> str:
    """The current screen contents, or empty if nothing has been written."""
    try:
        return paths.screen_file().read_text()
    except OSError:
        return ""
