"""Add ambassador program tables.

Programme de parrainage avec commission réelle : ``ambassadors``,
``ambassador_referrals`` et ``ambassador_commissions``.

Tables préfixées ``ambassador_*`` pour ne PAS entrer en collision avec la table
legacy ``referrals`` (email-based, vestige du MVP) du ``SCHEMA`` SQLite
historique de ``app/infrastructure/database.py``.

Idempotente (``if <table> not in tables``) pour rejouabilité sur DB existantes.

Revision ID: 046_add_ambassador_program
Revises: 045_add_commitments
Create Date: 2026-06-18 00:00:01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "046_add_ambassador_program"
down_revision: Union[str, None] = "045_add_commitments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_names() -> set:
    bind = op.get_bind()
    return set(sa.inspect(bind).get_table_names())


def upgrade() -> None:
    tables = _table_names()

    if "ambassadors" not in tables:
        op.create_table(
            "ambassadors",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.BigInteger(), nullable=False),
            sa.Column("code", sa.String(length=32), nullable=False),
            sa.Column("stripe_coupon_id", sa.String(length=255), nullable=True),
            sa.Column("stripe_promotion_code_id", sa.String(length=255), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_ambassadors_user_id", "ambassadors", ["user_id"], unique=True)
        op.create_index("ix_ambassadors_code", "ambassadors", ["code"], unique=True)

    if "ambassador_referrals" not in tables:
        op.create_table(
            "ambassador_referrals",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "ambassador_id",
                sa.Integer(),
                sa.ForeignKey("ambassadors.id"),
                nullable=False,
            ),
            sa.Column("referred_user_id", sa.BigInteger(), nullable=False),
            sa.Column("referred_stripe_customer_id", sa.String(length=255), nullable=False),
            sa.Column("signed_up_at", sa.DateTime(), nullable=False),
            sa.Column("commission_window_end", sa.DateTime(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "referred_stripe_customer_id", name="uq_ambassador_referrals_customer"
            ),
        )
        op.create_index(
            "ix_ambassador_referrals_ambassador_id", "ambassador_referrals", ["ambassador_id"]
        )
        op.create_index(
            "ix_ambassador_referrals_referred_user_id",
            "ambassador_referrals",
            ["referred_user_id"],
        )
        op.create_index(
            "ix_ambassador_referrals_referred_stripe_customer_id",
            "ambassador_referrals",
            ["referred_stripe_customer_id"],
        )

    if "ambassador_commissions" not in tables:
        op.create_table(
            "ambassador_commissions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "referral_id",
                sa.Integer(),
                sa.ForeignKey("ambassador_referrals.id"),
                nullable=False,
            ),
            sa.Column("stripe_invoice_id", sa.String(length=255), nullable=False),
            sa.Column("amount_net", sa.BigInteger(), nullable=False),
            sa.Column("commission_amount", sa.BigInteger(), nullable=False),
            sa.Column("currency", sa.String(length=8), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("paid_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "stripe_invoice_id", name="uq_ambassador_commissions_invoice"
            ),
        )
        op.create_index(
            "ix_ambassador_commissions_referral_id", "ambassador_commissions", ["referral_id"]
        )


def downgrade() -> None:
    tables = _table_names()
    if "ambassador_commissions" in tables:
        op.drop_table("ambassador_commissions")
    if "ambassador_referrals" in tables:
        op.drop_table("ambassador_referrals")
    if "ambassadors" in tables:
        op.drop_table("ambassadors")
