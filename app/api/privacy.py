"""Privacy lifecycle endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import logging
from typing import Any
from uuid import uuid4

from flask import Blueprint, g, jsonify, request
from sqlalchemy import select

from app.db.database import get_db_session
from app.db.models import LegalConsent

privacy_bp = Blueprint("privacy", __name__)
logger = logging.getLogger(__name__)

_LEGAL_TERMS_VERSION = "2026-05-30"
_LEGAL_PRIVACY_VERSION = "2026-05-30"
_CONSENT_PROVIDERS = {"gmail", "outlook"}

_EXPORT_EXCLUDED_COLUMNS = {
    "access_token",
    "refresh_token",
    "token_expires_at",
    "body_text",
    "body_html",
    "snippet",
    "raw_headers",
    "generation_prompt",
    "user_edits",
    "feedback_notes",
    "email_body",
    "draft_body",
    "draft_v1",
    "critique",
    "draft_final",
    "conversation_history",
    "pipeline_summary",
}


def _json_export_value(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (bytes, bytearray)):
        return f"<{len(value)} bytes redacted>"
    return value


def _export_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _json_export_value(value)
        for key, value in row.items()
        if key not in _EXPORT_EXCLUDED_COLUMNS
    }


def _client_ip() -> str | None:
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()[:45] or None
    return (request.remote_addr or "").strip()[:45] or None


def _clean_version(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    if not text:
        return fallback
    return text[:64]


def _auth_user_id() -> int | None:
    auth_user = getattr(g, "auth_user", None)
    if not isinstance(auth_user, dict):
        return None
    try:
        return int(auth_user.get("id"))
    except (TypeError, ValueError):
        return None


def _build_account_export(db_account_id: int, public_account_id: str) -> dict[str, Any]:
    from app.db.models import Base
    from app.email_content_storage import get_email_content_storage_mode

    tables: dict[str, list[dict[str, Any]]] = {}
    with get_db_session() as session:
        for table in Base.metadata.sorted_tables:
            column_names = table.c.keys()
            if table.name == "accounts":
                stmt = select(table).where(table.c.id == db_account_id)
            elif "account_id" in column_names:
                stmt = select(table).where(table.c.account_id == db_account_id)
            else:
                continue

            rows = [_export_row(dict(row._mapping)) for row in session.execute(stmt)]
            if rows:
                tables[table.name] = rows

    return {
        "account_id": public_account_id,
        "db_account_id": db_account_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "storage_mode": get_email_content_storage_mode(),
        "content_omitted": sorted(_EXPORT_EXCLUDED_COLUMNS),
        "tables": tables,
    }


@privacy_bp.route("/consents", methods=["POST"])
def record_legal_consent():
    """Record explicit legal consent before starting an OAuth flow."""
    from app.api.routes_helpers import _rate_limited

    ip_address = _client_ip()
    allowed, retry_after = _rate_limited(
        f"legal_consent:{ip_address or 'unknown'}",
        max_calls=20,
        window_seconds=60,
    )
    if not allowed:
        return jsonify({"error": "rate limit exceeded", "retry_after": retry_after}), 429

    data = request.get_json(silent=True) or {}
    if data.get("accepted") is not True:
        return jsonify({
            "error": "Consent is required",
            "code": "CONSENT_REQUIRED",
        }), 400

    provider = str(data.get("provider") or "").strip().lower()
    if provider not in _CONSENT_PROVIDERS:
        return jsonify({
            "error": "Unsupported provider",
            "code": "UNSUPPORTED_PROVIDER",
        }), 400

    account_id: int | None = None
    if data.get("account_id") is not None:
        try:
            account_id = int(data["account_id"])
        except (TypeError, ValueError):
            return jsonify({
                "error": "Invalid account_id",
                "code": "INVALID_ACCOUNT_ID",
            }), 400

    consent_id = str(uuid4())
    accepted_at = datetime.now(timezone.utc)
    consent = LegalConsent(
        id=consent_id,
        provider=provider,
        terms_version=_clean_version(data.get("terms_version"), _LEGAL_TERMS_VERSION),
        privacy_version=_clean_version(data.get("privacy_version"), _LEGAL_PRIVACY_VERSION),
        accepted_at=accepted_at,
        ip_address=ip_address,
        user_agent=(request.headers.get("User-Agent") or "").strip()[:512] or None,
        account_id=account_id,
        user_id=_auth_user_id(),
    )

    try:
        with get_db_session() as session:
            session.add(consent)
    except Exception:
        logger.exception("Failed to record legal consent")
        return jsonify({
            "error": "Consent could not be recorded",
            "code": "CONSENT_RECORD_FAILED",
        }), 500

    return jsonify({
        "success": True,
        "consent_id": consent_id,
        "accepted_at": accepted_at.isoformat(),
    }), 201


@privacy_bp.route("/accounts/<account_id>/data", methods=["GET"])
def export_account_data(account_id: str):
    """Export Agentys-side stored data for an email account."""
    from app.api.onboarding import _resolve_db_account_id

    try:
        db_account_id = _resolve_db_account_id(account_id)
    except PermissionError:
        return jsonify({"error": "Forbidden", "code": "FORBIDDEN"}), 403
    except Exception:
        return jsonify({"error": "Account not found", "code": "ACCOUNT_NOT_FOUND"}), 404

    return jsonify(_build_account_export(db_account_id, account_id))


@privacy_bp.route("/accounts/<account_id>/data", methods=["DELETE"])
def delete_account_data(account_id: str):
    """Delete all Agentys-side data for an email account."""
    data = request.get_json(silent=True) or {}
    if data.get("confirm") not in ("DELETE", account_id):
        return jsonify({
            "error": "Confirmation required",
            "code": "CONFIRMATION_REQUIRED",
        }), 400

    from app.api.accounts import delete_account

    return delete_account(account_id)
