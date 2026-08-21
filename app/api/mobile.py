# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Routes API pour l'app mobile companion.

Endpoints disponibles:
- POST /api/mobile/session/start - Démarrer une session
- POST /api/mobile/session/end - Terminer une session
- POST /api/mobile/session/touch - Maintenir la session active

- POST /api/mobile/sync - Synchroniser les brouillons
- GET /api/mobile/drafts - Liste des brouillons en attente
- GET /api/mobile/drafts/<draft_id> - Détails d'un brouillon

- POST /api/mobile/actions - Appliquer une action sur un brouillon
- POST /api/mobile/actions/batch - Appliquer plusieurs actions
- POST /api/mobile/drafts/<draft_id>/read - Marquer comme lu

- GET /api/mobile/stats - Statistiques du dashboard
- POST /api/mobile/analytics - Enregistrer un événement

- GET /api/mobile/preferences - Récupérer les préférences
- PUT /api/mobile/preferences - Mettre à jour les préférences

- GET /api/mobile/config - Configuration de l'app
- PUT /api/mobile/config/maintenance - Mode maintenance (admin)
- PUT /api/mobile/config/versions - Versions de l'app (admin)
- PUT /api/mobile/config/feature/<flag_name> - Feature flags (admin)
"""

import logging
from datetime import datetime
from functools import wraps
from typing import Callable, Optional

from app.api.admin import require_admin

from flask import Blueprint, request, jsonify, g

from app.api.helpers import require_json
from app.domain.entities.mobile_companion import (
    MobileEventType,
    MobileDraftAction,
    MobileAnalyticsEvent,
    MobileDraftActionRequest,
)
from app.infrastructure.container import get_container

logger = logging.getLogger(__name__)

mobile_bp = Blueprint("mobile", __name__)


# ============================================================================
# HELPERS
# ============================================================================

def _authenticated_user_id() -> Optional[str]:
    """Resolve the authenticated user_id from the JWT (g.auth_user["email"]).

    Audit P0-001 (2026-04-28): the previous `require_user_id` decorator
    trusted whatever `user_id` arrived in the query string or JSON body,
    which let a remote caller list / mutate someone else's drafts. We now
    derive identity exclusively from the JWT — any client-supplied
    user_id is ignored. Returns None when no JWT is present (caller
    decides 401 vs. allow).
    """
    auth_user = getattr(g, "auth_user", None)
    if auth_user and auth_user.get("email"):
        return str(auth_user["email"])
    return None


def require_user_id(f: Callable) -> Callable:
    """Decorator: require an authenticated JWT and inject g.mobile_user_id.

    The view body MUST read `g.mobile_user_id` (or call
    `_authenticated_user_id()`) instead of `request.args.get("user_id")`.
    Any user_id from the request payload is intentionally discarded.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        user_id = _authenticated_user_id()
        if not user_id:
            return jsonify({"error": "Authentication required"}), 401
        g.mobile_user_id = user_id
        return f(*args, **kwargs)
    return decorated


def get_service():
    """Retourne le service mobile companion depuis le Container."""
    return get_container().get_mobile_companion_service()


def parse_datetime(date_str: Optional[str]) -> Optional[datetime]:
    """Parse une date ISO 8601."""
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_action(action_str: str) -> Optional[MobileDraftAction]:
    """Parse une action de brouillon."""
    try:
        return MobileDraftAction(action_str)
    except ValueError:
        return None


def parse_event_type(event_str: str) -> Optional[MobileEventType]:
    """Parse un type d'événement."""
    try:
        return MobileEventType(event_str)
    except ValueError:
        return None


# ============================================================================
# ROUTES - SESSION
# ============================================================================

@mobile_bp.route("/session/start", methods=["POST"])
@require_json
def start_session():
    """
    Démarre une nouvelle session mobile.

    Body JSON:
        user_id: Identifiant de l'utilisateur (required)
        device_token: Token push du device (optional)
        app_version: Version de l'app (optional)
        os_version: Version de l'OS (optional)
        device_model: Modèle du device (optional)

    Returns:
        Session créée avec configuration et préférences.
    """
    data = request.get_json()
    # P0-001: derive user_id from JWT, ignore client-supplied value.
    user_id = _authenticated_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required"}), 401

    service = get_service()
    result = service.start_session(
        user_id=user_id,
        device_token=data.get("device_token"),
        app_version=data.get("app_version"),
        os_version=data.get("os_version"),
        device_model=data.get("device_model"),
    )

    if not result.success:
        status_code = 503 if result.app_config and result.app_config.maintenance_mode else 400
        return jsonify({
            "success": False,
            "error": result.error_message,
            "app_config": result.app_config.to_dict() if result.app_config else None,
        }), status_code

    return jsonify({
        "success": True,
        "session": result.session.to_dict() if result.session else None,
        "app_config": result.app_config.to_dict() if result.app_config else None,
        "preferences": result.preferences.to_dict() if result.preferences else None,
    }), 201


@mobile_bp.route("/session/end", methods=["POST"])
@require_json
def end_session():
    """
    Termine une session mobile.

    Body JSON:
        session_id: Identifiant de la session (required)
        user_id: Identifiant de l'utilisateur (required)

    Returns:
        Succès ou erreur.
    """
    data = request.get_json()
    session_id = data.get("session_id")
    # P0-001: derive user_id from JWT, ignore client-supplied value.
    user_id = _authenticated_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required"}), 401

    if not session_id:
        return jsonify({"error": "session_id is required"}), 400

    service = get_service()
    success = service.end_session(session_id, user_id)

    return jsonify({"success": success}), 200 if success else 404


@mobile_bp.route("/session/touch", methods=["POST"])
@require_json
def touch_session():
    """
    Maintient une session active (heartbeat).

    Body JSON:
        session_id: Identifiant de la session (required)

    Returns:
        Succès ou erreur.
    """
    data = request.get_json()
    session_id = data.get("session_id")

    if not session_id:
        return jsonify({"error": "session_id is required"}), 400

    service = get_service()
    success = service.touch_session(session_id)

    return jsonify({"success": success}), 200 if success else 404


# ============================================================================
# ROUTES - SYNC & DRAFTS
# ============================================================================

@mobile_bp.route("/sync", methods=["POST"])
@require_json
def sync_data():
    """
    Synchronise les brouillons avec le mobile.

    Body JSON:
        user_id: Identifiant de l'utilisateur (required)
        device_token: Token du device (required)
        since: Date ISO depuis laquelle synchroniser (optional)
        limit: Nombre max de brouillons (optional, default: 100)
        cursor: Curseur de pagination (optional)

    Returns:
        Brouillons synchronisés et état de sync.
    """
    data = request.get_json()
    # P0-001: derive user_id from JWT, ignore client-supplied value.
    user_id = _authenticated_user_id() or data.get("user_id")
    device_token = data.get("device_token")
    if _authenticated_user_id() is None:
        return jsonify({"error": "Authentication required"}), 401

    if not user_id or not device_token:
        return jsonify({"error": "user_id and device_token are required"}), 400

    since = parse_datetime(data.get("since"))
    limit = data.get("limit", 100)
    cursor = data.get("cursor")

    service = get_service()
    response = service.sync_data(
        user_id=user_id,
        device_token=device_token,
        since=since,
        limit=limit,
        cursor=cursor,
    )

    return jsonify(response.to_dict()), 200 if response.success else 500


@mobile_bp.route("/drafts", methods=["GET"])
@require_user_id
def list_pending_drafts():
    """
    Liste les brouillons en attente d'action.

    Query params:
        user_id: Identifiant de l'utilisateur (required)
        limit: Nombre max (optional, default: 50)

    Returns:
        Liste des brouillons en attente.
    """
    user_id = g.mobile_user_id  # P0-001: from JWT, never from client
    limit = request.args.get("limit", 50, type=int)

    service = get_service()
    drafts = service.get_pending_drafts(user_id, limit)

    return jsonify({
        "count": len(drafts),
        "drafts": [d.to_list_dict() for d in drafts],
    })


@mobile_bp.route("/drafts/<draft_id>", methods=["GET"])
@require_user_id
def get_draft_details(draft_id: str):
    """
    Récupère les détails complets d'un brouillon.

    Args:
        draft_id: Identifiant du brouillon.

    Query params:
        user_id: Identifiant de l'utilisateur (required)

    Returns:
        Détails du brouillon.
    """
    user_id = g.mobile_user_id  # P0-001: from JWT, never from client

    service = get_service()
    draft = service.get_draft(draft_id, user_id)

    if not draft:
        return jsonify({"error": "Draft not found"}), 404

    return jsonify({"draft": draft.to_dict()})


# ============================================================================
# ROUTES - ACTIONS
# ============================================================================

@mobile_bp.route("/actions", methods=["POST"])
@require_json
def apply_action():
    """
    Applique une action sur un brouillon.

    Body JSON:
        draft_id: Identifiant du brouillon (required)
        action: "approved" | "rejected" | "edited" | "sent" (required)
        user_id: Identifiant de l'utilisateur (required)
        edited_body: Nouveau corps si action="edited" (required for edit)
        device_token: Token du device (optional)
        offline_timestamp: Timestamp si action offline (optional)

    Returns:
        Brouillon mis à jour.
    """
    data = request.get_json()
    draft_id = data.get("draft_id")
    action_str = data.get("action")
    # P0-001: derive user_id from JWT, ignore client-supplied value.
    user_id = _authenticated_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required"}), 401

    if not draft_id or not action_str:
        return jsonify({"error": "draft_id and action are required"}), 400

    action = parse_action(action_str)
    if not action:
        return jsonify({"error": f"Invalid action: {action_str}"}), 400

    # Vérifier edited_body pour les éditions
    if action == MobileDraftAction.EDITED and not data.get("edited_body"):
        return jsonify({"error": "edited_body is required for edit action"}), 400

    try:
        action_request = MobileDraftActionRequest(
            draft_id=draft_id,
            action=action,
            user_id=user_id,
            edited_body=data.get("edited_body"),
            device_token=data.get("device_token"),
            offline_timestamp=parse_datetime(data.get("offline_timestamp")),
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    service = get_service()
    result = service.apply_action(action_request)

    if not result.success:
        return jsonify({
            "success": False,
            "error": result.error_message,
        }), 400

    return jsonify({
        "success": True,
        "draft": result.draft.to_dict() if result.draft else None,
    })


@mobile_bp.route("/actions/batch", methods=["POST"])
@require_json
def apply_batch_actions():
    """
    Applique plusieurs actions en batch.

    Body JSON:
        user_id: Identifiant de l'utilisateur (required)
        actions: Liste d'actions (required)
            - draft_id: Identifiant du brouillon
            - action: Action à appliquer
            - edited_body: Nouveau corps si édition

    Returns:
        Résultats par brouillon.
    """
    data = request.get_json()
    # P0-001: derive user_id from JWT, ignore client-supplied value.
    user_id = _authenticated_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required"}), 401
    actions_data = data.get("actions", [])

    if not actions_data:
        return jsonify({"error": "actions list is required"}), 400

    action_requests = []
    for action_data in actions_data:
        action = parse_action(action_data.get("action"))
        if not action:
            continue

        try:
            req = MobileDraftActionRequest(
                draft_id=action_data.get("draft_id"),
                action=action,
                user_id=user_id,
                edited_body=action_data.get("edited_body"),
                device_token=data.get("device_token"),
            )
            action_requests.append(req)
        except ValueError:
            continue

    service = get_service()
    result = service.apply_batch_actions(action_requests, user_id)

    return jsonify({
        "success": result.success,
        "total": len(action_requests),
        "succeeded": len(action_requests) - result.error_count,
        "failed": result.error_count,
        "results": result.results,
    })


@mobile_bp.route("/drafts/<draft_id>/read", methods=["POST"])
@require_json
def mark_draft_read(draft_id: str):
    """
    Marque un brouillon comme lu.

    Args:
        draft_id: Identifiant du brouillon.

    Body JSON:
        user_id: Identifiant de l'utilisateur (required)

    Returns:
        Succès ou erreur.
    """
    # P0-001: derive user_id from JWT, ignore any client-supplied value
    # in the body. Body is intentionally not consumed here — owner-scoped
    # mark-read does not need it.
    user_id = _authenticated_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required"}), 401

    service = get_service()
    success = service.mark_draft_read(draft_id, user_id)

    return jsonify({"success": success}), 200 if success else 404


# ============================================================================
# ROUTES - STATS & ANALYTICS
# ============================================================================

@mobile_bp.route("/stats", methods=["GET"])
@require_user_id
def get_stats():
    """
    Récupère les statistiques pour le dashboard mobile.

    Query params:
        user_id: Identifiant de l'utilisateur (required)
        days: Nombre de jours (optional, default: 7)

    Returns:
        Statistiques du dashboard.
    """
    user_id = g.mobile_user_id  # P0-001: from JWT, never from client
    days = request.args.get("days", 7, type=int)

    service = get_service()
    stats = service.get_stats(user_id, days)

    return jsonify({"stats": stats.to_dict()})


@mobile_bp.route("/analytics", methods=["POST"])
@require_json
def track_analytics():
    """
    Enregistre un ou plusieurs événements analytics.

    Body JSON (single event):
        event_type: Type d'événement (required)
        user_id: Identifiant de l'utilisateur (required)
        session_id: Identifiant de la session (optional)
        properties: Propriétés additionnelles (optional)
        device_info: Informations sur le device (optional)

    Body JSON (batch):
        events: Liste d'événements (required)

    Returns:
        Succès ou erreur.
    """
    data = request.get_json()

    # Déterminer si c'est un batch ou un single event
    events_data = data.get("events")
    if events_data:
        # P0-001: derive user_id from JWT, ignore client-supplied value.
        auth_user_id = _authenticated_user_id()
        if not auth_user_id:
            return jsonify({"error": "Authentication required"}), 401
        # Batch mode
        events = []
        for event_data in events_data:
            event_type = parse_event_type(event_data.get("event_type"))
            if not event_type:
                continue
            try:
                event = MobileAnalyticsEvent(
                    event_type=event_type,
                    user_id=auth_user_id,
                    session_id=event_data.get("session_id"),
                    properties=event_data.get("properties", {}),
                    device_info=event_data.get("device_info", {}),
                )
                events.append(event)
            except ValueError:
                continue

        service = get_service()
        count = service.track_batch_events(events)

        return jsonify({
            "success": True,
            "tracked": count,
        })
    else:
        # Single event mode
        event_type = parse_event_type(data.get("event_type"))
        # P0-001: derive user_id from JWT, ignore client-supplied value.
        user_id = _authenticated_user_id()
        if not user_id:
            return jsonify({"error": "Authentication required"}), 401

        if not event_type:
            return jsonify({"error": "event_type is required"}), 400

        try:
            event = MobileAnalyticsEvent(
                event_type=event_type,
                user_id=user_id,
                session_id=data.get("session_id"),
                properties=data.get("properties", {}),
                device_info=data.get("device_info", {}),
            )
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

        service = get_service()
        success = service.track_event(event)

        return jsonify({"success": success})


# ============================================================================
# ROUTES - PREFERENCES
# ============================================================================

@mobile_bp.route("/preferences", methods=["GET"])
@require_user_id
def get_preferences():
    """
    Récupère les préférences utilisateur.

    Query params:
        user_id: Identifiant de l'utilisateur (required)

    Returns:
        Préférences utilisateur.
    """
    user_id = g.mobile_user_id  # P0-001: from JWT, never from client

    service = get_service()
    preferences = service.get_preferences(user_id)

    return jsonify({"preferences": preferences.to_dict()})


@mobile_bp.route("/preferences", methods=["PUT"])
@require_json
def update_preferences():
    """
    Met à jour les préférences utilisateur.

    Body JSON:
        user_id: Identifiant de l'utilisateur (required)
        notification_preference: "all" | "important_only" | "none" (optional)
        sync_frequency: "realtime" | "5min" | "15min" | "1hour" | "manual" (optional)
        auto_approve_threshold: 0-100 (optional)
        dark_mode: true | false (optional)
        language: Code langue (optional)
        biometric_enabled: true | false (optional)
        offline_mode: true | false (optional)

    Returns:
        Préférences mises à jour.
    """
    data = request.get_json()
    # P0-001: derive user_id from JWT, ignore client-supplied value.
    user_id = _authenticated_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required"}), 401

    # Extraire les champs à mettre à jour
    updates = {}
    allowed_fields = [
        "notification_preference", "sync_frequency", "auto_approve_threshold",
        "dark_mode", "language", "biometric_enabled", "offline_mode",
    ]
    for field in allowed_fields:
        if field in data:
            updates[field] = data[field]

    if not updates:
        return jsonify({"error": "No fields to update"}), 400

    # Valider les valeurs enum avant de les envoyer au service
    from app.domain.entities.mobile_companion import NotificationPreference, SyncFrequency

    if "notification_preference" in updates:
        try:
            NotificationPreference(updates["notification_preference"])
        except ValueError:
            valid_values = [e.value for e in NotificationPreference]
            return jsonify({
                "error": f"Invalid notification_preference. Valid values: {valid_values}"
            }), 400

    if "sync_frequency" in updates:
        try:
            SyncFrequency(updates["sync_frequency"])
        except ValueError:
            valid_values = [e.value for e in SyncFrequency]
            return jsonify({
                "error": f"Invalid sync_frequency. Valid values: {valid_values}"
            }), 400

    service = get_service()
    preferences = service.update_preferences(user_id, updates)

    if not preferences:
        return jsonify({"error": "User preferences not found"}), 404

    return jsonify({"preferences": preferences.to_dict()})


# ============================================================================
# ROUTES - CONFIG (ADMIN)
# ============================================================================

@mobile_bp.route("/config", methods=["GET"])
def get_app_config():
    """
    Récupère la configuration de l'app mobile.

    Query params:
        app_version: Version de l'app pour vérification (optional)

    Returns:
        Configuration de l'app.
    """
    app_version = request.args.get("app_version")

    service = get_service()
    config = service.get_app_config(app_version)

    return jsonify({"config": config})


@mobile_bp.route("/config/maintenance", methods=["PUT"])
@require_admin
@require_json
def set_maintenance_mode():
    """
    Active/désactive le mode maintenance (admin).

    F-04 (audit issue #209, 2026-04-29): @require_admin added; previous
    versions accepted any authenticated JWT and let any user globally
    DoS the mobile app.

    Body JSON:
        enabled: true | false (required)
        message: Message de maintenance (optional)

    Returns:
        Succès ou erreur.
    """
    data = request.get_json()
    enabled = data.get("enabled")

    if enabled is None:
        return jsonify({"error": "enabled is required"}), 400

    service = get_service()
    success = service.set_maintenance_mode(enabled, data.get("message"))

    return jsonify({
        "success": success,
        "maintenance_mode": enabled,
    })


@mobile_bp.route("/config/versions", methods=["PUT"])
@require_admin
@require_json
def update_versions():
    """
    Met à jour les versions de l'app (admin).

    F-04 (audit issue #209, 2026-04-29): @require_admin added.

    Body JSON:
        min_version: Version minimale (optional)
        latest_version: Dernière version (optional)
        force_update: Forcer la mise à jour (optional)

    Returns:
        Configuration mise à jour.
    """
    data = request.get_json()

    service = get_service()
    config = service.update_versions(
        min_version=data.get("min_version"),
        latest_version=data.get("latest_version"),
        force_update=data.get("force_update"),
    )

    return jsonify({"config": config.to_dict()})


@mobile_bp.route("/config/feature/<flag_name>", methods=["PUT"])
@require_admin
@require_json
def update_feature_flag(flag_name: str):
    """
    Met à jour un feature flag (admin).

    F-04 (audit issue #209, 2026-04-29): @require_admin added.

    Args:
        flag_name: Nom du flag.

    Body JSON:
        enabled: true | false (required)

    Returns:
        Succès ou erreur.
    """
    data = request.get_json()
    enabled = data.get("enabled")

    if enabled is None:
        return jsonify({"error": "enabled is required"}), 400

    service = get_service()
    success = service.update_feature_flag(flag_name, enabled)

    return jsonify({
        "success": success,
        "flag": flag_name,
        "enabled": enabled,
    })
