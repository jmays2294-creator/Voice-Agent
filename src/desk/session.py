"""Session options for the warm client.

Registers the guard as a `PreToolUse` hook — the same mechanism
`app-loop-dispatcher` uses to machine-enforce lane prohibitions — and narrows
the tool surface before the model ever sees it.

Two layers, deliberately:

  * `disallowed_tools` removes capabilities from the model's context entirely,
    so a poisoned instruction cannot even name a tool that exists.
  * the hook denies anything that gets through, because context narrowing is a
    convenience and the hook is the boundary.
"""

from __future__ import annotations

import sys
from pathlib import Path

from . import paths
from .config import Config

#: Removed from context outright. Not a substitute for the hook — a second wall.
DISALLOWED = [
    "WebSearch", "Task", "Agent", "KillShell", "BashOutput",
    "NotebookEdit", "SlashCommand",
]

CLAUDE_MD = Path(__file__).resolve().parents[2] / "CLAUDE.md"


def guard_command() -> list[str]:
    """How Claude Code should invoke the guard."""
    hook = Path(__file__).resolve().parent / "guard" / "hook.py"
    return [sys.executable, str(hook)]


def hook_settings() -> dict:
    """The settings.json-shaped hook registration, for the external form."""
    return {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "*",
                    "hooks": [{
                        "type": "command",
                        "command": " ".join(guard_command()),
                        "timeout": 10,
                    }],
                }
            ]
        }
    }


def build_options(cfg: Config):
    """Construct ClaudeAgentOptions for the voice session."""
    from claude_agent_sdk import ClaudeAgentOptions
    from claude_agent_sdk.types import HookMatcher

    from .guard.sdk_hook import pre_tool_use

    system_prompt = CLAUDE_MD.read_text() if CLAUDE_MD.exists() else None

    return ClaudeAgentOptions(
        model=cfg.model,
        system_prompt=system_prompt,
        cwd=str(paths.workspace_root()),
        # A permission prompt is fatal to a voice loop, which is exactly why the
        # hook below is the security boundary and not the system prompt.
        permission_mode="bypassPermissions",
        disallowed_tools=DISALLOWED,
        include_partial_messages=True,
        # Settings files are not loaded: the session's limits come from this
        # process, not from whatever happens to be on disk.
        setting_sources=[],
        hooks={"PreToolUse": [HookMatcher(hooks=[pre_tool_use])]},
    )
