# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Connectivity API Blueprint.

Provides endpoints for network connectivity status and offline action queue.
"""

import logging
from typing import Any, Dict

from flask import Blueprint, jsonify, request, g

from app.services.connectivity_service import get_connectivity_service
from app.services.action_queue import get_action_queue, process_all_pending_actions
from app.api.websocket import emit_queue_processed

logger = logging.getLogger(__name__)

connectivity_bp = Blueprint("connectivity", __name__, url_prefix="/api/connectivity")


def _user_owns_account(account_id: int) -> bool:
    """Audit 2026-04-25 (HIGH-Backend-2 / sub-report 02 H-... no, 02 inferred).

    Verify that the JWT user owns `account_id`. Loopback (Tauri desktop)
    is allowed without restriction. JWT users must match the
    `accounts.user_id` column (mirroring _auth_helpers.check_account_ownership).
    """
    from app.api.auth import is_trusted_loopback
    auth_user = getattr(g, "auth_user", None)

    # Loopback caller without JWT — trust the host.
    if (auth_user is None) and is_trusted_loopback():
        return True
    if not auth_user or not auth_user.get("id"):
        return False
    try:
        from app.db.database import get_db_session
        from app.db.repositories.account_repository import AccountRepository
        with get_db_session() as session:
            repo = AccountRepository(session)
            account = repo.get_by_id(account_id)
            if account is None:
                return False
            user_id = int(auth_user["id"])
            account_uid = getattr(account, "user_id", None)
            if account_uid is None:
                # Legacy account without user_id — refuse cross-account access
                # in JWT mode (defensive default; isolation audit M-6 hint).
                return False
            return int(account_uid) == user_id
    except Exception as exc:
        logger.warning(f"[connectivity] ownership check failed: {exc}")
        return False


@connectivity_bp.route("/status", methods=["GET"])
def get_connectivity_status() -> tuple:
    """
    Get current network connectivity status.

    Returns:
        JSON with connectivity status including:
        - is_online: Whether the app is currently online
        - last_check_at: ISO timestamp of last connectivity check
        - last_online_at: ISO timestamp of when connectivity was last online
        - last_offline_at: ISO timestamp of when connectivity was last offline
        - pending_actions_count: Number of actions waiting to be synced
    """
    connectivity_service = get_connectivity_service()

    if connectivity_service is None:
        # Service not initialized - assume online (first load)
        return jsonify({
            "success": True,
            "status": {
                "is_online": True,
                "last_check_at": None,
                "last_online_at": None,
                "last_offline_at": None,
                "pending_actions_count": 0,
            }
        }), 200

    status = connectivity_service.status
    action_queue = get_action_queue()
    pending_count = action_queue.get_pending_count()

    response: Dict[str, Any] = {
        "success": True,
        "status": {
            "is_online": status.is_online,
            "last_check_at": status.last_check_at.isoformat() if status.last_check_at else None,
            "last_online_at": status.last_online_at.isoformat() if status.last_online_at else None,
            "last_offline_at": status.last_offline_at.isoformat() if status.last_offline_at else None,
            "pending_actions_count": pending_count,
        }
    }

    return jsonify(response), 200


@connectivity_bp.route("/check", methods=["POST"])
def trigger_connectivity_check() -> tuple:
    """
    Trigger an immediate connectivity check.

    Returns:
        JSON with current connectivity status after check.
    """
    connectivity_service = get_connectivity_service()

    if connectivity_service is None:
        return jsonify({
            "success": False,
            "error": "Connectivity service not initialized"
        }), 503

    is_online = connectivity_service.check_now()

    logger.info(f"Manual connectivity check triggered via API: {'online' if is_online else 'offline'}")

    return jsonify({
        "success": True,
        "is_online": is_online,
        "message": "Connectivity check completed"
    }), 200


@connectivity_bp.route("/queue", methods=["GET"])
def get_queue_summary() -> tuple:
    """
    Get summary of pending action queue across all accounts.

    Returns:
        JSON with queue summary including:
        - total_pending: Total pending actions across all accounts
        - is_online: Current connectivity status
    """
    action_queue = get_action_queue()
    connectivity_service = get_connectivity_service()

    pending_count = action_queue.get_pending_count()
    is_online = connectivity_service.is_online if connectivity_service else True

    return jsonify({
        "success": True,
        "queue": {
            "total_pending": pending_count,
            "is_online": is_online,
        }
    }), 200


@connectivity_bp.route("/queue/<int:account_id>", methods=["GET"])
def get_account_queue(account_id: int) -> tuple:
    """
    Get pending actions for a specific account.

    Args:
        account_id: The account ID to get pending actions for.

    Query params:
        limit: Maximum number of actions to return (default 50, max 100)

    Returns:
        JSON with list of pending actions for the account.
    """
    # Audit 2026-04-25 (HIGH-Backend-2): IDOR fix. Previously any JWT user
    # could iterate account_ids and read every tenant's queue.
    if not _user_owns_account(account_id):
        return jsonify({
            "success": False,
            "error": "Account not found",
        }), 404

    action_queue = get_action_queue()

    # Get limit from query params
    try:
        limit = min(int(request.args.get("limit", 50)), 100)
    except (ValueError, TypeError):
        limit = 50

    pending_count = action_queue.get_pending_count(account_id=account_id)
    pending_actions = action_queue.get_pending_actions(account_id=account_id, limit=limit)

    actions_list = []
    for action in pending_actions:
        actions_list.append({
            "id": action.id,
            "action_type": action.action_type,
            "email_id": action.email_id,
            "status": action.status,
            "retry_count": action.retry_count,
            "created_at": action.created_at.isoformat() if action.created_at else None,
            "error_message": action.error_message,
        })

    return jsonify({
        "success": True,
        "account_id": account_id,
        "queue": {
            "total_pending": pending_count,
            "actions": actions_list,
        }
    }), 200


@connectivity_bp.route("/queue/<int:account_id>/action/<int:action_id>", methods=["DELETE"])
def cancel_pending_action(account_id: int, action_id: int) -> tuple:
    """
    Cancel a pending action.

    Args:
        account_id: The account ID (for validation).
        action_id: The action ID to cancel.

    Returns:
        JSON indicating whether cancellation was successful.
    """
    # Audit 2026-04-25 (HIGH-Backend-2): ownership check before mutation.
    if not _user_owns_account(account_id):
        return jsonify({
            "success": False,
            "error": "Action not found",
        }), 404

    action_queue = get_action_queue()

    cancelled = action_queue.cancel_action(action_id, account_id=account_id)

    if cancelled:
        logger.info(f"Cancelled action {action_id} for account {account_id}")
        return jsonify({
            "success": True,
            "message": f"Action {action_id} cancelled"
        }), 200
    else:
        return jsonify({
            "success": False,
            "error": "Action not found or already processed"
        }), 404


@connectivity_bp.route("/queue/process", methods=["POST"])
def process_queue() -> tuple:
    """
    Process pending actions for accounts owned by the caller.

    This endpoint is typically called when connectivity is restored
    to sync queued offline actions.

    H-5 (audit security.md, issue #531): pre-fix, the route delegated to
    ``process_all_pending_actions()`` which iterated EVERY account in the
    DB regardless of ownership. The sibling cancel route at L:212 already
    has a per-id ownership check ; this one was global. A non-admin JWT
    user could force-flush sends/deletes/archives queued by other users
    against the real upstream provider. Fix: scope the iteration to the
    caller's accounts (``Account.user_id == auth_user.id``). Loopback
    Tauri without JWT keeps the legacy unrestricted behaviour because
    the host is single-user by construction (mirrors ``_user_owns_account``
    above).

    Returns:
        JSON with processing results per account.
    """
    from app.api.auth import is_trusted_loopback

    auth_user = getattr(g, "auth_user", None)
    is_loopback_no_jwt = (auth_user is None) and is_trusted_loopback()

    if is_loopback_no_jwt:
        scope_user_id: int | None = None  # legacy: trust the host, process every account
    elif auth_user and auth_user.get("id") is not None:
        try:
            scope_user_id = int(auth_user["id"])
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": "Invalid auth context"}), 401
    else:
        # Belt-and-suspenders: blueprint guard should have rejected this
        # already, but if it ever falls through don't drain the global queue.
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    connectivity_service = get_connectivity_service()

    # Check if we're online before processing
    if connectivity_service and not connectivity_service.is_online:
        return jsonify({
            "success": False,
            "error": "Cannot process queue while offline"
        }), 503

    action_queue = get_action_queue()
    initial_pending = action_queue.get_pending_count()

    if initial_pending == 0:
        return jsonify({
            "success": True,
            "message": "No pending actions to process",
            "results": {}
        }), 200

    logger.info(f"Processing {initial_pending} pending actions...")

    # Process pending actions scoped to the caller's accounts (None = loopback host).
    results = process_all_pending_actions(user_id=scope_user_id)

    # Calculate totals
    total_completed = sum(r.completed for r in results.values())
    total_failed = sum(r.failed for r in results.values())
    total_processed = sum(r.total for r in results.values())

    # Emit WebSocket event
    emit_queue_processed(
        total=total_processed,
        completed=total_completed,
        failed=total_failed,
    )

    # Format results for response
    results_dict = {}
    for account_id, result in results.items():
        results_dict[str(account_id)] = {
            "total": result.total,
            "completed": result.completed,
            "failed": result.failed,
            "errors": result.errors,
        }

    logger.info(
        f"Queue processing complete: {total_completed} completed, {total_failed} failed"
    )

    return jsonify({
        "success": True,
        "message": f"Processed {total_processed} actions",
        "summary": {
            "total": total_processed,
            "completed": total_completed,
            "failed": total_failed,
        },
        "results": results_dict,
    }), 200
