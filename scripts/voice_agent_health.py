#!/usr/bin/env python3
"""voice-agent-health — the Phase 6 guard.

Four things, PASS/WARN/FAIL, non-zero on FAIL:

  1. the daemon is alive
  2. the interlock works
  3. a synthetic turn lands inside the latency contract
  4. the guard still refuses what it must

Report-only. It never edits, never deploys, never changes a setting.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from desk import interlock, paths, signals
from desk.config import load

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []

    def add(self, verdict: str, check: str, detail: str = "") -> None:
        self.rows.append((verdict, check, detail))

    @property
    def failed(self) -> bool:
        return any(v == FAIL for v, _, _ in self.rows)

    def render(self) -> str:
        out = ["voice-agent-health", "=" * 18, ""]
        for verdict, check, detail in self.rows:
            out.append(f"  {verdict:<4}  {check}" + (f" — {detail}" if detail else ""))
        out += ["", "FAIL" if self.failed else "OK"]
        return "\n".join(out)


def check_daemon(report: Report) -> None:
    state = signals.get_state()
    if state in (signals.IDLE, signals.LISTENING, signals.THINKING,
                 signals.SPEAKING, signals.DEAF):
        report.add(PASS, "daemon state signal", state)
    else:
        report.add(FAIL, "daemon state signal", f"unreadable: {state!r}")

    try:
        out = subprocess.run(["launchctl", "list", "com.thecompdesk.desk"],
                             capture_output=True, text=True, timeout=10, check=False)
        if out.returncode == 0:
            report.add(PASS, "LaunchAgent loaded")
        else:
            report.add(WARN, "LaunchAgent not loaded",
                       "run scripts/install_launchagent.sh")
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
    hook = Path(__file__).resolve().parents[1] / "src" / "desk" / "guard" / "hook.py"
    probes = [
        ("Bash", {"command": "git push origin main"}, 2, "git push refused"),
        ("Write", {"file_path": "/etc/hosts", "content": "x"}, 2,
         "write outside scratch refused"),
        ("Read", {"file_path": "~/TheCompDesk-Secrets/x"}, 2, "secrets refused"),
        ("WebFetch", {"url": "https://example.com"}, 2, "ungranted web refused"),
        ("Bash", {"command": "desk-action loop.status"}, 0, "named action permitted"),
    ]
    for tool, ti, want, label in probes:
        payload = json.dumps({"tool_name": tool, "tool_input": ti,
                              "cwd": str(paths.workspace_root()),
                              "permission_mode": "bypassPermissions"})
        out = subprocess.run([sys.executable, str(hook)], input=payload,
                             capture_output=True, text=True, timeout=30, check=False)
        ok = out.returncode == want
        report.add(PASS if ok else FAIL, label,
                   "" if ok else f"exit {out.returncode}, expected {want}")


def check_latency(report: Report, cfg) -> None:
    """A synthetic turn through the real sentence and diction path."""
    from desk.diction import for_speech
    from desk.sentences import SentenceAccumulator

    start = time.perf_counter()
    acc = SentenceAccumulator()
    spoken = []
    for chunk in ["Three lanes ran. ", "One failed on a stale index.lock. ",
                  "Nothing else waits on you."]:
        for sentence in acc.feed(chunk):
            spoken.append(for_speech(sentence))
    spoken.extend(for_speech(s) for s in acc.flush())
    elapsed_ms = (time.perf_counter() - start) * 1000

    ok = elapsed_ms < 50 and len(spoken) == 3
    report.add(PASS if ok else FAIL, "synthetic turn through sentence path",
               f"{elapsed_ms:.1f}ms, {len(spoken)} sentences")

    metrics = signals.get_metrics()
    last = metrics.get("total_ms")
    if last is None:
        report.add(WARN, "no recent live turn", "run bench.py --live on the Mac")
    elif last <= cfg.latency.p95_ms:
        report.add(PASS, "last live turn within contract", f"{last:.0f}ms")
    else:
        report.add(FAIL, "last live turn over contract",
                   f"{last:.0f}ms > {cfg.latency.p95_ms}ms")


def check_hygiene(report: Report) -> None:
    """Rule 4: no audio at rest, anywhere under the state directory."""
    state = paths.state_dir()
    if not state.exists():
        report.add(WARN, "no state directory yet", str(state))
        return
    audio = [p for p in state.rglob("*")
             if p.suffix.lower().lstrip(".") in
             {"wav", "aiff", "caf", "flac", "mp3", "m4a", "raw", "pcm"}]
    report.add(PASS if not audio else FAIL, "no audio at rest",
               "" if not audio else f"{len(audio)} file(s) found")

    log = paths.decision_log()
    if log.exists():
        mode = oct(log.stat().st_mode)[-3:]
        report.add(PASS if mode == "600" else FAIL, "decision log is owner-only", mode)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    cfg = load()
    report = Report()
    check_daemon(report)
    check_interlock(report)
    check_guard(report)
    check_latency(report, cfg)
    check_hygiene(report)

    if args.json:
        print(json.dumps([{"verdict": v, "check": c, "detail": d}
                          for v, c, d in report.rows], indent=2))
    else:
        print(report.render())
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
