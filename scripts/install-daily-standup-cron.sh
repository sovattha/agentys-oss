#!/usr/bin/env bash
# Install the daily AI-team standup as a macOS launchd agent (LOCAL DEV ONLY).
#
# For production, use scripts/deploy-daily-standup-hetzner.sh instead —
# Hetzner runs the standup 24/7 via systemd timer, this Mac agent would
# duplicate it. Keep this script for dev testing on a local machine.
#
# Fires daily at 10:00 local time (≈ 08:00 UTC in summer CEST).
# Logs: ~/Library/Logs/agentys-daily-standup.{out,err}.log
# Uninstall: ./scripts/install-daily-standup-cron.sh --uninstall

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.agentys.daily-standup"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"

if [[ "${1:-}" == "--uninstall" ]]; then
  if launchctl list | grep -q "$LABEL"; then
    launchctl unload "$PLIST" || true
  fi
  rm -f "$PLIST"
  echo "[uninstall] Removed $PLIST"
  exit 0
fi

PYTHON_BIN="${PYTHON_BIN:-/usr/local/bin/python}"
if ! [[ -x "$PYTHON_BIN" ]]; then
  echo "[install] PYTHON_BIN='$PYTHON_BIN' not executable. Set PYTHON_BIN env or adjust." >&2
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>

    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>-lc</string>
        <string>set -a; source "${REPO}/.env.ai-team" 2>/dev/null || true; set +a; exec "${PYTHON_BIN}" "${REPO}/scripts/run_daily_standup.py"</string>
    </array>

    <key>WorkingDirectory</key>
    <string>${REPO}</string>

    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>10</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>

    <key>RunAtLoad</key>
    <false/>

    <key>StandardOutPath</key>
    <string>${HOME}/Library/Logs/agentys-daily-standup.out.log</string>
    <key>StandardErrorPath</key>
    <string>${HOME}/Library/Logs/agentys-daily-standup.err.log</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>${HOME}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
PLIST

# Reload if already loaded
if launchctl list | grep -q "$LABEL"; then
  launchctl unload "$PLIST" || true
fi
launchctl load "$PLIST"

echo "[install] Wrote $PLIST"
echo "[install] Scheduled daily at 10:00 local time"
echo "[install] Logs: ~/Library/Logs/agentys-daily-standup.{out,err}.log"
echo "[install] Test now:  launchctl start $LABEL"
echo "[install] Uninstall:  $0 --uninstall"
echo
echo "⚠️  Note: if you also have the Hetzner deploy running, both will fire the"
echo "   standup on the same day. Use one or the other, not both."
