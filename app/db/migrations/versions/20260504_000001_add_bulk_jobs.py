# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Add bulk_jobs + bulk_job_items tables for the centralized rate-limited
bulk-action queue.

Two tables:
- bulk_jobs (ULID PK) tracks one user-initiated or auto-deletion bulk
  operation (e.g. "archive 4230 emails"). Counters and lifecycle status
  are denormalized here for cheap UI list queries.
- bulk_job_items (autoinc PK) stores the per-message work units of each
  job. The worker pops items one at a time honoring per-provider token
  buckets (cf. app/services/bulk_jobs/worker.py).

Why ULIDs for bulk_jobs.id: lexically sortable by creation time, no
collisions across processes (worker can be sharded later), opaque to
clients. Stored as TEXT(26) so SQLite doesn't choke on integer FK type
mismatches.

Why a partial index on (job_id) WHERE state = 'pending': the worker hot
path runs `SELECT … WHERE job_id=? AND state='pending' ORDER BY id LIMIT 1`
many times per second. A narrow partial index keeps the working set in
page cache even with 10 000+ items per job.

Revision ID: 019_add_bulk_jobs
Revises: 018_faq_log_account_fk
Create Date: 2026-05-04 00:00:01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "019_add_bulk_jobs"
down_revision: Union[str, None] = "018_faq_log_account_fk"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bulk_jobs",
        sa.Column("id", sa.String(length=26), primary_key=True, nullable=False),
        # user_id is nullable: in Tauri loopback mode there is no JWT user.
        # Ownership is then enforced solely via account_id ↔ user mapping.
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("target_total", sa.Integer(), nullable=False),
        sa.Column(
            "succeeded_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "failed_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "skipped_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("params_json", sa.Text(), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.String(length=32), nullable=True),
        sa.Column("completed_at", sa.String(length=32), nullable=True),
    )
    op.create_index(
        "ix_bulk_jobs_user_status_created",
        "bulk_jobs",
        ["user_id", "status", "created_at"],
    )
    op.create_index(
        "ix_bulk_jobs_account_status",
        "bulk_jobs",
        ["account_id", "status"],
    )

    op.create_table(
        "bulk_job_items",
        sa.Column(
            "id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False
        ),
        sa.Column(
            "job_id",
            sa.String(length=26),
            sa.ForeignKey("bulk_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider_msg_id", sa.String(length=255), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.String(length=32), nullable=False),
    )
    op.create_index(
        "ix_bulk_job_items_job_state", "bulk_job_items", ["job_id", "state"]
    )
    # Partial index: hot path is "next pending item for this job".
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_bulk_job_items_pending "
            "ON bulk_job_items(job_id, id) WHERE state = 'pending'"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DROP INDEX IF EXISTS ix_bulk_job_items_pending"))
    op.drop_index("ix_bulk_job_items_job_state", table_name="bulk_job_items")
    op.drop_table("bulk_job_items")
    op.drop_index("ix_bulk_jobs_account_status", table_name="bulk_jobs")
    op.drop_index("ix_bulk_jobs_user_status_created", table_name="bulk_jobs")
    op.drop_table("bulk_jobs")
