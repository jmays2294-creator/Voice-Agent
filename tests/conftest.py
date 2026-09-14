import os
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from desk.guard.policy import Context  # noqa: E402


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """A throwaway workspace + state dir, wired through the same env overrides
    the daemon uses, so tests exercise the real path resolution."""
    ws = tmp_path / "Code"
    skills = tmp_path / "TheCompDesk-Skills"
    state = tmp_path / ".desk"
    scratch = state / "scratch"
    secrets = tmp_path / "TheCompDesk-Secrets"
    for d in (ws, skills, scratch, state / "log", secrets):
        d.mkdir(parents=True, exist_ok=True)
    (ws / "thecompdesk-app").mkdir(exist_ok=True)
    (secrets / "supabase.txt").write_text("service_role=REDACTED-IN-TEST\n")
    monkeypatch.setenv("DESK_WORKSPACE", str(ws))
    monkeypatch.setenv("DESK_STATE_DIR", str(state))
    monkeypatch.setenv("HOME", str(tmp_path))
    os.environ["HOME"] = str(tmp_path)
    return type("Sandbox", (), {
        "root": tmp_path, "ws": ws, "skills": skills, "state": state,
        "scratch": scratch, "secrets": secrets,
    })


@pytest.fixture
def ctx(sandbox):
    return Context(
        workspace_roots=(sandbox.ws, sandbox.skills, sandbox.scratch),
        scratch_dir=sandbox.scratch,
    )
