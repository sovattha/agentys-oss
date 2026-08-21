# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""HTTP API for the bulk-action queue.

All endpoints are scoped by the authenticated user except in Tauri
loopback mode, where the desktop is single-tenant and the worker writes
`user_id = NULL` on jobs. Loopback callers therefore see every job in
the local DB.

The worker (`app.services.bulk_jobs.worker`) does the heavy lifting;
these endpoints only mutate state via `BulkJobRepository`. A POST that
flips a job's status returns the *new* state of the job so the frontend
doesn't need a follow-up GET — saves one round-trip on every action.
"""
from __future__ import annotations

import logging
from typing import Any

from flask import jsonify, request

from app.api._auth_helpers import get_auth_user_id
from app.api.routes_helpers import api_bp
from app.db.database import get_db_session
from app.db.models.bulk_job import (
    JOB_STATUS_FAILED,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    JOB_STATUS_PAUSED,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_CANCELLED,
)
from app.services.bulk_jobs.repository import BulkJobRepository

logger = logging.getLogger(__name__)


# Allowed query-string filter values, kept tight so a typo gives 400
# rather than a silently-empty result.
_ALLOWED_STATUS_FILTERS = frozenset(
    {
        JOB_STATUS_QUEUED,
        JOB_STATUS_RUNNING,
        JOB_STATUS_PAUSED,
        JOB_STATUS_COMPLETED,
        JOB_STATUS_FAILED,
        JOB_STATUS_CANCELLED,
    }
)
_ALLOWED_ITEM_STATE_FILTERS = frozenset(
    {"pending", "in_progress", "succeeded", "failed", "skipped"}
)
_DEFAULT_LIST_LIMIT = 50
_MAX_LIST_LIMIT = 200
_DEFAULT_ITEMS_LIMIT = 100
_MAX_ITEMS_LIMIT = 500


# ── helpers ─────────────────────────────────────────────────────────────
def _ownership_violation(job: dict[str, Any] | None) -> bool:
    """Return True if the JWT caller is not allowed to see this job.

    In Tauri loopback mode (`get_auth_user_id() is None`), we skip the
    check — there is only ever one user on the device. Otherwise we
    require the job's `user_id` to match the JWT subject. A job with
    `user_id IS NULL` (legacy / scheduler-created) is intentionally
    *not* visible to a JWT user, because we can't prove tenancy.
    """
    if job is None:
        return False
    requester = get_auth_user_id()
    if requester is None:
        return False
    return job.get("user_id") != requester


def _parse_int(value: str | None, default: int, *, low: int, high: int) -> int:
    """Clamp a query-string int into [low, high]; default on missing/bad."""
    if value is None:
        return default
    try:
        n = int(value)
    except ValueError:
        return default
    return max(low, min(high, n))


# ── GET /api/bulk-jobs ──────────────────────────────────────────────────
@api_bp.route("/bulk-jobs", methods=["GET"])
def list_bulk_jobs():
    """List recent bulk jobs for the authenticated user (or all in loopback).

    Query params:
        status  — optional filter; one of queued|running|paused|completed|failed|cancelled
        since   — optional ISO-8601 lower bound on `created_at` (string compare,
                  matches the storage format `YYYY-MM-DDTHH:MM:SSZ`)
        limit   — 1..200, default 50
    """
    status_filter = request.args.get("status")
    if status_filter and status_filter not in _ALLOWED_STATUS_FILTERS:
        return jsonify({"error": f"invalid status filter {status_filter!r}"}), 400

    since = request.args.get("since")
    limit = _parse_int(
        request.args.get("limit"),
        _DEFAULT_LIST_LIMIT,
        low=1,
        high=_MAX_LIST_LIMIT,
    )

    user_id = get_auth_user_id()
    with get_db_session() as session:
        repo = BulkJobRepository(session)
        jobs = repo.list_jobs_for_user(
            user_id=user_id,
            status=status_filter,
            since_iso=since,
            limit=limit,
        )
    return jsonify({"jobs": jobs}), 200


# ── GET /api/bulk-jobs/<id> ────────────────────────────────────────────
@api_bp.route("/bulk-jobs/<job_id>", methods=["GET"])
def get_bulk_job(job_id: str):
    with get_db_session() as session:
        repo = BulkJobRepository(session)
        job = repo.get_job(job_id)
    if job is None:
        return jsonify({"error": "not found"}), 404
    if _ownership_violation(job):
        # Indistinguishable from "not found" — never leak existence to a
        # different user.
        return jsonify({"error": "not found"}), 404
    return jsonify({"job": job}), 200


# ── GET /api/bulk-jobs/<id>/items ──────────────────────────────────────
@api_bp.route("/bulk-jobs/<job_id>/items", methods=["GET"])
def list_bulk_job_items(job_id: str):
    """List items for a job (defaults to failed items so the UI can drill
    straight into the rows the user cares about)."""
    state = request.args.get("state", "failed")
    if state not in _ALLOWED_ITEM_STATE_FILTERS:
        return jsonify({"error": f"invalid state {state!r}"}), 400
    limit = _parse_int(
        request.args.get("limit"),
        _DEFAULT_ITEMS_LIMIT,
        low=1,
        high=_MAX_ITEMS_LIMIT,
    )
    with get_db_session() as session:
        repo = BulkJobRepository(session)
        job = repo.get_job(job_id)
        if job is None:
            return jsonify({"error": "not found"}), 404
        if _ownership_violation(job):
            return jsonify({"error": "not found"}), 404
        items = repo.list_items(job_id, state=state, limit=limit)
    return jsonify({"job_id": job_id, "state": state, "items": items}), 200


# ── POST /api/bulk-jobs/<id>/pause ─────────────────────────────────────
@api_bp.route("/bulk-jobs/<job_id>/pause", methods=["POST"])
def pause_bulk_job(job_id: str):
    return _flip_status(job_id, action="pause")


# ── POST /api/bulk-jobs/<id>/resume ────────────────────────────────────
@api_bp.route("/bulk-jobs/<job_id>/resume", methods=["POST"])
def resume_bulk_job(job_id: str):
    return _flip_status(job_id, action="resume")


# ── POST /api/bulk-jobs/<id>/cancel ────────────────────────────────────
@api_bp.route("/bulk-jobs/<job_id>/cancel", methods=["POST"])
def cancel_bulk_job(job_id: str):
    return _flip_status(job_id, action="cancel")


# ── POST /api/bulk-jobs/<id>/retry-failed ──────────────────────────────
@api_bp.route("/bulk-jobs/<job_id>/retry-failed", methods=["POST"])
def retry_bulk_job_failed(job_id: str):
    with get_db_session() as session:
        repo = BulkJobRepository(session)
        job = repo.get_job(job_id)
        if job is None:
            return jsonify({"error": "not found"}), 404
        if _ownership_violation(job):
            return jsonify({"error": "not found"}), 404
        requeued = repo.retry_failed(job_id)
        refreshed = repo.get_job(job_id)
    # Make sure the worker is awake to pick up the requeued items.
    if requeued:
        try:
            from app.services.bulk_jobs.worker import init_worker
            init_worker()
        except Exception:
            logger.exception("[bulk-jobs] failed to wake worker after retry")
    return jsonify({"job": refreshed, "requeued": requeued}), 200


# ── DELETE /api/bulk-jobs/<id> ─────────────────────────────────────────
@api_bp.route("/bulk-jobs/<job_id>", methods=["DELETE"])
def delete_bulk_job(job_id: str):
    """Dismiss (permanently remove) a terminal bulk job + its items.

    Lets the user clear a scary "248 failed" row that retry can't fix
    (e.g. a doomed scope job). Refuses to delete an active job (409) so
    we never orphan in-flight work.
    """
    with get_db_session() as session:
        repo = BulkJobRepository(session)
        job = repo.get_job(job_id)
        if job is None:
            return jsonify({"error": "not found"}), 404
        if _ownership_violation(job):
            return jsonify({"error": "not found"}), 404
        if job["status"] not in (
            JOB_STATUS_COMPLETED,
            JOB_STATUS_FAILED,
            JOB_STATUS_CANCELLED,
        ):
            return jsonify({"error": "job still active", "job": job}), 409
        deleted = repo.delete_job(job_id)
    return jsonify({"deleted": deleted}), 200


# ── shared status flip ─────────────────────────────────────────────────
def _flip_status(job_id: str, *, action: str):
    with get_db_session() as session:
        repo = BulkJobRepository(session)
        job = repo.get_job(job_id)
        if job is None:
            return jsonify({"error": "not found"}), 404
        if _ownership_violation(job):
            return jsonify({"error": "not found"}), 404

        if action == "pause":
            ok = repo.request_pause(job_id)
            error_409 = "job is not active"
        elif action == "resume":
            ok = repo.request_resume(job_id)
            error_409 = "job is not paused"
        elif action == "cancel":
            ok = repo.request_cancel(job_id)
            error_409 = "job already terminal"
        else:  # defensive: unreachable
            return jsonify({"error": "unknown action"}), 400

        if not ok:
            return jsonify({"error": error_409, "job": job}), 409

        refreshed = repo.get_job(job_id)

    # If we just resumed, kick the dispatcher so AccountQueue spawns
    # without waiting up to 1s for the next poll.
    if action == "resume":
        try:
            from app.services.bulk_jobs.worker import init_worker
            init_worker()
        except Exception:
            logger.exception("[bulk-jobs] failed to wake worker after resume")

    # Emit a status event so other tabs stay in sync.
    try:
        from app.api.websocket import emit_to_account
        if refreshed is not None:
            emit_to_account(
                "bulk_job_status",
                {"job_id": job_id, "status": refreshed["status"]},
                refreshed["account_id"],
            )
    except Exception:
        logger.debug("[bulk-jobs] could not emit status event", exc_info=True)

    return jsonify({"job": refreshed}), 200
