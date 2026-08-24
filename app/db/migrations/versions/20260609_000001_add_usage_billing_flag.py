# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Add usage billing flag to Stripe subscriptions.

Revision ID: 035_usage_billing_flag
Revises: 035_backfill_haiku45_costs
Create Date: 2026-06-09 00:00:01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "035_usage_billing_flag"
down_revision: Union[str, None] = "035_backfill_haiku45_costs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    if table_name not in set(sa.inspect(bind).get_table_names()):
        return set()
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def upgrade() -> None:
    if "billing_subscriptions" not in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    if "usage_billing_enabled" in _columns("billing_subscriptions"):
        return
    op.add_column(
        "billing_subscriptions",
        sa.Column("usage_billing_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    if "usage_billing_enabled" not in _columns("billing_subscriptions"):
        return
    op.drop_column("billing_subscriptions", "usage_billing_enabled")
