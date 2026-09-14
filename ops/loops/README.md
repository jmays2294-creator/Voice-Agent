# Loop contract

Every loop in the `voice` and `owner_app` departments obeys this. A loop that
skips any of it is a bug, not a variation.

The triggers do not carry instructions — they say "read
`ops/loops/<name>.md` and follow it". The prompt is therefore versioned,
reviewable in a diff, and changeable without touching a Routine.

## 1. The kill switch comes first

Before anything else:

```sql
select paused, paused_loops, reason from public.os_control where id = 1;
```

`paused = true`, or this loop's name in `paused_loops` → write nothing, open no
row, stop. Say why and exit. This is the first step of every Comp Desk loop and
the voice department is not special.

## 2. Open a run row, close it in a finally step

```sql
insert into public.loop_runs (loop, dept, host, status, started_at)
values ('<loop-name>', '<voice|owner_app>', '<cloud|mac>', 'running', now())
returning id;
```

Close it on every path — pass, fail, partial, noop — with `finished_at`,
`items_in`, `items_out`, and `error` when something broke. **A row left running
is a silent failure**, and `cd-chief-of-staff` reports it after six hours. Do
not leave one behind because the work was boring.

`noop` when the loop ran and had nothing to do. That is different from `pass`
and the distinction is the whole point.

## 3. Stay in your lane

| Loop | May write |
|---|---|
| `*-plan` | the backlog table only. **Never touches code.** |
| `*-build` | a feature branch. Never `main`, never a merge, never a deploy. |
| `*-review` | gate columns and review notes. Never code. |
| `*-verify` | verification columns and artefacts. Never code. |

## 4. The guard rail is risk_class=high

In the voice repo, these paths are the reason a permission-bypassed agent is
survivable at all:

```
src/desk/guard/**          config/weights.sha256
config/pf/**               CLAUDE.md
config/desk.toml (egress, model, stt/tts backend keys)
```

A change touching any of them is `risk_class = 'high'`, which means:

- it never auto-ships (a database trigger enforces this, not a convention),
- Gate B review is mandatory and is done by a **separate session on a stronger
  model**, adversarially,
- and Joel merges it. No loop merges a guard change, ever.

The build loop may still *write* one — Joel chose Gate B review over freezing
the path — but it lands on a branch and stops there.

## 5. Tests are the gate, not an opinion

`python3 -m pytest tests/ -q` and `python3 -m ruff check src/ tests/ scripts/`
must both pass before a branch is pushed. Gate A is exactly this, recorded in
`gate_a` / `gate_a_detail`. A build loop that cannot get to green **reverts its
branch and files what it learned** rather than pushing red and hoping.

The adversarial guard suite is not optional and is not slow. If
`tests/test_guard_injection.py` or `tests/test_never.py` go red, that is a stop,
not a flake.

## 6. What the cloud cannot do

Cloud loops have no microphone, no audio device, no event tap, no screen lock
and no Metal. They can prove logic and nothing else.

**Never mark a voice item verified from a cloud loop.** Latency, barge-in, the
screen-lock interlock, mic-closed-at-rest and the "no audio at rest" evidence
all belong to `mac-voice-verify`. A cloud loop claiming the latency contract is
met is worse than one that says nothing.

## 7. Write down what you learned

An item you could not finish gets `status` back to `planned` with a note saying
why, not a silent drop. A thing you noticed that is not this item's job goes to
`public.ideas` with `dept`. Research never goes straight to build.

## 8. Cost discipline

Planning and review run on the stronger model because judgement is the scarce
thing. Building runs on the cheaper one because the plan already made the
decisions. Do not escalate the model to get out of a hard spot — file the
difficulty and let the next plan pass scope it properly.
