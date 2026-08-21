"""Add sync_jobs table for provider sync requests.

Revision ID: 026_add_sync_jobs
Revises: 025_merge_audit_log_and_pinned
Create Date: 2026-05-13 00:00:01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "026_add_sync_jobs"
down_revision: Union[str, None] = "025_merge_audit_log_and_pinned"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sync_jobs",
        sa.Column("id", sa.String(length=32), primary_key=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("folder", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("requested_limit", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("unread_only", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("coalesced_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.String(length=32), nullable=True),
        sa.Column("completed_at", sa.String(length=32), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_sync_jobs_account_folder_status",
        "sync_jobs",
        ["account_id", "folder", "status"],
    )
    op.create_index(
        "ix_sync_jobs_user_status_created",
        "sync_jobs",
        ["user_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_sync_jobs_user_status_created", table_name="sync_jobs")
    op.drop_index("ix_sync_jobs_account_folder_status", table_name="sync_jobs")
    op.drop_table("sync_jobs")
