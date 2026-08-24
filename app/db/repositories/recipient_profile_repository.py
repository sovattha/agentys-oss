# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Repository pour ``RecipientProfile`` (#190).

Persiste les profils DISC inférés par le service heuristique (ou un LLM en
phase 2) et les restitue sous forme d'entity immuable au Drafter.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.recipient_profile import RecipientProfileRow
from app.domain.entities.recipient_profile import (
    DISCScores,
    DISCType,
    RecipientProfile,
)


def _scores_to_json(scores: Optional[DISCScores]) -> Optional[str]:
    if scores is None:
        return None
    return json.dumps(scores.to_dict())


def _scores_from_json(raw: Optional[str]) -> Optional[DISCScores]:
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return DISCScores(**data)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _row_to_entity(row: RecipientProfileRow) -> RecipientProfile:
    try:
        disc = DISCType(row.disc)
    except ValueError:
        disc = DISCType.UNKNOWN
    return RecipientProfile(
        email=row.recipient_email,
        disc=disc,
        disc_scores=_scores_from_json(row.disc_scores_json),
        confidence=row.confidence,
        sample_size=row.sample_size,
        source=row.source,
        updated_at=row.updated_at,
    )


class RecipientProfileRepository:
    """Repository scoped par ``account_id`` pour les profils DISC."""

    def __init__(self, session: Session):
        self._session = session

    def get(self, account_id: int, recipient_email: str) -> Optional[RecipientProfile]:
        """Retourne le profil d'un contact, ou None si absent."""
        row = self._session.execute(
            select(RecipientProfileRow)
            .where(RecipientProfileRow.account_id == account_id)
            .where(RecipientProfileRow.recipient_email == recipient_email.lower())
        ).scalar_one_or_none()
        if row is None:
            return None
        return _row_to_entity(row)

    def upsert(self, account_id: int, profile: RecipientProfile) -> None:
        """Insère ou met à jour le profil.

        L'unicité est garantie par la contrainte
        ``uq_recipient_profiles_account_email``. On lit d'abord pour mettre
        à jour en place (évite les side-effects d'un upsert atomique
        SQLite-spécifique). Pas de commit : appelant décide.
        """
        email_lower = profile.email.lower()
        existing = self._session.execute(
            select(RecipientProfileRow)
            .where(RecipientProfileRow.account_id == account_id)
            .where(RecipientProfileRow.recipient_email == email_lower)
        ).scalar_one_or_none()

        now = datetime.now(timezone.utc)

        if existing is None:
            row = RecipientProfileRow(
                account_id=account_id,
                recipient_email=email_lower,
                disc=profile.disc.value,
                confidence=profile.confidence,
                sample_size=profile.sample_size,
                source=profile.source,
                disc_scores_json=_scores_to_json(profile.disc_scores),
                updated_at=now,
            )
            self._session.add(row)
        else:
            existing.disc = profile.disc.value
            existing.confidence = profile.confidence
            existing.sample_size = profile.sample_size
            existing.source = profile.source
            existing.disc_scores_json = _scores_to_json(profile.disc_scores)
            existing.updated_at = now

        self._session.flush()

    def delete(self, account_id: int, recipient_email: str) -> bool:
        """Supprime le profil si présent. True si une ligne a été supprimée."""
        row = self._session.execute(
            select(RecipientProfileRow)
            .where(RecipientProfileRow.account_id == account_id)
            .where(RecipientProfileRow.recipient_email == recipient_email.lower())
        ).scalar_one_or_none()
        if row is None:
            return False
        self._session.delete(row)
        self._session.flush()
        return True

    def count_for_account(self, account_id: int) -> int:
        """Nombre de profils persistés pour un account (analytics, admin)."""
        result = self._session.execute(
            select(RecipientProfileRow)
            .where(RecipientProfileRow.account_id == account_id)
        ).scalars().all()
        return len(result)
