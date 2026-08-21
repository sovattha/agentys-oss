# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Routes API REST pour la Marketplace d'agents IA.

Endpoints disponibles:
- Publishers
  - POST /api/marketplace/publishers - Enregistrer un éditeur
  - GET /api/marketplace/publishers/<id> - Détails d'un éditeur

- Agents
  - GET /api/marketplace/agents - Rechercher/lister des agents
  - GET /api/marketplace/agents/<id> - Détails d'un agent
  - POST /api/marketplace/agents - Publier un agent (éditeur)
  - PATCH /api/marketplace/agents/<id> - Mettre à jour un agent
  - POST /api/marketplace/agents/<id>/submit - Soumettre pour review
  - POST /api/marketplace/agents/<id>/approve - Approuver (admin)

- Installations
  - GET /api/marketplace/installations - Mes installations
  - POST /api/marketplace/agents/<id>/install - Installer un agent
  - DELETE /api/marketplace/installations/<id> - Désinstaller
  - POST /api/marketplace/installations/<id>/usage - Enregistrer usage

- Reviews
  - GET /api/marketplace/agents/<id>/reviews - Avis d'un agent
  - POST /api/marketplace/agents/<id>/reviews - Soumettre un avis
  - POST /api/marketplace/reviews/<id>/respond - Répondre (éditeur)

- Packs
  - GET /api/marketplace/packs - Lister les packs
  - POST /api/marketplace/packs - Créer un pack (éditeur)
  - POST /api/marketplace/packs/<id>/install - Installer un pack
"""

import logging
import re
import unicodedata
from functools import wraps
from typing import Callable, Optional, Tuple

from flask import Blueprint, request, jsonify, g

from app.domain.entities.marketplace import (
    AgentCategory,
    AgentPricingModel,
    AgentPricing,
    MarketplaceSearchQuery,
)
from app.api.admin import require_admin
from app.api.utils.errors import error_response
from app.infrastructure.marketplace_store import (
    get_marketplace_stores,
)
from app.application.marketplace import (
    # Publisher
    RegisterPublisherUseCase,
    GetPublisherUseCase,
    # Agent Publication
    PublishAgentUseCase,
    SubmitAgentForReviewUseCase,
    ApproveAgentUseCase,
    UpdateAgentUseCase,
    # Search
    SearchAgentsUseCase,
    GetAgentDetailsUseCase,
    ListFeaturedAgentsUseCase,
    ListAgentsByCategoryUseCase,
    # Installation
    InstallAgentUseCase,
    UninstallAgentUseCase,
    ListInstalledAgentsUseCase,
    RecordAgentUsageUseCase,
    # Reviews
    SubmitReviewUseCase,
    RespondToReviewUseCase,
    ListAgentReviewsUseCase,
    # Packs
    CreateAgentPackUseCase,
    InstallPackUseCase,
)

logger = logging.getLogger(__name__)

marketplace_bp = Blueprint("marketplace", __name__)


# F-07 (regression audit, 2026-04-29): regex tolerant of attributes,
# whitespace, NBSP-collapsed-to-space, and case. ``<\s*/\s*`` deliberately
# allows whitespace between the angle bracket and slash — NFKC turns NBSP
# into a regular space, so an attacker who inserts NBSP between ``<`` and
# ``/`` would otherwise survive the strip-step. Compiled once at module load.
_BAD_TAG_RE = re.compile(
    r"<\s*/\s*(?:publisher(?:_content)?|system)\b[^>]*>",
    re.IGNORECASE,
)
# Stripped before lowercasing: NBSP, zero-width spaces, BOM, etc.
_INVISIBLE_CHARS_RE = re.compile(r"[ ​-‏ ⁠﻿]")


def _sanitize_system_prompt(raw: str) -> tuple[str | None, str | None]:
    """Validate + wrap a publisher-supplied system_prompt.

    F-02 + F-08 + F-10 (regression audit, 2026-04-29): unified the
    sanitizer originally inlined in `publish_agent` so `update_agent`
    (PATCH) can apply the same checks. Without this, a publisher could
    POST a clean prompt and PATCH a malicious one.

    F-07 (regression audit, 2026-04-29): the prior F-08 fix used exact
    substring containment on `.lower()`. Bypasses found in audit:
      - attribute-bearing close tag: ``</publisher_content x>``
      - whitespace-padded close tag: ``</   publisher_content   >``
      - NBSP between ``<`` and ``/`` (unicode normalisation hole)
    Now: NFKC-normalise + strip invisible chars + regex on tag patterns.

    Returns (safe_prompt, None) on success, (None, error_message) on
    rejection. Caller wraps the error_message in a 400 response.
    """
    raw_prompt = raw or ""
    if len(raw_prompt) > 4000:
        return None, "system_prompt too long (max 4000 chars)"

    # NFKC fold-equivalent unicode (e.g. fullwidth `<`) + strip invisible
    # spaces/zero-width chars before the close-tag regex sees the text.
    normalized = unicodedata.normalize("NFKC", raw_prompt)
    normalized = _INVISIBLE_CHARS_RE.sub("", normalized)
    lowered = normalized.lower()

    # Plain-text injection markers — substring is enough.
    _BAD_TEXT_PATTERNS = (
        "ignore previous", "ignore all previous", "disregard previous",
        "system:", "<|im_start|>", "<|im_end|>",
    )
    for pattern in _BAD_TEXT_PATTERNS:
        if pattern in lowered:
            return None, f"system_prompt contains forbidden pattern: {pattern}"

    # Structural envelope close-tags — regex tolerant of attrs/whitespace.
    if _BAD_TAG_RE.search(lowered):
        return None, "system_prompt contains forbidden envelope close tag"

    return f"<publisher_content>\n{raw_prompt}\n</publisher_content>", None


# ============================================================================
# AUTH HELPERS — F-01 / F-03 (regression audit, 2026-04-29)
# ============================================================================

def _caller_email() -> Optional[str]:
    """Return the JWT caller's email (lowercased), or None for loopback.

    `apply_auth_guard` (app.py:471) sets `g.auth_user` to a dict with
    `id` + `email` for JWT-authenticated requests, or to `None` for
    loopback callers (Tauri desktop). Any other case returns None.
    """
    auth_user = getattr(g, "auth_user", None)
    if not auth_user:
        return None
    email = auth_user.get("email") or ""
    return email.lower() or None


def _resolve_caller_publisher_id(
    stores: dict, body_publisher_id: Optional[str]
) -> Tuple[Optional[str], Optional[Tuple]]:
    """Derive publisher_id from JWT (canonical) or fall back to body (loopback).

    F-01 (regression audit, 2026-04-29): every PATCH/submit/respond/pack
    handler accepted body-supplied `publisher_id` and only verified
    ownership via ``agent.publisher_id == body_publisher_id``. But the
    Publisher entity has no caller binding — any authenticated user could
    rewrite any other publisher's agent prompt by replaying the public
    publisher_id from ``GET /api/marketplace/agents``.

    Resolution rules:
      * JWT present → look up Publisher by JWT email. That is the canonical
        publisher_id. If body supplies a different one, 403.
      * JWT absent (loopback / Tauri desktop) → trust body (legacy path).

    Returns ``(publisher_id, None)`` on success or
    ``(None, (response, status))`` on rejection. Caller must propagate the
    error tuple immediately (``return *err``).
    """
    caller_email = _caller_email()
    if caller_email:
        publisher = stores["publisher_store"].get_by_email(caller_email)
        if not publisher:
            return None, (
                jsonify({
                    "error": "no publisher registered for caller email",
                    "hint": "POST /api/marketplace/publishers first",
                }),
                403,
            )
        if body_publisher_id and body_publisher_id != publisher.id:
            logger.warning(
                "[F-01] publisher_id mismatch: body=%s jwt_derived=%s email=%s",
                body_publisher_id, publisher.id, caller_email,
            )
            return None, (
                jsonify({
                    "error": "publisher_id does not match authenticated caller",
                }),
                403,
            )
        return publisher.id, None

    # Loopback (Tauri desktop) — legacy: trust body.
    if not body_publisher_id:
        return None, (jsonify({"error": "publisher_id is required"}), 400)
    return body_publisher_id, None


def _resolve_caller_org_id(
    body_org_id: Optional[str],
) -> Tuple[Optional[str], Optional[Tuple]]:
    """Derive organization_id from JWT (canonical) or fall back to body.

    F-03 (regression audit, 2026-04-29): install/uninstall/list/usage/
    review/install_pack accepted body- or query-supplied `organization_id`
    with no caller binding. Any authenticated user could enumerate, install
    or uninstall on behalf of any other organization — distorts billing,
    review counts, and lets an attacker DoS legit orgs.

    Canonical org id for an authenticated caller = the JWT email
    (lowercased). It is stable across logins and binds installations to a
    single identity. Loopback callers fall back to the body for legacy
    Tauri desktop workflows.
    """
    caller_email = _caller_email()
    if caller_email:
        canonical = caller_email
        if body_org_id and body_org_id != canonical:
            logger.warning(
                "[F-03] organization_id mismatch: body=%s jwt_derived=%s",
                body_org_id, canonical,
            )
            return None, (
                jsonify({
                    "error": "organization_id does not match authenticated caller",
                }),
                403,
            )
        return canonical, None

    # Loopback — legacy: trust body.
    if not body_org_id:
        return None, (jsonify({"error": "organization_id is required"}), 400)
    return body_org_id, None


# ============================================================================
# HELPERS
# ============================================================================

def require_json(f: Callable) -> Callable:
    """Décorateur pour valider la présence d'un body JSON objet.

    silent=True + isinstance(dict) so a missing/non-JSON/array body returns a
    clean 400 instead of letting werkzeug raise or blowing up on a later
    `data.get(...)` (audit 2026-05-19 STAB-02)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or not body:
            return jsonify({"error": "JSON body required"}), 400
        return f(*args, **kwargs)
    return decorated


def get_stores():
    """Retourne les stores de la marketplace."""
    return get_marketplace_stores()


def serialize_agent(agent) -> dict:
    """Sérialise un agent pour la réponse JSON."""
    return {
        "id": agent.id,
        "name": agent.name,
        "slug": agent.slug,
        "description": agent.description,
        "long_description": agent.long_description,
        "version": agent.version,
        "category": agent.category.value,
        "tags": agent.tags,
        "status": agent.status.value,
        "pricing": {
            "model": agent.pricing.model.value,
            "price_cents": agent.pricing.price_cents,
            "currency": agent.pricing.currency,
            "trial_days": agent.pricing.trial_days,
        },
        "download_count": agent.download_count,
        "active_installations": agent.active_installations,
        "average_rating": agent.average_rating,
        "review_count": agent.review_count,
        "publisher_id": agent.publisher_id,
        "created_at": agent.created_at.isoformat() if agent.created_at else None,
        "published_at": agent.published_at.isoformat() if agent.published_at else None,
    }


def serialize_review(review) -> dict:
    """Sérialise un avis pour la réponse JSON."""
    return {
        "id": review.id,
        "agent_id": review.agent_id,
        "reviewer_name": review.reviewer_name,
        "rating": review.rating,
        "title": review.title,
        "content": review.content,
        "is_verified_purchase": review.is_verified_purchase,
        "publisher_response": review.publisher_response,
        "publisher_response_at": review.publisher_response_at.isoformat() if review.publisher_response_at else None,
        "created_at": review.created_at.isoformat() if review.created_at else None,
    }


def serialize_installation(installation, agent=None) -> dict:
    """Sérialise une installation pour la réponse JSON."""
    result = {
        "id": installation.id,
        "agent_id": installation.agent_id,
        "organization_id": installation.organization_id,
        "status": installation.status.value,
        "installed_version": installation.installed_version,
        "usage_count": installation.usage_count,
        "installed_at": installation.installed_at.isoformat() if installation.installed_at else None,
        "last_used_at": installation.last_used_at.isoformat() if installation.last_used_at else None,
        "expires_at": installation.expires_at.isoformat() if installation.expires_at else None,
    }
    if agent:
        result["agent"] = serialize_agent(agent)
    return result


# ============================================================================
# PUBLISHERS
# ============================================================================

@marketplace_bp.route("/publishers", methods=["POST"])
@require_json
def register_publisher():
    """
    Enregistre un nouvel éditeur sur la marketplace.

    F-01 (regression audit, 2026-04-29): when a JWT is present, the
    publisher email is forced to match the caller's identity. This
    prevents anyone from registering a publisher under someone else's
    email — which (combined with the JWT-derived ownership check below)
    is the binding that gates rewrite of marketplace agents.

    Body JSON:
        name: str (requis)
        email: str (requis pour loopback; ignoré + écrasé par JWT si présent)
        description: str (optional)
        website: str (optional)
    """
    data = request.get_json()
    stores = get_stores()

    # F-01: bind publisher email to JWT identity when authenticated.
    caller_email = _caller_email()
    body_email = (data.get("email") or "").strip().lower()
    if caller_email:
        if body_email and body_email != caller_email:
            logger.warning(
                "[F-01] publisher email mismatch: body=%s jwt=%s",
                body_email, caller_email,
            )
            return jsonify({
                "error": "publisher email does not match authenticated caller",
            }), 403
        effective_email = caller_email
    else:
        effective_email = body_email

    try:
        use_case = RegisterPublisherUseCase(publisher_port=stores["publisher_store"])
        publisher = use_case.execute(
            name=data.get("name", ""),
            email=effective_email,
            description=data.get("description", ""),
            website=data.get("website", ""),
        )

        return jsonify({
            "success": True,
            "publisher": {
                "id": publisher.id,
                "name": publisher.name,
                "email": publisher.email,
                "verified": publisher.verified,
            }
        }), 201

    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@marketplace_bp.route("/publishers/<publisher_id>", methods=["GET"])
def get_publisher(publisher_id: str):
    """Récupère les détails d'un éditeur."""
    stores = get_stores()

    use_case = GetPublisherUseCase(publisher_port=stores["publisher_store"])
    publisher = use_case.execute(publisher_id)

    if not publisher:
        return jsonify({"error": "Publisher not found"}), 404

    return jsonify({
        "id": publisher.id,
        "name": publisher.name,
        "description": publisher.description,
        "website": publisher.website,
        "verified": publisher.verified,
        "agent_count": publisher.agent_count,
        "total_downloads": publisher.total_downloads,
        "average_rating": publisher.average_rating,
    })


# ============================================================================
# AGENTS - SEARCH & LIST
# ============================================================================

@marketplace_bp.route("/agents", methods=["GET"])
def search_agents():
    """
    Recherche et liste les agents de la marketplace.

    Query params:
        q: str - Recherche textuelle
        category: str - Filtrer par catégorie
        pricing: str - Filtrer par modèle de tarification (free, subscription, etc.)
        min_rating: float - Note minimale
        sort: str - Tri (popularity, rating, newest, price)
        page: int - Page (défaut: 1)
        per_page: int - Résultats par page (défaut: 20)

    Returns:
        Liste paginée des agents.
    """
    stores = get_stores()

    # Construire la requête de recherche
    category = None
    if request.args.get("category"):
        try:
            category = AgentCategory(request.args.get("category"))
        except ValueError:
            pass

    pricing_models = []
    if request.args.get("pricing"):
        try:
            pricing_models = [AgentPricingModel(request.args.get("pricing"))]
        except ValueError:
            pass

    query = MarketplaceSearchQuery(
        query=request.args.get("q", ""),
        category=category,
        pricing_models=pricing_models,
        min_rating=float(request.args.get("min_rating", 0)),
        sort_by=request.args.get("sort", "popularity"),
        page=int(request.args.get("page", 1)),
        per_page=int(request.args.get("per_page", 20)),
    )

    use_case = SearchAgentsUseCase(agent_port=stores["agent_store"])
    result = use_case.execute(query)

    return jsonify({
        "agents": [serialize_agent(a) for a in result.agents],
        "total_count": result.total_count,
        "page": result.page,
        "per_page": result.per_page,
        "total_pages": result.total_pages,
    })


@marketplace_bp.route("/agents/featured", methods=["GET"])
def list_featured_agents():
    """Liste les agents mis en avant."""
    stores = get_stores()
    limit = int(request.args.get("limit", 10))

    use_case = ListFeaturedAgentsUseCase(agent_port=stores["agent_store"])
    agents = use_case.execute(limit=limit)

    return jsonify({
        "count": len(agents),
        "agents": [serialize_agent(a) for a in agents],
    })


@marketplace_bp.route("/agents/categories/<category>", methods=["GET"])
def list_agents_by_category(category: str):
    """Liste les agents d'une catégorie."""
    stores = get_stores()

    try:
        cat = AgentCategory(category)
    except ValueError:
        return jsonify({"error": f"Invalid category: {category}"}), 400

    limit = int(request.args.get("limit", 20))
    offset = int(request.args.get("offset", 0))

    use_case = ListAgentsByCategoryUseCase(agent_port=stores["agent_store"])
    agents = use_case.execute(category=cat, limit=limit, offset=offset)

    return jsonify({
        "category": category,
        "count": len(agents),
        "agents": [serialize_agent(a) for a in agents],
    })


@marketplace_bp.route("/agents/<agent_id>", methods=["GET"])
def get_agent_details(agent_id: str):
    """Récupère les détails complets d'un agent."""
    stores = get_stores()

    use_case = GetAgentDetailsUseCase(
        agent_port=stores["agent_store"],
        review_port=stores["review_store"],
        installation_port=stores["installation_store"],
    )
    result = use_case.execute(agent_id)

    if not result:
        return jsonify({"error": "Agent not found"}), 404

    agent = result["agent"]
    return jsonify({
        "agent": serialize_agent(agent),
        "system_prompt": agent.system_prompt,
        "capabilities": [
            {"name": c.name, "description": c.description, "keywords": c.keywords}
            for c in agent.capabilities
        ],
        "reviews": [serialize_review(r) for r in result["reviews"]],
        "active_installations": result["active_installations"],
        "average_rating": result["average_rating"],
        "review_count": result["review_count"],
    })


# ============================================================================
# AGENTS - PUBLICATION
# ============================================================================

@marketplace_bp.route("/agents", methods=["POST"])
@require_json
def publish_agent():
    """
    Publie un nouvel agent sur la marketplace.

    Body JSON:
        publisher_id: str (requis)
        name: str (requis)
        description: str (requis)
        category: str (requis)
        system_prompt: str (requis)
        capabilities: list[{name, description, keywords}] (optional)
        tags: list[str] (optional)
        pricing: {model, price_cents, currency, trial_days} (optional)

    Returns:
        L'agent créé (en statut DRAFT).
    """
    data = request.get_json()
    stores = get_stores()

    # Valider la catégorie
    try:
        category = AgentCategory(data.get("category", "custom"))
    except ValueError:
        return jsonify({"error": "Invalid category"}), 400

    # F-10 (audit issue #209, 2026-04-29) + F-02/F-08/F-07 (regression
    # audit): defense-in-depth on the publisher-supplied system_prompt.
    safe_system_prompt, error = _sanitize_system_prompt(data.get("system_prompt", ""))
    if error:
        return jsonify({"error": error}), 400

    # F-01 (regression audit, 2026-04-29): publisher_id derived from JWT
    # caller; body_publisher_id only honored on loopback.
    publisher_id, err = _resolve_caller_publisher_id(stores, data.get("publisher_id"))
    if err:
        return err

    # Construire le pricing
    pricing = None
    if data.get("pricing"):
        pricing_data = data["pricing"]
        try:
            pricing = AgentPricing(
                model=AgentPricingModel(pricing_data.get("model", "free")),
                price_cents=pricing_data.get("price_cents", 0),
                currency=pricing_data.get("currency", "EUR"),
                trial_days=pricing_data.get("trial_days", 0),
            )
        except ValueError as e:
            return jsonify({"error": f"Invalid pricing: {e}"}), 400

    try:
        use_case = PublishAgentUseCase(
            agent_port=stores["agent_store"],
            publisher_port=stores["publisher_store"],
        )
        agent = use_case.execute(
            publisher_id=publisher_id,
            name=data.get("name", ""),
            description=data.get("description", ""),
            category=category,
            system_prompt=safe_system_prompt,
            capabilities=data.get("capabilities", []),
            pricing=pricing,
            tags=data.get("tags", []),
            long_description=data.get("long_description", ""),
            knowledge_base_template=data.get("knowledge_base_template", ""),
        )

        return jsonify({
            "success": True,
            "agent": serialize_agent(agent),
            "message": "Agent created in DRAFT status. Submit for review to publish.",
        }), 201

    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@marketplace_bp.route("/agents/<agent_id>", methods=["PATCH"])
@require_json
def update_agent(agent_id: str):
    """Met à jour un agent existant.

    F-02 (regression audit, 2026-04-29): the original F-10 fix was
    inlined in `publish_agent` only. This PATCH path forwarded raw
    `system_prompt` straight into `UpdateAgentUseCase.execute` which
    `setattr`'s it onto the agent record (application/marketplace.py:
    329) — defeating F-10 via a publisher's first PATCH after publish.
    Now run the same `_sanitize_system_prompt` helper before the use
    case sees the field.

    F-01 (regression audit, 2026-04-29): the prior implementation
    accepted body-supplied `publisher_id` and only checked
    ``agent.publisher_id == body_publisher_id`` — but `publisher_id` is
    publicly exposed via ``GET /api/marketplace/agents``, so anyone
    authenticated could rewrite any publisher's prompt. Now derive
    publisher_id from the JWT identity (loopback fallback preserved).
    """
    data = request.get_json()
    stores = get_stores()

    # F-01 (regression audit, 2026-04-29): publisher_id derived from JWT.
    publisher_id, err = _resolve_caller_publisher_id(stores, data.get("publisher_id"))
    if err:
        return err

    # F-02: re-apply F-10's checks if system_prompt is being updated.
    update_kwargs = {k: v for k, v in data.items() if k != "publisher_id"}
    if "system_prompt" in update_kwargs:
        safe_prompt, error = _sanitize_system_prompt(update_kwargs["system_prompt"])
        if error:
            return jsonify({"error": error}), 400
        update_kwargs["system_prompt"] = safe_prompt

    try:
        use_case = UpdateAgentUseCase(agent_port=stores["agent_store"])
        agent = use_case.execute(
            agent_id=agent_id,
            publisher_id=publisher_id,
            **update_kwargs,
        )

        return jsonify({
            "success": True,
            "agent": serialize_agent(agent),
        })

    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@marketplace_bp.route("/agents/<agent_id>/submit", methods=["POST"])
@require_json
def submit_for_review(agent_id: str):
    """Soumet un agent pour review avant publication.

    F-01 (regression audit, 2026-04-29): publisher_id derived from JWT.
    """
    data = request.get_json()
    stores = get_stores()

    publisher_id, err = _resolve_caller_publisher_id(stores, data.get("publisher_id"))
    if err:
        return err

    try:
        use_case = SubmitAgentForReviewUseCase(agent_port=stores["agent_store"])
        agent = use_case.execute(agent_id=agent_id, publisher_id=publisher_id)

        return jsonify({
            "success": True,
            "agent": serialize_agent(agent),
            "message": "Agent submitted for review.",
        })

    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@marketplace_bp.route("/agents/<agent_id>/approve", methods=["POST"])
@require_admin
def approve_agent(agent_id: str):
    """Approuve et publie un agent (admin only).

    F-02 (audit issue #209, 2026-04-29): docstring claimed "admin only"
    but no admin gate existed. Added @require_admin.
    """
    stores = get_stores()

    try:
        use_case = ApproveAgentUseCase(agent_port=stores["agent_store"])
        agent = use_case.execute(agent_id=agent_id)

        return jsonify({
            "success": True,
            "agent": serialize_agent(agent),
            "message": "Agent approved and published.",
        })

    except ValueError as e:
        return jsonify({"error": str(e)}), 400


# ============================================================================
# INSTALLATIONS
# ============================================================================

@marketplace_bp.route("/installations", methods=["GET"])
def list_installations():
    """
    Liste les agents installés par une organisation.

    F-03 (regression audit, 2026-04-29): organization_id derived from JWT.

    Query params:
        organization_id: str (requis pour loopback; ignoré + écrasé par JWT si présent)
        active_only: bool (défaut: true)
    """
    organization_id, err = _resolve_caller_org_id(request.args.get("organization_id"))
    if err:
        return err

    active_only = request.args.get("active_only", "true").lower() == "true"

    stores = get_stores()
    use_case = ListInstalledAgentsUseCase(
        installation_port=stores["installation_store"],
        agent_port=stores["agent_store"],
    )
    installations = use_case.execute(organization_id, active_only=active_only)

    return jsonify({
        "count": len(installations),
        "installations": [
            serialize_installation(i["installation"], i["agent"])
            for i in installations
        ],
    })


@marketplace_bp.route("/agents/<agent_id>/install", methods=["POST"])
@require_json
def install_agent(agent_id: str):
    """
    Installe un agent pour une organisation.

    F-03 (regression audit, 2026-04-29): organization_id derived from JWT.

    Body JSON:
        organization_id: str (requis pour loopback; ignoré + écrasé par JWT si présent)
        custom_settings: dict (optional)
    """
    data = request.get_json()
    stores = get_stores()

    organization_id, err = _resolve_caller_org_id(data.get("organization_id"))
    if err:
        return err

    try:
        use_case = InstallAgentUseCase(
            agent_port=stores["agent_store"],
            installation_port=stores["installation_store"],
        )
        installation = use_case.execute(
            agent_id=agent_id,
            organization_id=organization_id,
            custom_settings=data.get("custom_settings"),
        )

        return jsonify({
            "success": True,
            "installation": serialize_installation(installation),
            "message": "Agent installed successfully.",
        }), 201

    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@marketplace_bp.route("/installations/<installation_id>", methods=["DELETE"])
def uninstall_agent(installation_id: str):
    """Désinstalle un agent.

    F-03 (regression audit, 2026-04-29): organization_id derived from JWT.
    """
    organization_id, err = _resolve_caller_org_id(request.args.get("organization_id"))
    if err:
        return err

    stores = get_stores()

    try:
        use_case = UninstallAgentUseCase(
            agent_port=stores["agent_store"],
            installation_port=stores["installation_store"],
        )
        use_case.execute(installation_id=installation_id, organization_id=organization_id)

        return jsonify({
            "success": True,
            "message": "Agent uninstalled successfully.",
        })

    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@marketplace_bp.route("/installations/<installation_id>/usage", methods=["POST"])
def record_usage(installation_id: str):
    """Enregistre une utilisation d'un agent installé.

    F-03 (regression audit, 2026-04-29): the prior handler had no
    organization_id check at all — any authenticated user could inflate
    usage counters on any installation. Now the JWT-derived org id must
    match ``installation.organization_id``. Loopback is exempt for the
    Tauri desktop legacy use case.
    """
    stores = get_stores()

    # Pre-fetch the installation so we can scope-check before incrementing.
    installation = stores["installation_store"].get_by_id(installation_id)
    if not installation:
        return error_response(
            "MARKETPLACE_INSTALLATION_NOT_FOUND",
            f"Installation {installation_id} not found",
            400,
            context={"installation_id": installation_id},
        )

    caller_email = _caller_email()
    if caller_email and installation.organization_id != caller_email:
        logger.warning(
            "[F-03] record_usage cross-tenant: installation.org=%s caller=%s",
            installation.organization_id, caller_email,
        )
        return jsonify({"error": "Cette installation ne vous appartient pas"}), 403

    try:
        use_case = RecordAgentUsageUseCase(installation_port=stores["installation_store"])
        installation = use_case.execute(installation_id)

        return jsonify({
            "success": True,
            "usage_count": installation.usage_count,
        })

    except ValueError as e:
        return jsonify({"error": str(e)}), 400


# ============================================================================
# REVIEWS
# ============================================================================

@marketplace_bp.route("/agents/<agent_id>/reviews", methods=["GET"])
def list_reviews(agent_id: str):
    """Liste les avis d'un agent."""
    stores = get_stores()
    limit = int(request.args.get("limit", 50))
    offset = int(request.args.get("offset", 0))

    use_case = ListAgentReviewsUseCase(review_port=stores["review_store"])
    reviews = use_case.execute(agent_id, limit=limit, offset=offset)

    return jsonify({
        "agent_id": agent_id,
        "count": len(reviews),
        "reviews": [serialize_review(r) for r in reviews],
    })


@marketplace_bp.route("/agents/<agent_id>/reviews", methods=["POST"])
@require_json
def submit_review(agent_id: str):
    """
    Soumet un avis sur un agent.

    F-03 (regression audit, 2026-04-29): organization_id derived from JWT.

    Body JSON:
        organization_id: str (requis pour loopback; ignoré + écrasé par JWT si présent)
        reviewer_name: str (requis)
        rating: int (1-5, requis)
        title: str (requis)
        content: str (requis)
    """
    data = request.get_json()
    stores = get_stores()

    organization_id, err = _resolve_caller_org_id(data.get("organization_id"))
    if err:
        return err

    try:
        use_case = SubmitReviewUseCase(
            review_port=stores["review_store"],
            installation_port=stores["installation_store"],
            agent_port=stores["agent_store"],
        )
        review = use_case.execute(
            agent_id=agent_id,
            organization_id=organization_id,
            reviewer_name=data.get("reviewer_name", ""),
            rating=int(data.get("rating", 0)),
            title=data.get("title", ""),
            content=data.get("content", ""),
        )

        return jsonify({
            "success": True,
            "review": serialize_review(review),
        }), 201

    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@marketplace_bp.route("/reviews/<review_id>/respond", methods=["POST"])
@require_json
def respond_to_review(review_id: str):
    """
    Permet à l'éditeur de répondre à un avis.

    F-01 (regression audit, 2026-04-29): publisher_id derived from JWT.

    Body JSON:
        publisher_id: str (requis pour loopback; ignoré + écrasé par JWT si présent)
        response: str (requis)
    """
    data = request.get_json()
    stores = get_stores()

    publisher_id, err = _resolve_caller_publisher_id(stores, data.get("publisher_id"))
    if err:
        return err

    try:
        use_case = RespondToReviewUseCase(
            review_port=stores["review_store"],
            agent_port=stores["agent_store"],
        )
        review = use_case.execute(
            review_id=review_id,
            publisher_id=publisher_id,
            response=data.get("response", ""),
        )

        return jsonify({
            "success": True,
            "review": serialize_review(review),
        })

    except ValueError as e:
        return jsonify({"error": str(e)}), 400


# ============================================================================
# PACKS
# ============================================================================

@marketplace_bp.route("/packs", methods=["GET"])
def list_packs():
    """Liste tous les packs disponibles."""
    stores = get_stores()
    packs = stores["pack_store"].list_all()

    return jsonify({
        "count": len(packs),
        "packs": [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "agent_count": len(p.agent_ids),
                "status": p.status.value,
                "discount_percent": p.discount_percent,
            }
            for p in packs
        ],
    })


@marketplace_bp.route("/packs", methods=["POST"])
@require_json
def create_pack():
    """
    Crée un pack d'agents.

    F-01 (regression audit, 2026-04-29): publisher_id derived from JWT.

    Body JSON:
        publisher_id: str (requis pour loopback; ignoré + écrasé par JWT si présent)
        name: str (requis)
        description: str (requis)
        agent_ids: list[str] (requis, min 2)
        discount_percent: int (optional)
    """
    data = request.get_json()
    stores = get_stores()

    publisher_id, err = _resolve_caller_publisher_id(stores, data.get("publisher_id"))
    if err:
        return err

    try:
        use_case = CreateAgentPackUseCase(
            pack_port=stores["pack_store"],
            agent_port=stores["agent_store"],
            publisher_port=stores["publisher_store"],
        )
        pack = use_case.execute(
            publisher_id=publisher_id,
            name=data.get("name", ""),
            description=data.get("description", ""),
            agent_ids=data.get("agent_ids", []),
            discount_percent=data.get("discount_percent", 0),
        )

        return jsonify({
            "success": True,
            "pack": {
                "id": pack.id,
                "name": pack.name,
                "agent_count": len(pack.agent_ids),
            },
        }), 201

    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@marketplace_bp.route("/packs/<pack_id>/install", methods=["POST"])
@require_json
def install_pack(pack_id: str):
    """
    Installe tous les agents d'un pack.

    F-03 (regression audit, 2026-04-29): organization_id derived from JWT.

    Body JSON:
        organization_id: str (requis pour loopback; ignoré + écrasé par JWT si présent)
    """
    data = request.get_json()
    stores = get_stores()

    organization_id, err = _resolve_caller_org_id(data.get("organization_id"))
    if err:
        return err

    try:
        install_agent_uc = InstallAgentUseCase(
            agent_port=stores["agent_store"],
            installation_port=stores["installation_store"],
        )
        use_case = InstallPackUseCase(
            pack_port=stores["pack_store"],
            install_agent_use_case=install_agent_uc,
        )
        installations = use_case.execute(pack_id=pack_id, organization_id=organization_id)

        return jsonify({
            "success": True,
            "installed_count": len(installations),
            "installations": [serialize_installation(i) for i in installations],
        }), 201

    except ValueError as e:
        return jsonify({"error": str(e)}), 400


# ============================================================================
# CATEGORIES
# ============================================================================

@marketplace_bp.route("/categories", methods=["GET"])
def list_categories():
    """Liste toutes les catégories disponibles."""
    categories = [
        {"id": c.value, "name": c.name.replace("_", " ").title()}
        for c in AgentCategory
    ]

    return jsonify({
        "count": len(categories),
        "categories": categories,
    })
