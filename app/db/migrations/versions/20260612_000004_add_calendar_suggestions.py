"""Add calendar_suggestions table (migration du store JSON vers la DB).

Suite du chantier « web tier stateless » (039/040/041) :
``data/calendar_suggestions.json`` cesse d'être une source de vérité.
Import legacy paresseux par ``app.services.calendar_suggestion_store``.

Revision ID: 042_add_calendar_suggestions
Revises: 041_add_followups
Create Date: 2026-06-12 00:00:04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "042_add_calendar_suggestions"
down_revision: Union[str, None] = "041_add_followups"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_names() -> set[str]:
    bind = op.get_bind()
    return set(sa.inspect(bind).get_table_names())


def upgrade() -> None:
    if "calendar_suggestions" in _table_names():
        return

    op.create_table(
        "calendar_suggestions",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("account_id", sa.String(length=64), nullable=False),
        sa.Column("email_id", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("deadline", sa.String(length=48), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.String(length=48), nullable=True),
        sa.Column("email_subject", sa.Text(), nullable=True),
        sa.Column("email_sender", sa.Text(), nullable=True),
        sa.Column("draft_body_preview", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_calendar_suggestions_account_id", "calendar_suggestions", ["account_id"]
    )
    op.create_index(
        "ix_calendar_suggestions_status", "calendar_suggestions", ["status"]
    )


def downgrade() -> None:
    if "calendar_suggestions" not in _table_names():
        return
    op.drop_index("ix_calendar_suggestions_status", table_name="calendar_suggestions")
    op.drop_index("ix_calendar_suggestions_account_id", table_name="calendar_suggestions")
    op.drop_table("calendar_suggestions")
