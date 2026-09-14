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

from . import paths
from .guard.redact import redact, redact_obj


def open_https(req, timeout: float):
    """Open a request, refusing anything that is not HTTPS.

    The URL is built from a configured host, so the scheme is fixed by
    construction — but `urlopen` honours `file:` and custom schemes, and a
    config value is one edit away from being somewhere it should not be. The
    scheme is checked at the point of use rather than assumed.
    """
    url = req.full_url if hasattr(req, "full_url") else str(req)
    if not url.startswith("https://"):
        raise ValueError(f"refusing a non-HTTPS request: {url[:40]}")
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 - scheme checked above


AUDIT_TABLE = "voice_audit"
TURNS_TABLE = "voice_turns"
RUNS_TABLE = "loop_runs"
SOURCE = "voice"

# Conventions read off the live loop_runs table, not guessed. Getting any of
# these wrong is a 400 on every insert, which — before the dead-letter handling
# below — would have spooled forever and looked exactly like a quiet daemon.
LOOP_NAME = "mac-desk-voice"     # mac-* is the prefix the Mac-hosted loops use
DEPT = "chief_of_staff"
HOST = "mac"
#: The status vocabulary loop_runs actually uses. Not passed/failed.
STATUS_RUNNING, STATUS_PASS, STATUS_FAIL, STATUS_NOOP = "running", "pass", "fail", "noop"


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
        # Fixed argv, no shell, no interpolation of anything the model touched.
        out = subprocess.run(cmd, capture_output=True, text=True,  # noqa: S603
                             timeout=10, check=False)
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
            with open_https(req, self.timeout) as resp:
                payload = json.loads(resp.read() or b"[]")
                return payload[0] if isinstance(payload, list) and payload else None
        except urllib.error.HTTPError as exc:
            if 400 <= exc.code < 500:
                # A rejected row will be rejected identically forever: a column
                # that does not exist, a status value outside the check
                # constraint, a revoked key. Spooling it would retry it every
                # boot and look exactly like a quiet daemon — which is the
                # silent-failure class this whole project exists to avoid. So it
                # goes to a dead-letter file that health.check reports as FAIL.
                self._reject(table, row, exc)
                return None
            self._spool(table, row)
            return None
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            # Network loss is a queue, not a dropped audit row. Rule 7 does not
            # get suspended because the wifi dropped.
            self._spool(table, row)
            return None

    def _reject(self, table: str, row: dict, exc) -> None:
        """Record a row the database refused. Loud, and never retried."""
        try:
            detail = exc.read().decode("utf-8", "replace")[:500]
        except Exception:
            detail = ""
        record = {"at": time.time(), "table": table, "status": getattr(exc, "code", None),
                  "detail": redact(detail), "row": redact_obj(row)}
        try:
            paths.log_dir().mkdir(parents=True, exist_ok=True)
            p = paths.dead_letter()
            with open(os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), "a") as fh:
                fh.write(json.dumps(record, separators=(",", ":"), default=str) + "\n")
        except Exception:
            pass

    def _spool(self, table: str, row: dict) -> None:
        try:
            paths.log_dir().mkdir(parents=True, exist_ok=True)
            p = paths.log_dir() / "audit-spool.jsonl"
            line = json.dumps({"table": table, "row": redact_obj(row)},
                              separators=(",", ":"), default=str)
            with open(os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), "a") as fh:
                fh.write(line + "\n")
        except Exception:
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
            "loop": LOOP_NAME,
            "dept": DEPT,
            "host": HOST,
            "status": STATUS_RUNNING,
            "started_at": _now(),
            "notes": redact(note) if note else None,
        }
        result = self._post(RUNS_TABLE, row)
        self._run_id = (result or {}).get("id")
        return self._run_id

    def end_session(self, turns: int, error: str | None = None,
                    actions: int = 0) -> None:
        """Close the row. A session with no turns is a noop, not a pass —
        cd-chief-of-staff reads these, and "ran and did nothing" and "answered
        nine questions" should not look the same."""
        if error:
            status = STATUS_FAIL
        elif turns == 0:
            status = STATUS_NOOP
        else:
            status = STATUS_PASS
        row = {
            "status": status,
            "finished_at": _now(),
            "items_in": int(turns),
            "items_out": int(actions),
            "notes": f"{turns} turn{'s' if turns != 1 else ''}",
            "error": redact(error)[:500] if error else None,
        }
        if self._run_id:
            self._post(RUNS_TABLE, row, method="PATCH", params=f"?id=eq.{self._run_id}")
        else:
            # No run id means the opening insert never landed. Record the close
            # anyway, with the identity columns it needs to stand alone.
            self._spool(RUNS_TABLE, {**row, "loop": LOOP_NAME, "dept": DEPT,
                                     "host": HOST, "started_at": _now()})

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

    def turn(self, *, total_ms: float, release_to_text_ms: float | None = None,
             first_token_ms: float | None = None, first_sentence_ms: float | None = None,
             first_audio_ms: float | None = None, sentences: int = 0,
             tool_calls: int = 0, barge_in: bool = False, rebuilt: bool = False) -> None:
        """One row per turn, for the dashboard's latency panel.

        Timings only. The row is built from keyword arguments that are all
        numbers or booleans, and the table it lands in has no text column, so
        there is no path by which a transcript could arrive here even by
        mistake. Rule 4 holds structurally rather than by care.
        """
        def ms(value: float | None) -> int | None:
            # A stage that did not happen stays null. Zero-filling would drag
            # the dashboard percentiles down and make the contract look met.
            return None if value is None else max(0, round(value))

        self._post(TURNS_TABLE, {
            "at": _now(),
            "run_id": self._run_id,
            "release_to_text_ms": ms(release_to_text_ms),
            "first_token_ms": ms(first_token_ms),
            "first_sentence_ms": ms(first_sentence_ms),
            "first_audio_ms": ms(first_audio_ms),
            "total_ms": ms(total_ms) or 0,  # never null: the table requires it
            "sentences": int(sentences),
            "tool_calls": int(tool_calls),
            "barge_in": bool(barge_in),
            "rebuilt": bool(rebuilt),
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
