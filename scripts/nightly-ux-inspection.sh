#!/bin/bash
# =============================================================================
# Nightly UX Inspection — Orchestrateur
# Demarre backend + frontend, lance claude -p avec le prompt UX, cleanup.
# Double cible : local (localhost) puis staging (URLs publiques).
#
# Usage:
#   ./scripts/nightly-ux-inspection.sh                  # Local + staging
#   ./scripts/nightly-ux-inspection.sh --local-only     # Local seulement
#   ./scripts/nightly-ux-inspection.sh --staging-only   # Staging seulement
#
# Prerequis: ANTHROPIC_API_KEY dans .env ou environnement
# =============================================================================

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REPORT_DIR="$PROJECT_DIR/tasks/nightly-reports"
DATE=$(date +%Y-%m-%d)
TIME=$(date +%H%M)
LOG_FILE="$REPORT_DIR/${DATE}_${TIME}_run.log"
BACKEND_PID=""
FRONTEND_PID=""
MODE="${1:---both}"
MAX_BUDGET="${NIGHTLY_MAX_BUDGET:-5.00}"
MODEL="${NIGHTLY_MODEL:-sonnet}"

# URLs staging (configurer dans .env ou ici)
STAGING_FRONTEND="${STAGING_FRONTEND_URL:-}"
STAGING_BACKEND="${STAGING_BACKEND_URL:-}"

cleanup_playwright_mcp() {
    # The Playwright MCP keeps an exclusive Chrome profile open. If a previous
    # run is interrupted, the next UX audit cannot start a browser.
    pkill -f "node .*playwright-mcp" 2>/dev/null || true
    pkill -f "npm exec @playwright/mcp" 2>/dev/null || true
    pkill -f "user-data-dir=.*mcp-chrome" 2>/dev/null || true
    sleep 1
    pkill -9 -f "node .*playwright-mcp" 2>/dev/null || true
    pkill -9 -f "npm exec @playwright/mcp" 2>/dev/null || true
    pkill -9 -f "user-data-dir=.*mcp-chrome" 2>/dev/null || true
}

# --- Cleanup trap ---
cleanup() {
    echo "[$(date +%H:%M:%S)] Cleaning up..." | tee -a "$LOG_FILE"
    if [ -n "$FRONTEND_PID" ]; then
        kill "$FRONTEND_PID" 2>/dev/null && echo "  Stopped frontend (PID $FRONTEND_PID)" | tee -a "$LOG_FILE"
    fi
    if [ -n "$BACKEND_PID" ]; then
        kill "$BACKEND_PID" 2>/dev/null && echo "  Stopped backend (PID $BACKEND_PID)" | tee -a "$LOG_FILE"
    fi
    # Kill remaining child processes
    jobs -p | xargs -r kill 2>/dev/null || true
    cleanup_playwright_mcp
    echo "[$(date +%H:%M:%S)] Cleanup complete" | tee -a "$LOG_FILE"
}
trap cleanup EXIT INT TERM

# --- Setup ---
mkdir -p "$REPORT_DIR"

echo "=============================================" | tee "$LOG_FILE"
echo " Nightly UX Inspection — $DATE $TIME" | tee -a "$LOG_FILE"
echo "=============================================" | tee -a "$LOG_FILE"
echo "Mode: $MODE" | tee -a "$LOG_FILE"
echo "[$(date +%H:%M:%S)] Cleaning stale Playwright MCP browsers" | tee -a "$LOG_FILE"
cleanup_playwright_mcp

# --- Rotate old reports (keep 14 days) ---
find "$REPORT_DIR" -name "*.md" -not -name ".gitkeep" -mtime +14 -delete 2>/dev/null || true
find "$REPORT_DIR" -name "*.log" -mtime +14 -delete 2>/dev/null || true
echo "[$(date +%H:%M:%S)] Rotated reports older than 14 days" | tee -a "$LOG_FILE"

# --- Load .env if needed (prefer nightly-specialised key for cost traceability) ---
if [ -f "$PROJECT_DIR/.env" ]; then
    _NIGHTLY_KEY=$(grep '^ANTHROPIC_API_KEY_NIGHTLY=' "$PROJECT_DIR/.env" 2>/dev/null | cut -d'=' -f2- | tr -d '"' | tr -d "'")
    if [ -n "$_NIGHTLY_KEY" ]; then
        export ANTHROPIC_API_KEY="$_NIGHTLY_KEY"
    fi
fi
if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    if [ -f "$PROJECT_DIR/.env" ]; then
        ANTHROPIC_API_KEY=$(grep '^ANTHROPIC_API_KEY=' "$PROJECT_DIR/.env" | cut -d'=' -f2- | tr -d '"' | tr -d "'")
        export ANTHROPIC_API_KEY
    fi
fi

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    echo "[ERROR] ANTHROPIC_API_KEY not set (check .env or environment)" | tee -a "$LOG_FILE"
    exit 1
fi

# Load staging URLs from .env if not set
if [ -z "$STAGING_FRONTEND" ] && [ -f "$PROJECT_DIR/.env" ]; then
    STAGING_FRONTEND=$(grep '^STAGING_FRONTEND_URL=' "$PROJECT_DIR/.env" 2>/dev/null | cut -d'=' -f2- | tr -d '"' | tr -d "'" || true)
fi
if [ -z "$STAGING_BACKEND" ] && [ -f "$PROJECT_DIR/.env" ]; then
    STAGING_BACKEND=$(grep '^STAGING_BACKEND_URL=' "$PROJECT_DIR/.env" 2>/dev/null | cut -d'=' -f2- | tr -d '"' | tr -d "'" || true)
fi

# --- Check prerequisites ---
if ! command -v claude &>/dev/null; then
    echo "[ERROR] claude CLI not found in PATH" | tee -a "$LOG_FILE"
    exit 1
fi

# =============================================================================
# PASSE 1: Local (si pas --staging-only)
# =============================================================================
if [ "$MODE" != "--staging-only" ]; then
    echo "" | tee -a "$LOG_FILE"
    echo ">>> PASSE 1: Inspection locale (localhost)" | tee -a "$LOG_FILE"
    echo "--------------------------------------------" | tee -a "$LOG_FILE"
    REPORT_LOCAL="$REPORT_DIR/${DATE}_${TIME}_ux-local.md"

    # Check/free ports
    if lsof -i :5050 >/dev/null 2>&1; then
        echo "[WARN] Port 5050 already in use — killing" | tee -a "$LOG_FILE"
        lsof -ti :5050 | xargs kill -9 2>/dev/null || true
        sleep 2
    fi
    if lsof -i :1420 >/dev/null 2>&1; then
        echo "[WARN] Port 1420 already in use — killing" | tee -a "$LOG_FILE"
        lsof -ti :1420 | xargs kill -9 2>/dev/null || true
        sleep 2
    fi

    # Start backend
    echo "[$(date +%H:%M:%S)] Starting backend..." | tee -a "$LOG_FILE"
    cd "$PROJECT_DIR"

    # Find the right Python: prefer the one that can import the app
    PYTHON_BIN=""
    for candidate in /usr/local/bin/python python3 python; do
        if $candidate -c "import sentry_sdk" 2>/dev/null; then
            PYTHON_BIN="$candidate"
            break
        fi
    done
    if [ -z "$PYTHON_BIN" ]; then
        # Fallback: try venvs
        if [ -f ".venv/bin/activate" ]; then
            source .venv/bin/activate
        elif [ -f "venv/bin/activate" ]; then
            source venv/bin/activate
        fi
        PYTHON_BIN="python"
    fi
    echo "[$(date +%H:%M:%S)] Using Python: $($PYTHON_BIN --version 2>&1) at $(which $PYTHON_BIN)" | tee -a "$LOG_FILE"
    $PYTHON_BIN run_api.py --port 5050 >> "$LOG_FILE" 2>&1 &
    BACKEND_PID=$!

    # Wait for backend health
    RETRIES=0
    while [ $RETRIES -lt 30 ]; do
        if curl -sf http://127.0.0.1:5050/api/health >/dev/null 2>&1; then
            echo "[$(date +%H:%M:%S)] Backend healthy (PID $BACKEND_PID)" | tee -a "$LOG_FILE"
            break
        fi
        RETRIES=$((RETRIES + 1))
        if [ $RETRIES -eq 30 ]; then
            echo "[ERROR] Backend failed to start after 30s" | tee -a "$LOG_FILE"
            echo "# Nightly UX Report (Local) — $DATE" > "$REPORT_LOCAL"
            echo "" >> "$REPORT_LOCAL"
            echo "## ABORTED: Backend failed to start" >> "$REPORT_LOCAL"
            echo "Check logs: $LOG_FILE" >> "$REPORT_LOCAL"
            BACKEND_PID=""
            break
        fi
        sleep 1
    done

    # Start frontend (only if backend is up)
    if [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
        echo "[$(date +%H:%M:%S)] Starting frontend..." | tee -a "$LOG_FILE"
        cd "$PROJECT_DIR/agentys-app"
        yarn dev >> "$LOG_FILE" 2>&1 &
        FRONTEND_PID=$!

        RETRIES=0
        while [ $RETRIES -lt 60 ]; do
            if curl -sf http://localhost:1420 >/dev/null 2>&1; then
                echo "[$(date +%H:%M:%S)] Frontend healthy (PID $FRONTEND_PID)" | tee -a "$LOG_FILE"
                break
            fi
            RETRIES=$((RETRIES + 1))
            if [ $RETRIES -eq 60 ]; then
                echo "[ERROR] Frontend failed to start after 60s" | tee -a "$LOG_FILE"
                echo "# Nightly UX Report (Local) — $DATE" > "$REPORT_LOCAL"
                echo "" >> "$REPORT_LOCAL"
                echo "## ABORTED: Frontend failed to start" >> "$REPORT_LOCAL"
                FRONTEND_PID=""
                break
            fi
            sleep 1
        done

        # Run Claude UX audit (local)
        if [ -n "$FRONTEND_PID" ] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
            echo "[$(date +%H:%M:%S)] Starting Claude UX audit (local)..." | tee -a "$LOG_FILE"
            cd "$PROJECT_DIR"

            TARGET_FRONTEND="http://localhost:1420" \
            TARGET_BACKEND="http://127.0.0.1:5050" \
            TARGET_LABEL="LOCAL" \
            REPORT_FILE="$REPORT_LOCAL" \
            claude -p \
                --model "$MODEL" \
                --max-budget-usd "$MAX_BUDGET" \
                --allowedTools "mcp__playwright__*,mcp__plugin_playwright_playwright__*,mcp__plugin_ecc_playwright__*,mcp__chrome-devtools__*,mcp__chrome_devtools__*,Read,Write,Bash(date:*)" \
                < scripts/nightly-ux-prompt.md \
                >> "$REPORT_LOCAL" 2>> "$LOG_FILE" || true

            echo "[$(date +%H:%M:%S)] Local audit complete → $REPORT_LOCAL" | tee -a "$LOG_FILE"
        fi

        # Stop local services
        if [ -n "$FRONTEND_PID" ]; then
            kill "$FRONTEND_PID" 2>/dev/null || true
            FRONTEND_PID=""
        fi
        if [ -n "$BACKEND_PID" ]; then
            kill "$BACKEND_PID" 2>/dev/null || true
            BACKEND_PID=""
        fi
        sleep 2
    fi
fi

# =============================================================================
# PASSE 2: Staging (si pas --local-only et URLs configurees)
# =============================================================================
if [ "$MODE" != "--local-only" ] && [ -n "$STAGING_FRONTEND" ] && [ -n "$STAGING_BACKEND" ]; then
    echo "" | tee -a "$LOG_FILE"
    echo ">>> PASSE 2: Inspection staging ($STAGING_FRONTEND)" | tee -a "$LOG_FILE"
    echo "--------------------------------------------" | tee -a "$LOG_FILE"
    REPORT_STAGING="$REPORT_DIR/${DATE}_${TIME}_ux-staging.md"

    # Verify staging is accessible
    if curl -sf "$STAGING_BACKEND/api/health" >/dev/null 2>&1; then
        echo "[$(date +%H:%M:%S)] Staging backend accessible" | tee -a "$LOG_FILE"

        cd "$PROJECT_DIR"
        TARGET_FRONTEND="$STAGING_FRONTEND" \
        TARGET_BACKEND="$STAGING_BACKEND" \
        TARGET_LABEL="STAGING" \
        REPORT_FILE="$REPORT_STAGING" \
        claude -p \
            --max-budget-usd "$MAX_BUDGET" \
            --allowedTools "mcp__playwright__*,mcp__chrome-devtools__*,Read,Write,Bash(date:*)" \
            < scripts/nightly-ux-prompt.md \
            >> "$REPORT_STAGING" 2>> "$LOG_FILE" || true

        echo "[$(date +%H:%M:%S)] Staging audit complete → $REPORT_STAGING" | tee -a "$LOG_FILE"
    else
        echo "[WARN] Staging backend not accessible at $STAGING_BACKEND/api/health" | tee -a "$LOG_FILE"
        echo "# Nightly UX Report (Staging) — $DATE" > "$REPORT_STAGING"
        echo "" >> "$REPORT_STAGING"
        echo "## SKIPPED: Staging backend not accessible" >> "$REPORT_STAGING"
    fi
elif [ "$MODE" != "--local-only" ]; then
    echo "" | tee -a "$LOG_FILE"
    echo "[INFO] Staging URLs not configured — skipping passe 2" | tee -a "$LOG_FILE"
    echo "  Set STAGING_FRONTEND_URL and STAGING_BACKEND_URL in .env" | tee -a "$LOG_FILE"
fi

# =============================================================================
# Note : la PASSE 3 (code intelligence) a ete extraite dans scripts/nightly-code-intel.sh
# et est desormais orchestree par scripts/nightly-orchestrator.sh.
# =============================================================================

# =============================================================================
# Summary
# =============================================================================
echo "" | tee -a "$LOG_FILE"
echo "=============================================" | tee -a "$LOG_FILE"
echo " Complete — $(date +%H:%M:%S)" | tee -a "$LOG_FILE"
echo " Reports in: $REPORT_DIR/" | tee -a "$LOG_FILE"
echo "=============================================" | tee -a "$LOG_FILE"
