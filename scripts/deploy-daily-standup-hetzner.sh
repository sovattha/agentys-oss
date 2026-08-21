#!/usr/bin/env bash
# Deploy the daily AI-team standup to the Hetzner server.
#
# Prereqs:
#   - SSH access: ssh agentys@<HETZNER_HOST> works (cf. ai_team/deploy/README.md)
#   - Local .env / .env.ai-team contains ANTHROPIC_API_KEY_NIGHTLY (or ANTHROPIC_API_KEY),
#     TELEGRAM_PM_TOKEN, TELEGRAM_PM_CHAT_ID, GITHUB_TOKEN (or gh CLI logged in)
#
# Effect:
#   1. Rsync the runner + ai_team/ module to the server
#   2. Install deps (anthropic + python-telegram-bot + httpx + PyYAML) in ~/venv
#   3. Write ~/.env.ai-team with the required secrets (0600)
#   4. Install a systemd user timer → fires daily at 08:00 UTC
#   5. Verify with a one-shot dry-run
#
# Uninstall: this script with --uninstall
#
# Usage:
#   bash scripts/deploy-daily-standup-hetzner.sh [--uninstall]

set -euo pipefail

HOST="${HETZNER_HOST:-65.109.150.123}"
USER="${HETZNER_USER:-agentys}"
REMOTE="${USER}@${HOST}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"

if [[ "${1:-}" == "--uninstall" ]]; then
  ssh "$REMOTE" "
    systemctl --user stop daily-standup.timer 2>/dev/null || true
    systemctl --user disable daily-standup.timer 2>/dev/null || true
    rm -f ~/.config/systemd/user/daily-standup.{service,timer}
    systemctl --user daemon-reload
  "
  echo "[uninstall] Removed systemd units on $HOST"
  exit 0
fi

# 1) Extract local secrets WITHOUT sourcing (avoids shell-metachar issues in .env)
_get() {
  local name="$1"; local file
  for file in "${REPO}/.env.ai-team" "${REPO}/.env"; do
    [[ -f "$file" ]] || continue
    local line
    line="$(grep -E "^${name}=" "$file" | tail -n 1 || true)"
    [[ -z "$line" ]] && continue
    local val="${line#${name}=}"
    # Strip surrounding single/double quotes if any
    val="${val%\"}"; val="${val#\"}"
    val="${val%\'}"; val="${val#\'}"
    printf '%s' "$val"
    return 0
  done
  return 0
}

NIGHTLY_KEY="$(_get ANTHROPIC_API_KEY_NIGHTLY)"
FALLBACK_KEY="$(_get ANTHROPIC_API_KEY)"
API_KEY="${NIGHTLY_KEY:-$FALLBACK_KEY}"
TELEGRAM_PM_TOKEN="$(_get TELEGRAM_PM_TOKEN)"
TELEGRAM_PM_CHAT_ID="$(_get TELEGRAM_PM_CHAT_ID)"
GITHUB_OWNER="$(_get GITHUB_OWNER)"
GITHUB_REPO="$(_get GITHUB_REPO)"
BUDGET="$(_get AI_TEAM_BUDGET_MONTHLY_USD)"

[[ -z "$API_KEY" ]] && { echo "❌ Missing ANTHROPIC_API_KEY[_NIGHTLY]" >&2; exit 1; }
[[ -z "${TELEGRAM_PM_TOKEN:-}" ]] && { echo "❌ Missing TELEGRAM_PM_TOKEN" >&2; exit 1; }
[[ -z "${TELEGRAM_PM_CHAT_ID:-}" ]] && { echo "❌ Missing TELEGRAM_PM_CHAT_ID" >&2; exit 1; }
GH_TOKEN="$(_get GITHUB_TOKEN)"
[[ -z "$GH_TOKEN" ]] && GH_TOKEN="$(gh auth token 2>/dev/null || true)"
[[ -z "$GH_TOKEN" ]] && { echo "❌ Missing GITHUB_TOKEN (set in env or login via gh)" >&2; exit 1; }

# 2) Rsync code (only what's needed)
echo "[deploy 1/5] Rsync code → $REMOTE:~/agentys/"
rsync -avz --delete \
  --include="scripts/" \
  --include="scripts/run_daily_standup.py" \
  --include="ai_team/" \
  --include="ai_team/**" \
  --exclude="ai_team/standups/*" \
  --exclude="ai_team/vendor/" \
  --exclude="ai_team/data/*.db*" \
  --exclude="**/__pycache__/**" \
  --exclude="**/*.pyc" \
  --exclude="*" \
  "${REPO}/" "${REMOTE}:~/agentys/"

# 3) Install Python deps inside a venv
echo "[deploy 2/5] Install deps (venv at ~/venv)"
ssh "$REMOTE" bash -s <<'REMOTE_BASH'
set -euo pipefail
command -v python3 >/dev/null
# Ensure venv module available (Debian/Ubuntu split it out)
if ! python3 -c 'import ensurepip' 2>/dev/null; then
  sudo -n apt-get update -qq
  PYVER="$(python3 -c 'import sys;print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  sudo -n apt-get install -y -qq "python${PYVER}-venv" python3-pip
fi
if [[ ! -d ~/venv ]]; then
  python3 -m venv ~/venv
fi
~/venv/bin/pip install --quiet --upgrade pip
~/venv/bin/pip install --quiet \
  'anthropic>=0.40,<1' \
  'PyYAML>=6' \
  'httpx>=0.28' \
  'python-telegram-bot>=21.0,<22.0'
mkdir -p ~/agentys/ai_team/standups ~/agentys/ai_team/data
REMOTE_BASH

# 4) Push secrets (0600)
echo "[deploy 3/5] Write ~/.env.ai-team (0600)"
ssh "$REMOTE" "umask 077; cat > ~/.env.ai-team" <<ENVFILE
ANTHROPIC_API_KEY_NIGHTLY=${API_KEY}
TELEGRAM_PM_TOKEN=${TELEGRAM_PM_TOKEN}
TELEGRAM_PM_CHAT_ID=${TELEGRAM_PM_CHAT_ID}
GITHUB_TOKEN=${GH_TOKEN}
GITHUB_OWNER=${GITHUB_OWNER:-nathan}
GITHUB_REPO=${GITHUB_REPO:-agentys}
AI_TEAM_BUDGET_MONTHLY_USD=${BUDGET:-200}
ENVFILE

# 5) Install systemd user units
echo "[deploy 4/5] Install systemd user timer"
ssh "$REMOTE" bash -s <<'REMOTE_BASH'
set -euo pipefail
mkdir -p ~/.config/systemd/user

cat > ~/.config/systemd/user/daily-standup.service <<'UNIT'
[Unit]
Description=Agentys AI-team daily standup (one-shot)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=%h/agentys
EnvironmentFile=%h/.env.ai-team
ExecStart=%h/venv/bin/python %h/agentys/scripts/run_daily_standup.py
StandardOutput=append:%h/agentys/ai_team/standups/.cron.log
StandardError=append:%h/agentys/ai_team/standups/.cron.log
UNIT

cat > ~/.config/systemd/user/daily-standup.timer <<'UNIT'
[Unit]
Description=Fire daily standup at 08:00 UTC

[Timer]
OnCalendar=*-*-* 08:00:00 UTC
Persistent=true
Unit=daily-standup.service

[Install]
WantedBy=timers.target
UNIT

systemctl --user daemon-reload
systemctl --user enable --now daily-standup.timer

# Enable lingering so the timer keeps running when Nat isn't logged in
sudo loginctl enable-linger "$USER" 2>/dev/null || true

echo "=== timer status ==="
systemctl --user list-timers daily-standup.timer --no-pager || true
REMOTE_BASH

# 6) Smoke test
echo "[deploy 5/5] Smoke test — dry-run on server"
ssh "$REMOTE" "set -a; source ~/.env.ai-team; set +a; cd ~/agentys && ~/venv/bin/python scripts/run_daily_standup.py --dry-run 2>&1 | tail -20"

echo
echo "✅ Deploy OK. Next real run at 08:00 UTC daily."
echo "Manual trigger:   ssh $REMOTE 'systemctl --user start daily-standup.service'"
echo "Tail logs:        ssh $REMOTE 'tail -f ~/agentys/ai_team/standups/.cron.log'"
echo "Uninstall:        $0 --uninstall"
