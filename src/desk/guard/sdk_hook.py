"""In-process form of the guard, for registration through the SDK.

Same policy, same decision, no subprocess on the latency path. The external
`hook.py` remains the reference form — it is what an auditor can run by hand
against a JSON payload, and what the adversarial suite exercises.
"""

from __future__ import annotations

import time
from typing import Any

from .. import paths
from .hook import _extra_egress_hosts, _log, _queue_spoken, _read_web_grant
from .policy import Context, Decision, decide


async def pre_tool_use(input_data: dict, tool_use_id: str | None,
                       context: Any) -> dict:
    """Return the hook JSON Claude Code honours. Fails closed on anything."""
    try:
        tool_name = input_data.get("tool_name")
        tool_input = input_data.get("tool_input")
        hosts, expires = _read_web_grant()
        ctx = Context(
            workspace_roots=paths.read_roots(),
            scratch_dir=paths.scratch_dir(),
            web_grant_hosts=hosts,
            web_grant_expires=expires,
            extra_egress_hosts=_extra_egress_hosts(),
        )
        decision = decide(tool_name, tool_input, ctx,
                          permission_mode=input_data.get("permission_mode"))
        _log({"at": time.time(), "tool": tool_name,
              "decision": "allow" if decision.allow else "deny",
              "rule": decision.rule, "reason": decision.reason,
              "action": decision.action, "risk": decision.risk,
              "input": tool_input if isinstance(tool_input, dict) else None})
        _queue_spoken(decision, tool_name or "unknown")
    except Exception as exc:
        decision = Decision(False, "guard.internal_error",
                            "the guard could not evaluate that call, so I refused it.")
        _log({"at": time.time(), "decision": "deny", "rule": "guard.internal_error",
              "error": f"{type(exc).__name__}: {exc}"})
        _queue_spoken(decision, "unknown")

    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow" if decision.allow else "deny",
            "permissionDecisionReason": decision.reason or decision.rule,
        }
    }
