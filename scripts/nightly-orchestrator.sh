#!/bin/bash
# =============================================================================
# Nightly Orchestrator — Enchaine inspection UX + code intel + ingestion memoire
#
# Appele par launchd (com.agentys.nightly) a 3h. Sequentiel :
#   1. nightly-ux-inspection.sh  (UX local + staging)
#   2. nightly-code-intel.sh     (audit code + deps + consolidation memoire)
#   3. nightly-memory-ingest.sh  (ingestion patterns dans graphe MCP)
#   4. nightly-e2e.sh            (Playwright 114 specs en local)
#   5. nightly_findings_router  (route les findings CRIT/IMP/BUG vers senior-dev)
#
# Si une etape echoue partiellement, les suivantes tournent quand meme sur
# les rapports disponibles. Pas de `set -e` volontairement : on veut que le
# pipeline continue meme apres des echecs partiels (staging down, timeout, etc.).
# =============================================================================

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPORT_DIR="$PROJECT_DIR/tasks/nightly-reports"
DATE=$(date +%Y-%m-%d)
TIME=$(date +%H%M)
ORCHESTRATOR_LOG="$REPORT_DIR/${DATE}_${TIME}_orchestrator.log"

mkdir -p "$REPORT_DIR"

echo "=============================================" | tee "$ORCHESTRATOR_LOG"
echo " Nightly Orchestrator — $DATE $TIME" | tee -a "$ORCHESTRATOR_LOG"
echo "=============================================" | tee -a "$ORCHESTRATOR_LOG"

# --- Passe 1 : inspection UX ---
echo "[$(date +%H:%M:%S)] >>> Lancement nightly-ux-inspection.sh" | tee -a "$ORCHESTRATOR_LOG"
if bash "$SCRIPT_DIR/nightly-ux-inspection.sh" "$@"; then
    INSPECTION_STATUS="OK"
else
    INSPECTION_STATUS="ECHEC_PARTIEL (exit $?)"
fi
echo "[$(date +%H:%M:%S)] <<< nightly-ux-inspection.sh : $INSPECTION_STATUS" | tee -a "$ORCHESTRATOR_LOG"

# --- Pause courte avant la passe code intel ---
sleep 3

# --- Passe 2 : code intelligence (audit + consolidation memoire) ---
echo "[$(date +%H:%M:%S)] >>> Lancement nightly-code-intel.sh" | tee -a "$ORCHESTRATOR_LOG"
if bash "$SCRIPT_DIR/nightly-code-intel.sh"; then
    CODE_INTEL_STATUS="OK"
else
    CODE_INTEL_STATUS="ECHEC (exit $?)"
fi
echo "[$(date +%H:%M:%S)] <<< nightly-code-intel.sh : $CODE_INTEL_STATUS" | tee -a "$ORCHESTRATOR_LOG"

# --- Pause courte avant la passe d'ingestion ---
sleep 3

# --- Passe 3 : ingestion memoire ---
echo "[$(date +%H:%M:%S)] >>> Lancement nightly-memory-ingest.sh" | tee -a "$ORCHESTRATOR_LOG"
if bash "$SCRIPT_DIR/nightly-memory-ingest.sh"; then
    INGEST_STATUS="OK"
else
    INGEST_STATUS="ECHEC (exit $?)"
fi
echo "[$(date +%H:%M:%S)] <<< nightly-memory-ingest.sh : $INGEST_STATUS" | tee -a "$ORCHESTRATOR_LOG"

# --- Pause courte avant la passe e2e ---
sleep 3

# --- Passe 4 : e2e Playwright en local ---
echo "[$(date +%H:%M:%S)] >>> Lancement nightly-e2e.sh" | tee -a "$ORCHESTRATOR_LOG"
if bash "$SCRIPT_DIR/nightly-e2e.sh"; then
    E2E_STATUS="OK"
else
    E2E_STATUS="ECHEC (exit $?)"
fi
echo "[$(date +%H:%M:%S)] <<< nightly-e2e.sh : $E2E_STATUS" | tee -a "$ORCHESTRATOR_LOG"

# --- Pause courte avant le routage des findings ---
sleep 3

# --- Passe 5 : route les findings vers senior-dev (issues GitHub auto-fix) ---
# Lit les rapports markdown des passes 1-4 et crée des issues
# `agent:senior-dev` pour chaque finding CRIT/IMP/BUG/CRASH/REGRESSION.
# Déduplication via fingerprint (cf. ai_team/lib/finding_router.py).
echo "[$(date +%H:%M:%S)] >>> Routage findings nightly → senior-dev" | tee -a "$ORCHESTRATOR_LOG"
if (cd "$PROJECT_DIR" && python -m ai_team.lib.nightly_findings_router --since 24h \
    >> "$ORCHESTRATOR_LOG" 2>&1); then
    ROUTING_STATUS="OK"
else
    ROUTING_STATUS="ECHEC (exit $?)"
fi
echo "[$(date +%H:%M:%S)] <<< Routage findings : $ROUTING_STATUS" | tee -a "$ORCHESTRATOR_LOG"

echo "=============================================" | tee -a "$ORCHESTRATOR_LOG"
echo " Orchestrator complete — $(date +%H:%M:%S)" | tee -a "$ORCHESTRATOR_LOG"
echo " Inspection  : $INSPECTION_STATUS" | tee -a "$ORCHESTRATOR_LOG"
echo " Code intel  : $CODE_INTEL_STATUS" | tee -a "$ORCHESTRATOR_LOG"
echo " Ingestion   : $INGEST_STATUS" | tee -a "$ORCHESTRATOR_LOG"
echo " E2E         : $E2E_STATUS" | tee -a "$ORCHESTRATOR_LOG"
echo " Routage     : $ROUTING_STATUS" | tee -a "$ORCHESTRATOR_LOG"
echo "=============================================" | tee -a "$ORCHESTRATOR_LOG"
