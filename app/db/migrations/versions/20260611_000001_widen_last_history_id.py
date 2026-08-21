"""Widen account sync checkpoint for Outlook delta links.

Revision ID: 038_widen_last_history_id
Revises: 037_repair_usage_billing_flag
Create Date: 2026-06-11 00:00:01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "038_widen_last_history_id"
down_revision: Union[str, None] = "037_repair_usage_billing_flag"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table_name: str) -> dict[str, sa.engine.interfaces.ReflectedColumn]:
    bind = op.get_bind()
    if table_name not in set(sa.inspect(bind).get_table_names()):
        return {}
    return {
        column["name"]: column
        for column in sa.inspect(bind).get_columns(table_name)
    }


def upgrade() -> None:
    columns = _columns("accounts")
    if "last_history_id" not in columns:
        return
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.alter_column(
            "last_history_id",
            existing_type=sa.String(length=256),
            type_=sa.Text(),
            existing_nullable=True,
        )


def downgrade() -> None:
    columns = _columns("accounts")
    if "last_history_id" not in columns:
        return
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.alter_column(
            "last_history_id",
            existing_type=sa.Text(),
            type_=sa.String(length=256),
            existing_nullable=True,
        )
