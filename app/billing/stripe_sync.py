"""Synchronize Stripe objects into local billing tables."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import BillingCustomer, BillingSubscription


def object_get(obj: Any, key: str, default: Any = None) -> Any:
    """Read from Stripe objects, dicts, or test doubles."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    try:
        return obj.get(key, default)
    except AttributeError:
        return getattr(obj, key, default)


def metadata_get(obj: Any, key: str, default: Any = None) -> Any:
    metadata = object_get(obj, "metadata", {}) or {}
    return object_get(metadata, key, default)


def upsert_billing_customer(
    session: Session,
    *,
    user_id: int,
    email: str,
    stripe_customer_id: str,
) -> BillingCustomer:
    customer = session.execute(
        select(BillingCustomer).where(BillingCustomer.user_id == int(user_id))
    ).scalar_one_or_none()
    if customer is None:
        customer = BillingCustomer(
            user_id=int(user_id),
            email=email,
            stripe_customer_id=stripe_customer_id,
        )
        session.add(customer)
    else:
        customer.email = email
        customer.stripe_customer_id = stripe_customer_id
    return customer


def find_user_id_for_customer(session: Session, stripe_customer_id: str) -> Optional[int]:
    customer = session.execute(
        select(BillingCustomer).where(BillingCustomer.stripe_customer_id == stripe_customer_id)
    ).scalar_one_or_none()
    return int(customer.user_id) if customer is not None else None


def mark_customer_deleted(session: Session, *, stripe_customer_id: str) -> Optional[int]:
    """Reflect a Stripe customer deletion in local billing state."""
    customer = session.execute(
        select(BillingCustomer).where(BillingCustomer.stripe_customer_id == stripe_customer_id)
    ).scalar_one_or_none()
    user_id = int(customer.user_id) if customer is not None else None

    query = select(BillingSubscription).where(BillingSubscription.stripe_customer_id == stripe_customer_id)
    if user_id is not None:
        query = select(BillingSubscription).where(
            (BillingSubscription.user_id == user_id)
            | (BillingSubscription.stripe_customer_id == stripe_customer_id)
        )
    subscriptions = session.execute(query).scalars().all()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for subscription in subscriptions:
        subscription.status = "canceled"
        subscription.cancel_at_period_end = False
        subscription.current_period_end = now

    if customer is not None:
        session.delete(customer)
    return user_id


def mark_subscription_canceled(
    session: Session,
    *,
    stripe_subscription_id: str,
    ended_at: Optional[datetime] = None,
) -> Optional[BillingSubscription]:
    row = session.execute(
        select(BillingSubscription).where(
            BillingSubscription.stripe_subscription_id == stripe_subscription_id
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    row.status = "canceled"
    row.cancel_at_period_end = False
    row.current_period_end = ended_at or datetime.now(timezone.utc).replace(tzinfo=None)
    return row


def resolve_user_id_from_stripe_object(
    session: Session,
    obj: Any,
    *,
    fallback_user_id: Optional[int] = None,
) -> Optional[int]:
    raw_user_id = metadata_get(obj, "agentys_user_id") or object_get(obj, "client_reference_id")
    if raw_user_id:
        try:
            return int(raw_user_id)
        except (TypeError, ValueError):
            pass
    customer_id = object_get(obj, "customer")
    if customer_id:
        return find_user_id_for_customer(session, str(customer_id))
    return fallback_user_id


def sync_subscription_from_stripe(
    session: Session,
    *,
    user_id: int,
    subscription: Any,
) -> BillingSubscription:
    stripe_subscription_id = str(object_get(subscription, "id", "") or "")
    stripe_customer_id = object_get(subscription, "customer")
    stripe_price_id, stripe_usage_price_id, plan = _subscription_price_ids_and_plan(subscription)
    status = str(object_get(subscription, "status", "unknown") or "unknown").lower()
    current_period_start = _datetime_from_stripe_ts(object_get(subscription, "current_period_start"))
    cancel_at = object_get(subscription, "cancel_at")
    current_period_end = _datetime_from_stripe_ts(
        object_get(subscription, "current_period_end") or cancel_at
    )
    cancel_at_period_end = bool(object_get(subscription, "cancel_at_period_end", False) or cancel_at)

    row = session.execute(
        select(BillingSubscription).where(BillingSubscription.user_id == int(user_id))
    ).scalar_one_or_none()
    if row is None:
        row = BillingSubscription(user_id=int(user_id))
        session.add(row)

    row.stripe_subscription_id = stripe_subscription_id or row.stripe_subscription_id
    row.stripe_customer_id = str(stripe_customer_id) if stripe_customer_id else row.stripe_customer_id
    row.stripe_price_id = stripe_price_id
    row.stripe_usage_price_id = stripe_usage_price_id
    row.plan = plan or ("professional" if (stripe_price_id or stripe_subscription_id) else "free")
    row.status = status
    row.current_period_start = current_period_start
    row.current_period_end = current_period_end
    row.cancel_at_period_end = cancel_at_period_end
    row.usage_billing_enabled = _usage_billing_enabled(subscription)
    return row


def mark_subscription_status(
    session: Session,
    *,
    stripe_subscription_id: str,
    status: str,
) -> Optional[BillingSubscription]:
    row = session.execute(
        select(BillingSubscription).where(
            BillingSubscription.stripe_subscription_id == stripe_subscription_id
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    row.status = status.lower()
    row.plan = row.plan if row.stripe_subscription_id else "free"
    return row


def _first_price_id_and_plan(subscription: Any) -> tuple[Optional[str], Optional[str]]:
    price_id, _usage_price_id, plan = _subscription_price_ids_and_plan(subscription)
    return price_id, plan


def _subscription_price_ids_and_plan(
    subscription: Any,
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    items = object_get(subscription, "items")
    data = object_get(items, "data", []) if items is not None else []
    if not data:
        return None, None, None
    base_price = None
    usage_price_id = None
    for item in data:
        price = object_get(item, "price")
        recurring = object_get(price, "recurring", {}) or {}
        usage_type = str(object_get(recurring, "usage_type", "") or "").lower()
        component = str(metadata_get(price, "agentys_component") or "").lower()
        if usage_type == "metered" or component == "ai_credit_overage":
            usage_price_id = str(object_get(price, "id")) if object_get(price, "id") else usage_price_id
            continue
        if base_price is None:
            base_price = price

    price = base_price or object_get(data[0], "price")
    price_id = object_get(price, "id")
    metadata_plan = metadata_get(price, "agentys_plan")
    lookup_key = str(object_get(price, "lookup_key", "") or "")
    plan = str(metadata_plan or "").lower() or None
    if plan not in {"starter", "professional"}:
        if "starter" in lookup_key:
            plan = "starter"
        elif "professional" in lookup_key or "pro" in lookup_key:
            plan = "professional"
        else:
            plan = None
    return (str(price_id) if price_id else None), usage_price_id, plan


def _usage_billing_enabled(subscription: Any) -> bool:
    raw = str(metadata_get(subscription, "agentys_usage_billing", "") or "").strip().lower()
    return raw in {"enabled", "true", "1", "yes", "on"}


def _datetime_from_stripe_ts(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError, OSError):
        return None
