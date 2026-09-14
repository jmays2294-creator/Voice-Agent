# Desk

A voice front end for the Comp Desk operating system. Joel holds a key, speaks,
and a Claude session with real tool access answers out loud in about a second.

Everything about speech happens on the Mac. Nothing Joel says leaves the
machine as audio or as text; the only thing that crosses the network is the
model exchange itself.

## Read these first

| | |
|---|---|
| [`THREAT_MODEL.md`](THREAT_MODEL.md) | Every third party the running system touches, what it would see, what it retains. Three hosts. |
| [`VOICE_SURFACE.md`](VOICE_SURFACE.md) | What is in scope, what is deliberately not, and the exact write allowlist. |
| [`SUPPLY_CHAIN.md`](SUPPLY_CHAIN.md) | The dependency floor and why each package is on it. |
| [`docs/FINDINGS.md`](docs/FINDINGS.md) | Five things that need Joel's decision, not the daemon's. |
| [`LAUNCH.md`](LAUNCH.md) | The launch runbook for the Mac, gate by gate. |
| [`ACCEPTANCE.md`](ACCEPTANCE.md) | The acceptance list, line by line, with honest status. |
| [`dashboard/`](dashboard/) | The owner dashboard voice section — it lives in `admin-thecompdesk`; this points at the branch. |

## The shape of it

```
key down  ─▶ ptt ─▶ ears (in-memory buffer)
key up    ─▶ transcribe on-device ─▶ brain (warm session)
                                       │
                            sentences ─┴─▶ mouth ─▶ on-device synthesis
                                       │
                          every tool call ─▶ guard ─▶ allow or refuse aloud
```

Six modules, each runnable from the command line:

| Module | Job |
|---|---|
| `ptt` | Hold-to-talk. The only thing that opens the microphone. |
| `ears` | Ring buffer, silence trim, transcribe, free the buffer. |
| `brain` | One warm session. Streams sentences; owns drain and interrupt. |
| `mouth` | Sentence queue to on-device synthesis. Cut in under 100ms. |
| `signals` | Five state words on disk, so a visualiser needs no coupling. |
| `main` | Loop, prewarm, interlock, crash recovery. |

## The guard is the point

The session runs with permissions bypassed, because a permission prompt is
fatal to a voice loop. That makes `desk/guard/` the security boundary — not the
system prompt, which is a suggestion to a model that an injected instruction is
actively trying to override.

- **Wide read, narrow write.** Reads anything in the workspace minus a
  credential denylist. Writes only through seventeen named actions.
- **No shell.** `Bash` is refused unless it is exactly one `desk-action` from
  the allowlist with validated arguments.
- **Deny by default.** A capability that is not on the allowlist does not
  exist.
- **Fails closed.** Claude Code treats a non-zero exit that is not 2 as
  non-blocking, so every exception exits 2.
- **Never sees tool output.** There is no text an injection can put in front of
  it.

```sh
python3 -m pytest tests/           # 299 tests, guard first
python3 scripts/voice_agent_health.py
```

## Running it

```sh
uv sync --extra mlx --extra macos
python3 -m desk.main --check       # boot checks, no microphone
sh scripts/install_launchagent.sh
```

Before the first real run, on the Mac:

```sh
python3 scripts/posture_report.py        # account tier and retention
python3 scripts/pin_weights.py ~/.desk/models
sh scripts/verify_egress.sh              # the fourth host must be unreachable
sh scripts/verify_mic_closed.sh
python3 scripts/bench.py --live          # regenerates BENCH.md
```

## Latency

Key release to first audible syllable: p50 ≤ 1.2s, p95 ≤ 1.8s. Measured, not
estimated — see [`BENCH.md`](BENCH.md).

What buys it: one warm session for the whole daemon; streaming sentences
instead of awaiting the turn; flushing at `content_block_stop` so filler plays
during a tool run; GPU transcription on Apple Silicon; and prewarming
everything at boot.

Removing the cloud voice made this faster, not slower — it was about 250ms of
the budget.
