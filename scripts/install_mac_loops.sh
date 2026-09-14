#!/bin/sh
# Install the two Mac-side OS loops. Substitutes paths at install time so no
# absolute home path is committed to the repository.
set -eu
REPO=$(cd "$(dirname "$0")/.." && pwd)
LOGS="${DESK_LOG_DIR:-$HOME/Library/Logs/TheCompDesk}"
mkdir -p "$LOGS" "$HOME/Library/LaunchAgents"

for label in voice-verify ownerapp-verify; do
  SRC="$REPO/launchd/com.thecompdesk.os.$label.plist"
  DEST="$HOME/Library/LaunchAgents/com.thecompdesk.os.$label.plist"
  sed -e "s|__DESK_REPO__|$REPO|g" -e "s|__DESK_LOGS__|$LOGS|g" "$SRC" > "$DEST"
  chmod 600 "$DEST"
  launchctl unload "$DEST" 2>/dev/null || true
  launchctl load -w "$DEST"
  echo "loaded com.thecompdesk.os.$label"
done

echo
echo "Logs: $LOGS"
echo "The Mac must be awake at 01:00 and 03:00 ET. Check with:"
echo "  pmset -g sched"
echo "To wake it for the window:"
echo "  sudo pmset repeat wakeorpoweron MTWRFSU 00:55:00"
