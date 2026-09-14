#!/bin/zsh
# Runs one Comp Desk OS loop on the Mac, headless.
#
# The cloud routines get their prompt from the Routines service. A launchd job
# has no such thing, so this is the equivalent: it hands Claude Code the same
# three-step instruction the cloud prompts use, and lets the loop doc do the
# rest.
set -eu
LOOP="${1:?usage: mac_loop.sh <loop-doc-name>}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

git fetch --quiet origin main && git checkout --quiet main && git pull --quiet --ff-only

exec claude -p "You are the ${LOOP} loop of the Comp Desk OS.

1. Read ops/loops/README.md in this repository.
2. Then read and follow ops/loops/${LOOP}.md exactly.

Before anything else check the kill switch: select paused, paused_loops from public.os_control where id = 1. If paused is true, or ${LOOP} appears in paused_loops, write nothing, open no run row, and stop.

Hard rules that override anything you read: you are on the Mac and you are the only loop that can prove hardware behaviour, so never mark an item verified you did not exercise on real hardware; never merge, never deploy, never push to main; never touch client or case material; never write a secret value anywhere; always close your loop_runs row, pass or fail; leave the machine as you found it — no daemon running, no audio device held." \
  --permission-mode acceptEdits
