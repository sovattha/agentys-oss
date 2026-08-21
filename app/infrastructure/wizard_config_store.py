# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Implémentation du stockage de la configuration wizard.

Ce module fournit l'adapter de persistance pour la configuration
d'onboarding entreprise (wizard).
"""

import json
import logging
import threading
from pathlib import Path
from typing import Optional

from app.domain.entities import WizardConfig
from app.domain.ports import WizardConfigPort

logger = logging.getLogger(__name__)


class JsonFileWizardConfigStore(WizardConfigPort):
    """
    Stockage persistant de la configuration wizard dans un fichier JSON.

    Thread-safe avec verrouillage pour les accès concurrents.
    """

    def __init__(self, filepath: Path):
        """
        Initialise le store.

        Args:
            filepath: Chemin vers le fichier JSON de persistance.
        """
        self.filepath = filepath
        self._config: Optional[WizardConfig] = None
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        """Charge la configuration depuis le fichier."""
        if self.filepath.exists():
            try:
                data = json.loads(self.filepath.read_text(encoding='utf-8'))
                self._config = WizardConfig.from_dict(data)
                logger.info(f"Loaded wizard config for: {self._config.company_name}")
            except Exception as e:
                logger.error(f"Error loading wizard config: {e}")
                self._config = None

    def _save(self) -> None:
        """Sauvegarde la configuration."""
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        if self._config:
            data = self._config.to_dict()
            self.filepath.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding='utf-8'
            )
            logger.info(f"Saved wizard config for: {self._config.company_name}")

    def save(self, config: WizardConfig) -> None:
        """
        Sauvegarde la configuration wizard.

        Args:
            config: Configuration à sauvegarder.
        """
        with self._lock:
            # Incrémenter la version si mise à jour
            if self._config and self._config.config_id == config.config_id:
                config.version = self._config.version + 1
            self._config = config
            self._save()

    def load(self) -> Optional[WizardConfig]:
        """
        Charge la configuration wizard.

        Returns:
            WizardConfig ou None si aucune configuration n'existe.
        """
        with self._lock:
            return self._config

    def exists(self) -> bool:
        """
        Vérifie si une configuration existe.

        Returns:
            True si une configuration existe.
        """
        return self._config is not None

    def delete(self) -> bool:
        """
        Supprime la configuration.

        Returns:
            True si supprimée, False si non trouvée.
        """
        with self._lock:
            if self._config:
                self._config = None
                if self.filepath.exists():
                    self.filepath.unlink()
                logger.info("Wizard config deleted")
                return True
            return False

    def export_to_file(self, path: str) -> None:
        """
        Exporte la configuration vers un fichier.

        Args:
            path: Chemin du fichier de destination.

        Raises:
            ValueError: Si aucune configuration n'existe.
        """
        with self._lock:
            if not self._config:
                raise ValueError("Aucune configuration à exporter")

            export_path = Path(path)
            export_path.parent.mkdir(parents=True, exist_ok=True)
            data = self._config.to_dict()
            export_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding='utf-8'
            )
            logger.info(f"Exported wizard config to: {path}")

    def import_from_file(self, path: str) -> WizardConfig:
        """
        Importe une configuration depuis un fichier.

        Args:
            path: Chemin du fichier source.

        Returns:
            Configuration importée.

        Raises:
            FileNotFoundError: Si le fichier n'existe pas.
            ValueError: Si le format est invalide.
        """
        import_path = Path(path)
        if not import_path.exists():
            raise FileNotFoundError(f"Fichier non trouvé: {path}")

        try:
            data = json.loads(import_path.read_text(encoding='utf-8'))
            config = WizardConfig.from_dict(data)

            with self._lock:
                self._config = config
                self._save()

            logger.info(f"Imported wizard config from: {path}")
            return config
        except json.JSONDecodeError as e:
            raise ValueError(f"Format JSON invalide: {e}")
        except KeyError as e:
            raise ValueError(f"Champ manquant: {e}")


# Singleton et factory
_wizard_config_store: Optional[JsonFileWizardConfigStore] = None


def get_wizard_config_store(filepath: Optional[Path] = None) -> JsonFileWizardConfigStore:
    """
    Retourne le singleton du wizard config store.

    Args:
        filepath: Chemin optionnel vers le fichier de persistance.

    Returns:
        Instance du JsonFileWizardConfigStore.
    """
    global _wizard_config_store
    if _wizard_config_store is None:
        if filepath is None:
            from app.config import PROJECT_ROOT
            filepath = PROJECT_ROOT / "data" / "wizard_config.json"
        _wizard_config_store = JsonFileWizardConfigStore(filepath)
    return _wizard_config_store


def reset_wizard_config_store() -> None:
    """Réinitialise le singleton (utile pour les tests)."""
    global _wizard_config_store
    _wizard_config_store = None
