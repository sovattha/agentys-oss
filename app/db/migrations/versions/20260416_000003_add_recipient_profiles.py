# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Add recipient_profiles table for DISC profiling persistence (#190).

Permet de ne calculer le profil DISC qu'une fois par contact (tâche background
ou lors de l'ingestion d'un nouvel email reçu). Le DrafterAgent lit depuis
la table à chaque draft plutôt que de refaire l'analyse des emails.

Revision ID: 017_add_recipient_profiles
Revises: 016_add_draft_edit_events
Create Date: 2026-04-16 00:00:03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "017_add_recipient_profiles"
down_revision: Union[str, None] = "016_add_draft_edit_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "recipient_profiles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("recipient_email", sa.String(length=320), nullable=False),
        sa.Column("disc", sa.String(length=2), nullable=False),  # D|I|S|C|?
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        # Scores bruts JSON encodés — permet debug et re-pondération future.
        sa.Column("disc_scores_json", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "account_id", "recipient_email",
            name="uq_recipient_profiles_account_email",
        ),
    )


def downgrade() -> None:
    op.drop_table("recipient_profiles")
