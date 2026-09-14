# Desk — Latency

Mode: **synthetic** · turns: 20 · generated 2026-09-14

> **These are not measurements.** This run used stubbed stages to prove the
> harness and the accounting on a machine that has no microphone, no Apple
> Silicon GPU and no audio device. The contract is unverified until
> `bench.py --live` has been run on the Mac and this file regenerated.

## Contract

Key release to first audible syllable: p50 ≤ 1200ms, p95 ≤ 1800ms.

| | p50 | p95 | budget | |
|---|---|---|---|---|
| **Key release to first audible syllable** | 911.0ms | 1022.9ms | 1200ms | — |

## Per stage

| Stage | p50 | p95 | mean | budget | n |
|---|---|---|---|---|---|
| Transcribe (mlx-whisper, small.en, GPU) | 146.2ms | 172.5ms | 144.3ms | 200ms | 20 |
| Claude first token (warm session) | 441.7ms | 536.0ms | 441.6ms | 600ms | 20 |
| First complete sentence | 267.5ms | 311.7ms | 256.9ms | 350ms | 20 |
| On-device TTS first audio | 62.3ms | 73.0ms | 61.3ms | 80ms | 20 |
| Device open (prewarmed) | 38.1ms | 45.0ms | 37.9ms | 50ms | 20 |

## Method

Twenty canned turns, warm session, prewarmed voice and transcriber.
Percentiles are nearest-rank over the twenty samples.

The microphone is never opened by the bench and no audio file is written.
Device-open is measured separately by `scripts/verify_mic_closed.sh`.

