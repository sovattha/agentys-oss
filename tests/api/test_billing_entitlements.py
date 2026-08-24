# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def _reset_db_engine_between_tests():
    yield

    from app.db.database import reset_engine

    reset_engine()


def _init_tmp_db(tmp_path, monkeypatch):
    from app.db.database import get_engine, init_db, reset_engine

    monkeypatch.setenv("AGENTYS_DB_PATH", str(tmp_path / "billing.db"))
    reset_engine()
    engine = get_engine()
    init_db(engine)
    return engine


def test_free_user_has_no_ai_entitlement(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)

    from app.billing.entitlements import BillingEntitlementService

    entitlement = BillingEntitlementService().get_for_user(42)

    assert entitlement.plan == "free"
    assert entitlement.subscription_status == "none"
    assert entitlement.ai_enabled is False
    assert entitlement.reason == "no_active_subscription"
    assert entitlement.limits == {
        "deepgram_minutes_per_day": 0,
        "deepgram_active_days_per_month": 0,
        "deepgram_minutes_per_month": 0,
        "llm_monthly_budget_usd": 0.0,
    }


@pytest.mark.parametrize("status", ["past_due", "canceled", "unpaid", "incomplete"])
def test_only_active_subscription_enables_ai(tmp_path, monkeypatch, status):
    _init_tmp_db(tmp_path, monkeypatch)

    from app.billing.entitlements import BillingEntitlementService
    from app.db.database import get_db_session
    from app.db.models import BillingSubscription

    with get_db_session() as session:
        session.add(
            BillingSubscription(
                user_id=42,
                stripe_subscription_id=f"sub_{status}",
                stripe_customer_id="cus_test",
                stripe_price_id="price_test",
                plan="pro",
                status=status,
                current_period_end=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=30),
            )
        )

    entitlement = BillingEntitlementService().get_for_user(42)

    assert entitlement.ai_enabled is False
    assert entitlement.plan == "pro"
    assert entitlement.subscription_status == status
    assert entitlement.reason == f"subscription_{status}"


def test_trialing_subscription_enables_ai_for_free_trial(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)

    from app.billing.entitlements import BillingEntitlementService
    from app.db.database import get_db_session
    from app.db.models import BillingSubscription

    with get_db_session() as session:
        session.add(
            BillingSubscription(
                user_id=42,
                stripe_subscription_id="sub_trial",
                stripe_customer_id="cus_test",
                stripe_price_id="price_test",
                plan="starter",
                status="trialing",
                current_period_end=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=7),
            )
        )

    entitlement = BillingEntitlementService().get_for_user(42)

    assert entitlement.ai_enabled is True
    assert entitlement.plan == "starter"
    assert entitlement.subscription_status == "trialing"
    assert entitlement.reason == "active"
    assert entitlement.limits["llm_monthly_budget_usd"] == 3.5
    assert entitlement.usage_billing_enabled is False


def test_trialing_professional_subscription_is_capped_to_350_llm_credits(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)

    from app.billing.entitlements import BillingEntitlementService
    from app.db.database import get_db_session
    from app.db.models import BillingSubscription

    with get_db_session() as session:
        session.add(
            BillingSubscription(
                user_id=42,
                stripe_subscription_id="sub_trial_professional",
                stripe_customer_id="cus_test",
                stripe_price_id="price_professional",
                plan="professional",
                status="trialing",
                current_period_end=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=7),
            )
        )

    entitlement = BillingEntitlementService().get_for_user(42)

    assert entitlement.ai_enabled is True
    assert entitlement.plan == "professional"
    assert entitlement.subscription_status == "trialing"
    assert entitlement.limits["llm_monthly_budget_usd"] == 3.5
    assert entitlement.usage_billing_enabled is False


def test_llm_credit_usage_reports_current_month_spend(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)

    from app.billing.entitlements import BillingEntitlementService
    from app.db.database import get_db_session
    from app.db.models import BillingSubscription, TokenUsageLogRow

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    with get_db_session() as session:
        session.add(
            BillingSubscription(
                user_id=42,
                stripe_subscription_id="sub_starter",
                stripe_customer_id="cus_test",
                stripe_price_id="price_starter",
                plan="starter",
                status="active",
                current_period_end=now + timedelta(days=30),
            )
        )
        session.add_all(
            [
                TokenUsageLogRow(
                    account_id=None,
                    user_id=42,
                    agent="DrafterAgent",
                    feature="drafting",
                    model="claude-test",
                    input_tokens=100,
                    output_tokens=50,
                    cost_usd=0.1,
                    created_at=now,
                ),
                TokenUsageLogRow(
                    account_id=None,
                    user_id=42,
                    agent="ClassifierAgent",
                    feature="classification",
                    model="claude-test",
                    input_tokens=100,
                    output_tokens=50,
                    cost_usd=0.32,
                    created_at=now,
                ),
                TokenUsageLogRow(
                    account_id=None,
                    user_id=42,
                    agent="DrafterAgent",
                    feature="drafting",
                    model="claude-test",
                    input_tokens=100,
                    output_tokens=50,
                    cost_usd=3.5,
                    created_at=month_start - timedelta(seconds=1),
                ),
            ]
        )

    usage = BillingEntitlementService().get_llm_credit_usage(42)

    assert usage["llm"]["included_credits"] == 350
    assert usage["llm"]["used_credits"] == 42
    assert usage["llm"]["remaining_credits"] == 308
    assert usage["llm"]["overage_credits"] == 0
    assert usage["llm"]["resets_at"].endswith("+00:00")


def test_llm_credit_usage_uses_trial_cap_for_professional(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)

    from app.billing.entitlements import BillingEntitlementService
    from app.db.database import get_db_session
    from app.db.models import BillingSubscription, TokenUsageLogRow

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with get_db_session() as session:
        session.add(
            BillingSubscription(
                user_id=42,
                stripe_subscription_id="sub_trial_professional",
                stripe_customer_id="cus_test",
                stripe_price_id="price_professional",
                plan="professional",
                status="trialing",
                current_period_end=now + timedelta(days=7),
            )
        )
        session.add(
            TokenUsageLogRow(
                account_id=None,
                user_id=42,
                agent="DrafterAgent",
                feature="drafting",
                model="claude-test",
                input_tokens=100,
                output_tokens=50,
                cost_usd=3.52,
                created_at=now,
            )
        )

    usage = BillingEntitlementService().get_llm_credit_usage(42)

    assert usage["llm"]["included_credits"] == 350
    assert usage["llm"]["used_credits"] == 352
    assert usage["llm"]["remaining_credits"] == 0
    assert usage["llm"]["overage_credits"] == 2
    assert usage["llm"]["usage_billing_enabled"] is False


def test_starter_dictation_credit_usage_reports_current_day(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)

    from app.billing.entitlements import BillingEntitlementService
    from app.db.database import get_db_session
    from app.db.models import BillingSubscription, DictationUsageLogRow

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    with get_db_session() as session:
        session.add(
            BillingSubscription(
                user_id=42,
                stripe_subscription_id="sub_starter_dictation",
                stripe_customer_id="cus_test",
                stripe_price_id="price_starter",
                plan="starter",
                status="active",
                current_period_end=now + timedelta(days=30),
            )
        )
        session.add_all(
            [
                DictationUsageLogRow(
                    account_id=None,
                    user_id=42,
                    provider="deepgram",
                    duration_seconds=30,
                    created_at=now,
                ),
                DictationUsageLogRow(
                    account_id=None,
                    user_id=42,
                    provider="openai",
                    duration_seconds=45,
                    created_at=now,
                ),
                DictationUsageLogRow(
                    account_id=None,
                    user_id=42,
                    provider="deepgram",
                    duration_seconds=600,
                    created_at=day_start - timedelta(seconds=1),
                ),
                DictationUsageLogRow(
                    account_id=None,
                    user_id=99,
                    provider="deepgram",
                    duration_seconds=600,
                    created_at=now,
                ),
            ]
        )

    usage = BillingEntitlementService().get_credit_usage(42)

    assert usage["dictation"]["window"] == "day"
    assert usage["dictation"]["included_credits"] == 10
    assert usage["dictation"]["used_credits"] == 13
    assert usage["dictation"]["remaining_credits"] == 0
    assert usage["dictation"]["overage_credits"] == 3
    assert usage["dictation"]["resets_at"].endswith("+00:00")


def test_professional_dictation_credit_usage_reports_current_month(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)

    from app.billing.entitlements import BillingEntitlementService
    from app.db.database import get_db_session
    from app.db.models import BillingSubscription, DictationUsageLogRow

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    with get_db_session() as session:
        session.add(
            BillingSubscription(
                user_id=42,
                stripe_subscription_id="sub_professional_dictation",
                stripe_customer_id="cus_test",
                stripe_price_id="price_professional",
                plan="professional",
                status="active",
                current_period_end=now + timedelta(days=30),
            )
        )
        session.add_all(
            [
                DictationUsageLogRow(
                    account_id=None,
                    user_id=42,
                    provider="deepgram",
                    duration_seconds=120,
                    created_at=now,
                ),
                DictationUsageLogRow(
                    account_id=None,
                    user_id=42,
                    provider="deepgram",
                    duration_seconds=600,
                    created_at=month_start - timedelta(seconds=1),
                ),
            ]
        )

    usage = BillingEntitlementService().get_credit_usage(42)

    assert usage["dictation"]["window"] == "month"
    assert usage["dictation"]["included_credits"] == 4000
    assert usage["dictation"]["used_credits"] == 20
    assert usage["dictation"]["remaining_credits"] == 3980
    assert usage["dictation"]["overage_credits"] == 0


def test_active_subscription_enables_ai(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)

    from app.billing.entitlements import BillingEntitlementService
    from app.db.database import get_db_session
    from app.db.models import BillingSubscription

    with get_db_session() as session:
        session.add(
            BillingSubscription(
                user_id=42,
                stripe_subscription_id="sub_active",
                stripe_customer_id="cus_test",
                stripe_price_id="price_test",
                plan="pro",
                status="active",
                current_period_end=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=30),
            )
        )

    entitlement = BillingEntitlementService().get_for_user(42)

    assert entitlement.ai_enabled is True
    assert entitlement.reason == "active"
    assert entitlement.limits["deepgram_minutes_per_day"] == 20
    assert entitlement.limits["deepgram_active_days_per_month"] == 20
    assert entitlement.limits["deepgram_minutes_per_month"] == 400
    assert entitlement.limits["llm_monthly_budget_usd"] == 7.0


def test_active_subscription_exposes_usage_billing_when_meter_configured(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_meter")
    monkeypatch.setenv("STRIPE_LLM_OVERAGE_METER_EVENT_NAME", "agentys_llm_overage")
    monkeypatch.setenv("STRIPE_USAGE_SYNC_ENABLED", "true")
    monkeypatch.setenv("STRIPE_USAGE_DRY_RUN", "false")

    from app.billing.entitlements import BillingEntitlementService
    from app.db.database import get_db_session
    from app.db.models import BillingSubscription

    with get_db_session() as session:
        session.add(
            BillingSubscription(
                user_id=42,
                stripe_subscription_id="sub_metered",
                stripe_customer_id="cus_test",
                stripe_price_id="price_starter",
                plan="starter",
                status="active",
                current_period_end=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=30),
                usage_billing_enabled=True,
            )
        )

    entitlement = BillingEntitlementService().get_for_user(42)

    assert entitlement.ai_enabled is True
    assert entitlement.usage_billing_enabled is True


def test_active_subscription_with_expired_period_is_blocked(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)

    from app.billing.entitlements import BillingEntitlementService
    from app.db.database import get_db_session
    from app.db.models import BillingSubscription

    with get_db_session() as session:
        session.add(
            BillingSubscription(
                user_id=42,
                stripe_subscription_id="sub_stale",
                stripe_customer_id="cus_test",
                stripe_price_id="price_test",
                plan="pro",
                status="active",
                current_period_end=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1),
            )
        )

    entitlement = BillingEntitlementService().get_for_user(42)

    assert entitlement.ai_enabled is False
    assert entitlement.reason == "subscription_period_ended"


def test_stripe_sync_keeps_professional_plan_for_past_due_without_ai_access(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)

    from app.billing.entitlements import BillingEntitlementService
    from app.billing.stripe_sync import sync_subscription_from_stripe
    from app.db.database import get_db_session

    stripe_subscription = {
        "id": "sub_past_due",
        "customer": "cus_test",
        "status": "past_due",
        "current_period_end": int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp()),
        "cancel_at_period_end": False,
        "items": {
            "data": [
                {
                    "price": {
                        "id": "price_test",
                        "lookup_key": "agentys_professional_monthly",
                        "metadata": {"agentys_plan": "professional"},
                    }
                }
            ]
        },
    }
    with get_db_session() as session:
        sync_subscription_from_stripe(session, user_id=42, subscription=stripe_subscription)

    entitlement = BillingEntitlementService().get_for_user(42)

    assert entitlement.plan == "professional"
    assert entitlement.subscription_status == "past_due"
    assert entitlement.ai_enabled is False
    assert entitlement.limits["deepgram_minutes_per_day"] == 20
    assert entitlement.limits["deepgram_active_days_per_month"] == 20
    assert entitlement.limits["deepgram_minutes_per_month"] == 400
    assert entitlement.limits["llm_monthly_budget_usd"] == 7.0


def test_stripe_sync_stores_starter_plan_from_price_metadata(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)

    from app.billing.entitlements import BillingEntitlementService
    from app.billing.stripe_sync import sync_subscription_from_stripe
    from app.db.database import get_db_session

    stripe_subscription = {
        "id": "sub_starter",
        "customer": "cus_test",
        "status": "active",
        "current_period_end": int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp()),
        "items": {
            "data": [
                {
                    "price": {
                        "id": "price_starter",
                        "lookup_key": "agentys_starter_yearly",
                        "metadata": {"agentys_plan": "starter"},
                    }
                }
            ]
        },
    }
    with get_db_session() as session:
        sync_subscription_from_stripe(session, user_id=42, subscription=stripe_subscription)

    entitlement = BillingEntitlementService().get_for_user(42)

    assert entitlement.plan == "starter"
    assert entitlement.ai_enabled is True
    assert entitlement.limits["deepgram_minutes_per_day"] == 1
    assert entitlement.limits["deepgram_active_days_per_month"] is None
    assert entitlement.limits["deepgram_minutes_per_month"] is None
    assert entitlement.limits["llm_monthly_budget_usd"] == 3.5


def test_stripe_sync_stores_usage_billing_flag_from_subscription_metadata(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)

    from app.billing.stripe_sync import sync_subscription_from_stripe
    from app.db.database import get_db_session
    from app.db.models import BillingSubscription

    stripe_subscription = {
        "id": "sub_usage_metered",
        "customer": "cus_test",
        "status": "active",
        "metadata": {"agentys_usage_billing": "enabled"},
        "current_period_end": int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp()),
        "items": {
            "data": [
                {
                    "price": {
                        "id": "price_starter",
                        "lookup_key": "agentys_starter_monthly",
                        "metadata": {"agentys_plan": "starter"},
                    }
                }
            ]
        },
    }
    with get_db_session() as session:
        sync_subscription_from_stripe(session, user_id=42, subscription=stripe_subscription)

    with get_db_session() as session:
        row = session.query(BillingSubscription).filter_by(user_id=42).one()
        assert row.usage_billing_enabled is True


def test_stripe_sync_treats_cancel_at_as_scheduled_cancellation(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)

    from app.billing.entitlements import BillingEntitlementService
    from app.billing.stripe_sync import sync_subscription_from_stripe
    from app.db.database import get_db_session

    cancel_at = int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp())
    stripe_subscription = {
        "id": "sub_cancel_at",
        "customer": "cus_test",
        "status": "active",
        "current_period_end": None,
        "cancel_at": cancel_at,
        "cancel_at_period_end": False,
        "items": {
            "data": [
                {
                    "price": {
                        "id": "price_starter",
                        "metadata": {"agentys_plan": "starter"},
                    }
                }
            ]
        },
    }
    with get_db_session() as session:
        row = sync_subscription_from_stripe(session, user_id=42, subscription=stripe_subscription)

    entitlement = BillingEntitlementService().get_for_user(42)

    assert row.cancel_at_period_end is True
    assert row.current_period_end == datetime.fromtimestamp(cancel_at, tz=timezone.utc).replace(tzinfo=None)
    assert entitlement.ai_enabled is True
    assert entitlement.cancel_at_period_end is True
    assert entitlement.current_period_end == datetime.fromtimestamp(cancel_at, tz=timezone.utc).isoformat()


def test_stripe_sync_keeps_base_plan_when_usage_price_is_first(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)

    from app.db.database import get_db_session
    from app.billing.stripe_sync import sync_subscription_from_stripe

    now = datetime.now(timezone.utc)
    stripe_subscription = {
        "id": "sub_with_usage",
        "customer": "cus_test",
        "status": "active",
        "current_period_start": int(now.timestamp()),
        "current_period_end": int((now + timedelta(days=30)).timestamp()),
        "items": {
            "data": [
                {
                    "price": {
                        "id": "price_usage",
                        "lookup_key": "agentys_ai_credits_overage_monthly",
                        "metadata": {"agentys_component": "ai_credit_overage"},
                        "recurring": {"usage_type": "metered"},
                    }
                },
                {
                    "price": {
                        "id": "price_starter",
                        "lookup_key": "agentys_starter_monthly",
                        "metadata": {"agentys_plan": "starter"},
                        "recurring": {"usage_type": "licensed"},
                    }
                },
            ]
        },
    }

    with get_db_session() as session:
        row = sync_subscription_from_stripe(session, user_id=42, subscription=stripe_subscription)
        assert row.plan == "starter"
        assert row.stripe_price_id == "price_starter"
        assert row.stripe_usage_price_id == "price_usage"
        assert row.current_period_start is not None


def test_checkout_price_selection_supports_starter_and_professional(monkeypatch):
    from app.api.billing import _select_llm_overage_price_id, _select_price_id

    monkeypatch.setenv("STRIPE_PRICE_STARTER_MONTHLY", "price_starter_m")
    monkeypatch.setenv("STRIPE_PRICE_STARTER_YEARLY", "price_starter_y")
    monkeypatch.setenv("STRIPE_PRICE_PROFESSIONAL_MONTHLY", "price_professional_m")
    monkeypatch.setenv("STRIPE_PRICE_PROFESSIONAL_YEARLY", "price_professional_y")
    monkeypatch.setenv("STRIPE_LLM_OVERAGE_PRICE_ID", "price_llm_overage")

    assert _select_price_id("starter", "monthly") == "price_starter_m"
    assert _select_price_id("starter", "yearly") == "price_starter_y"
    assert _select_price_id("professional", "monthly") == "price_professional_m"
    assert _select_price_id("professionnal", "annual") == "price_professional_y"
    assert _select_llm_overage_price_id("starter", "monthly") == "price_llm_overage"

    # Bug paiement annuel : le prix overage générique (`STRIPE_LLM_OVERAGE_PRICE_ID`)
    # est metered MENSUEL. L'attacher à une base annuelle fait échouer le Checkout
    # Stripe (intervalles incompatibles). Yearly ne reçoit donc d'overage QUE si un
    # prix metered annuel explicite est configuré.
    assert _select_llm_overage_price_id("professional", "yearly") is None
    monkeypatch.setenv("STRIPE_LLM_OVERAGE_PRICE_PROFESSIONAL_YEARLY", "price_overage_y")
    assert _select_llm_overage_price_id("professional", "yearly") == "price_overage_y"
    monkeypatch.delenv("STRIPE_LLM_OVERAGE_PRICE_PROFESSIONAL_YEARLY")

    monkeypatch.delenv("STRIPE_LLM_OVERAGE_PRICE_ID")
    monkeypatch.setenv("STRIPE_PRICE_AI_CREDITS_MONTHLY", "price_usage")
    assert _select_llm_overage_price_id("starter", "monthly") == "price_usage"


def test_checkout_session_adds_trial_and_usage_meter_price(monkeypatch):
    monkeypatch.setenv("STRIPE_TRIAL_DAYS", "7")

    from app.api.billing import _create_stripe_checkout_session

    checkout_calls = []

    class _CheckoutSession:
        @staticmethod
        def create(**kwargs):
            checkout_calls.append(kwargs)
            return {"id": "cs_trial", "url": "https://checkout.test/trial"}

    class _Checkout:
        Session = _CheckoutSession

    class _Stripe:
        checkout = _Checkout

    checkout = _create_stripe_checkout_session(
        _Stripe,
        customer_id="cus_test",
        user_id=42,
        price_id="price_base",
        llm_overage_price_id="price_metered",
        metadata={"agentys_user_id": "42", "agentys_plan": "starter"},
        success_url="https://app.test/success",
        cancel_url="https://app.test/cancel",
    )

    assert checkout["id"] == "cs_trial"
    assert checkout_calls[0]["line_items"] == [
        {"price": "price_base", "quantity": 1},
        {"price": "price_metered"},
    ]
    assert checkout_calls[0]["subscription_data"]["trial_period_days"] == 7
    assert checkout_calls[0]["subscription_data"]["metadata"]["agentys_usage_billing"] == "enabled"


def test_checkout_returns_503_when_stripe_customer_create_is_unavailable(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("STRIPE_PRICE_STARTER_MONTHLY", "price_starter_m")

    from flask import Flask
    import stripe

    from app.api import billing as billing_api

    class _Customer:
        @staticmethod
        def create(**_kwargs):
            raise stripe.error.APIConnectionError("network down")

    class _Stripe:
        error = stripe.error
        Customer = _Customer

    monkeypatch.setattr(billing_api, "_get_stripe", lambda: _Stripe)
    monkeypatch.setattr(
        billing_api,
        "_current_user_or_none",
        lambda: {"id": 42, "email": "buyer@example.com"},
    )

    app = Flask(__name__)
    with app.test_request_context(
        "/api/billing/checkout",
        method="POST",
        json={"plan": "starter", "interval": "monthly"},
    ):
        response, status = billing_api.create_checkout_session()

    payload = response.get_json()
    assert status == 503
    assert payload["error_code"] == "STRIPE_UNAVAILABLE"
    assert payload["retryable"] is True


def test_checkout_recreates_missing_stored_stripe_customer(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("STRIPE_PRICE_STARTER_MONTHLY", "price_starter_m")

    from flask import Flask
    import stripe

    from app.api import billing as billing_api
    from app.db.database import get_db_session
    from app.db.models import BillingCustomer

    with get_db_session() as session:
        session.add(
            BillingCustomer(
                user_id=42,
                email="buyer@example.com",
                stripe_customer_id="cus_old",
            )
        )

    created_customers = []
    checkout_calls = []

    class _Customer:
        @staticmethod
        def create(**kwargs):
            created_customers.append(kwargs)
            return {"id": "cus_new"}

    class _CheckoutSession:
        @staticmethod
        def create(**kwargs):
            checkout_calls.append(kwargs)
            if kwargs["customer"] == "cus_old":
                raise stripe.error.InvalidRequestError(
                    "No such customer: 'cus_old'",
                    "customer",
                    code="resource_missing",
                )
            return {"id": "cs_test_recovered", "url": "https://checkout.test/recovered"}

    class _Checkout:
        Session = _CheckoutSession

    class _Stripe:
        error = stripe.error
        Customer = _Customer
        checkout = _Checkout

    monkeypatch.setattr(billing_api, "_get_stripe", lambda: _Stripe)
    monkeypatch.setattr(
        billing_api,
        "_current_user_or_none",
        lambda: {"id": 42, "email": "buyer@example.com"},
    )

    app = Flask(__name__)
    with app.test_request_context(
        "/api/billing/checkout",
        method="POST",
        json={"plan": "starter", "interval": "monthly"},
    ):
        response = billing_api.create_checkout_session()

    payload = response.get_json()
    assert payload["session_id"] == "cs_test_recovered"
    assert [call["customer"] for call in checkout_calls] == ["cus_old", "cus_new"]
    assert len(created_customers) == 1

    with get_db_session() as session:
        customer = session.query(BillingCustomer).filter_by(user_id=42).one()
        assert customer.stripe_customer_id == "cus_new"


def test_checkout_uses_validated_frontend_return_origin(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("STRIPE_PRICE_STARTER_MONTHLY", "price_starter_m")
    monkeypatch.setenv(
        "STRIPE_SUCCESS_URL",
        "http://127.0.0.1:1420/settings/billing?billing=success&session_id={CHECKOUT_SESSION_ID}",
    )
    monkeypatch.setenv("STRIPE_CANCEL_URL", "http://127.0.0.1:1420/settings/billing?billing=cancelled")

    from flask import Flask

    from app.api import billing as billing_api

    checkout_calls = []

    class _Customer:
        @staticmethod
        def create(**_kwargs):
            return {"id": "cus_test"}

    class _CheckoutSession:
        @staticmethod
        def create(**kwargs):
            checkout_calls.append(kwargs)
            return {"id": "cs_test_return_origin", "url": "https://checkout.test/return-origin"}

    class _Checkout:
        Session = _CheckoutSession

    class _Stripe:
        Customer = _Customer
        checkout = _Checkout

    monkeypatch.setattr(billing_api, "_get_stripe", lambda: _Stripe)
    monkeypatch.setattr(
        billing_api,
        "_current_user_or_none",
        lambda: {"id": 42, "email": "buyer@example.com"},
    )

    app = Flask(__name__)
    with app.test_request_context(
        "/api/billing/checkout",
        method="POST",
        json={
            "plan": "starter",
            "interval": "monthly",
            "return_origin": "http://localhost:1420",
        },
    ):
        response = billing_api.create_checkout_session()

    assert response.get_json()["session_id"] == "cs_test_return_origin"
    assert checkout_calls[0]["success_url"] == (
        "http://localhost:1420/settings/billing?billing=success&session_id={CHECKOUT_SESSION_ID}"
    )
    assert checkout_calls[0]["cancel_url"] == "http://localhost:1420/settings/billing?billing=cancelled"


def test_checkout_ignores_untrusted_return_origin(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("STRIPE_PRICE_STARTER_MONTHLY", "price_starter_m")
    monkeypatch.setenv(
        "STRIPE_SUCCESS_URL",
        "https://app.agentys.io/settings/billing?billing=success&session_id={CHECKOUT_SESSION_ID}",
    )

    from flask import Flask

    from app.api import billing as billing_api

    checkout_calls = []

    class _Customer:
        @staticmethod
        def create(**_kwargs):
            return {"id": "cus_test"}

    class _CheckoutSession:
        @staticmethod
        def create(**kwargs):
            checkout_calls.append(kwargs)
            return {"id": "cs_test_untrusted_origin", "url": "https://checkout.test/untrusted-origin"}

    class _Checkout:
        Session = _CheckoutSession

    class _Stripe:
        Customer = _Customer
        checkout = _Checkout

    monkeypatch.setattr(billing_api, "_get_stripe", lambda: _Stripe)
    monkeypatch.setattr(
        billing_api,
        "_current_user_or_none",
        lambda: {"id": 42, "email": "buyer@example.com"},
    )

    app = Flask(__name__)
    with app.test_request_context(
        "/api/billing/checkout",
        method="POST",
        json={
            "plan": "starter",
            "interval": "monthly",
            "return_origin": "https://evil.example",
        },
    ):
        response = billing_api.create_checkout_session()

    assert response.get_json()["session_id"] == "cs_test_untrusted_origin"
    assert checkout_calls[0]["success_url"] == (
        "https://app.agentys.io/settings/billing?billing=success&session_id={CHECKOUT_SESSION_ID}"
    )


def test_customer_deleted_webhook_disables_local_entitlement(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)

    from app.api import billing as billing_api
    from app.billing.entitlements import BillingEntitlementService
    from app.db.database import get_db_session
    from app.db.models import BillingCustomer, BillingSubscription

    with get_db_session() as session:
        session.add(
            BillingCustomer(
                user_id=42,
                email="buyer@example.com",
                stripe_customer_id="cus_deleted",
            )
        )
        session.add(
            BillingSubscription(
                user_id=42,
                stripe_customer_id="cus_deleted",
                stripe_subscription_id="sub_deleted",
                stripe_price_id="price_professional_m",
                plan="professional",
                status="active",
            )
        )

    with get_db_session() as session:
        billing_api._process_stripe_event(session, None, "customer.deleted", {"id": "cus_deleted"})

    entitlement = BillingEntitlementService().get_for_user(42)
    assert entitlement.ai_enabled is False
    assert entitlement.subscription_status == "canceled"

    with get_db_session() as session:
        customer = session.query(BillingCustomer).filter_by(user_id=42).one_or_none()
        assert customer is None


def test_billing_me_fresh_marks_missing_stripe_subscription_canceled(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)

    from flask import Flask
    import stripe

    from app.api import billing as billing_api
    from app.db.database import get_db_session
    from app.db.models import BillingSubscription

    with get_db_session() as session:
        session.add(
            BillingSubscription(
                user_id=42,
                stripe_customer_id="cus_deleted",
                stripe_subscription_id="sub_deleted",
                stripe_price_id="price_professional_m",
                plan="professional",
                status="active",
            )
        )

    class _Subscription:
        @staticmethod
        def retrieve(*_args, **_kwargs):
            raise stripe.error.InvalidRequestError(
                "No such subscription: 'sub_deleted'",
                "subscription",
                code="resource_missing",
            )

    class _Stripe:
        error = stripe.error
        Subscription = _Subscription

    monkeypatch.setattr(billing_api, "_get_stripe", lambda: _Stripe)
    monkeypatch.setattr(
        billing_api,
        "_current_user_or_none",
        lambda: {"id": 42, "email": "buyer@example.com"},
    )

    app = Flask(__name__)
    with app.test_request_context("/api/billing/me?fresh=true", method="GET"):
        response = billing_api.billing_me()

    payload = response.get_json()
    assert payload["billing"]["ai_enabled"] is False
    assert payload["billing"]["subscription_status"] == "canceled"


def test_billing_me_reconciles_returned_checkout_session(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)

    from flask import Flask

    from app.api import billing as billing_api
    from app.db.database import get_db_session
    from app.db.models import BillingCustomer, BillingSubscription

    retrieved_sessions = []
    retrieved_subscriptions = []

    class _CheckoutSession:
        @staticmethod
        def retrieve(session_id):
            retrieved_sessions.append(session_id)
            return {
                "id": session_id,
                "client_reference_id": "42",
                "customer": "cus_checkout",
                "customer_details": {"email": "buyer@example.com"},
                "subscription": "sub_checkout",
                "status": "complete",
                "payment_status": "paid",
            }

    class _Checkout:
        Session = _CheckoutSession

    class _Subscription:
        @staticmethod
        def retrieve(subscription_id, **_kwargs):
            retrieved_subscriptions.append(subscription_id)
            return {
                "id": subscription_id,
                "customer": "cus_checkout",
                "status": "active",
                "current_period_end": int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp()),
                "items": {
                    "data": [
                        {
                            "price": {
                                "id": "price_professional_m",
                                "metadata": {"agentys_plan": "professional"},
                            }
                        }
                    ]
                },
            }

    class _Stripe:
        checkout = _Checkout
        Subscription = _Subscription

    monkeypatch.setattr(billing_api, "_get_stripe", lambda: _Stripe)
    monkeypatch.setattr(
        billing_api,
        "_current_user_or_none",
        lambda: {"id": 42, "email": "buyer@example.com"},
    )

    app = Flask(__name__)
    with app.test_request_context("/api/billing/me?fresh=true&session_id=cs_test_return", method="GET"):
        response = billing_api.billing_me()

    payload = response.get_json()
    assert payload["billing"]["ai_enabled"] is True
    assert payload["billing"]["plan"] == "professional"
    assert payload["billing"]["limits"]["deepgram_minutes_per_day"] == 20
    assert payload["billing"]["limits"]["deepgram_active_days_per_month"] == 20
    assert payload["billing"]["limits"]["llm_monthly_budget_usd"] == 7.0
    assert retrieved_sessions == ["cs_test_return"]
    assert retrieved_subscriptions == ["sub_checkout"]

    with get_db_session() as session:
        customer = session.query(BillingCustomer).filter_by(user_id=42).one()
        subscription = session.query(BillingSubscription).filter_by(user_id=42).one()
        assert customer.stripe_customer_id == "cus_checkout"
        assert subscription.stripe_subscription_id == "sub_checkout"
        assert subscription.status == "active"


def test_billing_me_rejects_checkout_session_for_other_user(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)

    from flask import Flask

    from app.api import billing as billing_api

    class _CheckoutSession:
        @staticmethod
        def retrieve(_session_id):
            return {
                "id": "cs_wrong_user",
                "client_reference_id": "99",
                "customer": "cus_other",
                "subscription": "sub_other",
                "status": "complete",
                "payment_status": "paid",
            }

    class _Checkout:
        Session = _CheckoutSession

    class _Stripe:
        checkout = _Checkout

    monkeypatch.setattr(billing_api, "_get_stripe", lambda: _Stripe)
    monkeypatch.setattr(
        billing_api,
        "_current_user_or_none",
        lambda: {"id": 42, "email": "buyer@example.com"},
    )

    app = Flask(__name__)
    with app.test_request_context("/api/billing/me?fresh=true&session_id=cs_wrong_user", method="GET"):
        response, status = billing_api.billing_me()

    assert status == 403
    assert response.get_json()["error_code"] == "BILLING_SESSION_FORBIDDEN"


def test_billing_usage_requires_auth(monkeypatch):
    from flask import Flask

    from app.api import billing as billing_api

    monkeypatch.setattr(billing_api, "_current_user_or_none", lambda: None)

    app = Flask(__name__)
    with app.test_request_context("/api/billing/usage", method="GET"):
        response, status = billing_api.billing_usage()

    assert status == 401
    assert response.get_json()["error_code"] == "NOT_AUTHENTICATED"


def test_billing_usage_returns_llm_credit_usage(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)

    from flask import Flask

    from app.api import billing as billing_api
    from app.db.database import get_db_session
    from app.db.models import BillingSubscription, DictationUsageLogRow, TokenUsageLogRow

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with get_db_session() as session:
        session.add(
            BillingSubscription(
                user_id=42,
                stripe_subscription_id="sub_starter",
                stripe_customer_id="cus_test",
                stripe_price_id="price_starter",
                plan="starter",
                status="active",
                current_period_end=now + timedelta(days=30),
            )
        )
        session.add(
            TokenUsageLogRow(
                account_id=None,
                user_id=42,
                agent="DrafterAgent",
                feature="drafting",
                model="claude-test",
                input_tokens=100,
                output_tokens=50,
                cost_usd=0.42,
                created_at=now,
            )
        )
        session.add(
            DictationUsageLogRow(
                account_id=None,
                user_id=42,
                provider="deepgram",
                duration_seconds=60,
                created_at=now,
            )
        )

    monkeypatch.setattr(
        billing_api,
        "_current_user_or_none",
        lambda: {"id": 42, "email": "buyer@example.com"},
    )

    app = Flask(__name__)
    with app.test_request_context("/api/billing/usage", method="GET"):
        response = billing_api.billing_usage()

    payload = response.get_json()
    assert payload["usage"]["llm"]["included_credits"] == 350
    assert payload["usage"]["llm"]["used_credits"] == 42
    assert payload["usage"]["llm"]["remaining_credits"] == 308
    assert payload["usage"]["dictation"]["included_credits"] == 10
    assert payload["usage"]["dictation"]["used_credits"] == 10
    assert payload["usage"]["dictation"]["remaining_credits"] == 0
    assert payload["usage"]["dictation"]["window"] == "day"


def test_portal_retries_without_stale_stripe_configuration(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("STRIPE_PORTAL_CONFIGURATION_ID", "bpc_live_stale")

    from flask import Flask
    import stripe

    from app.api import billing as billing_api
    from app.db.database import get_db_session
    from app.db.models import BillingCustomer

    with get_db_session() as session:
        session.add(
            BillingCustomer(
                user_id=42,
                email="buyer@example.com",
                stripe_customer_id="cus_test",
            )
        )

    portal_calls = []

    class _PortalSession:
        @staticmethod
        def create(**kwargs):
            portal_calls.append(kwargs)
            if kwargs.get("configuration") == "bpc_live_stale":
                raise stripe.error.InvalidRequestError(
                    "No such configuration: 'bpc_live_stale'",
                    "configuration",
                    code="resource_missing",
                )
            return {"url": "https://billing.stripe.test/session"}

    class _BillingPortal:
        Session = _PortalSession

    class _Stripe:
        error = stripe.error
        billing_portal = _BillingPortal

    monkeypatch.setattr(billing_api, "_get_stripe", lambda: _Stripe)
    monkeypatch.setattr(
        billing_api,
        "_current_user_or_none",
        lambda: {"id": 42, "email": "buyer@example.com"},
    )

    app = Flask(__name__)
    with app.test_request_context("/api/billing/portal", method="POST", json={}):
        response = billing_api.create_portal_session()

    payload = response.get_json()
    assert payload["portal_url"] == "https://billing.stripe.test/session"
    assert portal_calls[0]["configuration"] == "bpc_live_stale"
    assert "configuration" not in portal_calls[1]


def test_subscription_details_returns_local_billing_state(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)

    from flask import Flask

    from app.api import billing as billing_api
    from app.db.database import get_db_session
    from app.db.models import BillingSubscription

    period_end = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=30)
    with get_db_session() as session:
        session.add(
            BillingSubscription(
                user_id=42,
                stripe_customer_id="cus_test",
                stripe_subscription_id="sub_test",
                stripe_price_id="price_professional_m",
                plan="professional",
                status="active",
                current_period_end=period_end,
                cancel_at_period_end=True,
            )
        )

    monkeypatch.setattr(
        billing_api,
        "_current_user_or_none",
        lambda: {"id": 42, "email": "buyer@example.com"},
    )

    app = Flask(__name__)
    with app.test_request_context("/api/billing/subscription", method="GET"):
        response = billing_api.billing_subscription_details()

    payload = response.get_json()
    assert payload["subscription"] == {
        "subscription_id": "sub_test",
        "customer_id": "cus_test",
        "price_id": "price_professional_m",
        "plan": "professional",
        "status": "active",
        "current_period_end": period_end.replace(tzinfo=timezone.utc).isoformat(),
        "cancel_at_period_end": True,
    }


def test_subscription_details_returns_null_without_subscription(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)

    from flask import Flask

    from app.api import billing as billing_api

    monkeypatch.setattr(
        billing_api,
        "_current_user_or_none",
        lambda: {"id": 42, "email": "buyer@example.com"},
    )

    app = Flask(__name__)
    with app.test_request_context("/api/billing/subscription", method="GET"):
        response = billing_api.billing_subscription_details()

    assert response.get_json()["subscription"] is None


def test_invoices_use_authenticated_customer_not_client_params(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)

    from flask import Flask

    from app.api import billing as billing_api
    from app.db.database import get_db_session
    from app.db.models import BillingCustomer, BillingSubscription

    with get_db_session() as session:
        session.add(
            BillingCustomer(
                user_id=42,
                email="buyer@example.com",
                stripe_customer_id="cus_real_user",
            )
        )
        session.add(
            BillingSubscription(
                user_id=42,
                stripe_customer_id="cus_real_user",
                stripe_subscription_id="sub_real_user",
                stripe_price_id="price_professional_m",
                plan="professional",
                status="active",
            )
        )

    invoice_calls = []
    created_ts = int(datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp())

    class _Invoice:
        @staticmethod
        def list(**kwargs):
            invoice_calls.append(kwargs)
            return {
                "data": [
                    {
                        "id": "in_real",
                        "amount_paid": 2500,
                        "currency": "eur",
                        "created": created_ts,
                        "status": "paid",
                        "invoice_pdf": "https://pay.stripe.test/in_real.pdf",
                        "hosted_invoice_url": "https://pay.stripe.test/in_real",
                        "description": "Agentys Professional",
                    },
                    {
                        "id": "in_open",
                        "amount_paid": 0,
                        "amount_due": 5000,
                        "total": 5000,
                        "currency": "eur",
                        "created": created_ts,
                        "status": "open",
                        "invoice_pdf": None,
                        "hosted_invoice_url": "https://pay.stripe.test/in_open",
                        "description": "Agentys Professional renewal",
                    }
                ]
            }

    class _Stripe:
        Invoice = _Invoice

    monkeypatch.setattr(billing_api, "_get_stripe", lambda: _Stripe)
    monkeypatch.setattr(
        billing_api,
        "_current_user_or_none",
        lambda: {"id": 42, "email": "buyer@example.com"},
    )

    app = Flask(__name__)
    with app.test_request_context(
        "/api/billing/invoices?customer=cus_attacker&subscription=sub_attacker&limit=5",
        method="GET",
    ):
        response = billing_api.billing_invoices()

    payload = response.get_json()
    assert invoice_calls == [{
        "customer": "cus_real_user",
        "subscription": "sub_real_user",
        "limit": 5,
    }]
    assert payload["invoices"] == [{
        "id": "in_real",
        "amount": 2500,
        "currency": "eur",
        "date": datetime.fromtimestamp(created_ts, tz=timezone.utc).isoformat(),
        "status": "paid",
        "invoice_pdf": "https://pay.stripe.test/in_real.pdf",
        "hosted_invoice_url": "https://pay.stripe.test/in_real",
        "description": "Agentys Professional",
    }, {
        "id": "in_open",
        "amount": 5000,
        "currency": "eur",
        "date": datetime.fromtimestamp(created_ts, tz=timezone.utc).isoformat(),
        "status": "open",
        "invoice_pdf": None,
        "hosted_invoice_url": "https://pay.stripe.test/in_open",
        "description": "Agentys Professional renewal",
    }]


def test_invoices_return_empty_without_billing_customer(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)

    from flask import Flask

    from app.api import billing as billing_api

    monkeypatch.setattr(
        billing_api,
        "_current_user_or_none",
        lambda: {"id": 42, "email": "buyer@example.com"},
    )

    app = Flask(__name__)
    with app.test_request_context("/api/billing/invoices", method="GET"):
        response = billing_api.billing_invoices()

    assert response.get_json() == {"invoices": []}


def test_stripe_webhook_is_public_but_signature_protected(monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)

    from app.api.app import create_app

    app = create_app(config={"TESTING": True})
    client = app.test_client()

    response = client.post(
        "/api/billing/stripe/webhook",
        data=b"{}",
        headers={"Stripe-Signature": "invalid"},
        environ_base={"REMOTE_ADDR": "203.0.113.10"},
    )

    assert response.status_code == 503
    assert response.get_json()["error_code"] == "BILLING_NOT_CONFIGURED"


def test_entitlement_gated_llm_blocks_without_active_subscription(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)

    from app.infrastructure.cost_manager import reset_usage_context, set_usage_context
    from app.infrastructure.entitlement_gate import EntitlementGatedLLM

    class _Inner:
        def complete(self):
            return "should not run"

    tokens = set_usage_context(user_id=42, feature="drafting")
    try:
        with pytest.raises(Exception) as excinfo:
            EntitlementGatedLLM(_Inner()).complete()
    finally:
        reset_usage_context(tokens)

    assert excinfo.value.__class__.__name__ == "EntitlementRequiredError"


def test_entitlement_gated_llm_blocks_when_monthly_budget_spent(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)

    from app.db.database import get_db_session
    from app.db.models import BillingSubscription, TokenUsageLogRow
    from app.infrastructure.cost_manager import reset_usage_context, set_usage_context
    from app.infrastructure.entitlement_gate import EntitlementGatedLLM

    with get_db_session() as session:
        session.add(
            BillingSubscription(
                user_id=42,
                stripe_subscription_id="sub_starter",
                stripe_customer_id="cus_test",
                stripe_price_id="price_starter",
                plan="starter",
                status="active",
                current_period_end=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=30),
            )
        )
        session.add(
            TokenUsageLogRow(
                account_id=None,
                user_id=42,
                agent="DrafterAgent",
                feature="drafting",
                model="claude-test",
                input_tokens=100,
                output_tokens=50,
                cost_usd=3.5,
                created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )

    class _Inner:
        def complete(self):
            return "should not run"

    tokens = set_usage_context(user_id=42, feature="drafting")
    try:
        with pytest.raises(Exception) as excinfo:
            EntitlementGatedLLM(_Inner()).complete()
    finally:
        reset_usage_context(tokens)

    assert excinfo.value.__class__.__name__ == "EntitlementRequiredError"
    assert excinfo.value.entitlement.reason == "llm_monthly_budget_exceeded"


def test_entitlement_gated_llm_allows_usage_billing_when_monthly_budget_spent(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_meter")
    monkeypatch.setenv("STRIPE_LLM_OVERAGE_METER_EVENT_NAME", "agentys_llm_overage")
    monkeypatch.setenv("STRIPE_USAGE_SYNC_ENABLED", "true")
    monkeypatch.setenv("STRIPE_USAGE_DRY_RUN", "false")

    from app.db.database import get_db_session
    from app.db.models import BillingSubscription, TokenUsageLogRow
    from app.infrastructure.cost_manager import reset_usage_context, set_usage_context
    from app.infrastructure.entitlement_gate import EntitlementGatedLLM

    with get_db_session() as session:
        session.add(
            BillingSubscription(
                user_id=42,
                stripe_subscription_id="sub_starter",
                stripe_customer_id="cus_test",
                stripe_price_id="price_starter",
                plan="starter",
                status="active",
                current_period_end=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=30),
                usage_billing_enabled=True,
            )
        )
        session.add(
            TokenUsageLogRow(
                account_id=None,
                user_id=42,
                agent="DrafterAgent",
                feature="drafting",
                model="claude-test",
                input_tokens=100,
                output_tokens=50,
                cost_usd=3.5,
                created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )

    class _Inner:
        def complete(self):
            return "ok"

    tokens = set_usage_context(user_id=42, feature="drafting")
    try:
        assert EntitlementGatedLLM(_Inner()).complete() == "ok"
    finally:
        reset_usage_context(tokens)


def test_llm_overage_meter_reports_only_delta_above_included_budget(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_meter")
    monkeypatch.setenv("STRIPE_LLM_OVERAGE_METER_EVENT_NAME", "agentys_llm_overage")
    monkeypatch.setenv("STRIPE_USAGE_SYNC_ENABLED", "true")
    monkeypatch.setenv("STRIPE_USAGE_DRY_RUN", "false")
    monkeypatch.setenv("STRIPE_AI_CREDIT_COST_USD", "0.01")
    monkeypatch.setenv("STRIPE_INCLUDED_CREDITS_STARTER", "350")

    from app.billing.usage_metering import report_llm_overage_if_needed
    from app.db.database import get_db_session
    from app.db.models import BillingSubscription, TokenUsageLogRow

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with get_db_session() as session:
        session.add(
            BillingSubscription(
                user_id=42,
                stripe_subscription_id="sub_starter",
                stripe_customer_id="cus_test",
                stripe_price_id="price_starter",
                plan="starter",
                status="active",
                current_period_start=now - timedelta(days=1),
                current_period_end=now + timedelta(days=30),
                usage_billing_enabled=True,
            )
        )
        session.add_all(
            [
                TokenUsageLogRow(
                    account_id=None,
                    user_id=42,
                    agent="DrafterAgent",
                    feature="drafting",
                    model="claude-test",
                    input_tokens=100,
                    output_tokens=50,
                    cost_usd=3.49,
                    created_at=now,
                ),
                TokenUsageLogRow(
                    account_id=None,
                    user_id=42,
                    agent="DrafterAgent",
                    feature="drafting",
                    model="claude-test",
                    input_tokens=100,
                    output_tokens=50,
                    cost_usd=0.03,
                    created_at=now,
                ),
            ]
        )

    meter_events = []

    class _MeterEvent:
        @staticmethod
        def create(**kwargs):
            meter_events.append(kwargs)
            return {"id": "mtr_test"}

    fake_stripe = SimpleNamespace(
        api_key=None,
        billing=SimpleNamespace(MeterEvent=_MeterEvent),
    )
    monkeypatch.setitem(sys.modules, "stripe", fake_stripe)

    record = SimpleNamespace(user_id=42, cost_usd=0.03, feature="drafting")

    assert report_llm_overage_if_needed(record) is True
    assert fake_stripe.api_key == "sk_test_meter"
    assert meter_events[0]["event_name"] == "agentys_llm_overage"
    assert meter_events[0]["payload"] == {
        "stripe_customer_id": "cus_test",
        "value": "2",
    }
    assert meter_events[0]["identifier"].startswith("agys_usage_")
