"""Add categories_json column to onboarding_results.

Revision ID: 006_add_categories_json
Revises: 005_onboarding_results
Create Date: 2026-02-16 00:00:01

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "006_add_categories_json"
down_revision: Union[str, None] = "005_onboarding_results"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "onboarding_results",
        sa.Column("categories_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("onboarding_results", "categories_json")
