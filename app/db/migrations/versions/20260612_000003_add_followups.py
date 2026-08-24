# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Add followups table (migration du store JSON de calendar.py vers la DB).

Suite du chantier « web tier stateless » (039 contact_groups, 040 snippets) :
``data/followups.json`` cesse d'être une source de vérité. L'import des
données legacy est fait paresseusement par
``app.services.followup_store.ensure_legacy_import`` au premier accès.

``account_id`` est la string OAuth hash (pas l'int DB) — format manipulé par
tout calendar.py. Pas de FK.

Revision ID: 041_add_followups
Revises: 040_add_snippets
Create Date: 2026-06-12 00:00:03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "041_add_followups"
down_revision: Union[str, None] = "040_add_snippets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_names() -> set[str]:
    bind = op.get_bind()
    return set(sa.inspect(bind).get_table_names())


def upgrade() -> None:
    if "followups" in _table_names():
        return

    op.create_table(
        "followups",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("account_id", sa.String(length=64), nullable=False),
        sa.Column("email_id", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("due_date", sa.String(length=48), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.String(length=48), nullable=True),
        sa.Column("completed_at", sa.String(length=48), nullable=True),
        sa.Column("snoozed_until", sa.String(length=48), nullable=True),
        sa.Column("snooze_count", sa.Integer(), nullable=False),
        sa.Column("calendar_event_id", sa.Text(), nullable=True),
        sa.Column("sync_to_calendar", sa.Boolean(), nullable=False),
        sa.Column("email_subject", sa.Text(), nullable=True),
        sa.Column("email_sender", sa.Text(), nullable=True),
        sa.Column("auto_created", sa.Boolean(), nullable=False),
        sa.Column("ai_reason", sa.Text(), nullable=True),
    )
    op.create_index("ix_followups_account_id", "followups", ["account_id"])
    op.create_index("ix_followups_status", "followups", ["status"])


def downgrade() -> None:
    if "followups" not in _table_names():
        return
    op.drop_index("ix_followups_status", table_name="followups")
    op.drop_index("ix_followups_account_id", table_name="followups")
    op.drop_table("followups")
