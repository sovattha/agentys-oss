# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Add scheduled_emails table (migration de la base annexe vers la DB principale).

Chantier « web tier stateless » : ``data/scheduled_emails.db`` (SQLite
annexe à connexion directe) cesse d'exister — première side-SQLite
absorbée par la DB alembic-isée. L'import des lignes legacy est fait
paresseusement par ``ScheduledEmailStore`` au premier usage du store par
défaut.

Revision ID: 043_add_scheduled_emails
Revises: 042_add_calendar_suggestions
Create Date: 2026-06-12 00:00:05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "043_add_scheduled_emails"
down_revision: Union[str, None] = "042_add_calendar_suggestions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_names() -> set[str]:
    bind = op.get_bind()
    return set(sa.inspect(bind).get_table_names())


def upgrade() -> None:
    if "scheduled_emails" in _table_names():
        return

    op.create_table(
        "scheduled_emails",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("send_at", sa.String(length=48), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.String(length=48), nullable=False),
        sa.Column("updated_at", sa.String(length=48), nullable=False),
        sa.Column("sent_at", sa.String(length=48), nullable=True),
        sa.Column("sent_message_id", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
    )
    op.create_index("idx_scheduled_emails_due", "scheduled_emails", ["status", "send_at"])
    op.create_index(
        "idx_scheduled_emails_account", "scheduled_emails", ["account_id", "status"]
    )
    op.create_index(
        "idx_scheduled_emails_idempotency",
        "scheduled_emails",
        ["idempotency_key"],
        unique=True,
    )


def downgrade() -> None:
    if "scheduled_emails" not in _table_names():
        return
    op.drop_index("idx_scheduled_emails_idempotency", table_name="scheduled_emails")
    op.drop_index("idx_scheduled_emails_account", table_name="scheduled_emails")
    op.drop_index("idx_scheduled_emails_due", table_name="scheduled_emails")
    op.drop_table("scheduled_emails")
