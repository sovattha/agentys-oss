# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Use Case pour le suivi des engagements."""

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from app.domain.entities.commitment import Commitment, CommitmentStatus
from app.domain.ports.commitment_port import CommitmentTrackerPort

if TYPE_CHECKING:
    from app.agents import ExtractedCommitment


@dataclass
class CommitmentTrackingUseCase:
    """
    Use case pour le suivi des engagements.

    Ce use case orchestre les operations sur les engagements
    en deleguant au port d'infrastructure.
    """

    tracker: CommitmentTrackerPort

    def track_commitment(self, commitment: Commitment) -> None:
        """Enregistre un nouvel engagement."""
        self.tracker.add_commitment(commitment)

    def get_pending(self) -> List[Commitment]:
        """Recupere les engagements en attente."""
        return self.tracker.get_pending()

    def get_overdue(self) -> List[Commitment]:
        """Recupere les engagements en retard."""
        return self.tracker.get_overdue()

    def complete(self, commitment_id: str) -> bool:
        """Marque un engagement comme complete."""
        return self.tracker.mark_completed(commitment_id)

    def cancel(self, commitment_id: str) -> bool:
        """Marque un engagement comme annule."""
        return self.tracker.mark_cancelled(commitment_id)

    def get_by_email(self, email_id: str) -> List[Commitment]:
        """Recupere les engagements pour un email."""
        return self.tracker.get_by_email(email_id)

    def get_by_id(self, commitment_id: str) -> Optional[Commitment]:
        """Recupere un engagement par son ID."""
        return self.tracker.get_by_id(commitment_id)

    def get_all(self) -> List[Commitment]:
        """Recupere tous les engagements."""
        return self.tracker.get_all()

    def track_from_extracted(
        self,
        extracted: "List[ExtractedCommitment]",
        email_id: str,
        account_id: Optional[int] = None,
    ) -> List[Commitment]:
        """
        Convertit et enregistre une liste d'engagements extraits.

        Args:
            extracted: Liste d'engagements extraits par le LLM.
            email_id: ID de l'email source.

        Returns:
            Liste des engagements créés et persistés.
        """
        created = []
        for ext in extracted:
            commitment = Commitment(
                id=f"{email_id}-{hash(ext.description) % 10000}",
                email_id=email_id,
                description=ext.description,
                detected_at=datetime.now().isoformat(),
                deadline=ext.deadline,
                status=CommitmentStatus.PENDING,
                account_id=account_id,
            )
            self.tracker.add_commitment(commitment)
            created.append(commitment)
        return created
