# Voice + owner_app loop definitions

These are routine files for the Comp Desk OS, for the `voice` and `owner_app`
departments. They sit in this repo rather than `thecompdesk-app/ops/os/routines/`
because they describe the code beside them and should version with it — a change
to the guard rail and the rule about reviewing it land in the same commit.

## They are read third, not first

Every routine starts with the house preamble, which these do not repeat:

1. `thecompdesk-app` → `ops/os/routines/COMMON.md` — the preamble.
2. `thecompdesk-app` → `ops/os/LOOP_CONTRACT.md` — the mandatory rules: kill
   switch first, `loop_runs` row second and closed last, hard stops, sessions.
3. **Then** the file here that the routine names.

Where this repo and `LOOP_CONTRACT.md` disagree, the contract wins. Nothing
below is an exception to it — it is the part that only applies to a voice agent.

## House specifics these loops must honour

- `loop_runs.routine` = this routine's id (the file name here without `.md`),
  so the dashboard can show it running. `dept` is `voice` or `owner_app`,
  `host` is `cloud` or `mac`.
- **A queue is a view, never a predicate in one of these files.** The voice
  queues are `public.voice_gate_b_queue` and its complement; what no queue can
  see is `public.voice_stuck_items`, and every voice loop reads that one too.
  Twice a selection rule lived in prose here, twice a copy drifted from the
  other, and the second time a P0 guard change was invisible to review for 111
  minutes while every loop reported healthy. Do not transcribe a predicate out
  of `sql/004_voice_gate_flow.sql` into a routine; name the view.
- Supabase is project `ltibymvlytodkemdeeox` through the Supabase connector
  (`execute_sql`). **A routine without that connector cannot work** — it cannot
  read the kill switch or open a run row.
- At most 2 subagents (3 sessions including you).
- Finish with a short plain-English summary: what you did, what is waiting on
  whom, what failed.

## What only applies here

### 1. Stay in your lane

| Loop | May write |
|---|---|
| `*-plan` | the backlog table only. **Never touches code.** |
| `*-build` | a feature branch. Never `main`, never a merge, never a deploy. |
| `*-review` | gate columns and review notes. Never code. |
| `*-verify` | verification columns and artefacts. Never code. |

### 2. The guard rail is risk_class=high

In the voice repo these paths are the reason a permission-bypassed agent is
survivable at all:

```
src/desk/guard/**          config/weights.sha256
config/pf/**               CLAUDE.md
config/desk.toml (egress, model, stt/tts backend keys)
sql/004_voice_gate_flow.sql
```

The last one is there because it defines what reaches Gate B at all. A change
to it does not alter what Desk may do; it alters what gets looked at before
Desk may do it, which is the same thing one remove.

A change touching any of them is `risk_class='high'`, which means it never
auto-ships — a database trigger enforces that, not a convention — Gate B review
is mandatory and adversarial, and Joel merges it. **No loop merges a guard
change, ever.** Joel chose Gate B review over freezing the path, so a builder
may write one; it lands on a branch and stops there.

### 3. Tests are the gate, not an opinion

`python3 -m pytest tests/ -q` and `python3 -m ruff check src/ tests/ scripts/`
both green before a branch is pushed. That is Gate A, recorded in `gate_a`.
A builder that cannot reach green **deletes its branch and files what it
learned** rather than pushing red and hoping.

`tests/test_guard_injection.py` and `tests/test_never.py` encode the threat
model. Red there is a stop, never a flake.

### 4. The cloud has no microphone

Cloud loops have no mic, no audio device, no event tap, no screen lock and no
Metal. They can prove logic and nothing else.

**Never mark a voice item verified from a cloud loop.** Latency, barge-in, the
screen-lock interlock, mic-closed-at-rest and the no-audio-at-rest evidence all
belong to `mac-voice-verify`. A cloud loop claiming the latency contract is met
is worse than one that says nothing.

### 5. Cost shape

Planning and review run on the stronger model because judgement is the scarce
thing. Building runs on the cheaper one because the plan already made the
decisions. Do not escalate the model to get out of a hard spot — file the
difficulty and let the next plan pass scope it properly.
