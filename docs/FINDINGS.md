# Findings for Joel

Surfaced, not acted on. Each needs a decision that is his, not the daemon's.

---

## 1. `jmays2294-creator/Voice-Agent` is a public repository

**Status: open, by decision.**

Rule 6 asks for a private repo under `jmays2294-creator`. This repository is
public. The risk was put to Joel on 2026-09-14 and he chose to push to it
anyway, so this is a recorded decision rather than an oversight.

What that means in practice: `THREAT_MODEL.md`, `VOICE_SURFACE.md`, the write
allowlist and the guard's rule identifiers are world-readable. They are a map
of how a machine holding privileged client material is defended. Nothing here
is a credential — `test_zero_secret_values` fails the build if one appears, and
no host, project reference, account identifier or email is committed — but the
design is legible to anyone.

Everything in this repository is written on the assumption that it is public.
If that assumption ever stops holding, it should be re-reviewed rather than
relaxed.

**Still available at any time:** repository → Settings → General → Danger Zone
→ Change visibility → Make private. Nothing in the build depends on the repo
being public.

Rule 6 also asks for: branch protection on `main`, 2FA enforced, signed commits
required, no GitHub Actions holding secrets, and no third-party GitHub Apps
installed. Those are unaffected by the visibility decision and still worth
doing.

**Naming.** Phase 0 proposed `thecompdesk-voice`. This build uses the existing
`Voice-Agent` repository instead, because that is the repository the session is
scoped to and the one the branch instruction names — creating a second repo
would have left the work in a place the session could not push to. If Joel
prefers the original name, renaming the repo in Settings preserves history and
redirects the remote.

---

## 2. Claude Code account tier is undetermined; transcript retention is at default

**Severity: high — this is the privileged-material question.**

Consumer (Pro/Max) and commercial terms differ on whether conversation content
may be used for model training. Desk's conversations are Comp Desk material and
will sometimes be client material under RPC 1.6.

The tier could not be read from the build session (`oauth_scope_insufficient`
on `user:profile`), and that session ran in a cloud container rather than on
the Mac in any case. `cleanupPeriodDays` was unset, i.e. the default retention
window for local transcripts.

**Fix:** run `scripts/posture_report.py` on the Mac. If it reports consumer
terms, move Desk to commercial terms before Phase 5. Set `cleanupPeriodDays`
explicitly and low for this project either way — Claude Code writes session
transcripts under `~/.claude/projects/` regardless of Desk keeping its own in
memory.

---

## 3. Two Supabase tables have Row Level Security disabled

**Severity: high, and independent of Desk.**

`public.union_campaign_batches` and `public._union_snapshot_tmp` have RLS
disabled. Both are fully exposed to the `anon` and `authenticated` roles —
anyone holding the anon key, which ships inside the iOS app, can read or modify
every row.

`_union_snapshot_tmp` (1 row) looks like a leftover temp table from a
migration.

Desk does not read either table. It is here because a table any app user can
write is exactly the injection source the threat model is built around, and
because it is a live exposure regardless of this project.

**Do not apply this blindly** — enabling RLS with no policies blocks all
access, including the loops that legitimately use these tables:

```sql
ALTER TABLE "public"."union_campaign_batches" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."_union_snapshot_tmp"   ENABLE ROW LEVEL SECURITY;
```

The likely shape is: drop `_union_snapshot_tmp` if it is dead, and give
`union_campaign_batches` service-role-only access (RLS on, no policies) to
match the other `*_config` and batch tables, which is what its writers already
use.

---

## 4. `~/TheCompDesk-Secrets` — 27 plaintext files

**Severity: medium, raised by this project's existence.**

Out of scope for this build, and Desk never reads that directory — the guard
refuses it by rule (`read.secret`) and the refusal is tested. But a plaintext
secrets directory on a machine now running an agent daemon is a materially
worse risk than it was when it was just sitting there.

They belong in the macOS keychain or a password manager. Desk reads any
credential it needs from the keychain at runtime and holds none.
