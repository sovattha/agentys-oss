"""Add settings_json column to accounts table for per-account settings isolation.

Each account can now have its own settings overrides stored as JSON, merged
on top of the global data/settings.json defaults.

Revision ID: 011_add_settings_json
Revises: 010_fix_email_id_unique
Create Date: 2026-03-24 00:00:01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "011_add_settings_json"
down_revision: Union[str, None] = "010_fix_email_id_unique"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite requires batch mode to alter tables
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.add_column(sa.Column("settings_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.drop_column("settings_json")
