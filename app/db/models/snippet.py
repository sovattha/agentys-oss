# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Snippets + partages : persistés en DB (migration des stores JSON).

Remplace ``data/snippets.json`` et ``data/snippet_shares.json`` comme source
de vérité (chantier « web tier stateless », suite de la migration 039
contact_groups). Choix de fidélité au contrat historique :

- ``id`` reste la string ``snippet_<hex>`` / ``share_<hex>`` (PK) — les ids
  connus du frontend survivent à l'import du JSON legacy.
- ``owner_email`` NULLABLE : un snippet legacy sans propriétaire est visible
  et éditable par TOUT utilisateur authentifié (``_is_owner`` historique) —
  cette sémantique est portée telle quelle.
- ``account_id`` NULLABLE (et sans FK) : NULL = visible dans tous les comptes
  du propriétaire (contrat du filtre ``?account_id=``).
- ``created_at``/``updated_at``/``shared_at`` stockés en TEXT : le store
  historique émet des ISO 8601 timezone-aware (``+00:00``) que le contrat
  API renvoie verbatim — une colonne DateTime SQLite perdrait le fuseau.
- ``to``/``cc``/``bcc`` stockés JSON-encodés (``*_json``) : le store
  historique acceptait n'importe quelle valeur JSON (string libre du FE,
  potentiellement liste) et la renvoyait telle quelle.
"""

from typing import Any, Dict, Optional

import json

from sqlalchemy import Boolean, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


def _decode_json(value: Optional[str]) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


class SnippetRow(Base):
    """Mapping ORM pour la table ``snippets``."""

    __tablename__ = "snippets"
    __table_args__ = (
        Index("ix_snippets_owner_email", "owner_email"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    account_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    to_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cc_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    bcc_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_private: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    use_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[str] = mapped_column(String(48), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(48), nullable=False)

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise au format EXACT du store JSON historique."""
        return {
            "id": self.id,
            "name": self.name,
            "content": self.content,
            "subject": self.subject,
            "to": _decode_json(self.to_json),
            "cc": _decode_json(self.cc_json),
            "bcc": _decode_json(self.bcc_json),
            "category": self.category,
            "is_private": bool(self.is_private),
            "owner_email": self.owner_email,
            "account_id": self.account_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "use_count": self.use_count,
        }


class SnippetShareRow(Base):
    """Mapping ORM pour la table ``snippet_shares``."""

    __tablename__ = "snippet_shares"
    __table_args__ = (
        Index("ix_snippet_shares_snippet_id", "snippet_id"),
        Index("ix_snippet_shares_shared_with", "shared_with"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    snippet_id: Mapped[str] = mapped_column(String(64), nullable=False)
    shared_by: Mapped[str] = mapped_column(String(320), nullable=False)
    shared_with: Mapped[str] = mapped_column(String(320), nullable=False)
    shared_at: Mapped[str] = mapped_column(String(48), nullable=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "snippet_id": self.snippet_id,
            "shared_by": self.shared_by,
            "shared_with": self.shared_with,
            "shared_at": self.shared_at,
        }
