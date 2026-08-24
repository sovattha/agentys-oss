# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
DraftEditEvent : enregistre le diff entre un draft IA et sa version envoyée.

Alimente la boucle de feedback (#196). Quand l'utilisateur modifie un draft
avant l'envoi, le backend enregistre la nature de l'édition (ton, longueur,
structure, contenu, signature) pour alimenter un ajustement futur des prompts
et du profil d'écriture.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class DraftEditEvent(Base):
    """Événement d'édition d'un brouillon entre génération IA et envoi."""

    __tablename__ = "draft_edit_events"
    __table_args__ = (
        Index("ix_draft_edit_events_account_created", "account_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    account_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    draft_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    original_email_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("emails.id", ondelete="SET NULL"),
        nullable=True,
    )

    category: Mapped[str] = mapped_column(String(32), nullable=False)
    magnitude: Mapped[float] = mapped_column(Float, nullable=False)
    initial_length: Mapped[int] = mapped_column(Integer, nullable=False)
    final_length: Mapped[int] = mapped_column(Integer, nullable=False)

    intent: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    recipient_email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )
