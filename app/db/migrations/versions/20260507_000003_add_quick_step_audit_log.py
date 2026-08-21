"""Add quick_step_audit_log table for persistent execution history.

The ``quick_step_executions`` table is a 60-second idempotency cache: rows
get garbage-collected on next read and the table never holds long-term
history. That makes "did Quick Step X run on email Y?" or "why did my
auto-trigger fail at 3am?" unanswerable — the only trace lives in stderr
of the daemon process, which gets rotated.

This migration adds an append-only audit log so the engine can record one
row per execution, regardless of outcome. Source distinguishes ``manual``
(UI keypress / palette) from ``auto`` (daemon trigger). Stored fields are
the minimum needed for after-the-fact debugging:

  - actions_json   serialized list of {type, ok, error}
  - executed       count of actions that ran (incl. skipped/replays)
  - replay         True if the engine returned a cached idempotent replay

The table is intentionally NOT used by the engine for idempotency — that
job stays with ``quick_step_executions`` whose unique constraint on
(account_id, idempotency_key) is the cross-worker dedupe primitive.

Composite index on (account_id, created_at DESC) backs the "recent
executions for this account" query that the future Settings UI will use.

Revision ID: 024_add_quick_step_audit_log
Revises: 023_add_quick_step_executions
Create Date: 2026-05-07 00:00:03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "024_add_quick_step_audit_log"
down_revision: Union[str, None] = "023_add_quick_step_executions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "quick_step_audit_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("step_id", sa.String(length=64), nullable=False),
        sa.Column("step_name", sa.String(length=255), nullable=True),
        sa.Column("email_id", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("executed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("actions_json", sa.Text(), nullable=True),
        sa.Column("replay", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_quick_step_audit_log_account_created",
        "quick_step_audit_log",
        ["account_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_quick_step_audit_log_account_created",
        table_name="quick_step_audit_log",
    )
    op.drop_table("quick_step_audit_log")
