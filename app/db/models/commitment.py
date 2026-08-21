# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Commitments : persistés dans la DB principale (migration 045).

Remplace la base annexe ``data/commitments.db`` (chantier « web tier
stateless », même gabarit que la migration 043 ``scheduled_emails``).

Fidélité au schéma historique (``CommitmentAdapter.TABLE_SCHEMA``) :
- ``id`` = TEXT PK (chaîne dérivée de ``f"{email_id}-{hash(desc) % 10000}"``
  côté use case — longueur non bornée car les ids Outlook sont longs) ;
- timestamps en TEXT ISO **local naïf** (``datetime.now().isoformat()``) —
  contrat historique conservé tel quel, ne PAS normaliser en UTC ;
- ``deadline`` = TEXT libre (aucune validation de format, caractérisé) ;
- ``status`` = TEXT avec DEFAULT 'pending' (valeurs de ``CommitmentStatus``) ;
- ``account_id`` nullable : le writer daemon n'en fournit pas (lignes NULL
  jamais purgées par ``delete_by_account`` — P3 connu, conservé tel quel).
"""

from typing import Optional

from sqlalchemy import Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class CommitmentRow(Base):
    """Mapping ORM pour la table ``commitments``."""

    __tablename__ = "commitments"
    __table_args__ = (
        Index("idx_commitments_email_id", "email_id"),
        Index("idx_commitments_status", "status"),
        Index("idx_commitments_account_id", "account_id"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    email_id: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    detected_at: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    deadline: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    completed_at: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    account_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
