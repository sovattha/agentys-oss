# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Ports pour l'édition temps réel des brouillons.

Ces interfaces définissent les contrats pour les adaptateurs de:
- Stockage des sessions d'édition
- Traitement des changements de texte
- Génération de suggestions IA
"""

from abc import ABC, abstractmethod
from typing import Optional, List

from app.domain.entities.realtime_edit import (
    EditSession,
    TextChange,
    EditTrigger,
    Suggestion,
    SuggestionResult,
)


class EditSessionStorePort(ABC):
    """
    Port pour la persistance des sessions d'édition.

    Responsable de sauvegarder, récupérer et supprimer
    les sessions d'édition temps réel.
    """

    @abstractmethod
    def save(self, session: EditSession) -> None:
        """
        Sauvegarde une session d'édition.

        Args:
            session: La session à sauvegarder.
        """
        pass

    @abstractmethod
    def get(self, session_id: str) -> Optional[EditSession]:
        """
        Récupère une session par son ID.

        Args:
            session_id: L'identifiant de la session.

        Returns:
            La session si trouvée, None sinon.
        """
        pass

    @abstractmethod
    def delete(self, session_id: str) -> bool:
        """
        Supprime une session.

        Args:
            session_id: L'identifiant de la session.

        Returns:
            True si supprimée, False si non trouvée.
        """
        pass

    @abstractmethod
    def get_by_user(self, user_id: str) -> List[EditSession]:
        """
        Récupère toutes les sessions actives d'un utilisateur.

        Args:
            user_id: L'identifiant de l'utilisateur.

        Returns:
            Liste des sessions actives.
        """
        pass

    @abstractmethod
    def cleanup_expired(self, timeout_minutes: int = 30) -> int:
        """
        Nettoie les sessions expirées.

        Args:
            timeout_minutes: Durée d'inactivité avant expiration.

        Returns:
            Nombre de sessions supprimées.
        """
        pass


class RealTimeEditPort(ABC):
    """
    Port principal pour l'édition temps réel.

    Coordonne les opérations de session et de suggestion.
    """

    @abstractmethod
    def start_session(
        self,
        user_id: str,
        initial_text: str = "",
    ) -> EditSession:
        """
        Démarre une nouvelle session d'édition.

        Args:
            user_id: ID de l'utilisateur.
            initial_text: Texte initial optionnel.

        Returns:
            La nouvelle session créée.
        """
        pass

    @abstractmethod
    def process_change(
        self,
        session_id: str,
        change: TextChange,
    ) -> Optional[EditSession]:
        """
        Traite un changement de texte.

        Args:
            session_id: ID de la session.
            change: Le changement à appliquer.

        Returns:
            La session mise à jour, None si non trouvée.
        """
        pass

    @abstractmethod
    def get_suggestion(
        self,
        session_id: str,
        trigger: EditTrigger,
    ) -> Optional[SuggestionResult]:
        """
        Génère une suggestion pour le texte courant.

        Args:
            session_id: ID de la session.
            trigger: Le déclencheur de la suggestion.

        Returns:
            Le résultat de suggestion, None si pas applicable.
        """
        pass

    @abstractmethod
    def apply_suggestion(
        self,
        session_id: str,
        suggestion: Suggestion,
        accept: bool,
    ) -> Optional[EditSession]:
        """
        Applique ou rejette une suggestion.

        Args:
            session_id: ID de la session.
            suggestion: La suggestion à traiter.
            accept: True pour accepter, False pour rejeter.

        Returns:
            La session mise à jour.
        """
        pass

    @abstractmethod
    def close_session(self, session_id: str) -> Optional[EditSession]:
        """
        Ferme une session d'édition.

        Args:
            session_id: ID de la session.

        Returns:
            La session fermée, None si non trouvée.
        """
        pass


class SuggestionHistoryPort(ABC):
    """
    Port pour l'historique des suggestions.

    Permet de conserver les suggestions pour le learning.
    """

    @abstractmethod
    def save_suggestion(
        self,
        session_id: str,
        result: SuggestionResult,
    ) -> None:
        """
        Sauvegarde un résultat de suggestion.

        Args:
            session_id: ID de la session.
            result: Le résultat à sauvegarder.
        """
        pass

    @abstractmethod
    def get_suggestions(
        self,
        session_id: str,
    ) -> List[SuggestionResult]:
        """
        Récupère l'historique des suggestions d'une session.

        Args:
            session_id: ID de la session.

        Returns:
            Liste des résultats de suggestion.
        """
        pass

    @abstractmethod
    def get_accepted_suggestions(
        self,
        user_id: str,
        limit: int = 100,
    ) -> List[SuggestionResult]:
        """
        Récupère les suggestions acceptées par un utilisateur.

        Utile pour le learning et l'amélioration des prompts.

        Args:
            user_id: ID de l'utilisateur.
            limit: Nombre maximum de résultats.

        Returns:
            Liste des suggestions acceptées.
        """
        pass
