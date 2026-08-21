#!/bin/bash
# =============================================================================
# Install Vercel Build Monitor
#
# Installe le hook pre-push qui lance vercel-build-monitor.sh en arriere-plan
# apres chaque push vers main. Idempotent : re-lancer ne casse rien.
#
# Usage:
#   ./scripts/install-vercel-monitor.sh             # Installe
#   ./scripts/install-vercel-monitor.sh --uninstall # Desinstalle
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
# Resout le repertoire .git (peut etre un worktree)
GIT_DIR=$(git -C "$PROJECT_DIR" rev-parse --git-dir 2>/dev/null || true)
if [ -z "$GIT_DIR" ]; then
    echo "[install] ERROR : pas un repo git"
    exit 1
fi
# Toplevel git (hook doit pointer vers le main repo, pas le worktree .git/worktrees/)
GIT_COMMON_DIR=$(git -C "$PROJECT_DIR" rev-parse --git-common-dir 2>/dev/null || echo "$GIT_DIR")
HOOK_FILE="$GIT_COMMON_DIR/hooks/pre-push"
MARKER="# AGENTYS_VERCEL_MONITOR_START"
MARKER_END="# AGENTYS_VERCEL_MONITOR_END"

if [ "${1:-}" = "--uninstall" ]; then
    if [ ! -f "$HOOK_FILE" ]; then
        echo "[install] aucun hook pre-push present"
        exit 0
    fi
    if ! grep -q "$MARKER" "$HOOK_FILE"; then
        echo "[install] hook pre-push present mais pas de bloc agentys a retirer"
        exit 0
    fi
    # Supprime le bloc marque
    TMP=$(mktemp)
    awk -v start="$MARKER" -v end="$MARKER_END" '
        $0 ~ start { skip=1; next }
        $0 ~ end   { skip=0; next }
        !skip
    ' "$HOOK_FILE" > "$TMP"
    mv "$TMP" "$HOOK_FILE"
    chmod +x "$HOOK_FILE"
    echo "[install] ✓ bloc agentys retire de $HOOK_FILE"
    exit 0
fi

echo "[install] ===== Installation Vercel Build Monitor ====="
echo "[install] Project : $PROJECT_DIR"
echo "[install] Hook    : $HOOK_FILE"

# --- 1. Verif CLIs ---
echo "[install] Verification CLIs..."
missing=()
for cli in vercel gh jq claude; do
    if ! command -v "$cli" &>/dev/null; then
        missing+=("$cli")
    fi
done
if [ ${#missing[@]} -gt 0 ]; then
    echo "[install] ✗ CLIs manquants : ${missing[*]}"
    echo "[install]   Install :"
    echo "[install]     brew install vercel-cli gh jq"
    echo "[install]     curl -fsSL https://claude.ai/install.sh | sh"
    exit 1
fi
echo "[install] ✓ vercel, gh, jq, claude presents"

# --- 2. Verif vercel authentifie ---
if ! vercel whoami &>/dev/null; then
    echo "[install] ✗ vercel non authentifie → vercel login"
    exit 1
fi
echo "[install] ✓ vercel authentifie : $(vercel whoami 2>/dev/null)"

# --- 3. Verif project lie ---
if [ ! -f "$PROJECT_DIR/.vercel/project.json" ]; then
    echo "[install] ✗ $PROJECT_DIR/.vercel/project.json absent → lancer 'vercel link' depuis la racine"
    exit 1
fi
echo "[install] ✓ projet Vercel lie : $(jq -r .projectName "$PROJECT_DIR/.vercel/project.json")"

# --- 4. chmod scripts ---
chmod +x "$SCRIPT_DIR/vercel-build-monitor.sh"
chmod +x "$SCRIPT_DIR/vercel-build-fix.sh"
chmod +x "$SCRIPT_DIR/prompts/vercel-fix-user.sh"
echo "[install] ✓ scripts executables"

# --- 5. Dossier reports ---
mkdir -p "$PROJECT_DIR/tasks/vercel-reports"
echo "[install] ✓ tasks/vercel-reports/ present"

# --- 6. Hook pre-push ---
mkdir -p "$(dirname "$HOOK_FILE")"

# Resolution du chemin absolu du monitor a l'install (pas au runtime du hook).
# Fix adversarial review CRITICAL-1 : `git rev-parse --git-common-dir` retourne
# un chemin relatif au cwd, donc embedding a runtime cassait la resolution.
MONITOR_ABS_PATH=$(cd "$SCRIPT_DIR" && pwd)/vercel-build-monitor.sh
if [ ! -x "$MONITOR_ABS_PATH" ]; then
    echo "[install] ✗ monitor introuvable ou non-executable : $MONITOR_ABS_PATH"
    exit 1
fi

HOOK_BLOCK="$MARKER
# Agentys Vercel Build Monitor — fire-and-forget sur push vers main
# Installer : $SCRIPT_DIR/install-vercel-monitor.sh
if [ \"\$(git config --bool hooks.vercel-monitor.disabled 2>/dev/null)\" != \"true\" ]; then
  while read _local_ref _local_sha _remote_ref _remote_sha; do
    case \"\$_remote_ref\" in
      refs/heads/main)
        if git log -1 --format=%B \"\$_local_sha\" 2>/dev/null | grep -q '\[skip-monitor\]'; then
          echo \"[vercel-monitor] skip ([skip-monitor] detecte)\"
          continue
        fi
        _monitor=\"$MONITOR_ABS_PATH\"
        if [ -x \"\$_monitor\" ]; then
          nohup \"\$_monitor\" \"\$_local_sha\" </dev/null >/dev/null 2>&1 &
          disown
          echo \"[vercel-monitor] demarre pour \${_local_sha:0:8} (PID \$!)\"
        else
          echo \"[vercel-monitor] WARN : \$_monitor introuvable, hook installe mais inactif\" >&2
        fi
        ;;
    esac
  done
fi
$MARKER_END"

# S'assurer que le fichier a un shebang
ensure_shebang() {
    if [ ! -s "$HOOK_FILE" ] || ! head -1 "$HOOK_FILE" | grep -q '^#!'; then
        TMP=$(mktemp)
        echo "#!/bin/sh" > "$TMP"
        [ -s "$HOOK_FILE" ] && cat "$HOOK_FILE" >> "$TMP"
        mv "$TMP" "$HOOK_FILE"
    fi
}

if [ ! -f "$HOOK_FILE" ] || [ ! -s "$HOOK_FILE" ]; then
    # Nouveau hook
    cat > "$HOOK_FILE" <<EOF
#!/bin/sh
$HOOK_BLOCK
EOF
    chmod +x "$HOOK_FILE"
    echo "[install] ✓ hook pre-push cree : $HOOK_FILE"
else
    # Si bloc deja present, on le retire d'abord (awk single-marker)
    # puis on append la nouvelle version. Plus robuste que awk avec une
    # variable multiline (qui casse sur certains awk).
    if grep -q "$MARKER" "$HOOK_FILE"; then
        TMP=$(mktemp)
        awk -v start="$MARKER" -v end="$MARKER_END" '
            $0 ~ start { skip=1; next }
            $0 ~ end   { skip=0; next }
            !skip
        ' "$HOOK_FILE" > "$TMP"
        mv "$TMP" "$HOOK_FILE"
    fi
    ensure_shebang
    {
        echo ""
        echo "$HOOK_BLOCK"
    } >> "$HOOK_FILE"
    chmod +x "$HOOK_FILE"
    echo "[install] ✓ bloc agentys ajoute/mis a jour dans $HOOK_FILE"
fi

echo ""
echo "[install] ===== Installation terminee ====="
echo ""
echo "  Activation   : automatique sur git push vers main"
echo "  Desactivation: git config hooks.vercel-monitor.disabled true"
echo "  Skip ponctuel: git commit -m '... [skip-monitor]'"
echo "  Uninstall    : $0 --uninstall"
echo "  Mode notify  : export VERCEL_MONITOR_MODE=notify"
echo ""
echo "  Test dry-run : $SCRIPT_DIR/vercel-build-monitor.sh \$(git rev-parse HEAD) --dry-run"
