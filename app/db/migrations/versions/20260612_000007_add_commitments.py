"""Add commitments table (migration de la base annexe vers la DB principale).

Chantier « web tier stateless » : ``data/commitments.db`` (SQLite annexe à
connexion directe partagée + RLock) cesse d'exister — même gabarit que la
migration 043 ``scheduled_emails``. L'import des lignes legacy est fait
paresseusement par ``CommitmentAdapter`` au premier usage en mode DB
principale (tolérant au schéma pré-``account_id``, fichier parqué en
``.imported``).

Revision ID: 045_add_commitments
Revises: 044_add_batch_queue
Create Date: 2026-06-12 00:00:07
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "045_add_commitments"
down_revision: Union[str, None] = "044_add_batch_queue"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_names() -> set[str]:
    bind = op.get_bind()
    return set(sa.inspect(bind).get_table_names())


def upgrade() -> None:
    if "commitments" in _table_names():
        return

    op.create_table(
        "commitments",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("email_id", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("detected_at", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("deadline", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.Text(), nullable=True),
        sa.Column("account_id", sa.Integer(), nullable=True),
    )
    op.create_index("idx_commitments_email_id", "commitments", ["email_id"])
    op.create_index("idx_commitments_status", "commitments", ["status"])
    op.create_index("idx_commitments_account_id", "commitments", ["account_id"])


def downgrade() -> None:
    if "commitments" not in _table_names():
        return
    op.drop_index("idx_commitments_account_id", table_name="commitments")
    op.drop_index("idx_commitments_status", table_name="commitments")
    op.drop_index("idx_commitments_email_id", table_name="commitments")
    op.drop_table("commitments")
