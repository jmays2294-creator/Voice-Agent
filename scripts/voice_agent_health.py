#!/usr/bin/env python3
"""voice-agent-health — the Phase 6 guard.

Daemon alive, interlock working, the guard still refusing, a synthetic turn
inside the contract, and no audio at rest. PASS/WARN/FAIL, non-zero on FAIL.

The checks themselves live in `desk.health`, shared with the `health.check`
voice action so "is Desk well?" has one answer however it is asked.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from desk import health
from desk.config import load


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    report = health.run(load().latency.p95_ms)
    print(json.dumps(report.as_dict(), indent=2) if args.json else report.render())
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
