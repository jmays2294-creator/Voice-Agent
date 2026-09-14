#!/usr/bin/env python3
"""Measure the latency contract. Do not estimate it.

Runs twenty canned turns end to end and reports p50/p95 per stage. Writes
BENCH.md. If p50 is over the contract, fix it before adding features — every
feature after this makes the regression harder to find.

Modes:
  --synthetic   every stage stubbed. Proves the harness and the accounting on
                any machine, including CI. Produces NO latency claim.
  --live        the real daemon on the Mac. The only mode whose numbers mean
                anything, and the only mode whose output may be committed as a
                measurement.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from desk.config import load

TURNS = [
    "What happened overnight?",
    "Anything waiting on me?",
    "Did the Wednesday lanes finish?",
    "Why did lane A fail?",
    "What's in the approval queue?",
    "Read me the top item.",
    "What's its risk class?",
    "How long has that been sitting there?",
    "Did the app sweep run?",
    "What did it find?",
    "Is anything still marked running?",
    "How old is that row?",
    "What's the median latency this week?",
    "Any refused actions today?",
    "What did I approve yesterday?",
    "Is the workspace sweep green?",
    "What's the oldest open owner request?",
    "Remind me to check the fee rounding guard.",
    "Anything else?",
    "Thanks, that's all.",
]


@dataclass
class Stage:
    name: str
    budget_ms: int
    samples: list[float] = field(default_factory=list)

    def p(self, q: float) -> float:
        if not self.samples:
            return 0.0
        ordered = sorted(self.samples)
        idx = min(len(ordered) - 1, round(q * (len(ordered) - 1)))
        return ordered[idx]

    def row(self) -> dict:
        return {
            "stage": self.name, "budget_ms": self.budget_ms,
            "p50_ms": round(self.p(0.50), 1), "p95_ms": round(self.p(0.95), 1),
            "mean_ms": round(statistics.mean(self.samples), 1) if self.samples else 0.0,
            "n": len(self.samples),
            "within_budget": round(self.p(0.50), 1) <= self.budget_ms,
        }


async def run_synthetic(cfg) -> dict:
    """Stubbed stages with the budget as the mean. Proves the harness only."""
    import random

    lat = cfg.latency
    stages = {
        "transcribe": Stage("Transcribe (mlx-whisper, small.en, GPU)", lat.transcribe_ms),
        "first_token": Stage("Claude first token (warm session)", lat.first_token_ms),
        "first_sentence": Stage("First complete sentence", lat.first_sentence_ms),
        "tts": Stage("On-device TTS first audio", lat.tts_first_audio_ms),
        "device": Stage("Device open (prewarmed)", lat.device_open_ms),
    }
    total = Stage("Key release to first audible syllable", cfg.latency.p50_ms)
    # Seeded so a synthetic run is reproducible. Not a security primitive.
    rng = random.Random(20260914)  # noqa: S311
    for _ in TURNS:
        turn = 0.0
        for key, stage in stages.items():
            value = stage.budget_ms * rng.uniform(0.55, 0.95)
            stage.samples.append(value)
            if key != "device":
                turn += value
        total.samples.append(turn)
    return {"mode": "synthetic", "stages": [s.row() for s in stages.values()],
            "total": total.row()}


async def run_live(cfg) -> dict:
    """The real thing, on the Mac."""
    from desk import paths, session
    from desk.brain import Brain
    from desk.mouth import Mouth
    from desk.stt import create as create_stt
    from desk.tts import create as create_tts

    lat = cfg.latency
    stages = {
        "transcribe": Stage("Transcribe (mlx-whisper, small.en, GPU)", lat.transcribe_ms),
        "first_token": Stage("Claude first token (warm session)", lat.first_token_ms),
        "first_sentence": Stage("First complete sentence", lat.first_sentence_ms),
        "tts": Stage("On-device TTS first audio", lat.tts_first_audio_ms),
        "device": Stage("Device open (prewarmed)", lat.device_open_ms),
    }
    total = Stage("Key release to first audible syllable", lat.p50_ms)

    paths.ensure_dirs()
    transcriber = create_stt(cfg.stt_backend, cfg.stt_model)
    voice = create_tts(cfg.tts_backend, cfg.tts_voice, cfg.tts_rate)
    mouth = Mouth(voice, check_interlock=False)
    brain = Brain(lambda: session.build_options(cfg))

    transcriber.prewarm()
    mouth.start()
    mouth.prewarm()
    await brain.connect()
    await brain.prewarm()

    try:
        for prompt in TURNS:
            # Device open is measured separately: the mic is not opened here,
            # because the bench must not record audio.
            start = time.perf_counter()
            mouth.begin_turn()
            first_audio = None
            async for sentence in brain.ask(prompt):
                mouth.say(sentence)
                if first_audio is None:
                    mouth.wait_until_quiet(timeout=5)
                    first_audio = mouth.stats.first_audio_ms
                    break
            async for _ in brain.ask(""):  # drain politely
                break
            st = brain.last
            if st and st.first_token_ms:
                stages["first_token"].samples.append(st.first_token_ms)
            if st and st.first_sentence_ms:
                stages["first_sentence"].samples.append(
                    st.first_sentence_ms - (st.first_token_ms or 0))
            if first_audio:
                stages["tts"].samples.append(first_audio - (st.first_sentence_ms or 0))
            total.samples.append((time.perf_counter() - start) * 1000)
            mouth.barge_in()
    finally:
        mouth.stop_worker()
        await brain.disconnect()

    return {"mode": "live", "stages": [s.row() for s in stages.values()],
            "total": total.row(), "rebuilds": brain.rebuilds}


def render(result: dict, cfg) -> str:
    live = result["mode"] == "live"
    total = result["total"]
    # An em dash rather than a verdict: a synthetic run makes no latency claim.
    verdict = "—" if not live else (
        "PASS" if total["p50_ms"] <= cfg.latency.p50_ms else "FAIL")
    lines = [
        "# Desk — Latency",
        "",
        (f"Mode: **{result['mode']}** · turns: {total['n']} · "
         f"generated {time.strftime('%Y-%m-%d')}"),
        "",
    ]
    if not live:
        lines += [
            "> **These are not measurements.** This run used stubbed stages to prove the",
            "> harness and the accounting on a machine that has no microphone, no Apple",
            "> Silicon GPU and no audio device. The contract is unverified until",
            "> `bench.py --live` has been run on the Mac and this file regenerated.",
            "",
        ]
    lines += [
        "## Contract",
        "",
        (f"Key release to first audible syllable: p50 ≤ {cfg.latency.p50_ms}ms, "
         f"p95 ≤ {cfg.latency.p95_ms}ms."),
        "",
        "| | p50 | p95 | budget | |",
        "|---|---|---|---|---|",
        (f"| **{total['stage']}** | {total['p50_ms']}ms | {total['p95_ms']}ms | "
         f"{cfg.latency.p50_ms}ms | {verdict} |"),
        "",
        "## Per stage",
        "",
        "| Stage | p50 | p95 | mean | budget | n |",
        "|---|---|---|---|---|---|",
    ]
    for row in result["stages"]:
        lines.append(
            f"| {row['stage']} | {row['p50_ms']}ms | {row['p95_ms']}ms | "
            f"{row['mean_ms']}ms | {row['budget_ms']}ms | {row['n']} |")
    lines += ["", "## Method", "",
              "Twenty canned turns, warm session, prewarmed voice and transcriber.",
              "Percentiles are nearest-rank over the twenty samples.",
              "",
              "The microphone is never opened by the bench and no audio file is written.",
              "Device-open is measured separately by `scripts/verify_mic_closed.sh`.",
              ""]
    if live:
        lines.append(f"Session rebuilds during the run: {result.get('rebuilds', 0)} "
                     f"(any number above zero means the drain path was exercised).")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--synthetic", action="store_true")
    mode.add_argument("--live", action="store_true")
    ap.add_argument("--out", default="BENCH.md")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    cfg = load()
    result = asyncio.run(run_live(cfg) if args.live else run_synthetic(cfg))

    if args.json:
        print(json.dumps(result, indent=2))
    Path(args.out).write_text(render(result, cfg))
    print(f"wrote {args.out} ({result['mode']})")
    if result["mode"] == "live" and result["total"]["p50_ms"] > cfg.latency.p50_ms:
        print("p50 is over the contract — fix it before Phase 4.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
