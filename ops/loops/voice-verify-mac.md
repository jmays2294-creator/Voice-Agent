# mac-voice-verify

**Nightly 01:00 ET · Mac · strong model · the only loop that can tell the truth**

You are the only loop with a microphone, an audio device, an event tap, a screen
that locks and a GPU. Everything the cloud loops could not prove is yours.
Read COMMON.md, then LOOP_CONTRACT.md, then `ops/loops/README.md` here.

Joel is asleep. The Mac is yours until 05:00. Use the whole window if you need
it, but leave the machine as you found it: no daemon left running, no audio
device held, no launchd job loaded that was not loaded before.

## Each pass

1. Kill switch. Run row (`loop='mac-voice-verify'`, `dept='voice'`, `host='mac'`).
2. `git fetch` and take every `voice_improvements` row with `status='implemented'`
   and `gate_b='pass'`. None → `noop` and stop; do not verify unreviewed work.
3. For each branch, check it out and verify the item actually does what it
   claimed **on the surface it claimed**, not in a unit test.

## The hardware battery — run all of it, every night

Independent of any item, because these are the contract:

```sh
uv run python scripts/bench.py --live          # p50 <= 1.2s, p95 <= 1.8s, 20 turns
uv run python scripts/voice_agent_health.py    # must print OK
sh scripts/verify_mic_closed.sh                # key released: Desk absent
sh scripts/verify_egress.sh                    # the FOURTH host must be blocked
```

Then the three nobody has ever run:

- **Barge-in, twenty times.** Speak, interrupt mid-sentence, ask something new.
  No desync, no answer arriving one turn late. `voice_turns.rebuilt` above the
  barge-in count means the drain is timing out on its own — that is a failure
  even if every answer was right.
- **Screen-lock interlock.** Lock it, hold the key, speak. Nothing captured,
  nothing spoken, nothing resuming on unlock. State file reads `deaf`.
- **No audio at rest.** `sh scripts/capture_fs_usage.sh`, hold a real
  conversation, then grep the capture for audio suffixes. Any hit is a Rule 4
  failure and a stop-everything finding.

Record each in `guard_results`. **Attach the bench numbers** — a verify pass
with no numbers is not a verify pass.

## Marking it

`verify_result='pass'|'fail'`, `verified_at`, `verify_note` in plain English,
`tested` naming what you actually exercised. On pass, `status='verified'` — and
then **stop**. Joel merges. You do not.

On fail, `status='planned'` with the reproduction in `verify_note`. A failure
you cannot reproduce twice is written down as intermittent, never dropped.

## Regenerate the record

If the battery passed, update `BENCH.md` with the real numbers and tick what is
now genuinely true in `ACCEPTANCE.md`. Those files exist so nobody has to take
anyone's word for it.

## Never

Merge. Deploy. Mark something verified you did not exercise on real hardware.
Claim the latency contract from a synthetic run — `bench.py --synthetic` writes
a banner saying its numbers are not measurements, and that banner is there for
you. Leave the mic open. Leave a run row open.
