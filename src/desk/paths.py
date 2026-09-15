"""Runtime paths.

Nothing here is a literal home directory. Every absolute path is derived at
runtime, so the repository contains no machine-identifying string and a clone on
another Mac works unchanged.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Environment overrides, so tests and the bench can point Desk at a sandbox.
_ENV_STATE = "DESK_STATE_DIR"
_ENV_WORKSPACE = "DESK_WORKSPACE"


def home() -> Path:
    return Path(os.path.expanduser("~"))


def workspace_root() -> Path:
    """The code workspace Desk may read. Defaults to the usual Code directory."""
    override = os.environ.get(_ENV_WORKSPACE)
    if override:
        return Path(override).expanduser().resolve(strict=False)
    return (home() / "Code").resolve(strict=False)


def skills_root() -> Path:
    return (home() / "TheCompDesk-Skills").resolve(strict=False)


def state_dir() -> Path:
    """Everything Desk writes at runtime. Mode 0700, never committed."""
    override = os.environ.get(_ENV_STATE)
    base = Path(override).expanduser() if override else home() / ".desk"
    return base.resolve(strict=False)


def scratch_dir() -> Path:
    """The only place the model may write a file."""
    return state_dir() / "scratch"


def models_dir() -> Path:
    """Model weights Desk verifies AND loads. Those must be the same directory:
    hashing a file you do not open is theatre."""
    return state_dir() / "models"


def signals_dir() -> Path:
    return state_dir() / "signals"


def screen_file() -> Path:
    """Privileged detail written for Rule 4.5 — headline aloud, detail on
    screen. Deliberately not under signals_dir(): that directory is
    documented content-free and the owner dashboard polls it, while this
    file carries case material and must never become something a dashboard
    can read."""
    return state_dir() / "screen"


def log_dir() -> Path:
    return state_dir() / "log"


def decision_log() -> Path:
    """Append-only JSONL of every guard decision, allow and deny alike."""
    return log_dir() / "decisions.jsonl"


def dead_letter() -> Path:
    """Rows the database refused. A 4xx never succeeds on replay, so these are
    recorded loudly rather than retried forever. health.check reports a
    non-empty file as a FAIL."""
    return log_dir() / "audit-rejected.jsonl"


def speak_queue() -> Path:
    """Denials the daemon has not yet spoken."""
    return state_dir() / "speak-queue.jsonl"


def web_grant_file() -> Path:
    """Present only during the single turn in which Joel asked for the web."""
    return state_dir() / "web-grant"


def ensure_dirs() -> None:
    for d in (state_dir(), scratch_dir(), signals_dir(), log_dir()):
        d.mkdir(parents=True, exist_ok=True)
        os.chmod(d, 0o700)


def read_roots() -> tuple[Path, ...]:
    """What the model may read. Wide, but enumerated."""
    roots = [workspace_root(), skills_root(), scratch_dir()]
    return tuple(r for r in roots if r)
