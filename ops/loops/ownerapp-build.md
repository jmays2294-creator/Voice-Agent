# cd-ownerapp-build

**Hourly · cloud · cheaper model · writes one feature branch**

You build the top planned item for the owner app. Read `ops/loops/README.md`
first, then `ops/loops/voice-build.md` — the discipline is identical and is not
restated here.

Differences that matter:

- The repository is whichever the shape decision named. Until that item is
  approved there is nothing to build: close the row `noop` and stop. **Do not
  pick a stack yourself to get unblocked.**
- Gate A is that project's own test and lint commands, not this repo's.
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
