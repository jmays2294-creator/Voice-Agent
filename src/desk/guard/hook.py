"""PreToolUse hook: the process that actually says no.

Registered the same way `app-loop-dispatcher` registers its lane guard, so the
mechanism is one Joel already runs. Claude Code hands this process the tool call
on stdin and honours what it prints.

Two properties matter more than anything else in this file:

  1. **It fails closed.** Claude Code treats a non-zero exit that is not 2 as
     non-blocking — the tool call proceeds. So every exception, every malformed
     input, every unexpected state exits 2. A guard that crashes open is not a
     guard.
  2. **It never reads tool output.** It sees the call, not the result. Nothing a
     poisoned README, web page or database row says can reach this decision.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

if __package__ in (None, ""):  # direct invocation as a script
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from desk import paths
from desk.guard.policy import Context, Decision, decide
from desk.guard.redact import redact_obj

_EXIT_ALLOW = 0
_EXIT_DENY = 2  # the only exit code that reliably blocks


def _emit(decision: Decision) -> None:
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow" if decision.allow else "deny",
            "permissionDecisionReason": decision.reason or decision.rule,
        }
    }
    sys.stdout.write(json.dumps(payload))
    sys.stdout.flush()


def _log(record: dict) -> None:
    """Append one redacted decision record. Logging must never block a denial,
    so every failure here is swallowed — the exit code still stands."""
    try:
        d = paths.log_dir()
        d.mkdir(parents=True, exist_ok=True)
        os.chmod(d, 0o700)
        line = json.dumps(redact_obj(record), separators=(",", ":"), default=str)
        p = paths.decision_log()
        with open(os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), "a") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def _queue_spoken(decision: Decision, tool_name: str) -> None:
    """A silent denial teaches Joel nothing. Queue the reason for the mouth."""
    if decision.allow:
        return
    try:
        rec = {"at": time.time(), "kind": "denial", "tool": tool_name,
               "rule": decision.rule, "say": decision.spoken}
        p = paths.speak_queue()
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), "a") as fh:
            fh.write(json.dumps(redact_obj(rec), separators=(",", ":")) + "\n")
    except Exception:
        pass


def _read_web_grant() -> tuple[frozenset[str], float]:
    """Read the per-turn web grant, if the daemon wrote one.

    The grant is data written by the daemon after hearing Joel ask for a
    specific source out loud. It names hosts and an expiry; anything malformed
    is treated as no grant at all, because the safe reading of a broken grant is
    that there isn't one."""
    try:
        raw = paths.web_grant_file().read_text()
        data = json.loads(raw)
        hosts = data.get("hosts") or []
        if not isinstance(hosts, list):
            return frozenset(), 0.0
        clean = frozenset(h.lower() for h in hosts if isinstance(h, str) and h)
        expires = float(data.get("expires") or 0.0)
        return clean, expires  # noqa: TRY300
    except Exception:
        return frozenset(), 0.0


def _extra_egress_hosts() -> frozenset[str]:
    """The project's Supabase host, named (not secret) and supplied by config."""
    host = os.environ.get("DESK_SUPABASE_HOST", "").strip().lower()
    return frozenset({host}) if host else frozenset()


def build_context(payload: dict) -> Context:
    hosts, expires = _read_web_grant()
    return Context(
        workspace_roots=paths.read_roots(),
        scratch_dir=paths.scratch_dir(),
        web_grant_hosts=hosts,
        web_grant_expires=expires,
        extra_egress_hosts=_extra_egress_hosts(),
    )


def run(payload: dict) -> tuple[Decision, dict]:
    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    cwd_raw = payload.get("cwd")
    cwd = Path(cwd_raw) if isinstance(cwd_raw, str) and cwd_raw else None
    ctx = build_context(payload)
    decision = decide(tool_name, tool_input, ctx, cwd=cwd,
                      permission_mode=payload.get("permission_mode"))
    record = {
        "at": time.time(),
        "session": payload.get("session_id"),
        "tool": tool_name,
        "decision": "allow" if decision.allow else "deny",
        "rule": decision.rule,
        "reason": decision.reason,
        "action": decision.action,
        "risk": decision.risk,
        # The call, never the result. Kept for reconstruction, redacted on write.
        "input": tool_input if isinstance(tool_input, dict) else None,
    }
    return decision, record


def main(argv: list[str] | None = None) -> int:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        if not isinstance(payload, dict):
            raise TypeError("hook payload was not an object")  # noqa: TRY301
        decision, record = run(payload)
    except Exception as exc:
        fallback = Decision(
            False, "guard.internal_error",
            "the guard could not evaluate that call, so I refused it.",
        )
        _log({"at": time.time(), "decision": "deny", "rule": "guard.internal_error",
              "error": f"{type(exc).__name__}: {exc}"})
        _queue_spoken(fallback, "unknown")
        _emit(fallback)
        return _EXIT_DENY

    _log(record)
    _queue_spoken(decision, record.get("tool") or "unknown")
    _emit(decision)
    return _EXIT_ALLOW if decision.allow else _EXIT_DENY


if __name__ == "__main__":
    raise SystemExit(main())
