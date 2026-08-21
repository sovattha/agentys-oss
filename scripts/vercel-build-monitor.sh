#!/bin/bash
# =============================================================================
# Vercel Build Monitor — Surveille les builds Vercel post-push et auto-fix
#
# Declenche via .git/hooks/pre-push (fire-and-forget, detache). Poll Vercel
# pour le deployment du SHA push, attend la completion, et si ERROR invoque
# claude -p pour corriger les erreurs TS/ESLint/Vite.
#
# Max 3 iterations par SHA. Escalade via gh issue si echec final.
#
# Usage:
#   ./scripts/vercel-build-monitor.sh <sha>                   # Mode fix (defaut)
#   ./scripts/vercel-build-monitor.sh <sha> --dry-run         # Poll 1x, pas de fix
#   VERCEL_MONITOR_MODE=notify ./scripts/vercel-build-monitor.sh <sha>
#
# Prerequis : vercel, jq, claude, gh (pour escalade)
# =============================================================================

set -u
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPORT_DIR="$PROJECT_DIR/tasks/vercel-reports"
LOCK_DIR="$REPORT_DIR/.lock"

SHA="${1:-}"
DRY_RUN="false"
if [ "${2:-}" = "--dry-run" ]; then
    DRY_RUN="true"
fi

if [ -z "$SHA" ]; then
    echo "[ERROR] Usage: $0 <sha> [--dry-run]" >&2
    exit 1
fi

SHA8="${SHA:0:8}"
DATE=$(date +%Y-%m-%d)
TIME=$(date +%H%M)
REPORT_FILE="$REPORT_DIR/${DATE}_${TIME}_${SHA8}.md"
ITER_FILE="$REPORT_DIR/.iterations-${SHA}"

# --- Config ---
MODE="${VERCEL_MONITOR_MODE:-fix}"       # fix|notify
MAX_ITER=3
POLL_INTERVAL=30                          # secondes entre polls
POLL_TIMEOUT=900                          # 15 min max par iteration
GLOBAL_TIMEOUT=2700                       # 45 min max total
INITIAL_DELAY=20                          # attente initiale que Vercel recoive le push

mkdir -p "$REPORT_DIR"

# --- Lock atomique (mkdir) — un seul monitor a la fois ---
# Si un lock existe mais le PID est mort, on le nettoie (tolerance SIGKILL/crash)
if [ -d "$LOCK_DIR" ]; then
    LOCK_PID=$(cat "$LOCK_DIR/pid" 2>/dev/null || echo "")
    if [ -n "$LOCK_PID" ] && kill -0 "$LOCK_PID" 2>/dev/null; then
        echo "[monitor] Deja en cours (PID $LOCK_PID), abandon." >&2
        exit 0
    fi
    echo "[monitor] Lock obsolete (PID $LOCK_PID absent), reprise." >&2
    rm -rf "$LOCK_DIR"
fi
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    echo "[monitor] Course sur lock, abandon." >&2
    exit 0
fi
echo "$$" > "$LOCK_DIR/pid"
trap 'rm -rf "$LOCK_DIR"; exit' EXIT INT TERM

# --- Fonctions utilitaires ---

notify() {
    local title="$1" msg="$2"
    osascript -e "display notification \"$msg\" with title \"$title\"" 2>/dev/null || true
}

log() {
    local msg="$1"
    echo "[$(date +%H:%M:%S)] $msg" | tee -a "$REPORT_FILE" >&2
}

init_report() {
    cat > "$REPORT_FILE" <<EOF
# Vercel Build Monitor — $DATE $TIME

- **SHA** : \`$SHA\`
- **Mode** : \`$MODE\`
- **Branche** : \`$(git -C "$PROJECT_DIR" branch --show-current 2>/dev/null || echo '?')\`
- **Dry run** : \`$DRY_RUN\`

## Journal

EOF
}

get_iter() {
    [ -f "$ITER_FILE" ] && cat "$ITER_FILE" || echo "0"
}

incr_iter() {
    local current
    current=$(get_iter)
    echo $((current + 1)) > "$ITER_FILE"
}

# Retourne l'etat du deployment Vercel pour le SHA donne.
# Echo : "<state>|<url>" ou "NONE|" si pas trouve.
fetch_deployment_state() {
    local sha="$1"
    local json
    json=$(cd "$PROJECT_DIR" && vercel list --format json -y 2>/dev/null) || {
        echo "ERROR_CLI|"
        return
    }
    local deployment
    deployment=$(echo "$json" | jq -r --arg sha "$sha" '
        .deployments // []
        | map(select(.meta.githubCommitSha == $sha and .target == "production"))
        | sort_by(.createdAt)
        | last
        | if . then "\(.state)|\(.url)" else "NONE|" end
    ' 2>/dev/null)
    echo "${deployment:-NONE|}"
}

# Attend la completion du build pour le SHA. Retourne READY|ERROR|CANCELED|TIMEOUT|NOT_FOUND.
wait_deployment() {
    local sha="$1"
    local deadline=$(($(date +%s) + POLL_TIMEOUT))
    local last_state=""
    while [ "$(date +%s)" -lt "$deadline" ]; do
        local raw state url
        raw=$(fetch_deployment_state "$sha")
        state="${raw%%|*}"
        url="${raw##*|}"

        case "$state" in
            READY)
                echo "READY|$url"
                return
                ;;
            ERROR|CANCELED)
                echo "$state|$url"
                return
                ;;
            BUILDING|QUEUED|INITIALIZING)
                if [ "$state" != "$last_state" ]; then
                    log "  Etat Vercel : $state ($url)"
                    last_state="$state"
                fi
                ;;
            NONE|"")
                if [ "$last_state" != "NONE" ]; then
                    log "  Aucun deployment trouve pour $sha (pas encore declenche ?)"
                    last_state="NONE"
                fi
                ;;
            ERROR_CLI)
                log "  [warn] vercel CLI a echoue, retry dans ${POLL_INTERVAL}s"
                ;;
        esac

        sleep "$POLL_INTERVAL"
    done
    echo "TIMEOUT|"
}

fetch_logs() {
    local url="$1" out="$2"
    cd "$PROJECT_DIR" && vercel inspect "$url" --logs > "$out" 2>&1 || true
}

open_issue() {
    local title="$1" body_file="$2"
    if ! command -v gh &>/dev/null; then
        log "  [warn] gh CLI absent, escalade impossible"
        return
    fi
    cd "$PROJECT_DIR" && gh issue create \
        --title "$title" \
        --label "build,auto" \
        --body-file "$body_file" 2>&1 | tee -a "$REPORT_FILE" || true
}

# --- Main ---

init_report

# Anti-boucle absolue : si deja 3+ iter sur ce SHA, stop.
CURRENT_ITER=$(get_iter)
if [ "$CURRENT_ITER" -ge "$MAX_ITER" ]; then
    log "STOP : $CURRENT_ITER iter deja effectuees sur ce SHA (max $MAX_ITER). Voir $REPORT_FILE."
    notify "Agentys Vercel" "Monitor stop : max iter atteint pour $SHA8"
    exit 0
fi

# Skip si dernier commit tag [skip-monitor]
COMMIT_MSG=$(git -C "$PROJECT_DIR" log -1 --format=%B "$SHA" 2>/dev/null || echo "")
if echo "$COMMIT_MSG" | grep -q '\[skip-monitor\]'; then
    log "SKIP : commit message contient [skip-monitor]"
    exit 0
fi

log "Monitor demarre pour $SHA8 (mode=$MODE, pid=$$)"
notify "Agentys Vercel" "Monitor demarre : $SHA8"

log "Attente initiale ${INITIAL_DELAY}s (que Vercel recoive le push)"
sleep "$INITIAL_DELAY"

# --- Boucle principale ---
TRACKED_SHA="$SHA"
GLOBAL_DEADLINE=$(($(date +%s) + GLOBAL_TIMEOUT))

while true; do
    ITER=$(get_iter)
    if [ "$ITER" -ge "$MAX_ITER" ]; then
        log "STOP : $ITER iter deja effectuees sur ce SHA (max $MAX_ITER)."
        notify "Agentys Vercel" "Monitor stop : max iter atteint pour $SHA8"
        break
    fi
    NEXT_ITER=$((ITER + 1))

    if [ "$(date +%s)" -ge "$GLOBAL_DEADLINE" ]; then
        log "TIMEOUT global ${GLOBAL_TIMEOUT}s atteint, abandon."
        notify "Agentys Vercel" "Timeout global atteint pour $SHA8"
        break
    fi

    # Refresh COMMIT_MSG pour le SHA courant (fix adversarial LOW-1 :
    # l'anti-boucle doit verifier le message du HEAD courant, pas du SHA initial)
    COMMIT_MSG=$(git -C "$PROJECT_DIR" log -1 --format=%B "$TRACKED_SHA" 2>/dev/null || echo "")

    log "--- Iteration $NEXT_ITER/$MAX_ITER (SHA tracke : ${TRACKED_SHA:0:8}) ---"

    RESULT=$(wait_deployment "$TRACKED_SHA")
    STATE="${RESULT%%|*}"
    URL="${RESULT##*|}"

    log "Resultat : state=$STATE url=$URL"

    case "$STATE" in
        READY)
            log "✓ Build Vercel vert pour ${TRACKED_SHA:0:8}"
            notify "Agentys Vercel ✓" "Build vert : ${TRACKED_SHA:0:8}"
            break
            ;;
        CANCELED)
            log "Build annule, pas notre probleme, exit."
            notify "Agentys Vercel" "Build annule : ${TRACKED_SHA:0:8}"
            break
            ;;
        TIMEOUT)
            log "Poll timeout (${POLL_TIMEOUT}s) sans etat terminal, abandon iter."
            notify "Agentys Vercel" "Poll timeout : ${TRACKED_SHA:0:8}"
            break
            ;;
        ERROR)
            log "✗ Build Vercel casse : $URL"
            notify "Agentys Vercel ✗" "Build casse iter $NEXT_ITER, SHA ${TRACKED_SHA:0:8}"

            if [ "$DRY_RUN" = "true" ]; then
                log "Dry-run : on n'invoque pas le fix."
                break
            fi

            if [ "$MODE" = "notify" ]; then
                log "Mode notify : aucune action auto-fix."
                break
            fi

            # Recuperation logs
            LOGS_FILE="/tmp/vercel-logs-${TRACKED_SHA:0:8}-iter${NEXT_ITER}.txt"
            log "Recuperation logs vercel → $LOGS_FILE"
            fetch_logs "$URL" "$LOGS_FILE"
            if [ ! -s "$LOGS_FILE" ]; then
                log "[warn] Logs vides, fix impossible"
                break
            fi

            # Increment compteur AVANT appel claude
            incr_iter

            # Anti-boucle auto-agent : si le commit courant est deja un fix auto
            # et qu'on est a iter 3 → escalade directe.
            if [ "$NEXT_ITER" -ge "$MAX_ITER" ] && echo "$COMMIT_MSG" | grep -q "fix(build): auto"; then
                log "Anti-boucle : dernier commit est deja un auto-fix et iter max atteint."
                ISSUE_BODY="/tmp/vercel-issue-${SHA8}.md"
                {
                    echo "# Build Vercel casse apres $MAX_ITER tentatives auto"
                    echo ""
                    echo "SHA initial : \`$SHA\`"
                    echo "Dernier SHA : \`$TRACKED_SHA\`"
                    echo "URL Vercel : https://$URL"
                    echo ""
                    echo "## Rapport monitor"
                    echo ""
                    cat "$REPORT_FILE"
                    echo ""
                    echo "## Extrait logs Vercel"
                    echo ""
                    echo '```'
                    tail -80 "$LOGS_FILE"
                    echo '```'
                } > "$ISSUE_BODY"
                open_issue "Build Vercel casse (auto-fix $MAX_ITER/$MAX_ITER)" "$ISSUE_BODY"
                notify "Agentys Vercel ✗" "Escalade GitHub issue creee"
                break
            fi

            # Invocation fix
            log "Invocation vercel-build-fix.sh iter=$NEXT_ITER"
            if bash "$SCRIPT_DIR/vercel-build-fix.sh" "$LOGS_FILE" "$NEXT_ITER" "$TRACKED_SHA" 2>&1 | tee -a "$REPORT_FILE"; then
                NEW_SHA=$(git -C "$PROJECT_DIR" rev-parse HEAD)
                log "Fix applique, nouveau SHA : ${NEW_SHA:0:8}"
                notify "Agentys Vercel" "Fix push, attente build iter $NEXT_ITER"
                TRACKED_SHA="$NEW_SHA"
                # Petite pause pour laisser Vercel recevoir le push
                sleep "$INITIAL_DELAY"
            else
                log "✗ Fix echoue (exit $?)"
                notify "Agentys Vercel" "Fix iter $NEXT_ITER echoue"
                # Si c'etait la derniere tentative, escalade
                if [ "$NEXT_ITER" -ge "$MAX_ITER" ]; then
                    ISSUE_BODY="/tmp/vercel-issue-${SHA8}.md"
                    {
                        echo "# Build Vercel casse apres $MAX_ITER tentatives auto"
                        echo ""
                        echo "SHA initial : \`$SHA\`"
                        echo "URL Vercel : https://$URL"
                        echo ""
                        echo "## Rapport monitor"
                        echo ""
                        cat "$REPORT_FILE"
                    } > "$ISSUE_BODY"
                    open_issue "Build Vercel casse (auto-fix $MAX_ITER/$MAX_ITER)" "$ISSUE_BODY"
                    notify "Agentys Vercel ✗" "Escalade GitHub issue creee"
                fi
                break
            fi
            ;;
        *)
            log "Etat inconnu '$STATE', abandon"
            break
            ;;
    esac
done

# --- Fin ---
log "Monitor termine."

# Nettoyage fichier iter si succes (permet un nouveau cycle si le SHA est repush)
if [ "$STATE" = "READY" ] || [ "$STATE" = "CANCELED" ]; then
    rm -f "$ITER_FILE"
fi

exit 0
