#!/bin/bash
# =============================================================================
# Nightly Code Intelligence — Audit code + deps + consolidation memoire
#
# Extraction de la PASSE 3 historiquement presente dans nightly-ux-inspection.sh.
# Motivation :
#   1. Fix du bug heredoc : le prompt externalise evite les backticks non echappes
#   2. Script testable seul (sans relancer toute l'inspection UX)
#   3. Coherence architecturale : 1 passe = 1 script (comme ux-inspection et memory-ingest)
#
# Usage :
#   ./scripts/nightly-code-intel.sh                              # Mode standard
#   NIGHTLY_CODE_INTEL_BUDGET=3.00 ./scripts/nightly-code-intel.sh   # Budget custom
#
# Prerequis :
#   - ANTHROPIC_API_KEY dans .env ou environnement
#   - claude CLI dans PATH
#   - Repo git initialise (PART 1 utilise git log)
# =============================================================================

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPORT_DIR="$PROJECT_DIR/tasks/nightly-reports"
DATE=$(date +%Y-%m-%d)
TIME=$(date +%H%M)
REPORT_CODE="$REPORT_DIR/${DATE}_${TIME}_code-intel.md"
LOG_FILE="$REPORT_DIR/${DATE}_${TIME}_code-intel.log"
PROMPT_FILE="$SCRIPT_DIR/nightly-code-intel-prompt.md"
MODEL="${NIGHTLY_MODEL:-sonnet}"
MAX_BUDGET="${NIGHTLY_CODE_INTEL_BUDGET:-5.00}"

mkdir -p "$REPORT_DIR"

echo "=============================================" | tee "$LOG_FILE"
echo " Nightly Code Intelligence — $DATE $TIME" | tee -a "$LOG_FILE"
echo "=============================================" | tee -a "$LOG_FILE"

# --- Load .env if needed (prefer nightly-specialised key for cost traceability) ---
if [ -f "$PROJECT_DIR/.env" ]; then
    _NIGHTLY_KEY=$(grep '^ANTHROPIC_API_KEY_NIGHTLY=' "$PROJECT_DIR/.env" 2>/dev/null | cut -d'=' -f2- | tr -d '"' | tr -d "'")
    if [ -n "$_NIGHTLY_KEY" ]; then
        export ANTHROPIC_API_KEY="$_NIGHTLY_KEY"
    fi
fi
if [ -z "${ANTHROPIC_API_KEY:-}" ] && [ -f "$PROJECT_DIR/.env" ]; then
    ANTHROPIC_API_KEY=$(grep '^ANTHROPIC_API_KEY=' "$PROJECT_DIR/.env" | cut -d'=' -f2- | tr -d '"' | tr -d "'")
    export ANTHROPIC_API_KEY
fi

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    echo "[ERROR] ANTHROPIC_API_KEY non defini (check .env ou environnement)" | tee -a "$LOG_FILE"
    exit 1
fi

if ! command -v claude &>/dev/null; then
    echo "[ERROR] claude CLI introuvable dans PATH" | tee -a "$LOG_FILE"
    exit 1
fi

if [ ! -f "$PROMPT_FILE" ]; then
    echo "[ERROR] Prompt introuvable : $PROMPT_FILE" | tee -a "$LOG_FILE"
    exit 1
fi

# --- Run Claude code intel ---
echo "[$(date +%H:%M:%S)] Demarrage code intel via claude -p..." | tee -a "$LOG_FILE"
echo "[$(date +%H:%M:%S)] Budget : \$$MAX_BUDGET | Model : $MODEL" | tee -a "$LOG_FILE"
echo "[$(date +%H:%M:%S)] Rapport cible : $REPORT_CODE" | tee -a "$LOG_FILE"

cd "$PROJECT_DIR"

# Pre-substituer les placeholders {{REPORT_FILE}} et {{DATE}} dans le prompt
# avant de le piper a claude. Cela evite le bug heredoc (backticks markdown
# non echappes) tout en injectant le path exact dans le texte du prompt,
# ce qui rend Claude plus fiable pour appeler Write avec le bon chemin.
PROMPT_EXPANDED=$(sed -e "s|{{REPORT_FILE}}|$REPORT_CODE|g" -e "s|{{DATE}}|$DATE|g" "$PROMPT_FILE")

claude -p \
    --model "$MODEL" \
    --max-budget-usd "$MAX_BUDGET" \
    --strict-mcp-config \
    --allowedTools "Read,Write,Edit,Grep,Glob,Bash(git:*),Bash(wc:*),Bash(find:*),Bash(date:*),Bash(ls:*),Bash(echo:*),Bash(grep:*)" \
    <<< "$PROMPT_EXPANDED" \
    >> "$LOG_FILE" 2>&1 || true

echo "[$(date +%H:%M:%S)] Code intel terminee → $REPORT_CODE" | tee -a "$LOG_FILE"

if [ -s "$REPORT_CODE" ]; then
    echo "[$(date +%H:%M:%S)] Rapport code-intel : $(wc -l < "$REPORT_CODE") lignes" | tee -a "$LOG_FILE"
else
    echo "[WARN] Rapport code-intel vide ou manquant" | tee -a "$LOG_FILE"
fi

echo "=============================================" | tee -a "$LOG_FILE"
echo " Complete — $(date +%H:%M:%S)" | tee -a "$LOG_FILE"
echo "=============================================" | tee -a "$LOG_FILE"
