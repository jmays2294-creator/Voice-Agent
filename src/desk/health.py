"""Daemon self-check.

Shared by `scripts/voice_agent_health.py` (the Phase 6 guard) and by the
`health.check` voice action, so "is Desk well?" has one answer however it is
asked. Report-only: nothing here edits, deploys, or changes a setting.

Deliberately does not touch the network. A health check that needs Supabase
cannot tell you the network is down.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from . import interlock, paths, signals

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"

_AUDIO_SUFFIXES = {"wav", "aiff", "caf", "flac", "mp3", "m4a", "raw", "pcm"}

#: Five probes the guard must still refuse (or permit). If the boundary stopped
#: holding, nothing else on this list matters.
_GUARD_PROBES: tuple[tuple[str, dict, int, str], ...] = (
    ("Bash", {"command": "git push origin main"}, 2, "git push refused"),
    ("Write", {"file_path": "/etc/hosts", "content": "x"}, 2, "write outside scratch refused"),
    ("Read", {"file_path": "~/TheCompDesk-Secrets/x"}, 2, "secrets refused"),
    ("WebFetch", {"url": "https://example.com"}, 2, "ungranted web refused"),
    ("Bash", {"command": "desk-action loop.status"}, 0, "named action permitted"),
)


@dataclass
class Check:
    verdict: str
    name: str
    detail: str = ""


class Report:
    def __init__(self) -> None:
        self.checks: list[Check] = []

    def add(self, verdict: str, name: str, detail: str = "") -> None:
        self.checks.append(Check(verdict, name, detail))

    @property
    def failed(self) -> bool:
        return any(c.verdict == FAIL for c in self.checks)

    def as_dict(self) -> dict:
        return {
            "ok": not self.failed,
            "checks": [{"verdict": c.verdict, "check": c.name, "detail": c.detail}
                       for c in self.checks],
        }

    def spoken(self) -> str:
        """One sentence, for the mouth. Leads with the answer."""
        bad = [c for c in self.checks if c.verdict == FAIL]
        warn = [c for c in self.checks if c.verdict == WARN]
        if bad:
            first = bad[0]
            rest = f" and {len(bad) - 1} other problem{'s' if len(bad) > 2 else ''}" \
                if len(bad) > 1 else ""
            return f"Not well. {first.name} failed{rest}."
        if warn:
            noun = "things" if len(warn) > 1 else "thing"
            return f"Working, with {len(warn)} {noun} to note: {warn[0].name}."
        return "All clear."

    def render(self) -> str:
        out = ["voice-agent-health", "=" * 18, ""]
        for c in self.checks:
            out.append(f"  {c.verdict:<4}  {c.name}" + (f" — {c.detail}" if c.detail else ""))
        out += ["", "FAIL" if self.failed else "OK"]
        return "\n".join(out)


def check_daemon(report: Report) -> None:
    state = signals.get_state()
    if state in signals.STATES:
        report.add(PASS, "daemon state signal", state)
    else:
        report.add(FAIL, "daemon state signal", f"unreadable: {state!r}")
    try:
        out = subprocess.run(["launchctl", "list", "com.thecompdesk.desk"],  # noqa: S607
                             capture_output=True, text=True, timeout=10, check=False)
        if out.returncode == 0:
            report.add(PASS, "LaunchAgent loaded")
        else:
            report.add(WARN, "LaunchAgent not loaded", "run scripts/install_launchagent.sh")
    except (OSError, subprocess.SubprocessError):
        report.add(WARN, "launchctl unavailable", "not a Mac?")


def check_interlock(report: Report) -> None:
    """The interlock must refuse when it cannot tell, not assume it is safe."""
    interlock.set_probe(lambda: (_ for _ in ()).throw(RuntimeError("probe failed")))
    try:
        safe = interlock.is_locked() is True
    finally:
        interlock.set_probe(None)
    report.add(PASS if safe else FAIL, "interlock fails safe",
               "" if safe else "a daemon that cannot tell must not speak")
    report.add(PASS, "interlock live reading",
               "locked" if interlock.is_locked() else "unlocked")


def check_guard(report: Report) -> None:
    """The guard is the security boundary. If it stopped refusing, nothing
    downstream matters."""
    hook = Path(__file__).resolve().parent / "guard" / "hook.py"
    for tool, tool_input, want, label in _GUARD_PROBES:
        payload = json.dumps({"tool_name": tool, "tool_input": tool_input,
                              "cwd": str(paths.workspace_root()),
                              "permission_mode": "bypassPermissions"})
        # Fixed argv: this interpreter and a path inside the package. The
        # payload goes on stdin, never into the command line.
        out = subprocess.run([sys.executable, str(hook)], input=payload,  # noqa: S603
                             capture_output=True, text=True, timeout=30, check=False)
        ok = out.returncode == want
        report.add(PASS if ok else FAIL, label,
                   "" if ok else f"exit {out.returncode}, expected {want}")


def check_latency(report: Report, p95_budget_ms: int = 1800) -> None:
    """A synthetic turn through the real sentence and diction path."""
    import time

    from .diction import for_speech
    from .sentences import SentenceAccumulator

    start = time.perf_counter()
    acc = SentenceAccumulator()
    spoken: list[str] = []
    for chunk in ["Three lanes ran. ", "One failed on a stale index.lock. ",
                  "Nothing else waits on you."]:
        spoken.extend(for_speech(s) for s in acc.feed(chunk))
    spoken.extend(for_speech(s) for s in acc.flush())
    elapsed_ms = (time.perf_counter() - start) * 1000

    ok = elapsed_ms < 50 and len(spoken) == 3
    report.add(PASS if ok else FAIL, "synthetic turn through sentence path",
               f"{elapsed_ms:.1f}ms, {len(spoken)} sentences")

    last = signals.get_metrics().get("total_ms")
    if last is None:
        report.add(WARN, "no recent live turn", "run bench.py --live on the Mac")
    elif last <= p95_budget_ms:
        report.add(PASS, "last live turn within contract", f"{last:.0f}ms")
    else:
        report.add(FAIL, "last live turn over contract",
                   f"{last:.0f}ms > {p95_budget_ms}ms")


def check_hygiene(report: Report) -> None:
    """Rule 4: no audio at rest, anywhere under the state directory."""
    state = paths.state_dir()
    if not state.exists():
        report.add(WARN, "no state directory yet", str(state))
        return
    audio = [p for p in state.rglob("*")
             if p.suffix.lower().lstrip(".") in _AUDIO_SUFFIXES]
    report.add(PASS if not audio else FAIL, "no audio at rest",
               "" if not audio else f"{len(audio)} file(s) found")
    log = paths.decision_log()
    if log.exists():
        mode = oct(log.stat().st_mode)[-3:]
        report.add(PASS if mode == "600" else FAIL, "decision log is owner-only", mode)

    # A row the database refused will be refused identically forever. It is a
    # schema or credential problem wearing the costume of a quiet daemon.
    rejected = paths.dead_letter()
    if rejected.exists() and rejected.stat().st_size > 0:
        n = len([x for x in rejected.read_text().splitlines() if x.strip()])
        report.add(FAIL, "audit rows the database refused",
                   f"{n} in {rejected.name} — these are NOT retried; read the file")
    else:
        report.add(PASS, "no audit rows refused")


def run(p95_budget_ms: int = 1800) -> Report:
    report = Report()
    check_daemon(report)
    check_interlock(report)
    check_guard(report)
    check_latency(report, p95_budget_ms)
    check_hygiene(report)
    return report
