#!/bin/bash
# Agentys Docker Entrypoint
# Gère le setup initial et le lancement de l'application

set -e

# Couleurs pour l'affichage
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

log_info() { echo -e "${CYAN}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# SECURITY (audit 2026-05-29, CWE-250): the container starts as root so it can
# chown the (root-owned) Railway volume; we then drop to the non-root 'agentys'
# user for the actual long-running process. Falls back to the current user if
# gosu/the user is unavailable, so a missing tool can never crash-loop the box.
drop_privs_exec() {
    chown -R agentys:agentys /app/data /app/logs /app/agents 2>/dev/null || true
    if [ "$(id -u)" = "0" ] && command -v gosu >/dev/null 2>&1 && id agentys >/dev/null 2>&1; then
        exec gosu agentys "$@"
    fi
    [ "$(id -u)" = "0" ] && log_warning "Running as root (gosu/user unavailable) — non-root drop skipped"
    exec "$@"
}

# Chemin vers le .env (monté depuis l'hôte)
ENV_FILE="/app/.env"
ENV_EXAMPLE="/app/.env.example"

# =============================================================================
# FONCTION: Créer le .env s'il n'existe pas
# =============================================================================
create_env_if_needed() {
    if [ ! -f "$ENV_FILE" ]; then
        log_warning "Fichier .env non trouvé"

        if [ -f "$ENV_EXAMPLE" ]; then
            log_info "Création depuis .env.example..."
            cp "$ENV_EXAMPLE" "$ENV_FILE"
            log_success ".env créé"
        else
            log_info "Création d'un .env minimal..."
            cat > "$ENV_FILE" << 'EOF'
# Agentys Configuration
# Généré automatiquement par Docker

# LLM Provider
LLM_PROVIDER=claude
LLM_MODEL=claude-sonnet-4-6

# Email Provider
EMAIL_PROVIDER_TYPE=IMAP_SMTP

# Obligatoire: Clé API Anthropic
ANTHROPIC_API_KEY=

# IMAP Configuration (pour EMAIL_PROVIDER_TYPE=IMAP_SMTP)
IMAP_HOST=imap.gmail.com
IMAP_PORT=993
IMAP_USER=
IMAP_PASSWORD=
IMAP_USE_SSL=true

# SMTP Configuration
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
SMTP_USE_TLS=true
EOF
            log_success ".env minimal créé"
        fi
    else
        log_success ".env existant trouvé"
    fi
}

# =============================================================================
# FONCTION: Mettre à jour une variable dans le .env
# =============================================================================
update_env_var() {
    local key="$1"
    local value="$2"

    if [ -z "$value" ]; then
        return
    fi

    # Échapper les caractères spéciaux
    local escaped_value=$(printf '%s\n' "$value" | sed 's/[&/\]/\\&/g')

    if grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
        # Mettre à jour la variable existante
        sed -i "s|^${key}=.*|${key}=${escaped_value}|" "$ENV_FILE"
    else
        # Ajouter la nouvelle variable
        echo "${key}=${value}" >> "$ENV_FILE"
    fi
}

# =============================================================================
# FONCTION: Setup interactif (mode setup)
# =============================================================================
interactive_setup() {
    log_info "Mode setup interactif"
    echo ""

    create_env_if_needed

    # Charger le .env actuel
    source "$ENV_FILE" 2>/dev/null || true

    echo "=============================================="
    echo "       Agentys - Configuration Docker"
    echo "=============================================="
    echo ""

    # LLM Provider
    echo -e "${CYAN}1. Configuration LLM${NC}"
    read -p "Provider LLM [${LLM_PROVIDER:-claude}]: " input_llm_provider
    LLM_PROVIDER="${input_llm_provider:-${LLM_PROVIDER:-claude}}"
    update_env_var "LLM_PROVIDER" "$LLM_PROVIDER"

    if [ "$LLM_PROVIDER" = "claude" ]; then
        read -p "Clé API Anthropic [${ANTHROPIC_API_KEY:+****...}]: " input_api_key
        if [ -n "$input_api_key" ]; then
            update_env_var "ANTHROPIC_API_KEY" "$input_api_key"
        fi
    fi

    echo ""

    # Email Provider
    echo -e "${CYAN}2. Configuration Email${NC}"
    echo "Types disponibles: GMAIL, OUTLOOK, IMAP_SMTP"
    read -p "Provider Email [${EMAIL_PROVIDER_TYPE:-IMAP_SMTP}]: " input_email_provider
    EMAIL_PROVIDER_TYPE="${input_email_provider:-${EMAIL_PROVIDER_TYPE:-IMAP_SMTP}}"
    update_env_var "EMAIL_PROVIDER_TYPE" "$EMAIL_PROVIDER_TYPE"

    if [ "$EMAIL_PROVIDER_TYPE" = "IMAP_SMTP" ] || [ "$EMAIL_PROVIDER_TYPE" = "IMAP" ]; then
        echo ""
        echo "Configuration IMAP:"
        read -p "  Serveur IMAP [${IMAP_HOST:-imap.gmail.com}]: " input
        update_env_var "IMAP_HOST" "${input:-${IMAP_HOST:-imap.gmail.com}}"

        read -p "  Port IMAP [${IMAP_PORT:-993}]: " input
        update_env_var "IMAP_PORT" "${input:-${IMAP_PORT:-993}}"

        read -p "  Email/Utilisateur [${IMAP_USER}]: " input
        [ -n "$input" ] && update_env_var "IMAP_USER" "$input"

        read -sp "  Mot de passe [caché]: " input
        echo ""
        [ -n "$input" ] && update_env_var "IMAP_PASSWORD" "$input"
    fi

    if [ "$EMAIL_PROVIDER_TYPE" = "IMAP_SMTP" ] || [ "$EMAIL_PROVIDER_TYPE" = "SMTP" ]; then
        echo ""
        echo "Configuration SMTP:"
        read -p "  Serveur SMTP [${SMTP_HOST:-smtp.gmail.com}]: " input
        update_env_var "SMTP_HOST" "${input:-${SMTP_HOST:-smtp.gmail.com}}"

        read -p "  Port SMTP [${SMTP_PORT:-587}]: " input
        update_env_var "SMTP_PORT" "${input:-${SMTP_PORT:-587}}"

        # Utiliser les mêmes credentials que IMAP si non spécifié
        read -p "  Email/Utilisateur [${SMTP_USER:-${IMAP_USER}}]: " input
        update_env_var "SMTP_USER" "${input:-${SMTP_USER:-${IMAP_USER}}}"

        if [ -z "$SMTP_PASSWORD" ]; then
            read -sp "  Mot de passe [identique à IMAP si vide]: " input
            echo ""
            [ -n "$input" ] && update_env_var "SMTP_PASSWORD" "$input"
        fi
    fi

    if [ "$EMAIL_PROVIDER_TYPE" = "GMAIL" ]; then
        echo ""
        echo "Configuration Gmail OAuth:"
        read -p "  Client ID [${GOOGLE_CLIENT_ID:+****}]: " input
        [ -n "$input" ] && update_env_var "GOOGLE_CLIENT_ID" "$input"

        read -p "  Client Secret [${GOOGLE_CLIENT_SECRET:+****}]: " input
        [ -n "$input" ] && update_env_var "GOOGLE_CLIENT_SECRET" "$input"

        read -p "  Refresh Token [${GOOGLE_REFRESH_TOKEN:+****}]: " input
        [ -n "$input" ] && update_env_var "GOOGLE_REFRESH_TOKEN" "$input"
    fi

    echo ""
    log_success "Configuration sauvegardée dans $ENV_FILE"
    echo ""
    echo "Pour démarrer Agentys, lancez:"
    echo "  docker-compose up -d agentys"
    echo ""
}

# =============================================================================
# FONCTION: Vérification de la configuration
# =============================================================================
check_config() {
    log_info "Vérification de la configuration..."

    local errors=0

    # Charger le .env
    if [ -f "$ENV_FILE" ]; then
        source "$ENV_FILE"
    else
        log_error ".env non trouvé"
        return 1
    fi

    # Vérifier LLM
    if [ "$LLM_PROVIDER" = "claude" ] && [ -z "$ANTHROPIC_API_KEY" ]; then
        log_warning "ANTHROPIC_API_KEY non configuré"
        errors=$((errors + 1))
    fi

    # Vérifier Email
    if [ -z "$EMAIL_PROVIDER_TYPE" ]; then
        log_warning "EMAIL_PROVIDER_TYPE non configuré"
        errors=$((errors + 1))
    fi

    if [ $errors -eq 0 ]; then
        log_success "Configuration OK"
        return 0
    else
        log_warning "$errors avertissement(s)"
        return 0  # Continue quand même
    fi
}

# =============================================================================
# FONCTION: Afficher l'aide
# =============================================================================
show_help() {
    echo "Agentys Docker Entrypoint"
    echo ""
    echo "Usage: docker-compose run --rm agentys [COMMAND]"
    echo ""
    echo "Commands:"
    echo "  setup       Lance le setup interactif pour configurer le .env"
    echo "  check       Vérifie la configuration"
    echo "  api         Lance l'API REST (pour Railway/production)"
    echo "  daemon      Lance le daemon (par défaut)"
    echo "  help        Affiche cette aide"
    echo ""
    echo "Exemples:"
    echo "  docker-compose run --rm agentys setup   # Configurer"
    echo "  docker-compose up -d agentys            # Démarrer le daemon"
    echo ""
}

# =============================================================================
# MAIN
# =============================================================================

# Créer les répertoires nécessaires
mkdir -p /app/data /app/logs /app/agents

# Traitement de la commande
COMMAND="${1:-daemon}"

case "$COMMAND" in
    setup)
        interactive_setup
        ;;
    check)
        create_env_if_needed
        check_config
        ;;
    api)
        create_env_if_needed
        if check_config; then
            log_info "Démarrage de l'API REST Agentys..."
            drop_privs_exec python run_api.py
        else
            log_error "Configuration incomplète."
            exit 1
        fi
        ;;
    daemon)
        create_env_if_needed
        if check_config; then
            log_info "Démarrage du daemon Agentys..."
            drop_privs_exec python run_daemon.py
        else
            log_error "Configuration incomplète. Lancez 'docker-compose run --rm agentys setup' d'abord."
            exit 1
        fi
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        # Commande personnalisée
        exec "$@"
        ;;
esac
