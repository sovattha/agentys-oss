# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
API REST pour l'édition temps réel des brouillons.

Endpoints:
- POST /api/realtime-edit/sessions - Démarrer une session
- PUT /api/realtime-edit/sessions/<id>/text - Mettre à jour le texte
- POST /api/realtime-edit/sessions/<id>/suggest - Obtenir une suggestion
- POST /api/realtime-edit/sessions/<id>/apply - Appliquer une suggestion
- DELETE /api/realtime-edit/sessions/<id> - Fermer une session
"""

from flask import Blueprint, request, jsonify, g

from app.api.utils.errors import error_response
from app.infrastructure.container import get_container
from app.domain.entities.realtime_edit import (
    TextChange,
    EditTrigger,
    Suggestion,
)


realtime_edit_bp = Blueprint("realtime_edit", __name__)


def _get_container():
    """Retourne le container d'injection de dépendances."""
    return get_container()


def _caller_user_id() -> str | None:
    """Audit 2026-04-25 (HIGH-Backend-1): resolve the JWT-authenticated user.

    Loopback (Tauri) gets a magic single-user identity so the desktop app
    keeps working without a JWT. Web/JWT callers MUST own the session.
    """
    auth_user = getattr(g, "auth_user", None)
    if auth_user and auth_user.get("email"):
        return str(auth_user["email"]).lower()
    if auth_user and auth_user.get("id"):
        return f"user:{auth_user['id']}"
    # Loopback (Tauri desktop) — no JWT — sentinel string the use case
    # treats as "single-user host". Same convention as `_check_token_ownership`.
    from app.api.auth import is_trusted_loopback
    if is_trusted_loopback():
        return "loopback:tauri"
    return None


def _enforce_session_ownership(session, caller_id: str | None):
    """Return a (response, status) tuple if the caller can't access the session, else None."""
    if session is None:
        return jsonify({"error": "Session not found"}), 404
    if caller_id is None:
        return error_response("NOT_AUTHENTICATED", "Not authenticated", 401)
    # The session.user_id is whatever was stored at start time. If the
    # caller is loopback, allow (single-user). Otherwise require an exact
    # match against the caller's stable identity.
    if caller_id == "loopback:tauri":
        return None
    session_owner = str(getattr(session, "user_id", "") or "").lower()
    if not session_owner or session_owner != caller_id:
        # Don't disclose existence — same envelope as not-found.
        return jsonify({"error": "Session not found"}), 404
    return None


@realtime_edit_bp.route("/sessions", methods=["POST"])
def start_session():
    """
    Démarre une nouvelle session d'édition temps réel.

    Request body:
        {
            "user_id": "string",
            "initial_text": "string (optional)"
        }

    Response (201):
        {
            "session_id": "string",
            "user_id": "string",
            "current_text": "string",
            "is_active": true,
            "created_at": "ISO8601"
        }
    """
    data = request.get_json() or {}

    # Audit 2026-04-25 (HIGH-Backend-1): bind the session owner to the
    # JWT identity, NEVER to a body-supplied user_id (which an attacker
    # could spoof to plant a session under another user's name).
    caller_id = _caller_user_id()
    if caller_id is None:
        return error_response("NOT_AUTHENTICATED", "Not authenticated", 401)
    user_id = caller_id

    initial_text = data.get("initial_text", "")

    container = _get_container()
    use_case = container.get_start_edit_session_use_case()

    session = use_case.execute(
        user_id=user_id,
        initial_text=initial_text,
    )

    return jsonify({
        "session_id": session.session_id,
        "user_id": session.user_id,
        "current_text": session.current_text,
        "is_active": session.is_active,
        "created_at": session.created_at.isoformat(),
    }), 201


@realtime_edit_bp.route("/sessions/<session_id>/text", methods=["PUT"])
def update_text(session_id: str):
    """
    Met à jour le texte d'une session.

    Request body:
        {
            "old_text": "string",
            "new_text": "string",
            "cursor_position": int
        }

    Response (200):
        {
            "session_id": "string",
            "current_text": "string",
            "version": int
        }
    """
    data = request.get_json() or {}

    old_text = data.get("old_text", "")
    new_text = data.get("new_text")
    cursor_position = data.get("cursor_position", len(new_text) if new_text else 0)

    if new_text is None:
        return jsonify({"error": "new_text is required"}), 400

    # Audit 2026-04-25 (HIGH-Backend-1): ownership check.
    container = _get_container()
    fetch_use_case = container.get_edit_session_use_case()
    existing = fetch_use_case.execute(session_id=session_id)
    denied = _enforce_session_ownership(existing, _caller_user_id())
    if denied is not None:
        return denied

    change = TextChange.from_typing(
        old_text=old_text,
        new_text=new_text,
        cursor_position=cursor_position,
    )

    use_case = container.get_process_text_change_use_case()

    session = use_case.execute(
        session_id=session_id,
        change=change,
    )

    if session is None:
        return jsonify({"error": "Session not found"}), 404

    return jsonify({
        "session_id": session.session_id,
        "current_text": session.current_text,
        "version": session.version,
    }), 200


@realtime_edit_bp.route("/sessions/<session_id>/suggest", methods=["POST"])
def get_suggestion(session_id: str):
    """
    Génère une suggestion IA pour le texte courant.

    Request body:
        {
            "trigger": "blur" | "typing_pause" | "sentence_end" | "manual"
        }

    Response (200):
        {
            "session_id": "string",
            "original_full_text": "string",
            "suggested_full_text": "string",
            "suggestion_id": "string",
            "suggestions": [
                {
                    "suggestion_id": "string",
                    "original_text": "string",
                    "suggested_text": "string",
                    "confidence": float,
                    "explanation": "string (optional)"
                }
            ],
            "processing_time_ms": int
        }
    """
    data = request.get_json() or {}

    trigger_str = data.get("trigger", "manual")
    trigger = EditTrigger.from_string(trigger_str)

    container = _get_container()
    # Audit 2026-04-25 (HIGH-Backend-1): ownership check before suggestion.
    fetch_use_case = container.get_edit_session_use_case()
    existing = fetch_use_case.execute(session_id=session_id)
    denied = _enforce_session_ownership(existing, _caller_user_id())
    if denied is not None:
        return denied

    use_case = container.get_suggestion_use_case()

    result = use_case.execute(
        session_id=session_id,
        trigger=trigger,
    )

    if result is None:
        return jsonify({
            "session_id": session_id,
            "message": "No suggestion available",
        }), 200

    suggestions_data = []
    for s in result.suggestions:
        suggestions_data.append({
            "suggestion_id": s.suggestion_id,
            "original_text": s.original_text,
            "suggested_text": s.suggested_text,
            "confidence": s.confidence,
            "explanation": s.explanation,
        })

    return jsonify({
        "session_id": result.session_id,
        "original_full_text": result.original_full_text,
        "suggested_full_text": result.suggested_full_text,
        "suggestion_id": result.suggestion_id,
        "suggestions": suggestions_data,
        "processing_time_ms": result.processing_time_ms,
    }), 200


@realtime_edit_bp.route("/sessions/<session_id>/apply", methods=["POST"])
def apply_suggestion(session_id: str):
    """
    Applique ou rejette une suggestion.

    Request body:
        {
            "suggestion_id": "string",
            "accept": true/false,
            "original_text": "string",
            "suggested_text": "string"
        }

    Response (200):
        {
            "session_id": "string",
            "current_text": "string",
            "applied": true/false
        }
    """
    data = request.get_json() or {}

    accept = data.get("accept", True)
    original_text = data.get("original_text", "")
    suggested_text = data.get("suggested_text", "")

    if not original_text or not suggested_text:
        return jsonify({"error": "original_text and suggested_text are required"}), 400

    suggestion = Suggestion(
        original_text=original_text,
        suggested_text=suggested_text,
        confidence=1.0,  # On fait confiance puisque c'est l'utilisateur qui applique
    )

    container = _get_container()
    # Audit 2026-04-25 (HIGH-Backend-1): ownership check before applying.
    fetch_use_case = container.get_edit_session_use_case()
    existing = fetch_use_case.execute(session_id=session_id)
    denied = _enforce_session_ownership(existing, _caller_user_id())
    if denied is not None:
        return denied

    use_case = container.get_apply_suggestion_use_case()

    session = use_case.execute(
        session_id=session_id,
        suggestion=suggestion,
        accept=accept,
    )

    if session is None:
        return jsonify({"error": "Session not found"}), 404

    return jsonify({
        "session_id": session.session_id,
        "current_text": session.current_text,
        "applied": accept,
    }), 200


@realtime_edit_bp.route("/sessions/<session_id>", methods=["DELETE"])
def close_session(session_id: str):
    """
    Ferme une session d'édition.

    Response (200):
        {
            "session_id": "string",
            "is_active": false,
            "closed_at": "ISO8601"
        }
    """
    container = _get_container()
    # Audit 2026-04-25 (HIGH-Backend-1): ownership check before close.
    fetch_use_case = container.get_edit_session_use_case()
    existing = fetch_use_case.execute(session_id=session_id)
    denied = _enforce_session_ownership(existing, _caller_user_id())
    if denied is not None:
        return denied

    use_case = container.get_close_edit_session_use_case()

    session = use_case.execute(session_id=session_id)

    if session is None:
        return jsonify({"error": "Session not found"}), 404

    return jsonify({
        "session_id": session.session_id,
        "is_active": session.is_active,
        "closed_at": session.closed_at.isoformat() if session.closed_at else None,
    }), 200


@realtime_edit_bp.route("/sessions/<session_id>", methods=["GET"])
def get_session(session_id: str):
    """
    Récupère les informations d'une session.

    Response (200):
        {
            "session_id": "string",
            "user_id": "string",
            "current_text": "string",
            "is_active": boolean,
            "created_at": "ISO8601",
            "version": int
        }
    """
    container = _get_container()
    use_case = container.get_edit_session_use_case()

    session = use_case.execute(session_id=session_id)

    # Audit 2026-04-25 (HIGH-Backend-1): ownership check before exposing
    # session content (text could contain a draft NDA, salary letter, etc.).
    denied = _enforce_session_ownership(session, _caller_user_id())
    if denied is not None:
        return denied

    return jsonify({
        "session_id": session.session_id,
        "user_id": session.user_id,
        "current_text": session.current_text,
        "is_active": session.is_active,
        "created_at": session.created_at.isoformat(),
        "version": session.version,
    }), 200
