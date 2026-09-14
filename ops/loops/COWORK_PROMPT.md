# Cowork prompt — set up the voice department

Paste everything between the rules into a Claude Cowork session on the Mac.

---

Set up the two new Comp Desk OS departments on this Mac. Everything you need is
in `~/Code/Voice-Agent` (branch `main`) — clone it from
`https://github.com/jmays2294-creator/Voice-Agent` if it is not there.

Read `ops/loops/ROUTINES.md` first. It has the exact values. Do not invent any.

## Part 1 — five cloud Routines

Create these five Routines on my claude.ai account. Each one needs the
**Supabase connector**, the repository `jmays2294-creator/Voice-Agent`, and the
environment **Comp Desk OS**.

| Routine | Model | Cron (UTC) |
|---|---|---|
| `cd-voice-plan` | Opus | `0 */4 * * *` |
| `cd-voice-build` | Sonnet | `0 */2 * * *` |
| `cd-voice-review` | Opus | `0 */2 * * *` |
| `cd-ownerapp-plan` | Opus | `0 */6 * * *` |
| `cd-ownerapp-build` | Sonnet | `0 */2 * * *` |

The prompt for each is in `ops/loops/ROUTINES.md` — use it verbatim.

**Try `/schedule` first.** It is the CLI path and it works from a terminal
session on this Mac. If it is unavailable here, do not fight it: open
`claude.ai/code/routines` in Chrome and drive the form, or walk me through it
field by field and tell me exactly what to type.

**Two things that will bite you, both already verified:**

1. **A Routine without the Supabase connector is useless.** These loops read a
   kill switch and write `loop_runs` rows through `execute_sql`. Without the
   connector they fire, find no database, and fail — or worse, look like they
   ran. The MCP `create_trigger` tool **cannot attach connectors on this
   account** ("the connectors parameter is not available for this
   organization"), so if that is the only path you have, stop and tell me
   rather than creating five broken Routines. Creating from the web form
   attaches every connected connector by default, which is what we want here.
2. **Trim the connectors to Supabase only.** The form attaches everything —
   Gmail, Vercel, Drive, Stripe. Every tool on an attached connector is usable
   without asking during an unattended run. A build loop has no business
   holding a send button. Remove all of them except Supabase.

The form only offers hourly/daily/weekdays/weekly. Pick the nearest, create,
then set the real cron with `/schedule update` from a terminal.

After creating `cd-voice-plan`, **Run now** and watch that one run before
creating the rest. It is the loop that decides what everything else builds.

## Part 2 — two Mac loops

```sh
cd ~/Code/Voice-Agent && git pull
sh scripts/install_mac_loops.sh
```

These run at 01:00 and 03:00 ET and need the Mac awake:

```sh
sudo pmset repeat wakeorpoweron MTWRFSU 00:55:00
```

Confirm both are loaded with `launchctl list | grep thecompdesk.os`.

## Part 3 — two small things only this Mac can do

```sh
cd ~/Code/Voice-Agent
uv lock          # a lockfile resolved anywhere else pins the wrong wheels
```

Commit `uv.lock` and mark item "uv.lock, hash-pinned" verified in
`voice_improvements`.

Then check the model weights against the publisher, which has never been done —
right now they only prove the file has not changed since I downloaded it:

```sh
curl -sI https://huggingface.co/mlx-community/whisper-small.en-mlx/resolve/52a88bf6e98b114a210c21bb83e22d6e1505cb73/weights.npz | grep -i x-linked-etag
```

That must equal the `weights.npz` digest in `config/weights.sha256`. If it does
not, stop and tell me — that is a bad download, not a formatting problem.

## Rules

- Do not create a Routine you cannot attach Supabase to.
- Do not invent prompts, crons or models. They are in `ops/loops/ROUTINES.md`.
- Do not change anything under `src/desk/guard/`, `config/weights.sha256`,
  `config/pf/` or `CLAUDE.md`. Those are the guard rail and they go through
  review, not a setup session.
- Watch the daily Routine run cap at `claude.ai/code/routines`. Five loops at
  these crons is about 34 runs a day. If that is over the cap, tell me before
  creating them all.
- When you are done, tell me in plain English: which Routines exist, which
  connectors each carries, whether both launchd jobs are loaded, and what the
  publisher digest check said.
