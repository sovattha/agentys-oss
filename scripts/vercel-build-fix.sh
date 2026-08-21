#!/bin/bash
# =============================================================================
# Vercel Build Fix — Wrapper claude -p qui corrige les erreurs de build Vercel
#
# Invoque par vercel-build-monitor.sh avec les logs d'erreur Vercel.
# Delegue la correction a claude -p (budget $3, mode acceptEdits),
# valide avec yarn tsc -b, enforce le scope guard, commit + push.
#
# Usage:
#   ./scripts/vercel-build-fix.sh <logs_file> <iter_num> <sha>
#
# Exit codes:
#   0 = fix applique et push reussi
#   1 = tsc local echoue apres fix
#   2 = scope guard : fichiers hors perimetre touches
#   3 = claude -p a abandonne ou echoue
#   4 = git commit/push echoue
# =============================================================================

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

LOGS_FILE="${1:-}"
ITER="${2:-?}"
SHA="${3:-}"

if [ -z "$LOGS_FILE" ] || [ ! -f "$LOGS_FILE" ]; then
    echo "[fix] ERROR : logs file absent : $LOGS_FILE" >&2
    exit 1
fi

MODEL="${VERCEL_FIX_MODEL:-sonnet}"
MAX_BUDGET="${VERCEL_FIX_BUDGET:-3.00}"

echo "[fix] ===== Vercel Build Fix iter=$ITER SHA=${SHA:0:8} ====="
echo "[fix] logs : $LOGS_FILE ($(wc -l < "$LOGS_FILE") lignes)"
echo "[fix] model : $MODEL budget : \$$MAX_BUDGET"

# --- F-03 (audit 2026-05-05): NE PAS exporter ANTHROPIC_API_KEY ici. ---
# Pre-fix: ce bloc lisait ANTHROPIC_API_KEY depuis .env et l'exportait, ce qui
# forçait `claude -p` à utiliser le billing API key (~$3/iteration ×3 retries
# = ~$9/build cassé) au lieu de l'abonnement OAuth Max (gratuit). Voir
# `docs/claude-pipe-mode.md` règle 1 : « ANTHROPIC_API_KEY doit être scrubé
# de l'env passé à claude -p » pour que l'auth OAuth soit utilisée.
# Ce hook tourne sur la machine du dev où `claude auth login` est déjà fait,
# donc OAuth Max est dispo sans variable d'env.
# Si tu dois absolument utiliser l'API key (machine sans OAuth Max), ajoute
# ANTHROPIC_API_KEY=... AVANT d'invoquer ce script — pas dans le script.
unset ANTHROPIC_API_KEY 2>/dev/null || true

# --- Genere le prompt user ---
USER_PROMPT=$("$SCRIPT_DIR/prompts/vercel-fix-user.sh" "$LOGS_FILE" "$ITER" "$SHA")

SYSTEM_PROMPT_FILE="$SCRIPT_DIR/prompts/vercel-fix-system.md"
if [ ! -f "$SYSTEM_PROMPT_FILE" ]; then
    echo "[fix] ERROR : prompt system absent : $SYSTEM_PROMPT_FILE" >&2
    exit 3
fi

# --- Invoque claude -p en mode bare (isolation maximale, pattern CLAUDE.md) ---
cd "$PROJECT_DIR"
echo "[fix] Invocation claude -p..."

CLAUDE_OUTPUT="/tmp/vercel-fix-claude-${SHA:0:8}-iter${ITER}.json"

set +e
claude \
    --print \
    --bare \
    --strict-mcp-config \
    --output-format json \
    --model "$MODEL" \
    --max-budget-usd "$MAX_BUDGET" \
    --permission-mode acceptEdits \
    --add-dir "$PROJECT_DIR" \
    --allowedTools "Read,Edit,Write,Glob,Grep,Bash(yarn:*),Bash(npx:*),Bash(git diff:*),Bash(git status:*),Bash(git log:*),Bash(cat:*),Bash(ls:*)" \
    --system-prompt "$(cat "$SYSTEM_PROMPT_FILE")" \
    "$USER_PROMPT" > "$CLAUDE_OUTPUT" 2>&1
CLAUDE_EXIT=$?
set -e

# Scrub API key au cas ou (defense en profondeur, fix adversarial HIGH-1)
scrub_secrets() {
    sed -E 's/sk-ant-[A-Za-z0-9_-]+/[REDACTED]/g; s/sk-proj-[A-Za-z0-9_-]+/[REDACTED]/g'
}

echo "[fix] claude exit=$CLAUDE_EXIT, output : $CLAUDE_OUTPUT ($(wc -c < "$CLAUDE_OUTPUT") bytes)"

if [ "$CLAUDE_EXIT" -ne 0 ]; then
    echo "[fix] ✗ claude -p a echoue (exit $CLAUDE_EXIT)"
    tail -30 "$CLAUDE_OUTPUT" | scrub_secrets
    exit 3
fi

# --- Scope guard : verifie que seuls des fichiers autorises sont touches ---
# Fix adversarial CRITICAL-2 : inclut aussi les fichiers non-trackes (crees
# par claude), et clean -fd sur rollback pour les supprimer.
echo "[fix] Verification scope (git diff + ls-files --others)..."
CHANGED=$({
    git -C "$PROJECT_DIR" diff --name-only
    git -C "$PROJECT_DIR" ls-files --others --exclude-standard
} | sort -u)
if [ -z "$CHANGED" ]; then
    echo "[fix] ✗ aucun fichier modifie ni cree par claude, rien a committer"
    exit 3
fi
echo "$CHANGED" | sed 's/^/[fix]   - /'

OUT_OF_SCOPE=$(echo "$CHANGED" | grep -Ev '^agentys-app/src/|^agentys-app/e2e/' || true)
if [ -n "$OUT_OF_SCOPE" ]; then
    echo "[fix] ✗ SCOPE GUARD : fichiers hors perimetre detectes :"
    echo "$OUT_OF_SCOPE" | sed 's/^/[fix]   ! /'
    echo "[fix] Rollback (git checkout -- . + clean -fd agentys-app/)"
    git -C "$PROJECT_DIR" checkout -- .
    git -C "$PROJECT_DIR" clean -fd agentys-app/ || true
    exit 2
fi

# --- Gate local : yarn tsc -b doit passer ---
echo "[fix] Validation tsc locale..."
cd "$PROJECT_DIR/agentys-app"
if ! yarn tsc -b 2>&1 | tail -40; then
    echo "[fix] ✗ tsc local echoue apres fix, rollback"
    cd "$PROJECT_DIR" && git checkout -- .
    exit 1
fi
echo "[fix] ✓ tsc local passe"

# --- Commit + push ---
cd "$PROJECT_DIR"
echo "[fix] Commit..."
# Stage modifications + nouveaux fichiers dans le scope (CRITICAL-2)
git add agentys-app/src agentys-app/e2e 2>/dev/null || true

if git diff --cached --quiet; then
    echo "[fix] Rien dans l'index (fichiers hors index ?), abandon"
    exit 3
fi

COMMIT_MSG="fix(build): auto-fix vercel iter $ITER

Auto-genere par vercel-build-monitor sur SHA ${SHA:0:8}.
[skip-monitor]"

if ! git commit -m "$COMMIT_MSG" 2>&1; then
    echo "[fix] ✗ git commit echoue"
    exit 4
fi

CURRENT_BRANCH=$(git branch --show-current)
echo "[fix] Push vers origin/$CURRENT_BRANCH..."
if ! git push origin "$CURRENT_BRANCH" 2>&1; then
    echo "[fix] ✗ git push echoue (probable non-fast-forward), soft-reset du commit local"
    # Fix adversarial HIGH-2 : reset le commit local pour laisser le repo dans
    # un etat coherent. Le prochain run de monitor pull + retente si pertinent.
    git reset --soft HEAD~1 || true
    exit 4
fi

NEW_SHA=$(git rev-parse HEAD)
echo "[fix] ✓ Fix applique et push : ${NEW_SHA:0:8}"
exit 0
