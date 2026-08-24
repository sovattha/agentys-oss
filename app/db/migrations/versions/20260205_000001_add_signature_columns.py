# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Add signature_html and signature_text columns to accounts table.

Revision ID: 003_add_signatures
Revises: 002_fts5_search
Create Date: 2026-02-05 00:00:01

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "003_add_signatures"
down_revision: Union[str, None] = "002_fts5_search"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add signature columns to accounts table
    # Using batch mode for SQLite compatibility
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.add_column(
            sa.Column("signature_html", sa.String(length=8192), nullable=True)
        )
        batch_op.add_column(
            sa.Column("signature_text", sa.String(length=4096), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.drop_column("signature_text")
        batch_op.drop_column("signature_html")
