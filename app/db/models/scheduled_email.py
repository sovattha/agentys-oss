# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Scheduled emails : persistés dans la DB principale (migration 043).

Remplace la base annexe ``data/scheduled_emails.db`` (chantier « web tier
stateless » — première des side-SQLite à rejoindre la DB alembic-isée).

Fidélité au schéma historique :
- ``id`` = uuid hex string (PK), ``account_id`` = int DB ;
- timestamps en TEXT ISO UTC normalisé (``_to_iso`` du store force
  ``+00:00``) — les comparaisons SQL du store (``send_at <= ?``,
  ``updated_at < ?``) sont LEXICOGRAPHIQUES et restent correctes car le
  format est constant ; on conserve ce contrat tel quel ;
- ``idempotency_key`` UNIQUE (anti double-envoi par reconciliation provider).
"""

from typing import Optional

from sqlalchemy import Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class ScheduledEmailRow(Base):
    """Mapping ORM pour la table ``scheduled_emails``."""

    __tablename__ = "scheduled_emails"
    __table_args__ = (
        Index("idx_scheduled_emails_due", "status", "send_at"),
        Index("idx_scheduled_emails_account", "account_id", "status"),
        Index("idx_scheduled_emails_idempotency", "idempotency_key", unique=True),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    send_at: Mapped[str] = mapped_column(String(48), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[str] = mapped_column(String(48), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(48), nullable=False)
    sent_at: Mapped[Optional[str]] = mapped_column(String(48), nullable=True)
    sent_message_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
