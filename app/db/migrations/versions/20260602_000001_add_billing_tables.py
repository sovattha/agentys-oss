# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Add billing tables for Stripe entitlements.

Revision ID: 034_billing_tables
Revises: 033_legal_consents
Create Date: 2026-06-02 00:00:01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "034_billing_tables"
down_revision: Union[str, None] = "033_legal_consents"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())

    if "billing_customers" not in existing:
        op.create_table(
            "billing_customers",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("user_id", sa.BigInteger(), nullable=False),
            sa.Column("email", sa.String(length=255), nullable=False),
            sa.Column("stripe_customer_id", sa.String(length=255), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_billing_customers_user_id", "billing_customers", ["user_id"], unique=True)
        op.create_index(
            "ix_billing_customers_stripe_customer_id",
            "billing_customers",
            ["stripe_customer_id"],
            unique=True,
        )

    if "billing_subscriptions" not in existing:
        op.create_table(
            "billing_subscriptions",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("user_id", sa.BigInteger(), nullable=False),
            sa.Column("stripe_customer_id", sa.String(length=255), nullable=True),
            sa.Column("stripe_subscription_id", sa.String(length=255), nullable=True),
            sa.Column("stripe_price_id", sa.String(length=255), nullable=True),
            sa.Column("plan", sa.String(length=32), nullable=False, server_default="free"),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="free"),
            sa.Column("current_period_end", sa.DateTime(), nullable=True),
            sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("user_id", name="uq_billing_subscriptions_user_id"),
            sa.UniqueConstraint(
                "stripe_subscription_id",
                name="uq_billing_subscriptions_stripe_subscription_id",
            ),
        )
        op.create_index("ix_billing_subscriptions_user_id", "billing_subscriptions", ["user_id"])
        op.create_index(
            "ix_billing_subscriptions_stripe_customer_id",
            "billing_subscriptions",
            ["stripe_customer_id"],
        )

    if "stripe_events" not in existing:
        op.create_table(
            "stripe_events",
            sa.Column("id", sa.String(length=255), primary_key=True, nullable=False),
            sa.Column("event_type", sa.String(length=255), nullable=False),
            sa.Column("processed_at", sa.DateTime(), nullable=False),
        )


def downgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())

    if "stripe_events" in existing:
        op.drop_table("stripe_events")
    if "billing_subscriptions" in existing:
        op.drop_index("ix_billing_subscriptions_stripe_customer_id", table_name="billing_subscriptions")
        op.drop_index("ix_billing_subscriptions_user_id", table_name="billing_subscriptions")
        op.drop_table("billing_subscriptions")
    if "billing_customers" in existing:
        op.drop_index("ix_billing_customers_stripe_customer_id", table_name="billing_customers")
        op.drop_index("ix_billing_customers_user_id", table_name="billing_customers")
        op.drop_table("billing_customers")
