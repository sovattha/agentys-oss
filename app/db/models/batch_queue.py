# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Batch queue : persistée dans la DB principale (migration 044).

Remplace la base annexe ``data/batch_queue.db`` (chantier « web tier
stateless ») — deux tables : la file de requêtes batch (``batch_queue``,
une ligne par draft à soumettre à l'API Anthropic Message Batches) et le
suivi des batches en vol (``active_batches``).

Fidélité au schéma historique :
- ``id`` = ``str(uuid.uuid4())`` (PK, 36 caractères avec tirets) ;
- ``account_id`` stocké en TEXT (``''`` = sentinelle legacy mono-compte,
  conservée telle quelle — le filtre ``account_id = ? OR account_id = ''``
  du store en dépend) ;
- ``metadata`` (JSON brut TEXT) est mappé sur l'attribut ``metadata_json``
  (``metadata`` est réservé par SQLAlchemy Declarative) mais le NOM de
  colonne reste ``metadata`` — le contrat dict du store expose la clé
  ``"metadata"`` avec la string JSON brute, comme ``dict(sqlite3.Row)`` ;
- timestamps en TEXT ISO LOCAL-NAÏF (``datetime.now().isoformat()`` —
  divergence VOLONTAIRE vs la migration 043 qui est UTC) : toutes les
  comparaisons SQL du store (``ORDER BY created_at``, ``submitted_at < ?``,
  ``completed_at < ?``) sont LEXICOGRAPHIQUES sur ce format constant et
  restent correctes ; ne PAS « corriger » en UTC, la fenêtre stale se
  décalerait de plusieurs heures ;
- ``status`` batch_queue : pending|submitted|completed|failed (``expired``
  n'est jamais écrit mais reste filtré par ``cleanup_old``) ;
- ``status`` active_batches : in_progress|ended (upsert historique
  ``INSERT OR REPLACE`` → ``session.merge`` côté store, portable Postgres).
"""

from typing import Optional

from sqlalchemy import Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class BatchQueueItemRow(Base):
    """Mapping ORM pour la table ``batch_queue``."""

    __tablename__ = "batch_queue"
    __table_args__ = (
        Index("idx_batch_queue_status", "status"),
        Index("idx_batch_queue_email_id", "email_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email_id: Mapped[str] = mapped_column(Text, nullable=False)
    account_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tier: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    user_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=512)
    temperature: Mapped[Optional[float]] = mapped_column(Float, nullable=True, default=0.5)
    metadata_json: Mapped[Optional[str]] = mapped_column("metadata", Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    batch_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    result_draft: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    input_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    output_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    created_at: Mapped[str] = mapped_column(String(48), nullable=False)
    submitted_at: Mapped[Optional[str]] = mapped_column(String(48), nullable=True)
    completed_at: Mapped[Optional[str]] = mapped_column(String(48), nullable=True)


class ActiveBatchRow(Base):
    """Mapping ORM pour la table ``active_batches`` (batches Anthropic en vol)."""

    __tablename__ = "active_batches"

    batch_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False)
    submitted_at: Mapped[str] = mapped_column(String(48), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="in_progress")
