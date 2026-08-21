# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Port pour les brouillons en attente de validation.

Ce port définit le contrat pour la gestion des pending drafts
générés automatiquement par le daemon.
"""

from abc import ABC, abstractmethod
from typing import List, Optional

from app.domain.entities.pending_draft import PendingDraft, PendingDraftStatus


class PendingDraftStorePort(ABC):
    """
    Port pour la gestion des brouillons en attente.

    Responsabilités:
    - Stocker les brouillons générés automatiquement
    - Récupérer les brouillons en attente de validation
    - Mettre à jour le statut (validé, rejeté, modifié)
    - Supprimer les brouillons traités
    """

    @abstractmethod
    def add(self, pending_draft: PendingDraft) -> str:
        """
        Ajoute un brouillon en attente.

        Args:
            pending_draft: Le brouillon à stocker.

        Returns:
            L'ID du brouillon créé.
        """
        pass

    @abstractmethod
    def get_by_id(self, draft_id: str) -> Optional[PendingDraft]:
        """
        Récupère un brouillon par son ID.

        Args:
            draft_id: Identifiant du brouillon.

        Returns:
            Le brouillon ou None si non trouvé.
        """
        pass

    @abstractmethod
    def get_pending(self, limit: int = 50) -> List[PendingDraft]:
        """
        Récupère les brouillons en attente de validation.

        Args:
            limit: Nombre maximum de brouillons.

        Returns:
            Liste des brouillons en attente (les plus récents en premier).
        """
        pass

    @abstractmethod
    def get_all(self, limit: int = 100) -> List[PendingDraft]:
        """
        Récupère tous les brouillons.

        Args:
            limit: Nombre maximum de brouillons.

        Returns:
            Liste de tous les brouillons.
        """
        pass

    @abstractmethod
    def update_status(
        self,
        draft_id: str,
        status: PendingDraftStatus,
        gmail_draft_id: Optional[str] = None,
    ) -> bool:
        """
        Met à jour le statut d'un brouillon.

        Args:
            draft_id: ID du brouillon.
            status: Nouveau statut.
            gmail_draft_id: ID du brouillon Gmail si validé.

        Returns:
            True si la mise à jour a réussi, False sinon.
        """
        pass

    @abstractmethod
    def update_content(
        self,
        draft_id: str,
        draft_subject: str,
        draft_body: str,
    ) -> bool:
        """
        Met à jour le contenu d'un brouillon.

        Args:
            draft_id: ID du brouillon.
            draft_subject: Nouveau sujet.
            draft_body: Nouveau corps.

        Returns:
            True si la mise à jour a réussi, False sinon.
        """
        pass

    @abstractmethod
    def delete(self, draft_id: str) -> bool:
        """
        Supprime un brouillon.

        Args:
            draft_id: ID du brouillon à supprimer.

        Returns:
            True si la suppression a réussi, False sinon.
        """
        pass

    @abstractmethod
    def count_pending(self) -> int:
        """
        Compte les brouillons en attente.

        Returns:
            Nombre de brouillons en attente.
        """
        pass

    @abstractmethod
    def get_by_email_id(self, email_id: str) -> Optional[PendingDraft]:
        """
        Récupère un brouillon par l'ID de l'email source.

        Args:
            email_id: ID de l'email source.

        Returns:
            Le brouillon ou None si non trouvé.
        """
        pass

    @abstractmethod
    def get_unsent(self, limit: int = 50) -> List[PendingDraft]:
        """
        Récupère les brouillons non envoyés (pour badge "Draft prêt").

        Inclut les statuts PENDING, VALIDATED et MODIFIED.
        Le badge reste affiché tant que l'utilisateur n'a pas envoyé
        la réponse (status SENT).

        Args:
            limit: Nombre maximum de brouillons.

        Returns:
            Liste des brouillons non envoyés (les plus récents en premier).
        """
        pass
