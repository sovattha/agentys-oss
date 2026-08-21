"""Fix faq_agent_logs.account_id type + FK CASCADE (Audit FI-001).

The column was declared as String with no foreign key. accounts.id is
Integer, so:
- type mismatch silently allowed cross-row referential drift
- account deletion left FAQ logs as orphans forever (no CASCADE)

This migration:
1. Recreates the table with account_id INTEGER + FK CASCADE.
2. Casts existing string values via CAST AS INTEGER. Rows with non-numeric
   account_id (legacy bug data, if any) are dropped — log a count first
   so a sysadmin sees what was lost.

SQLite cannot ALTER COLUMN type, so batch_alter_table is used.

Revision ID: 018_faq_log_account_fk
Revises: 017_add_recipient_profiles
Create Date: 2026-04-27 00:00:01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "018_faq_log_account_fk"
down_revision: Union[str, None] = "017_add_recipient_profiles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    return table_name in set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if not _table_exists("faq_agent_logs"):
        return

    # 1. Drop rows with non-numeric account_id (cannot cast safely).
    bind = op.get_bind()
    bad = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM faq_agent_logs "
            "WHERE account_id IS NULL "
            "OR account_id = '' "
            "OR account_id NOT GLOB '[0-9]*' "
            "OR CAST(account_id AS INTEGER) || '' <> account_id"
        )
    ).scalar()
    if bad:
        print(f"[migration 018] dropping {bad} faq_agent_logs rows with non-numeric account_id")
        bind.execute(
            sa.text(
                "DELETE FROM faq_agent_logs "
                "WHERE account_id IS NULL "
            "OR account_id = '' "
            "OR account_id NOT GLOB '[0-9]*' "
            "OR CAST(account_id AS INTEGER) || '' <> account_id"
            )
        )

    # 2. Recreate the column as Integer + FK + CASCADE. SQLite needs
    # batch_alter_table for type changes and FK additions.
    with op.batch_alter_table("faq_agent_logs") as batch_op:
        batch_op.alter_column(
            "account_id",
            existing_type=sa.String(),
            type_=sa.Integer(),
            existing_nullable=False,
            postgresql_using="account_id::integer",
        )
        batch_op.create_foreign_key(
            "fk_faq_agent_logs_account_id_accounts",
            "accounts",
            ["account_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    with op.batch_alter_table("faq_agent_logs") as batch_op:
        batch_op.drop_constraint(
            "fk_faq_agent_logs_account_id_accounts", type_="foreignkey"
        )
        batch_op.alter_column(
            "account_id",
            existing_type=sa.Integer(),
            type_=sa.String(),
            existing_nullable=False,
        )
