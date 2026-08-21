"""Add dictation usage log for billing credits.

Revision ID: 036_dictation_usage_log
Revises: 036_stripe_usage_metering
Create Date: 2026-06-09 00:00:02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "036_dictation_usage_log"
down_revision: Union[str, None] = "036_stripe_usage_metering"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_names() -> set[str]:
    bind = op.get_bind()
    return set(sa.inspect(bind).get_table_names())


def upgrade() -> None:
    if "dictation_usage_log" in _table_names():
        return

    op.create_table(
        "dictation_usage_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_dictation_usage_log_user_created",
        "dictation_usage_log",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_dictation_usage_log_account_created",
        "dictation_usage_log",
        ["account_id", "created_at"],
    )


def downgrade() -> None:
    if "dictation_usage_log" not in _table_names():
        return
    op.drop_index("ix_dictation_usage_log_account_created", table_name="dictation_usage_log")
    op.drop_index("ix_dictation_usage_log_user_created", table_name="dictation_usage_log")
    op.drop_table("dictation_usage_log")
