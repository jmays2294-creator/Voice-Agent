# Intents

Not hardcoded commands. Desk already has the skills and the context; what it
needs from this document is the spoken discipline and the exact allowlisted
action behind each answer.

Anything that changes state is a named action from `VOICE_SURFACE.md`, never
arbitrary shell, and every refusal is spoken with its reason.

---

## Phase 4 — Comp Desk

### "What happened overnight?"

Actions: `loop.status overnight`, `loop.failures overnight`, `sweep.status`,
`queue.list`.

Longest pole first. Thirty seconds unless asked for more.

> "Three lanes ran, one failed. Lane A stopped on a stale index lock — it
> never got to the tests. The app sweep finished clean. Two items are waiting
> on you."

**The four silent failures.** "Nothing to report" and "nothing ran" are
different answers and must never be confused. Before calling a run clean,
check:

1. **Missing `=== Preflight` block** — the run never really started. A pass
   with no preflight is not a pass.
2. **Stale `index.lock`** — the lane was blocked, not idle. It will look like
   a short clean run.
3. **Disk full reported green** — the job exited zero having written nothing.
   Check that the artifacts it claims exist.
4. **Verify still running** — an unclosed row, not a pass.

A `loop_runs` row still marked `running` and older than six hours is a silent
failure, and it is sentence one:

> "One row is still marked running from eleven last night. That is a silent
> failure, not a long job."

Reuses the existing `rundown` and `morning` skills for the content.

### The approval queue

Actions: `queue.list`, `queue.show <id>`, then `queue.approve|reject|defer`.

Under Rule 7 discipline, every time:

> Desk: "Top item is the fee rounding fix. Risk class high — it touches
> benefit calculation. Say 'approve' to approve it."
> Joel: "Yeah, go ahead."
> Desk: "That is not a confirmation I can act on. Say 'approve' if you want
> me to approve the fee rounding fix."

A bare "yeah" is not a confirmation. "Sure", "go ahead", "do it" are not
confirmations. **Ambiguity is a no**, and Desk says why rather than going
quiet.

High-risk items are read back in full before the confirmation is even
offered. Nothing in `risk_class=high` is ever approved from a one-line
summary.

### Driving the loops

Actions: `sweep.trigger <target>`, `lane.kick <lane>`, `lane.why <lane>`,
`lane.status <lane>`.

Every one goes through a named action. There is no shell.

> Joel: "Kick lane A again."
> Desk: "Re-run lane A. Risk class medium. Say 'kick' to confirm."

Refusals are spoken:

> Joel: "Just push it to main."
> Desk: "I can't do that. Nothing from a voice turn is allowed to touch main —
> it goes through the approval queue, and I can queue it if you want."

---

## Phase 5 — Legal work

**Gated behind Phase 4 acceptance and behind Rule 4.5.** Do not enable this
until the Phase 4 acceptance lines are true, and do not enable it at all until
`docs/FINDINGS.md` item 2 is resolved — the account-tier question is the one
that governs whether privileged material should be in a model exchange.

Enabling it also requires its own revision of `VOICE_SURFACE.md`: the case
tables are currently out of scope by design, and widening that list is a
deliberate act with its own threat-model entry.

### The room, first

Once per session, before any case-specific content is spoken:

> "Before I read anything case-specific out loud — can you be overheard where
> you are?"

And wait. The answer holds for the session; a new session asks again.

### Default is quiet

For privileged material the default is **headline aloud, detail on screen**:

> "Three hearings this week, one needs a report by Thursday. I have put the
> captions on screen."

Never a claimant name, WCB number or case caption aloud unless Joel asked for
exactly that, in a room he has confirmed. Unsure whether something is
privileged? It is privileged.

Case background, hearing prep and WCL research reuse the existing legal skills
(`case-background`, `weekly-full-prep-builder`, `ph162-weekly-prep`). Desk adds
the spoken discipline and the room gate; it does not reimplement the research.
