"""Add draft_feedback table for explicit user verdicts (accept/edit/reject).

Complements draft_edit_events (#196 — auto-detected magnitude+category) with
the user's explicit verdict. The audit 2026-05-05 flagged that the learning
loop ingests corrections but is blind to the "user trashed the draft and
wrote their own" case — that signal lands here as `action='reject'`.

Three actions:
- ``accept`` : user sent the draft as-is. Implicit positive — strongest signal.
- ``edit``   : user sent a modified version. Edit distance (0–1, Levenshtein /
               max len) is recorded so threshold tuning can weigh light vs
               heavy edits differently.
- ``reject`` : user dismissed the draft and either skipped reply or wrote
               from scratch. The strongest negative signal — Critic threshold
               tuner should weight these heavier than edits.

Schema kept lean on purpose: no full original_draft / final_text columns
(we already store drafts in draft_history, sent emails in emails). Storing
both would 2× the disk footprint of the table for no analytic gain. The
analytics path joins on (draft_id, account_id) to fetch the bodies on demand.

Revision ID: 020_add_draft_feedback
Revises: 020_add_raw_headers_to_emails
Create Date: 2026-05-05 00:00:01

NOTE: ``down_revision`` was originally ``019_add_bulk_jobs`` but is now
chained after ``020_add_raw_headers_to_emails`` to repair the lost-file
drift documented in that recovery migration. The two revisions both keep
their ``020_*`` prefix for historical readability — Alembic identifies
them by full revision string, not prefix, so there's no collision.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "020_add_draft_feedback"
down_revision: Union[str, None] = "020_add_raw_headers_to_emails"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "draft_feedback",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("draft_id", sa.String(length=128), nullable=False, index=True),
        # 'accept' | 'edit' | 'reject' — enforced at the application layer
        # (SQLite has no native enum; a CHECK constraint here would block
        # future values like 'partial_accept' that we may want to add).
        sa.Column("action", sa.String(length=16), nullable=False),
        # Edit distance (0–1). Nullable: not always meaningful for accept/reject.
        sa.Column("edit_distance", sa.Float(), nullable=True),
        sa.Column("intent", sa.String(length=32), nullable=True),
        # Optional free-text note (e.g. why the user rejected). Length-capped
        # to 1024 chars at the application layer to keep the table cheap.
        sa.Column("note", sa.String(length=1024), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    # Composite index for the most common analytics query:
    # "rejection rate per account over the last N days".
    op.create_index(
        "ix_draft_feedback_account_action_created",
        "draft_feedback",
        ["account_id", "action", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_draft_feedback_account_action_created",
        table_name="draft_feedback",
    )
    op.drop_table("draft_feedback")
