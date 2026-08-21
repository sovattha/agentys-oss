"""CLI entrypoint to attach the AI credits metered price to subscriptions."""

from __future__ import annotations

import argparse
import json
import os

import stripe
from sqlalchemy import select

from app.billing.stripe_sync import object_get, sync_subscription_from_stripe
from app.db.database import get_db_session
from app.db.models import BillingSubscription


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--send", action="store_true", help="Create subscription items in Stripe")
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    args = parser.parse_args()

    api_key = os.environ.get("STRIPE_SECRET_KEY", "").strip()
    if not api_key:
        raise RuntimeError("STRIPE_SECRET_KEY is required")
    usage_price_id = _usage_price_id()
    stripe.api_key = api_key

    dry_run = not args.send
    rows = []
    with get_db_session() as session:
        subscriptions = session.execute(
            select(BillingSubscription)
            .where(BillingSubscription.status == "active")
            .where(BillingSubscription.stripe_subscription_id.isnot(None))
            .order_by(BillingSubscription.user_id)
        ).scalars().all()

        for local_sub in subscriptions:
            stripe_sub = stripe.Subscription.retrieve(
                local_sub.stripe_subscription_id,
                expand=["items.data.price"],
            )
            items = object_get(object_get(stripe_sub, "items"), "data", []) or []
            attached = any(
                object_get(object_get(item, "price"), "id") == usage_price_id
                for item in items
            )
            status = "already_attached" if attached else "would_attach"
            if not attached and not dry_run:
                stripe.SubscriptionItem.create(
                    subscription=local_sub.stripe_subscription_id,
                    price=usage_price_id,
                )
                stripe_sub = stripe.Subscription.retrieve(
                    local_sub.stripe_subscription_id,
                    expand=["items.data.price"],
                )
                status = "attached"
            if not dry_run:
                sync_subscription_from_stripe(session, user_id=local_sub.user_id, subscription=stripe_sub)
            rows.append(
                {
                    "user_id": local_sub.user_id,
                    "stripe_subscription_id": local_sub.stripe_subscription_id,
                    "status": status,
                    "usage_price_id": usage_price_id,
                }
            )

    payload = {"dry_run": dry_run, "usage_price_id": usage_price_id, "subscriptions": rows}
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(f"Stripe usage price attach: dry_run={dry_run} usage_price_id={usage_price_id}")
    for row in rows:
        print("user={user_id} subscription={stripe_subscription_id} status={status}".format(**row))
    return 0


def _usage_price_id() -> str:
    value = os.environ.get("STRIPE_PRICE_AI_CREDITS_MONTHLY", "").strip()
    if value:
        return value
    value = os.environ.get("STRIPE_PRICE_AI_USAGE", "").strip()
    if value:
        return value
    raise RuntimeError("STRIPE_PRICE_AI_CREDITS_MONTHLY is required")


if __name__ == "__main__":
    raise SystemExit(main())
