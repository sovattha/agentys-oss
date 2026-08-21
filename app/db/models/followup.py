# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Follow-ups : persistés en DB (migration du store JSON de calendar.py).

Remplace ``data/followups.json`` (objet ``{followup_id: record}`` chargé en
mémoire à l'import du module calendar) comme source de vérité — chantier
« web tier stateless », suite des migrations 039/040.

Choix de fidélité au contrat historique :
- ``id`` = l'uuid4 string historique (PK) — les ids connus du FE survivent.
- ``account_id`` est la **string OAuth hash** (``acc_…``/hash), PAS l'int DB :
  c'est le format que tout calendar.py manipule (`_validate_account_ownership`,
  providers). Pas de FK possible ni souhaitable.
- les dates (``due_date``, ``created_at``, ``completed_at``, ``snoozed_until``)
  restent des strings ISO renvoyées verbatim par l'API — le store historique
  acceptait des ISO aware OU naïfs et les re-servait tels quels.
"""

from typing import Any, Dict, Optional

from sqlalchemy import Boolean, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class FollowupRow(Base):
    """Mapping ORM pour la table ``followups``."""

    __tablename__ = "followups"
    __table_args__ = (
        Index("ix_followups_account_id", "account_id"),
        Index("ix_followups_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    email_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    due_date: Mapped[Optional[str]] = mapped_column(String(48), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[Optional[str]] = mapped_column(String(48), nullable=True)
    completed_at: Mapped[Optional[str]] = mapped_column(String(48), nullable=True)
    snoozed_until: Mapped[Optional[str]] = mapped_column(String(48), nullable=True)
    snooze_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    calendar_event_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sync_to_calendar: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    email_subject: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    email_sender: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    auto_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ai_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    def to_record(self) -> Dict[str, Any]:
        """Record au format EXACT du store JSON historique (sans l'id —
        l'id était la CLÉ du dict ; les routes composent ``{"id": fid, **rec}``)."""
        return {
            "email_id": self.email_id,
            "account_id": self.account_id,
            "title": self.title,
            "description": self.description,
            "due_date": self.due_date,
            "status": self.status,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "snoozed_until": self.snoozed_until,
            "snooze_count": self.snooze_count,
            "calendar_event_id": self.calendar_event_id,
            "sync_to_calendar": bool(self.sync_to_calendar),
            "email_subject": self.email_subject,
            "email_sender": self.email_sender,
            "auto_created": bool(self.auto_created),
            "ai_reason": self.ai_reason,
        }

    def apply_record(self, record: Dict[str, Any]) -> None:
        """Écrit un record dict (format historique) dans la row.

        Tolérant aux champs manquants (records legacy partiels) ; les champs
        inconnus du schéma sont ignorés — le store historique laissait passer
        n'importe quelle clé, mais aucune n'est produite par le code vivant.
        """
        self.account_id = str(record.get("account_id") or "")
        self.email_id = record.get("email_id")
        self.title = str(record.get("title") or "")
        self.description = record.get("description")
        self.due_date = record.get("due_date")
        self.status = str(record.get("status") or "pending")
        self.created_at = record.get("created_at")
        self.completed_at = record.get("completed_at")
        self.snoozed_until = record.get("snoozed_until")
        self.snooze_count = int(record.get("snooze_count", 0) or 0)
        self.calendar_event_id = record.get("calendar_event_id")
        self.sync_to_calendar = bool(record.get("sync_to_calendar", False))
        self.email_subject = record.get("email_subject")
        self.email_sender = record.get("email_sender")
        self.auto_created = bool(record.get("auto_created", False))
        self.ai_reason = record.get("ai_reason")
