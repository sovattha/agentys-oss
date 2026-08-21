# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Implémentation du stockage des device tokens.

Ce module fournit l'adapter de persistance pour les device tokens
utilisés pour les notifications push mobiles.
"""

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from app.domain.entities import DeviceToken, DevicePlatform
from app.domain.ports import DeviceStorePort

logger = logging.getLogger(__name__)


class JsonFileDeviceStore(DeviceStorePort):
    """
    Stockage persistant des device tokens dans un fichier JSON.

    Thread-safe avec verrouillage pour les accès concurrents.
    """

    def __init__(self, filepath: Path):
        """
        Initialise le store.

        Args:
            filepath: Chemin vers le fichier JSON de persistance.
        """
        self.filepath = filepath
        self._devices: Dict[str, DeviceToken] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        """Charge les devices depuis le fichier."""
        if self.filepath.exists():
            try:
                data = json.loads(self.filepath.read_text(encoding="utf-8"))
                for device_data in data.get("devices", []):
                    device = DeviceToken.from_dict(device_data)
                    self._devices[device.token] = device
                logger.info(f"Loaded {len(self._devices)} device tokens")
            except Exception as e:
                logger.error(f"Error loading devices: {e}")

    def _save(self) -> None:
        """Sauvegarde les devices."""
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "devices": [d.to_dict() for d in self._devices.values()],
            "updated_at": datetime.now().isoformat(),
        }
        self.filepath.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def register(
        self,
        token: str,
        platform: str,
        user_id: Optional[str] = None,
        device_name: Optional[str] = None,
        app_version: Optional[str] = None,
    ) -> DeviceToken:
        """Enregistre un nouveau device token."""
        with self._lock:
            device = DeviceToken(
                token=token,
                platform=DevicePlatform(platform),
                user_id=user_id,
                device_name=device_name,
                app_version=app_version,
            )
            self._devices[token] = device
            self._save()
            logger.info(f"Device registered: {token[:20]}... ({platform})")
            return device

    def unregister(self, token: str) -> bool:
        """Supprime un device token."""
        with self._lock:
            if token in self._devices:
                del self._devices[token]
                self._save()
                logger.info(f"Device unregistered: {token[:20]}...")
                return True
            return False

    def get(self, token: str) -> Optional[DeviceToken]:
        """Récupère un device par son token."""
        return self._devices.get(token)

    def get_all(self, user_id: Optional[str] = None) -> List[DeviceToken]:
        """Liste tous les devices actifs."""
        devices = [d for d in self._devices.values() if d.is_active]
        if user_id:
            devices = [d for d in devices if d.user_id == user_id]
        return devices

    def get_tokens(self, user_id: Optional[str] = None) -> List[str]:
        """Récupère uniquement les tokens (strings)."""
        return [d.token for d in self.get_all(user_id)]

    def update_last_used(self, token: str) -> None:
        """Met à jour la date de dernière utilisation."""
        with self._lock:
            if token in self._devices:
                self._devices[token].last_used_at = datetime.now()
                self._save()

    def deactivate(self, token: str) -> bool:
        """Désactive un device (token invalide)."""
        with self._lock:
            if token in self._devices:
                self._devices[token].is_active = False
                self._save()
                logger.info(f"Device deactivated: {token[:20]}...")
                return True
            return False


# Singleton et factory
_device_store: Optional[JsonFileDeviceStore] = None


def get_device_store(filepath: Optional[Path] = None) -> JsonFileDeviceStore:
    """
    Retourne le singleton du device store.

    Args:
        filepath: Chemin optionnel vers le fichier de persistance.

    Returns:
        Instance du JsonFileDeviceStore.
    """
    global _device_store
    if _device_store is None:
        if filepath is None:
            from app.config import PROJECT_ROOT
            filepath = PROJECT_ROOT / "data" / "push_devices.json"
        _device_store = JsonFileDeviceStore(filepath)
    return _device_store


def reset_device_store() -> None:
    """Réinitialise le singleton (utile pour les tests)."""
    global _device_store
    _device_store = None
