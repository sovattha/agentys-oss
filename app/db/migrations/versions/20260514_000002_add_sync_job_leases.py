"""Add lease and backoff fields to sync_jobs.

Revision ID: 028_add_sync_job_leases
Revises: 027_add_email_deadline_marker
Create Date: 2026-05-14 00:00:02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "028_add_sync_job_leases"
down_revision: Union[str, None] = "027_add_email_deadline_marker"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_names() -> set[str]:
    bind = op.get_bind()
    return {col["name"] for col in sa.inspect(bind).get_columns("sync_jobs")}


def _index_names() -> set[str]:
    bind = op.get_bind()
    return {idx["name"] for idx in sa.inspect(bind).get_indexes("sync_jobs")}


def _create_index(name: str, columns: list[str]) -> None:
    bind = op.get_bind()
    if name in _index_names():
        return
    if bind.dialect.name == "postgresql":
        column_sql = ", ".join(columns)
        with op.get_context().autocommit_block():
            op.execute(
                f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} "
                f"ON sync_jobs ({column_sql})"
            )
    else:
        op.create_index(name, "sync_jobs", columns)


def _drop_index(name: str) -> None:
    bind = op.get_bind()
    if name not in _index_names():
        return
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
    else:
        op.drop_index(name, table_name="sync_jobs")


def upgrade() -> None:
    columns = _column_names()
    if "lease_owner" not in columns:
        op.add_column("sync_jobs", sa.Column("lease_owner", sa.String(length=128), nullable=True))
    if "lease_expires_at" not in columns:
        op.add_column("sync_jobs", sa.Column("lease_expires_at", sa.DateTime(), nullable=True))
    if "attempt_count" not in columns:
        op.add_column(
            "sync_jobs",
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        )
    if "backoff_until" not in columns:
        op.add_column("sync_jobs", sa.Column("backoff_until", sa.DateTime(), nullable=True))
    if "last_error_code" not in columns:
        op.add_column("sync_jobs", sa.Column("last_error_code", sa.String(length=64), nullable=True))
    if "provider_units_estimate" not in columns:
        op.add_column(
            "sync_jobs",
            sa.Column("provider_units_estimate", sa.Integer(), nullable=False, server_default="0"),
        )

    _create_index("ix_sync_jobs_status_backoff", ["status", "backoff_until"])
    _create_index("ix_sync_jobs_lease_expires", ["lease_expires_at"])


def downgrade() -> None:
    _drop_index("ix_sync_jobs_lease_expires")
    _drop_index("ix_sync_jobs_status_backoff")

    columns = _column_names()
    if "provider_units_estimate" in columns:
        op.drop_column("sync_jobs", "provider_units_estimate")
    if "last_error_code" in columns:
        op.drop_column("sync_jobs", "last_error_code")
    if "backoff_until" in columns:
        op.drop_column("sync_jobs", "backoff_until")
    if "attempt_count" in columns:
        op.drop_column("sync_jobs", "attempt_count")
    if "lease_expires_at" in columns:
        op.drop_column("sync_jobs", "lease_expires_at")
    if "lease_owner" in columns:
        op.drop_column("sync_jobs", "lease_owner")
