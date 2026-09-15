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
```

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

## Working on this repo from a Cowork session

Three things about a Cowork session on the Mac that are not obvious and have each
already cost something. All verified 2026-09-15.

### The Mac shell is a Linux VM, not macOS

`device_bash` does **not** run on macOS. It is a Linux aarch64 VM with the connected
folders bind-mounted under `$HOME/mnt/`. `uname -a` says
`Linux claude 6.8.0 ... aarch64`; `launchctl`, `pmset` and `sw_vers` are all absent.

So anything macOS-only has to be run by Joel in Terminal.app:

- **`scripts/install_mac_loops.sh`.** It computes `REPO` from its own location, which
  in that VM resolves to `/sessions/<session-id>/mnt/Code/Voice-Agent` — a per-session
  mount path that disappears when the session ends. Running it there would write
  plists into the VM's own LaunchAgents directory, pointing at a path that will not
  exist, and `launchctl` would fail anyway. Two silent failures stacked.
- **`sudo` anything**, including `pmset`. The shell is non-interactive.

Before promising macOS work in a Cowork session, run `uname -s`.

`uv lock` is the exception that proves the rule: it is safe to *check* from anywhere
because `uv.lock` is a **universal** lockfile — it always carries every platform
(~158 darwin and ~264 linux wheel refs here). There is no darwin-only state to reach.
What matters is that `mlx-metal` pins `macosx_*_arm64` wheels only and `mlx` gates it
behind `sys_platform == 'darwin'`. Generate it on the Mac anyway, so a no-op result
from the target machine confirms it.

### Every git write through the bridge strands a `.git/*.lock`

The bridge mount cannot unlink its own lock files. A single `git status` leaves a
zero-byte `.git/index.lock`; a commit leaves that plus `HEAD.lock`. The *next* git
command then dies with `Unable to create '.git/index.lock': File exists` — which is
the total-stop failure mode already recorded for the launchd loops, except here the
cause is the bridge rather than a crash.

A Cowork session cannot delete them either. It can only `mv` them aside, which is a
workaround, not a fix.

**So: git writes on this repo belong in Terminal, not in a Cowork session.** Reading
is fine. If a Cowork session must commit, it has to clear the stranded locks
afterwards or it has broken git for whoever touches the repo next.

### zsh does not strip inline `#` comments

This one destroyed `.git` on 2026-09-15. An annotated command was pasted into an
interactive zsh prompt:

    rm -rf ~/Code/_to_delete          # 4 zero-byte lock files I moved out of .git

zsh passed every word after the `#` to `rm` as an argument, including `.git`, while
the shell was `cd`'d into the repo root. The bogus arguments did not exist and `-f`
ignored them; `.git` did exist. The working tree survived and the repo was rebuilt
from `origin`, losing only an unpushed commit.

**Never put an inline `#` comment on a command meant to be pasted into this shell.**
Put the explanation on its own line above it. This applies to anything handed to Joel
and to anything a loop writes into a runbook.
