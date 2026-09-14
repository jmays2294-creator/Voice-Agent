"""Per-turn web grants.

Rule 2: no web access in the voice session unless Joel explicitly asks in that
turn, and then only for that turn. The grant is written by the daemon after
hearing him ask, names a single host from the egress allowlist, and expires.

Deliberately literal. It matches an explicit request and nothing else — no
inference, no "he probably meant", no standing permission. If the match is
uncertain the answer is no, because the cost of a false positive is an open
egress channel during a turn that has just read untrusted text.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import time

from . import paths

#: Only hosts on the egress allowlist can ever be granted.
_PHRASES = {
    "github.com": re.compile(
        r"(?i)\b(?:look\s+(?:\w+\s+){0,2}up|check|fetch|pull\s+up|open|read|see)\b"
        r"[^.?!]{0,40}\bgithub\b"
    ),
}


def detect(transcript: str, allowed_hosts: tuple[str, ...]) -> frozenset[str]:
    """Hosts Joel actually asked for in this turn. Empty means no grant."""
    if not transcript:
        return frozenset()
    hosts = {h for h, pattern in _PHRASES.items()
             if h in allowed_hosts and pattern.search(transcript)}
    return frozenset(hosts)


def issue(hosts: frozenset[str], seconds: int = 90) -> None:
    if not hosts:
        return
    payload = {"hosts": sorted(hosts), "expires": time.time() + seconds}
    p = paths.web_grant_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with open(fd, "w") as fh:
        fh.write(json.dumps(payload))


def revoke() -> None:
    """Called at the end of every turn, unconditionally."""
    with contextlib.suppress(OSError):
        paths.web_grant_file().unlink(missing_ok=True)


def active() -> bool:
    return paths.web_grant_file().exists()
