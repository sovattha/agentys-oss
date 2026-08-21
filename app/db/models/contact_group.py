# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""ContactGroup : groupe de contacts persisté en DB (migration du store JSON).

Remplace ``data/contact_groups.json`` comme source de vérité (chantier
« web tier stateless », audit scalabilité 2026-05-29 rank-6). L'``id`` reste
la string ``grp_<hex>`` historique pour que les ids déjà connus du frontend
survivent à l'import du JSON legacy.

NB volontaire : PAS de ForeignKey sur ``account_id`` — les groupes legacy
créés avant l'isolation par compte portent le sentinel ``-1`` (orphelins,
servis uniquement aux appels loopback desktop) et doivent rester
représentables ; une FK vers ``accounts.id`` casserait leur import sur
Postgres. Le nettoyage par compte passe par
``ContactGroupRepository.delete_all_for_account``.
"""

from datetime import datetime
from typing import Any, Dict, Optional

import json

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class ContactGroupRow(Base):
    """Mapping ORM pour la table ``contact_groups``."""

    __tablename__ = "contact_groups"
    __table_args__ = (
        Index("ix_contact_groups_account_id", "account_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    emoji: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    label_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    members_json: Mapped[str] = mapped_column(Text, nullable=False)
    virtual_meeting: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    use_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise au format EXACT du store JSON historique.

        Le contrat API (frontend ContactGroupsManager, quicksteps forward)
        a été écrit contre ce format — il ne doit pas bouger pendant la
        migration de persistance.
        """
        try:
            members = json.loads(self.members_json) if self.members_json else []
        except (TypeError, ValueError):
            members = []
        return {
            "id": self.id,
            "name": self.name,
            "emoji": self.emoji,
            "description": self.description,
            "label_name": self.label_name,
            "members": members,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "use_count": self.use_count,
            "account_id": self.account_id,
            "virtual_meeting": bool(self.virtual_meeting),
        }
