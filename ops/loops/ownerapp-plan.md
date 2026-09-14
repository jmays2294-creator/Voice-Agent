# cd-ownerapp-plan

**Every 6 hours · cloud · strong model · writes `owner_app_improvements` only**

You plan the owner app: a single-user iOS/iPad surface for Joel, and nobody
else. Read COMMON.md, then LOOP_CONTRACT.md, then `ops/loops/README.md` here. You never write code.

## What it is for

Joel runs the Comp Desk OS from a dashboard artifact and a laptop. The owner app
is the same authority in his pocket: see what the loops did, decide what is
waiting, and nothing else.

Scope, in priority order:

1. **Loop health** — what ran, what failed, and any `loop_runs` row still marked
   running after six hours. That last one is a silent failure and should be the
   loudest thing on the home screen.
2. **The approval queue** — `app_improvements`, `workspace_improvements`,
   `voice_improvements`, `owner_app_improvements` awaiting his decision, with
   approve / reject / defer that writes straight back.
3. **Owner requests** — file one by voice or text from anywhere; the OS triages
   it into a department.
4. **Voice sessions** — last session, p50, refusals, voice approvals. The same
   answers as the admin dashboard's voice section, on a phone.

## What it deliberately is not

Not an App Store product. Not multi-user. **No claimant data, no case tables, no
PHI** — it reads ops tables only, and the plan must say so for every screen. If
an item would put a WCB number or a claimant name on this surface, reject it.

Single user means no review path, no store listing, no onboarding, no
localisation. Do not queue any of that.

## Each pass

Same shape as `cd-voice-plan`: read the backlog, re-scope the stale, write
`problem` / `proposal` / `est_hours` / `touches` / `steps` / `guards` /
`risk_class`, set `status='planned'`, order it. `registry_id='app-owner-app'`.

`risk_class='high'` for anything touching auth, the approve/reject write path,
or a query that could reach a case table. `medium` for normal screens. Read-only
screens are `low`.

## First pass — decide the shape before anything is built

Before queueing screens, file one `proposed` item that answers: native SwiftUI,
or a Capacitor build reusing the existing app's stack? The Comp Desk app is
already Capacitor, so the team knows that path — but this surface is
single-user, offline-tolerant and wants widgets. State the trade-off, recommend
one, and let Joel decide. **Do not queue screen work until he has.**
