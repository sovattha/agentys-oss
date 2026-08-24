# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Billing state synchronized from Stripe."""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, TimestampMixin


class BillingCustomer(Base, TimestampMixin):
    """Stripe customer linked to an Agentys authenticated user."""

    __tablename__ = "billing_customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    stripe_customer_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)


class BillingSubscription(Base, TimestampMixin):
    """Current subscription entitlement for one Agentys user."""

    __tablename__ = "billing_subscriptions"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_billing_subscriptions_user_id"),
        UniqueConstraint("stripe_subscription_id", name="uq_billing_subscriptions_stripe_subscription_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    stripe_subscription_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    stripe_price_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    stripe_usage_price_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    plan: Mapped[str] = mapped_column(String(32), nullable=False, default="free", server_default="free")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="free", server_default="free")
    current_period_start: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    current_period_end: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    usage_billing_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")


class StripeUsageMeterEvent(Base, TimestampMixin):
    """Meter event audit row for AI credit overage billing."""

    __tablename__ = "stripe_usage_meter_events"
    __table_args__ = (
        UniqueConstraint("stripe_identifier", name="uq_stripe_usage_meter_events_identifier"),
        Index("ix_stripe_usage_meter_events_user_period", "user_id", "billing_period_start"),
        Index("ix_stripe_usage_meter_events_status_created", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    stripe_customer_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    stripe_subscription_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    billing_period_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    billing_period_end: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    usage_window_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    usage_window_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    event_name: Mapped[str] = mapped_column(String(100), nullable=False)
    stripe_identifier: Mapped[str] = mapped_column(String(100), nullable=False)
    included_credits: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    used_credits: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    previously_metered_credits: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    metered_credits: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", server_default="pending")
    stripe_event_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class StripeEvent(Base):
    """Processed Stripe webhook event for idempotency."""

    __tablename__ = "stripe_events"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(255), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class Ambassador(Base, TimestampMixin):
    """An Agentys user enrolled in the referral / ambassador program.

    Table préfixée ``ambassadors`` pour ne pas entrer en collision avec la
    table legacy ``referrals`` du SCHEMA SQLite historique.
    """

    __tablename__ = "ambassadors"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True, index=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    stripe_coupon_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    stripe_promotion_code_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", server_default="active")


class Referral(Base, TimestampMixin):
    """A referred customer attached to an ambassador via their promo code."""

    __tablename__ = "ambassador_referrals"
    __table_args__ = (
        UniqueConstraint("referred_stripe_customer_id", name="uq_ambassador_referrals_customer"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ambassador_id: Mapped[int] = mapped_column(ForeignKey("ambassadors.id"), nullable=False, index=True)
    referred_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    referred_stripe_customer_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    signed_up_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    commission_window_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ReferralCommission(Base, TimestampMixin):
    """A commission owed to an ambassador for one paid invoice of a referral.

    ``stripe_invoice_id`` is unique: it makes ``invoice.paid`` processing
    idempotent even if Stripe redelivers the same event.
    """

    __tablename__ = "ambassador_commissions"
    __table_args__ = (
        UniqueConstraint("stripe_invoice_id", name="uq_ambassador_commissions_invoice"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    referral_id: Mapped[int] = mapped_column(ForeignKey("ambassador_referrals.id"), nullable=False, index=True)
    stripe_invoice_id: Mapped[str] = mapped_column(String(255), nullable=False)
    amount_net: Mapped[int] = mapped_column(BigInteger, nullable=False)
    commission_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", server_default="pending")
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
