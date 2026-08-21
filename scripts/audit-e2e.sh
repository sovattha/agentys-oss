#!/usr/bin/env bash
# =============================================================================
# Audit e2e multi-agents — wrapper shell (cron-friendly)
#
# Lance `claude -p` qui orchestre 4 agents en parallèle pour un audit complet :
#   1. Silent failures frontend React
#   2. Silent failures backend Flask
#   3. UX live via Playwright MCP
#   4. Toast coverage gaps
#
# Les prompts sont dans scripts/audit-prompts/*.md (réutilisés par le slash
# command /audit-e2e aussi — source de vérité unique).
#
# Usage :
#   ./scripts/audit-e2e.sh                  # Rapport uniquement
#   ./scripts/audit-e2e.sh --auto-issues    # Crée aussi les issues HIGH
#   ./scripts/audit-e2e.sh --scope=backend  # Sous-ensemble (1 agent)
#
# Prérequis :
#   - backend (port 5050) et frontend (port 1420) tournent
#   - `claude` CLI installé + ANTHROPIC_API_KEY configuré
#   - `gh` CLI authentifié si --auto-issues
# =============================================================================

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DATE=$(date +%Y-%m-%d_%H%M)
REPORT_DIR="$PROJECT_DIR/tasks/audit-reports/$DATE"
PROMPTS_DIR="$PROJECT_DIR/scripts/audit-prompts"
LOG_FILE="$REPORT_DIR/run.log"

AUTO_ISSUES=""
SCOPE="all"
MAX_BUDGET="${AUDIT_MAX_BUDGET:-6.00}"
MODEL="${AUDIT_MODEL:-sonnet}"

for arg in "$@"; do
  case "$arg" in
    --auto-issues)   AUTO_ISSUES="yes" ;;
    --scope=*)       SCOPE="${arg#*=}" ;;
    -h|--help)
      sed -n '/^# Usage/,/^# =====/p' "$0"
      exit 0
      ;;
  esac
done

mkdir -p "$REPORT_DIR"
echo "[$(date +%H:%M:%S)] Audit e2e starting — report dir: $REPORT_DIR" | tee "$LOG_FILE"
echo "  model=$MODEL  budget=\$$MAX_BUDGET  scope=$SCOPE  auto-issues=${AUTO_ISSUES:-no}" | tee -a "$LOG_FILE"

# Préflight — backends UP ?
if ! curl -sS -m 3 http://localhost:5050/api/health > /dev/null 2>&1; then
  echo "❌ Backend localhost:5050 not reachable" | tee -a "$LOG_FILE"
  exit 1
fi
if ! curl -sS -m 3 http://localhost:1420/ > /dev/null 2>&1; then
  echo "❌ Frontend localhost:1420 not reachable" | tee -a "$LOG_FILE"
  exit 1
fi
echo "  ✅ Backend + frontend reachable" | tee -a "$LOG_FILE"

# Construire le master prompt qui coordonne les 4 agents.
MASTER_PROMPT_FILE="$REPORT_DIR/master-prompt.md"
cat > "$MASTER_PROMPT_FILE" <<EOF
# Audit e2e multi-agents — coordinateur

Tu orchestres un audit complet de l'app Agentys via 4 agents parallèles. Chaque
prompt est dans \`$PROMPTS_DIR/\`. Lis-les, lance les 4 Agents en parallèle (un
seul message avec 4 tool calls), attends leurs rapports, agrège dans
\`$REPORT_DIR/SUMMARY.md\`.

Le frontend tourne sur http://localhost:1420 et le backend sur http://localhost:5050.

## Étapes

1. Lire les 4 prompts :
   - \`$PROMPTS_DIR/01-frontend-silent.md\`
   - \`$PROMPTS_DIR/02-backend-silent.md\`
   - \`$PROMPTS_DIR/03-ui-live.md\`
   - \`$PROMPTS_DIR/04-toast-coverage.md\`

2. Lancer les 4 agents en parallèle. Pour chaque agent :
   - subagent_type selon le prompt (silent-failure-hunter, customer-experience-tester, general-purpose)
   - Passer tout le contenu du prompt MD comme \`prompt\` à l'Agent
   - Remplacer \`\$REPORT_DIR\` par \`$REPORT_DIR\` dans le prompt
   - Les agents écrivent eux-mêmes dans \`$REPORT_DIR/0X-*.md\` via le tool Write

3. Après retour des 4 agents : lire les 4 rapports, dédupliquer contre les issues GH récentes (\`gh issue list --state all --limit 60\`), écrire \`$REPORT_DIR/SUMMARY.md\` avec :
   - Compteurs NEW/EXISTING/REGRESSION
   - Top 5 HIGH prioritisés
   - Recommandations

$(if [ -n "$AUTO_ISSUES" ]; then
  echo "4. Mode \`--auto-issues\` activé : pour chaque finding NEW HIGH (max 10), créer une issue GitHub via \`gh issue create\` avec labels \`bug,high,<scope>\`."
else
  echo "4. Mode rapport uniquement : NE PAS créer d'issues, juste les lister dans SUMMARY.md avec la commande \`gh issue create\` suggérée."
fi)

5. Retourner un résumé compact (< 300 mots) : findings par catégorie + top 3-5 HIGH NEW + actions suggérées.

## Scope

$(case "$SCOPE" in
  frontend) echo "Restreindre aux prompts 01 et 04 uniquement." ;;
  backend)  echo "Restreindre au prompt 02 uniquement." ;;
  ui)       echo "Restreindre au prompt 03 uniquement." ;;
  all|*)    echo "Les 4 prompts (comportement par défaut)." ;;
esac)

## Garde-fous

- Si un agent crash : continuer avec les autres, noter dans SUMMARY.
- Si > 20 findings HIGH : signaler régression système probable.
- Pas de Lighthouse.
EOF

echo "  📝 Master prompt written: $MASTER_PROMPT_FILE" | tee -a "$LOG_FILE"
echo "[$(date +%H:%M:%S)] Invoking claude -p (model=$MODEL, budget=\$$MAX_BUDGET)..." | tee -a "$LOG_FILE"

# Invoker claude -p. Le --max-budget-usd est le garde-fou de coût.
cd "$PROJECT_DIR"
claude -p \
  --model "$MODEL" \
  --max-budget-usd "$MAX_BUDGET" \
  --bare \
  < "$MASTER_PROMPT_FILE" \
  > "$REPORT_DIR/claude-output.md" \
  2>> "$LOG_FILE"

EXIT_CODE=$?
echo "[$(date +%H:%M:%S)] claude -p exited with code $EXIT_CODE" | tee -a "$LOG_FILE"

if [ -f "$REPORT_DIR/SUMMARY.md" ]; then
  echo "[$(date +%H:%M:%S)] ✅ Audit complete. Summary:" | tee -a "$LOG_FILE"
  head -60 "$REPORT_DIR/SUMMARY.md" | tee -a "$LOG_FILE"
  echo ""
  echo "Full report: $REPORT_DIR/"
else
  echo "[$(date +%H:%M:%S)] ⚠️ SUMMARY.md not found — see $REPORT_DIR/claude-output.md for raw output" | tee -a "$LOG_FILE"
  exit 1
fi

exit $EXIT_CODE
