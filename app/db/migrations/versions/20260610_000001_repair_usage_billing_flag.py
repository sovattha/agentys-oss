# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Repair missing usage billing flag on stamped production databases.

Revision ID: 037_repair_usage_billing_flag
Revises: 036_dictation_usage_log
Create Date: 2026-06-10 00:00:01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "037_repair_usage_billing_flag"
down_revision: Union[str, None] = "036_dictation_usage_log"
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
    # No-op by design: 035_usage_billing_flag already owns this column. This
    # repair revision only heals databases that were stamped past 035 without
    # the actual column.
    return
