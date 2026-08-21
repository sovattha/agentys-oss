# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Entites pour le suivi des engagements (Commitments).

Ces entites representent les engagements detectes dans les emails
envoyes, comme des promesses d'action ou des deadlines mentionnees.
"""

from dataclasses import dataclass, replace
from typing import Optional
from enum import Enum


class CommitmentStatus(Enum):
    """Statut d'un engagement."""
    PENDING = "pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    OVERDUE = "overdue"


@dataclass
class Commitment:
    """
    Engagement detecte dans un email envoye.

    Attributes:
        id: Identifiant unique.
        email_id: Reference a l'email source.
        description: Description de l'engagement.
        detected_at: ISO timestamp de detection.
        status: Statut actuel.
        deadline: ISO date optionnelle.
        completed_at: Date de completion si applicable.
    """

    id: str
    email_id: str
    description: str
    detected_at: str
    status: CommitmentStatus
    deadline: Optional[str] = None
    completed_at: Optional[str] = None
    account_id: Optional[int] = None

    def mark_completed(self, completed_at: str) -> "Commitment":
        """Retourne une copie marquee comme completee."""
        return replace(
            self,
            status=CommitmentStatus.COMPLETED,
            completed_at=completed_at,
        )

    def mark_cancelled(self) -> "Commitment":
        """Retourne une copie marquee comme annulee."""
        return replace(self, status=CommitmentStatus.CANCELLED)

    def mark_overdue(self) -> "Commitment":
        """Retourne une copie marquee comme en retard."""
        return replace(self, status=CommitmentStatus.OVERDUE)
