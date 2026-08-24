# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Add batch_queue + active_batches tables (migration de la base annexe vers la DB principale).

Chantier « web tier stateless » : ``data/batch_queue.db`` (SQLite annexe à
connexion directe, file de drafts pour l'API Anthropic Message Batches)
cesse d'exister. L'import des lignes legacy est fait paresseusement par
``app.batch_queue.BatchQueue`` au premier usage du store par défaut.
L'ancienne colonne ``account_id`` ajoutée par ALTER in-code devient une
colonne de plein droit (l'import tolère un fichier legacy sans elle).

Revision ID: 044_add_batch_queue
Revises: 043_add_scheduled_emails
Create Date: 2026-06-12 00:00:06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "044_add_batch_queue"
down_revision: Union[str, None] = "043_add_scheduled_emails"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_names() -> set[str]:
    bind = op.get_bind()
    return set(sa.inspect(bind).get_table_names())


def upgrade() -> None:
    existing = _table_names()

    if "batch_queue" not in existing:
        op.create_table(
            "batch_queue",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("email_id", sa.Text(), nullable=False),
            sa.Column("account_id", sa.Text(), nullable=False),
            sa.Column("tier", sa.String(length=32), nullable=False),
            sa.Column("model", sa.Text(), nullable=False),
            sa.Column("system_prompt", sa.Text(), nullable=False),
            sa.Column("user_prompt", sa.Text(), nullable=False),
            sa.Column("max_tokens", sa.Integer(), nullable=False),
            sa.Column("temperature", sa.Float(), nullable=True),
            sa.Column("metadata", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("batch_id", sa.Text(), nullable=True),
            sa.Column("result_draft", sa.Text(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("input_tokens", sa.Integer(), nullable=True),
            sa.Column("output_tokens", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.String(length=48), nullable=False),
            sa.Column("submitted_at", sa.String(length=48), nullable=True),
            sa.Column("completed_at", sa.String(length=48), nullable=True),
        )
        op.create_index("idx_batch_queue_status", "batch_queue", ["status"])
        op.create_index("idx_batch_queue_email_id", "batch_queue", ["email_id"])

    if "active_batches" not in existing:
        op.create_table(
            "active_batches",
            sa.Column("batch_id", sa.String(length=128), primary_key=True),
            sa.Column("request_count", sa.Integer(), nullable=False),
            sa.Column("submitted_at", sa.String(length=48), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False),
        )


def downgrade() -> None:
    existing = _table_names()
    if "active_batches" in existing:
        op.drop_table("active_batches")
    if "batch_queue" in existing:
        op.drop_index("idx_batch_queue_email_id", table_name="batch_queue")
        op.drop_index("idx_batch_queue_status", table_name="batch_queue")
        op.drop_table("batch_queue")
