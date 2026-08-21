# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""REST endpoints for the schedule-send feature.

Routes (registered under `/api/emails`):
    POST   /schedule              — create a scheduled send
    GET    /scheduled             — list pending sends for the current account
    DELETE /scheduled/<id>        — cancel a scheduled send
    PATCH  /scheduled/<id>        — edit send_at / subject / body / recipients
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request

from app.api.utils.errors import error_response
from app.api.routes_helpers import (
    _get_current_account_for_user,
    _rate_limited,
    _resolve_account_id_cached,
)
from app.api.websocket import (
    emit_email_schedule_canceled,
    emit_email_schedule_updated,
    emit_email_scheduled,
)
from app.services.scheduled_email_store import (
    ScheduledEmailStore,
    get_default_store,
)

logger = logging.getLogger(__name__)


scheduled_emails_bp = Blueprint("scheduled_emails", __name__)


# ── Helpers ────────────────────────────────────────────────────────────────


def _store() -> ScheduledEmailStore:
    return get_default_store()


def _parse_iso(s: str) -> datetime | None:
    if not isinstance(s, str) or not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _validate_to(raw) -> list[str] | None:
    """Accept str (comma/semicolon separated) or list[str]; require an `@` and a `.`."""
    if isinstance(raw, list):
        addrs = [str(a).strip() for a in raw if str(a).strip()]
    elif isinstance(raw, str):
        addrs = [a.strip() for a in raw.replace(";", ",").split(",") if a.strip()]
    else:
        return None
    if not addrs or not all("@" in a and "." in a.split("@", 1)[-1] for a in addrs):
        return None
    return addrs


def _split_csv(raw) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(a).strip() for a in raw if str(a).strip()]
    return [a.strip() for a in str(raw).split(",") if a.strip()]


# FIX EMAIL-005 (audit P1): cap total decoded attachment size to match the
# 25 MiB limit already enforced in routes_emails.py:4497 for live sends.
# Without this, a single user could enqueue an arbitrary number of multi-
# hundred-MB rows, fill the SQLite payload column on the shared volume, and
# OOM the scheduler when it materializes attachments for a tick batch.
MAX_TOTAL_ATTACHMENT_SIZE = 25 * 1024 * 1024  # 25 MiB decoded


class AttachmentTooLargeError(ValueError):
    """Raised when serialized attachments exceed MAX_TOTAL_ATTACHMENT_SIZE."""


def _serialize_attachments(raw_attachments) -> list[dict]:
    if not raw_attachments:
        return []
    import base64 as _b64
    out: list[dict] = []
    total_bytes = 0
    for att in raw_attachments:
        b64 = str(att.get("data") or "")
        try:
            decoded_len = len(_b64.b64decode(b64, validate=False)) if b64 else 0
        except Exception:
            raise AttachmentTooLargeError(
                f"Pièce jointe '{att.get('filename', '?')}' invalide (base64 illisible)"
            )
        total_bytes += decoded_len
        if total_bytes > MAX_TOTAL_ATTACHMENT_SIZE:
            raise AttachmentTooLargeError(
                f"Taille totale des pièces jointes dépasse "
                f"{MAX_TOTAL_ATTACHMENT_SIZE // (1024 * 1024)} MiB"
            )
        out.append(
            {
                "filename": str(att.get("filename") or "file"),
                "data": b64,
                "content_type": str(
                    att.get("content_type") or "application/octet-stream"
                ),
            }
        )
    return out


def _row_to_dict_for_api(row: dict) -> dict:
    p = row.get("payload") or {}
    return {
        "id": row["id"],
        "send_at": row["send_at"].isoformat() if row.get("send_at") else None,
        "status": row.get("status"),
        "to": p.get("to") or [],
        "cc": p.get("cc") or [],
        "bcc": p.get("bcc") or [],
        "subject": p.get("subject") or "",
        "body": p.get("body") or "",
        "is_html": bool(p.get("is_html", False)),
        "reply_to_id": p.get("reply_to_id"),
        "thread_id": p.get("thread_id"),
        "attachments_count": len(p.get("attachments") or []),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
        "sent_at": row["sent_at"].isoformat() if row.get("sent_at") else None,
        "sent_message_id": row.get("sent_message_id"),
        "error": row.get("error"),
    }


def _validate_send_at(raw: str | None) -> tuple[datetime | None, str | None]:
    """Return (parsed datetime, error_message). 60s clock-skew margin tolerated."""
    parsed = _parse_iso(raw or "")
    if parsed is None:
        return None, "send_at est requis et doit être au format ISO 8601"
    now = datetime.now(timezone.utc)
    if parsed < now - timedelta(seconds=60):
        return None, "send_at doit être dans le futur"
    if parsed > now + timedelta(days=365):
        return None, "send_at est trop loin dans le futur (max 1 an)"
    return parsed, None


# ── Routes ─────────────────────────────────────────────────────────────────


@scheduled_emails_bp.route("/schedule", methods=["POST"])
def create_scheduled_email():
    # Per-tenant bucket (H-8 follow-up #534).
    try:
        _aid = _resolve_account_id_cached()
    except Exception:
        _aid = "anonymous"
    allowed, retry_after = _rate_limited(f"schedule_email:{_aid}", max_calls=20, window_seconds=60)
    if not allowed:
        return error_response(
            "SCHEDULED_TOO_MANY_SCHEDULES",
            "Too many schedules, try again later",
            429,
            extra={"retry_after": retry_after},
        )

    data = request.get_json(silent=True) or {}

    to_list = _validate_to(data.get("to"))
    if not to_list:
        # Audit regressions (2026-05-18 batch5) F-10: migrate to error_code so
        # the FE renders the localized errors.json message instead of the
        # hardcoded French string.
        return error_response("TO_INVALID_OR_MISSING", "Recipient address invalid or missing", 400)

    cc_list = _split_csv(data.get("cc"))
    bcc_list = _split_csv(data.get("bcc"))
    for addr in cc_list + bcc_list:
        if "@" not in addr or "." not in addr.split("@", 1)[-1]:
            return error_response(
                "RECIPIENT_INVALID",
                f"Invalid address: {addr}",
                400,
                context={"address": addr},
            )

    subject = (data.get("subject") or "").strip()
    body = (data.get("body") or "").strip()
    if not body:
        return error_response("BODY_REQUIRED", "Message body is required", 400)
    if len(subject) > 998:
        return error_response("SUBJECT_TOO_LONG", "Subject too long (max 998 characters)", 400)

    send_at, err = _validate_send_at(data.get("send_at"))
    if err is not None:
        return jsonify({"error": err}), 400

    account = _get_current_account_for_user()
    if account is None:
        return error_response("NO_AUTHENTICATED_ACCOUNT", "No authenticated account", 401)
    account_id = _resolve_account_id_cached()
    # SECURITY (deep audit 2026-06-02 E): the None-gate above resolves the account
    # via multi_accounts, but account_id comes from the DB resolver; the two
    # diverge when the DB row is missing / a lookup errors (-1 sentinel). Reject
    # <=0 so a divergent caller can't insert under the shared account_id=-1 bucket
    # (cross-tenant pooling + the row never sends — _load_account(-1) is None).
    if not isinstance(account_id, int) or account_id <= 0:
        return error_response("NO_AUTHENTICATED_ACCOUNT", "No authenticated account", 401)

    try:
        serialized_attachments = _serialize_attachments(data.get("attachments"))
    except AttachmentTooLargeError as e:
        return jsonify({"error": str(e)}), 413

    payload = {
        "to": to_list,
        "subject": subject,
        "body": body,
        "cc": cc_list,
        "bcc": bcc_list,
        "is_html": bool(data.get("is_html", False)),
        "reply_to_id": (data.get("reply_to_id") or None),
        "thread_id": (data.get("thread_id") or None),
        "attachments": serialized_attachments,
        "skip_signature": bool(data.get("skip_signature", False)),
        "signature_html": (data.get("signature_html") or ""),
        "ai_assisted": bool(data.get("ai_assisted", False)),
        "from_name": (data.get("from_name") or None),
    }

    sched_id = _store().insert(account_id=account_id, payload=payload, send_at=send_at)

    try:
        emit_email_scheduled(
            sched_id, send_at=send_at.isoformat(), account_id=account_id
        )
    except Exception:
        logger.exception("emit_email_scheduled failed")

    return (
        jsonify(
            {
                "scheduled_id": sched_id,
                "status": "pending",
                "send_at": send_at.isoformat(),
            }
        ),
        201,
    )


@scheduled_emails_bp.route("/scheduled", methods=["GET"])
def list_scheduled_emails():
    # BUG-J002 fix: wrap in try/except so DB init or query failures never
    # propagate as unhandled exceptions (which Flask would render as 500,
    # possibly misread by the frontend network tracker as 404).
    try:
        account = _get_current_account_for_user()
        if account is None:
            return jsonify({"items": [], "count": 0}), 200
        account_id = _resolve_account_id_cached()
        # SECURITY (deep audit 2026-06-02 E): don't query the shared account_id=-1
        # bucket when the DB resolver diverges from the multi_accounts None-gate —
        # return empty (consistent with the account-None branch) rather than leak
        # another tenant's pending sends.
        if not isinstance(account_id, int) or account_id <= 0:
            return jsonify({"items": [], "count": 0}), 200

        statuses = request.args.get("status", "pending").split(",")
        statuses = [s.strip() for s in statuses if s.strip()]
        rows = _store().list_by_account(
            account_id=account_id,
            statuses=tuple(statuses) if statuses else ("pending",),
        )
        items = [_row_to_dict_for_api(r) for r in rows]
        return jsonify({"items": items, "count": len(items)}), 200
    except Exception as exc:
        logger.warning("list_scheduled_emails error: %s", exc, exc_info=True)
        # Deep audit 2026-06-02 U (BS-01): distinguish "broken store" from "no
        # scheduled emails". Keep HTTP 200 — a 5xx would trip the apiClient's
        # connection-lost interceptor (api.ts: 502/503/504 → retry + offline
        # banner), the very reason BUG-J002 moved off 500. The `degraded` flag
        # lets the FE show a retry banner instead of silently rendering an empty
        # list as success.
        return jsonify({"items": [], "count": 0, "degraded": True}), 200


@scheduled_emails_bp.route("/scheduled/<sched_id>", methods=["DELETE"])
def cancel_scheduled_email(sched_id: str):
    # Per-tenant bucket (H-8 follow-up #534).
    try:
        _aid = _resolve_account_id_cached()
    except Exception:
        _aid = "anonymous"
    allowed, retry_after = _rate_limited(f"schedule_cancel:{_aid}", max_calls=30, window_seconds=60)
    if not allowed:
        return error_response(
            "SCHEDULED_TOO_MANY_CANCELS",
            "Too many cancellations, try again later",
            429,
            extra={"retry_after": retry_after},
        )

    account = _get_current_account_for_user()
    if account is None:
        return error_response("NO_AUTHENTICATED_ACCOUNT", "No authenticated account", 401)
    account_id = _resolve_account_id_cached()
    # SECURITY (deep audit 2026-06-02 E): reject the -1 sentinel (DB resolver vs
    # multi_accounts None-gate divergence) so a divergent caller can't cancel
    # another tenant's send in the shared account_id=-1 bucket.
    if not isinstance(account_id, int) or account_id <= 0:
        return error_response("NO_AUTHENTICATED_ACCOUNT", "No authenticated account", 401)

    row = _store().get_by_id(sched_id, account_id=account_id)
    if row is None:
        return error_response("SCHEDULE_NOT_FOUND", "Scheduled email not found", 404)
    if row["status"] != "pending":
        # Audit regressions (2026-05-18 batch5) F-10: mirror the SCHEDULED_
        # STATUS_NOT_EDITABLE migration; context={"status": ...} feeds the
        # i18n template `Status {{status}}: cannot cancel`.
        return error_response(
            "SCHEDULED_STATUS_NOT_CANCELABLE",
            f"Status {row['status']}: cannot cancel",
            409,
            context={"status": row["status"]},
        )

    if not _store().cancel(sched_id, account_id=account_id):
        # Race : another caller transitioned the row between our check and the
        # update. Treat as a conflict so the frontend can refresh.
        return error_response("SCHEDULED_CANCEL_REJECTED", "Cancellation rejected", 409)

    try:
        emit_email_schedule_canceled(sched_id, account_id=account_id)
    except Exception:
        logger.exception("emit_email_schedule_canceled failed")

    return jsonify({"success": True, "scheduled_id": sched_id}), 200


@scheduled_emails_bp.route("/scheduled/<sched_id>", methods=["PATCH"])
def patch_scheduled_email(sched_id: str):
    # Per-tenant bucket (H-8 follow-up #534).
    try:
        _aid = _resolve_account_id_cached()
    except Exception:
        _aid = "anonymous"
    allowed, retry_after = _rate_limited(f"schedule_patch:{_aid}", max_calls=30, window_seconds=60)
    if not allowed:
        return error_response(
            "SCHEDULED_TOO_MANY_UPDATES",
            "Too many updates, try again later",
            429,
            extra={"retry_after": retry_after},
        )

    account = _get_current_account_for_user()
    if account is None:
        return error_response("NO_AUTHENTICATED_ACCOUNT", "No authenticated account", 401)
    account_id = _resolve_account_id_cached()
    # SECURITY (deep audit 2026-06-02 E): reject the -1 sentinel (DB resolver vs
    # multi_accounts None-gate divergence) so a divergent caller can't edit
    # another tenant's send in the shared account_id=-1 bucket.
    if not isinstance(account_id, int) or account_id <= 0:
        return error_response("NO_AUTHENTICATED_ACCOUNT", "No authenticated account", 401)

    row = _store().get_by_id(sched_id, account_id=account_id)
    if row is None:
        return error_response("SCHEDULE_NOT_FOUND", "Scheduled email not found", 404)
    if row["status"] != "pending":
        return error_response(
            "SCHEDULED_STATUS_NOT_EDITABLE",
            f"Status {row['status']}: not editable",
            409,
            context={"status": row["status"]},
        )

    data = request.get_json(silent=True) or {}
    new_send_at_iso: str | None = None
    payload_changed = False

    if "send_at" in data:
        new_at, err = _validate_send_at(data.get("send_at"))
        if err is not None:
            return jsonify({"error": err}), 400
        if not _store().update_send_at(sched_id, new_send_at=new_at, account_id=account_id):
            return error_response("SCHEDULED_UPDATE_REJECTED", "Update rejected", 409)
        new_send_at_iso = new_at.isoformat()

    payload_keys = ("subject", "body", "to", "cc", "bcc", "is_html", "attachments", "from_name", "signature_html")
    payload_updates = {k: data[k] for k in payload_keys if k in data}
    if payload_updates:
        new_payload = dict(row["payload"])
        if "to" in payload_updates:
            to_list = _validate_to(payload_updates["to"])
            if not to_list:
                return error_response("TO_INVALID", "Recipient address invalid", 400)
            new_payload["to"] = to_list
        if "cc" in payload_updates:
            new_payload["cc"] = _split_csv(payload_updates["cc"])
        if "bcc" in payload_updates:
            new_payload["bcc"] = _split_csv(payload_updates["bcc"])
        if "subject" in payload_updates:
            new_payload["subject"] = (payload_updates["subject"] or "").strip()
        if "body" in payload_updates:
            body = (payload_updates["body"] or "").strip()
            if not body:
                return error_response("BODY_REQUIRED", "Message body is required", 400)
            new_payload["body"] = body
        if "is_html" in payload_updates:
            new_payload["is_html"] = bool(payload_updates["is_html"])
        if "attachments" in payload_updates:
            try:
                new_payload["attachments"] = _serialize_attachments(
                    payload_updates["attachments"]
                )
            except AttachmentTooLargeError as e:
                return jsonify({"error": str(e)}), 413
        if "from_name" in payload_updates:
            new_payload["from_name"] = (payload_updates["from_name"] or None)
        if "signature_html" in payload_updates:
            new_payload["signature_html"] = (payload_updates["signature_html"] or "")
        if not _store().update_payload(sched_id, new_payload=new_payload, account_id=account_id):
            return error_response("SCHEDULED_UPDATE_REJECTED", "Update rejected", 409)
        payload_changed = True

    if new_send_at_iso is None and not payload_changed:
        return error_response("SCHEDULED_NOTHING_TO_UPDATE", "Nothing to update", 400)

    refreshed = _store().get_by_id(sched_id, account_id=account_id)
    try:
        emit_email_schedule_updated(
            sched_id,
            send_at=(refreshed["send_at"].isoformat() if refreshed and refreshed.get("send_at") else ""),
            account_id=account_id,
        )
    except Exception:
        logger.exception("emit_email_schedule_updated failed")

    return jsonify({"success": True, "scheduled": _row_to_dict_for_api(refreshed)}), 200


@scheduled_emails_bp.route("/scheduled/<sched_id>/send-now", methods=["POST"])
def send_scheduled_now(sched_id: str):
    """Override the schedule and dispatch the email immediately.

    The user already authored the message; this just bypasses the future
    send_at and runs the regular dispatch synchronously so they get an
    answer in a few seconds instead of waiting for the 60s poll.
    """
    try:
        _aid = _resolve_account_id_cached()
    except Exception:
        _aid = "anonymous"
    allowed, retry_after = _rate_limited(
        f"schedule_send_now:{_aid}", max_calls=20, window_seconds=60
    )
    if not allowed:
        return error_response(
            "SCHEDULED_TOO_MANY_IMMEDIATE_SENDS",
            "Too many immediate sends, try again later",
            429,
            extra={"retry_after": retry_after},
        )

    account = _get_current_account_for_user()
    if account is None:
        return error_response("NO_AUTHENTICATED_ACCOUNT", "No authenticated account", 401)
    account_id = _resolve_account_id_cached()

    row = _store().get_by_id(sched_id, account_id=account_id)
    if row is None:
        return error_response("SCHEDULE_NOT_FOUND", "Scheduled email not found", 404)
    if row["status"] != "pending":
        return error_response(
            "SCHEDULED_STATUS_NOT_SENDABLE",
            f"Status {row['status']}: cannot send",
            409,
            context={"status": row["status"]},
        )

    from app.services.scheduled_email_scheduler import get_default_scheduler

    success, err = get_default_scheduler().dispatch_now(
        sched_id, account_id=int(account_id)
    )
    if not success:
        return error_response(
            "SCHEDULED_SEND_FAILED",
            err or "Send failed",
            502,
        )

    refreshed = _store().get_by_id(sched_id, account_id=account_id)
    return (
        jsonify({"success": True, "scheduled": _row_to_dict_for_api(refreshed)}),
        200,
    )
