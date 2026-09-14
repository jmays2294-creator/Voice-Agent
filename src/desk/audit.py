"""Audit.

Rule 7: every voice session writes a `loop_runs` row; every action the allowlist
permitted writes an audit row with `source='voice'`; every action the hook
denied is logged too. A silent denial teaches Joel nothing; a silent approval is
unreconstructable.

Uses `urllib` from the standard library rather than an HTTP client package —
this runs on a machine with repository write access, and the dependency floor
is part of the security posture.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import paths
from .guard.redact import redact, redact_obj

AUDIT_TABLE = "voice_audit"
RUNS_TABLE = "loop_runs"
SOURCE = "voice"


class CredentialUnavailable(RuntimeError):
    pass


def keychain_secret(service: str, account: str = "") -> str:
    """Read a credential from the macOS keychain at runtime.

    Nothing in this repository holds a secret value — only the name of one. The
    value is fetched here, used, and never logged, spoken, or written to a row.
    """
    cmd = ["security", "find-generic-password", "-w", "-s", service]
    if account:
        cmd += ["-a", account]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise CredentialUnavailable(f"could not reach the keychain for {service}") from exc
    if out.returncode != 0:
        raise CredentialUnavailable(
            f"no keychain item named {service}. Add it with: "
            f"security add-generic-password -s {service} -a desk -w"
        )
    return out.stdout.strip()


@dataclass
class Audit:
    """Ships rows to Supabase. Offline is a queue, never a lost row."""

    host: str
    service: str = "desk-supabase"
    timeout: float = 5.0
    _token: str | None = field(default=None, repr=False)
    session_id: str | None = None
    _run_id: str | None = None

    # --- transport -------------------------------------------------------

    def _auth(self) -> str:
        if self._token is None:
            self._token = os.environ.get("DESK_SUPABASE_KEY") or keychain_secret(self.service)
        return self._token

    def _post(self, table: str, row: dict, method: str = "POST",
              params: str = "") -> dict | None:
        if not self.host:
            self._spool(table, row)
            return None
        url = f"https://{self.host}/rest/v1/{table}{params}"
        body = json.dumps(redact_obj(row)).encode()
        try:
            token = self._auth()
        except CredentialUnavailable:
            self._spool(table, row)
            return None
        req = urllib.request.Request(url, data=body, method=method, headers={
            "apikey": token,
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        })
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read() or b"[]")
                return payload[0] if isinstance(payload, list) and payload else None
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            # Network loss is a queue, not a dropped audit row. Rule 7 does not
            # get suspended because the wifi dropped.
            self._spool(table, row)
            return None

    def _spool(self, table: str, row: dict) -> None:
        try:
            paths.log_dir().mkdir(parents=True, exist_ok=True)
            p = paths.log_dir() / "audit-spool.jsonl"
            line = json.dumps({"table": table, "row": redact_obj(row)},
                              separators=(",", ":"), default=str)
            with open(os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), "a") as fh:
                fh.write(line + "\n")
        except Exception:  # noqa: BLE001
            pass

    def flush_spool(self) -> int:
        """Replay queued rows. Called at boot and after network recovery."""
        p = paths.log_dir() / "audit-spool.jsonl"
        if not p.exists() or not self.host:
            return 0
        lines = [ln for ln in p.read_text().splitlines() if ln.strip()]
        sent, remaining = 0, []
        for ln in lines:
            try:
                item = json.loads(ln)
            except ValueError:
                continue
            before = p.stat().st_size
            result = self._post(item["table"], item["row"])
            if result is None and p.stat().st_size > before:
                remaining.append(ln)
            else:
                sent += 1
        p.write_text("\n".join(remaining) + ("\n" if remaining else ""))
        return sent

    # --- rows ------------------------------------------------------------

    def start_session(self, note: str = "") -> str | None:
        row = {
            "loop": "desk-voice",
            "status": "running",
            "started_at": _now(),
            "source": SOURCE,
            "notes": redact(note) if note else None,
        }
        result = self._post(RUNS_TABLE, row)
        self._run_id = (result or {}).get("id")
        return self._run_id

    def end_session(self, turns: int, error: str | None = None) -> None:
        row = {
            "status": "failed" if error else "passed",
            "finished_at": _now(),
            "notes": redact(error)[:500] if error else f"{turns} turns",
        }
        if self._run_id:
            self._post(RUNS_TABLE, row, method="PATCH", params=f"?id=eq.{self._run_id}")
        else:
            self._spool(RUNS_TABLE, {**row, "loop": "desk-voice", "source": SOURCE})

    def action(self, name: str, risk: str, asked: str, argv: list[str],
               outcome: str, changed: str | None = None) -> None:
        """One row per permitted action: what was asked, what ran, what changed."""
        self._post(AUDIT_TABLE, {
            "source": SOURCE,
            "at": _now(),
            "run_id": self._run_id,
            "action": name,
            "risk": risk,
            "asked": redact(asked)[:1000],
            "argv": redact_obj(argv),
            "outcome": outcome,
            "changed": redact(changed)[:1000] if changed else None,
            "decision": "allow",
        })

    def denial(self, tool: str, rule: str, reason: str, spoken: bool) -> None:
        self._post(AUDIT_TABLE, {
            "source": SOURCE,
            "at": _now(),
            "run_id": self._run_id,
            "action": tool,
            "risk": "denied",
            "asked": None,
            "outcome": rule,
            "changed": None,
            "decision": "deny",
            "reason": redact(reason)[:500],
            "spoken_aloud": spoken,
        })

    def ship_decision_log(self) -> int:
        """Ship the guard's local decision log, denials included, then truncate."""
        p = paths.decision_log()
        if not p.exists():
            return 0
        shipped = 0
        for line in p.read_text().splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("decision") == "deny":
                self.denial(rec.get("tool") or "unknown", rec.get("rule") or "",
                            rec.get("reason") or "", spoken=True)
                shipped += 1
        p.write_text("")
        return shipped


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def pending_denials() -> list[dict]:
    """Denials the guard queued that the mouth has not yet spoken."""
    p = paths.speak_queue()
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    p.write_text("")
    return out
