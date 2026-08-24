# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Add quick_step_executions table for cross-worker idempotency.

The original engine kept idempotency cache in a process-local dict, which
loses correctness under multiple gunicorn workers — worker A puts a key,
worker B's lookup misses, the chain runs twice. SQLite-backed cache fixes
that. TTL eviction is opportunistic on read (no background sweeper).

Schema kept lean: one row per (account_id, idempotency_key) with the
serialized ExecutionReport. Composite unique constraint enforces dedupe;
created_at index supports the cheap range delete used for TTL cleanup.

Revision ID: 023_add_quick_step_executions
Revises: 022_merge_021_heads
Create Date: 2026-05-07 00:00:02

Chained after the merge revision so the alembic graph stays linear (the
merge consolidated the three parallel ``021_*`` heads). Was originally
authored as ``022_add_quick_step_executions`` descending from
``021_add_quick_steps`` — that re-forked the chain and re-introduced
the multi-head deploy block. Renumbered + re-parented during audit
follow-up (cf. F-01 in tasks/audit-reports/2026-05-06_1245_regressions/).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "023_add_quick_step_executions"
down_revision: Union[str, None] = "022_merge_021_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "quick_step_executions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("report_json", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "account_id", "idempotency_key",
            name="uq_quick_step_executions_account_key",
        ),
    )
    op.create_index(
        "ix_quick_step_executions_created_at",
        "quick_step_executions",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_quick_step_executions_created_at",
        table_name="quick_step_executions",
    )
    op.drop_table("quick_step_executions")
