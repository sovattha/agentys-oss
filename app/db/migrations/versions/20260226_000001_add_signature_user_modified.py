"""Add signature_user_modified column to accounts table.

Revision ID: 007_signature_user_modified
Revises: 006_categories_json
Create Date: 2026-02-26 00:00:01

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "007_signature_user_modified"
down_revision: Union[str, None] = "006_add_categories_json"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.add_column(
            sa.Column("signature_user_modified", sa.Boolean(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.drop_column("signature_user_modified")
