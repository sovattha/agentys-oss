# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Gestion des erreurs explicites pour Agentys.

Ce module fournit:
- Des messages d'erreur clairs et actionnables
- Des suggestions de résolution
- Des codes d'erreur standardisés
- Un formatage cohérent des erreurs

Usage:
    from app.infrastructure.errors import (
        AgentysError,
        AuthenticationError,
        format_error,
        get_resolution,
    )

    try:
        authenticate()
    except AuthenticationError as e:
        print(format_error(e))
"""

import logging
import traceback
from typing import Optional, Dict, Any
from enum import Enum

logger = logging.getLogger(__name__)


# ============================================================================
# CODES D'ERREUR
# ============================================================================

class ErrorCode(Enum):
    """Codes d'erreur standardisés."""

    # Authentification (AUTH_xxx)
    AUTH_001 = "AUTH_001"  # Token Gmail expiré
    AUTH_002 = "AUTH_002"  # Credentials Outlook invalides
    AUTH_003 = "AUTH_003"  # Token refresh échoué
    AUTH_004 = "AUTH_004"  # Fichier token manquant
    AUTH_005 = "AUTH_005"  # Permissions insuffisantes

    # API LLM (LLM_xxx)
    LLM_001 = "LLM_001"    # Rate limit dépassé
    LLM_002 = "LLM_002"    # API surchargée
    LLM_003 = "LLM_003"    # Clé API invalide
    LLM_004 = "LLM_004"    # Timeout
    LLM_005 = "LLM_005"    # Réponse invalide
    LLM_006 = "LLM_006"    # Budget dépassé

    # Email (EMAIL_xxx)
    EMAIL_001 = "EMAIL_001"  # Création brouillon échouée
    EMAIL_002 = "EMAIL_002"  # Récupération emails échouée
    EMAIL_003 = "EMAIL_003"  # Email invalide
    EMAIL_004 = "EMAIL_004"  # Pièce jointe trop grande

    # Configuration (CFG_xxx)
    CFG_001 = "CFG_001"    # Variable env manquante
    CFG_002 = "CFG_002"    # Valeur config invalide
    CFG_003 = "CFG_003"    # Fichier config manquant

    # Base de données (DB_xxx)
    DB_001 = "DB_001"      # Base verrouillée
    DB_002 = "DB_002"      # Corruption détectée
    DB_003 = "DB_003"      # Migration échouée

    # Réseau (NET_xxx)
    NET_001 = "NET_001"    # Connexion refusée
    NET_002 = "NET_002"    # DNS résolution échouée
    NET_003 = "NET_003"    # SSL/TLS erreur

    # Générique
    UNKNOWN = "UNKNOWN"    # Erreur inconnue


# ============================================================================
# RÉSOLUTIONS SUGGÉRÉES
# ============================================================================

RESOLUTIONS: Dict[ErrorCode, Dict[str, Any]] = {
    ErrorCode.AUTH_001: {
        "title": "Token Gmail expiré",
        "description": "Le token d'authentification Gmail a expiré ou a été révoqué.",
        "steps": [
            "Supprimer le fichier token.json",
            "Relancer l'application",
            "Suivre le flux OAuth dans le navigateur",
        ],
        "commands": [
            "rm token.json",
            "python run_daemon.py",
        ],
        "doc_link": "docs/TROUBLESHOOTING.md#gmail---tokenjson-invalide-ou-corrompu",
    },
    ErrorCode.AUTH_002: {
        "title": "Credentials Outlook invalides",
        "description": "Les credentials Azure AD sont invalides ou mal configurés.",
        "steps": [
            "Vérifier AZURE_TENANT_ID dans .env",
            "Vérifier AZURE_CLIENT_ID dans .env",
            "Vérifier AZURE_CLIENT_SECRET dans .env",
            "Vérifier les permissions dans Azure AD (Mail.ReadWrite, Mail.Send)",
        ],
        "commands": [
            "cat .env | grep AZURE",
        ],
        "doc_link": "docs/TROUBLESHOOTING.md#outlook---erreur-401-unauthorized",
    },
    ErrorCode.AUTH_003: {
        "title": "Échec refresh token",
        "description": "Impossible de rafraîchir le token d'authentification.",
        "steps": [
            "Le token a peut-être été révoqué dans les paramètres du compte",
            "Accéder aux permissions de votre compte",
            "Révoquer l'accès Agentys",
            "Supprimer token.json et réauthentifier",
        ],
        "commands": [
            "rm token.json",
        ],
    },
    ErrorCode.AUTH_004: {
        "title": "Fichier token manquant",
        "description": "Le fichier token.json n'existe pas ou a été supprimé.",
        "steps": [
            "C'est normal au premier lancement",
            "Lancer l'application pour démarrer l'authentification",
            "Suivre les instructions dans le navigateur",
        ],
        "commands": [
            "python run_daemon.py",
        ],
    },
    ErrorCode.AUTH_005: {
        "title": "Permissions insuffisantes",
        "description": "L'application n'a pas les permissions nécessaires.",
        "steps": [
            "Vérifier les scopes OAuth demandés",
            "Pour Gmail: gmail.modify, gmail.compose, gmail.send",
            "Pour Outlook: Mail.ReadWrite, Mail.Send",
            "Révoquer et réautoriser l'application",
        ],
    },
    ErrorCode.LLM_001: {
        "title": "Rate limit API dépassé",
        "description": "Trop de requêtes envoyées à l'API Claude/OpenAI.",
        "steps": [
            "Attendre quelques secondes (le retry automatique gère ça)",
            "Réduire MAX_EMAILS_PER_POLL dans .env",
            "Augmenter DAEMON_POLL_INTERVAL",
        ],
        "commands": [
            "# Dans .env:",
            "MAX_EMAILS_PER_POLL=5",
            "DAEMON_POLL_INTERVAL=120",
        ],
        "doc_link": "docs/TROUBLESHOOTING.md#claude-api---rate-limit-429",
    },
    ErrorCode.LLM_002: {
        "title": "API LLM surchargée",
        "description": "L'API est temporairement surchargée.",
        "steps": [
            "Le circuit breaker protège contre les échecs en cascade",
            "Attendre le timeout de récupération (60s par défaut)",
            "Réessayer automatiquement plus tard",
        ],
        "commands": [
            "# Vérifier l'état du circuit breaker:",
            "python -c \"from app.infrastructure.circuit_breaker import get_circuit_breaker; print(get_circuit_breaker('claude_api').state)\"",
        ],
        "doc_link": "docs/TROUBLESHOOTING.md#claude-api---overloaded-529",
    },
    ErrorCode.LLM_003: {
        "title": "Clé API invalide",
        "description": "La clé API fournie est invalide ou révoquée.",
        "steps": [
            "Vérifier ANTHROPIC_API_KEY dans .env",
            "S'assurer que la clé commence par 'sk-ant-'",
            "Vérifier sur console.anthropic.com que la clé est active",
        ],
        "commands": [
            "echo $ANTHROPIC_API_KEY | head -c 10",
        ],
    },
    ErrorCode.LLM_004: {
        "title": "Timeout API",
        "description": "L'API n'a pas répondu dans le délai imparti.",
        "steps": [
            "Problème temporaire de latence réseau",
            "Réessayer l'opération",
            "Vérifier la connexion internet",
        ],
    },
    ErrorCode.LLM_005: {
        "title": "Réponse API invalide",
        "description": "La réponse de l'API n'est pas au format attendu.",
        "steps": [
            "Problème temporaire de l'API",
            "Vérifier les logs pour plus de détails",
            "Contacter le support si le problème persiste",
        ],
    },
    ErrorCode.LLM_006: {
        "title": "Budget API dépassé",
        "description": "Le budget mensuel configuré a été atteint.",
        "steps": [
            "Augmenter MONTHLY_BUDGET_USD dans .env",
            "Attendre le prochain mois",
            "Utiliser un modèle moins coûteux (Haiku)",
        ],
        "commands": [
            "# Dans .env:",
            "MONTHLY_BUDGET_USD=100",
            "# Ou utiliser Haiku:",
            "LLM_MODEL=claude-3-5-haiku-20241022",
        ],
    },
    ErrorCode.EMAIL_001: {
        "title": "Création brouillon échouée",
        "description": "Impossible de créer le brouillon dans la boîte mail.",
        "steps": [
            "Vérifier les permissions de l'API",
            "Vérifier que la boîte mail n'est pas pleine",
            "Réauthentifier si nécessaire",
        ],
    },
    ErrorCode.EMAIL_002: {
        "title": "Récupération emails échouée",
        "description": "Impossible de récupérer les emails depuis le serveur.",
        "steps": [
            "Vérifier la connexion réseau",
            "Vérifier l'authentification",
            "Vérifier les quotas API",
        ],
    },
    ErrorCode.EMAIL_003: {
        "title": "Email invalide",
        "description": "L'email ne peut pas être traité (format invalide, corrompu).",
        "steps": [
            "L'email sera ignoré automatiquement",
            "Vérifier les logs pour l'ID de l'email",
        ],
    },
    ErrorCode.CFG_001: {
        "title": "Variable d'environnement manquante",
        "description": "Une variable d'environnement requise n'est pas définie.",
        "steps": [
            "Vérifier le fichier .env",
            "Exécuter le script de configuration",
            "Voir les variables requises ci-dessous",
        ],
        "commands": [
            "python setup.py",
        ],
    },
    ErrorCode.CFG_002: {
        "title": "Valeur de configuration invalide",
        "description": "Une valeur de configuration n'est pas valide.",
        "steps": [
            "Vérifier le format de la valeur",
            "Consulter la documentation pour les valeurs acceptées",
        ],
    },
    ErrorCode.DB_001: {
        "title": "Base de données verrouillée",
        "description": "La base SQLite est verrouillée par un autre processus.",
        "steps": [
            "Vérifier qu'une seule instance du daemon tourne",
            "Attendre quelques secondes",
            "Redémarrer l'application si nécessaire",
        ],
        "commands": [
            "ps aux | grep python | grep agentys",
        ],
    },
    ErrorCode.DB_002: {
        "title": "Base de données corrompue",
        "description": "La base SQLite semble corrompue.",
        "steps": [
            "Sauvegarder la base existante",
            "Vérifier l'intégrité",
            "Recréer si nécessaire",
        ],
        "commands": [
            "cp data/agentys.db data/agentys.db.backup",
            "sqlite3 data/agentys.db 'PRAGMA integrity_check'",
        ],
        "doc_link": "docs/TROUBLESHOOTING.md#base-sqlite-corrompue",
    },
    ErrorCode.NET_001: {
        "title": "Connexion refusée",
        "description": "Impossible de se connecter au serveur distant.",
        "steps": [
            "Vérifier la connexion internet",
            "Vérifier le firewall",
            "Pour Ollama: vérifier qu'il est démarré",
        ],
        "commands": [
            "# Pour Ollama:",
            "ollama serve",
        ],
    },
    ErrorCode.UNKNOWN: {
        "title": "Erreur inconnue",
        "description": "Une erreur inattendue s'est produite.",
        "steps": [
            "Consulter les logs pour plus de détails",
            "Redémarrer l'application",
            "Signaler le bug si le problème persiste",
        ],
        "commands": [
            "tail -f logs/agentys.log",
        ],
    },
}


# ============================================================================
# EXCEPTIONS PERSONNALISÉES
# ============================================================================

class AgentysError(Exception):
    """Exception de base pour Agentys."""

    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.UNKNOWN,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}
        self.cause = cause

    def __str__(self) -> str:
        return f"[{self.code.value}] {self.message}"

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire."""
        return {
            "code": self.code.value,
            "message": self.message,
            "details": self.details,
            "cause": str(self.cause) if self.cause else None,
        }


class AuthenticationError(AgentysError):
    """Erreur d'authentification."""

    def __init__(self, message: str, code: ErrorCode = ErrorCode.AUTH_001, **kwargs):
        super().__init__(message, code, **kwargs)


class LLMError(AgentysError):
    """Erreur API LLM."""

    def __init__(self, message: str, code: ErrorCode = ErrorCode.LLM_001, **kwargs):
        super().__init__(message, code, **kwargs)


class EmailError(AgentysError):
    """Erreur email."""

    def __init__(self, message: str, code: ErrorCode = ErrorCode.EMAIL_001, **kwargs):
        super().__init__(message, code, **kwargs)


class ConfigurationError(AgentysError):
    """Erreur de configuration."""

    def __init__(self, message: str, code: ErrorCode = ErrorCode.CFG_001, **kwargs):
        super().__init__(message, code, **kwargs)


class DatabaseError(AgentysError):
    """Erreur base de données."""

    def __init__(self, message: str, code: ErrorCode = ErrorCode.DB_001, **kwargs):
        super().__init__(message, code, **kwargs)


class NetworkError(AgentysError):
    """Erreur réseau."""

    def __init__(self, message: str, code: ErrorCode = ErrorCode.NET_001, **kwargs):
        super().__init__(message, code, **kwargs)


# ============================================================================
# FORMATAGE ET RÉSOLUTION
# ============================================================================

def get_resolution(code: ErrorCode) -> Dict[str, Any]:
    """Retourne les informations de résolution pour un code d'erreur."""
    return RESOLUTIONS.get(code, RESOLUTIONS[ErrorCode.UNKNOWN])


def format_error(
    error: Exception,
    include_resolution: bool = True,
    include_traceback: bool = False,
) -> str:
    """
    Formate une erreur de manière lisible.

    Args:
        error: L'exception à formater.
        include_resolution: Inclure les suggestions de résolution.
        include_traceback: Inclure la stack trace.

    Returns:
        Message formaté.
    """
    lines = []

    # En-tête
    if isinstance(error, AgentysError):
        lines.append(f"❌ Erreur [{error.code.value}]: {error.message}")
        code = error.code
    else:
        lines.append(f"❌ Erreur: {str(error)}")
        code = ErrorCode.UNKNOWN

    # Détails
    if isinstance(error, AgentysError) and error.details:
        lines.append("")
        lines.append("📋 Détails:")
        for key, value in error.details.items():
            lines.append(f"   • {key}: {value}")

    # Cause originale
    if isinstance(error, AgentysError) and error.cause:
        lines.append("")
        lines.append(f"🔍 Cause: {type(error.cause).__name__}: {error.cause}")

    # Résolution
    if include_resolution:
        resolution = get_resolution(code)
        lines.append("")
        lines.append(f"💡 {resolution['title']}")
        lines.append(f"   {resolution['description']}")

        if "steps" in resolution:
            lines.append("")
            lines.append("📝 Étapes de résolution:")
            for i, step in enumerate(resolution["steps"], 1):
                lines.append(f"   {i}. {step}")

        if "commands" in resolution:
            lines.append("")
            lines.append("💻 Commandes utiles:")
            for cmd in resolution["commands"]:
                lines.append(f"   $ {cmd}")

        if "doc_link" in resolution:
            lines.append("")
            lines.append(f"📖 Documentation: {resolution['doc_link']}")

    # Stack trace
    if include_traceback:
        lines.append("")
        lines.append("📜 Stack trace:")
        lines.append(traceback.format_exc())

    return "\n".join(lines)


def log_error(error: Exception, logger: logging.Logger = None) -> None:
    """Log une erreur avec son contexte."""
    log = logger or logging.getLogger(__name__)

    if isinstance(error, AgentysError):
        log.error(f"[{error.code.value}] {error.message}", extra={
            "error_code": error.code.value,
            "details": error.details,
        })
    else:
        log.error(str(error), exc_info=True)


# ============================================================================
# HELPERS POUR DÉTECTION D'ERREURS
# ============================================================================

def classify_exception(e: Exception) -> ErrorCode:
    """
    Classifie une exception standard en code d'erreur.

    Args:
        e: L'exception à classifier.

    Returns:
        Le code d'erreur correspondant.
    """
    error_type = type(e).__name__.lower()
    error_msg = str(e).lower()

    # Authentification
    if "token" in error_msg and ("expired" in error_msg or "invalid" in error_msg):
        return ErrorCode.AUTH_001
    if "unauthorized" in error_msg or "401" in error_msg:
        return ErrorCode.AUTH_002
    if "refresh" in error_msg and "failed" in error_msg:
        return ErrorCode.AUTH_003
    if "permission" in error_msg or "scope" in error_msg:
        return ErrorCode.AUTH_005

    # Rate limiting
    if "rate" in error_msg or "429" in error_msg or "too many" in error_msg:
        return ErrorCode.LLM_001
    if "overload" in error_msg or "529" in error_msg:
        return ErrorCode.LLM_002
    if "api_key" in error_msg or "invalid key" in error_msg:
        return ErrorCode.LLM_003
    if "timeout" in error_type or "timeout" in error_msg:
        return ErrorCode.LLM_004

    # Réseau
    if "connection" in error_msg and "refused" in error_msg:
        return ErrorCode.NET_001
    if "dns" in error_msg or "resolve" in error_msg:
        return ErrorCode.NET_002
    if "ssl" in error_msg or "certificate" in error_msg:
        return ErrorCode.NET_003

    # Base de données
    if "locked" in error_msg or "database is locked" in error_msg:
        return ErrorCode.DB_001
    if "corrupt" in error_msg or "malformed" in error_msg:
        return ErrorCode.DB_002

    return ErrorCode.UNKNOWN


def wrap_exception(e: Exception) -> AgentysError:
    """
    Enveloppe une exception standard dans une AgentysError.

    Args:
        e: L'exception originale.

    Returns:
        Une AgentysError avec le code approprié.
    """
    if isinstance(e, AgentysError):
        return e

    code = classify_exception(e)
    return AgentysError(
        message=str(e),
        code=code,
        cause=e,
    )


# ============================================================================
# EXEMPLE D'UTILISATION
# ============================================================================

if __name__ == "__main__":
    # Test formatage d'erreur
    print("=== Test des erreurs ===\n")

    # Erreur d'authentification
    error1 = AuthenticationError(
        "Token Gmail expiré",
        code=ErrorCode.AUTH_001,
        details={"token_file": "token.json", "last_refresh": "2024-01-01"},
    )
    print(format_error(error1))
    print("\n" + "=" * 60 + "\n")

    # Erreur LLM
    error2 = LLMError(
        "Rate limit exceeded",
        code=ErrorCode.LLM_001,
        details={"retry_after": 30},
    )
    print(format_error(error2))
    print("\n" + "=" * 60 + "\n")

    # Erreur wrappée
    try:
        raise ConnectionRefusedError("Connection to localhost:11434 refused")
    except Exception as e:
        wrapped = wrap_exception(e)
        print(format_error(wrapped))
