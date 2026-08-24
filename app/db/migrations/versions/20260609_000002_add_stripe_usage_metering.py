# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Add Stripe usage metering audit tables.

Revision ID: 036_stripe_usage_metering
Revises: 035_usage_billing_flag
Create Date: 2026-06-09 00:00:02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "036_stripe_usage_metering"
down_revision: Union[str, None] = "035_usage_billing_flag"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table_name: str) -> set[str]:
    if table_name not in _tables():
        return set()
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _indexes(table_name: str) -> set[str]:
    if table_name not in _tables():
        return set()
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table_name)}


def upgrade() -> None:
    if "billing_subscriptions" in _tables():
        columns = _columns("billing_subscriptions")
        if "stripe_usage_price_id" not in columns:
            op.add_column(
                "billing_subscriptions",
                sa.Column("stripe_usage_price_id", sa.String(length=255), nullable=True),
            )
        if "current_period_start" not in columns:
            op.add_column(
                "billing_subscriptions",
                sa.Column("current_period_start", sa.DateTime(), nullable=True),
            )

    if "stripe_usage_meter_events" not in _tables():
        op.create_table(
            "stripe_usage_meter_events",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("user_id", sa.BigInteger(), nullable=False),
            sa.Column("stripe_customer_id", sa.String(length=255), nullable=False),
            sa.Column("stripe_subscription_id", sa.String(length=255), nullable=True),
            sa.Column("billing_period_start", sa.DateTime(), nullable=False),
            sa.Column("billing_period_end", sa.DateTime(), nullable=True),
            sa.Column("usage_window_start", sa.DateTime(), nullable=False),
            sa.Column("usage_window_end", sa.DateTime(), nullable=False),
            sa.Column("event_name", sa.String(length=100), nullable=False),
            sa.Column("stripe_identifier", sa.String(length=100), nullable=False),
            sa.Column("included_credits", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("used_credits", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("previously_metered_credits", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("metered_credits", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("stripe_event_id", sa.String(length=255), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("sent_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint(
                "stripe_identifier",
                name="uq_stripe_usage_meter_events_identifier",
            ),
        )

    indexes = _indexes("stripe_usage_meter_events")
    if "ix_stripe_usage_meter_events_user_id" not in indexes:
        op.create_index("ix_stripe_usage_meter_events_user_id", "stripe_usage_meter_events", ["user_id"])
    if "ix_stripe_usage_meter_events_stripe_customer_id" not in indexes:
        op.create_index(
            "ix_stripe_usage_meter_events_stripe_customer_id",
            "stripe_usage_meter_events",
            ["stripe_customer_id"],
        )
    if "ix_stripe_usage_meter_events_stripe_subscription_id" not in indexes:
        op.create_index(
            "ix_stripe_usage_meter_events_stripe_subscription_id",
            "stripe_usage_meter_events",
            ["stripe_subscription_id"],
        )
    if "ix_stripe_usage_meter_events_user_period" not in indexes:
        op.create_index(
            "ix_stripe_usage_meter_events_user_period",
            "stripe_usage_meter_events",
            ["user_id", "billing_period_start"],
        )
    if "ix_stripe_usage_meter_events_status_created" not in indexes:
        op.create_index(
            "ix_stripe_usage_meter_events_status_created",
            "stripe_usage_meter_events",
            ["status", "created_at"],
        )


def downgrade() -> None:
    if "stripe_usage_meter_events" in _tables():
        indexes = _indexes("stripe_usage_meter_events")
        for index_name in (
            "ix_stripe_usage_meter_events_status_created",
            "ix_stripe_usage_meter_events_user_period",
            "ix_stripe_usage_meter_events_stripe_subscription_id",
            "ix_stripe_usage_meter_events_stripe_customer_id",
            "ix_stripe_usage_meter_events_user_id",
        ):
            if index_name in indexes:
                op.drop_index(index_name, table_name="stripe_usage_meter_events")
        op.drop_table("stripe_usage_meter_events")

    if "billing_subscriptions" in _tables():
        columns = _columns("billing_subscriptions")
        if "current_period_start" in columns:
            op.drop_column("billing_subscriptions", "current_period_start")
        if "stripe_usage_price_id" in columns:
            op.drop_column("billing_subscriptions", "stripe_usage_price_id")
