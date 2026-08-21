"""Add avatar_url column to accounts table.

Revision ID: 019_add_avatar_url_to_accounts
Revises: 018_faq_log_account_fk
Create Date: 2026-05-01 00:00:01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "019_add_avatar_url_to_accounts"
down_revision: Union[str, None] = "018_faq_log_account_fk"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.add_column(sa.Column("avatar_url", sa.String(512), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.drop_column("avatar_url")
