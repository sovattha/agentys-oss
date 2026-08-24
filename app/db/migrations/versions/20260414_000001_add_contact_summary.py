# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Add contact summary columns for pre-computed long-term context.

Stores a structured JSON summary of the user's relationship with each
contact (relation type, habitual tone, recurring topics, key facts, etc.)
so the drafter prompt doesn't need to load 20 raw historical emails every
time. Cuts ~46k input tokens per draft.

Columns added to contacts:
- summary_json: structured summary as JSON text
- summary_last_message_id: tracks staleness (regenerate if newer message arrives)
- summary_updated_at: audit timestamp

Revision ID: 013_add_contact_summary
Revises: 012_cascade_account_fks
Create Date: 2026-04-14 00:00:01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "013_add_contact_summary"
down_revision: Union[str, None] = "012_cascade_account_fks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("contacts") as batch_op:
        batch_op.add_column(sa.Column("summary_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("summary_last_message_id", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("summary_updated_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("contacts") as batch_op:
        batch_op.drop_column("summary_updated_at")
        batch_op.drop_column("summary_last_message_id")
        batch_op.drop_column("summary_json")
