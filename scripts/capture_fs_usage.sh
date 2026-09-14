#!/bin/sh
# Rule 4 acceptance: no audio file is written anywhere during a full session.
#
# fs_usage needs root and sees every write the daemon makes. Run this, then
# have a normal conversation with Desk, then stop it. The capture is the
# evidence; attach it to the acceptance record.
set -eu
OUT="${1:-desk-fs-usage.txt}"
echo "Capturing every filesystem write by the Desk daemon."
echo "Have a full conversation, then press ctrl-C."
echo "Writing to $OUT"
echo

sudo fs_usage -w -f filesys 2>/dev/null \
  | grep -i -E 'desk|python' \
  | grep -i -E 'open|write|create|rename' \
  | tee "$OUT"

echo
echo "Now check the capture for audio:"
echo "  grep -i -E '\\.(wav|aiff|caf|flac|mp3|m4a|raw|pcm)' $OUT"
echo "Any hit is a Rule 4 failure. Expected writes are only:"
echo "  ~/.desk/signals/state, ~/.desk/log/decisions.jsonl, ~/.desk/log/audit-spool.jsonl"
