# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Add CASCADE delete on per-account tables that were leaking orphans.

Three tables stored an `account_id` column referencing accounts.id but
without a proper foreign key + CASCADE, so deleting an account left
orphaned rows on disk forever:

- knowledge_entries: had FK but no CASCADE
- relationship_overrides: account_id was a bare Integer (no FK)
- email_labels: account_id was a bare Integer (no FK)

This migration recreates each table with a real FK and ondelete=CASCADE.
SQLite doesn't support modifying FKs in place, so batch_alter_table is
used to recreate-and-copy.

Revision ID: 012_cascade_account_fks
Revises: 011_add_settings_json
Create Date: 2026-04-13 00:00:01

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "012_cascade_account_fks"
down_revision: Union[str, None] = "011_add_settings_json"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    return table_name in set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    # 1. knowledge_entries — already had FK, just add CASCADE
    if _table_exists("knowledge_entries"):
        with op.batch_alter_table("knowledge_entries") as batch_op:
            batch_op.drop_constraint("fk_knowledge_entries_account_id_accounts", type_="foreignkey")
            batch_op.create_foreign_key(
                "fk_knowledge_entries_account_id_accounts",
                "accounts",
                ["account_id"],
                ["id"],
                ondelete="CASCADE",
            )

    # 2. relationship_overrides — was a bare Integer, add real FK + CASCADE
    if _table_exists("relationship_overrides"):
        with op.batch_alter_table("relationship_overrides") as batch_op:
            batch_op.create_foreign_key(
                "fk_relationship_overrides_account_id_accounts",
                "accounts",
                ["account_id"],
                ["id"],
                ondelete="CASCADE",
            )

    # 3. email_labels — was a bare Integer, add real FK + CASCADE
    if _table_exists("email_labels"):
        with op.batch_alter_table("email_labels") as batch_op:
            batch_op.create_foreign_key(
                "fk_email_labels_account_id_accounts",
                "accounts",
                ["account_id"],
                ["id"],
                ondelete="CASCADE",
            )


def downgrade() -> None:
    with op.batch_alter_table("email_labels") as batch_op:
        batch_op.drop_constraint("fk_email_labels_account_id_accounts", type_="foreignkey")

    with op.batch_alter_table("relationship_overrides") as batch_op:
        batch_op.drop_constraint("fk_relationship_overrides_account_id_accounts", type_="foreignkey")

    with op.batch_alter_table("knowledge_entries") as batch_op:
        batch_op.drop_constraint("fk_knowledge_entries_account_id_accounts", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_knowledge_entries_account_id_accounts",
            "accounts",
            ["account_id"],
            ["id"],
        )
