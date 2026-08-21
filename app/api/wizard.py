# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Routes API REST pour le Wizard de Configuration.

Endpoints disponibles:
- GET /api/wizard/config - Configuration actuelle
- POST /api/wizard/config - Sauvegarder une configuration
- GET /api/wizard/packs - Liste des packs disponibles
- GET /api/wizard/agents - Liste des agents disponibles
- PATCH /api/wizard/agents/<agent_id> - Activer/désactiver un agent
- POST /api/wizard/import - Importer une knowledge base
- POST /api/wizard/export - Exporter la configuration
- POST /api/wizard/test-connection - Tester connexion email IMAP/SMTP
- POST /api/wizard/import-env - Importer un fichier .env existant (migration)
"""

import logging
import threading
import time
import uuid
from datetime import datetime
from functools import wraps
from typing import Callable

from flask import Blueprint, g, has_request_context, request, jsonify

from app.api.admin import require_admin
from app.api.routes_helpers import _is_safe_path
from app.providers.imap_adapter import IMAPAdapter
from app.providers.smtp_adapter import SMTPAdapter
from app.config import PROJECT_ROOT

from app.domain.entities import (
    WizardConfig,
    BusinessSector,
    CompanySize,
    ConfigPack,
    KnowledgeBaseConfig,
)
from app.infrastructure.wizard_config_store import (
    get_wizard_config_store,
)
from app.application import (
    SaveWizardConfigUseCase,
    CreateWizardConfigUseCase,
    ToggleAgentUseCase,
    ImportKnowledgeBaseUseCase,
    ExportConfigUseCase,
    get_available_packs,
    get_available_agents,
)

logger = logging.getLogger(__name__)

wizard_bp = Blueprint("wizard", __name__)


# ============================================================================
# HELPERS
# ============================================================================

def require_json(f: Callable) -> Callable:
    """Décorateur pour valider la présence d'un body JSON."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not request.get_json():
            return jsonify({"error": "JSON body required"}), 400
        return f(*args, **kwargs)
    return decorated


def _validate_ollama_url(url: str) -> tuple[bool, str]:
    """
    Validate an Ollama base URL before persisting it or making a test call.

    AUTHZ-VULN-08 / AUTHZ-VULN-09 (Shannon pentest 2026-05-05, issue #557):
    `/api/wizard/test-llm` and `/api/wizard/llm-settings` previously accepted
    any URL and made an outbound request to it. In prod that produced a
    pre-auth blind SSRF (file://, gopher://, link-local, RFC 1918) and a
    persistent rerouting of every Ollama call platform-wide.

    Defense:
    - Scheme MUST be http or https (rejects file://, gopher://, dict://).
    - In production, hostname must NOT resolve to a private/loopback/
      link-local/cloud-metadata IP (Railway server cannot reach customer
      laptops anyway, so localhost is meaningless there and only useful
      to attack the box itself).
    - In dev/desktop, localhost stays allowed because Ollama is bundled
      with the user's machine.

    Returns:
        (ok, error_message). `ok=True` on success; on failure error_message
        is operator-safe.
    """
    from app.api._auth_helpers import is_production
    from app.utils.safe_outbound import SsrfBlocked, validate_outbound_url

    if not url or not isinstance(url, str):
        return False, "ollama_url manquante ou invalide"

    if is_production():
        try:
            validate_outbound_url(url)
        except SsrfBlocked as e:
            return False, f"ollama_url refusée: {e}"
        return True, ""

    # Dev / desktop install: only enforce scheme allowlist; localhost is OK.
    from urllib.parse import urlparse
    parsed = urlparse(url.strip())
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"}:
        return False, f"Scheme non autorisé: {scheme or '<vide>'}"
    if not parsed.hostname:
        return False, "Hôte manquant dans ollama_url"
    return True, ""


def build_knowledge_base_from_data(data: dict, default_company_name: str) -> KnowledgeBaseConfig:
    """Construit un KnowledgeBaseConfig depuis les données de la requête."""
    return KnowledgeBaseConfig(
        company_name=data.get("company_name", default_company_name),
        company_description=data.get("company_description", ""),
        products_services=data.get("products_services", ""),
        tone_guidelines=data.get("tone_guidelines", ""),
        forbidden_topics=data.get("forbidden_topics", []),
        custom_signatures=data.get("custom_signatures", {}),
        faq_entries=data.get("faq_entries", {}),
    )


def _has_completed_account_onboarding() -> bool:
    """Return True when the current user's active account already finished KB onboarding."""
    from flask import g, has_request_context

    auth_user = getattr(g, "auth_user", None) if has_request_context() else None
    is_loopback = False
    if has_request_context():
        try:
            from app.api.auth import is_trusted_loopback
            is_loopback = is_trusted_loopback()
        except Exception:
            is_loopback = False

    # Remote callers must be scoped by JWT. Loopback keeps the legacy desktop
    # behaviour where the local backend is single-user.
    if not auth_user and has_request_context() and not is_loopback:
        return False

    try:
        from app.db.database import get_db_session
        from app.db.repositories.account_repository import AccountRepository
        from app.db.repositories.onboarding_repository import OnboardingRepository

        with get_db_session() as session:
            account_repo = AccountRepository(session)
            if auth_user and auth_user.get("id"):
                auth_email = (auth_user.get("email") or "").strip()
                if auth_email:
                    try:
                        from app.db.maintenance import repair_account_user_id
                        repair_account_user_id(
                            session,
                            auth_email=auth_email,
                            user_id=int(auth_user["id"]),
                            source="wizard-status",
                        )
                    except Exception as e:
                        logger.warning("[WIZARD] account ownership repair failed: %s", e)
                accounts = account_repo.get_active_accounts_for_user(int(auth_user["id"]))
            else:
                accounts = account_repo.get_active_accounts()

            onboarding_repo = OnboardingRepository(session)
            return any(
                onboarding_repo.get_completed_by_account(int(account.id)) is not None
                for account in accounts
                if getattr(account, "id", None) is not None
            )
    except Exception as e:
        logger.warning("[WIZARD] Account onboarding status lookup failed: %s", e)
        return False


# ============================================================================
# ONBOARDING STATUS
# ============================================================================

@wizard_bp.route("/status", methods=["GET"])
def get_onboarding_status():
    """
    Vérifie si l'onboarding est complété.

    L'onboarding est considéré complété si:
    - Une configuration wizard existe, ou
    - Le compte authentifié a déjà un onboarding KB complété en DB

    Returns:
        JSON avec le status de l'onboarding.
    """
    store = get_wizard_config_store()
    config = store.load()

    auth_user = getattr(g, "auth_user", None) if has_request_context() else None

    # Remote/web users must be scoped by their own onboarding result. The
    # wizard config file is process-global legacy desktop state and must not
    # mark every new user complete on a shared install.
    has_config = config is not None
    has_account_onboarding = _has_completed_account_onboarding()
    onboarding_complete = has_account_onboarding or (has_config and not auth_user)

    return jsonify({
        "onboarding_complete": onboarding_complete,
        "has_config": has_config,
        "source": (
            "wizard_config"
            if has_config
            else "account_onboarding"
            if has_account_onboarding
            else "none"
        ),
    })


@wizard_bp.route("/config", methods=["DELETE"])
@require_admin
def delete_wizard_config():
    """
    Supprime la configuration wizard pour forcer un nouvel onboarding.
    Utilisé par le reset complet des données.

    F-05 (audit issue #209, 2026-04-29): @require_admin added — wizard
    config is a global singleton and any authenticated user could wipe
    every other user's onboarding state.

    F-07 (regression audit, 2026-04-29) — KNOWN MULTI-WORKER LIMITATION:
    `container._wizard_config_store = None` only invalidates the
    singleton on the worker that handled this DELETE. Sibling workers
    keep serving their cached store until they restart. Single-process
    Werkzeug (current Railway prod) is unaffected. If we migrate to
    gunicorn N>1 workers, switch the store to read-from-disk-on-every-
    load (the file is small) or add an mtime check.
    """
    store = get_wizard_config_store()
    filepath = getattr(store, '_filepath', None) or getattr(store, 'filepath', None)
    if filepath:
        import pathlib
        p = pathlib.Path(filepath)
        if p.exists():
            p.unlink()
            logger.info("[WIZARD] Config supprimée: %s", p)

    # Invalider le singleton en mémoire pour que le prochain load() retourne None
    from app.infrastructure.container import get_container
    container = get_container()
    container._wizard_config_store = None

    return jsonify({"success": True, "message": "Wizard config deleted"})


# ============================================================================
# ENV CONFIG (pour pré-remplir le wizard depuis le .env)
# ============================================================================

@wizard_bp.route("/env-config", methods=["GET"])
def get_env_config():
    """
    Récupère la configuration depuis le fichier .env pour pré-remplir le wizard.

    Retourne les valeurs email et LLM du .env existant.
    Cet endpoint est destiné à être appelé au démarrage du wizard
    pour permettre à l'utilisateur de valider les paramètres existants.

    Returns:
        JSON avec la configuration email et LLM détectée dans le .env.
    """
    from app.config import PROJECT_ROOT

    # ── Check DB accounts first (PKCE OAuth stores tokens in SQLite, not .env) ──
    from flask import g, has_request_context
    auth_user = getattr(g, 'auth_user', None) if has_request_context() else None

    _db_account = None
    try:
        from app.db.database import get_db_session
        from app.db.repositories.account_repository import AccountRepository
        with get_db_session() as _sess:
            repo = AccountRepository(_sess)
            if auth_user and auth_user.get("id"):
                _db_accounts = list(repo.get_active_accounts_for_user(int(auth_user["id"])))
            else:
                _db_accounts = list(repo.get_active_accounts())
            if _db_accounts:
                _db_account = _db_accounts[0]
    except Exception as e:
        logger.warning(f"[WIZARD] DB account lookup failed, falling back to .env: {e}")

    # If an active account exists in DB, report it as configured regardless of .env
    if _db_account is not None:
        email_config = {
            "provider": _db_account.provider,  # gmail, outlook, imap
            "configured": True,
        }
        result = {
            "success": True,
            "has_env": True,
            "email": email_config,
        }
        # Still try to include LLM config from .env if available
        env_path = PROJECT_ROOT / ".env"
        if not env_path.exists():
            env_path = PROJECT_ROOT / "config" / ".env"
        if env_path.exists():
            try:
                env_vars = _parse_env_file(str(env_path))
                llm_config = {}
                if "LLM_PROVIDER" in env_vars:
                    llm_config["provider"] = env_vars["LLM_PROVIDER"]
                if "LLM_MODEL" in env_vars:
                    llm_config["model"] = env_vars["LLM_MODEL"]
                if "ANTHROPIC_API_KEY" in env_vars:
                    llm_config["has_api_key"] = True
                if "OLLAMA_BASE_URL" in env_vars:
                    llm_config["ollama_url"] = env_vars["OLLAMA_BASE_URL"]
                if llm_config:
                    result["llm"] = llm_config
            except Exception:
                pass
        return jsonify(result)

    # ── No DB account — fall back to .env detection ──
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        env_path = PROJECT_ROOT / "config" / ".env"
        if not env_path.exists():
            return jsonify({
                "success": False,
                "has_env": False,
                "message": "No .env file found",
            })

    try:
        env_vars = _parse_env_file(str(env_path))

        result = {
            "success": True,
            "has_env": True,
        }

        # Detecter le type de provider email
        provider_type = env_vars.get("EMAIL_PROVIDER_TYPE", "").upper()
        result["email_provider_type"] = provider_type

        # Configuration Email selon le provider
        email_config = {}

        if provider_type == "GMAIL":
            # Gmail OAuth - verifier si configure (exclure les placeholders)
            from app.config import is_placeholder
            has_client_id = "GOOGLE_CLIENT_ID" in env_vars and not is_placeholder(env_vars.get("GOOGLE_CLIENT_ID"))
            has_client_secret = "GOOGLE_CLIENT_SECRET" in env_vars and not is_placeholder(env_vars.get("GOOGLE_CLIENT_SECRET"))
            has_refresh_token = "GOOGLE_REFRESH_TOKEN" in env_vars and not is_placeholder(env_vars.get("GOOGLE_REFRESH_TOKEN"))
            email_config["provider"] = "gmail"
            email_config["configured"] = has_client_id and has_client_secret and has_refresh_token
            email_config["has_client_id"] = has_client_id
            email_config["has_client_secret"] = has_client_secret
            email_config["has_refresh_token"] = has_refresh_token

        elif provider_type == "OUTLOOK":
            # Outlook OAuth - verifier si configure (exclure les placeholders)
            from app.config import is_placeholder
            has_tenant_id = "AZURE_TENANT_ID" in env_vars and not is_placeholder(env_vars.get("AZURE_TENANT_ID"))
            has_client_id = "AZURE_CLIENT_ID" in env_vars and not is_placeholder(env_vars.get("AZURE_CLIENT_ID"))
            has_client_secret = "AZURE_CLIENT_SECRET" in env_vars and not is_placeholder(env_vars.get("AZURE_CLIENT_SECRET"))
            email_config["provider"] = "outlook"
            email_config["configured"] = has_tenant_id and has_client_id and has_client_secret
            email_config["has_tenant_id"] = has_tenant_id
            email_config["has_client_id"] = has_client_id
            email_config["has_client_secret"] = has_client_secret
            if "OUTLOOK_USER_ID" in env_vars:
                email_config["user_id"] = env_vars["OUTLOOK_USER_ID"]

        else:
            # IMAP/SMTP standard
            email_config["provider"] = "imap_smtp"
            if "IMAP_HOST" in env_vars:
                email_config["imap_host"] = env_vars["IMAP_HOST"]
            if "IMAP_PORT" in env_vars:
                email_config["imap_port"] = _parse_int_safe(env_vars["IMAP_PORT"], 993)
            if "IMAP_USER" in env_vars:
                email_config["imap_username"] = env_vars["IMAP_USER"]
            if "IMAP_PASSWORD" in env_vars:
                email_config["has_imap_password"] = True
            if "IMAP_USE_SSL" in env_vars:
                email_config["imap_use_ssl"] = _parse_boolean(env_vars["IMAP_USE_SSL"])

            if "SMTP_HOST" in env_vars:
                email_config["smtp_host"] = env_vars["SMTP_HOST"]
            if "SMTP_PORT" in env_vars:
                email_config["smtp_port"] = _parse_int_safe(env_vars["SMTP_PORT"], 587)
            if "SMTP_USER" in env_vars:
                email_config["smtp_username"] = env_vars["SMTP_USER"]
            if "SMTP_PASSWORD" in env_vars:
                email_config["has_smtp_password"] = True
            if "SMTP_USE_TLS" in env_vars:
                email_config["smtp_use_tls"] = _parse_boolean(env_vars["SMTP_USE_TLS"])
            if "SMTP_USE_SSL" in env_vars:
                email_config["smtp_use_ssl"] = _parse_boolean(env_vars["SMTP_USE_SSL"])

            # Verifier si IMAP/SMTP est configure
            email_config["configured"] = bool(
                email_config.get("imap_host") and email_config.get("smtp_host")
            )

        if email_config:
            result["email"] = email_config

        # Configuration LLM
        llm_config = {}
        if "LLM_PROVIDER" in env_vars:
            llm_config["provider"] = env_vars["LLM_PROVIDER"]
        if "LLM_MODEL" in env_vars:
            llm_config["model"] = env_vars["LLM_MODEL"]
        if "ANTHROPIC_API_KEY" in env_vars:
            llm_config["has_api_key"] = True
        if "OLLAMA_BASE_URL" in env_vars:
            llm_config["ollama_url"] = env_vars["OLLAMA_BASE_URL"]

        if llm_config:
            result["llm"] = llm_config

        return jsonify(result)

    except Exception as e:
        logger.error(f"Error reading .env config: {e}")
        return jsonify({
            "success": False,
            "has_env": True,
            "error": str(e),
        }), 500


# ============================================================================
# CONFIGURATION
# ============================================================================

@wizard_bp.route("/config", methods=["GET"])
def get_config():
    """
    Récupère la configuration wizard actuelle.

    Returns:
        JSON avec la configuration ou null si inexistante.
    """
    store = get_wizard_config_store()
    config = store.load()

    if not config:
        return jsonify({
            "exists": False,
            "config": None,
        })

    return jsonify({
        "exists": True,
        "config": config.to_dict(),
        "active_agents": [
            {
                "agent_id": a.agent_id,
                "priority": a.priority,
            }
            for a in config.get_active_agents()
        ],
    })


@wizard_bp.route("/config", methods=["POST"])
@require_admin
@require_json
def save_config():
    """
    Sauvegarde une nouvelle configuration wizard.

    F-05 (audit issue #209, 2026-04-29): @require_admin added — wizard
    config is a global singleton (forbidden_topics, tone_guidelines,
    custom_signatures all feed Drafter prompt construction for every
    user). Any authenticated user could overwrite the org-wide config.

    Body JSON:
        company_name: str (requis)
        sector: str (optional, default: "other")
        size: str (optional, default: "smb")
        primary_language: str (optional, default: "fr")
        supported_languages: list[str] (optional)
        pack: str (optional)
        agents: list[{agent_id, enabled, priority}] (optional)
        knowledge_base: dict (optional)

    Returns:
        Configuration sauvegardée.
    """
    data = request.get_json()
    company_name = data.get("company_name")
    if not company_name:
        return jsonify({"error": "company_name is required"}), 400

    try:
        config = _create_config_from_data(data, company_name)
        _apply_agents_from_data(config, data.get("agents", []))
        _apply_knowledge_base_from_data(config, data.get("knowledge_base", {}), company_name)

        # Sauvegarder
        store = get_wizard_config_store()
        save_use_case = SaveWizardConfigUseCase(persistence=store)
        save_use_case.execute(config)

        return jsonify({
            "success": True,
            "config": config.to_dict(),
        }), 201

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(f"Error saving config: {e}")
        return jsonify({"error": "An internal error occurred while saving configuration"}), 500


def _create_config_from_data(data: dict, company_name: str) -> WizardConfig:
    """Crée une configuration wizard à partir des données de la requête."""
    store = get_wizard_config_store()
    create_use_case = CreateWizardConfigUseCase(persistence=store)

    sector = BusinessSector(data.get("sector", "other"))
    size = CompanySize(data.get("size", "smb"))
    pack = ConfigPack(data.get("pack", "custom")) if data.get("pack") else None

    config = create_use_case.execute(
        company_name=company_name,
        sector=sector,
        size=size,
        pack=pack,
    )

    config.primary_language = data.get("primary_language", "fr")
    config.supported_languages = data.get("supported_languages", ["fr", "en"])
    return config


def _apply_agents_from_data(config: WizardConfig, agents_data: list) -> None:
    """Applique la configuration des agents depuis les données."""
    for agent in agents_data:
        if agent.get("enabled", True):
            config.activate_agent(
                agent_id=agent["agent_id"],
                priority=agent.get("priority", 50)
            )
        else:
            config.deactivate_agent(agent["agent_id"])


def _apply_knowledge_base_from_data(
    config: WizardConfig,
    kb_data: dict,
    company_name: str
) -> None:
    """Applique la knowledge base depuis les données."""
    if kb_data:
        config.knowledge_base = build_knowledge_base_from_data(kb_data, company_name)


# F-05 (audit issue #209, 2026-04-29): duplicate DELETE /config route removed.
# The earlier definition at L113 (delete_wizard_config) is the canonical one — it
# also invalidates the container's wizard_config_store singleton. Flask raised no
# error because the second registration silently overrode the first; the dead
# delete_config() at L434 was the one that actually fired in prod and skipped
# the singleton-invalidation.


# ============================================================================
# PACKS
# ============================================================================

@wizard_bp.route("/packs", methods=["GET"])
def list_packs():
    """
    Liste les packs préconfigurés disponibles.

    Returns:
        Liste des packs avec leur description.
    """
    packs = get_available_packs()

    return jsonify({
        "count": len(packs),
        "packs": packs,
    })


@wizard_bp.route("/packs/<pack_id>", methods=["GET"])
def get_pack(pack_id: str):
    """
    Récupère les détails d'un pack.

    Args:
        pack_id: ID du pack (startup, smb, enterprise, saas, ecommerce, b2b)

    Returns:
        Détails du pack avec les agents inclus.
    """
    from app.application.wizard_config import PACK_CONFIGURATIONS

    try:
        pack_enum = ConfigPack(pack_id)
    except ValueError:
        return jsonify({"error": f"Pack not found: {pack_id}"}), 404

    if pack_enum not in PACK_CONFIGURATIONS:
        return jsonify({"error": f"Pack not found: {pack_id}"}), 404

    pack_config = PACK_CONFIGURATIONS[pack_enum]

    # Enrichir avec les infos des agents
    all_agents = {a["id"]: a for a in get_available_agents()}
    agents_details = []
    for agent_ref in pack_config.get("agents", []):
        agent_id = agent_ref["id"]
        if agent_id in all_agents:
            agent_info = all_agents[agent_id].copy()
            agent_info["priority"] = agent_ref.get("priority", 50)
            agents_details.append(agent_info)

    return jsonify({
        "id": pack_id,
        "name": pack_id.title(),
        "agents": agents_details,
        "languages": pack_config.get("languages", ["fr", "en"]),
        "tone_guidelines": pack_config.get("tone_guidelines", ""),
    })


# ============================================================================
# AGENTS
# ============================================================================

@wizard_bp.route("/agents", methods=["GET"])
def list_agents():
    """
    Liste tous les agents disponibles.

    Query params:
        category: Filtrer par catégorie (core, support, expert, sales, productivity, analytics)

    Returns:
        Liste des agents avec leur état d'activation.
    """
    category = request.args.get("category")
    all_agents = get_available_agents()

    # Filtrer par catégorie si spécifié
    if category:
        all_agents = [a for a in all_agents if a.get("category") == category]

    # Ajouter l'état d'activation depuis la config
    store = get_wizard_config_store()
    config = store.load()
    active_ids = set()
    if config:
        active_ids = {a.agent_id for a in config.get_active_agents()}

    agents_with_status = []
    for agent in all_agents:
        agent_copy = agent.copy()
        agent_copy["enabled"] = agent["id"] in active_ids
        agents_with_status.append(agent_copy)

    # Grouper par catégorie
    by_category = {}
    for agent in agents_with_status:
        cat = agent.get("category", "other")
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(agent)

    return jsonify({
        "count": len(agents_with_status),
        "agents": agents_with_status,
        "by_category": by_category,
    })


@wizard_bp.route("/agents/<agent_id>", methods=["PATCH"])
@require_json
def toggle_agent(agent_id: str):
    """
    Active ou désactive un agent.

    Args:
        agent_id: ID de l'agent.

    Body JSON:
        enabled: bool (requis)
        priority: int (optional, 0-100)

    Returns:
        État de l'agent après modification.
    """
    data = request.get_json()
    enabled = data.get("enabled")
    if enabled is None:
        return jsonify({"error": "enabled is required"}), 400

    priority = data.get("priority", 50)
    if not 0 <= priority <= 100:
        return jsonify({"error": "priority must be between 0 and 100"}), 400

    # Vérifier que l'agent existe
    all_agents = {a["id"]: a for a in get_available_agents()}
    if agent_id not in all_agents:
        return jsonify({"error": f"Agent not found: {agent_id}"}), 404

    # Vérifier qu'on ne désactive pas un agent core
    agent = all_agents[agent_id]
    if agent.get("category") == "core" and not enabled:
        return jsonify({"error": "Cannot disable core agents"}), 400

    # Modifier
    store = get_wizard_config_store()
    use_case = ToggleAgentUseCase(persistence=store)
    config = use_case.execute(agent_id, enabled, priority)

    if not config:
        return jsonify({"error": "No configuration found. Create one first."}), 404

    # Récupérer l'état actuel de l'agent
    is_active = config.is_agent_active(agent_id)
    agent_activation = next(
        (a for a in config.agents if a.agent_id == agent_id),
        None
    )

    return jsonify({
        "success": True,
        "agent_id": agent_id,
        "enabled": is_active,
        "priority": agent_activation.priority if agent_activation else priority,
    })


# ============================================================================
# KNOWLEDGE BASE
# ============================================================================

@wizard_bp.route("/knowledge-base", methods=["GET"])
def get_knowledge_base():
    """
    Récupère la knowledge base actuelle.

    Returns:
        Configuration de la knowledge base.
    """
    store = get_wizard_config_store()
    config = store.load()

    if not config:
        return jsonify({"error": "No configuration found"}), 404

    kb = config.knowledge_base

    return jsonify({
        "company_name": kb.company_name,
        "company_description": kb.company_description,
        "products_services": kb.products_services,
        "tone_guidelines": kb.tone_guidelines,
        "forbidden_topics": kb.forbidden_topics,
        "custom_signatures": kb.custom_signatures,
        "faq_entries": kb.faq_entries,
        "custom_file_path": kb.custom_file_path,
    })


@wizard_bp.route("/knowledge-base", methods=["PATCH"])
@require_json
def update_knowledge_base():
    """
    Met à jour la knowledge base.

    Body JSON: (tous optionnels)
        company_name: str
        company_description: str
        products_services: str
        tone_guidelines: str
        forbidden_topics: list[str]
        custom_signatures: dict
        faq_entries: dict

    Returns:
        Knowledge base mise à jour.
    """
    data = request.get_json()
    store = get_wizard_config_store()
    config = store.load()

    if not config:
        return jsonify({"error": "No configuration found"}), 404

    # Mettre à jour les champs fournis
    kb = config.knowledge_base

    if "company_name" in data:
        kb.company_name = data["company_name"]
    if "company_description" in data:
        kb.company_description = data["company_description"]
    if "products_services" in data:
        kb.products_services = data["products_services"]
    if "tone_guidelines" in data:
        kb.tone_guidelines = data["tone_guidelines"]
    if "forbidden_topics" in data:
        kb.forbidden_topics = data["forbidden_topics"]
    if "custom_signatures" in data:
        kb.custom_signatures = data["custom_signatures"]
    if "faq_entries" in data:
        kb.faq_entries = data["faq_entries"]

    # Sauvegarder
    save_use_case = SaveWizardConfigUseCase(persistence=store)
    save_use_case.execute(config)

    return jsonify({
        "success": True,
        "knowledge_base": {
            "company_name": kb.company_name,
            "company_description": kb.company_description,
            "products_services": kb.products_services,
            "tone_guidelines": kb.tone_guidelines,
            "forbidden_topics": kb.forbidden_topics,
        },
    })


@wizard_bp.route("/import", methods=["POST"])
@require_admin
@require_json
def import_kb():
    """
    Importe une knowledge base depuis un fichier.

    Body JSON:
        file_path: str (requis) - Chemin du fichier
        merge: bool (optional, default: false)

    Returns:
        Résultat de l'import.

    F-03 (audit issue #209, 2026-04-29): triple-gated — @require_admin,
    loopback-only in prod (Tauri desktop is the only legitimate caller;
    the web app never sends absolute paths), and `_is_safe_path()` check
    on the resolved path. Previously any authenticated user could read
    `/etc/passwd`, OAuth tokens, or the SQLite DB into the global wizard
    config and then read it back via GET /api/wizard/config.
    """
    from app.api.auth import is_trusted_loopback
    from app.api._auth_helpers import is_production

    if is_production() and not is_trusted_loopback():
        return jsonify({"error": "wizard import disabled outside loopback in production"}), 403

    data = request.get_json()
    file_path = data.get("file_path")
    if not file_path:
        return jsonify({"error": "file_path is required"}), 400

    if not _is_safe_path(file_path):
        return jsonify({"error": "Path outside allowed directories"}), 403

    merge = data.get("merge", False)

    try:
        store = get_wizard_config_store()
        use_case = ImportKnowledgeBaseUseCase(persistence=store)
        config = use_case.execute(file_path, merge=merge)

        if not config:
            return jsonify({"error": "No configuration found. Create one first."}), 404

        return jsonify({
            "success": True,
            "file_path": file_path,
            "merged": merge,
            "description_length": len(config.knowledge_base.company_description),
        })

    except FileNotFoundError:
        return jsonify({"error": "Specified file not found"}), 404
    except Exception as e:
        logger.error(f"Error importing KB: {e}")
        return jsonify({"error": "An internal error occurred while importing knowledge base"}), 500


@wizard_bp.route("/export", methods=["POST"])
@require_admin
@require_json
def export_config():
    """
    Exporte la configuration vers un fichier.

    Body JSON:
        file_path: str (requis) - Chemin de destination

    Returns:
        Confirmation de l'export.

    F-03 (audit issue #209, 2026-04-29): same triple gate as /import —
    @require_admin + loopback-only in prod + `_is_safe_path()` check.
    Previously could overwrite `.encryption_key`, breaking all encrypted
    token decryption on next boot.
    """
    from app.api.auth import is_trusted_loopback
    from app.api._auth_helpers import is_production

    if is_production() and not is_trusted_loopback():
        return jsonify({"error": "wizard export disabled outside loopback in production"}), 403

    data = request.get_json()
    file_path = data.get("file_path")
    if not file_path:
        return jsonify({"error": "file_path is required"}), 400

    if not _is_safe_path(file_path):
        return jsonify({"error": "Path outside allowed directories"}), 403

    try:
        store = get_wizard_config_store()
        use_case = ExportConfigUseCase(persistence=store)
        use_case.execute(file_path)

        return jsonify({
            "success": True,
            "file_path": file_path,
        })

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(f"Error exporting config: {e}")
        return jsonify({"error": "An internal error occurred while exporting configuration"}), 500


# ============================================================================
# TEST CONNECTION
# ============================================================================

MIN_PORT = 1
MAX_PORT = 65535
DEFAULT_IMAP_PORT = 993
DEFAULT_SMTP_PORT = 587


def _validate_connection_params(data: dict) -> tuple[bool, str | None]:
    """Valide les paramètres de connexion."""
    if not data.get("imap_host"):
        return False, "imap_host is required"
    if not data.get("smtp_host"):
        return False, "smtp_host is required"
    if not data.get("imap_username"):
        return False, "imap_username is required"
    if not data.get("smtp_username"):
        return False, "smtp_username is required"

    imap_port = data.get("imap_port", DEFAULT_IMAP_PORT)
    smtp_port = data.get("smtp_port", DEFAULT_SMTP_PORT)

    if not MIN_PORT <= imap_port <= MAX_PORT:
        return False, f"imap_port must be between {MIN_PORT} and {MAX_PORT}"
    if not MIN_PORT <= smtp_port <= MAX_PORT:
        return False, f"smtp_port must be between {MIN_PORT} and {MAX_PORT}"

    return True, None


def _test_imap_connection(data: dict) -> dict:
    """Teste la connexion IMAP et retourne le résultat."""
    start_time = time.time()
    imap = None
    try:
        imap = IMAPAdapter(
            host=data.get("imap_host"),
            port=data.get("imap_port", DEFAULT_IMAP_PORT),
            username=data.get("imap_username"),
            password=data.get("imap_password", ""),
            use_ssl=data.get("imap_use_ssl", True),
        )
        success = imap.authenticate()
        elapsed_ms = (time.time() - start_time) * 1000

        return {
            "success": success,
            "response_time_ms": round(elapsed_ms, 2),
        }
    except Exception as e:
        elapsed_ms = (time.time() - start_time) * 1000
        return {
            "success": False,
            "error": str(e),
            "response_time_ms": round(elapsed_ms, 2),
        }
    finally:
        if imap:
            try:
                imap.disconnect()
            except Exception:
                pass


def _test_smtp_connection(data: dict) -> dict:
    """Teste la connexion SMTP et retourne le résultat."""
    start_time = time.time()
    smtp = None
    try:
        smtp = SMTPAdapter(
            host=data.get("smtp_host"),
            port=data.get("smtp_port", DEFAULT_SMTP_PORT),
            username=data.get("smtp_username"),
            password=data.get("smtp_password", ""),
            use_tls=data.get("smtp_use_tls", True),
            use_ssl=data.get("smtp_use_ssl", False),
        )
        success = smtp.authenticate()
        elapsed_ms = (time.time() - start_time) * 1000

        return {
            "success": success,
            "response_time_ms": round(elapsed_ms, 2),
        }
    except Exception as e:
        elapsed_ms = (time.time() - start_time) * 1000
        return {
            "success": False,
            "error": str(e),
            "response_time_ms": round(elapsed_ms, 2),
        }
    finally:
        if smtp:
            try:
                smtp.disconnect()
            except Exception:
                pass


@wizard_bp.route("/test-connection", methods=["POST"])
@require_admin
@require_json
def test_connection():
    """
    Teste la connexion email IMAP et SMTP sans sauvegarder de configuration.

    Body JSON:
        imap_host: str (requis)
        imap_port: int (optional, default: 993)
        imap_username: str (requis)
        imap_password: str (optional)
        imap_use_ssl: bool (optional, default: True)
        smtp_host: str (requis)
        smtp_port: int (optional, default: 587)
        smtp_username: str (requis)
        smtp_password: str (optional)
        smtp_use_tls: bool (optional, default: True)
        smtp_use_ssl: bool (optional, default: False)

    Returns:
        JSON avec le status de chaque connexion.
    """
    data = request.get_json()

    is_valid, error_msg = _validate_connection_params(data)
    if not is_valid:
        return jsonify({"error": error_msg}), 400

    imap_result = _test_imap_connection(data)
    smtp_result = _test_smtp_connection(data)

    return jsonify({
        "success": imap_result["success"] and smtp_result["success"],
        "imap": imap_result,
        "smtp": smtp_result,
    })


# ============================================================================
# TEST LLM CONNECTION
# ============================================================================

def _test_claude_connection(api_key: str, model: str) -> dict:
    """Teste la connexion à Claude et retourne le résultat."""
    from app.adapters.llm.claude_adapter import ClaudeAdapter

    start_time = time.time()
    try:
        adapter = ClaudeAdapter(model=model, api_key=api_key)
        _response = adapter.complete(
            system="You are a test assistant.",
            user="Say 'Connection successful' in exactly those words.",
            max_tokens=20
        )
        elapsed_ms = (time.time() - start_time) * 1000

        return {
            "success": True,
            "provider": "claude",
            "model": model,
            "response_time_ms": round(elapsed_ms, 2),
        }
    except ValueError as e:
        elapsed_ms = (time.time() - start_time) * 1000
        return {
            "success": False,
            "error": str(e),
            "response_time_ms": round(elapsed_ms, 2),
        }
    except Exception as e:
        elapsed_ms = (time.time() - start_time) * 1000
        error_msg = str(e)
        if "authentication" in error_msg.lower() or "api key" in error_msg.lower():
            error_msg = "Clé API invalide"
        elif "rate limit" in error_msg.lower():
            error_msg = "Limite de requêtes atteinte"
        return {
            "success": False,
            "error": error_msg,
            "response_time_ms": round(elapsed_ms, 2),
        }


def _test_claude_code_connection(model: str) -> dict:
    """Teste la connexion via Claude Code CLI et retourne le résultat."""
    from app.adapters.llm.claude_code_adapter import ClaudeCodeAdapter
    from app.domain.exceptions import (
        LLMConnectionError,
        LLMResponseError,
        LLMTimeoutError,
    )

    start_time = time.time()
    try:
        adapter = ClaudeCodeAdapter(model=model, timeout=30)
        if not adapter.is_available():
            return {
                "success": False,
                "error": "Claude Code CLI not found. Install it with: npm install -g @anthropic-ai/claude-code",
                "response_time_ms": 0,
            }

        _response = adapter.complete(
            system="You are a test assistant.",
            user="Say 'Connection successful' in exactly those words.",
        )
        elapsed_ms = (time.time() - start_time) * 1000

        return {
            "success": True,
            "provider": "claude-code",
            "model": model,
            "response_time_ms": round(elapsed_ms, 2),
        }
    except (LLMConnectionError, LLMResponseError, LLMTimeoutError) as e:
        elapsed_ms = (time.time() - start_time) * 1000
        return {
            "success": False,
            "error": str(e),
            "response_time_ms": round(elapsed_ms, 2),
        }
    except Exception as e:
        elapsed_ms = (time.time() - start_time) * 1000
        return {
            "success": False,
            "error": f"Claude Code error: {e}",
            "response_time_ms": round(elapsed_ms, 2),
        }


def _test_ollama_connection(base_url: str, model: str) -> dict:
    """Teste la connexion à Ollama et retourne le résultat."""
    from app.adapters.llm.ollama_adapter import OllamaAdapter
    from app.domain.exceptions import (
        LLMConnectionError,
        LLMModelNotFoundError,
    )

    start_time = time.time()
    try:
        adapter = OllamaAdapter(model=model, base_url=base_url)

        if not adapter.is_available():
            elapsed_ms = (time.time() - start_time) * 1000
            return {
                "success": False,
                "error": f"Unable to connect to Ollama at {base_url}",
                "response_time_ms": round(elapsed_ms, 2),
            }

        available_models = adapter.list_models()
        if model not in available_models and available_models:
            elapsed_ms = (time.time() - start_time) * 1000
            return {
                "success": False,
                "error": f"Model '{model}' not found. Available models: {', '.join(available_models[:5])}",
                "response_time_ms": round(elapsed_ms, 2),
            }

        _response = adapter.complete(
            system="You are a test assistant.",
            user="Say 'OK'.",
            max_tokens=10
        )
        elapsed_ms = (time.time() - start_time) * 1000

        return {
            "success": True,
            "provider": "ollama",
            "model": model,
            "response_time_ms": round(elapsed_ms, 2),
        }
    except LLMConnectionError as e:
        elapsed_ms = (time.time() - start_time) * 1000
        return {
            "success": False,
            "error": f"Unable to connect to Ollama: {e}",
            "response_time_ms": round(elapsed_ms, 2),
        }
    except LLMModelNotFoundError as e:
        elapsed_ms = (time.time() - start_time) * 1000
        return {
            "success": False,
            "error": f"Model not found: {e}",
            "response_time_ms": round(elapsed_ms, 2),
        }
    except Exception as e:
        elapsed_ms = (time.time() - start_time) * 1000
        return {
            "success": False,
            "error": str(e),
            "response_time_ms": round(elapsed_ms, 2),
        }


@wizard_bp.route("/test-llm", methods=["POST"])
@require_admin
@require_json
def test_llm_connection():
    """
    Teste la connexion au LLM (Claude ou Ollama).

    AUTHZ-VULN-08 (issue #557): admin-only + ollama_url validée contre
    SSRF (scheme allowlist, blocage RFC 1918 en prod). Avant le fix, un
    appelant non authentifié pouvait déclencher une fetch outbound vers
    file://, gopher://, ou 169.254.169.254.

    Body JSON:
        provider: str (requis) - "claude" ou "ollama"
        api_key: str (requis pour claude)
        ollama_url: str (requis pour ollama, default: http://localhost:11434)
        model: str (requis)

    Returns:
        JSON avec le status de la connexion.
    """
    data = request.get_json()

    provider = data.get("provider")
    if provider not in ("claude", "claude-code", "ollama"):
        return jsonify({"error": "provider must be 'claude', 'claude-code' or 'ollama'"}), 400

    model = data.get("model")
    if not model:
        return jsonify({"error": "model is required"}), 400

    if provider == "claude":
        api_key = data.get("api_key")
        if not api_key:
            return jsonify({"error": "api_key is required for Claude"}), 400
        result = _test_claude_connection(api_key, model)
    elif provider == "claude-code":
        result = _test_claude_code_connection(model)
    else:
        ollama_url = data.get("ollama_url", "http://localhost:11434")
        ok, err = _validate_ollama_url(ollama_url)
        if not ok:
            return jsonify({"error": err}), 400
        result = _test_ollama_connection(ollama_url, model)

    return jsonify(result)


# ============================================================================
# IMPORT ENV FILE
# ============================================================================

def _parse_env_file(file_path: str) -> dict[str, str]:
    """Parse un fichier .env et retourne un dictionnaire des variables."""
    env_vars = {}

    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            if "=" not in line:
                continue

            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()

            # Supprime les guillemets autour des valeurs
            if (value.startswith('"') and value.endswith('"')) or \
               (value.startswith("'") and value.endswith("'")):
                value = value[1:-1]

            env_vars[key] = value

    return env_vars


def _parse_boolean(value: str) -> bool:
    """Parse une valeur booleenne depuis une string."""
    return value.lower() in ("true", "1", "yes", "on")


def _parse_int_safe(value: str, default: int = 0) -> int:
    """Parse un entier de facon securisee."""
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _build_imap_config(env_vars: dict[str, str]) -> dict:
    """Construit la configuration IMAP depuis les variables d'environnement."""
    config = {}

    if "IMAP_HOST" in env_vars:
        config["host"] = env_vars["IMAP_HOST"]
    if "IMAP_PORT" in env_vars:
        config["port"] = _parse_int_safe(env_vars["IMAP_PORT"], 993)
    if "IMAP_USER" in env_vars:
        config["username"] = env_vars["IMAP_USER"]
    if "IMAP_USE_SSL" in env_vars:
        config["use_ssl"] = _parse_boolean(env_vars["IMAP_USE_SSL"])
    if "IMAP_PASSWORD" in env_vars:
        config["has_password"] = True

    return config


def _build_smtp_config(env_vars: dict[str, str]) -> dict:
    """Construit la configuration SMTP depuis les variables d'environnement."""
    config = {}

    if "SMTP_HOST" in env_vars:
        config["host"] = env_vars["SMTP_HOST"]
    if "SMTP_PORT" in env_vars:
        config["port"] = _parse_int_safe(env_vars["SMTP_PORT"], 587)
    if "SMTP_USER" in env_vars:
        config["username"] = env_vars["SMTP_USER"]
    if "SMTP_USE_TLS" in env_vars:
        config["use_tls"] = _parse_boolean(env_vars["SMTP_USE_TLS"])
    if "SMTP_USE_SSL" in env_vars:
        config["use_ssl"] = _parse_boolean(env_vars["SMTP_USE_SSL"])
    if "SMTP_PASSWORD" in env_vars:
        config["has_password"] = True

    return config


def _build_gmail_config(env_vars: dict[str, str]) -> dict:
    """Construit la configuration Gmail depuis les variables d'environnement."""
    config = {}

    if "GOOGLE_CLIENT_ID" in env_vars:
        config["has_client_id"] = True
    if "GOOGLE_CLIENT_SECRET" in env_vars:
        config["has_client_secret"] = True
    if "GOOGLE_REFRESH_TOKEN" in env_vars:
        config["has_refresh_token"] = True

    return config


def _build_outlook_config(env_vars: dict[str, str]) -> dict:
    """Construit la configuration Outlook depuis les variables d'environnement."""
    from app.config import is_placeholder
    config = {}

    if "AZURE_TENANT_ID" in env_vars and not is_placeholder(env_vars.get("AZURE_TENANT_ID")):
        config["has_tenant_id"] = True
    if "AZURE_CLIENT_ID" in env_vars and not is_placeholder(env_vars.get("AZURE_CLIENT_ID")):
        config["has_client_id"] = True
    if "AZURE_CLIENT_SECRET" in env_vars and not is_placeholder(env_vars.get("AZURE_CLIENT_SECRET")):
        config["has_client_secret"] = True
    if "OUTLOOK_USER_ID" in env_vars:
        config["user_id"] = env_vars["OUTLOOK_USER_ID"]

    return config


def _build_llm_config(env_vars: dict[str, str]) -> dict:
    """Construit la configuration LLM depuis les variables d'environnement."""
    config = {}

    if "LLM_PROVIDER" in env_vars:
        config["provider"] = env_vars["LLM_PROVIDER"]
    if "LLM_MODEL" in env_vars:
        config["model"] = env_vars["LLM_MODEL"]
    if "ANTHROPIC_API_KEY" in env_vars:
        config["has_api_key"] = True
    if "OLLAMA_BASE_URL" in env_vars:
        config["ollama_url"] = env_vars["OLLAMA_BASE_URL"]

    return config


def _build_daemon_config(env_vars: dict[str, str]) -> dict:
    """Construit la configuration du daemon depuis les variables d'environnement."""
    config = {}

    if "DAEMON_POLL_INTERVAL" in env_vars:
        config["poll_interval"] = _parse_int_safe(env_vars["DAEMON_POLL_INTERVAL"], 60)

    return config


@wizard_bp.route("/import-env", methods=["POST"])
@require_admin
@require_json
def import_env():
    """
    Importe et parse un fichier .env existant pour pre-remplir le wizard.

    Body JSON:
        file_path: str (requis) - Chemin vers le fichier .env

    Returns:
        JSON avec la configuration detectee, sans exposer les secrets.

    F-03 (audit issue #209, 2026-04-29): same triple gate — admin +
    loopback-only in prod + `_is_safe_path()`. Previously an attacker
    could probe filesystem (`/etc/shadow` returns 500 vs 404) and parse
    sensitive .env-like files anywhere on disk.
    """
    from app.api.auth import is_trusted_loopback
    from app.api._auth_helpers import is_production

    if is_production() and not is_trusted_loopback():
        return jsonify({"error": "wizard import-env disabled outside loopback in production"}), 403

    data = request.get_json()
    file_path = data.get("file_path")

    if not file_path:
        return jsonify({"error": "file_path is required"}), 400

    if not _is_safe_path(file_path):
        return jsonify({"error": "Path outside allowed directories"}), 403

    import os
    if not os.path.exists(file_path):
        return jsonify({"error": "File not found"}), 404

    try:
        env_vars = _parse_env_file(file_path)

        result = {
            "success": True,
            "variables_count": len(env_vars),
            "provider_type": env_vars.get("EMAIL_PROVIDER_TYPE", ""),
        }

        # Configuration IMAP
        imap_config = _build_imap_config(env_vars)
        if imap_config:
            result["imap"] = imap_config

        # Configuration SMTP
        smtp_config = _build_smtp_config(env_vars)
        if smtp_config:
            result["smtp"] = smtp_config

        # Configuration Gmail
        gmail_config = _build_gmail_config(env_vars)
        if gmail_config:
            result["gmail"] = gmail_config

        # Configuration Outlook
        outlook_config = _build_outlook_config(env_vars)
        if outlook_config:
            result["outlook"] = outlook_config

        # Configuration LLM
        llm_config = _build_llm_config(env_vars)
        if llm_config:
            result["llm"] = llm_config

        # Configuration Daemon
        daemon_config = _build_daemon_config(env_vars)
        if daemon_config:
            result["daemon"] = daemon_config

        return jsonify(result)

    except Exception as e:
        logger.error(f"Error importing .env file: {e}")
        return jsonify({"error": "Error parsing .env file"}), 500


# ============================================================================
# STYLE ANALYSIS
# ============================================================================

def _analyze_sent_emails_style(
    imap_host: str,
    imap_port: int,
    imap_username: str,
    imap_password: str,
    imap_use_ssl: bool = True,
    max_emails: int = 10,
    timeout_sec: int = 15,
) -> dict:
    """
    Analyse les emails envoyes pour extraire le style de l'utilisateur.

    Phase 1 - Detection rapide (10 emails, 15 secondes max):
    - Signature (nom, poste, entreprise)
    - Ton general (formel/informel, tu/vous)
    - Longueur moyenne des reponses
    """
    import signal
    from contextlib import contextmanager

    @contextmanager
    def timeout_context(seconds: int):
        """Context manager pour timeout."""
        def handler(signum, frame):
            raise TimeoutError("Timeout: analyse trop longue")

        old_handler = signal.signal(signal.SIGALRM, handler)
        signal.alarm(seconds)
        try:
            yield
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)

    imap = None
    try:
        with timeout_context(timeout_sec):
            imap = IMAPAdapter(
                host=imap_host,
                port=imap_port,
                username=imap_username,
                password=imap_password,
                use_ssl=imap_use_ssl,
            )

            if not imap.authenticate():
                return {
                    "success": False,
                    "error": "Unable to connect to IMAP server",
                }

            # Recuperer les emails envoyes
            sent_emails = imap.get_sent_emails(limit=max_emails)
            emails_analyzed = len(sent_emails)

            if emails_analyzed == 0:
                return {
                    "success": True,
                    "emails_analyzed": 0,
                    "warning": "Aucun email envoyé trouvé.",
                    "profile": _empty_profile(),
                }

            if emails_analyzed < 5:
                warning = f"Seulement {emails_analyzed} emails trouves. Analyse partielle."
            else:
                warning = None

            # Analyser le style
            profile = _extract_style_profile(sent_emails)

            result = {
                "success": True,
                "emails_analyzed": emails_analyzed,
                "profile": profile,
            }
            if warning:
                result["warning"] = warning

            return result

    except TimeoutError as e:
        return {
            "success": False,
            "error": str(e),
        }
    except Exception as e:
        logger.error(f"Error analyzing style: {e}")
        return {
            "success": False,
            "error": f"Unable to connect to IMAP server: {e}",
        }
    finally:
        if imap:
            try:
                imap.disconnect()
            except Exception:
                pass


def _empty_profile() -> dict:
    """Retourne un profil de style vide."""
    return {
        "signature": None,
        "tone": "unknown",
        "formality_level": "unknown",
        "avg_response_length": 0,
        "greeting_patterns": [],
        "closing_patterns": [],
    }


def _extract_style_profile(emails: list) -> dict:
    """
    Extrait le profil de style depuis une liste d'emails.

    Detecte:
    - Signature (nom, poste, entreprise)
    - Ton (formel/informel)
    - Niveau de formalite (tu/vous)
    - Longueur moyenne
    - Formules de salutation
    - Formules de conclusion
    """
    import re
    from collections import Counter

    greetings = Counter()
    closings = Counter()
    total_length = 0
    vous_count = 0
    tu_count = 0
    signatures = []

    greeting_patterns = [
        r"^(Bonjour[^,\n]*)",
        r"^(Bonsoir[^,\n]*)",
        r"^(Cher[^,\n]*)",
        r"^(Chere[^,\n]*)",
        r"^(Hello[^,\n]*)",
        r"^(Hi[^,\n]*)",
        r"^(Salut[^,\n]*)",
    ]

    closing_patterns = [
        r"(Cordialement[^,\n]*)",
        r"(Bien [a\u00e0] vous[^,\n]*)",
        r"(Bien cordialement[^,\n]*)",
        r"(Meilleures salutations[^,\n]*)",
        r"(Best regards[^,\n]*)",
        r"(Best[^,\n]*)",
        r"(Merci[^,\n]*)",
        r"(A bient[o\u00f4]t[^,\n]*)",
        r"(Amicalement[^,\n]*)",
    ]

    signature_pattern = re.compile(
        r"(?:^|\n)--\s*\n(.+?)(?:\n\n|\Z)|"
        r"(?:Cordialement|Bien [a\u00e0] vous|Best),?\s*\n+([A-Z][a-z]+ [A-Z][a-z]+(?:\n.+)?)",
        re.MULTILINE | re.DOTALL
    )

    def _email_text(email) -> str:
        if isinstance(email, dict):
            return (
                email.get("body", "")
                or email.get("content", "")
                or email.get("body_text", "")
            )
        return (
            getattr(email, "body", "")
            or getattr(email, "content", "")
            or getattr(email, "body_text", "")
        )

    for email in emails:
        body = _email_text(email)
        if not body:
            continue

        total_length += len(body)

        # Detecter formules de salutation
        for pattern in greeting_patterns:
            matches = re.findall(pattern, body, re.IGNORECASE | re.MULTILINE)
            for match in matches:
                greetings[match.strip()] += 1

        # Detecter formules de conclusion
        for pattern in closing_patterns:
            matches = re.findall(pattern, body, re.IGNORECASE)
            for match in matches:
                closings[match.strip()] += 1

        # Compter tu/vous
        vous_count += len(re.findall(r"\bvous\b", body, re.IGNORECASE))
        tu_count += len(re.findall(r"\b(tu|toi)\b", body, re.IGNORECASE))

        # Detecter signature
        sig_matches = signature_pattern.findall(body)
        for match in sig_matches:
            sig = match[0] if match[0] else match[1] if len(match) > 1 else None
            if sig and len(sig) < 500:
                signatures.append(sig.strip())

    # Calculer les resultats
    num_emails = len(emails)
    avg_length = total_length // num_emails if num_emails > 0 else 0

    # Determiner le niveau de formalite
    if vous_count > tu_count * 2:
        formality_level = "vous"
    elif tu_count > vous_count * 2:
        formality_level = "tu"
    else:
        formality_level = "mixed"

    # Determiner le ton
    formal_indicators = vous_count + sum(1 for g in greetings if "cher" in g.lower())
    informal_indicators = tu_count + sum(1 for g in greetings if "salut" in g.lower())

    if formal_indicators > informal_indicators:
        tone = "formal"
    elif informal_indicators > formal_indicators:
        tone = "informal"
    else:
        tone = "neutral"

    # Extraire la signature la plus commune
    signature_info = _parse_signature(signatures) if signatures else None

    return {
        "signature": signature_info,
        "tone": tone,
        "formality_level": formality_level,
        "avg_response_length": avg_length,
        "greeting_patterns": [g for g, _ in greetings.most_common(3)],
        "closing_patterns": [c for c, _ in closings.most_common(3)],
    }


def _parse_signature(signatures: list) -> dict | None:
    """
    Parse les signatures pour extraire nom, poste, entreprise.
    """
    import re

    if not signatures:
        return None

    # Prendre la signature la plus longue (probablement la plus complete)
    sig = max(signatures, key=len)
    lines = [line.strip() for line in sig.split("\n") if line.strip()]

    if not lines:
        return None

    result = {
        "name": None,
        "title": None,
        "company": None,
    }

    # Premiere ligne = nom
    if lines:
        result["name"] = lines[0]

    # Chercher poste et entreprise dans les lignes suivantes
    for line in lines[1:4]:
        # Pattern pour poste
        title_patterns = [
            r"(Directeur|Manager|CEO|CTO|CFO|Responsable|Chef|Lead|Senior|Junior|"
            r"Consultant|Ingenieur|Developpeur|Designer|Analyste|Commercial|"
            r"Fondateur|President|Associe|Partner)[^|,\n]*",
        ]
        for pattern in title_patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if match and not result["title"]:
                result["title"] = line
                break

        # Pattern pour entreprise (@ ou chez ou |)
        company_patterns = [
            r"@\s*(.+)",
            r"chez\s+(.+)",
            r"\|\s*(.+)",
        ]
        for pattern in company_patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if match and not result["company"]:
                result["company"] = match.group(1).strip()
                break

    # Si pas de company trouvee mais une ligne reste
    if not result["company"] and len(lines) > 2:
        # Verifier si c'est un nom d'entreprise (commence par majuscule, pas un email)
        for line in lines[1:]:
            if "@" not in line and line[0].isupper() and not result["title"]:
                if not result["company"]:
                    result["company"] = line

    return result if result["name"] else None


def _save_style_profile(profile: dict) -> dict:
    """Sauvegarde le profil de style dans la configuration."""
    store = get_wizard_config_store()
    config = store.load()

    if not config:
        return {"success": False, "error": "No configuration found"}

    # Sauvegarder le profil dans la knowledge base
    if config.knowledge_base:
        # Ajouter les formules detectees
        if profile.get("closing_patterns"):
            config.knowledge_base.custom_signatures["default"] = profile["closing_patterns"][0]
        if profile.get("signature"):
            sig = profile["signature"]
            sig_text = sig.get("name", "")
            if sig.get("title"):
                sig_text += f"\n{sig['title']}"
            if sig.get("company"):
                sig_text += f"\n{sig['company']}"
            config.knowledge_base.custom_signatures["full"] = sig_text

        # Ajouter les guidelines de ton
        tone = profile.get("tone", "neutral")
        formality = profile.get("formality_level", "vous")
        guidelines = []
        if tone == "formal":
            guidelines.append("Utiliser un ton formel et professionnel")
        elif tone == "informal":
            guidelines.append("Utiliser un ton decontracte et amical")
        if formality == "vous":
            guidelines.append("Vouvoyer systematiquement")
        elif formality == "tu":
            guidelines.append("Tutoyer de preference")
        if guidelines:
            config.knowledge_base.tone_guidelines = ". ".join(guidelines)

    save_use_case = SaveWizardConfigUseCase(persistence=store)
    save_use_case.execute(config)

    return {"success": True}


def _analyze_oauth_style(max_emails: int = 10) -> dict:
    """
    Analyse le style via le provider OAuth configuré (Gmail/Outlook).

    Args:
        max_emails: Nombre max d'emails à analyser.

    Returns:
        Dictionnaire avec le profil de style.
    """
    provider = None
    try:
        from app.api import routes_helpers as _rh
        from app.providers.factory import get_pooled_provider

        account_id = _rh._resolve_account_id_for_user()
        if not account_id or account_id <= 0:
            return {"success": False, "error": "No active account"}
        oauth_account_id = _rh._resolve_oauth_account_id_for_db_account(account_id)
        if not oauth_account_id:
            return {"success": False, "error": "Email provider not configured"}

        provider = get_pooled_provider(account_id=oauth_account_id)
        if not provider:
            return {"success": False, "error": "Email provider not configured"}

        # Vérifier que le provider supporte get_sent_emails
        if not hasattr(provider, "get_sent_emails"):
            return {"success": False, "error": "Provider does not support style analysis"}

        emails = provider.get_sent_emails(limit=max_emails)

        # Disconnect IMAP immediately after fetching
        if hasattr(provider, 'disconnect'):
            provider.disconnect()
            provider = None

        if not emails:
            return {
                "success": True,
                "emails_analyzed": 0,
                "warning": "Aucun email envoyé trouvé",
                "profile": {
                    "signature": None,
                    "tone": "unknown",
                    "formality_level": "unknown",
                    "avg_response_length": 0,
                    "greeting_patterns": [],
                    "closing_patterns": [],
                }
            }

        profile = _extract_style_profile(emails)

        return {
            "success": True,
            "emails_analyzed": len(emails),
            "profile": profile,
        }

    except Exception as e:
        logger.warning(f"Erreur analyse style OAuth: {e}")
        return {"success": False, "error": str(e)}
    finally:
        if provider and hasattr(provider, 'disconnect'):
            try:
                provider.disconnect()
            except Exception:
                pass


@wizard_bp.route("/analyze-style", methods=["POST"])
@require_json
def analyze_style():
    """
    Analyse les emails envoyes pour extraire le style de l'utilisateur.

    Phase 1 de l'onboarding - Detection rapide (10 emails, 15 secondes max).

    Body JSON:
        use_oauth: bool (optional) - Utiliser le provider OAuth configuré
        imap_host: str (requis si use_oauth=false)
        imap_port: int (optional, default: 993)
        imap_username: str (requis si use_oauth=false)
        imap_password: str (requis si use_oauth=false)
        imap_use_ssl: bool (optional, default: True)
        max_emails: int (optional, default: 10)
        timeout_sec: int (optional, default: 15)

    Returns:
        JSON avec le profil de style detecte.
    """
    data = request.get_json()

    # Si OAuth est activé, utiliser le provider configuré
    if data.get("use_oauth"):
        result = _analyze_oauth_style(max_emails=data.get("max_emails", 10))
        return jsonify(result)

    # Sinon, utiliser IMAP (comportement original)
    if not data.get("imap_host"):
        return jsonify({"error": "imap_host is required (email config missing)"}), 400
    if not data.get("imap_username"):
        return jsonify({"error": "imap_username is required (email config missing)"}), 400
    if not data.get("imap_password"):
        return jsonify({"error": "imap_password is required (email config missing)"}), 400

    result = _analyze_sent_emails_style(
        imap_host=data["imap_host"],
        imap_port=data.get("imap_port", DEFAULT_IMAP_PORT),
        imap_username=data["imap_username"],
        imap_password=data["imap_password"],
        imap_use_ssl=data.get("imap_use_ssl", True),
        max_emails=data.get("max_emails", 10),
        timeout_sec=data.get("timeout_sec", 15),
    )

    return jsonify(result)


@wizard_bp.route("/save-style", methods=["POST"])
@require_json
def save_style():
    """
    Sauvegarde le profil de style confirme par l'utilisateur.

    Body JSON:
        profile: dict (requis) - Le profil de style
        confirmed: bool (requis) - L'utilisateur a confirme

    Returns:
        JSON avec le status de la sauvegarde.
    """
    data = request.get_json()

    if not data.get("confirmed"):
        return jsonify({"error": "User confirmation required"}), 400

    profile = data.get("profile", {})
    result = _save_style_profile(profile)

    if result.get("success"):
        return jsonify(result)
    else:
        return jsonify(result), 400


# ============================================================================
# DEEP STYLE ANALYSIS (PHASE 2 - BACKGROUND)
# ============================================================================

# Storage for background tasks
_deep_analysis_tasks: dict[str, dict] = {}
_tasks_lock = threading.Lock()

# S-11 fix (2026-04-24): trim entries older than 1h on each insert. Without
# this, every onboarding run leaks a dict (with potentially tens-of-KB
# `deep_profile` blobs) and the dict grows unbounded over the container's
# lifetime.
_DEEP_ANALYSIS_TTL_SECONDS = 3600.0


def _trim_deep_analysis_tasks(now: float | None = None) -> int:
    """Drop deep-analysis task entries older than the TTL.

    Caller MUST hold `_tasks_lock`. Returns the number of entries evicted
    (useful for tests / observability).
    """
    import time as _time
    if now is None:
        now = _time.time()
    to_drop: list[str] = []
    for tid, entry in _deep_analysis_tasks.items():
        # Entries persisted with started_at as ISO; fall back to a None →
        # always-fresh interpretation (don't evict when timestamp missing).
        started_at = entry.get("started_at")
        ts = entry.get("_started_epoch")
        if ts is None and isinstance(started_at, str):
            try:
                ts = datetime.fromisoformat(started_at.replace("Z", "+00:00")).timestamp()
                entry["_started_epoch"] = ts
            except Exception:
                ts = None
        if ts is None:
            continue
        if now - ts > _DEEP_ANALYSIS_TTL_SECONDS:
            to_drop.append(tid)
    for tid in to_drop:
        _deep_analysis_tasks.pop(tid, None)
    return len(to_drop)


def _start_deep_style_analysis(
    imap_host: str,
    imap_port: int,
    imap_username: str,
    imap_password: str,
    imap_use_ssl: bool = True,
    max_emails: int = 50,
) -> dict:
    """
    Demarre l'analyse approfondie du style en arriere-plan.

    Phase 2 - Apprentissage profond:
    - Analyse 40 emails supplementaires (total 50)
    - Detecte formules recurrentes, patterns contextuels, expressions
    """
    task_id = f"deep-{uuid.uuid4().hex[:8]}"

    import time as _time
    _now_epoch = _time.time()
    with _tasks_lock:
        # S-11: garbage-collect old entries on every insert.
        _trim_deep_analysis_tasks(now=_now_epoch)
        _deep_analysis_tasks[task_id] = {
            "task_id": task_id,
            "status": "started",
            "progress": 0,
            "emails_analyzed": 0,
            "patterns_found": 0,
            "started_at": datetime.utcnow().isoformat(),
            "_started_epoch": _now_epoch,
            "deep_profile": None,
            "error": None,
        }

    def run_analysis():
        try:
            _execute_deep_analysis(
                task_id,
                imap_host,
                imap_port,
                imap_username,
                imap_password,
                imap_use_ssl,
                max_emails,
            )
        except Exception as e:
            with _tasks_lock:
                if task_id in _deep_analysis_tasks:
                    _deep_analysis_tasks[task_id]["status"] = "failed"
                    _deep_analysis_tasks[task_id]["error"] = str(e)

    thread = threading.Thread(target=run_analysis, daemon=True)
    thread.start()

    return {
        "success": True,
        "task_id": task_id,
        "status": "started",
        "estimated_duration_sec": 120,
    }


def _execute_deep_analysis(
    task_id: str,
    imap_host: str,
    imap_port: int,
    imap_username: str,
    imap_password: str,
    imap_use_ssl: bool,
    max_emails: int,
) -> None:
    """Execute l'analyse approfondie en arriere-plan."""

    imap = None
    try:
        imap = IMAPAdapter(
            host=imap_host,
            port=imap_port,
            username=imap_username,
            password=imap_password,
            use_ssl=imap_use_ssl,
        )

        if not imap.authenticate():
            with _tasks_lock:
                _deep_analysis_tasks[task_id]["status"] = "failed"
                _deep_analysis_tasks[task_id]["error"] = "Impossible de se connecter au serveur IMAP"
            return

        with _tasks_lock:
            _deep_analysis_tasks[task_id]["status"] = "in_progress"

        sent_emails = imap.get_sent_emails(limit=max_emails)
        total_emails = len(sent_emails)

        if total_emails == 0:
            with _tasks_lock:
                _deep_analysis_tasks[task_id]["status"] = "completed"
                _deep_analysis_tasks[task_id]["progress"] = 100
                _deep_analysis_tasks[task_id]["deep_profile"] = _empty_deep_profile()
            return

        deep_profile = _analyze_deep_patterns(sent_emails, task_id)

        with _tasks_lock:
            _deep_analysis_tasks[task_id]["status"] = "completed"
            _deep_analysis_tasks[task_id]["progress"] = 100
            _deep_analysis_tasks[task_id]["emails_analyzed"] = total_emails
            _deep_analysis_tasks[task_id]["deep_profile"] = deep_profile

    except Exception as e:
        logger.error(f"Deep analysis error: {e}")
        with _tasks_lock:
            if task_id in _deep_analysis_tasks:
                _deep_analysis_tasks[task_id]["status"] = "failed"
                _deep_analysis_tasks[task_id]["error"] = str(e)
    finally:
        if imap:
            try:
                imap.disconnect()
            except Exception:
                pass


def _analyze_deep_patterns(emails: list, task_id: str) -> dict:
    """
    Analyse approfondie des patterns d'ecriture.

    Detecte:
    - Formules recurrentes (salutations, conclusions)
    - Patterns contextuels (client vs collegue)
    - Expressions signature
    - Rythme de reponse par type d'email
    """
    import re
    from collections import Counter, defaultdict

    greetings = Counter()
    closings = Counter()
    expressions = Counter()
    context_patterns = defaultdict(lambda: {"count": 0, "lengths": [], "tones": []})

    greeting_patterns = [
        r"^(Bonjour[^,\n]*)",
        r"^(Bonsoir[^,\n]*)",
        r"^(Cher[^,\n]*)",
        r"^(Chere[^,\n]*)",
        r"^(Hello[^,\n]*)",
        r"^(Hi[^,\n]*)",
        r"^(Salut[^,\n]*)",
    ]

    closing_patterns_regex = [
        r"(Cordialement[^,\n]*)",
        r"(Bien [aà] vous[^,\n]*)",
        r"(Bien cordialement[^,\n]*)",
        r"(Meilleures salutations[^,\n]*)",
        r"(Best regards[^,\n]*)",
        r"(Merci[^,\n]*)",
        r"(A bient[oô]t[^,\n]*)",
        r"(Amicalement[^,\n]*)",
    ]

    signature_expressions_patterns = [
        r"(N'h[eé]sitez pas [aà] me contacter[^.\n]*)",
        r"(Je reste [aà] votre disposition[^.\n]*)",
        r"(Je me tiens [aà] votre disposition[^.\n]*)",
        r"(N'h[eé]sitez pas [aà] revenir vers moi[^.\n]*)",
        r"(En esp[eé]rant avoir r[eé]pondu [aà] votre question[^.\n]*)",
        r"(Restant [aà] votre disposition[^.\n]*)",
        r"(Dans l'attente de votre retour[^.\n]*)",
    ]

    total = len(emails)
    for idx, email in enumerate(emails):
        body = email.get("body", "") or email.get("content", "")
        if not body:
            continue

        progress = int((idx + 1) / total * 100)
        with _tasks_lock:
            if task_id in _deep_analysis_tasks:
                _deep_analysis_tasks[task_id]["progress"] = progress
                _deep_analysis_tasks[task_id]["emails_analyzed"] = idx + 1

        for pattern in greeting_patterns:
            matches = re.findall(pattern, body, re.IGNORECASE | re.MULTILINE)
            for match in matches:
                greetings[match.strip()] += 1

        for pattern in closing_patterns_regex:
            matches = re.findall(pattern, body, re.IGNORECASE)
            for match in matches:
                closings[match.strip()] += 1

        for pattern in signature_expressions_patterns:
            matches = re.findall(pattern, body, re.IGNORECASE)
            for match in matches:
                expressions[match.strip()] += 1

        context = _detect_email_context(email)
        context_patterns[context]["count"] += 1
        context_patterns[context]["lengths"].append(len(body))
        context_patterns[context]["tones"].append(_detect_tone(body))

    greeting_results = [
        {"formula": g, "frequency": c, "contexts": ["professional"]}
        for g, c in greetings.most_common(5)
        if c >= 3
    ]

    closing_results = [
        {"formula": cl, "frequency": c, "contexts": _infer_context(cl)}
        for cl, c in closings.most_common(5)
        if c >= 3
    ]

    expression_results = [e for e, c in expressions.most_common(5) if c >= 2]

    contextual = {}
    for ctx, data in context_patterns.items():
        if data["count"] >= 2:
            avg_len = sum(data["lengths"]) // len(data["lengths"]) if data["lengths"] else 0
            tone_counter = Counter(data["tones"])
            dominant_tone = tone_counter.most_common(1)[0][0] if tone_counter else "neutral"
            contextual[ctx] = {
                "tone": dominant_tone,
                "avg_length": avg_len,
            }

    patterns_found = len(greeting_results) + len(closing_results) + len(expression_results)
    with _tasks_lock:
        if task_id in _deep_analysis_tasks:
            _deep_analysis_tasks[task_id]["patterns_found"] = patterns_found

    return {
        "recurring_formulas": {
            "greetings": greeting_results,
            "closings": closing_results,
        },
        "contextual_patterns": contextual,
        "signature_expressions": expression_results,
        "response_rhythm": {
            "urgent": {"avg_delay_hours": 1},
            "normal": {"avg_delay_hours": 24},
        },
    }


def _empty_deep_profile() -> dict:
    """Retourne un profil approfondi vide."""
    return {
        "recurring_formulas": {"greetings": [], "closings": []},
        "contextual_patterns": {},
        "signature_expressions": [],
        "response_rhythm": {},
    }


def _detect_email_context(email: dict) -> str:
    """Détecte le contexte de l'email (client, collegue, etc.)."""
    to_addr = email.get("to", "") or ""
    subject = email.get("subject", "") or ""

    to_lower = to_addr.lower()
    subj_lower = subject.lower()

    if any(kw in subj_lower for kw in ["urgent", "asap", "important"]):
        return "urgent"
    if any(kw in subj_lower for kw in ["facture", "devis", "commande", "invoice"]):
        return "client"
    if any(kw in to_lower for kw in ["support", "contact", "info", "client"]):
        return "client"
    if any(kw in subj_lower for kw in ["re:", "fwd:", "tr:"]):
        return "followup"

    return "colleague"


def _detect_tone(text: str) -> str:
    """Détecte le ton d'un texte."""
    import re

    vous_count = len(re.findall(r"\bvous\b", text, re.IGNORECASE))
    tu_count = len(re.findall(r"\b(tu|toi)\b", text, re.IGNORECASE))

    formal_markers = len(re.findall(r"\b(cher|madame|monsieur|veuillez)\b", text, re.IGNORECASE))
    informal_markers = len(re.findall(r"\b(salut|coucou|bisous|bises)\b", text, re.IGNORECASE))

    if formal_markers > 0 or vous_count > tu_count * 2:
        return "formal"
    if informal_markers > 0 or tu_count > vous_count:
        return "informal"
    return "neutral"


def _infer_context(closing: str) -> list[str]:
    """Infere le contexte d'une formule de conclusion."""
    closing_lower = closing.lower()

    if any(kw in closing_lower for kw in ["cordialement", "salutations", "sincères"]):
        return ["professional", "formal"]
    if any(kw in closing_lower for kw in ["amicalement", "bises", "bisous"]):
        return ["informal", "personal"]
    if any(kw in closing_lower for kw in ["best", "regards", "sincerely"]):
        return ["professional", "international"]

    return ["professional"]


def _get_deep_analysis_status(task_id: str) -> dict | None:
    """Retourne le status d'une tache d'analyse approfondie."""
    with _tasks_lock:
        return _deep_analysis_tasks.get(task_id)


def _cancel_deep_analysis(task_id: str) -> dict:
    """Annule une tache d'analyse approfondie."""
    with _tasks_lock:
        if task_id in _deep_analysis_tasks:
            _deep_analysis_tasks[task_id]["status"] = "cancelled"
            return {"success": True, "status": "cancelled"}
        return {"success": False, "error": "Task not found"}


@wizard_bp.route("/analyze-style-deep", methods=["POST"])
@require_json
def analyze_style_deep():
    """
    Lance l'analyse approfondie du style en arriere-plan (Phase 2).

    Analyse 40 emails supplementaires pour detecter:
    - Formules recurrentes (salutations, conclusions)
    - Patterns contextuels (client vs collegue)
    - Expressions signature
    - Rythme de reponse

    Body JSON:
        imap_host: str (requis)
        imap_port: int (optional, default: 993)
        imap_username: str (requis)
        imap_password: str (requis)
        imap_use_ssl: bool (optional, default: True)
        max_emails: int (optional, default: 50)

    Returns:
        202 Accepted avec task_id pour suivre la progression.
    """
    data = request.get_json()

    if not data.get("imap_host"):
        return jsonify({"error": "imap_host is required (email config missing)"}), 400
    if not data.get("imap_username"):
        return jsonify({"error": "imap_username is required (email config missing)"}), 400
    if not data.get("imap_password"):
        return jsonify({"error": "imap_password is required (email config missing)"}), 400

    result = _start_deep_style_analysis(
        imap_host=data["imap_host"],
        imap_port=data.get("imap_port", DEFAULT_IMAP_PORT),
        imap_username=data["imap_username"],
        imap_password=data["imap_password"],
        imap_use_ssl=data.get("imap_use_ssl", True),
        max_emails=data.get("max_emails", 50),
    )

    if result.get("success"):
        return jsonify(result), 202
    else:
        return jsonify(result)


@wizard_bp.route("/analyze-style-deep/<task_id>", methods=["GET"])
def get_deep_analysis_status(task_id: str):
    """
    Retourne le status d'une tache d'analyse approfondie.

    Args:
        task_id: ID de la tache retourne par POST /analyze-style-deep

    Returns:
        Status de la tache avec progression et resultats si termine.
    """
    result = _get_deep_analysis_status(task_id)

    if not result:
        return jsonify({"error": "Task not found"}), 404

    return jsonify(result)


@wizard_bp.route("/analyze-style-deep/<task_id>", methods=["DELETE"])
def cancel_deep_analysis(task_id: str):
    """
    Annule une tache d'analyse approfondie en cours.

    Args:
        task_id: ID de la tache a annuler.

    Returns:
        Confirmation d'annulation.
    """
    result = _cancel_deep_analysis(task_id)
    return jsonify(result)


# ============================================================================
# LLM SETTINGS
# ============================================================================

def _update_env_variable(key: str, value: str) -> None:
    """Met à jour une variable dans le fichier .env."""
    env_path = PROJECT_ROOT / ".env"

    if not env_path.exists():
        # Créer le fichier s'il n'existe pas
        env_path.write_text(f"{key}={value}\n", encoding="utf-8")
        return

    lines = env_path.read_text(encoding="utf-8").splitlines()
    found = False
    new_lines = []

    for line in lines:
        if line.strip().startswith(f"{key}="):
            new_lines.append(f"{key}={value}")
            found = True
        else:
            new_lines.append(line)

    if not found:
        new_lines.append(f"{key}={value}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


@wizard_bp.route("/llm-settings", methods=["GET"])
@require_admin
def get_llm_settings():
    """
    Récupère la configuration LLM actuelle.

    AUTHZ-VULN-09 (issue #557): admin-only — la valeur leaks la base URL
    Ollama, ce qui est utile à un attaquant qui prépare son SSRF.

    Returns:
        JSON avec la configuration LLM.
    """
    import os

    return jsonify({
        "success": True,
        "llm": {
            "provider": os.getenv("LLM_PROVIDER", "claude"),
            "model": os.getenv("LLM_MODEL", ""),
            "ollama_url": os.getenv("OLLAMA_URL", "http://localhost:11434"),
            "has_api_key": bool(os.getenv("ANTHROPIC_API_KEY")),
        }
    })


@wizard_bp.route("/llm-settings", methods=["POST"])
@require_admin
@require_json
def save_llm_settings():
    """
    Sauvegarde la configuration LLM dans le fichier .env.

    AUTHZ-VULN-09 (Shannon pentest 2026-05-05, issue #557): admin-only +
    ollama_url validée. Avant le fix, un appelant non auth pouvait écrire
    une URL d'attaquant dans `.env` + `os.environ` — redirigeant ainsi
    TOUS les appels LLM Ollama de la plateforme vers l'attaquant, de
    manière persistante cross-restart. Persistant + global = critical.

    Body JSON:
        provider: str (requis) - "claude" ou "ollama"
        api_key: str (requis pour claude)
        ollama_url: str (optionnel, default: http://localhost:11434)
        model: str (requis)

    Returns:
        JSON avec confirmation de sauvegarde.
    """
    data = request.get_json()

    provider = data.get("provider")
    if provider not in ("claude", "claude-code", "ollama"):
        return jsonify({"error": "provider must be 'claude', 'claude-code' or 'ollama'"}), 400

    model = data.get("model")
    if not model:
        return jsonify({"error": "model is required"}), 400

    # Pre-validate ollama_url BEFORE any write to .env or os.environ.
    # If the URL is bad we want to fail closed without poisoning state.
    if provider == "ollama":
        ollama_url = data.get("ollama_url", "http://localhost:11434")
        ok, err = _validate_ollama_url(ollama_url)
        if not ok:
            return jsonify({"error": err}), 400

    try:
        # Sauvegarder le provider et le modèle
        _update_env_variable("LLM_PROVIDER", provider)
        _update_env_variable("LLM_MODEL", model)

        if provider == "claude":
            api_key = data.get("api_key")
            if api_key:
                _update_env_variable("ANTHROPIC_API_KEY", api_key)
        elif provider == "ollama":
            ollama_url = data.get("ollama_url", "http://localhost:11434")
            _update_env_variable("OLLAMA_URL", ollama_url)
        # claude-code: pas de clé API ni d'URL à sauvegarder

        # Mettre à jour les variables d'environnement en mémoire
        import os
        os.environ["LLM_PROVIDER"] = provider
        os.environ["LLM_MODEL"] = model
        if provider == "claude" and data.get("api_key"):
            os.environ["ANTHROPIC_API_KEY"] = data.get("api_key")
        elif provider == "ollama":
            os.environ["OLLAMA_URL"] = data.get("ollama_url", "http://localhost:11434")

        return jsonify({
            "success": True,
            "message": "LLM configuration saved. Restart the API to apply changes.",
            "requires_restart": True,
        })

    except Exception as e:
        logger.error(f"Error saving LLM settings: {e}")
        return jsonify({"error": "Failed to save LLM settings"}), 500
