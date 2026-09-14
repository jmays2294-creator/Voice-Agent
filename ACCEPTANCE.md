# Acceptance

Every line from the brief, with honest status. **Nothing is marked done that
was not actually verified.**

This build ran in a Linux cloud container. Everything that is pure logic — the
guard, the policy, the sentence path, the drain, the redaction — is verified
here and the evidence is the test suite. Everything that needs Apple Silicon, a
microphone, an audio device, a screen lock or a pf table **cannot be verified
from here**, and is listed as such with the exact command that verifies it.

A green checkbox on an unverifiable line would be the most damaging thing in
this repository.

## Verified here

| | Line | Evidence |
|---|---|---|
| ✅ | `THREAT_MODEL.md` lists exactly three external hosts, each justified | `THREAT_MODEL.md`; `EGRESS_HOSTS` in `policy.py` |
| ✅ | Guard-hook adversarial suite passes: injected instruction in a file, in a web page, in a Supabase row — all denied and logged | `tests/test_guard_injection.py` — 42 cases through the real hook process |
| ✅ | `git push`, writes outside scratch, and any `main`-touching verb are denied by the hook, verified by test, not by reading the code | `tests/test_guard_policy.py`, `tests/test_guard_hook.py` — subprocess, exit code 2 |
| ✅ | Zero network calls carry Joel's speech or any transcript, asserted by a test | `test_no_module_that_touches_speech_can_reach_the_network` (AST-level) |
| ✅ | Barge-in twenty times, no desync, no one-turn-late answers | `test_twenty_barge_ins_never_desync`, against a fake that models the SDK's shared-stream semantics faithfully |
| ✅ | A denied action is spoken with its reason | `test_denials_are_queued_to_be_spoken` |
| ✅ | Zero absolute home paths — neither the macOS user-directory prefix nor the iCloud container appears anywhere; zero secret values | `test_zero_absolute_home_paths`, `test_zero_secret_values` — scan the committed tree |
| ✅ | Owner dashboard voice section: last session, p50 this week, refused actions, voice approvals | Branch `claude/owner-dashboard-voice-section` in `admin-thecompdesk` at `a2881a6`; `npm run build` (strict `tsc -b`) passes. See `dashboard/`. |
| ✅ | Model weights SHA-verified at boot | `tests/test_interlock_grant_weights.py`; `desk.weights.verify` raises rather than warning |
| ✅ | Screen-lock interlock implemented and fails safe | `test_a_daemon_that_cannot_tell_treats_the_screen_as_locked`, `test_nothing_resumes_when_the_screen_unlocks` |

Full launch sequence: [`LAUNCH.md`](LAUNCH.md).

## Needs the Mac — with the command that closes each line

| | Line | How to close it |
|---|---|---|
| ⬜ | Egress rules installed and verified — a fourth host is unreachable from the daemon | `sg _desk -c 'sh scripts/verify_egress.sh'`. Installation per `docs/EGRESS.md`. The fourth-host probe is the one that matters. |
| ⬜ | No audio file written anywhere during a full session (`fs_usage` capture attached) | `sh scripts/capture_fs_usage.sh`, hold a full conversation, then grep the capture for audio suffixes. Attach the capture here. |
| ⬜ | Mic verified closed at rest by a device-level check | `sh scripts/verify_mic_closed.sh` with the key released, then again with it held. It must appear only in the second. |
| ⬜ | Screen-lock interlock verified: locked = deaf and mute | Lock the screen, hold the key, speak. Nothing should be captured or spoken, and nothing should resume on unlock. State file reads `deaf`. |
| ⬜ | p50 ≤ 1.2s, p95 ≤ 1.8s over 20 turns, committed | `python3 scripts/bench.py --live`, then commit the regenerated `BENCH.md`. The committed file currently carries a banner saying its numbers are synthetic. |
| ⬜ | A voice approval appears in audit with `source='voice'` | **Both migrations are applied and verified against the live database** — RLS on, append-only, the WCB/SSN/risk/timing guards all refuse (tested in a rolled-back block, no rows left), `anon` cannot call the RPC, and the RPC returns clean nulls on empty tables. What remains is a real voice approval flowing through: approve one low-risk queue item by voice, then `desk-action audit.recent`. |
| ⬜ | The dashboard section renders against live data | Apply the two SQL files, merge `claude/owner-dashboard-voice-section`, then open `/metrics` as owner. The section is built and type-checked but has never rendered against real rows. |
| ⬜ | `uv.lock` hash-pinned | `uv lock` on the Mac and commit it. Not generated here: a lockfile resolved on Linux would pin the wrong wheels for Apple Silicon and would be worse than none. |
| ⬜ | Model weights pinned (not just verified) | `python3 scripts/pin_weights.py ~/.desk/models`, paste into `config/weights.sha256`, **then check each digest against the publisher's published digest**. Desk refuses to boot until this is done. |
| ⬜ | Survives sleep/wake and network loss, and says so rather than hanging | Sleep the Mac mid-session; pull the network mid-turn. Audit rows spool locally and replay (`Audit.flush_spool`), but the end-to-end behaviour is untested without the hardware. |

## Not met, by decision

| | Line | Status |
|---|---|---|
| ⚠️ | Private repo under `jmays2294-creator` | **`jmays2294-creator/Voice-Agent` is public.** The risk was put to Joel on 2026-09-14 and he chose to push to it anyway. Recorded in `docs/FINDINGS.md` item 1. No credential, host, project reference or account identifier is committed, and the build does not depend on the repo being public — flipping it to private later changes nothing except who can read the design. |
| ⬜ | Branch protection on `main`, 2FA enforced, signed commits, no Actions holding secrets, no third-party Apps | Unaffected by the visibility decision, and still to do in repository Settings. |

## Deliberately not built

- **Phase 5 (legal-work intents)** is designed (`docs/INTENTS.md`) and not
  enabled. It is gated behind Phase 4 acceptance, behind Rule 4.5, and behind
  `docs/FINDINGS.md` item 2 — the account-tier question governs whether
  privileged material belongs in a model exchange at all. Enabling it also
  requires widening `VOICE_SURFACE.md`, which is a deliberate act with its own
  threat-model entry, not a config change.
- **A cloud voice behind a flag.** Not built, and
  `tests/test_never.py::test_no_cloud_voice_service_anywhere_in_the_tree` fails
  the build if one appears.
