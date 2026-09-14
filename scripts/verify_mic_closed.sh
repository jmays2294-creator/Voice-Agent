#!/bin/sh
# Rule 4 acceptance: the microphone is closed at rest, checked at the device
# level rather than by reading the code.
set -eu
echo "Microphone at rest"
echo "=================="

state_file="${DESK_STATE_DIR:-$HOME/.desk}/signals/state"
[ -f "$state_file" ] && echo "daemon state: $(cat "$state_file")" || echo "daemon state: (no signal file)"

echo
echo "Processes holding an audio input device:"
if command -v lsof >/dev/null 2>&1; then
  found=$(lsof 2>/dev/null | grep -i -E 'AppleHDA|CoreAudio|AudioDevice' | grep -i -v coreaudiod || true)
  if [ -z "$found" ]; then echo "  none"; else echo "$found"; fi
fi

echo
echo "CoreAudio input clients (authoritative):"
if command -v log >/dev/null 2>&1; then
  log show --last 2m --predicate 'subsystem == "com.apple.coreaudio"' --style compact 2>/dev/null \
    | grep -i -E 'input|record' | tail -20 || echo "  no recent input activity"
fi

echo
echo "Microphone indicator (macOS 12+ reports an active mic in the control centre):"
if command -v ioreg >/dev/null 2>&1; then
  ioreg -c AppleUSBAudioEngine 2>/dev/null | grep -i -c 'IOAudioEngineState.*1' \
    | sed 's/^/  engines running: /' || true
fi

echo
echo "PASS if: state is idle or deaf, and no Desk process appears above."
echo "Run this while the key is NOT held. Then hold the key and re-run: Desk"
echo "must appear. A daemon that never appears is not capturing at all."
