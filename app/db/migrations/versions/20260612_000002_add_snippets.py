# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Add snippets + snippet_shares tables (migration des stores JSON vers la DB).

Suite du chantier « web tier stateless » (039 = contact_groups) :
``data/snippets.json`` et ``data/snippet_shares.json`` cessent d'être des
sources de vérité. L'import des données legacy est fait paresseusement par
``app.api.snippets._ensure_legacy_import`` au premier accès — cette migration
ne crée que le schéma.

Pas de FK : ``account_id`` est nullable (NULL = tous les comptes du
propriétaire, contrat historique) et ``snippet_shares.snippet_id`` garde la
cascade en code (sémantique historique de delete_snippet, et l'import legacy
peut rencontrer des shares orphelins qu'on veut importer sans erreur).

Revision ID: 040_add_snippets
Revises: 039_add_contact_groups
Create Date: 2026-06-12 00:00:02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "040_add_snippets"
down_revision: Union[str, None] = "039_add_contact_groups"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_names() -> set[str]:
    bind = op.get_bind()
    return set(sa.inspect(bind).get_table_names())


def upgrade() -> None:
    tables = _table_names()

    if "snippets" not in tables:
        op.create_table(
            "snippets",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("owner_email", sa.String(length=320), nullable=True),
            sa.Column("account_id", sa.Integer(), nullable=True),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("subject", sa.Text(), nullable=True),
            sa.Column("to_json", sa.Text(), nullable=True),
            sa.Column("cc_json", sa.Text(), nullable=True),
            sa.Column("bcc_json", sa.Text(), nullable=True),
            sa.Column("category", sa.Text(), nullable=True),
            sa.Column("is_private", sa.Boolean(), nullable=False),
            sa.Column("use_count", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.String(length=48), nullable=False),
            sa.Column("updated_at", sa.String(length=48), nullable=False),
        )
        op.create_index("ix_snippets_owner_email", "snippets", ["owner_email"])

    if "snippet_shares" not in tables:
        op.create_table(
            "snippet_shares",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("snippet_id", sa.String(length=64), nullable=False),
            sa.Column("shared_by", sa.String(length=320), nullable=False),
            sa.Column("shared_with", sa.String(length=320), nullable=False),
            sa.Column("shared_at", sa.String(length=48), nullable=False),
        )
        op.create_index(
            "ix_snippet_shares_snippet_id", "snippet_shares", ["snippet_id"]
        )
        op.create_index(
            "ix_snippet_shares_shared_with", "snippet_shares", ["shared_with"]
        )


def downgrade() -> None:
    tables = _table_names()
    if "snippet_shares" in tables:
        op.drop_index("ix_snippet_shares_shared_with", table_name="snippet_shares")
        op.drop_index("ix_snippet_shares_snippet_id", table_name="snippet_shares")
        op.drop_table("snippet_shares")
    if "snippets" in tables:
        op.drop_index("ix_snippets_owner_email", table_name="snippets")
        op.drop_table("snippets")
