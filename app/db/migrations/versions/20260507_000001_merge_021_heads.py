"""Merge three parallel ``021_*`` revisions into a single head.

Three migrations were authored on 2026-05-06 from the same parent (020):
  - ``021_add_account_id_to_extracted_tasks`` (per-tenant isolation IDOR fix)
  - ``021_add_token_usage_log`` (queryable per-(user, agent, day) cost log)
  - ``021_add_quick_steps`` (quick steps column on accounts)

Each is independently correct, but together they create three heads.
Alembic refuses ``upgrade head`` while multiple heads are unmerged, which
would block the next deploy. This is a no-op merge: all three upgrades
have already been applied by the parent revisions.

Revision ID: 022_merge_021_heads
Revises: 021_add_account_id_to_extracted_tasks, 021_add_token_usage_log, 021_add_quick_steps
Create Date: 2026-05-07 00:00:01
"""
from typing import Sequence, Union


revision: str = "022_merge_021_heads"
down_revision: Union[str, Sequence[str], None] = (
    "021_add_account_id_to_extracted_tasks",
    "021_add_token_usage_log",
    "021_add_quick_steps",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
