#!/bin/bash
# =============================================================================
# Nightly Memory Ingest — Ingestion des patterns dans le graphe MCP memoire
#
# Lit les rapports nocturnes recents (7 derniers jours), identifie les patterns
# recurrents (bugs qui reviennent, findings persistants), et les ecrit comme
# observations sur les entites du graphe MCP memoire.
#
# Separé de nightly-ux-inspection.sh pour ne pas le fragiliser.
# Peut etre lance manuellement ou enchainé via launchd apres la passe principale.
#
# Usage:
#   ./scripts/nightly-memory-ingest.sh                # Mode standard (7 jours)
#   NIGHTLY_INGEST_DAYS=3 ./scripts/nightly-memory-ingest.sh  # Fenetre custom
#
# Prerequis:
#   - ANTHROPIC_API_KEY dans .env ou environnement
#   - MCP memory server configure dans ~/.claude.json
#   - claude CLI dans PATH
# =============================================================================

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REPORT_DIR="$PROJECT_DIR/tasks/nightly-reports"
DATE=$(date +%Y-%m-%d)
TIME=$(date +%H%M)
INGEST_REPORT="$REPORT_DIR/${DATE}_${TIME}_memory-ingest.md"
LOG_FILE="$REPORT_DIR/${DATE}_${TIME}_memory-ingest.log"
INGEST_DAYS="${NIGHTLY_INGEST_DAYS:-7}"
MODEL="${NIGHTLY_MODEL:-sonnet}"
MAX_BUDGET="${NIGHTLY_INGEST_BUDGET:-5.00}"

mkdir -p "$REPORT_DIR"

echo "=============================================" | tee "$LOG_FILE"
echo " Nightly Memory Ingest — $DATE $TIME" | tee -a "$LOG_FILE"
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

# --- Collecte des rapports recents ---
RECENT_UX=$(find "$REPORT_DIR" -name "*_ux-local.md" -mtime -${INGEST_DAYS} | sort | tr '\n' ',' | sed 's/,$//')
RECENT_CODE=$(find "$REPORT_DIR" -name "*_code-intel.md" -mtime -${INGEST_DAYS} | sort | tr '\n' ',' | sed 's/,$//')

UX_COUNT=$(echo "$RECENT_UX" | tr ',' '\n' | grep -c . || echo 0)
CODE_COUNT=$(echo "$RECENT_CODE" | tr ',' '\n' | grep -c . || echo 0)

echo "[$(date +%H:%M:%S)] Rapports UX trouves : $UX_COUNT" | tee -a "$LOG_FILE"
echo "[$(date +%H:%M:%S)] Rapports code-intel trouves : $CODE_COUNT" | tee -a "$LOG_FILE"

if [ "$UX_COUNT" -eq 0 ] && [ "$CODE_COUNT" -eq 0 ]; then
    echo "[WARN] Aucun rapport a analyser. Sortie anticipee." | tee -a "$LOG_FILE"
    echo "# Memory Ingest Report — $DATE" > "$INGEST_REPORT"
    echo "" >> "$INGEST_REPORT"
    echo "## SKIPPED: Aucun rapport recent dans les $INGEST_DAYS derniers jours" >> "$INGEST_REPORT"
    exit 0
fi

# --- Build list of reports for the prompt ---
REPORTS_LIST=""
for f in $(echo "$RECENT_UX" | tr ',' ' '); do
    [ -n "$f" ] && REPORTS_LIST+="- $f"$'\n'
done
for f in $(echo "$RECENT_CODE" | tr ',' ' '); do
    [ -n "$f" ] && REPORTS_LIST+="- $f"$'\n'
done

# --- Run Claude ingestion ---
echo "[$(date +%H:%M:%S)] Demarrage ingestion via claude -p..." | tee -a "$LOG_FILE"
cd "$PROJECT_DIR"

claude -p \
    --model "$MODEL" \
    --max-budget-usd "$MAX_BUDGET" \
    --allowedTools "mcp__plugin_ecc_memory__*,mcp__memory__*,Read,Write,Glob" \
    <<PROMPT >> "$LOG_FILE" 2>&1 || true
Tu es un agent d'ingestion memoire pour le projet Agentys.

## Ton role

Analyser les rapports nocturnes recents (${INGEST_DAYS} derniers jours) pour identifier des patterns repetes et les enregistrer comme observations dans le graphe MCP memoire.

## Etapes obligatoires

1. Utilise \`mcp__plugin_ecc_memory__read_graph\` (ou \`mcp__memory__read_graph\`) pour charger l'etat actuel du graphe. Les entites deja bootstrappees incluent :
   - Agentys, Backend-Flask, Frontend-Tauri, Frontend-Mobile
   - OnboardingPipeline, DrafterAgent, CriticAgent
   - Persona-Default, Persona-LawyerParis, Persona-SalesDirector, Persona-StartupCEO, Persona-HRDirector, Persona-ConsultantIntl
   - Infra-Railway, Infra-Vercel, Infra-Azure-AD, Database-SQLite
   - PipelineNocturne

2. Lis les rapports listes ci-dessous (via Read).

3. Identifie uniquement les patterns avec signal fort :
   - Bug qui apparait au moins 2 fois dans la fenetre
   - Regression confirmee (feature qui marchait et ne marche plus)
   - Evolution de score (onboarding personas)
   - Nouveaux findings code-intel recurrents

4. Pour chaque pattern, utilise \`mcp__plugin_ecc_memory__add_observations\` sur l'entite concernee.

5. Format obligatoire de chaque observation : \`[YYYY-MM-DD] pattern concret + quantifie + source\`
   Exemple : \`[2026-04-12] Bug EmailList scroll glitch observe 3 jours consecutifs (04-10, 04-11, 04-12 rapports UX)\`

## Regles strictes

- Maximum 10 nouvelles observations par run (evite le bruit)
- Ne cree PAS de nouvelle entite sauf si un nouveau composant apparait clairement et manque
- Pas d'observations speculatives ou triviales
- Pas de modifications de code source
- Tu as l'autorisation d'ecrire directement via les tools MCP, sans demander confirmation

## Rapports a analyser

$REPORTS_LIST

## Rapport final

Ecris ensuite via Write dans : $INGEST_REPORT

Format :
\`\`\`markdown
# Memory Ingest Report — $DATE $TIME
## Fenetre : ${INGEST_DAYS} derniers jours
## Rapports analyses : $((UX_COUNT + CODE_COUNT))

## Observations ajoutees
- Entite X : "[date] pattern"
- ...

## Nouvelles entites creees (si applicable)
- ...

## Patterns detectes mais NON enregistres (signal faible)
- ...

## Recommandations pour la prochaine passe
- ...
\`\`\`
PROMPT

echo "[$(date +%H:%M:%S)] Ingestion terminee → $INGEST_REPORT" | tee -a "$LOG_FILE"

if [ -s "$INGEST_REPORT" ]; then
    echo "[$(date +%H:%M:%S)] Rapport ingest : $(wc -l < "$INGEST_REPORT") lignes" | tee -a "$LOG_FILE"
else
    echo "[WARN] Rapport ingest vide ou manquant" | tee -a "$LOG_FILE"
fi

echo "=============================================" | tee -a "$LOG_FILE"
echo " Complete — $(date +%H:%M:%S)" | tee -a "$LOG_FILE"
echo "=============================================" | tee -a "$LOG_FILE"
