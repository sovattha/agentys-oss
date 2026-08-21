"""Add durable provider quota windows.

Revision ID: 029_add_provider_quota_windows
Revises: 028_add_sync_job_leases
Create Date: 2026-05-14 00:00:03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "029_add_provider_quota_windows"
down_revision: Union[str, None] = "028_add_sync_job_leases"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_names() -> set[str]:
    bind = op.get_bind()
    return set(sa.inspect(bind).get_table_names())


def upgrade() -> None:
    if "provider_quota_windows" in _table_names():
        return

    op.create_table(
        "provider_quota_windows",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("quota_scope", sa.String(length=32), nullable=False),
        sa.Column("scope_key", sa.String(length=128), nullable=False),
        sa.Column("window_start", sa.DateTime(), nullable=False),
        sa.Column("units_reserved", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "provider",
            "quota_scope",
            "scope_key",
            "window_start",
            name="uq_provider_quota_window",
        ),
    )
    op.create_index(
        "ix_provider_quota_windows_window",
        "provider_quota_windows",
        ["provider", "window_start"],
    )


def downgrade() -> None:
    if "provider_quota_windows" not in _table_names():
        return
    op.drop_index(
        "ix_provider_quota_windows_window",
        table_name="provider_quota_windows",
    )
    op.drop_table("provider_quota_windows")
