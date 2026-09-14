# Owner dashboard — voice section

The voice section of the Owner Dashboard at `admin.thecompdesk.com`. It lives in
a different repository, so this directory is a pointer, not a copy — there is no
second version of the code here to drift out of sync.

**Branch:** [`claude/owner-dashboard-voice-section`](https://github.com/jmays2294-creator/admin-thecompdesk/tree/claude/owner-dashboard-voice-section)
in `jmays2294-creator/admin-thecompdesk`, at `a2881a6`.

Verified: `npm run build` (strict `tsc -b`, then vite) passes on that branch.

## The database side goes first

The section reads one RPC, and that RPC ships from **this** repository:

```sh
psql "$DATABASE_URL" -f sql/001_voice_audit.sql
psql "$DATABASE_URL" -f sql/002_voice_turns_and_dashboard.sql
```

Until they are applied the section renders a single explanatory card naming the
missing function, rather than a broken panel — so "not deployed yet" never reads
as "the daemon is dead".

Neither file has been run against the database yet. Both parse under the real
PostgreSQL grammar; that is syntax, not execution.

## What the branch changes

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
