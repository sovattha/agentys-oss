#!/bin/bash
#
# Script d'installation Agentys pour Mac/Linux
#
# Usage:
#   ./install.sh          # Installation standard
#   ./install.sh --dev    # Installation avec dépendances de développement
#   ./install.sh --docker # Prépare pour Docker
#

set -e

# Couleurs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Variables
PYTHON_MIN_VERSION="3.10"
INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$INSTALL_DIR/venv"
DEV_MODE=false
DOCKER_MODE=false

# Fonctions utilitaires
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Parse les arguments
for arg in "$@"; do
    case $arg in
        --dev)
            DEV_MODE=true
            shift
            ;;
        --docker)
            DOCKER_MODE=true
            shift
            ;;
        --help|-h)
            echo "Usage: ./install.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --dev       Install development dependencies"
            echo "  --docker    Prepare for Docker installation"
            echo "  --help      Show this help message"
            exit 0
            ;;
    esac
done

# Bannière
echo ""
echo -e "${BLUE}╔═══════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║${NC}         ${GREEN}Agentys Installation${NC}            ${BLUE}║${NC}"
echo -e "${BLUE}║${NC}     Pipeline Multi-Agents IA pour Email   ${BLUE}║${NC}"
echo -e "${BLUE}╚═══════════════════════════════════════════╝${NC}"
echo ""

# Vérifier Python
log_info "Vérification de Python..."
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
else
    log_error "Python n'est pas installé. Veuillez installer Python $PYTHON_MIN_VERSION ou supérieur."
    exit 1
fi

PYTHON_VERSION=$($PYTHON_CMD -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
log_success "Python $PYTHON_VERSION trouvé"

# Vérifier la version de Python
PYTHON_MAJOR=$($PYTHON_CMD -c 'import sys; print(sys.version_info[0])')
PYTHON_MINOR=$($PYTHON_CMD -c 'import sys; print(sys.version_info[1])')

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 10 ]); then
    log_error "Python $PYTHON_MIN_VERSION ou supérieur est requis. Version actuelle: $PYTHON_VERSION"
    exit 1
fi

# Mode Docker
if [ "$DOCKER_MODE" = true ]; then
    log_info "Mode Docker activé - préparation..."

    if ! command -v docker &> /dev/null; then
        log_error "Docker n'est pas installé. Veuillez installer Docker."
        exit 1
    fi

    log_success "Docker trouvé"
    log_info "Pour lancer avec Docker, utilisez:"
    echo "  docker-compose up -d"
    exit 0
fi

# Créer l'environnement virtuel
log_info "Création de l'environnement virtuel..."
if [ -d "$VENV_DIR" ]; then
    log_warning "Environnement virtuel existant trouvé"
    read -p "Voulez-vous le recréer? (o/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Oo]$ ]]; then
        rm -rf "$VENV_DIR"
        $PYTHON_CMD -m venv "$VENV_DIR"
    fi
else
    $PYTHON_CMD -m venv "$VENV_DIR"
fi
log_success "Environnement virtuel créé"

# Activer l'environnement virtuel
log_info "Activation de l'environnement virtuel..."
source "$VENV_DIR/bin/activate"

# Mettre à jour pip
log_info "Mise à jour de pip..."
pip install --upgrade pip > /dev/null 2>&1

# Installer les dépendances
log_info "Installation des dépendances..."
pip install -r "$INSTALL_DIR/requirements.txt"
log_success "Dépendances installées"

# Installer les dépendances de développement si demandé
if [ "$DEV_MODE" = true ]; then
    log_info "Installation des dépendances de développement..."
    pip install pytest pytest-cov black flake8 mypy
    log_success "Dépendances de développement installées"
fi

# Créer les répertoires nécessaires
log_info "Création des répertoires..."
mkdir -p "$INSTALL_DIR/data"
mkdir -p "$INSTALL_DIR/logs"
mkdir -p "$INSTALL_DIR/knowledge"
mkdir -p "$INSTALL_DIR/agents"

# Créer le fichier .env s'il n'existe pas
if [ ! -f "$INSTALL_DIR/.env" ]; then
    log_info "Création du fichier .env..."
    cat > "$INSTALL_DIR/.env" << EOF
# Configuration Agentys
# Copiez ce fichier et remplissez les valeurs

# LLM Provider (claude ou ollama)
LLM_PROVIDER=claude
LLM_MODEL=claude-opus-4-7

# Clé API Anthropic (requis si LLM_PROVIDER=claude)
ANTHROPIC_API_KEY=

# Email Provider (GMAIL, OUTLOOK, ou IMAP)
EMAIL_PROVIDER_TYPE=GMAIL

# Intervalle de polling en secondes
DAEMON_POLL_INTERVAL=60

# Budget mensuel (USD)
MONTHLY_BUDGET_USD=50

# Notifications
NOTIFICATIONS_ENABLED=true
EOF
    log_success "Fichier .env créé"
fi

# Créer le fichier de mémoire s'il n'existe pas
if [ ! -f "$INSTALL_DIR/knowledge/memoire.md" ]; then
    log_info "Création du fichier de mémoire..."
    cat > "$INSTALL_DIR/knowledge/memoire.md" << EOF
# Base de Connaissances Agentys

## Informations Générales

Bienvenue dans Agentys. Cette base de connaissances contient les informations
que l'IA utilisera pour générer des réponses personnalisées.

## Style de Réponse

- Ton professionnel et courtois
- Réponses concises mais complètes
- Toujours proposer de l'aide supplémentaire

## FAQ

Ajoutez ici les questions fréquentes et leurs réponses.

---
*Modifiez ce fichier pour personnaliser le comportement de l'IA.*
EOF
    log_success "Fichier de mémoire créé"
fi

# Instructions finales
echo ""
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Installation terminée avec succès!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
echo ""
echo "Prochaines étapes:"
echo ""
echo "1. Configurez votre fichier .env:"
echo "   nano .env"
echo ""
echo "2. Lancez le setup interactif:"
echo "   source venv/bin/activate"
echo "   python setup.py"
echo ""
echo "3. Démarrez le daemon:"
echo "   python run_daemon.py"
echo ""
echo "4. (Optionnel) Lancez le dashboard:"
echo "   python -c 'from app.dashboard import run_dashboard; run_dashboard()'"
echo ""
echo -e "${BLUE}Documentation: https://github.com/votre-repo/agentys${NC}"
echo ""
