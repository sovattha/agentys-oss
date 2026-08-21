"""Add email_labels table for SQL-based label search.

Revision ID: 008_email_labels
Revises: 007_signature_user_modified
Create Date: 2026-02-27 00:00:01

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "008_email_labels"
down_revision: Union[str, None] = "007_signature_user_modified"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "email_labels",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("email_id", sa.String(255), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("label_name", sa.String(100), nullable=False),
    )
    op.create_index("ix_email_labels_label_account", "email_labels", ["label_name", "account_id"])
    op.create_index("ix_email_labels_email_id", "email_labels", ["email_id"])


def downgrade() -> None:
    op.drop_index("ix_email_labels_label_account", table_name="email_labels")
    op.drop_index("ix_email_labels_email_id", table_name="email_labels")
    op.drop_table("email_labels")
