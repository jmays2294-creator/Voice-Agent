# cd-ownerapp-build

**Hourly · cloud · cheaper model · writes one feature branch**

You build the top planned item for the owner app. Read COMMON.md, LOOP_CONTRACT.md and
`ops/loops/README.md` here, then `ops/loops/voice-build.md` — the discipline is
identical and is not restated here.

Differences that matter:

- The repository is `jmays2294-creator/owner-app`. Decided 2026-09-16 on item
  `4a5f4659`: **native SwiftUI, in its own repository.** Build the owner app
  nowhere else — in particular not in `thecompdesk-app`, which is a different
  product with a different threat model and a mirroring chore this surface does
  not share. **Do not pick a stack yourself.** If an item seems to need a
  different one, that is a question for the plan loop, not a decision for you:
  set it back to `planned` and say so.
- **Gate A is not reachable from the cloud. That is the price of SwiftUI, and
  it was paid knowingly.** A cloud loop has no Xcode, no Swift toolchain and no
  Simulator, so it cannot compile or test this project. You therefore push a
  branch that *nothing has verified*: leave `gate_a` at `pending`, and say on
  the item that the branch is pushed, not green. `mac-ownerapp-verify` owns
  Gate A here.

  Claiming a build, test or Simulator result you did not observe is the same
  failure as claiming a latency number with no microphone (README rule 4), and
  it is worse on this surface, because a green Gate A is what tells Joel a
  branch is safe to look at. An honest `pending` is always better than an
  invented `pass`.
- **No claimant data reaches this surface.** A query touching a case table is a
  stop, not a review comment — `saved_cases`, `case_events`, `firm_case_*`,
  `c3_*`, `worker_*`, `recovery_*`, `comp_buddy_chats`, `advisor_sessions` and
  anything else in `VOICE_SURFACE.md`'s out-of-scope list. If an item seems to
  need one, it is mis-scoped: set it back to `planned` and say so.
- Everything this app reads is an ops table: `loop_runs`, the four
  `*_improvements` backlogs, `owner_requests`, `voice_audit`, `voice_turns`,
  `os_schedule`, `os_control`.

Never merge, never deploy, never submit to a store, never claim a Simulator
result — that is `mac-ownerapp-verify`'s.
