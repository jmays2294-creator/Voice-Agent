# Desk — Supply Chain

The daemon pulls ML packages and model weights onto a machine that has
repository write access and keychain reach. That makes it a software
supply-chain target, and the dependency floor is deliberately small enough to
audit in one sitting.

## Rules

1. `uv.lock` is committed, hashes required, no unpinned ranges.
2. Model weights are pinned by SHA-256 in `config/weights.sha256` and verified
   after download. A weights file that does not match its recorded hash
   **aborts the boot** — it does not warn and continue.
3. No post-install scripts. The transitive tree is audited once and recorded
   below.
4. A dependency added after launch needs a recorded reason in this file. The
   floor stays permissive.

## The floor

| Package | Licence | Why it is here |
|---|---|---|
| `claude-agent-sdk` | MIT | The warm session. The agent itself. |
| `mlx-whisper` | MIT | Speech-in on the Apple Silicon GPU. |
| `faster-whisper` | MIT | Speech-in fallback where MLX is unavailable. |
| `sounddevice` | MIT | Microphone and output device. |
| `webrtcvad` | MIT | Trimming silence off a held-key capture. Not used to *trigger* capture — see below. |
| `numpy` | BSD-3 | Audio buffers. Transitive through everything above anyway. |
| `pyobjc-framework-AVFoundation` | MIT | `AVSpeechSynthesizer`. OS-native speech-out. |
| `pyobjc-framework-Quartz` | MIT | CoreGraphics event tap for the hold-to-talk key, and the screen-lock interlock. |

**`webrtcvad` is a trimmer, never a trigger.** It runs only on audio already
captured while the key was held. There is no code path in which VAD opens the
microphone — Rule 4 forbids it, and
`test_vad_is_a_trimmer_and_never_a_trigger` asserts it against the call graph
rather than the prose.

## Deliberate exclusions

| Not used | Why |
|---|---|
| **ElevenLabs**, and every other cloud TTS | Retains request history by default; Zero Retention Mode is enterprise-only. Every spoken sentence would be retained on a shared platform. Cut, with no flag left behind. |
| **Piper** | GPLv3. Not suitable for a commercial venture Joel intends to sell. |
| **pynput** | LGPLv3. A CoreGraphics event tap via `pyobjc-framework-Quartz` does the same job under MIT with fewer moving parts. |
| **Kokoro** | Available as an opt-in quality upgrade (`[kokoro]` extra), not a default. Apache-2.0 itself, but its `espeak-ng` phonemizer is GPL-3.0. It is invoked as a separate system binary rather than linked, which is fine for an internal tool — and is exactly the reason it stays opt-in rather than shipping on by default. |

## Model weights

Pinned in `config/weights.sha256`, verified by `desk.weights` at boot.

`whisper-small.en` is the default: it meets the ≤200ms transcription budget on
the GPU and is the smallest model that handles legal vocabulary acceptably.

The hashes must be filled in **on first download on the Mac**, from the
downloaded artifact, and then reviewed against the publisher's published
digest. `scripts/pin_weights.py` prints the digests to paste in.
`desk.weights.verify()` refuses to boot against an unpinned or mismatched file
— including the placeholder state, so an unfilled pin file fails loudly rather
than silently accepting anything.

## Auditing the tree

```
uv lock                      # hashes required, see pyproject
uv pip compile --generate-hashes
uv tree --depth 3            # record any addition here with its reason
```

Re-audit on every dependency change. The record of what was audited, when, and
by whom belongs in this file.

## Change log

| Date | Change | Reason |
|---|---|---|
| 2026-09-14 | Initial floor | Phase 0 |
| 2026-09-14 | ElevenLabs removed from the design | Retention on standard tiers; see THREAT_MODEL.md |
