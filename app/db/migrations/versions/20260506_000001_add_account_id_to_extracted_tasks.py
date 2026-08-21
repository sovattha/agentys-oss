"""Add account_id to extracted_tasks for per-tenant isolation (AUTHZ-VULN-04).

Shannon pentest 2026-05-05 (issue #557) confirmed an IDOR on
``GET /api/tasks/{task_id}``: any JWT user could read any other user's
task by guessing/iterating numeric IDs because the endpoint had no
ownership check (TODO documented inline in routes_learning.py).

Strategy mirrors migration 014 (draft_history):
  1. Add nullable ``account_id`` column with FK + CASCADE to accounts(id).
  2. Backfill by joining ``extracted_tasks.email_id`` → ``emails.account_id``.
     Tasks with empty email_id (manually created via POST /api/tasks)
     stay NULL — the route layer hard-quarantines NULL rows so they
     never surface in any user's list.
  3. Composite index (account_id, status) for the hot list query.

Revision ID: 021_add_account_id_to_extracted_tasks
Revises: 020_add_draft_feedback
Create Date: 2026-05-06 00:00:01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "021_add_account_id_to_extracted_tasks"
down_revision: Union[str, None] = "020_add_draft_feedback"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    return table_name in set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if not _table_exists("extracted_tasks"):
        return

    # 1. Add the column (nullable — FK enforced, CASCADE on account delete).
    with op.batch_alter_table("extracted_tasks") as batch_op:
        batch_op.add_column(sa.Column("account_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_extracted_tasks_account_id_accounts",
            "accounts",
            ["account_id"],
            ["id"],
            ondelete="CASCADE",
        )

    # 2. Backfill via the email_id link. Tasks created from email parsing
    #    have email_id set; tasks created via POST /api/tasks have email_id=''
    #    and stay NULL (those will be hard-quarantined).
    op.execute(
        """
        UPDATE extracted_tasks
        SET account_id = (
            SELECT e.account_id FROM emails e
            WHERE e.email_id = extracted_tasks.email_id
            LIMIT 1
        )
        WHERE account_id IS NULL
          AND email_id IS NOT NULL
          AND email_id != ''
        """
    )

    # 3. Composite index for the hot list query.
    op.create_index(
        "idx_extracted_tasks_account_status",
        "extracted_tasks",
        ["account_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_extracted_tasks_account_status",
        table_name="extracted_tasks",
    )
    with op.batch_alter_table("extracted_tasks") as batch_op:
        batch_op.drop_constraint(
            "fk_extracted_tasks_account_id_accounts", type_="foreignkey"
        )
        batch_op.drop_column("account_id")
