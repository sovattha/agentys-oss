"""Billing API — Stripe Checkout, Customer Portal, and entitlements."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlsplit

from flask import Blueprint, g, jsonify, request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.utils.errors import error_response
from app.billing.ambassador import attach_referral_from_checkout, record_commission_from_invoice
from app.billing.entitlements import BillingEntitlementService
from app.billing.stripe_sync import (
    find_user_id_for_customer,
    mark_customer_deleted,
    mark_subscription_canceled,
    object_get,
    resolve_user_id_from_stripe_object,
    sync_subscription_from_stripe,
    upsert_billing_customer,
)
from app.db.database import get_db_session
from app.db.models import BillingCustomer, BillingSubscription, StripeEvent


logger = logging.getLogger(__name__)

billing_bp = Blueprint("billing", __name__)


@billing_bp.route("/me", methods=["GET"])
def billing_me():
    user = _current_user_or_none()
    if user is None:
        return error_response("NOT_AUTHENTICATED", "Not authenticated", 401)
    user_id = int(user["id"])
    wants_fresh = _request_wants_fresh_billing()
    checkout_session_id = _request_checkout_session_id()
    if wants_fresh or checkout_session_id:
        try:
            with get_db_session() as session:
                if checkout_session_id:
                    _reconcile_checkout_session_from_stripe(
                        session,
                        user_id=user_id,
                        session_id=checkout_session_id,
                    )
                elif wants_fresh:
                    _reconcile_user_billing_from_stripe(session, user_id=user_id)
        except BillingSessionForbidden:
            return error_response(
                "BILLING_SESSION_FORBIDDEN",
                "Checkout session does not belong to the authenticated user",
                403,
            )
        except BillingConfigError as exc:
            if checkout_session_id:
                return error_response("BILLING_NOT_CONFIGURED", str(exc), 503)
            logger.info("[BILLING] Fresh billing reconciliation skipped: Stripe is not configured")
        except Exception as exc:
            stripe_response = _stripe_error_response(_get_stripe_safely(), exc, operation="billing-refresh")
            if stripe_response is not None:
                return stripe_response
            raise
    entitlement = BillingEntitlementService().get_for_user(user_id)
    return jsonify({"billing": entitlement.to_dict()})


@billing_bp.route("/usage", methods=["GET"])
def billing_usage():
    user = _current_user_or_none()
    if user is None:
        return error_response("NOT_AUTHENTICATED", "Not authenticated", 401)
    usage = BillingEntitlementService().get_credit_usage(int(user["id"]))
    return jsonify({"usage": usage})


@billing_bp.route("/checkout", methods=["POST"])
def create_checkout_session():
    user = _current_user_or_none()
    if user is None:
        return error_response("NOT_AUTHENTICATED", "Not authenticated", 401)

    payload = request.get_json(silent=True) or {}
    try:
        stripe = _get_stripe()
        plan = _normalize_plan(payload.get("plan"))
        interval = _normalize_interval(payload.get("interval"))
        price_id = _select_price_id(plan, interval)
        llm_overage_price_id = _select_llm_overage_price_id(plan, interval)
        return_origin = _request_return_origin(payload)
    except BillingConfigError as exc:
        # Surface the specific missing-config reason in the server logs. The FE
        # only renders a generic "Impossible d'ouvrir le paiement Stripe" banner,
        # so without this an ops misconfiguration — most commonly the
        # STRIPE_PRICE_<PLAN>_YEARLY price never being set, which silently breaks
        # ONLY annual checkout while monthly keeps working — is undiagnosable.
        # plan/interval may be unbound if _normalize_* raised, so read the raw
        # request values defensively for the log line.
        logger.warning(
            "[BILLING] Checkout not configured (plan=%r interval=%r): %s",
            payload.get("plan"), payload.get("interval"), exc,
        )
        return error_response("BILLING_NOT_CONFIGURED", str(exc), 503)

    user_id = int(user["id"])
    email = str(user.get("email") or "")
    checkout_metadata = {
        "agentys_user_id": str(user_id),
        "agentys_plan": plan,
        "agentys_interval": interval,
    }
    try:
        with get_db_session() as session:
            customer = session.execute(
                select(BillingCustomer).where(BillingCustomer.user_id == user_id)
            ).scalar_one_or_none()
            reused_stored_customer = customer is not None
            if customer is None:
                customer = _create_billing_customer(session, stripe, user_id=user_id, email=email)

            try:
                checkout = _create_stripe_checkout_session(
                    stripe,
                    customer_id=customer.stripe_customer_id,
                    user_id=user_id,
                    price_id=price_id,
                    llm_overage_price_id=llm_overage_price_id,
                    metadata=checkout_metadata,
                    success_url=_success_url(return_origin),
                    cancel_url=_cancel_url(return_origin),
                )
            except Exception as exc:
                if not reused_stored_customer or not _is_missing_stripe_customer_error(stripe, exc):
                    raise
                logger.warning(
                    "[BILLING] Stored Stripe customer missing; recreating before checkout for user %s",
                    user_id,
                    exc_info=True,
                )
                customer = _create_billing_customer(session, stripe, user_id=user_id, email=email)
                checkout = _create_stripe_checkout_session(
                    stripe,
                    customer_id=customer.stripe_customer_id,
                    user_id=user_id,
                    price_id=price_id,
                    llm_overage_price_id=llm_overage_price_id,
                    metadata=checkout_metadata,
                    success_url=_success_url(return_origin),
                    cancel_url=_cancel_url(return_origin),
                )
    except Exception as exc:
        stripe_response = _stripe_error_response(stripe, exc, operation="checkout")
        if stripe_response is not None:
            return stripe_response
        raise

    return jsonify({
        "session_id": object_get(checkout, "id"),
        "checkout_url": object_get(checkout, "url"),
        "plan": plan,
        "interval": interval,
        "usage_price_configured": bool(llm_overage_price_id),
    })


@billing_bp.route("/portal", methods=["POST"])
def create_portal_session():
    user = _current_user_or_none()
    if user is None:
        return error_response("NOT_AUTHENTICATED", "Not authenticated", 401)

    payload = request.get_json(silent=True) or {}
    return_origin = _request_return_origin(payload)

    try:
        stripe = _get_stripe()
    except BillingConfigError as exc:
        return error_response("BILLING_NOT_CONFIGURED", str(exc), 503)

    with get_db_session() as session:
        customer = session.execute(
            select(BillingCustomer).where(BillingCustomer.user_id == int(user["id"]))
        ).scalar_one_or_none()
        if customer is None:
            return error_response("BILLING_CUSTOMER_NOT_FOUND", "No billing customer found", 404)

        params = {
            "customer": customer.stripe_customer_id,
            "return_url": _portal_return_url(return_origin),
        }
        portal_configuration_id = os.environ.get("STRIPE_PORTAL_CONFIGURATION_ID", "").strip()
        if portal_configuration_id:
            params["configuration"] = portal_configuration_id
        try:
            portal = _create_stripe_portal_session(stripe, **params)
        except Exception as exc:
            if not portal_configuration_id or not _is_missing_stripe_portal_configuration_error(stripe, exc):
                stripe_response = _stripe_error_response(stripe, exc, operation="portal")
                if stripe_response is not None:
                    return stripe_response
                raise
            logger.warning(
                "[BILLING] Stored Stripe portal configuration missing; retrying with default configuration",
                exc_info=True,
            )
            params.pop("configuration", None)
            try:
                portal = _create_stripe_portal_session(stripe, **params)
            except Exception as retry_exc:
                stripe_response = _stripe_error_response(stripe, retry_exc, operation="portal")
                if stripe_response is not None:
                    return stripe_response
                raise

    return jsonify({"portal_url": object_get(portal, "url")})


@billing_bp.route("/subscription", methods=["GET"])
def billing_subscription_details():
    user = _current_user_or_none()
    if user is None:
        return error_response("NOT_AUTHENTICATED", "Not authenticated", 401)

    user_id = int(user["id"])
    if _request_wants_fresh_billing():
        try:
            with get_db_session() as session:
                _reconcile_user_billing_from_stripe(session, user_id=user_id)
        except BillingConfigError:
            logger.info("[BILLING] Subscription details reconciliation skipped: Stripe is not configured")
        except Exception as exc:
            stripe_response = _stripe_error_response(_get_stripe_safely(), exc, operation="subscription-details")
            if stripe_response is not None:
                return stripe_response
            raise

    with get_db_session() as session:
        subscription = _get_user_subscription(session, user_id)
        if subscription is None:
            return jsonify({"subscription": None})
        return jsonify({"subscription": _serialize_subscription_details(subscription)})


@billing_bp.route("/invoices", methods=["GET"])
def billing_invoices():
    user = _current_user_or_none()
    if user is None:
        return error_response("NOT_AUTHENTICATED", "Not authenticated", 401)

    user_id = int(user["id"])
    with get_db_session() as session:
        customer = session.execute(
            select(BillingCustomer).where(BillingCustomer.user_id == user_id)
        ).scalar_one_or_none()
        subscription = _get_user_subscription(session, user_id)
        if customer is None:
            return jsonify({"invoices": []})
        stripe_customer_id = str(customer.stripe_customer_id)
        stripe_subscription_id = (
            str(subscription.stripe_subscription_id)
            if subscription is not None and subscription.stripe_subscription_id
            else None
        )

    try:
        stripe = _get_stripe()
        params = {
            "customer": stripe_customer_id,
            "limit": _invoice_limit(),
        }
        if stripe_subscription_id:
            params["subscription"] = stripe_subscription_id
        invoices = stripe.Invoice.list(**params)
    except BillingConfigError as exc:
        return error_response("BILLING_NOT_CONFIGURED", str(exc), 503)
    except Exception as exc:
        stripe_response = _stripe_error_response(stripe, exc, operation="invoices")
        if stripe_response is not None:
            return stripe_response
        raise

    invoice_rows = object_get(invoices, "data", []) or []
    return jsonify({"invoices": [_serialize_invoice(invoice) for invoice in invoice_rows]})


@billing_bp.route("/stripe/webhook", methods=["POST"])
def stripe_webhook():
    try:
        stripe = _get_stripe()
        webhook_secret = _required_env("STRIPE_WEBHOOK_SECRET")
    except BillingConfigError as exc:
        return error_response("BILLING_NOT_CONFIGURED", str(exc), 503)

    payload = request.get_data(cache=False, as_text=False)
    signature = request.headers.get("Stripe-Signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, signature, webhook_secret)
    except Exception as exc:
        logger.warning("[BILLING] Stripe webhook signature rejected: %s", exc)
        return error_response("STRIPE_WEBHOOK_INVALID", "Invalid Stripe webhook signature", 400)

    event_id = str(object_get(event, "id", ""))
    event_type = str(object_get(event, "type", ""))
    event_object = object_get(object_get(event, "data", {}), "object", {})

    with get_db_session() as session:
        if session.get(StripeEvent, event_id) is not None:
            return jsonify({"received": True, "duplicate": True})

        _process_stripe_event(session, stripe, event_type, event_object)
        session.add(
            StripeEvent(
                id=event_id,
                event_type=event_type,
                processed_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )

    return jsonify({"received": True})


class BillingConfigError(RuntimeError):
    pass


class BillingSessionForbidden(RuntimeError):
    pass


def _stripe_error_response(stripe: Any, exc: Exception, *, operation: str):
    """Convert expected Stripe SDK failures into stable API responses."""
    stripe_error = getattr(getattr(stripe, "error", None), "StripeError", None)
    api_connection_error = getattr(getattr(stripe, "error", None), "APIConnectionError", None)
    rate_limit_error = getattr(getattr(stripe, "error", None), "RateLimitError", None)
    if stripe_error is None or not isinstance(exc, stripe_error):
        return None

    retryable = bool(
        (api_connection_error is not None and isinstance(exc, api_connection_error))
        or (rate_limit_error is not None and isinstance(exc, rate_limit_error))
    )
    logger.warning(
        "[BILLING] Stripe %s failed: %s",
        operation,
        exc,
        exc_info=True,
    )
    return error_response(
        "STRIPE_UNAVAILABLE",
        "Stripe is temporarily unavailable",
        503,
        extra={"retryable": retryable},
    )


def _current_user_or_none() -> Optional[dict]:
    user = getattr(g, "auth_user", None)
    return user if isinstance(user, dict) and user.get("id") else None


def _get_stripe():
    api_key = _required_env("STRIPE_SECRET_KEY")
    try:
        import stripe
    except ImportError as exc:  # pragma: no cover - dependency is pinned in requirements
        raise BillingConfigError("stripe SDK not installed") from exc
    stripe.api_key = api_key
    return stripe


def _get_stripe_safely():
    try:
        return _get_stripe()
    except BillingConfigError:
        return None


def _request_wants_fresh_billing() -> bool:
    value = str(request.args.get("fresh") or "").strip().lower()
    return value in {"1", "true", "yes"}


def _request_checkout_session_id() -> Optional[str]:
    value = str(request.args.get("session_id") or "").strip()
    return value or None


def _invoice_limit() -> int:
    try:
        value = int(str(request.args.get("limit") or "24"))
    except ValueError:
        return 24
    return max(1, min(value, 100))


def _get_user_subscription(session, user_id: int) -> Optional[BillingSubscription]:
    return session.execute(
        select(BillingSubscription).where(BillingSubscription.user_id == int(user_id))
    ).scalar_one_or_none()


def _reconcile_checkout_session_from_stripe(session, *, user_id: int, session_id: str) -> None:
    stripe = _get_stripe()
    checkout_session = stripe.checkout.Session.retrieve(str(session_id))
    resolved_user_id = resolve_user_id_from_stripe_object(session, checkout_session)
    if resolved_user_id is not None and int(resolved_user_id) != int(user_id):
        raise BillingSessionForbidden()
    if resolved_user_id is None:
        logger.warning("[BILLING] Checkout session without resolvable user_id: %s", session_id)
        return

    status = str(object_get(checkout_session, "status", "") or "").lower()
    payment_status = str(object_get(checkout_session, "payment_status", "") or "").lower()
    if status and status != "complete":
        logger.info("[BILLING] Checkout session is not complete yet: %s", session_id)
        return
    if payment_status and payment_status not in {"paid", "no_payment_required"}:
        logger.info("[BILLING] Checkout session payment is not complete yet: %s", session_id)
        return

    _sync_checkout_completed(session, stripe, checkout_session)


def _reconcile_user_billing_from_stripe(session, *, user_id: int) -> None:
    subscription = session.execute(
        select(BillingSubscription).where(BillingSubscription.user_id == int(user_id))
    ).scalar_one_or_none()
    if subscription is None or not subscription.stripe_subscription_id:
        return

    stripe = _get_stripe()
    try:
        stripe_subscription = stripe.Subscription.retrieve(
            str(subscription.stripe_subscription_id),
            expand=["items.data.price"],
        )
    except Exception as exc:
        if _is_missing_stripe_subscription_error(stripe, exc):
            logger.warning(
                "[BILLING] Stored Stripe subscription missing; marking local subscription canceled for user %s",
                user_id,
                exc_info=True,
            )
            mark_subscription_canceled(
                session,
                stripe_subscription_id=str(subscription.stripe_subscription_id),
            )
            return
        raise

    sync_subscription_from_stripe(session, user_id=user_id, subscription=stripe_subscription)


def _create_billing_customer(session, stripe: Any, *, user_id: int, email: str) -> BillingCustomer:
    stripe_customer = stripe.Customer.create(
        email=email,
        metadata={"agentys_user_id": str(user_id)},
    )
    return upsert_billing_customer(
        session,
        user_id=user_id,
        email=email,
        stripe_customer_id=str(object_get(stripe_customer, "id")),
    )


def _create_stripe_checkout_session(
    stripe: Any,
    *,
    customer_id: str,
    user_id: int,
    price_id: str,
    llm_overage_price_id: Optional[str],
    metadata: dict[str, str],
    success_url: str,
    cancel_url: str,
):
    line_items = [{"price": price_id, "quantity": 1}]
    subscription_metadata = dict(metadata)
    if llm_overage_price_id:
        line_items.append({"price": llm_overage_price_id})
        subscription_metadata["agentys_usage_billing"] = "enabled"
    trial_days = _checkout_trial_days()
    subscription_data: dict[str, Any] = {"metadata": subscription_metadata}
    if trial_days > 0:
        subscription_data["trial_period_days"] = trial_days
    return stripe.checkout.Session.create(
        mode="subscription",
        customer=customer_id,
        client_reference_id=str(user_id),
        line_items=line_items,
        success_url=success_url,
        cancel_url=cancel_url,
        metadata=metadata,
        subscription_data=subscription_data,
        # Permet au filleul de saisir le code ambassadeur (programme de
        # parrainage) ; sans ça, checkout.session.completed n'a jamais de
        # discount et le rattachement ne se déclenche pas.
        allow_promotion_codes=True,
    )


def _create_stripe_portal_session(stripe: Any, **params):
    return stripe.billing_portal.Session.create(**params)


def _serialize_subscription_details(subscription: BillingSubscription) -> dict[str, Any]:
    return {
        "subscription_id": subscription.stripe_subscription_id,
        "customer_id": subscription.stripe_customer_id,
        "price_id": subscription.stripe_price_id,
        "plan": subscription.plan or "free",
        "status": subscription.status or "free",
        "current_period_end": _serialize_dt(subscription.current_period_end),
        "cancel_at_period_end": bool(subscription.cancel_at_period_end),
    }


def _serialize_invoice(invoice: Any) -> dict[str, Any]:
    created = _datetime_from_stripe_ts(object_get(invoice, "created"))
    amount = object_get(invoice, "total")
    if amount is None:
        amount = object_get(invoice, "amount_paid")
    if amount is None:
        amount = object_get(invoice, "amount_due", 0)
    return {
        "id": str(object_get(invoice, "id", "")),
        "amount": int(amount or 0),
        "currency": str(object_get(invoice, "currency", "eur") or "eur"),
        "date": _serialize_dt(created),
        "status": str(object_get(invoice, "status", "open") or "open"),
        "invoice_pdf": object_get(invoice, "invoice_pdf"),
        "hosted_invoice_url": object_get(invoice, "hosted_invoice_url"),
        "description": (
            object_get(invoice, "description")
            or object_get(invoice, "number")
            or "Stripe invoice"
        ),
    }


def _serialize_dt(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _datetime_from_stripe_ts(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError, OSError):
        return None


def _is_missing_stripe_customer_error(stripe: Any, exc: Exception) -> bool:
    invalid_request_error = getattr(getattr(stripe, "error", None), "InvalidRequestError", None)
    if invalid_request_error is None or not isinstance(exc, invalid_request_error):
        return False
    if getattr(exc, "code", None) != "resource_missing":
        return False
    param = str(getattr(exc, "param", "") or "")
    message = str(exc).lower()
    return param == "customer" or "no such customer" in message


def _is_missing_stripe_subscription_error(stripe: Any, exc: Exception) -> bool:
    invalid_request_error = getattr(getattr(stripe, "error", None), "InvalidRequestError", None)
    if invalid_request_error is None or not isinstance(exc, invalid_request_error):
        return False
    if getattr(exc, "code", None) != "resource_missing":
        return False
    param = str(getattr(exc, "param", "") or "")
    message = str(exc).lower()
    return param == "subscription" or "no such subscription" in message


def _is_missing_stripe_portal_configuration_error(stripe: Any, exc: Exception) -> bool:
    invalid_request_error = getattr(getattr(stripe, "error", None), "InvalidRequestError", None)
    if invalid_request_error is None or not isinstance(exc, invalid_request_error):
        return False
    if getattr(exc, "code", None) != "resource_missing":
        return False
    param = str(getattr(exc, "param", "") or "")
    message = str(exc).lower()
    return param == "configuration" or "no such configuration" in message


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise BillingConfigError(f"{name} is missing")
    return value


def _normalize_plan(value: Any) -> str:
    normalized = str(value or "professional").strip().lower().replace("-", "_")
    aliases = {
        "pro": "professional",
        "professionnal": "professional",
        "professional": "professional",
        "starter": "starter",
    }
    plan = aliases.get(normalized)
    if plan is None:
        raise BillingConfigError("Unsupported billing plan")
    return plan


def _normalize_interval(value: Any) -> str:
    normalized = str(value or "monthly").strip().lower().replace("-", "_")
    if normalized in {"month", "monthly"}:
        return "monthly"
    if normalized in {"year", "yearly", "annual", "annually"}:
        return "yearly"
    raise BillingConfigError("Unsupported billing interval")


def _select_price_id(plan: Any, interval: Any) -> str:
    normalized_plan = _normalize_plan(plan)
    normalized_interval = _normalize_interval(interval)
    env_key = f"STRIPE_PRICE_{normalized_plan.upper()}_{normalized_interval.upper()}"
    price = os.environ.get(env_key, "").strip()
    if price:
        return price

    # Backward-compatible aliases from the first Pro-only implementation.
    if normalized_plan == "professional":
        alias_key = "STRIPE_PRICE_PRO_YEARLY" if normalized_interval == "yearly" else "STRIPE_PRICE_PRO_MONTHLY"
        price = os.environ.get(alias_key, "").strip()
        if price:
            return price
    raise BillingConfigError(f"{env_key} is missing")


def _select_llm_overage_price_id(plan: Any, interval: Any) -> Optional[str]:
    normalized_plan = _normalize_plan(plan)
    normalized_interval = _normalize_interval(interval)
    specific_key = f"STRIPE_LLM_OVERAGE_PRICE_{normalized_plan.upper()}_{normalized_interval.upper()}"
    price = os.environ.get(specific_key, "").strip()
    if price:
        return price
    # Les prix overage génériques ci-dessous sont metered MENSUELS. Les attacher à
    # une base annuelle fait échouer le Checkout Stripe (« You cannot combine
    # currencies/intervals »). On ne retombe donc sur eux que pour l'intervalle
    # mensuel ; l'annuel n'a d'overage que via un prix metered annuel explicite.
    if normalized_interval != "monthly":
        return None
    for env_name in (
        "STRIPE_LLM_OVERAGE_PRICE_ID",
        "STRIPE_PRICE_AI_CREDITS_MONTHLY",
        "STRIPE_PRICE_AI_USAGE",
    ):
        price = os.environ.get(env_name, "").strip()
        if price:
            return price
    return None


def _checkout_trial_days() -> int:
    raw = os.environ.get("STRIPE_TRIAL_DAYS", "7").strip()
    try:
        value = int(raw)
    except ValueError:
        return 7
    return max(0, value)


def _request_return_origin(payload: dict[str, Any]) -> Optional[str]:
    raw_origin = str(payload.get("return_origin") or request.headers.get("Origin") or "").strip()
    return _validated_return_origin(raw_origin)


def _validated_return_origin(raw_origin: str) -> Optional[str]:
    if not raw_origin:
        return None

    parsed = urlsplit(raw_origin)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        logger.warning("[BILLING] Ignoring invalid return origin: %s", raw_origin)
        return None

    origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    if _is_allowed_return_origin(origin):
        return origin

    logger.warning("[BILLING] Ignoring untrusted return origin: %s", origin)
    return None


def _is_allowed_return_origin(origin: str) -> bool:
    parsed = urlsplit(origin)
    host = parsed.hostname or ""
    if host in {"localhost", "127.0.0.1", "::1"}:
        return parsed.scheme in {"http", "https"}

    allowed_origins = {
        _origin_from_url(os.environ.get("FRONTEND_URL", "")),
        _origin_from_url(os.environ.get("STRIPE_SUCCESS_URL", "")),
        _origin_from_url(os.environ.get("STRIPE_CANCEL_URL", "")),
        _origin_from_url(os.environ.get("STRIPE_PORTAL_RETURN_URL", "")),
    }
    for env_name in ("STRIPE_RETURN_ORIGINS", "API_CORS_ORIGINS"):
        allowed_origins.update(
            _origin_from_url(value.strip())
            for value in os.environ.get(env_name, "").split(",")
            if value.strip()
        )
    allowed_origins.discard(None)
    return origin in allowed_origins


def _origin_from_url(value: str) -> Optional[str]:
    parsed = urlsplit(value.strip().strip('"').strip("'"))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def _success_url(return_origin: Optional[str] = None) -> str:
    if return_origin:
        return f"{return_origin}/settings/billing?billing=success&session_id={{CHECKOUT_SESSION_ID}}"
    return os.environ.get(
        "STRIPE_SUCCESS_URL",
        "https://app.agentys.io/settings/billing?billing=success&session_id={CHECKOUT_SESSION_ID}",
    )


def _cancel_url(return_origin: Optional[str] = None) -> str:
    if return_origin:
        return f"{return_origin}/settings/billing?billing=cancelled"
    return os.environ.get(
        "STRIPE_CANCEL_URL",
        "https://app.agentys.io/settings/billing?billing=cancelled",
    )


def _portal_return_url(return_origin: Optional[str] = None) -> str:
    if return_origin:
        return f"{return_origin}/settings/billing"
    return os.environ.get(
        "STRIPE_PORTAL_RETURN_URL",
        "https://app.agentys.io/settings/billing",
    )


def _record_ambassador_referral(session, checkout_session: Any) -> None:
    """Rattachement ambassadeur — best-effort, ne doit jamais casser le billing.

    Exécuté dans un savepoint : un échec (ou un doublon sur livraison webhook
    concurrente) est annulé seul, sans empoisonner la transaction billing.
    """
    try:
        with session.begin_nested():
            attach_referral_from_checkout(session, checkout_session)
    except IntegrityError:
        logger.info("[BILLING] ambassador referral duplicate (concurrent delivery), ignored")
    except Exception:  # noqa: BLE001 - parrainage secondaire, billing primaire
        logger.error("[BILLING] ambassador referral attach failed", exc_info=True)


def _record_ambassador_commission(session, invoice: Any) -> None:
    """Commission ambassadeur — best-effort, ne doit jamais casser le billing.

    Savepoint : idem référence — l'idempotence par ``stripe_invoice_id`` peut
    lever IntegrityError sur livraison concurrente ; on l'absorbe proprement.
    """
    try:
        with session.begin_nested():
            record_commission_from_invoice(session, invoice)
    except IntegrityError:
        logger.info("[BILLING] ambassador commission duplicate (concurrent delivery), ignored")
    except Exception:  # noqa: BLE001 - parrainage secondaire, billing primaire
        logger.error("[BILLING] ambassador commission record failed", exc_info=True)


def _process_stripe_event(session, stripe, event_type: str, obj: Any) -> None:
    if event_type == "checkout.session.completed":
        _sync_checkout_completed(session, stripe, obj)
        _record_ambassador_referral(session, obj)
        return

    if event_type in {"customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"}:
        user_id = resolve_user_id_from_stripe_object(session, obj)
        if user_id is None:
            logger.warning("[BILLING] Subscription event without resolvable user_id: %s", event_type)
            return
        sync_subscription_from_stripe(session, user_id=user_id, subscription=obj)
        return

    if event_type == "customer.deleted":
        customer_id = object_get(obj, "id")
        if not customer_id:
            logger.warning("[BILLING] customer.deleted without customer id")
            return
        user_id = mark_customer_deleted(session, stripe_customer_id=str(customer_id))
        if user_id is None:
            logger.warning("[BILLING] customer.deleted for unknown customer: %s", customer_id)
        return

    if event_type in {"invoice.paid", "invoice.payment_failed"}:
        subscription_id = object_get(obj, "subscription")
        if subscription_id:
            subscription = stripe.Subscription.retrieve(
                str(subscription_id),
                expand=["items.data.price"],
            )
            user_id = resolve_user_id_from_stripe_object(session, subscription)
            if user_id is None:
                logger.warning("[BILLING] Invoice event without resolvable user_id")
            else:
                sync_subscription_from_stripe(session, user_id=user_id, subscription=subscription)
        # Commission ambassadeur uniquement sur encaissement réel.
        if event_type == "invoice.paid":
            _record_ambassador_commission(session, obj)


def _sync_checkout_completed(session, stripe, checkout_session: Any) -> None:
    user_id = resolve_user_id_from_stripe_object(session, checkout_session)
    if user_id is None:
        logger.warning("[BILLING] checkout.session.completed without user_id")
        return

    customer_id = object_get(checkout_session, "customer")
    customer_details = object_get(checkout_session, "customer_details", {}) or {}
    email = object_get(customer_details, "email") or object_get(checkout_session, "customer_email") or ""
    if customer_id:
        upsert_billing_customer(
            session,
            user_id=int(user_id),
            email=str(email),
            stripe_customer_id=str(customer_id),
        )

    subscription_id = object_get(checkout_session, "subscription")
    if subscription_id:
        subscription = stripe.Subscription.retrieve(
            str(subscription_id),
            expand=["items.data.price"],
        )
        sync_subscription_from_stripe(session, user_id=int(user_id), subscription=subscription)
    elif customer_id:
        resolved_user_id = find_user_id_for_customer(session, str(customer_id))
        if resolved_user_id is not None:
            logger.info("[BILLING] Checkout completed without subscription id for user %s", resolved_user_id)
