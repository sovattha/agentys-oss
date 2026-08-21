"""Add contact_groups table (migration du store JSON vers la DB).

Première brique du chantier « web tier stateless » (audit scalabilité
2026-05-29, rank-6) : ``data/contact_groups.json`` cesse d'être la source
de vérité. L'import des données legacy est fait paresseusement par
``app.api.contact_groups._ensure_legacy_import`` au premier accès — cette
migration ne crée que le schéma.

Pas de ForeignKey sur ``account_id`` : les groupes legacy pré-isolation
portent le sentinel ``-1`` et doivent rester importables (cf. modèle).

Revision ID: 039_add_contact_groups
Revises: 038_widen_last_history_id
Create Date: 2026-06-12 00:00:01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "039_add_contact_groups"
down_revision: Union[str, None] = "038_widen_last_history_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_names() -> set[str]:
    bind = op.get_bind()
    return set(sa.inspect(bind).get_table_names())


def upgrade() -> None:
    if "contact_groups" in _table_names():
        return

    op.create_table(
        "contact_groups",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("emoji", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("label_name", sa.Text(), nullable=True),
        sa.Column("members_json", sa.Text(), nullable=False),
        sa.Column("virtual_meeting", sa.Boolean(), nullable=False),
        sa.Column("use_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_contact_groups_account_id",
        "contact_groups",
        ["account_id"],
    )


def downgrade() -> None:
    if "contact_groups" not in _table_names():
        return
    op.drop_index("ix_contact_groups_account_id", table_name="contact_groups")
    op.drop_table("contact_groups")
