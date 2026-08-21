# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Routes API pour le marketplace d'agents.

Endpoints:
- GET  /api/agent-marketplace/catalog             — Catalogue des agents disponibles
- GET  /api/agent-marketplace/installed           — Agents installés
- POST /api/agent-marketplace/<id>/subscribe      — Souscrire à un agent
- DELETE /api/agent-marketplace/<id>/unsubscribe  — Désinstaller un agent
- GET  /api/agent-marketplace/<id>/config         — Lire la config d'un agent
- PATCH /api/agent-marketplace/<id>/config        — Sauvegarder la config d'un agent
- GET  /api/agent-marketplace/faq/stats           — Stats FAQ Agent
- GET  /api/agent-marketplace/faq/history         — Historique FAQ Agent
"""

import json
import logging
import re
from pathlib import Path
from typing import Optional

from flask import Blueprint, g, jsonify, request

from app.api.settings import load_settings, save_settings, _get_current_account_id
from app.api.utils.errors import error_response

logger = logging.getLogger(__name__)

agent_marketplace_bp = Blueprint("agent_marketplace", __name__)

# Répertoire de stockage des configs agents
from app.config import DATA_DIR as _APP_DATA_DIR
_DATA_DIR = _APP_DATA_DIR / "agent_configs"

# AUTHZ-VULN-10 (Shannon pentest 2026-05-05, issue #557): pré-fix, les configs
# vivaient dans `_DATA_DIR / <agent_id>.json` — un namespace global. User A
# pouvait lire/écraser la config (incluant Stripe secret, custom API URL, …)
# de User B simplement en hitting PATCH /api/agent-marketplace/<id>/config.
# Désormais on namespace par user_id du JWT : `_DATA_DIR / u_<uid> / <id>.json`.
_LEGACY_CONFIG_DIR = _DATA_DIR
_AGENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _ensure_data_dir() -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)


def _current_user_id() -> Optional[int]:
    """Retourne l'id du user JWT (auth_user.id), ou None en mode loopback."""
    auth_user = getattr(g, "auth_user", None)
    if not auth_user:
        return None
    return auth_user.get("id")


def _user_config_dir(user_id: Optional[int]) -> Path:
    """Dossier de configs scopé par user.

    Si `user_id` est None (mode Tauri loopback / single-tenant), on retombe
    sur l'ancien répertoire global pour préserver le UX existant.
    """
    if user_id is None:
        return _DATA_DIR
    return _DATA_DIR / f"u_{int(user_id)}"


def _config_path(agent_id: str, user_id: Optional[int] = None) -> Path:
    # Hardening : refuse les agent_id non conformes pour éviter path traversal.
    if not isinstance(agent_id, str) or not _AGENT_ID_RE.match(agent_id):
        raise ValueError(f"agent_id invalide: {agent_id!r}")
    return _user_config_dir(user_id) / f"{agent_id}.json"


def _load_agent_config(agent_id: str, user_id: Optional[int] = None) -> dict:
    try:
        path = _config_path(agent_id, user_id)
    except ValueError:
        return {}
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    # Fallback compat : si pas encore de config user-scopée, lire l'ancienne
    # config globale (utilisée avant le fix #557). Read-only — la prochaine
    # PATCH écrira dans le scope user.
    if user_id is not None:
        legacy = _LEGACY_CONFIG_DIR / f"{agent_id}.json"
        if legacy.exists():
            try:
                return json.loads(legacy.read_text(encoding="utf-8"))
            except Exception:
                pass
    return {}


def _save_agent_config(agent_id: str, config: dict, user_id: Optional[int] = None) -> None:
    path = _config_path(agent_id, user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Catalogue ──────────────────────────────────────────────────────────────────

_CATALOG = [
    {
        "id": "faq",
        "name": "FAQ Agent",
        "description": "Responds autonomously to emails matching your FAQ knowledge base. Zero mental overhead — the loop closes itself.",
        "category": "Customer Service",
        "price_monthly": 15,
        "rating": 4.7,
        "rating_count": 64,
        "icon": "headphones",
        "config_fields": [
            {"key": "confidence_threshold", "type": "slider", "default": 80, "min": 50, "max": 95},
            {"key": "auto_send", "type": "toggle", "default": True},
            {"key": "test_mode", "type": "toggle", "default": False},
            {"key": "reply_tone", "type": "select", "options": ["professional", "friendly", "concise"]},
        ],
    },
    {
        "id": "account",
        "name": "Account Agent",
        "description": "Manage user accounts — password reset & email change. Supports WordPress, Shopify, and custom REST APIs.",
        "category": "Customer Service",
        "price_monthly": 29,
        "rating": 4.3,
        "rating_count": 42,
        "icon": "shield",
        "supported_providers": ["wordpress", "shopify", "custom"],
        "config_fields": [
            {"key": "provider", "label": "Provider", "type": "radio", "options": ["wordpress", "shopify", "custom"]},
            {"key": "brand_name", "label": "Brand / Site Name", "type": "text"},
            {"key": "providers.wordpress.site_url", "label": "WordPress Site URL", "type": "url"},
            {"key": "providers.wordpress.username", "label": "Admin Username", "type": "text"},
            {"key": "providers.wordpress.app_password", "label": "Application Password", "type": "password"},
            {"key": "providers.shopify.shop_domain", "label": "Shop Domain", "type": "text"},
            {"key": "providers.shopify.admin_api_token", "label": "Admin API Token", "type": "password"},
            {"key": "providers.custom.base_url", "label": "Base URL", "type": "url"},
            {"key": "providers.custom.auth_type", "label": "Auth Type", "type": "select", "options": ["none", "bearer", "basic", "api_key"]},
            {"key": "auto_approve", "label": "Auto-approve actions", "type": "boolean", "default": False},
            {"key": "notify_user_by_email", "label": "Notify user by email", "type": "boolean", "default": True},
        ],
    },
]


@agent_marketplace_bp.route("/catalog", methods=["GET"])
def get_catalog():
    """
    Retourne le catalogue des agents disponibles.
    ---
    tags:
      - AgentMarketplace
    responses:
      200:
        description: Liste des agents avec statut d'installation
    """
    # Per-account install state — never the process-global settings.json,
    # which would surface another tenant's installed agents (audit 2026-05-29).
    settings = load_settings(account_id=_get_current_account_id())
    installed = settings.get("installed_agents", [])

    result = []
    for agent in _CATALOG:
        result.append({**agent, "installed": agent["id"] in installed})

    return jsonify(result), 200


# ── Agents installés ───────────────────────────────────────────────────────────

@agent_marketplace_bp.route("/installed", methods=["GET"])
def get_installed():
    """
    Retourne les agents installés par l'utilisateur.
    ---
    tags:
      - AgentMarketplace
    responses:
      200:
        description: Liste des agents installés
    """
    settings = load_settings(account_id=_get_current_account_id())
    installed = settings.get("installed_agents", [])

    user_id = _current_user_id()
    catalog_map = {a["id"]: a for a in _CATALOG}
    result = []
    for agent_id in installed:
        if agent_id in catalog_map:
            config = _load_agent_config(agent_id, user_id=user_id)
            if agent_id == "faq":
                # FAQ Agent is configured if there are FAQ entries in the KB
                is_configured = True  # No secrets needed — uses KB entries
            elif agent_id == "account":
                provider = config.get("provider", "wordpress")
                providers_cfg = config.get("providers", {})
                p_cfg = providers_cfg.get(provider, {})
                if provider == "wordpress":
                    is_configured = bool(p_cfg.get("site_url") and p_cfg.get("app_password"))
                elif provider == "shopify":
                    is_configured = bool(p_cfg.get("shop_domain") and p_cfg.get("admin_api_token"))
                elif provider == "custom":
                    is_configured = bool(p_cfg.get("base_url"))
                else:
                    is_configured = False
                # Fallback: legacy flat format
                if not is_configured and "wordpress_site_url" in config:
                    is_configured = bool(config.get("wordpress_site_url") and config.get("wordpress_app_password"))
            else:
                is_configured = bool(config)
            result.append({
                **catalog_map[agent_id],
                "installed": True,
                "is_configured": is_configured,
                "config": config,
            })

    return jsonify(result), 200


# ── Souscription ───────────────────────────────────────────────────────────────

@agent_marketplace_bp.route("/<agent_id>/subscribe", methods=["POST"])
def subscribe(agent_id: str):
    """
    Installe un agent (mock paiement — pour MVP).
    ---
    tags:
      - AgentMarketplace
    parameters:
      - name: agent_id
        in: path
        type: string
        required: true
    responses:
      200:
        description: Agent installé
      404:
        description: Agent introuvable
    """
    catalog_ids = {a["id"] for a in _CATALOG}
    if agent_id not in catalog_ids:
        return jsonify({"error": f"Agent '{agent_id}' introuvable"}), 404

    account_id = _get_current_account_id()
    settings = load_settings(account_id=account_id)
    installed = settings.get("installed_agents", [])
    if agent_id not in installed:
        installed.append(agent_id)
        settings["installed_agents"] = installed
        save_settings(settings, account_id=account_id)

    logger.info("[AgentMarketplace] Agent souscrit : %s", agent_id)
    return jsonify({"ok": True, "agent_id": agent_id}), 200


@agent_marketplace_bp.route("/<agent_id>/unsubscribe", methods=["DELETE"])
def unsubscribe(agent_id: str):
    """
    Désinstalle un agent.
    ---
    tags:
      - AgentMarketplace
    parameters:
      - name: agent_id
        in: path
        type: string
        required: true
    responses:
      200:
        description: Agent désinstallé
    """
    account_id = _get_current_account_id()
    settings = load_settings(account_id=account_id)
    installed = settings.get("installed_agents", [])
    if agent_id in installed:
        installed.remove(agent_id)
        settings["installed_agents"] = installed
        save_settings(settings, account_id=account_id)

    logger.info("[AgentMarketplace] Agent désinstallé : %s", agent_id)
    return jsonify({"ok": True, "agent_id": agent_id}), 200


# ── Configuration ──────────────────────────────────────────────────────────────

@agent_marketplace_bp.route("/<agent_id>/config", methods=["GET"])
def get_config(agent_id: str):
    """
    Lit la configuration d'un agent (scopée user — AUTHZ-VULN-10).
    ---
    tags:
      - AgentMarketplace
    responses:
      200:
        description: Configuration de l'agent
    """
    config = _load_agent_config(agent_id, user_id=_current_user_id())
    # Masquer les cles secretes dans la reponse
    safe = dict(config)
    # Legacy flat format
    if safe.get("wordpress_app_password"):
        key = safe["wordpress_app_password"]
        safe["wordpress_app_password"] = key[:4] + "••••••••" if len(key) > 4 else "••••••••"
    # New nested provider secrets
    if "providers" in safe:
        providers = safe["providers"] = dict(safe["providers"])
        if "wordpress" in providers:
            wp = providers["wordpress"] = dict(providers["wordpress"])
            if wp.get("app_password") and "••" not in wp["app_password"]:
                key = wp["app_password"]
                wp["app_password"] = key[:4] + "••••••••" if len(key) > 4 else "••••••••"
        if "shopify" in providers:
            sh = providers["shopify"] = dict(providers["shopify"])
            if sh.get("admin_api_token") and "••" not in sh["admin_api_token"]:
                sh["admin_api_token"] = "••••••••"
        if "custom" in providers:
            cu = providers["custom"] = dict(providers["custom"])
            if cu.get("auth_credentials") and isinstance(cu["auth_credentials"], dict):
                creds = cu["auth_credentials"] = dict(cu["auth_credentials"])
                for k in ("token", "password", "key"):
                    if creds.get(k) and "••" not in creds[k]:
                        creds[k] = "••••••••"
    return jsonify(safe), 200


@agent_marketplace_bp.route("/<agent_id>/config", methods=["PATCH"])
def save_config(agent_id: str):
    """
    Sauvegarde la configuration d'un agent.

    AUTHZ-VULN-10 (Shannon pentest 2026-05-05, issue #557): pré-fix, pas de
    check ownership — User A pouvait écraser la config (incluant Stripe
    secret + custom API URL → SSRF stored) de User B. Désormais scoped par
    user_id via _config_path. URL custom API validée contre SSRF en prod.
    ---
    tags:
      - AgentMarketplace
    responses:
      200:
        description: Configuration sauvegardée
    """
    data = request.get_json(silent=True) or {}
    user_id = _current_user_id()

    # AUTHZ-VULN-10 (#557): valider la base URL custom API si présente. Une
    # config malicieuse pouvait pointer vers 169.254.169.254 ou un host
    # interne pour SSRF stored.
    if isinstance(data, dict):
        custom_provider = (data.get("providers") or {}).get("custom") or {}
        if isinstance(custom_provider, dict) and custom_provider.get("base_url"):
            from app.api._auth_helpers import is_production
            from app.utils.safe_outbound import SsrfBlocked, validate_outbound_url
            if is_production():
                try:
                    validate_outbound_url(custom_provider["base_url"])
                except SsrfBlocked as e:
                    return error_response(
                        "MARKETPLACE_BASE_URL_REJECTED",
                        f"base_url rejected: {e}",
                        400,
                        context={"detail": str(e)},
                        extra={"ok": False},
                    )

    def _deep_merge_skip_masked(target: dict, incoming: dict) -> dict:
        """Fusionne incoming dans target en ignorant toute valeur masquée (••)."""
        for key, value in incoming.items():
            if isinstance(value, str) and "••" in value:
                continue  # garder la valeur existante (non masquée)
            elif isinstance(value, dict) and isinstance(target.get(key), dict):
                _deep_merge_skip_masked(target[key], value)  # récursif pour nested dicts
            else:
                target[key] = value
        return target

    # Lire la config existante pour ne pas écraser les champs masqués
    try:
        existing = _load_agent_config(agent_id, user_id=user_id)
        _deep_merge_skip_masked(existing, data)
        _save_agent_config(agent_id, existing, user_id=user_id)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    logger.info("[AgentMarketplace] Config sauvegardée : %s (user=%s)", agent_id, user_id)
    return jsonify({"ok": True}), 200


# ── Tests de connexion ─────────────────────────────────────────────────────────

@agent_marketplace_bp.route("/account/test-connection", methods=["GET", "POST"])
def test_account_connection():
    """
    Teste la connexion du provider de compte actif.
    ---
    tags:
      - AgentMarketplace
    responses:
      200:
        description: Test reussi
      400:
        description: Test échoué
    """
    config = _load_agent_config("account", user_id=_current_user_id())
    # Accept live credentials from request body (not yet saved to disk)
    if request.method == "POST" and request.is_json:
        override = request.get_json(silent=True) or {}
        if override:
            config.update(override)
    try:
        from app.integrations.account_provider_factory import create_account_provider
        provider = create_account_provider(config)
        result = provider.test_connection()
        if result.success:
            return jsonify({"ok": True, "message": result.message, "provider": provider.provider_name, **(result.details or {})}), 200
        return jsonify({"ok": False, "error": result.message}), 400
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


# Legacy alias for backward compatibility
@agent_marketplace_bp.route("/account/test-wordpress", methods=["GET"])
def test_wordpress():
    """Legacy endpoint — redirects to test-connection."""
    return test_account_connection()


# ── FAQ Agent stats & history ────────────────────────────────────────────────

@agent_marketplace_bp.route("/faq/stats", methods=["GET"])
def faq_stats():
    """
    Retourne les métriques du FAQ Agent.
    ---
    tags:
      - AgentMarketplace
    responses:
      200:
        description: Stats du FAQ Agent (auto-sent, skipped, avg confidence, top entries)
    """
    days = request.args.get("days", 30, type=int)
    account_id = request.args.get("account_id", "")
    _empty_payload = {
        "auto_sent_count": 0,
        "skipped_count": 0,
        "avg_confidence": 0,
        "top_entries": [],
        "period_days": days,
    }

    # F-01 (audit issue #209, 2026-04-29): the ISO-05 fix only covered
    # the empty-string fallback. A supplied account_id from any JWT user
    # was passed straight to FaqLogRepository.get_stats(), leaking other
    # tenants' FAQ stats. Now: empty → resolve from JWT; supplied →
    # validate ownership via require_owned_account_id, sentinel = 404.
    from app.api.routes_helpers import (
        _resolve_account_id_for_user,
        require_owned_account_id,
        _NO_ACCOUNT_SENTINEL,
    )
    if not account_id:
        try:
            scoped = _resolve_account_id_for_user()
            if scoped and scoped != _NO_ACCOUNT_SENTINEL:
                account_id = scoped
        except Exception:
            pass
    else:
        owned = require_owned_account_id(account_id)
        if owned == _NO_ACCOUNT_SENTINEL:
            return jsonify({"error": "account not found"}), 404
        account_id = owned

    if not account_id:
        return jsonify(_empty_payload), 200

    try:
        from app.db.database import get_db_session
        from app.db.repositories.faq_log_repository import FaqLogRepository
        with get_db_session() as session:
            stats = FaqLogRepository(session).get_stats(account_id, days)
        return jsonify(stats), 200
    except Exception as exc:
        logger.error("[FaqAgent] Stats error: %s", exc)
        return jsonify(_empty_payload), 200


@agent_marketplace_bp.route("/faq/history", methods=["GET"])
def faq_history():
    """
    Retourne l'historique récent des actions du FAQ Agent.
    ---
    tags:
      - AgentMarketplace
    responses:
      200:
        description: Historique des 20 dernières actions
    """
    limit = request.args.get("limit", 20, type=int)
    account_id = request.args.get("account_id", "")

    # F-01 (audit issue #209, 2026-04-29): same fix as faq_stats — empty
    # → resolve from JWT; supplied → validate ownership.
    from app.api.routes_helpers import (
        _resolve_account_id_for_user,
        require_owned_account_id,
        _NO_ACCOUNT_SENTINEL,
    )
    if not account_id:
        try:
            scoped = _resolve_account_id_for_user()
            if scoped and scoped != _NO_ACCOUNT_SENTINEL:
                account_id = scoped
        except Exception:
            pass
    else:
        owned = require_owned_account_id(account_id)
        if owned == _NO_ACCOUNT_SENTINEL:
            return jsonify({"error": "account not found"}), 404
        account_id = owned

    if not account_id:
        return jsonify([]), 200

    try:
        from app.db.database import get_db_session
        from app.db.repositories.faq_log_repository import FaqLogRepository
        with get_db_session() as session:
            logs = FaqLogRepository(session).get_history(account_id, limit)
            return jsonify([log.to_dict() for log in logs]), 200
    except Exception as exc:
        logger.error("[FaqAgent] History error: %s", exc)
        return jsonify([]), 200
