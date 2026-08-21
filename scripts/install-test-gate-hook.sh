#!/usr/bin/env bash
# Installe le test-gate dans .git/hooks/pre-push (idempotent).
# Coexiste avec le bloc Vercel monitor déjà présent (n'utilise pas stdin).

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
HOOK_FILE="$REPO_ROOT/.git/hooks/pre-push"
TEST_GATE_SCRIPT="$REPO_ROOT/scripts/pre-push-test-gate.sh"

if [ ! -f "$TEST_GATE_SCRIPT" ]; then
  echo "ERR : $TEST_GATE_SCRIPT introuvable" >&2
  exit 1
fi

chmod +x "$TEST_GATE_SCRIPT" "$REPO_ROOT/scripts/pre-push-test-gate.py"

# Crée le hook s'il n'existe pas, avec un shebang.
if [ ! -f "$HOOK_FILE" ]; then
  echo "#!/bin/sh" > "$HOOK_FILE"
  chmod +x "$HOOK_FILE"
fi

# Sélectionne python disponible (Windows ne livre habituellement que `python`).
PYTHON_BIN=""
if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "ERR : python introuvable" >&2
  exit 1
fi

# Idempotence : retire un éventuel ancien bloc avant de réécrire.
if grep -q "AGENTYS_TEST_GATE_START" "$HOOK_FILE"; then
  "$PYTHON_BIN" - "$HOOK_FILE" <<'PY'
import sys
path = sys.argv[1]
src = open(path).read()
start = "# AGENTYS_TEST_GATE_START"
end = "# AGENTYS_TEST_GATE_END"
if start in src and end in src:
    s = src.index(start)
    e = src.index(end) + len(end)
    src = src[:s].rstrip() + "\n\n" + src[e:].lstrip()
    open(path, "w").write(src)
PY
fi

# Append. Le bloc s'exécute AVANT les autres hooks et peut bloquer le push
# en exit non-zero. Il n'utilise pas stdin → pas de collision avec les
# blocs qui lisent les refs poussées (ex. vercel monitor).
{
  echo ""
  echo "# AGENTYS_TEST_GATE_START"
  echo "# Pre-push test gate — empêche les tests stales de partir en CI."
  echo "# Désactiver durablement : git config hooks.test-gate.disabled true"
  echo "# Bypass ponctuel        : SKIP_TEST_GATE=1 git push"
  echo "if [ \"\$(git config --bool hooks.test-gate.disabled 2>/dev/null)\" != \"true\" ]; then"
  # Invoque via bash explicite — sur Windows (Git Bash), le bit +x sur NTFS"
  # est fragile et le shebang peut ne pas être respecté. Forcer bash garantit"
  # l'exécution même si chmod n'a pas pris."
  echo "  bash \"$TEST_GATE_SCRIPT\" </dev/null || exit \$?"
  echo "fi"
  echo "# AGENTYS_TEST_GATE_END"
} >> "$HOOK_FILE"

chmod +x "$HOOK_FILE"

echo "✓ test-gate installé dans $HOOK_FILE"
echo ""
echo "Désactiver durablement : git config hooks.test-gate.disabled true"
echo "Bypass ponctuel        : SKIP_TEST_GATE=1 git push"
echo ""
echo "Coéquipiers : chacun doit relancer ce script après clone (les .git/hooks"
echo "ne sont pas versionnés). À documenter dans le README."
