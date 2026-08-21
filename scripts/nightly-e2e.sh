#!/bin/bash
# =============================================================================
# Nightly E2E — Lance `yarn test:e2e` en local (macOS)
#
# Demarre backend Python puis Playwright sur les 114 specs. Cleanup strict.
# Invoque par nightly-orchestrator.sh.
#
# Pas de `set -e` : on veut capturer l'exit code de playwright meme sur echec
# pour remonter le status correctement.
# =============================================================================

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_DIR="$PROJECT_DIR/agentys-app"
REPORT_DIR="$PROJECT_DIR/tasks/nightly-reports"
DATE=$(date +%Y-%m-%d)
TIME=$(date +%H%M)
LOG_FILE="$REPORT_DIR/${DATE}_${TIME}_e2e.log"
BACKEND_PID=""

mkdir -p "$REPORT_DIR"

cleanup_playwright_mcp() {
    # The MCP browser is separate from Playwright test browsers. Stale MCP
    # processes can still block later browser automation in the nightly chain.
    pkill -f "node .*playwright-mcp" 2>/dev/null || true
    pkill -f "npm exec @playwright/mcp" 2>/dev/null || true
    pkill -f "user-data-dir=.*mcp-chrome" 2>/dev/null || true
    sleep 1
    pkill -9 -f "node .*playwright-mcp" 2>/dev/null || true
    pkill -9 -f "npm exec @playwright/mcp" 2>/dev/null || true
    pkill -9 -f "user-data-dir=.*mcp-chrome" 2>/dev/null || true
}

echo "=============================================" | tee "$LOG_FILE"
echo " Nightly E2E — $DATE $TIME" | tee -a "$LOG_FILE"
echo "=============================================" | tee -a "$LOG_FILE"
echo "[$(date +%H:%M:%S)] Cleaning stale Playwright MCP browsers" | tee -a "$LOG_FILE"
cleanup_playwright_mcp

# --- Cleanup trap ---
# Ne tue que le backend/frontend QU'ON A DEMARRES (BACKEND_PID non-empty).
# Si on a reuse un backend existant, on le laisse tranquille.
cleanup() {
    echo "[$(date +%H:%M:%S)] Cleanup..." | tee -a "$LOG_FILE"
    if [ -n "$BACKEND_PID" ]; then
        kill "$BACKEND_PID" 2>/dev/null && echo "  Stopped backend (PID $BACKEND_PID)" | tee -a "$LOG_FILE"
        pkill -P "$BACKEND_PID" 2>/dev/null || true
    fi
    # Playwright webServer tue son propre vite ; rien a faire de plus pour :1420
    cleanup_playwright_mcp
}
trap cleanup EXIT INT TERM

# --- Check if backend already healthy (reuse, don't stomp) ---
if curl -sSf http://127.0.0.1:5050/api/health >/dev/null 2>&1; then
    echo "[$(date +%H:%M:%S)] Backend deja healthy sur :5050 — reuse" | tee -a "$LOG_FILE"
else
    # Port occupe sans backend healthy = reliquat, on kill
    if lsof -ti:5050 >/dev/null 2>&1; then
        echo "[$(date +%H:%M:%S)] Port 5050 occupe mais pas healthy — kill" | tee -a "$LOG_FILE"
        lsof -ti:5050 | xargs -r kill -9 2>/dev/null || true
        sleep 2
    fi

    # Demarrage
    echo "[$(date +%H:%M:%S)] Demarrage backend Python..." | tee -a "$LOG_FILE"
    cd "$PROJECT_DIR"
    python run_api.py >>"$LOG_FILE" 2>&1 &
    BACKEND_PID=$!
    echo "  Backend PID: $BACKEND_PID" | tee -a "$LOG_FILE"

    # Wait ready (max 60s)
    echo "[$(date +%H:%M:%S)] Wait backend :5050..." | tee -a "$LOG_FILE"
    for i in {1..60}; do
        if curl -sSf http://127.0.0.1:5050/api/health >/dev/null 2>&1; then
            echo "  Backend ready apres ${i}s" | tee -a "$LOG_FILE"
            break
        fi
        sleep 1
        if [ "$i" = "60" ]; then
            echo "  ERREUR : backend pas ready apres 60s — abort" | tee -a "$LOG_FILE"
            exit 1
        fi
    done
fi

# --- Run playwright ---
echo "[$(date +%H:%M:%S)] Lancement yarn test:e2e (114 specs)..." | tee -a "$LOG_FILE"
cd "$APP_DIR"
# On NE met PAS CI=true : playwright.config.ts aurait reuseExistingServer=false
# alors qu'en local un vite dev peut deja tourner. retries=0 est deja le default.
# Workers : 4 par defaut en local (machine 20 coeurs ; la limite reelle est le
# backend SQLite partage). Surcharger via E2E_WORKERS si contention observee.
export FLASK_ENV=testing
export JWT_SECRET=test-secret-ci
# Mode API ABSOLU : la suite e2e a été écrite pour des mocks sur les origins
# :5050. La CSP (connect-src) avait cassé ce mode en avril 2026 — relaxée en
# dev uniquement par cspDevRelaxPlugin (vite.config.ts). Le webServer de
# playwright.config.ts force aussi cette variable ; on l'exporte ici pour
# couvrir le cas reuseExistingServer avec un vite déjà lancé par ce script.
export VITE_API_URL=http://127.0.0.1:5050
# Un vite dev en mode proxy (sans VITE_API_URL) qui traîne sur :1420 ferait
# échouer les specs à mocks :5050 — on repart toujours d'un serveur propre.
if lsof -ti:1420 >/dev/null 2>&1; then
    echo "[$(date +%H:%M:%S)] Vite résiduel sur :1420 — kill (le webServer Playwright relancera)" | tee -a "$LOG_FILE"
    lsof -ti:1420 | xargs kill 2>/dev/null || true
    sleep 2
fi

# Arg optionnel : passer un filtre (ex. "accessibility.spec.ts") pour smoke test
PLAYWRIGHT_FILTER="${1:-}"
# PIPESTATUS capture l'exit code de yarn avant tee (sinon tee masque les failures)
yarn test:e2e ${PLAYWRIGHT_FILTER} --workers="${E2E_WORKERS:-4}" --reporter=list 2>&1 | tee -a "$LOG_FILE"
E2E_EXIT=${PIPESTATUS[0]}

echo "=============================================" | tee -a "$LOG_FILE"
echo " Nightly E2E complete — $(date +%H:%M:%S)" | tee -a "$LOG_FILE"
echo " Exit code : $E2E_EXIT" | tee -a "$LOG_FILE"
echo " Rapport HTML : $APP_DIR/playwright-report/index.html" | tee -a "$LOG_FILE"
echo "=============================================" | tee -a "$LOG_FILE"

exit $E2E_EXIT
