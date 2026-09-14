# Owner dashboard — voice section

The voice section of the Owner Dashboard at `admin.thecompdesk.com`. It lives in
a different repository (`jmays2294-creator/admin-thecompdesk`), so it ships from
here as a patch.

`owner-dashboard-voice-section.patch` is the whole change. The two new files
appear in it in full, so the patch is also the reviewable artifact — there is no
second copy to drift out of sync.

## Landing it

```sh
cd ~/Code/admin-thecompdesk
git checkout -b voice-section
git apply /path/to/Voice-Agent/dashboard/owner-dashboard-voice-section.patch
npm run build          # tsc -b strict, then vite
```

Verified: applies cleanly to a pristine checkout of `admin-thecompdesk` at
`717747e`, and `npm run build` passes from the patched tree.

The database side is separate, and goes first:

```sh
psql "$DATABASE_URL" -f sql/001_voice_audit.sql
psql "$DATABASE_URL" -f sql/002_voice_turns_and_dashboard.sql
```

Until those are applied the section renders a single explanatory card rather
than a broken panel — it names the missing function specifically, so "not
deployed yet" never reads like "the daemon is dead".

## What it changes

| File | |
|---|---|
| `src/lib/voiceMetrics.ts` | **new** — types, the single RPC call, and the rule-name labels |
| `src/routes/OwnerMetricsVoice.tsx` | **new** — the section |
| `src/routes/OwnerMetrics.tsx` | +7/−5 — imports and renders it |
| `src/design-system/primitives/Card.tsx` | +6 — `SectionTitle` moves here |

`SectionTitle` was a local helper in `OwnerMetrics.tsx`. Two files now render
sections, so it moved into the design system rather than being duplicated. That
is the only change to existing behaviour, and it is a move, not a rewrite.

## Conventions it follows

Taken from `OwnerMetrics.tsx`, which is explicit about them:

- **Single data source.** One `SECURITY DEFINER` RPC, `is_owner()` gated. The
  nav entry and route guard stay cosmetic; the RPC's `42501` is the boundary.
  No direct table reads from the screen, ever.
- **Fail loud.** A failed fetch surfaces the real error and keeps the last good
  read on screen, marked stale. Never zero-filled — zeros here would read as
  "the voice agent did nothing", which is indistinguishable from "the voice
  agent is dead" and from "you lost owner access".
- Poll every 30s, skip hidden tabs, discard responses that arrive after the
  window changed.

It owns its own RPC and its own poll, and sits outside the parent's `data &&`
guard: if `owner_dashboard_metrics` is down, that is not a reason to hide
whether the voice daemon is alive.

## Reading order

Deliberate, and not the order the data arrives in:

1. **Is it alive** — last session, its age, whether it closed. A run still
   marked `running` after six hours is a silent failure and gets the loudest
   treatment on the page.
2. **Is anything trying things it should not** — refusals, split into
   adversarial (something reached for a dangerous verb) and routine (the agent
   reached for a capability it does not have). Only the first is worth a look,
   and the section says which is which rather than showing one number.
3. **Is it inside the contract** — p50 and p95 against 1.2s and 1.8s, plus the
   per-stage breakdown so you can see which stage is the pole. Under twenty
   turns it says so: that is a reading, not a verdict.
4. **What did it change** — actions by name, approvals, high-risk approvals.

A dashboard that leads with latency buries the sentence that matters.

## What it cannot show

There is no transcript on this screen and no way to put one there. `voice_turns`
has no text column at all, and the RPC selects counts, millisecond figures and
guard rule names. The daemon composes audit rows from the action name and its
validated arguments; a dictated note's body goes only to the table Joel reads it
from. See `THREAT_MODEL.md` and `sql/002_voice_turns_and_dashboard.sql`.
