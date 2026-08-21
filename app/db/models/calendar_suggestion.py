# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Suggestions d'engagement IA (calendar) : persistées en DB.

Remplace ``data/calendar_suggestions.json`` (dict module-level de
calendar.py, audit Calendar-HIGH-2) — chantier « web tier stateless »,
suite des migrations 039/040/041. Mêmes choix de fidélité : id uuid string
historique en PK, ``account_id`` = string OAuth hash, dates ISO verbatim.
"""

from typing import Any, Dict, Optional

from sqlalchemy import Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class CalendarSuggestionRow(Base):
    """Mapping ORM pour la table ``calendar_suggestions``."""

    __tablename__ = "calendar_suggestions"
    __table_args__ = (
        Index("ix_calendar_suggestions_account_id", "account_id"),
        Index("ix_calendar_suggestions_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    email_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    deadline: Mapped[Optional[str]] = mapped_column(String(48), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[Optional[str]] = mapped_column(String(48), nullable=True)
    email_subject: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    email_sender: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    draft_body_preview: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    def to_record(self) -> Dict[str, Any]:
        """Record au format EXACT du store JSON historique (sans l'id)."""
        return {
            "email_id": self.email_id,
            "account_id": self.account_id,
            "description": self.description,
            "deadline": self.deadline,
            "status": self.status,
            "created_at": self.created_at,
            "email_subject": self.email_subject,
            "email_sender": self.email_sender,
            "draft_body_preview": self.draft_body_preview,
        }

    def apply_record(self, record: Dict[str, Any]) -> None:
        """Écrit un record dict (format historique) dans la row (tolérant)."""
        self.account_id = str(record.get("account_id") or "")
        self.email_id = record.get("email_id")
        self.description = record.get("description")
        self.deadline = record.get("deadline")
        self.status = str(record.get("status") or "pending")
        self.created_at = record.get("created_at")
        self.email_subject = record.get("email_subject")
        self.email_sender = record.get("email_sender")
        self.draft_body_preview = record.get("draft_body_preview")
