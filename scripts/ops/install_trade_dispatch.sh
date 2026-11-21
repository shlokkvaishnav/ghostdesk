#!/bin/sh
# D23: install (or with "remove", uninstall) the Mac launchd job that starts the trade run on time.
# The hours in the plist are local IST (UTC+5:30): 20:15 and 21:15 = 14:45 and 15:45 UTC.
set -e
P="$HOME/Library/LaunchAgents/com.ghostdesk.trade-dispatch.plist"
launchctl bootout "gui/$(id -u)" "$P" 2>/dev/null || true
if [ "${1:-}" = remove ]; then rm -f "$P"; echo "removed"; exit 0; fi
cp "$(dirname "$0")/com.ghostdesk.trade-dispatch.plist" "$P"
plutil -lint "$P"
launchctl bootstrap "gui/$(id -u)" "$P"
echo "installed; log: /tmp/ghostdesk-trade-dispatch.log"
