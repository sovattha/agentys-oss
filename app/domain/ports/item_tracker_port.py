# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Port generique pour le suivi d'items traites.

Ce port definit le contrat pour la persistance des IDs
d'items deja traites par le daemon (emails, brouillons, etc.).

Clean Architecture:
- Couche Domain (Ports)
- Definit le contrat sans implementation
- Respect de DIP (Dependency Inversion Principle)
"""

from abc import ABC, abstractmethod
from typing import Set


class ItemTrackerPort(ABC):
    """
    Port generique pour le suivi d'items traites.

    Ce port est une abstraction qui peut etre utilisee pour:
    - Tracker les emails traites (ProcessedEmailsTrackerPort)
    - Tracker les brouillons traites (ProcessedDraftsTrackerPort)
    - Tout autre type d'item necessitant un suivi

    Responsabilites:
    - Persister les IDs d'items traites
    - Verifier si un item a deja ete traite
    - Eviter les traitements en doublon
    """

    @abstractmethod
    def is_processed(self, item_id: str) -> bool:
        """
        Verifie si un item a deja ete traite.

        Args:
            item_id: Identifiant unique de l'item.

        Returns:
            True si l'item a deja ete traite.
        """
        pass

    @abstractmethod
    def mark_processed(self, item_id: str) -> None:
        """
        Marque un item comme traite.

        Args:
            item_id: Identifiant unique de l'item.
        """
        pass

    @abstractmethod
    def count(self) -> int:
        """
        Retourne le nombre d'items traites.

        Returns:
            Nombre total d'items traites.
        """
        pass

    @abstractmethod
    def get_all_ids(self) -> Set[str]:
        """
        Retourne tous les IDs d'items traites.

        Returns:
            Ensemble des IDs traites.
        """
        pass

    @abstractmethod
    def clear(self) -> None:
        """
        Efface tous les items traites.

        Utilise principalement pour les tests.
        """
        pass


# Alias pour compatibilite avec le code existant
ProcessedEmailsTrackerPort = ItemTrackerPort
ProcessedDraftsTrackerPort = ItemTrackerPort
