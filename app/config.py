# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Configuration centralisée pour Agentys.

Gestion des clés API, constantes et paramètres globaux.
Ce module centralise toutes les configurations, évitant les "magic numbers".
"""

import os
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import List
from dotenv import load_dotenv

from app import email_content_storage as _email_content_storage

EMAIL_CONTENT_STORAGE_METADATA_ONLY = _email_content_storage.EMAIL_CONTENT_STORAGE_METADATA_ONLY
EMAIL_CONTENT_STORAGE_LEGACY_FULL_CACHE = _email_content_storage.EMAIL_CONTENT_STORAGE_LEGACY_FULL_CACHE
EMAIL_CONTENT_STORAGE_MODES = _email_content_storage.EMAIL_CONTENT_STORAGE_MODES
get_email_content_storage_mode = _email_content_storage.get_email_content_storage_mode
should_persist_email_content = _email_content_storage.should_persist_email_content

# ============================================================================
# CHEMINS DU PROJET
# ============================================================================

PROJECT_ROOT = Path(__file__).parent.parent
APP_DIR = PROJECT_ROOT / "app"
# Allow overriding DATA_DIR for production (e.g. Railway volume at /data)
DATA_DIR = Path(os.environ.get("AGENTYS_DATA_DIR", str(PROJECT_ROOT / "data")))
INPUTS_DIR = DATA_DIR / "inputs"
OUTPUTS_DIR = DATA_DIR / "outputs"
KNOWLEDGE_DIR = PROJECT_ROOT / "knowledge"
CONFIG_DIR = PROJECT_ROOT / "config"
LOGS_DIR = PROJECT_ROOT / "logs"

# Fichiers de persistance
PROCESSED_EMAILS_FILE = DATA_DIR / ".processed_emails.json"
HISTORY_FILE = DATA_DIR / "history.json"
FOLLOWUPS_DIR = DATA_DIR / "followups"
LEARNING_DIR = DATA_DIR / "learning"

# Créer les répertoires nécessaires
for _dir in [DATA_DIR, INPUTS_DIR, OUTPUTS_DIR, CONFIG_DIR, LOGS_DIR]:
    _dir.mkdir(parents=True, exist_ok=True)

# ============================================================================
# CHARGEMENT DES VARIABLES D'ENVIRONNEMENT
# ============================================================================

# Chercher .env dans plusieurs emplacements possibles
_env_locations = [
    PROJECT_ROOT / ".env",
    PROJECT_ROOT / "config" / ".env",
]

for env_path in _env_locations:
    if env_path.exists():
        load_dotenv(env_path)
        break


# ============================================================================
# UTILITAIRES DE CONFIGURATION
# ============================================================================

def is_placeholder(value: str | None) -> bool:
    """Détecte si une valeur d'env est un placeholder non configuré."""
    if not value:
        return True
    _placeholders = {
        "your-client-id", "your-client-secret", "your-tenant-id",
        "your_client_id", "your_client_secret", "your_tenant_id",
        "changeme", "xxx", "TODO", "REPLACE_ME",
        "REPLACE_WITH_YOUR_APP_CLIENT_ID", "REPLACE_WITH_YOUR_CLIENT_SECRET",
    }
    return value.strip() in _placeholders


def is_env_set(key: str) -> bool:
    """Vérifie qu'une variable d'env existe ET n'est pas un placeholder."""
    return not is_placeholder(os.getenv(key))


def get_env(key: str, default: str = "") -> str:
    """Récupère une variable d'environnement."""
    return os.getenv(key, default)


def get_env_bool(key: str, default: bool = False) -> bool:
    """Récupère une variable d'environnement booléenne."""
    value = os.getenv(key, str(default)).lower()
    return value in ("true", "1", "yes", "on")


def get_env_int(key: str, default: int = 0) -> int:
    """Récupère une variable d'environnement entière."""
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


def get_env_float(key: str, default: float = 0.0) -> float:
    """Récupère une variable d'environnement flottante."""
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def is_production_environment() -> bool:
    """Détecte la prod avec les mêmes indicateurs que Railway/API."""
    return any(
        os.environ.get(name, "").lower() == "production"
        for name in (
            "FLASK_ENV",
            "ENVIRONMENT",
            "RAILWAY_ENVIRONMENT",
            "RAILWAY_ENVIRONMENT_NAME",
        )
    )


def get_pending_draft_active_retention_days() -> int:
    """Rétention des brouillons actifs persistés en mode metadata-only."""
    return max(1, get_env_int("AGENTYS_PENDING_DRAFT_ACTIVE_RETENTION_DAYS", 30))


def get_pending_draft_terminal_retention_days() -> int:
    """Rétention des brouillons terminaux persistés."""
    return max(1, get_env_int("AGENTYS_PENDING_DRAFT_TERMINAL_RETENTION_DAYS", 30))


def get_ai_artifact_retention_days() -> int:
    """Rétention des artefacts IA datés en mode metadata-only."""
    return max(1, get_env_int("AGENTYS_AI_ARTIFACT_RETENTION_DAYS", 90))


def third_party_ai_training_allowed() -> bool:
    """Opt-in explicite futur pour l'entraînement fournisseur; false par défaut."""
    return get_env_bool("AGENTYS_ALLOW_THIRD_PARTY_AI_TRAINING", False)


# ============================================================================
# CONFIGURATION LLM
# ============================================================================

# Provider LLM : 'claude', 'claude-code', 'ollama' ou 'mock' en test local
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "claude")
AGENTYS_MOCK_LLM = get_env_bool("AGENTYS_MOCK_LLM", False)

# Clé API Anthropic (requise uniquement pour le provider Claude)
# Clé "master" utilisée comme fallback si les clés spécialisées ne sont pas définies
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# Clés spécialisées par catégorie d'usage (traçabilité des coûts Anthropic)
# Chaque clé a un fallback vers ANTHROPIC_API_KEY pour rétrocompatibilité.
# Voir .env.keys.local pour les valeurs et la console Anthropic pour le suivi/coût par clé.
ANTHROPIC_API_KEY_DRAFTING = os.getenv("ANTHROPIC_API_KEY_DRAFTING") or ANTHROPIC_API_KEY
ANTHROPIC_API_KEY_ONBOARDING = os.getenv("ANTHROPIC_API_KEY_ONBOARDING") or ANTHROPIC_API_KEY
ANTHROPIC_API_KEY_BACKGROUND = os.getenv("ANTHROPIC_API_KEY_BACKGROUND") or ANTHROPIC_API_KEY
ANTHROPIC_API_KEY_NIGHTLY = os.getenv("ANTHROPIC_API_KEY_NIGHTLY") or ANTHROPIC_API_KEY

# ============================================================================
# SECOND BRAIN — chemins des 4 sources de mémoire agrégées (issue #261)
# ============================================================================
# Retrieval local (zéro appel LLM). Chaque source est optionnelle — si un
# chemin n'existe pas, l'adapter dégrade gracieusement vers les suivantes.
SECOND_BRAIN_MEMPALACE_DB = Path(os.getenv(
    "SECOND_BRAIN_MEMPALACE_DB",
    str(PROJECT_ROOT / "ai_team" / "memory" / "palace" / "chroma.sqlite3"),
))
SECOND_BRAIN_GRAPH_DB = Path(os.getenv(
    "SECOND_BRAIN_GRAPH_DB",
    str(PROJECT_ROOT / "ai_team" / "memory" / "palace" / "knowledge_graph.sqlite3"),
))
SECOND_BRAIN_MEMOIRE_MD = Path(os.getenv(
    "SECOND_BRAIN_MEMOIRE_MD",
    str(KNOWLEDGE_DIR / "memoire.md"),
))
# Account-scoped KB reuses the main data DB (convention: agentys.db)
SECOND_BRAIN_ACCOUNT_DB = Path(os.getenv(
    "SECOND_BRAIN_ACCOUNT_DB",
    str(DATA_DIR / "agentys.db"),
))

# Clé API OpenAI (pour voice, optionnel)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# URL du serveur Ollama (pour le provider Ollama)
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")


# ============================================================================
# MODÈLES PAR DÉFAUT
# ============================================================================

# Modèles Claude
CLAUDE_MODEL_LABEL = "claude-haiku-4-5-20251001"  # Labeling only (fast, cheap)
# Bumped 2026-05-04 from sonnet-4-20250514 / opus-4-20250514 to 4.6 / 4.7.
# Both are drop-in replacements at the same price points and outperform the
# May-2025 versions on the internal eval. Override via LLM_MODEL_FAST /
# LLM_MODEL_SMART env vars if a regression appears post-deploy.
CLAUDE_MODEL_FAST = "claude-sonnet-4-6"
CLAUDE_MODEL_OPUS = "claude-opus-4-7"
# Backward-compat alias — kept so external callers / configs that reference
# the old name keep working. Prefer `CLAUDE_MODEL_OPUS` in new code: the
# previous name was misleading because `MODEL_SMART` (the env-driven public
# alias below) does NOT actually default to this constant when a user sets
# `LLM_MODEL_SMART`, and most onboarding agents resolve through the
# Container's tier="smart" which maps to `CLAUDE_MODEL_FAST` (Sonnet), not
# Opus. Renaming to OPUS makes the intent explicit.
CLAUDE_MODEL_SMART = CLAUDE_MODEL_OPUS

# Modèles Ollama
OLLAMA_MODEL_FAST = "mixtral:latest"
OLLAMA_MODEL_SMART = "mixtral:latest"

# Sélection des modèles selon le provider
if LLM_PROVIDER.lower() == "ollama":
    MODEL_FAST = os.getenv("LLM_MODEL_FAST", OLLAMA_MODEL_FAST)
    MODEL_SMART = os.getenv("LLM_MODEL_SMART", OLLAMA_MODEL_SMART)
else:
    MODEL_FAST = os.getenv("LLM_MODEL_FAST", CLAUDE_MODEL_FAST)
    MODEL_SMART = os.getenv("LLM_MODEL_SMART", CLAUDE_MODEL_OPUS)

# Modèle par défaut (configurable)
MODEL_DEFAULT = os.getenv("LLM_MODEL", MODEL_SMART)


# ============================================================================
# PARAMÈTRES DES AGENTS
# ============================================================================

# Tokens maximum pour les réponses
# Drafts that survive the eval suite cap at ~400 output tokens; 600 leaves
# 50% margin without paying for the long tail of unused 1024-token budgets.
# Output tokens cost 5× input on Haiku, and Haiku emits ~70 t/s — so trimming
# the worst-case ceiling shaves ~6s of p99 latency and ~30% of output spend.
# `DrafterAgent.draft` retries once at MAX_TOKENS_DRAFT_RETRY when the API
# returns stop_reason="max_tokens", so legitimate long replies are not lost.
#
# Why `int(os.getenv(...))` and not `get_env_int`: there's no `get_env_int`
# helper in this module, only `get_env_bool`. The plain int(...) cast is
# the established pattern (see `MAX_EMAIL_TOKENS`, `POLL_INTERVAL`, etc.).
# Casting raises ValueError on a bad string, which is the desired behavior
# at process boot — fail-fast is preferable to silently using the default
# when an operator typo'd the env value.
MAX_TOKENS_DRAFT = int(os.getenv("MAX_TOKENS_DRAFT", "600"))
MAX_TOKENS_DRAFT_RETRY = int(os.getenv("MAX_TOKENS_DRAFT_RETRY", "1024"))

# B4-lite: adaptive output budget based on incoming email length.
# Short emails ("ok merci") rarely need 600 tokens to answer — capping
# them at ~250 saves wall-time + cost without quality loss. The retry
# path catches the long-tail of legitimately-long replies via the
# stop_reason="max_tokens" signal, so this is a soft cap.
ADAPTIVE_DRAFT_BUDGET_ENABLED = get_env_bool("ADAPTIVE_DRAFT_BUDGET_ENABLED", True)


def adaptive_draft_max_tokens(body_chars: int) -> int:
    """Return a tier'd max_tokens budget given the incoming body length.

    Tiers (rev 2 — 2026-05-05) tuned from the eval-set distribution:
    most STANDARD replies finish under 250 tokens; only multi-question
    drafts need > 400. Lower budgets cut both cost (output tokens are
    5× input on Haiku) AND wall time (~70 t/s, so each saved 100 tokens
    saves ~1.4s of generation time). Retry-on-truncation in
    `DrafterAgent.draft` rescues anything that genuinely needs more.

      ≤  100 chars  → 150 tokens (one-line acks: "OK", "à demain", "merci")
      ≤  400 chars  → 250 tokens (1 question replies — the bulk of inbox)
      ≤ 1500 chars  → 450 tokens (multi-question or context-heavy)
      > 1500 chars  → 600 tokens (default — keeps headroom for COMPLEX)

    Comparison with rev 1 (yesterday):
      rev 1 tier 1 (≤150):   250   →   rev 2 (≤100): 150   (−40%)
      rev 1 tier 2 (≤600):   400   →   rev 2 (≤400): 250   (−37%)
      rev 1 tier 3 (≤2000):  600   →   rev 2 (≤1500): 450  (−25%)
      rev 1 tier 4 (>2000):  800   →   rev 2 (>1500): 600  (−25%)

    Retry path (`MAX_TOKENS_DRAFT_RETRY = 1024`) catches the long-tail
    of legitimately-long drafts. We expect retry rate to climb from
    ~2% (rev 1) to ~5% (rev 2). Net cost still negative because the
    saved tokens on the 95% non-truncated calls outweigh the rare
    retry cost.
    """
    if not ADAPTIVE_DRAFT_BUDGET_ENABLED:
        return MAX_TOKENS_DRAFT
    n = max(0, int(body_chars))
    if n <= 100:
        return 150
    if n <= 400:
        return 250
    if n <= 1500:
        return 450
    return min(600, MAX_TOKENS_DRAFT_RETRY)
MAX_TOKENS_CRITIC = 250  # 7 scores + decision + 3 short suggestions + 1-line
                         # explanation = ~160-200 output tokens. 250 leaves
                         # margin so the structured JSON never truncates mid-
                         # field (truncation → fallback parser → default 50/50
                         # scores → biased decisions). Bumped from 120 on
                         # 2026-05-04 because the eval ran with max_tokens=600
                         # and never hit it; 120 was historical, possibly the
                         # cause of unexplained reject-default behaviour in
                         # prod. The system prompt's own "Maximum 250 tokens"
                         # hint matches.
MAX_TOKENS_PRIORITIZATION = 80  # Internal agent, single number + 1 short reason (was 200)
MAX_TOKENS_CLASSIFICATION = 60  # Internal agent, one-word output + priority (was 150)
MAX_TOKENS_COMMITMENT_EXTRACTION = 800
MAX_TOKENS_CONTACT_SUMMARY = 800
MAX_TOKENS_CONTEXT_ANALYSIS = 512  # Internal agent, structured JSON only

# Paramètres de nettoyage email
MAX_EMAIL_TOKENS = 8000
CHARS_PER_TOKEN = 4.0


# ============================================================================
# PARAMÈTRES D'AFFICHAGE
# ============================================================================

# Longueur de la barre de progression
PROGRESS_BAR_LENGTH = 30


# ============================================================================
# CONFIGURATION DAEMON
# ============================================================================

@dataclass(frozen=True)
class DaemonConfig:
    """Configuration du daemon."""
    poll_interval: int = 60
    skip_low_priority: bool = True
    learning_interval: int = 50
    confidence_threshold: int = 70
    max_emails_per_poll: int = 50

    # Email cleaning
    max_email_tokens: int = 8000
    chars_per_token: float = 4.0


DEFAULT_DAEMON_CONFIG = DaemonConfig(
    poll_interval=get_env_int("DAEMON_POLL_INTERVAL", 60),
    skip_low_priority=get_env_bool("DAEMON_SKIP_LOW_PRIORITY", True),
    learning_interval=get_env_int("DAEMON_LEARNING_INTERVAL", 50),
    confidence_threshold=get_env_int("CONFIDENCE_THRESHOLD", 70),
    max_emails_per_poll=get_env_int("EMAIL_MAX_PER_POLL", 50),
    max_email_tokens=get_env_int("MAX_EMAIL_TOKENS", 8000),
    chars_per_token=get_env_float("CHARS_PER_TOKEN", 4.0),
)


# ============================================================================
# CONFIGURATION RETRY
# ============================================================================

@dataclass(frozen=True)
class RetryConfig:
    """Configuration du retry avec backoff."""
    max_attempts: int = 3
    backoff_factor: float = 2.0
    initial_delay: float = 1.0
    max_delay: float = 60.0


DEFAULT_RETRY_CONFIG = RetryConfig(
    max_attempts=get_env_int("RETRY_MAX_ATTEMPTS", 3),
    backoff_factor=get_env_float("RETRY_BACKOFF_FACTOR", 2.0),
    initial_delay=get_env_float("RETRY_INITIAL_DELAY", 1.0),
    max_delay=get_env_float("RETRY_MAX_DELAY", 60.0),
)


# ============================================================================
# CONFIGURATION CIRCUIT BREAKER
# ============================================================================

@dataclass(frozen=True)
class CircuitBreakerConfig:
    """Configuration du circuit breaker."""
    failure_threshold: int = 5
    recovery_timeout: int = 60
    half_open_max_calls: int = 3


DEFAULT_CIRCUIT_BREAKER_CONFIG = CircuitBreakerConfig(
    failure_threshold=get_env_int("CB_FAILURE_THRESHOLD", 5),
    recovery_timeout=get_env_int("CB_RECOVERY_TIMEOUT", 60),
    half_open_max_calls=get_env_int("CB_HALF_OPEN_MAX_CALLS", 3),
)


# ============================================================================
# CONFIGURATION RATE LIMITING
# ============================================================================

@dataclass(frozen=True)
class RateLimitConfig:
    """Configuration des rate limits."""
    # Claude API
    claude_requests_per_minute: int = 50
    claude_tokens_per_minute: int = 100000

    # Gmail API
    gmail_requests_per_second: int = 10
    gmail_requests_per_day: int = 1000000

    # Outlook API
    outlook_requests_per_minute: int = 60


DEFAULT_RATE_LIMIT_CONFIG = RateLimitConfig(
    claude_requests_per_minute=get_env_int("CLAUDE_RPM", 50),
    claude_tokens_per_minute=get_env_int("CLAUDE_TPM", 100000),
    gmail_requests_per_second=get_env_int("GMAIL_RPS", 10),
    gmail_requests_per_day=get_env_int("GMAIL_RPD", 1000000),
    outlook_requests_per_minute=get_env_int("OUTLOOK_RPM", 60),
)


# ============================================================================
# CONFIGURATION LOGGING
# ============================================================================

@dataclass(frozen=True)
class LoggingConfig:
    """Configuration du logging."""
    level: str = "INFO"
    format_style: str = "standard"  # "standard" ou "json"
    max_bytes: int = 10 * 1024 * 1024  # 10MB
    backup_count: int = 5
    log_to_file: bool = True
    log_to_console: bool = True


DEFAULT_LOGGING_CONFIG = LoggingConfig(
    level=get_env("LOG_LEVEL", "INFO"),
    format_style=get_env("LOG_FORMAT", "standard"),
    max_bytes=get_env_int("LOG_MAX_BYTES", 10 * 1024 * 1024),
    backup_count=get_env_int("LOG_BACKUP_COUNT", 5),
    log_to_file=get_env_bool("LOG_TO_FILE", True),
    log_to_console=get_env_bool("LOG_TO_CONSOLE", True),
)


# ============================================================================
# CONFIGURATION EMAIL CACHE
# ============================================================================

@dataclass(frozen=True)
class CacheConfig:
    """Configuration du cache d'emails."""
    email_cache_limit: int = 500  # Max emails per account
    initial_sync_limit: int = 100  # Emails fetched on first sync
    max_email_age_days: int = 90  # Don't fetch emails older than this
    gmail_batch_chunk_size: int = 25  # Gmail batch API chunk size (max 100)
    gmail_batch_initial_delay: float = 1.5  # Inter-chunk delay in seconds


DEFAULT_CACHE_CONFIG = CacheConfig(
    email_cache_limit=get_env_int("EMAIL_CACHE_LIMIT", 10000),
    # Default 30 — minimum to fill the first inbox screen (~10-15 visible rows
    # + headroom for Noise filtering). The post-onboarding cold-start uses
    # stale-while-revalidate (routes_emails.list_emails returns empty +
    # triggers background sync), so this number controls how fast the FIRST
    # batch lands in the UI, not the eventual corpus size — subsequent
    # background syncs grow the cache in the background.
    # Bump via INITIAL_SYNC_LIMIT env var for a richer initial corpus
    # (cost: longer first-paint, more 429s on rate-limited Gmail accounts).
    initial_sync_limit=get_env_int("INITIAL_SYNC_LIMIT", 30),
    max_email_age_days=get_env_int("MAX_EMAIL_AGE_DAYS", 365),
    gmail_batch_chunk_size=get_env_int("GMAIL_BATCH_CHUNK_SIZE", 25),
    gmail_batch_initial_delay=get_env_float("GMAIL_BATCH_INITIAL_DELAY", 1.5),
)


# ============================================================================
# CONFIGURATION EMAIL
# ============================================================================

EMAIL_PROVIDER_TYPE = get_env("EMAIL_PROVIDER_TYPE", "GMAIL")
EMAIL_CONTENT_STORAGE_MODE = get_email_content_storage_mode()


# ============================================================================
# VALIDATION DE CONFIGURATION
# ============================================================================

class ConfigValidationError(Exception):
    """Erreur de validation de configuration."""
    pass


def validate_config(raise_on_error: bool = False) -> List[str]:
    """
    Valide la configuration au démarrage.

    Args:
        raise_on_error: Si True, lève une exception sur erreur.

    Returns:
        Liste des erreurs de configuration (vide si tout est OK).
    """
    errors = []
    warnings = []
    logger = logging.getLogger(__name__)

    # Vérifier les clés API
    if LLM_PROVIDER.lower() == "claude" and not AGENTYS_MOCK_LLM and not ANTHROPIC_API_KEY:
        errors.append("ANTHROPIC_API_KEY manquante (requise pour LLM_PROVIDER=claude)")

    # Vérifier les répertoires
    required_dirs = [DATA_DIR, CONFIG_DIR, LOGS_DIR]
    for dir_path in required_dirs:
        try:
            dir_path.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            errors.append(f"Impossible de créer le répertoire: {dir_path}")

    # Vérifier les valeurs numériques
    if DEFAULT_DAEMON_CONFIG.poll_interval < 10:
        warnings.append("DAEMON_POLL_INTERVAL < 10s peut causer des problèmes de rate limit")

    if DEFAULT_DAEMON_CONFIG.poll_interval > 600:
        warnings.append("DAEMON_POLL_INTERVAL > 600s peut causer des délais de réponse importants")

    if DEFAULT_DAEMON_CONFIG.confidence_threshold < 0 or DEFAULT_DAEMON_CONFIG.confidence_threshold > 100:
        errors.append("CONFIDENCE_THRESHOLD doit être entre 0 et 100")

    # Vérifier le provider email
    valid_providers = ["GMAIL", "OUTLOOK", "IMAP", "SMTP", "IMAP_SMTP", "MOCK"]
    if EMAIL_PROVIDER_TYPE.upper() not in valid_providers:
        errors.append(f"EMAIL_PROVIDER_TYPE invalide: {EMAIL_PROVIDER_TYPE}. Valeurs: {valid_providers}")

    email_content_mode = get_email_content_storage_mode()
    if email_content_mode not in EMAIL_CONTENT_STORAGE_MODES:
        errors.append(
            "AGENTYS_EMAIL_CONTENT_STORAGE_MODE invalide: "
            f"{email_content_mode}. Valeurs: {sorted(EMAIL_CONTENT_STORAGE_MODES)}"
        )

    if (
        is_production_environment()
        and email_content_mode == EMAIL_CONTENT_STORAGE_LEGACY_FULL_CACHE
        and not get_env_bool("AGENTYS_ALLOW_LEGACY_EMAIL_CONTENT_CACHE", False)
    ):
        errors.append(
            "AGENTYS_EMAIL_CONTENT_STORAGE_MODE=legacy_full_cache est interdit "
            "en production sans AGENTYS_ALLOW_LEGACY_EMAIL_CONTENT_CACHE=true"
        )

    if is_production_environment() and third_party_ai_training_allowed():
        errors.append(
            "AGENTYS_ALLOW_THIRD_PARTY_AI_TRAINING=true est interdit en production; "
            "les données utilisateur ne doivent pas entraîner de modèles tiers par défaut"
        )

    # Log warnings
    for warning in warnings:
        logger.warning(f"[WARN] Config: {warning}")

    if raise_on_error and errors:
        raise ConfigValidationError(
            "Configuration invalide:\n" + "\n".join(f"  - {e}" for e in errors)
        )

    return errors


def require_valid_config() -> None:
    """
    Valide la configuration et lève une exception si invalide.

    Raises:
        ConfigValidationError: Si la configuration est invalide.
    """
    validate_config(raise_on_error=True)


# ============================================================================
# CONFIGURATION SMART ROUTING
# ============================================================================

SMART_ROUTING_ENABLED = get_env_bool("SMART_ROUTING_ENABLED", True)
SONNET_ROUTING_ENABLED = get_env_bool("SONNET_ROUTING_ENABLED", True)
MULTI_DRAFT_ENABLED = get_env_bool("MULTI_DRAFT_ENABLED", False)

# Phase 2b: when True, /api/emails/compose routes through DraftService.generate
# (unified pipeline, includes Self-Critique shadow + KB Savoir injection).
# Kill-switch — flip to False instantly via env var if regression detected.
USE_DRAFT_SERVICE_COMPOSE = get_env_bool("USE_DRAFT_SERVICE_COMPOSE", False)
# FAQ auto-reply: when False, FAQ entries are NOT used for auto-sending replies.
# They are still injected into the drafter prompt as grounding context — see
# _build_prompts() in smart_routing.py and find_relevant_faqs_for_drafter() in faq_agent.py.
FAQ_AUTO_REPLY_ENABLED = get_env_bool("FAQ_AUTO_REPLY_ENABLED", False)

# Conversation history fetch: when False, drafter does NOT fetch past emails
# from IMAP/Gmail nor the thread_context from the local DB. Style-by-contact
# (ContactStyleProfile) and the global WritingStyleProfile are used instead
# to dictate tone, greeting, closing, formality. Cuts 250ms-1.3s per reply
# (skipped IMAP fetch + shorter prompts). Short or referential emails
# ("ok go", "comme convenu") may lose context — acceptable trade-off.
USE_CONVERSATION_HISTORY = get_env_bool("USE_CONVERSATION_HISTORY", False)

# Self-consistency for COMPLEX-tier drafts: generate 2 samples in parallel
# at different temperatures (0.4 + 0.7) and keep the cleaner one (no
# placeholders, no hedging, more thorough). COMPLEX is ~10% of the inbox,
# so the marginal cost is +1 LLM call on ~10% of drafts (~$0.0003 amortized
# per email). Skipped when the user provided `instructions` — those callers
# expect deterministic single-shot output.
SELF_CONSISTENCY_COMPLEX_ENABLED = get_env_bool("SELF_CONSISTENCY_COMPLEX_ENABLED", True)

# 2026-05-05 — multi-block prompt cache. When ON, agents that opt-in build
# their system prompt as a list of `SystemSegment` (persona | KB | per-
# contact context) instead of a single concatenated string. Each segment
# gets its own cache_control breakpoint, so a change in one segment (e.g.
# the user updates their KB) doesn't blow away the cache for the others.
# Anthropic limits to 4 breakpoints per request — see
# `app/adapters/llm/claude_adapter.py:_build_anthropic_system_blocks`.
# Default ON; flip to false to roll back to single-block instantly.
ENABLE_MULTI_BLOCK_CACHE = get_env_bool("ENABLE_MULTI_BLOCK_CACHE", True)

# 2026-05-05 — regex-first PII detection. When ON, SensitiveDataDetectorAgent
# uses `app.services.pii_detector` (pure regex, $0 LLM cost) for the
# deterministic categories (email, phone, credit_card, IBAN, SSN, SIN, SIRET,
# IP, API_KEY, secret keywords). The LLM is invoked only when the regex
# layer flags AT LEAST one match — to extract the structured snippet/type
# information the downstream pipeline expects. Drafts with zero regex
# matches now skip the LLM entirely. Default ON; flip false to roll back
# to the all-LLM path. The forthcoming Presidio NER layer will sit between
# the regex pre-filter and the LLM fallback (next sprint).
USE_REGEX_PII_DETECTOR = get_env_bool("USE_REGEX_PII_DETECTOR", True)

# 2026-05-05 — non-destructive V2 replacement.
# When ON, `route_streaming` emits a `draft_revised` event (with both V1
# and V2 + critique summary) instead of silently overwriting the streamed
# V1 with V2 via `_emit_instant_draft`. The frontend chooses whether to
# replace or surface a "View improved version" toggle — preserves user
# edits made in the ~1.5s critic window.
#
# Default ON since 2026-05-05: frontend toggle is wired in
# `useWebSocketSync.ts` (handler) and `websocket.ts` (event type +
# socket.on listener). Older frontends that don't recognize the event
# simply ignore it — they continue to receive the legacy `draft_complete`
# only when the critic accepts V1 (no V2 generated, no race condition).
STREAM_V1_BEFORE_CRITIC_NONDESTRUCTIVE = get_env_bool(
    "STREAM_V1_BEFORE_CRITIC_NONDESTRUCTIVE", True,
)

# Contact summary injection: when False, the pre-computed contact_summary
# (relation, topics, key_facts, last_interaction_summary…) is NOT injected
# into the Drafter prompt. Only the pure style layer (ContactStyleProfile +
# WritingStyleProfile) dictates the reply. Pairs with USE_CONVERSATION_HISTORY=False
# to fully eliminate any historical conversational content from the prompt.
USE_CONTACT_SUMMARY = get_env_bool("USE_CONTACT_SUMMARY", True)

# Specialty pre-draft agents (refund / subscription / account) — when False,
# these agents are NOT called in the smart_routing pipeline. The drafter handles
# those emails normally without specialty-aware overrides. All three default to
# False to keep the pipeline lean; re-enable individually via env var if needed.
REFUND_AGENT_ENABLED = get_env_bool("REFUND_AGENT_ENABLED", False)
SUBSCRIPTION_AGENT_ENABLED = get_env_bool("SUBSCRIPTION_AGENT_ENABLED", False)
ACCOUNT_AGENT_ENABLED = get_env_bool("ACCOUNT_AGENT_ENABLED", False)
ROUTING_SIMPLE_THRESHOLD = 30
ROUTING_COMPLEX_THRESHOLD = 50
ROUTING_MAX_TOKENS_SIMPLE = 150
ROUTING_MAX_TOKENS_STANDARD = 512
ROUTING_MAX_TOKENS_COMPLEX = 1024


# ============================================================================
# CONFIGURATION BATCH API
# ============================================================================

BATCH_API_ENABLED = get_env_bool("BATCH_API_ENABLED", True)

# Schedule: off-hours window (batch processing active outside these active hours)
BATCH_ACTIVE_HOURS_START = get_env("BATCH_ACTIVE_HOURS_START", "07:00")
BATCH_ACTIVE_HOURS_END = get_env("BATCH_ACTIVE_HOURS_END", "20:00")
BATCH_WEEKEND_ALL_DAY = get_env_bool("BATCH_WEEKEND_ALL_DAY", True)

# Activity override: switch to real-time if user was active recently
BATCH_ACTIVITY_TIMEOUT_MIN = get_env_int("BATCH_ACTIVITY_TIMEOUT_MIN", 15)

# Queue thresholds for micro-batch submission
BATCH_QUEUE_MAX_SIZE = get_env_int("BATCH_QUEUE_MAX_SIZE", 50)
BATCH_QUEUE_MIN_SIZE = get_env_int("BATCH_QUEUE_MIN_SIZE", 5)
BATCH_QUEUE_MAX_AGE_SEC = get_env_int("BATCH_QUEUE_MAX_AGE_SEC", 60)

# Worker polling intervals
BATCH_WORKER_POLL_SEC = get_env_int("BATCH_WORKER_POLL_SEC", 30)
BATCH_RESULT_POLL_SEC = get_env_int("BATCH_RESULT_POLL_SEC", 30)

# Fallback: max wait time before giving up on batch and using real-time
BATCH_FALLBACK_TIMEOUT_MIN = get_env_int("BATCH_FALLBACK_TIMEOUT_MIN", 30)


# ============================================================================
# CONFIGURATION STYLE ADAPTATION (Story 4-4)
# ============================================================================

# Enable/disable style adaptation in DrafterAgent
STYLE_ADAPTATION_ENABLED = get_env_bool("STYLE_ADAPTATION_ENABLED", True)

# Minimum similarity score threshold (0-100) for acceptable style match
STYLE_SIMILARITY_THRESHOLD = get_env_float("STYLE_SIMILARITY_THRESHOLD", 70.0)

# Maximum tokens for style analysis
MAX_TOKENS_STYLE_ANALYSIS = 300


# ============================================================================
# VÉRIFICATION AU CHARGEMENT (pour Claude uniquement, comme avant)
# ============================================================================

# Vérification de la clé API uniquement si on utilise Claude
if LLM_PROVIDER.lower() == "claude" and not AGENTYS_MOCK_LLM and not ANTHROPIC_API_KEY:
    raise EnvironmentError(
        "[ERROR] ANTHROPIC_API_KEY non trouvée. "
        "Créez un fichier .env avec : ANTHROPIC_API_KEY=sk-ant-...\n"
        "Ou utilisez Ollama : LLM_PROVIDER=ollama"
    )
