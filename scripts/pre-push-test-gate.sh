#!/usr/bin/env bash
# Pre-push test gate — lance les tests pytest impactés par les commits
# qu'on s'apprête à pousser. Bloque le push si un test échoue.
#
# Bypass : `git push --no-verify` OU `SKIP_TEST_GATE=1 git push`
# Désactivation : `git config hooks.test-gate.disabled true`
#
# Exit code 0 = OK / skip ; non-zero = bloque le push.
#
# N'utilise PAS stdin — détermine la branche cible via `git rev-parse @{push}`.
# Permet la coexistence avec d'autres hooks pre-push qui lisent stdin (ex.
# le bloc Vercel monitor qui écoute les refs poussées).
#
# Le mapping fichier → tests reflète la table de `.claude/commands/commit.md`
# Étape 2b. Les deux outils doivent rester synchronisés.

set -uo pipefail

# Bypass via env var.
if [ "${SKIP_TEST_GATE:-0}" = "1" ]; then
  echo "[test-gate] SKIP_TEST_GATE=1 — bypass volontaire"
  exit 0
fi

# Désactivé via git config.
if [ "$(git config --bool hooks.test-gate.disabled 2>/dev/null)" = "true" ]; then
  echo "[test-gate] désactivé via git config — bypass"
  exit 0
fi

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")"
if [ -z "$CURRENT_BRANCH" ] || [ "$CURRENT_BRANCH" = "HEAD" ]; then
  # Detached HEAD — pas notre cas d'usage.
  exit 0
fi

# Le gate ne s'applique qu'aux pushes vers main/develop. Pour les feature
# branches, on laisse passer (CI les couvre via le workflow PR).
case "$CURRENT_BRANCH" in
  main|develop) ;;
  *)
    echo "[test-gate] branche $CURRENT_BRANCH ≠ main/develop — skip"
    exit 0
    ;;
esac

# Compare HEAD à l'upstream (`@{u}`) — si non configuré, fallback origin/<branch>.
UPSTREAM="$(git rev-parse --abbrev-ref @{u} 2>/dev/null || echo "origin/$CURRENT_BRANCH")"
REMOTE_SHA="$(git rev-parse "$UPSTREAM" 2>/dev/null || echo "")"
LOCAL_SHA="$(git rev-parse HEAD)"

if [ -z "$REMOTE_SHA" ]; then
  echo "[test-gate] WARN : upstream $UPSTREAM introuvable — skip"
  exit 0
fi

if [ "$REMOTE_SHA" = "$LOCAL_SHA" ]; then
  echo "[test-gate] rien à pousser (HEAD == upstream) — skip"
  exit 0
fi

CHANGED_FILES="$(git diff --name-only "$REMOTE_SHA..$LOCAL_SHA" 2>/dev/null)"
if [ -z "$CHANGED_FILES" ]; then
  echo "[test-gate] aucun fichier modifié — skip"
  exit 0
fi

REPO_ROOT="$(git rev-parse --show-toplevel)"
PYTHON_GATE="$REPO_ROOT/scripts/pre-push-test-gate.py"

if [ ! -f "$PYTHON_GATE" ]; then
  echo "[test-gate] WARN : $PYTHON_GATE introuvable — skip"
  exit 0
fi

# Active venv si présent. Layouts différents :
#   - Linux/macOS : venv/bin/activate
#   - Windows (Git Bash) : venv/Scripts/activate
if [ -f "$REPO_ROOT/venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  . "$REPO_ROOT/venv/bin/activate"
elif [ -f "$REPO_ROOT/venv/Scripts/activate" ]; then
  # shellcheck disable=SC1091
  . "$REPO_ROOT/venv/Scripts/activate"
fi

# Sélectionne `python` ou `python3` selon ce qui existe (Windows ne livre
# habituellement que `python` ; macOS/Linux livrent les deux).
PYTHON_BIN=""
if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "[test-gate] WARN : ni python3 ni python trouvés — skip"
  exit 0
fi

echo "[test-gate] analyse des fichiers modifiés ($CURRENT_BRANCH ⇒ $UPSTREAM)..."
echo "$CHANGED_FILES" | "$PYTHON_BIN" "$PYTHON_GATE"
exit $?
