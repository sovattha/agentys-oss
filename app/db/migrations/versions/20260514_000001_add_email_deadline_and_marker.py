# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Add email deadline and emoji marker columns.

Revision ID: 027_add_email_deadline_marker
Revises: 026_add_sync_jobs
Create Date: 2026-05-14 00:00:01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "027_add_email_deadline_marker"
down_revision: Union[str, None] = "026_add_sync_jobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_names() -> set[str]:
    bind = op.get_bind()
    return {col["name"] for col in sa.inspect(bind).get_columns("emails")}


def _index_names() -> set[str]:
    bind = op.get_bind()
    return {idx["name"] for idx in sa.inspect(bind).get_indexes("emails")}


def upgrade() -> None:
    columns = _column_names()
    if "deadline_at" not in columns:
        op.add_column("emails", sa.Column("deadline_at", sa.DateTime(), nullable=True))
    if "emoji_marker_json" not in columns:
        op.add_column("emails", sa.Column("emoji_marker_json", sa.Text(), nullable=True))

    if "ix_emails_deadline_at" in _index_names():
        return

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                "ix_emails_deadline_at ON emails (deadline_at)"
            )
    else:
        op.create_index("ix_emails_deadline_at", "emails", ["deadline_at"])


def downgrade() -> None:
    bind = op.get_bind()
    if "ix_emails_deadline_at" in _index_names():
        if bind.dialect.name == "postgresql":
            with op.get_context().autocommit_block():
                op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_emails_deadline_at")
        else:
            op.drop_index("ix_emails_deadline_at", table_name="emails")

    columns = _column_names()
    if "emoji_marker_json" in columns:
        op.drop_column("emails", "emoji_marker_json")
    if "deadline_at" in columns:
        op.drop_column("emails", "deadline_at")
