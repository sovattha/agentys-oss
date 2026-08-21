# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Blueprint /api/account — confirm, reject account actions (password reset, email change)."""

import logging

from flask import Blueprint, jsonify, request

from app.api.utils.errors import error_response

logger = logging.getLogger(__name__)

account_actions_bp = Blueprint("account_actions", __name__)


def _get_store():
    from app.api.routes import _get_container
    return _get_container().get_pending_draft_store()


def _emit(event_type: str, data: dict, account_id: int | None = None) -> None:
    try:
        from app.api.websocket import emit_to_account
        if account_id is None:
            from app.api.routes_helpers import _resolve_account_id_for_user
            account_id = _resolve_account_id_for_user()
        emit_to_account("daemon_event", {"type": event_type, "data": data}, account_id)
    except Exception as exc:
        logger.debug("[account] WebSocket emit failed: %s", exc)


@account_actions_bp.route("/account/<draft_id>/confirm", methods=["POST"])
def confirm_account_action(draft_id: str):
    """Execute l'action de compte apres approbation admin."""
    from app.api.routes import _rate_limited
    from app.api.routes_helpers import _resolve_account_id_cached
    # Per-tenant bucket (H-8 follow-up #534).
    try:
        _aid = _resolve_account_id_cached()
    except Exception:
        _aid = "anonymous"
    allowed, retry_after = _rate_limited(f"account_confirm:{_aid}", max_calls=3, window_seconds=60)
    if not allowed:
        return jsonify({"error": "Trop de tentatives", "retry_after": retry_after}), 429

    store = _get_store()
    draft = store.get_by_id(draft_id)
    if not draft:
        return jsonify({"error": "Draft introuvable"}), 404

    # Ownership check — prevent cross-account action execution
    from app.api.routes_helpers import _resolve_account_id_for_user
    account_id = _resolve_account_id_for_user()
    # Audit 2026-04-25 CRIT-Iso-4: strict comparison rejects None/empty.
    _draft_aid = getattr(draft, "account_id", None)
    if _draft_aid is None or str(_draft_aid).strip() == "" or str(_draft_aid) != str(account_id):
        return jsonify({"error": "Forbidden"}), 403

    ai = draft.account_info or {}
    if ai.get("status") != "pending":
        return jsonify({"error": f"Statut invalide pour confirmation : {ai.get('status')}"}), 409

    # Retrieve stored password from secure memory
    generated_password_full = store.get_secure_password(draft_id)

    # Reconstruct AccountResult for execution
    from app.account_agent import AccountAgent, AccountResult
    result = AccountResult(
        detected=True,
        action=ai.get("action", ""),
        requester_email=ai.get("requester_email", ""),
        requester_name=ai.get("requester_name"),
        wp_user={"id": ai.get("wp_user_id"), "slug": ai.get("wp_username"), "email": ai.get("wp_user_email")},
        new_email=ai.get("new_email"),
        generated_password=ai.get("generated_password"),
        generated_password_full=generated_password_full,
        confidence=ai.get("confidence", 0),
        reason=ai.get("reason", ""),
        status="pending",
        method=ai.get("method", "direct"),
        brand_name=ai.get("brand_name", ""),
        provider_name=ai.get("provider_name", "wordpress"),
    )

    agent = AccountAgent()
    if ai.get("wp_user_id"):
        success = agent.execute_action(result)
        if not success:
            provider_name = ai.get("provider_name", "la plateforme")
            return error_response(
                "ACCOUNT_ACTION_FAILED",
                f"The action failed on {provider_name}",
                500,
                context={"provider": provider_name},
            )
    # No wp_user_id → skip platform update; password injected into draft for admin to apply manually

    # Update status
    updated = {**ai, "status": "executed"}
    store.update_account_info(draft_id, updated)
    store.clear_secure_password(draft_id)

    # Inject new password into draft body so the reply is ready to send
    new_body = None
    if (
        ai.get("action") == "password_reset"
        and ai.get("method", "direct") == "direct"
        and generated_password_full
    ):
        brand_name = ai.get("brand_name") or ""
        brand_label = f" sur {brand_name}" if brand_name else ""
        password_line = f"Votre nouveau mot de passe{brand_label} : {generated_password_full}"
        current_body = draft.draft_body or ""
        if "[MOT_DE_PASSE]" in current_body:
            # LLM wrote the placeholder — replace it inline
            new_body = current_body.replace("[MOT_DE_PASSE]", password_line)
        else:
            # Fallback: insert before sign-off if last paragraph is short, otherwise append
            password_para = (
                f"{password_line}\n\n"
                "Pour votre sécurité, nous vous recommandons de le modifier dès votre première connexion."
            )
            parts = current_body.rsplit("\n\n", 1)
            if len(parts) == 2 and len(parts[1].strip()) < 60:
                new_body = parts[0] + "\n\n" + password_para + "\n\n" + parts[1]
            else:
                new_body = current_body.rstrip() + "\n\n" + password_para
        store.update_content(draft_id, draft.draft_subject or "", new_body)

    _emit("account_action_executed", {
        "draft_id": draft_id,
        "email_id": draft.email_id,
        "action": ai.get("action"),
        "wp_username": ai.get("wp_username"),
    })

    response = {"success": True, "action": ai.get("action"), "method": ai.get("method", "direct")}
    # For password reset with direct method: return the password + updated body
    # For reset_link method (Shopify): no password to return
    if ai.get("action") == "password_reset" and ai.get("method", "direct") == "direct" and generated_password_full:
        response["new_password"] = generated_password_full
    if new_body is not None:
        response["new_body"] = new_body

    logger.info("[account] Action executee: %s pour %s (draft=%s)", ai.get("action"), ai.get("wp_username"), draft_id)
    return jsonify(response)


@account_actions_bp.route("/account/<draft_id>/reject", methods=["POST"])
def reject_account_action(draft_id: str):
    """Refuse l'action de compte."""
    store = _get_store()
    draft = store.get_by_id(draft_id)
    if not draft:
        return jsonify({"error": "Draft introuvable"}), 404

    # Ownership check — prevent cross-account rejection
    from app.api.routes_helpers import _resolve_account_id_for_user
    account_id = _resolve_account_id_for_user()
    # Audit 2026-04-25 CRIT-Iso-4: strict comparison rejects None/empty.
    _draft_aid = getattr(draft, "account_id", None)
    if _draft_aid is None or str(_draft_aid).strip() == "" or str(_draft_aid) != str(account_id):
        return jsonify({"error": "Forbidden"}), 403

    ai = draft.account_info or {}
    if ai.get("status") not in ("pending", "not_found"):
        return jsonify({"error": f"Statut invalide pour rejet : {ai.get('status')}"}), 409

    body = request.get_json(silent=True) or {}
    reject_reason = body.get("reason", "")

    updated = {
        **ai,
        "status": "rejected",
        "reason": f"Refuse par l'utilisateur. {reject_reason}".strip(),
    }
    store.update_account_info(draft_id, updated)
    store.clear_secure_password(draft_id)

    _emit("account_action_rejected", {
        "draft_id": draft_id,
        "email_id": draft.email_id,
        "action": ai.get("action"),
        "reason": reject_reason,
    })

    logger.info("[account] Action refusee: %s (draft=%s)", ai.get("action"), draft_id)
    return jsonify({"success": True})
