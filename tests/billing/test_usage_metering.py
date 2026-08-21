from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.billing.usage_metering import (
    StripeUsageMeteringService,
    UsageMeteringConfig,
    credits_for_cost,
)
from app.db.models import Base, BillingSubscription, StripeUsageMeterEvent, TokenUsageLogRow


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False)
    return SessionLocal()


def _config(**overrides):
    values = {
        "event_name": "agentys_ai_credit_overage",
        "credit_cost_usd": Decimal("0.00861"),
        "credit_price_usd": Decimal("0.03"),
        "starter_included_credits": 425,
        "professional_included_credits": 850,
        "enabled": True,
        "dry_run": False,
    }
    values.update(overrides)
    return UsageMeteringConfig(**values)


def test_credits_for_cost_rounds_up_to_whole_credit():
    assert credits_for_cost(Decimal("8.61")) == 1000
    assert credits_for_cost(Decimal("8.6101")) == 1001


def test_calculate_subscription_overage_uses_plan_quota_and_period_cost():
    session = _session()
    now = datetime(2026, 6, 9, 12, 0, tzinfo=timezone.utc)
    period_start = now - timedelta(days=10)
    session.add(
        BillingSubscription(
            user_id=42,
            stripe_customer_id="cus_test",
            stripe_subscription_id="sub_test",
            stripe_price_id="price_starter",
            plan="starter",
            status="active",
            current_period_start=period_start.replace(tzinfo=None),
            current_period_end=(now + timedelta(days=20)).replace(tzinfo=None),
        )
    )
    session.add(
        TokenUsageLogRow(
            user_id=42,
            agent="DrafterAgent",
            feature="drafting",
            model="claude",
            input_tokens=1000,
            output_tokens=1000,
            cost_usd=4.0,
            created_at=(now - timedelta(days=1)).replace(tzinfo=None),
        )
    )
    session.commit()

    subscription = session.query(BillingSubscription).one()
    result = StripeUsageMeteringService(session, config=_config(), now=now).calculate_subscription_overage(
        subscription
    )

    assert result.used_credits == 465
    assert result.included_credits == 425
    assert result.metered_credits == 40
    assert result.status == "planned"


def test_sync_active_subscriptions_dry_run_does_not_persist_meter_event():
    session = _session()
    now = datetime(2026, 6, 9, 12, 0, tzinfo=timezone.utc)
    session.add(
        BillingSubscription(
            user_id=42,
            stripe_customer_id="cus_test",
            stripe_subscription_id="sub_test",
            stripe_price_id="price_starter",
            plan="starter",
            status="active",
            current_period_start=(now - timedelta(days=10)).replace(tzinfo=None),
            current_period_end=(now + timedelta(days=20)).replace(tzinfo=None),
        )
    )
    session.add(
        TokenUsageLogRow(
            user_id=42,
            agent="DrafterAgent",
            feature="drafting",
            model="claude",
            input_tokens=1000,
            output_tokens=1000,
            cost_usd=4.0,
            created_at=(now - timedelta(days=1)).replace(tzinfo=None),
        )
    )
    session.commit()

    result = StripeUsageMeteringService(session, config=_config(dry_run=True), now=now).sync_active_subscriptions()[0]

    assert result.status == "dry_run"
    assert result.metered_credits == 40
    assert session.query(StripeUsageMeterEvent).count() == 0


def test_sync_active_subscriptions_sends_meter_event_and_records_audit_row():
    session = _session()
    now = datetime(2026, 6, 9, 12, 0, tzinfo=timezone.utc)
    session.add(
        BillingSubscription(
            user_id=42,
            stripe_customer_id="cus_test",
            stripe_subscription_id="sub_test",
            stripe_price_id="price_starter",
            plan="starter",
            status="active",
            current_period_start=(now - timedelta(days=10)).replace(tzinfo=None),
            current_period_end=(now + timedelta(days=20)).replace(tzinfo=None),
        )
    )
    session.add(
        TokenUsageLogRow(
            user_id=42,
            agent="DrafterAgent",
            feature="drafting",
            model="claude",
            input_tokens=1000,
            output_tokens=1000,
            cost_usd=4.0,
            created_at=(now - timedelta(days=1)).replace(tzinfo=None),
        )
    )
    session.commit()

    class FakeMeterEvent:
        calls = []

        @classmethod
        def create(cls, **kwargs):
            cls.calls.append(kwargs)
            return {"identifier": kwargs["identifier"]}

    class FakeBilling:
        MeterEvent = FakeMeterEvent

    class FakeStripe:
        billing = FakeBilling()

    result = StripeUsageMeteringService(
        session,
        stripe_client=FakeStripe(),
        config=_config(),
        now=now,
    ).sync_active_subscriptions()[0]

    row = session.query(StripeUsageMeterEvent).one()
    assert result.status == "sent"
    assert row.status == "sent"
    assert row.metered_credits == 40
    assert FakeMeterEvent.calls == [
        {
            "event_name": "agentys_ai_credit_overage",
            "payload": {"stripe_customer_id": "cus_test", "value": "40"},
            "identifier": row.stripe_identifier,
            "timestamp": int(now.timestamp()),
        }
    ]
