"""Add legal consent proof records.

Revision ID: 033_legal_consents
Revises: 032_schema_contract
Create Date: 2026-05-30 00:00:02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "033_legal_consents"
down_revision: Union[str, None] = "032_schema_contract"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if "legal_consents" in set(sa.inspect(bind).get_table_names()):
        return

    op.create_table(
        "legal_consents",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("terms_version", sa.String(length=64), nullable=False),
        sa.Column("privacy_version", sa.String(length=64), nullable=False),
        sa.Column("accepted_at", sa.DateTime(), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
    )
    op.create_index(
        "ix_legal_consents_provider_accepted",
        "legal_consents",
        ["provider", "accepted_at"],
    )
    op.create_index("ix_legal_consents_account_id", "legal_consents", ["account_id"])
    op.create_index("ix_legal_consents_user_id", "legal_consents", ["user_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if "legal_consents" not in set(sa.inspect(bind).get_table_names()):
        return
    op.drop_index("ix_legal_consents_user_id", table_name="legal_consents")
    op.drop_index("ix_legal_consents_account_id", table_name="legal_consents")
    op.drop_index("ix_legal_consents_provider_accepted", table_name="legal_consents")
    op.drop_table("legal_consents")
