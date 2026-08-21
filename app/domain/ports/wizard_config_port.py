# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Port WizardConfigPort - Interface pour la persistance de la configuration wizard.

Ce port définit le contrat que tout adapter de stockage de configuration
doit implémenter (fichier JSON, base de données SQLite, etc.).
"""

from abc import ABC, abstractmethod
from typing import Optional

from app.domain.entities import WizardConfig


class WizardConfigPort(ABC):
    """
    Interface abstraite pour le stockage de la configuration wizard.

    Tout adapter de persistance doit implémenter cette interface.
    """

    @abstractmethod
    def save(self, config: WizardConfig) -> None:
        """
        Sauvegarde la configuration wizard.

        Args:
            config: Configuration à sauvegarder.

        Raises:
            IOError: Si la sauvegarde échoue.
        """
        pass

    @abstractmethod
    def load(self) -> Optional[WizardConfig]:
        """
        Charge la configuration wizard.

        Returns:
            WizardConfig ou None si aucune configuration n'existe.

        Raises:
            IOError: Si le chargement échoue.
            ValueError: Si les données sont corrompues.
        """
        pass

    @abstractmethod
    def exists(self) -> bool:
        """
        Vérifie si une configuration existe.

        Returns:
            True si une configuration existe.
        """
        pass

    @abstractmethod
    def delete(self) -> bool:
        """
        Supprime la configuration.

        Returns:
            True si supprimée, False si non trouvée.
        """
        pass

    @abstractmethod
    def export_to_file(self, path: str) -> None:
        """
        Exporte la configuration vers un fichier.

        Args:
            path: Chemin du fichier de destination.

        Raises:
            IOError: Si l'export échoue.
            ValueError: Si aucune configuration n'existe.
        """
        pass

    @abstractmethod
    def import_from_file(self, path: str) -> WizardConfig:
        """
        Importe une configuration depuis un fichier.

        Args:
            path: Chemin du fichier source.

        Returns:
            Configuration importée.

        Raises:
            IOError: Si le fichier n'existe pas.
            ValueError: Si le format est invalide.
        """
        pass
