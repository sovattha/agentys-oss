# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Ports pour le système d'apprentissage du style d'écriture.

Ces ports définissent les contrats que les adapters doivent implémenter
pour l'analyse et le stockage des profils de style d'écriture.
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Sequence

from app.db.models.email import Email
from app.domain.entities.writing_style import WritingStyleProfile


class WritingStyleAnalyzerPort(ABC):
    """
    Port pour l'analyse du style d'écriture.

    Cette interface définit le contrat pour analyser les emails envoyés
    par l'utilisateur et en extraire un profil de style.
    """

    @abstractmethod
    async def analyze(
        self,
        account_id: int,
        emails: Sequence[Email],
        timeout_seconds: int = 30,
    ) -> WritingStyleProfile:
        """
        Analyse une collection d'emails pour extraire le style d'écriture.

        Args:
            account_id: ID du compte email de l'utilisateur.
            emails: Séquence d'emails envoyés à analyser.
            timeout_seconds: Timeout en secondes (défaut: 30).

        Returns:
            WritingStyleProfile avec les caractéristiques extraites.

        Raises:
            ValueError: Si aucun email n'est fourni.
            TimeoutError: Si l'analyse dépasse le timeout.
        """
        pass

    @abstractmethod
    async def analyze_single(
        self,
        email: Email,
    ) -> dict:
        """
        Analyse un seul email pour extraction incrémentale.

        Utilisé pour la mise à jour du profil après envoi d'un email.

        Args:
            email: L'email envoyé à analyser.

        Returns:
            Dictionnaire avec les caractéristiques extraites:
            - common_words: List[str]
            - greetings: List[str]
            - closings: List[str]
            - sentence_length: float
            - email_length: int
        """
        pass

    def is_available(self) -> bool:
        """Vérifie si l'analyzer est disponible et configuré."""
        return True


class WritingStyleStorePort(ABC):
    """
    Port pour le stockage des profils de style.

    Cette interface définit le contrat pour persister les profils
    de style d'écriture localement sur la machine de l'utilisateur.
    """

    @abstractmethod
    def save(self, profile: WritingStyleProfile) -> bool:
        """
        Sauvegarde un profil de style.

        Args:
            profile: Le profil à sauvegarder.

        Returns:
            True si la sauvegarde a réussi.
        """
        pass

    @abstractmethod
    def load(self, account_id: int) -> Optional[WritingStyleProfile]:
        """
        Charge un profil de style par ID de compte.

        Args:
            account_id: ID du compte email.

        Returns:
            Le profil ou None si non trouvé.
        """
        pass

    @abstractmethod
    def exists(self, account_id: int) -> bool:
        """
        Vérifie si un profil existe pour un compte.

        Args:
            account_id: ID du compte email.

        Returns:
            True si un profil existe.
        """
        pass

    @abstractmethod
    def delete(self, account_id: int) -> bool:
        """
        Supprime un profil de style.

        Args:
            account_id: ID du compte email.

        Returns:
            True si la suppression a réussi.
        """
        pass

    @abstractmethod
    def list_all(self) -> List[int]:
        """
        Liste tous les account_id ayant un profil.

        Returns:
            Liste des IDs de compte avec un profil.
        """
        pass
