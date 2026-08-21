"""Usage-based billing for AI credit overages."""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.billing.entitlements import ACTIVE_AI_STATUSES
from app.billing.stripe_sync import object_get
from app.db.database import get_db_session
from app.db.models import BillingSubscription, StripeUsageMeterEvent
from app.db.repositories.token_usage_log_repository import TokenUsageLogRepository


logger = logging.getLogger(__name__)

DEFAULT_AI_CREDIT_COST_USD = Decimal("0.00861")
DEFAULT_AI_CREDIT_PRICE_USD = Decimal("0.03")
DEFAULT_USAGE_EVENT_NAME = "agentys_ai_credit_overage"
DEFAULT_INCLUDED_CREDITS = {
    "starter": 425,
    "professional": 850,
}


@dataclass(frozen=True)
class UsageMeteringConfig:
    event_name: str = DEFAULT_USAGE_EVENT_NAME
    credit_cost_usd: Decimal = DEFAULT_AI_CREDIT_COST_USD
    credit_price_usd: Decimal = DEFAULT_AI_CREDIT_PRICE_USD
    starter_included_credits: int = DEFAULT_INCLUDED_CREDITS["starter"]
    professional_included_credits: int = DEFAULT_INCLUDED_CREDITS["professional"]
    enabled: bool = False
    dry_run: bool = True

    @classmethod
    def from_env(cls) -> "UsageMeteringConfig":
        return cls(
            event_name=_env_first(
                "STRIPE_LLM_OVERAGE_METER_EVENT_NAME",
                "STRIPE_AI_CREDIT_METER_EVENT_NAME",
                default=DEFAULT_USAGE_EVENT_NAME,
            ),
            credit_cost_usd=_env_decimal("STRIPE_AI_CREDIT_COST_USD", DEFAULT_AI_CREDIT_COST_USD),
            credit_price_usd=_env_decimal("STRIPE_AI_CREDIT_PRICE_USD", DEFAULT_AI_CREDIT_PRICE_USD),
            starter_included_credits=_env_int(
                "STRIPE_INCLUDED_CREDITS_STARTER",
                DEFAULT_INCLUDED_CREDITS["starter"],
            ),
            professional_included_credits=_env_int(
                "STRIPE_INCLUDED_CREDITS_PROFESSIONAL",
                DEFAULT_INCLUDED_CREDITS["professional"],
            ),
            enabled=_env_bool("STRIPE_USAGE_SYNC_ENABLED", False),
            dry_run=_env_bool("STRIPE_USAGE_DRY_RUN", True),
        )

    def included_credits_for_plan(self, plan: str) -> int:
        normalized = (plan or "free").lower()
        if normalized == "starter":
            return self.starter_included_credits
        if normalized in {"professional", "pro"}:
            return self.professional_included_credits
        return 0


def is_llm_overage_metering_configured() -> bool:
    """Compatibility probe for older entitlement checks."""
    config = UsageMeteringConfig.from_env()
    return bool(
        os.environ.get("STRIPE_SECRET_KEY", "").strip()
        and config.event_name
        and config.enabled
        and not config.dry_run
    )


def report_llm_overage_if_needed(record: Any) -> bool:
    """Compatibility hook that delegates to the audited usage sync.

    Older call sites invoked this after persisting an LLM usage row. The current
    implementation still keeps the LLM path non-blocking, but uses the audited
    period-based sync so repeated calls cannot double-report already metered
    credits.
    """
    user_id = getattr(record, "user_id", None)
    if user_id is None or not is_llm_overage_metering_configured():
        return False
    try:
        with get_db_session() as session:
            results = StripeUsageMeteringService(session).sync_active_subscriptions(user_id=int(user_id))
            return any(result.status == "sent" and result.metered_credits > 0 for result in results)
    except Exception:
        logger.warning("[BILLING] LLM overage compatibility sync skipped", exc_info=True)
        return False


@dataclass(frozen=True)
class UsageMeteringResult:
    user_id: int
    plan: str
    status: str
    reason: str
    cost_usd: float = 0.0
    included_credits: int = 0
    used_credits: int = 0
    previously_metered_credits: int = 0
    metered_credits: int = 0
    stripe_customer_id: Optional[str] = None
    stripe_subscription_id: Optional[str] = None
    stripe_identifier: Optional[str] = None
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "plan": self.plan,
            "status": self.status,
            "reason": self.reason,
            "cost_usd": self.cost_usd,
            "included_credits": self.included_credits,
            "used_credits": self.used_credits,
            "previously_metered_credits": self.previously_metered_credits,
            "metered_credits": self.metered_credits,
            "stripe_customer_id": self.stripe_customer_id,
            "stripe_subscription_id": self.stripe_subscription_id,
            "stripe_identifier": self.stripe_identifier,
            "period_start": _iso_or_none(self.period_start),
            "period_end": _iso_or_none(self.period_end),
        }


class StripeUsageMeteringService:
    """Calculates AI credit overages and sends Stripe meter events."""

    def __init__(
        self,
        session: Session,
        *,
        stripe_client: Optional[Any] = None,
        config: Optional[UsageMeteringConfig] = None,
        now: Optional[datetime] = None,
    ) -> None:
        self._session = session
        self._stripe = stripe_client
        self._config = config or UsageMeteringConfig.from_env()
        self._now = _aware_utc(now) if now is not None else datetime.now(timezone.utc)

    @property
    def config(self) -> UsageMeteringConfig:
        return self._config

    def sync_active_subscriptions(
        self,
        *,
        dry_run: Optional[bool] = None,
        user_id: Optional[int] = None,
    ) -> list[UsageMeteringResult]:
        effective_dry_run = self._effective_dry_run(dry_run)
        stmt = (
            select(BillingSubscription)
            .where(BillingSubscription.status.in_(ACTIVE_AI_STATUSES))
            .where(BillingSubscription.stripe_customer_id.isnot(None))
            .where(BillingSubscription.plan.in_(("starter", "professional")))
            .order_by(BillingSubscription.user_id)
        )
        if user_id is not None:
            stmt = stmt.where(BillingSubscription.user_id == int(user_id))

        results: list[UsageMeteringResult] = []
        for subscription in self._session.execute(stmt).scalars().all():
            planned = self.calculate_subscription_overage(subscription)
            if planned.metered_credits <= 0:
                results.append(planned)
                continue
            if effective_dry_run:
                results.append(
                    _replace_result(
                        planned,
                        status="dry_run",
                        reason="sync_disabled" if not self._config.enabled else "dry_run",
                    )
                )
                continue
            results.append(self._persist_and_send(planned))
        return results

    def calculate_subscription_overage(
        self,
        subscription: BillingSubscription,
    ) -> UsageMeteringResult:
        user_id = int(subscription.user_id)
        plan = (subscription.plan or "free").lower()
        period_start = _naive_utc(subscription.current_period_start)
        period_end = _naive_utc(subscription.current_period_end)
        if period_start is None:
            return UsageMeteringResult(
                user_id=user_id,
                plan=plan,
                status="skipped",
                reason="missing_period_start",
                stripe_customer_id=subscription.stripe_customer_id,
                stripe_subscription_id=subscription.stripe_subscription_id,
                period_end=period_end,
            )

        usage_end = _naive_utc(self._now)
        if period_end is not None and period_end < usage_end:
            usage_end = period_end
        if usage_end <= period_start:
            return UsageMeteringResult(
                user_id=user_id,
                plan=plan,
                status="skipped",
                reason="inactive_period",
                stripe_customer_id=subscription.stripe_customer_id,
                stripe_subscription_id=subscription.stripe_subscription_id,
                period_start=period_start,
                period_end=period_end,
            )

        usage = TokenUsageLogRepository(self._session).cost_for_user_period(
            user_id=user_id,
            start=period_start,
            end=usage_end,
        )
        included_credits = self._config.included_credits_for_plan(plan)
        used_credits = credits_for_cost(usage["cost_usd"], self._config.credit_cost_usd)
        overage_to_date = max(0, used_credits - included_credits)
        previously_metered = self._already_metered_credits(subscription, period_start)
        metered_credits = max(0, overage_to_date - previously_metered)
        reason = "overage_due" if metered_credits > 0 else "within_included_credits"
        return UsageMeteringResult(
            user_id=user_id,
            plan=plan,
            status="planned" if metered_credits > 0 else "skipped",
            reason=reason,
            cost_usd=float(usage["cost_usd"]),
            included_credits=included_credits,
            used_credits=used_credits,
            previously_metered_credits=previously_metered,
            metered_credits=metered_credits,
            stripe_customer_id=subscription.stripe_customer_id,
            stripe_subscription_id=subscription.stripe_subscription_id,
            stripe_identifier=_stripe_identifier(subscription, period_start, used_credits, previously_metered),
            period_start=period_start,
            period_end=period_end,
        )

    def _persist_and_send(self, planned: UsageMeteringResult) -> UsageMeteringResult:
        existing = self._session.execute(
            select(StripeUsageMeterEvent).where(
                StripeUsageMeterEvent.stripe_identifier == planned.stripe_identifier
            )
        ).scalar_one_or_none()
        if existing is not None and existing.status == "sent":
            return _replace_result(planned, status="skipped", reason="already_sent")

        row = existing or StripeUsageMeterEvent(
            user_id=planned.user_id,
            stripe_customer_id=planned.stripe_customer_id or "",
            stripe_subscription_id=planned.stripe_subscription_id,
            billing_period_start=planned.period_start,
            billing_period_end=planned.period_end,
            usage_window_start=planned.period_start,
            usage_window_end=_naive_utc(self._now),
            event_name=self._config.event_name,
            stripe_identifier=planned.stripe_identifier or _random_identifier(),
            included_credits=planned.included_credits,
            used_credits=planned.used_credits,
            previously_metered_credits=planned.previously_metered_credits,
            metered_credits=planned.metered_credits,
            cost_usd=planned.cost_usd,
        )
        if existing is None:
            self._session.add(row)

        row.status = "pending"
        row.last_error = None
        self._session.flush()

        try:
            meter_event = self._stripe_client().billing.MeterEvent.create(
                event_name=self._config.event_name,
                payload={
                    "stripe_customer_id": planned.stripe_customer_id,
                    "value": str(planned.metered_credits),
                },
                identifier=row.stripe_identifier,
                timestamp=int(self._now.timestamp()),
            )
        except Exception as exc:
            logger.warning(
                "[BILLING] Stripe usage meter event failed for user %s: %s",
                planned.user_id,
                exc,
            )
            row.status = "failed"
            row.last_error = str(exc)[:2000]
            return _replace_result(planned, status="failed", reason="stripe_error")

        row.status = "sent"
        row.stripe_event_id = str(object_get(meter_event, "id") or object_get(meter_event, "identifier") or "")
        row.sent_at = _naive_utc(self._now)
        return _replace_result(planned, status="sent", reason="sent", stripe_identifier=row.stripe_identifier)

    def _already_metered_credits(
        self,
        subscription: BillingSubscription,
        period_start: datetime,
    ) -> int:
        stmt = select(func.sum(StripeUsageMeterEvent.metered_credits)).where(
            StripeUsageMeterEvent.user_id == int(subscription.user_id),
            StripeUsageMeterEvent.billing_period_start == period_start,
            StripeUsageMeterEvent.status.in_(("pending", "sent")),
        )
        if subscription.stripe_subscription_id:
            stmt = stmt.where(
                StripeUsageMeterEvent.stripe_subscription_id == subscription.stripe_subscription_id
            )
        total = self._session.execute(stmt).scalar()
        return int(total or 0)

    def _effective_dry_run(self, dry_run: Optional[bool]) -> bool:
        if not self._config.enabled:
            return True
        if dry_run is not None:
            return bool(dry_run)
        return self._config.dry_run

    def _stripe_client(self) -> Any:
        if self._stripe is not None:
            return self._stripe
        import stripe

        api_key = os.environ.get("STRIPE_SECRET_KEY", "").strip()
        if not api_key:
            raise RuntimeError("STRIPE_SECRET_KEY is required for Stripe usage metering")
        stripe.api_key = api_key
        self._stripe = stripe
        return self._stripe


def credits_for_cost(cost_usd: float | Decimal, credit_cost_usd: Decimal = DEFAULT_AI_CREDIT_COST_USD) -> int:
    cost = Decimal(str(cost_usd or 0))
    if cost <= 0:
        return 0
    return int((cost / credit_cost_usd).to_integral_value(rounding=ROUND_CEILING))


def _stripe_identifier(
    subscription: BillingSubscription,
    period_start: datetime,
    used_credits: int,
    previously_metered_credits: int,
) -> str:
    subscription_key = subscription.stripe_subscription_id or f"user_{subscription.user_id}"
    seed = f"{subscription_key}:{period_start.isoformat()}:{used_credits}:{previously_metered_credits}"
    return f"agys_usage_{uuid.uuid5(uuid.NAMESPACE_URL, seed).hex}"


def _random_identifier() -> str:
    return f"agys_usage_{uuid.uuid4().hex}"


def _replace_result(result: UsageMeteringResult, **changes: Any) -> UsageMeteringResult:
    data = result.__dict__.copy()
    data.update(changes)
    return UsageMeteringResult(**data)


def _env_first(*names: str, default: str) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return default


def _env_decimal(name: str, default: Decimal) -> Decimal:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = Decimal(raw.strip())
    except (InvalidOperation, ValueError):
        logger.warning("[BILLING] Invalid decimal env %s=%r; using %s", name, raw, default)
        return default
    return value if value > 0 else default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        logger.warning("[BILLING] Invalid int env %s=%r; using %s", name, raw, default)
        return default
    return value if value >= 0 else default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _aware_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _naive_utc(value: Optional[datetime]) -> Optional[datetime]:
    aware = _aware_utc(value)
    if aware is None:
        return None
    return aware.replace(tzinfo=None)


def _iso_or_none(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    aware = _aware_utc(value)
    return aware.isoformat() if aware is not None else None
