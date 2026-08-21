"""Add token_usage_log table — queryable per-(user, agent, day) cost breakdown.

The audit 2026-05-05 wired the LegacyTokenCounterAdapter into the request
path, but the data still lived in-memory only. Operators couldn't answer
"how much did this user spend yesterday?" without grepping log files.

This table closes that gap. Every LLM completion writes one row with
(account_id, agent, model, input_tokens, output_tokens, cost_usd, ts).
A composite (account_id, ts) index keeps the per-user-per-day rollup
cheap; (agent, ts) supports the per-agent breakdown the admin dashboard
needs.

Schema notes:
- ``account_id`` is nullable so background processes that have no caller
  scope (sentinel-like jobs) still produce rows. Per-user reports filter
  ``account_id IS NOT NULL``.
- ``cost_usd`` is computed at write-time (using MODEL_COSTS) so reports
  don't need to re-look up prices when historical pricing changed.
- No FK to accounts.id intentionally — keep this table append-only and
  resilient to account deletions; queries left-join when needed.

Revision ID: 021_add_token_usage_log
Revises: 020_add_draft_feedback
Create Date: 2026-05-06 00:00:01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "021_add_token_usage_log"
down_revision: Union[str, None] = "020_add_draft_feedback"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "token_usage_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        # Nullable: background paths without caller scope still log.
        sa.Column("account_id", sa.Integer(), nullable=True, index=True),
        sa.Column("agent", sa.String(length=64), nullable=False, index=True),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        # Computed at write-time so historical rollups are pricing-stable.
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_token_usage_log_account_created",
        "token_usage_log",
        ["account_id", "created_at"],
    )
    op.create_index(
        "ix_token_usage_log_agent_created",
        "token_usage_log",
        ["agent", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_token_usage_log_agent_created", table_name="token_usage_log")
    op.drop_index("ix_token_usage_log_account_created", table_name="token_usage_log")
    op.drop_table("token_usage_log")
