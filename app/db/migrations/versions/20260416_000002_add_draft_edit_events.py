"""Add draft_edit_events table to capture diffs between IA draft and sent version.

Supports issue #196 (edit feedback loop). Every time a user edits a draft
before sending, we record the diff and classify the nature of the edit:

- ``tone_shift`` : formel ↔ décontracté
- ``length_adjustment`` : raccourcissement ou allongement
- ``structure_change`` : paragraphes réorganisés
- ``content_addition`` : info factuelle ajoutée
- ``signature_override`` : signature remplacée
- ``minor_typo_fix`` : corrections cosmétiques
- ``other``

Permet à terme d'ajuster automatiquement les prompts / WritingStyleProfile
quand un pattern se répète (> N occurrences d'un même type).

Revision ID: 016_add_draft_edit_events
Revises: 015_add_gmail_watch
Create Date: 2026-04-16 00:00:02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "016_add_draft_edit_events"
down_revision: Union[str, None] = "015_add_gmail_watch"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "draft_edit_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("draft_id", sa.String(length=128), nullable=False, index=True),
        sa.Column(
            "original_email_id",
            sa.Integer(),
            sa.ForeignKey("emails.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("category", sa.String(length=32), nullable=False),
        # Magnitude relative : |final_len - initial_len| / max(initial_len, 1).
        # Une seule métrique suffit ici — fine-grain peut venir plus tard.
        sa.Column("magnitude", sa.Float(), nullable=False),
        sa.Column("initial_length", sa.Integer(), nullable=False),
        sa.Column("final_length", sa.Integer(), nullable=False),
        sa.Column("intent", sa.String(length=32), nullable=True),
        sa.Column("recipient_email", sa.String(length=320), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_draft_edit_events_account_created",
        "draft_edit_events",
        ["account_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_draft_edit_events_account_created", table_name="draft_edit_events")
    op.drop_table("draft_edit_events")
