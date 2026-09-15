"""The screen: the surface Rule 4.5 promises.

CLAUDE.md promises a screen for privileged case material Desk will not speak
aloud, and until this module existed no such surface did. Under launchd the
daemon has no terminal, so the screen is a file the daemon writes — the shape
signals.py already uses for state, and for the same reason: a surface a
visualiser can poll with no coupling to the daemon works whether or not
anyone is attached to a terminal.

Unlike signals.py this file carries privileged detail, not content-free
state (see paths.screen_file), so it lives under its own path in
state_dir() rather than signals_dir().

Screen.write sanitises at the sink rather than trusting a caller to have
validated first: it is reached both from the desk-action subprocess (argv
already checked by the guard) and in-process from mouth.case_material_guard,
where a headline built from tool output never passes through a validator at
all. A defence that only holds for one of two callers is not a defence.
"""

from __future__ import annotations

import contextlib
import os
import re

#: A screen is a glance, not a scroll.
MAX_LEN = 4000

#: C0 and C1 control characters (ESC included), which is how an ANSI escape
#: sequence gets started. Whatever renders this file later — a terminal under
#: --verbose today, a menu-bar window some day — must not be steerable by
#: content that started life in a Supabase row any user of the app can write.
_UNSAFE = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def sanitize(text: str) -> str:
    """Strip control characters and ANSI escape introducers, and bound the
    length. Applied here, at the sink, so every caller is covered rather than
    only the one a validator happens to see."""
    if not text:
        return ""
    return _UNSAFE.sub("", text)[:MAX_LEN]


class Screen:
    """The one surface, addressed by path. A desk-action subprocess call and
    an in-process mouth call must land in the same file, because paths.py
    hands out the same path either way — nothing here holds instance state
    that could make the two disagree."""

    def write(self, text: str) -> bool:
        """Write sanitised text to the screen file, atomically, mode 0600.

        Returns False if there was nowhere to write it. The caller must then
        say so out loud (Rule 4.5's honesty property) rather than dropping
        the detail silently — that silence is the failure this module exists
        to remove.
        """
        from . import paths

        cleaned = sanitize(text)
        path = paths.screen_file()
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with open(fd, "w") as fh:
                fh.write(cleaned)
            os.replace(tmp, path)
        except OSError:
            return False
        return True

    def read(self) -> str:
        """Current screen content, or "" if nothing has been written."""
        from . import paths

        try:
            return paths.screen_file().read_text()
        except OSError:
            return ""

    def clear(self) -> None:
        """Session end, or the room goes unconfirmed again. Case material
        must not sit on disk once nobody has confirmed it is safe to show."""
        from . import paths

        with contextlib.suppress(OSError):
            paths.screen_file().unlink(missing_ok=True)
