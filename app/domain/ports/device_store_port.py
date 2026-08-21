# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Port DeviceStore - Interface pour la persistance des device tokens.

Ce port définit le contrat que tout adapter de stockage de device tokens
doit implémenter (fichier JSON, base de données, etc.).
"""

from abc import ABC, abstractmethod
from typing import List, Optional

from app.domain.entities import DeviceToken


class DeviceStorePort(ABC):
    """
    Interface abstraite pour le stockage des device tokens.

    Tout adapter de persistance doit implémenter cette interface.
    """

    @abstractmethod
    def register(
        self,
        token: str,
        platform: str,
        user_id: Optional[str] = None,
        device_name: Optional[str] = None,
        app_version: Optional[str] = None,
    ) -> DeviceToken:
        """
        Enregistre un nouveau device token.

        Args:
            token: Token push du device.
            platform: Plateforme (ios, android, web).
            user_id: ID utilisateur associé.
            device_name: Nom du device.
            app_version: Version de l'app.

        Returns:
            DeviceToken enregistré.
        """
        pass

    @abstractmethod
    def unregister(self, token: str) -> bool:
        """
        Supprime un device token.

        Args:
            token: Token à supprimer.

        Returns:
            True si supprimé, False si non trouvé.
        """
        pass

    @abstractmethod
    def get(self, token: str) -> Optional[DeviceToken]:
        """
        Récupère un device par son token.

        Args:
            token: Token du device.

        Returns:
            DeviceToken ou None si non trouvé.
        """
        pass

    @abstractmethod
    def get_all(self, user_id: Optional[str] = None) -> List[DeviceToken]:
        """
        Liste tous les devices actifs.

        Args:
            user_id: Filtrer par utilisateur (optionnel).

        Returns:
            Liste des DeviceTokens.
        """
        pass

    @abstractmethod
    def get_tokens(self, user_id: Optional[str] = None) -> List[str]:
        """
        Récupère uniquement les tokens (strings).

        Args:
            user_id: Filtrer par utilisateur (optionnel).

        Returns:
            Liste des tokens.
        """
        pass

    @abstractmethod
    def update_last_used(self, token: str) -> None:
        """Met à jour la date de dernière utilisation."""
        pass

    @abstractmethod
    def deactivate(self, token: str) -> bool:
        """
        Désactive un device (token invalide).

        Args:
            token: Token à désactiver.

        Returns:
            True si désactivé.
        """
        pass
