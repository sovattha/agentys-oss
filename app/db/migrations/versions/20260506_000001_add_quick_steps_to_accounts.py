# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Add quick_steps_json column to accounts table for user-defined Quick Steps.

Quick Steps are user-configured action chains (archive, label, forward,
reply with template, etc.) bound to a hotkey or chip button. They run
deterministically on the backend with zero new LLM calls. The config is
account-scoped and stored as a JSON list on accounts.quick_steps_json,
matching the existing settings_json pattern.

Revision ID: 021_add_quick_steps
Revises: 020_add_draft_feedback
Create Date: 2026-05-06 00:00:01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "021_add_quick_steps"
down_revision: Union[str, None] = "020_add_draft_feedback"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.add_column(sa.Column("quick_steps_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.drop_column("quick_steps_json")
