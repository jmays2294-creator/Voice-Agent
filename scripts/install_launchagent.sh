#!/bin/sh
# Install the LaunchAgent, substituting paths at install time so no absolute
# home path is ever committed to the repository.
set -eu
REPO=$(cd "$(dirname "$0")/.." && pwd)
LOGS="${DESK_LOG_DIR:-$HOME/Library/Logs/TheCompDesk}"
DEST="$HOME/Library/LaunchAgents/com.thecompdesk.desk.plist"

mkdir -p "$LOGS" "$HOME/Library/LaunchAgents"
sed -e "s|__DESK_HOME__|$HOME|g" \
    -e "s|__DESK_REPO__|$REPO|g" \
    -e "s|__DESK_LOGS__|$LOGS|g" \
    "$REPO/launchd/com.thecompdesk.desk.plist" > "$DEST"
chmod 600 "$DEST"

launchctl unload "$DEST" 2>/dev/null || true
launchctl load -w "$DEST"
echo "installed $DEST"
echo "logs: $LOGS/desk.out.log"
echo
echo "Grant Accessibility permission for the hold-to-talk event tap:"
echo "  System Settings > Privacy & Security > Accessibility"
