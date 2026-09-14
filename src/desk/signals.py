"""State signals.

Tiny files a visualiser or the owner dashboard can poll without importing
anything from the daemon. Deliberately dumb: one word per file, written
atomically, no IPC, no coupling. If the daemon dies the last state is still on
disk and obviously stale.

State never carries content — only which of five things Desk is doing.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from . import paths

IDLE = "idle"
LISTENING = "listening"
THINKING = "thinking"
SPEAKING = "speaking"
DEAF = "deaf"        # screen locked: the interlock is holding

STATES = (IDLE, LISTENING, THINKING, SPEAKING, DEAF)


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with open(fd, "w") as fh:
        fh.write(text)
    os.replace(tmp, path)


def set_state(state: str) -> None:
    if state not in STATES:
        raise ValueError(f"unknown state {state!r}")
    paths.signals_dir().mkdir(parents=True, exist_ok=True)
    _write_atomic(paths.signals_dir() / "state", state)


def get_state() -> str:
    try:
        return (paths.signals_dir() / "state").read_text().strip() or IDLE
    except OSError:
        return IDLE


def set_metrics(**kv) -> None:
    """Timings only. Never content — see Rule 4."""
    paths.signals_dir().mkdir(parents=True, exist_ok=True)
    payload = {"at": time.time(), **{k: v for k, v in kv.items() if isinstance(v, (int, float))}}
    _write_atomic(paths.signals_dir() / "metrics.json", json.dumps(payload))


def get_metrics() -> dict:
    try:
        return json.loads((paths.signals_dir() / "metrics.json").read_text())
    except (OSError, ValueError):
        return {}
