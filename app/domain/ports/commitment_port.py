# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Port pour le suivi des engagements (Commitments).

Ce port definit le contrat pour la gestion des engagements
detectes dans les emails envoyes.
"""

from abc import ABC, abstractmethod
from typing import List, Optional

from app.domain.entities.commitment import Commitment


class CommitmentTrackerPort(ABC):
    """
    Port pour le suivi des engagements.

    Responsabilites:
    - Tracker les engagements detectes
    - Identifier les engagements en attente
    - Gerer les statuts (complete, annule, en retard)
    - Fournir des requetes par email ou par ID
    """

    # =========================================================================
    # Gestion des engagements
    # =========================================================================

    @abstractmethod
    def add_commitment(self, commitment: Commitment) -> None:
        """
        Ajoute un engagement pour suivi.

        Args:
            commitment: Engagement a tracker.
        """
        pass

    @abstractmethod
    def get_pending(self) -> List[Commitment]:
        """
        Recupere les engagements en attente.

        Returns:
            Liste des engagements avec statut PENDING.
        """
        pass

    @abstractmethod
    def get_by_email(self, email_id: str) -> List[Commitment]:
        """
        Recupere les engagements associes a un email.

        Args:
            email_id: ID de l'email source.

        Returns:
            Liste des engagements pour cet email.
        """
        pass

    @abstractmethod
    def get_overdue(self) -> List[Commitment]:
        """
        Recupere les engagements en retard.

        Returns:
            Liste des engagements avec statut OVERDUE.
        """
        pass

    # =========================================================================
    # Actions
    # =========================================================================

    @abstractmethod
    def mark_completed(self, commitment_id: str) -> bool:
        """
        Marque un engagement comme complete.

        Args:
            commitment_id: ID de l'engagement.

        Returns:
            True si la mise a jour a reussi.
        """
        pass

    @abstractmethod
    def mark_cancelled(self, commitment_id: str) -> bool:
        """
        Marque un engagement comme annule.

        Args:
            commitment_id: ID de l'engagement.

        Returns:
            True si la mise a jour a reussi.
        """
        pass

    # =========================================================================
    # Requetes
    # =========================================================================

    @abstractmethod
    def get_by_id(self, commitment_id: str) -> Optional[Commitment]:
        """
        Recupere un engagement par son ID.

        Args:
            commitment_id: ID de l'engagement.

        Returns:
            L'engagement ou None si non trouve.
        """
        pass

    @abstractmethod
    def get_all(self) -> List[Commitment]:
        """
        Recupere tous les engagements.

        Returns:
            Liste de tous les engagements.
        """
        pass
