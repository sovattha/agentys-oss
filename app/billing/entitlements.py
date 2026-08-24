# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Billing entitlement resolution for paid AI features."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.database import get_db_session
from app.db.models import Account, BillingSubscription, DictationUsageLogRow, TokenUsageLogRow


ACTIVE_AI_STATUSES = frozenset({"active", "trialing"})
LLM_CREDITS_PER_USD = 100
DICTATION_CREDITS_PER_MINUTE = 10

BillingLimitValue = int | float | None

PLAN_LIMITS: dict[str, dict[str, BillingLimitValue]] = {
    "free": {
        "deepgram_minutes_per_day": 0,
        "deepgram_active_days_per_month": 0,
        "deepgram_minutes_per_month": 0,
        "llm_monthly_budget_usd": 0.0,
    },
    "starter": {
        "deepgram_minutes_per_day": 1,
        "deepgram_active_days_per_month": None,
        "deepgram_minutes_per_month": None,
        "llm_monthly_budget_usd": 3.5,
    },
    "professional": {
        "deepgram_minutes_per_day": 20,
        "deepgram_active_days_per_month": 20,
        "deepgram_minutes_per_month": 400,
        "llm_monthly_budget_usd": 7.0,
    },
}

PLAN_ALIASES = {
    "pro": "professional",
    "professionnal": "professional",
}

FREE_TRIAL_LLM_MONTHLY_BUDGET_USD = 3.5


def limits_for_plan(plan: Optional[str]) -> dict[str, BillingLimitValue]:
    normalized = (plan or "free").lower()
    normalized = PLAN_ALIASES.get(normalized, normalized)
    return dict(PLAN_LIMITS.get(normalized, PLAN_LIMITS["free"]))


def limits_for_subscription_status(plan: Optional[str], status: str) -> dict[str, BillingLimitValue]:
    limits = limits_for_plan(plan)
    if (status or "").lower() == "trialing":
        current_budget = limits.get("llm_monthly_budget_usd")
        if isinstance(current_budget, (int, float)) and current_budget > 0:
            limits["llm_monthly_budget_usd"] = min(
                float(current_budget),
                FREE_TRIAL_LLM_MONTHLY_BUDGET_USD,
            )
    return limits


class EntitlementRequiredError(RuntimeError):
    """Raised when a user without an active paid plan attempts an AI feature."""

    def __init__(self, entitlement: "BillingEntitlement"):
        self.entitlement = entitlement
        super().__init__(entitlement.reason)


@dataclass(frozen=True)
class BillingEntitlement:
    """Computed feature entitlement returned to API and backend callers."""

    plan: str
    subscription_status: str
    ai_enabled: bool
    reason: str
    limits: dict[str, BillingLimitValue] = field(default_factory=lambda: limits_for_plan("free"))
    user_id: Optional[int] = None
    stripe_customer_id: Optional[str] = None
    stripe_subscription_id: Optional[str] = None
    current_period_end: Optional[str] = None
    cancel_at_period_end: bool = False
    usage_billing_enabled: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


class BillingEntitlementService:
    """Resolves paid AI access from locally synchronized Stripe state."""

    def get_for_user(self, user_id: Optional[int], session: Optional[Session] = None) -> BillingEntitlement:
        if user_id is None:
            return self._free(None, "missing_user")

        def _resolve(sess: Session) -> BillingEntitlement:
            subscription = sess.execute(
                select(BillingSubscription).where(BillingSubscription.user_id == int(user_id))
            ).scalar_one_or_none()
            return self._from_subscription(int(user_id), subscription)

        if session is not None:
            return _resolve(session)

        with get_db_session() as sess:
            return _resolve(sess)

    def get_for_account(self, account_id: Optional[int], session: Optional[Session] = None) -> BillingEntitlement:
        if account_id is None:
            return self._free(None, "missing_account")

        def _resolve(sess: Session) -> BillingEntitlement:
            account = sess.get(Account, int(account_id))
            if account is None:
                return self._free(None, "account_not_found")
            return self.get_for_user(account.user_id, sess)

        if session is not None:
            return _resolve(session)

        with get_db_session() as sess:
            return _resolve(sess)

    def get_credit_usage(self, user_id: Optional[int], session: Optional[Session] = None) -> dict:
        def _resolve(sess: Session) -> dict:
            entitlement = self.get_for_user(user_id, sess)
            return {
                "llm": self._llm_credit_usage(sess, entitlement),
                "dictation": self._dictation_credit_usage(sess, entitlement),
            }

        if session is not None:
            return _resolve(session)

        with get_db_session() as sess:
            return _resolve(sess)

    def get_llm_credit_usage(self, user_id: Optional[int], session: Optional[Session] = None) -> dict:
        return self.get_credit_usage(user_id, session)

    def assert_ai_allowed(
        self,
        *,
        user_id: Optional[int] = None,
        account_id: Optional[int] = None,
        session: Optional[Session] = None,
        enforce_llm_budget: bool = False,
    ) -> BillingEntitlement:
        entitlement = (
            self.get_for_user(user_id, session)
            if user_id is not None
            else self.get_for_account(account_id, session)
        )
        if not entitlement.ai_enabled:
            raise EntitlementRequiredError(entitlement)
        if enforce_llm_budget and self._llm_budget_exceeded(entitlement, session):
            if self._usage_billing_allowed(entitlement):
                return replace(entitlement, reason="usage_billing")
            raise EntitlementRequiredError(
                replace(entitlement, ai_enabled=False, reason="llm_monthly_budget_exceeded")
            )
        return entitlement

    @staticmethod
    def _free(user_id: Optional[int], reason: str) -> BillingEntitlement:
        return BillingEntitlement(
            plan="free",
            subscription_status="none",
            ai_enabled=False,
            reason=reason,
            limits=limits_for_plan("free"),
            user_id=user_id,
        )

    def _from_subscription(
        self,
        user_id: int,
        subscription: Optional[BillingSubscription],
    ) -> BillingEntitlement:
        if subscription is None:
            return self._free(user_id, "no_active_subscription")

        status = (subscription.status or "free").lower()
        current_period_end = self._serialize_dt(subscription.current_period_end)
        period_active = self._period_active(subscription.current_period_end)
        ai_enabled = status in ACTIVE_AI_STATUSES and period_active
        if ai_enabled:
            reason = "active"
        elif status not in ACTIVE_AI_STATUSES:
            reason = f"subscription_{status}"
        else:
            reason = "subscription_period_ended"

        return BillingEntitlement(
            plan=subscription.plan or "free",
            subscription_status=status,
            ai_enabled=ai_enabled,
            reason=reason,
            limits=limits_for_subscription_status(subscription.plan, status),
            user_id=user_id,
            stripe_customer_id=subscription.stripe_customer_id,
            stripe_subscription_id=subscription.stripe_subscription_id,
            current_period_end=current_period_end,
            cancel_at_period_end=bool(subscription.cancel_at_period_end),
            usage_billing_enabled=self._usage_billing_allowed_for_status(
                status=status,
                stripe_customer_id=subscription.stripe_customer_id,
                subscription_usage_billing_enabled=bool(subscription.usage_billing_enabled),
            ),
        )

    @staticmethod
    def _period_active(value: Optional[datetime]) -> bool:
        if value is None:
            return True
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value > datetime.now(timezone.utc)

    def _llm_budget_exceeded(
        self,
        entitlement: BillingEntitlement,
        session: Optional[Session],
    ) -> bool:
        budget = entitlement.limits.get("llm_monthly_budget_usd")
        if entitlement.user_id is None or not isinstance(budget, (int, float)) or budget <= 0:
            return False

        def _spent(sess: Session) -> float:
            month_start, _next_month_start = self._current_month_bounds()
            return self._monthly_llm_spend_usd(sess, int(entitlement.user_id), month_start)

        spent = _spent(session) if session is not None else 0.0
        if session is None:
            with get_db_session() as sess:
                spent = _spent(sess)
        return spent >= float(budget)

    def _usage_billing_allowed(self, entitlement: BillingEntitlement) -> bool:
        return self._usage_billing_allowed_for_status(
            status=entitlement.subscription_status,
            stripe_customer_id=entitlement.stripe_customer_id,
            subscription_usage_billing_enabled=entitlement.usage_billing_enabled,
        )

    @staticmethod
    def _usage_billing_allowed_for_status(
        *,
        status: str,
        stripe_customer_id: Optional[str],
        subscription_usage_billing_enabled: bool,
    ) -> bool:
        if (
            not subscription_usage_billing_enabled
            or (status or "").lower() != "active"
            or not stripe_customer_id
        ):
            return False
        try:
            from app.billing.usage_metering import is_llm_overage_metering_configured

            return is_llm_overage_metering_configured()
        except Exception:
            return False

    @staticmethod
    def _serialize_dt(value: Optional[datetime]) -> Optional[str]:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()

    @staticmethod
    def _current_month_bounds() -> tuple[datetime, datetime]:
        month_start = datetime.now(timezone.utc).replace(
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        if month_start.month == 12:
            next_month_start = month_start.replace(year=month_start.year + 1, month=1)
        else:
            next_month_start = month_start.replace(month=month_start.month + 1)
        return month_start, next_month_start

    @staticmethod
    def _current_day_bounds() -> tuple[datetime, datetime]:
        day_start = datetime.now(timezone.utc).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        return day_start, day_start + timedelta(days=1)

    def _llm_credit_usage(self, sess: Session, entitlement: BillingEntitlement) -> dict:
        budget_usd = entitlement.limits.get("llm_monthly_budget_usd")
        included_usd = float(budget_usd) if isinstance(budget_usd, (int, float)) and budget_usd > 0 else 0.0
        month_start, next_month_start = self._current_month_bounds()
        spent_usd = (
            self._monthly_llm_spend_usd(sess, int(entitlement.user_id), month_start)
            if entitlement.user_id is not None
            else 0.0
        )
        included_credits = self._credits_in_budget(included_usd)
        used_credits = self._credits_from_usd(spent_usd)
        return {
            "included_credits": included_credits,
            "used_credits": used_credits,
            "remaining_credits": max(0, included_credits - used_credits),
            "overage_credits": max(0, used_credits - included_credits),
            "resets_at": next_month_start.isoformat(),
            "usage_billing_enabled": entitlement.usage_billing_enabled,
        }

    def _dictation_credit_usage(self, sess: Session, entitlement: BillingEntitlement) -> dict:
        monthly_minutes = entitlement.limits.get("deepgram_minutes_per_month")
        daily_minutes = entitlement.limits.get("deepgram_minutes_per_day")
        if isinstance(monthly_minutes, (int, float)) and monthly_minutes > 0:
            included_minutes = float(monthly_minutes)
            window = "month"
            window_start, window_end = self._current_month_bounds()
        else:
            included_minutes = float(daily_minutes) if isinstance(daily_minutes, (int, float)) and daily_minutes > 0 else 0.0
            window = "day"
            window_start, window_end = self._current_day_bounds()

        duration_seconds = (
            self._dictation_duration_seconds(sess, int(entitlement.user_id), window_start)
            if entitlement.user_id is not None
            else 0
        )
        included_credits = self._dictation_credits_from_minutes(included_minutes)
        used_credits = self._dictation_credits_from_seconds(duration_seconds)
        return {
            "included_credits": included_credits,
            "used_credits": used_credits,
            "remaining_credits": max(0, included_credits - used_credits),
            "overage_credits": max(0, used_credits - included_credits),
            "resets_at": window_end.isoformat(),
            "window": window,
        }

    @staticmethod
    def _monthly_llm_spend_usd(sess: Session, user_id: int, month_start: datetime) -> float:
        stmt = (
            select(func.coalesce(func.sum(TokenUsageLogRow.cost_usd), 0.0))
            .where(TokenUsageLogRow.user_id == int(user_id))
            .where(TokenUsageLogRow.created_at >= month_start.replace(tzinfo=None))
        )
        return float(sess.execute(stmt).scalar() or 0.0)

    @staticmethod
    def _dictation_duration_seconds(sess: Session, user_id: int, window_start: datetime) -> int:
        stmt = (
            select(func.coalesce(func.sum(DictationUsageLogRow.duration_seconds), 0))
            .where(DictationUsageLogRow.user_id == int(user_id))
            .where(DictationUsageLogRow.created_at >= window_start.replace(tzinfo=None))
        )
        return int(sess.execute(stmt).scalar() or 0)

    @staticmethod
    def _credits_in_budget(value_usd: float) -> int:
        return int(round(max(0.0, value_usd) * LLM_CREDITS_PER_USD))

    @staticmethod
    def _credits_from_usd(value_usd: float) -> int:
        if value_usd <= 0:
            return 0
        return int(math.ceil(round(value_usd * LLM_CREDITS_PER_USD, 6)))

    @staticmethod
    def _dictation_credits_from_minutes(value_minutes: float) -> int:
        return int(round(max(0.0, value_minutes) * DICTATION_CREDITS_PER_MINUTE))

    @staticmethod
    def _dictation_credits_from_seconds(value_seconds: int) -> int:
        if value_seconds <= 0:
            return 0
        return int(math.ceil((value_seconds / 60) * DICTATION_CREDITS_PER_MINUTE))
