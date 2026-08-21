# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Add FTS5 full-text search index for emails.

Revision ID: 002_fts5_search
Revises: 001_initial
Create Date: 2026-01-18 00:00:02

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002_fts5_search"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create FTS5 virtual table and triggers for email search."""
    if op.get_context().dialect.name != "sqlite":
        # PostgreSQL search will use the service's LIKE fallback until a
        # dedicated tsvector/GIN migration is added. This keeps the historical
        # SQLite-only FTS5 migration from blocking a fresh Postgres schema.
        return

    # Create FTS5 virtual table
    # Using content-sync mode with emails table
    # tokenize: unicode61 for international text support, remove diacritics
    op.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS emails_fts USING fts5(
            subject,
            body_text,
            sender,
            content='emails',
            content_rowid='id',
            tokenize='unicode61 remove_diacritics 1'
        )
    """)

    # Populate FTS index from existing emails
    op.execute("""
        INSERT INTO emails_fts(emails_fts) VALUES('rebuild')
    """)

    # Trigger: After INSERT on emails, add to FTS index
    op.execute("""
        CREATE TRIGGER IF NOT EXISTS emails_fts_insert AFTER INSERT ON emails BEGIN
            INSERT INTO emails_fts(rowid, subject, body_text, sender)
            VALUES (new.id, new.subject, new.body_text, new.sender);
        END
    """)

    # Trigger: After DELETE on emails, remove from FTS index
    op.execute("""
        CREATE TRIGGER IF NOT EXISTS emails_fts_delete AFTER DELETE ON emails BEGIN
            INSERT INTO emails_fts(emails_fts, rowid, subject, body_text, sender)
            VALUES('delete', old.id, old.subject, old.body_text, old.sender);
        END
    """)

    # Trigger: After UPDATE on emails, update FTS index
    op.execute("""
        CREATE TRIGGER IF NOT EXISTS emails_fts_update AFTER UPDATE ON emails BEGIN
            INSERT INTO emails_fts(emails_fts, rowid, subject, body_text, sender)
            VALUES('delete', old.id, old.subject, old.body_text, old.sender);
            INSERT INTO emails_fts(rowid, subject, body_text, sender)
            VALUES (new.id, new.subject, new.body_text, new.sender);
        END
    """)


def downgrade() -> None:
    """Remove FTS5 virtual table and triggers."""
    if op.get_context().dialect.name != "sqlite":
        return

    # Drop triggers first
    op.execute("DROP TRIGGER IF EXISTS emails_fts_insert")
    op.execute("DROP TRIGGER IF EXISTS emails_fts_delete")
    op.execute("DROP TRIGGER IF EXISTS emails_fts_update")

    # Drop FTS5 virtual table
    op.execute("DROP TABLE IF EXISTS emails_fts")
