"""Ambassador / referral program API.

- POST /api/ambassador/activate                       (user authentifié)
- GET  /api/ambassador/admin/commissions              (admin : agrégat dû)
- POST /api/ambassador/admin/commissions/mark-paid    (admin : versement manuel)

Réutilise les helpers Stripe/auth éprouvés de ``app.api.billing`` ; la logique
métier vit dans ``app.billing.ambassador``.
"""

from __future__ import annotations

import logging
import os

from flask import Blueprint, jsonify, request

from app.api.admin import require_admin_or_token
from app.api.billing import (
    BillingConfigError,
    _current_user_or_none,
    _get_stripe,
    _stripe_error_response,
)
from app.api.utils.errors import error_response
from app.billing.ambassador import (
    activate_ambassador,
    admin_commission_summary,
    mark_commissions_paid,
)
from app.db.database import get_db_session

logger = logging.getLogger(__name__)

ambassador_bp = Blueprint("ambassador", __name__)

_DEFAULT_SIGNUP_URL = "https://agentys.app/signup"


def _referral_link(code: str) -> str:
    base = (os.environ.get("AMBASSADOR_SIGNUP_URL", "").strip() or _DEFAULT_SIGNUP_URL)
    separator = "&" if "?" in base else "?"
    return f"{base}{separator}ref={code}"


@ambassador_bp.route("/ambassador/activate", methods=["POST"])
def activate():
    user = _current_user_or_none()
    if user is None:
        return error_response("NOT_AUTHENTICATED", "Not authenticated", 401)

    try:
        stripe = _get_stripe()
    except BillingConfigError as exc:
        return error_response("BILLING_NOT_CONFIGURED", str(exc), 503)

    user_id = int(user["id"])
    email = str(user.get("email") or "")
    try:
        with get_db_session() as session:
            ambassador = activate_ambassador(session, stripe, user_id=user_id, email=email)
            code = ambassador.code
            status = ambassador.status
    except Exception as exc:
        stripe_response = _stripe_error_response(stripe, exc, operation="ambassador_activate")
        if stripe_response is not None:
            return stripe_response
        raise

    return jsonify({"code": code, "status": status, "referral_link": _referral_link(code)})


@ambassador_bp.route("/ambassador/admin/commissions", methods=["GET"])
@require_admin_or_token
def admin_commissions():
    with get_db_session() as session:
        rows = admin_commission_summary(session)
    return jsonify({"ambassadors": rows})


@ambassador_bp.route("/ambassador/admin/commissions/mark-paid", methods=["POST"])
@require_admin_or_token
def admin_mark_paid():
    payload = request.get_json(silent=True) or {}
    ids = payload.get("commission_ids") or []
    if not isinstance(ids, list) or not all(
        isinstance(i, int) and not isinstance(i, bool) for i in ids
    ):
        return error_response(
            "INVALID_PAYLOAD", "commission_ids must be a list of integers", 400
        )
    with get_db_session() as session:
        updated = mark_commissions_paid(session, ids)
    return jsonify({"updated": updated})
