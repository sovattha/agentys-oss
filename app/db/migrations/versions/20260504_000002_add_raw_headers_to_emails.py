# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Add ``emails.raw_headers`` column.

Recovery migration: a previous branch shipped this column to the live DB
without persisting the migration file (the alembic_version row was set to
``020_add_raw_headers_to_emails`` but no matching file existed in
``app/db/migrations/versions``). Restoring it lets ``alembic upgrade head``
walk the chain cleanly on fresh deployments and matches what the live
schema already has.

The column itself is currently unused (zero rows populated, no code
references). It's preserved as a no-op artifact rather than dropped to
avoid a destructive ALTER on the live DB. A follow-up migration can drop
it once we're sure no off-cluster snapshots rely on it.

Revision ID: 020_add_raw_headers_to_emails
Revises: 019_add_avatar_url_to_accounts, 019_add_bulk_jobs
Create Date: 2026-05-04 00:00:02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "020_add_raw_headers_to_emails"
down_revision: Union[str, Sequence[str], None] = (
    "019_add_avatar_url_to_accounts",
    "019_add_bulk_jobs",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("emails") as batch_op:
        batch_op.add_column(sa.Column("raw_headers", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("emails") as batch_op:
        batch_op.drop_column("raw_headers")
