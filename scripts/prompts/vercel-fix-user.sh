#!/bin/bash
# =============================================================================
# Genere le prompt user pour vercel-build-fix.sh
# Args : $1=logs_file $2=iter $3=sha
# Sortie sur stdout : prompt markdown multi-ligne
#
# Securite : on ne fait PAS de heredoc non-quote sur les logs Vercel (sinon
# shell injection via $PATH, backticks, etc. dans les logs). On assemble le
# prompt via printf + concatenation pure, les logs passent par printf "%s".
# =============================================================================

set -u

LOGS_FILE="$1"
ITER="$2"
SHA="$3"

# Troncature preventive : on garde les 400 dernieres lignes des logs
# (suffisant pour capturer les erreurs TS/ESLint de build Vercel).
LOGS_CONTENT=$(tail -400 "$LOGS_FILE")

# Header — heredoc quote pour garantir pas d'interpolation sur le texte fixe
cat <<'HEADER_EOF'
# Build Vercel casse

## Logs Vercel (bruts)

```
HEADER_EOF

# Logs — passes via printf "%s" pour neutraliser toute interpolation
printf '%s\n' "$LOGS_CONTENT"

# Footer avec variables controlees (SHA/ITER sont des entrees du monitor,
# deja filtrees : SHA ne contient que [0-9a-f], ITER est un nombre)
printf -- '```\n\n'
printf -- '## Contexte\n\n'
printf -- '- Commit : `%s`\n' "$SHA"
printf -- '- Iteration : %s / 3\n\n' "$ITER"
cat <<'TAIL_EOF'
## Instructions

1. Parse uniquement les erreurs du perimetre autorise (voir system prompt).
2. Pour chaque erreur :
   - Lis le fichier concerne avec `Read`
   - Applique un `Edit` minimal
3. Valide avec `cd agentys-app && yarn tsc -b`.
4. Si tsc passe → ecris le JSON de resume.
5. Si tsc echoue → refix puis revalide (max 3 tentatives).

Tu as l'autorisation d'editer les fichiers directement sans confirmation.
Ne fais PAS de git commit ni git push : un script s'en charge apres toi.
TAIL_EOF
