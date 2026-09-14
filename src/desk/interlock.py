"""Screen-lock interlock.

If the screen is locked the daemon is deaf and mute. It does not queue, and it
does not resume mid-thought on unlock — a half-finished sentence about a case,
delivered to whoever walked up to the Mac, is the failure this prevents.

Implemented against CoreGraphics, which reports the session's lock state
directly. On any platform that cannot answer, the answer is "locked": a daemon
that cannot tell whether the room is safe does not speak.
"""

from __future__ import annotations

import platform
from collections.abc import Callable

_probe: Callable[[], bool] | None = None


def _darwin_probe() -> bool:
    from Quartz import CGSessionCopyCurrentDictionary  # type: ignore

    info = CGSessionCopyCurrentDictionary()
    if not info:
        return True
    # True when the screen is locked; absent on older systems, in which case
    # fall back to whether the session is on console.
    locked = info.get("CGSSessionScreenIsLocked")
    if locked is not None:
        return bool(locked)
    return not bool(info.get("kCGSSessionOnConsoleKey", True))


def _unavailable_probe() -> bool:
    return True


def _select() -> Callable[[], bool]:
    if platform.system() != "Darwin":
        return _unavailable_probe
    try:
        import Quartz  # type: ignore  # noqa: F401
    except ImportError:
        return _unavailable_probe
    return _darwin_probe


def set_probe(fn: Callable[[], bool] | None) -> None:
    """Override the lock probe. Tests and the health guard only — module state
    is the right seam here because the probe must be swappable from outside the
    process that reads it."""
    global _probe  # noqa: PLW0603
    _probe = fn


def is_locked() -> bool:
    fn = _probe or _select()
    try:
        return bool(fn())
    except Exception:
        return True


def can_listen() -> bool:
    return not is_locked()


def can_speak() -> bool:
    return not is_locked()
