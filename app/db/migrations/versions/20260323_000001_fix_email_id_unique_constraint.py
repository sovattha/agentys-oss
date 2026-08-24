# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Replace global unique index on email_id with composite (email_id, account_id).

In multi-account mode, IMAP UIDs are per-mailbox and can collide across accounts.
The global unique constraint prevents storing the same IMAP UID from two different
accounts. This migration replaces it with a composite unique index.

Revision ID: 010_fix_email_id_unique
Revises: 009_add_user_id
Create Date: 2026-03-23 00:00:01

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "010_fix_email_id_unique"
down_revision: Union[str, None] = "009_add_user_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite requires batch mode to alter indexes
    with op.batch_alter_table("emails") as batch_op:
        # Drop the global unique index on email_id
        batch_op.drop_index("ix_emails_email_id")
        # Add a composite unique index (email_id, account_id)
        batch_op.create_index(
            "ix_emails_email_id_account",
            ["email_id", "account_id"],
            unique=True,
        )
        # Keep a non-unique index on email_id alone for single-account lookups
        batch_op.create_index("ix_emails_email_id", ["email_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("emails") as batch_op:
        batch_op.drop_index("ix_emails_email_id")
        batch_op.drop_index("ix_emails_email_id_account")
        batch_op.create_index("ix_emails_email_id", ["email_id"], unique=True)
