# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Add pinned_email_ids_json to accounts for backend-persisted inbox pin state.

Allows the Quick Step 'pin' action (run by the daemon on auto-trigger) to
persist pinned email IDs so the frontend can merge them on next load.

Revision ID: 018_add_pinned_email_ids
Revises: 017_add_recipient_profiles
Create Date: 2026-05-07 00:00:01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "018_add_pinned_email_ids"
down_revision: Union[str, None] = "017_add_recipient_profiles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.add_column(
            sa.Column("pinned_email_ids_json", sa.Text(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.drop_column("pinned_email_ids_json")
