# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Port pour l'historique des brouillons.

Ce port definit le contrat que les adapters de persistance
des brouillons doivent implementer.
"""

from abc import ABC, abstractmethod
from typing import List, Optional

from app.domain.entities.draft_history import DraftRecord


class DraftHistoryPort(ABC):
    """
    Port pour la persistance de l'historique des brouillons.

    Responsabilites:
    - Persister les brouillons generes (avec account_id obligatoire)
    - Recuperer les brouillons par ID ou en liste, scopes par compte
    - Mettre a jour le feedback utilisateur
    - Compter les brouillons

    ISOLATION MULTI-COMPTE: toute méthode de lecture scoppe par account_id.
    Les méthodes non scoppees (`get_all`, `get_by_id`, `get_recent`,
    `update_feedback`) sont dépréciées et leves `RuntimeError` en prod via
    les adapters — n'utiliser QUE les variantes `*_for_account`.
    """

    # =========================================================================
    # Méthodes scoped par account_id — à utiliser systématiquement
    # =========================================================================

    @abstractmethod
    def get_all_for_account(
        self, account_id: int, limit: int = 1000
    ) -> List[DraftRecord]:
        """
        Récupère tous les brouillons d'un compte donné.

        Args:
            account_id: ID du compte (int DB, > 0). Si <= 0, renvoie [].
            limit: Nombre maximum de brouillons.

        Returns:
            Liste des brouillons du compte (les plus récents en premier).
            Les rows legacy (account_id NULL) sont toujours exclus.
        """
        pass

    @abstractmethod
    def get_by_id_for_account(
        self, draft_id: str, account_id: int
    ) -> Optional[DraftRecord]:
        """
        Récupère un brouillon par son ID, uniquement s'il appartient au compte.

        Args:
            draft_id: Identifiant du brouillon.
            account_id: ID du compte demandeur.

        Returns:
            Le brouillon ou None si non trouvé OU si appartient à un autre compte.
        """
        pass

    @abstractmethod
    def get_recent_for_account(
        self, account_id: int, days: int = 7
    ) -> List[DraftRecord]:
        """Récupère les brouillons récents d'un compte."""
        pass

    @abstractmethod
    def update_feedback_for_account(
        self,
        draft_id: str,
        account_id: int,
        feedback: str,
        rating: Optional[int] = None,
    ) -> bool:
        """
        Met à jour le feedback uniquement si le draft appartient au compte.

        Returns:
            False si le draft n'existe pas ou appartient à un autre compte.
        """
        pass

    # =========================================================================
    # Méthodes non scopées — DÉPRÉCIÉES. Lèvent RuntimeError dans les adapters.
    # Conservées pour typage / tests legacy seulement.
    # =========================================================================

    @abstractmethod
    def add(self, record: DraftRecord) -> None:
        """
        Ajoute un brouillon à l'historique.

        ATTENTION : `record.account_id` DOIT être renseigné (> 0).
        L'adapter lève ValueError si account_id est manquant.
        """
        pass

    @abstractmethod
    def get_by_id(self, draft_id: str) -> Optional[DraftRecord]:
        """DÉPRÉCIÉ — fuit entre comptes. Utiliser get_by_id_for_account."""
        pass

    @abstractmethod
    def get_all(self, limit: int = 1000) -> List[DraftRecord]:
        """DÉPRÉCIÉ — fuit entre comptes. Utiliser get_all_for_account."""
        pass

    @abstractmethod
    def get_recent(self, days: int = 7) -> List[DraftRecord]:
        """DÉPRÉCIÉ — fuit entre comptes. Utiliser get_recent_for_account."""
        pass

    @abstractmethod
    def update_feedback(
        self,
        draft_id: str,
        feedback: str,
        rating: Optional[int] = None,
    ) -> bool:
        """
        Met a jour le feedback d'un brouillon.

        Args:
            draft_id: ID du brouillon.
            feedback: Texte du feedback.
            rating: Note de 1 a 5 (optionnel).

        Returns:
            True si la mise a jour a reussi, False si brouillon non trouve.
        """
        pass

    @abstractmethod
    def get_with_feedback(self, limit: int = 100) -> List[DraftRecord]:
        """
        Recupere les brouillons ayant un feedback.

        Args:
            limit: Nombre maximum de brouillons.

        Returns:
            Liste des brouillons avec feedback.
        """
        pass

    @abstractmethod
    def count(self) -> int:
        """
        Compte le nombre total de brouillons.

        Returns:
            Nombre de brouillons.
        """
        pass

    @abstractmethod
    def count_by_status(self) -> dict:
        """
        Compte les brouillons par statut.

        Returns:
            Dictionnaire {statut: count}.
        """
        pass

    @abstractmethod
    def count_by_category(self) -> dict:
        """
        Compte les brouillons par categorie.

        Returns:
            Dictionnaire {categorie: count}.
        """
        pass

    @abstractmethod
    def count_today(self) -> int:
        """
        Compte les brouillons crees aujourd'hui.

        Returns:
            Nombre de brouillons du jour.
        """
        pass
