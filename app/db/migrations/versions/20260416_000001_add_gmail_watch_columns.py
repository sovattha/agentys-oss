"""Add Gmail watch tracking columns to accounts (Pub/Sub push).

Adds two columns used by the Gmail Pub/Sub push integration:

- ``gmail_watch_expiration``: server-reported expiration of users.watch().
  Gmail force-renews after at most 7 days; we renew daily.
- ``gmail_watch_topic``: fully-qualified Pub/Sub topic the watch points at.
  Stored per-account so multi-tenant deployments can route to a topic per
  Google Cloud project if needed.

Revision ID: 015_add_gmail_watch
Revises: 014_add_account_id_to_draft_history
Create Date: 2026-04-16 00:00:01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "015_add_gmail_watch"
down_revision: Union[str, None] = "014_add_account_id_to_draft_history"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.add_column(
            sa.Column("gmail_watch_expiration", sa.DateTime(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("gmail_watch_topic", sa.String(length=512), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.drop_column("gmail_watch_topic")
        batch_op.drop_column("gmail_watch_expiration")
