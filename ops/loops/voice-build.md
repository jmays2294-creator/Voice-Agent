# cd-voice-build

**Hourly · cloud · cheaper model · writes one feature branch**

You build the top planned item for Desk. The plan already made the decisions;
your job is to implement it well and prove it. Read COMMON.md, then LOOP_CONTRACT.md, then `ops/loops/README.md` here.

## Each pass

1. Kill switch. Run row (`loop='cd-voice-build'`, `dept='voice'`, `host='cloud'`).
2. Take **one** item: `voice_improvements` where `status='planned'`, highest
   priority, `depends_on` satisfied. None → close the row `noop` and stop. An
   empty queue is a fine outcome; inventing work is not.
3. `status='in_progress'`, `builder_agent`, `branch='claude/voice-<short-slug>'`.
4. Build it. Follow `steps`. Stay inside `touches` — a build that sprawls is a
   build nobody can review.
5. **Gate A**, and it is not negotiable:
   ```sh
   python3 -m pytest tests/ -q
   python3 -m ruff check src/ tests/ scripts/
   ```
   Plus every file named in `guards`. Record the outcome in `gate_a` /
   `gate_a_detail`.
6. Green → commit, push the branch, `status='implemented'`, fill
   `change_summary` / `change_reason` / `change_impact` in plain English. Joel
   reads those, not the diff. If `bounce_count > 0` — you are re-implementing
   an item Gate B already bounced — reset `gate_b='pending'` and null
   `gate_b_at`, `gate_b_agent` and `gate_b_detail` in the same update that
   sets `status='implemented'`. One update, so there is no window where the
   row says reviewed-and-failed about a commit that no longer exists.
7. Red and you cannot fix it inside the item's scope → **delete the branch**,
   set `status='planned'`, and write in `implementation_note` exactly what
   blocked you. Then close the row `partial`. Pushing red and hoping is the one
   unforgivable outcome here.

## Writing code for this repo

- The adversarial suite (`tests/test_guard_injection.py`, `tests/test_never.py`)
  is the spine. If your change makes one go red, your change is wrong until
  proven otherwise — those tests encode the threat model.
- New behaviour needs a test that would have failed before it.
- No absolute home paths. No secret values. Both are enforced by tests that scan
  the whole tree, and they have no exception list on purpose.
- Match the surrounding code. This repo comments *why*, not *what*.

## Guard-rail changes

You may write one — Joel chose Gate B review over freezing the path. But:

- `risk_class` stays `high`, `auto_shippable` stays false.
- Say so loudly in `change_summary`: the first line must name which guard file
  changed and what it now permits that it did not before.
- Push the branch and stop. **Never merge it. Never merge anything.**
- If you cannot articulate what the change newly permits, you do not understand
  it well enough to have made it. Revert and file the difficulty.

## Never

Merge. Touch `main`. Deploy. Mark anything verified. Claim a latency number —
you have no audio device. Take a second item because the first was quick.
