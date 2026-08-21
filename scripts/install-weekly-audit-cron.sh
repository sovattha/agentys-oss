#!/usr/bin/env bash
# Install /audit-e2e weekly as a macOS launchd agent (LOCAL DEV ONLY).
#
# Fires every Sunday at 3:00 local time. Agit comme un filet de sécurité hebdo
# qui re-teste l'app complète sans intervention manuelle. Les findings HIGH
# créent automatiquement des issues GH via `--auto-issues`.
#
# PRÉREQUIS au moment du trigger :
#   - Mac est réveillé (laptop pas en sleep profond)
#   - Backend Flask UP (port 5050) et frontend Vite UP (port 1420)
#   - `claude` CLI auth + ANTHROPIC_API_KEY dans l'env
#   - `gh` CLI auth si --auto-issues
#
# Logs   : $REPO/tasks/audit-reports/launchd-std{out,err}.log
# Install: ./scripts/install-weekly-audit-cron.sh
# Remove : ./scripts/install-weekly-audit-cron.sh --uninstall
# Test   : ./scripts/install-weekly-audit-cron.sh --test (déclenche immédiatement)

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.agentys.weekly-audit"
PLIST_SRC="$REPO/scripts/${LABEL}.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/${LABEL}.plist"

if [[ "${1:-}" == "--uninstall" ]]; then
  if launchctl list | grep -q "$LABEL"; then
    launchctl unload "$PLIST_DEST" 2>/dev/null || true
    echo "[uninstall] Unloaded launchd agent $LABEL"
  fi
  rm -f "$PLIST_DEST"
  echo "[uninstall] Removed $PLIST_DEST"
  exit 0
fi

if [[ "${1:-}" == "--test" ]]; then
  echo "[test] Triggering audit-e2e.sh immediately…"
  bash "$REPO/scripts/audit-e2e.sh"
  exit $?
fi

# Install
if [[ ! -f "$PLIST_SRC" ]]; then
  echo "[install] ❌ Source plist not found: $PLIST_SRC" >&2
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents" "$REPO/tasks/audit-reports"

# Copier le plist dans LaunchAgents (pas symlink — launchd refuse les symlinks)
cp "$PLIST_SRC" "$PLIST_DEST"
echo "[install] Copied $PLIST_SRC → $PLIST_DEST"

# Unload si déjà chargé, puis reload
if launchctl list | grep -q "$LABEL"; then
  launchctl unload "$PLIST_DEST" 2>/dev/null || true
fi
launchctl load "$PLIST_DEST"
echo "[install] ✅ Loaded launchd agent $LABEL"

echo ""
echo "Next fire : dimanche 03:00 local time"
echo "Verify    : launchctl list | grep $LABEL"
echo "Test now  : $0 --test"
echo "Uninstall : $0 --uninstall"
