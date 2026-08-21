# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Adapter generique pour la persistance des items traites.

Implemente ItemTrackerPort avec stockage JSON.
Ce pattern DRY permet de factoriser les trackers:
- ProcessedEmailsTracker
- ProcessedDraftsTracker
- Tout autre tracker similaire

Clean Architecture:
- Couche Infrastructure
- Implemente le port generique defini dans le domaine
- Stocke les IDs dans un fichier JSON
"""

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Set, Dict, Any

from app.domain.ports.item_tracker_port import ItemTrackerPort

logger = logging.getLogger(__name__)


class JsonItemTracker(ItemTrackerPort):
    """
    Adapter JSON generique pour le tracking d'items.

    Persiste les IDs d'items traites dans un fichier JSON.
    Thread-safe grace a la lecture/ecriture atomique.

    Usage:
        # Pour les emails
        email_tracker = JsonItemTracker(
            filepath=Path("data/processed_emails.json"),
            item_type="email"
        )

        # Pour les brouillons
        draft_tracker = JsonItemTracker(
            filepath=Path("data/processed_drafts.json"),
            item_type="draft"
        )
    """

    def __init__(self, filepath: Path, item_type: str = "item"):
        """
        Initialise le tracker.

        Args:
            filepath: Chemin du fichier JSON de persistance.
            item_type: Type d'item (pour les logs et metadata).
        """
        self._filepath = filepath
        self._item_type = item_type
        self._json_key = f"processed_{item_type}_ids"
        self._processed_ids: Set[str] = set()
        self._lock = threading.Lock()
        self._ensure_dir()
        self._load()

    @property
    def filepath(self) -> Path:
        """Retourne le chemin du fichier."""
        return self._filepath

    @property
    def item_type(self) -> str:
        """Retourne le type d'item."""
        return self._item_type

    def _ensure_dir(self) -> None:
        """Cree le repertoire parent si necessaire."""
        self._filepath.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> None:
        """Charge les IDs depuis le fichier."""
        if not self._filepath.exists():
            self._processed_ids = set()
            return

        try:
            data = json.loads(self._filepath.read_text(encoding="utf-8"))
            # Supporte l'ancien format et le nouveau
            # Gere les cas ou la valeur est None ou non-iterable
            ids_list = data.get(self._json_key) or data.get("processed_ids") or []
            self._processed_ids = set(ids_list) if ids_list else set()
            logger.debug(
                f"Loaded {len(self._processed_ids)} processed {self._item_type} IDs"
            )
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            logger.warning(f"Could not load processed {self._item_type}s: {e}")
            self._processed_ids = set()

    def _save(self) -> None:
        """Sauvegarde les IDs sur disque (caller must hold self._lock)."""
        data: Dict[str, Any] = {
            self._json_key: sorted(list(self._processed_ids)),
            "last_updated": datetime.now().isoformat(),
            "count": len(self._processed_ids),
            "item_type": self._item_type,
        }
        self._filepath.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

    def is_processed(self, item_id: str) -> bool:
        """
        Verifie si un item a deja ete traite.

        Args:
            item_id: Identifiant unique de l'item.

        Returns:
            True si l'item a deja ete traite.
        """
        with self._lock:
            return item_id in self._processed_ids

    def mark_processed(self, item_id: str) -> None:
        """
        Marque un item comme traite.

        Args:
            item_id: Identifiant unique de l'item.
        """
        with self._lock:
            if item_id not in self._processed_ids:
                self._processed_ids.add(item_id)
                self._save()

    def unmark_processed(self, item_id: str) -> None:
        """
        Retire un item des IDs traités (pour requeue).

        Args:
            item_id: Identifiant unique de l'item.
        """
        with self._lock:
            if item_id in self._processed_ids:
                self._processed_ids.discard(item_id)
                self._save()

    def count(self) -> int:
        """
        Retourne le nombre d'items traites.

        Returns:
            Nombre total d'items traites.
        """
        return len(self._processed_ids)

    def get_all_ids(self) -> Set[str]:
        """
        Retourne tous les IDs d'items traites.

        Returns:
            Ensemble des IDs traites.
        """
        return self._processed_ids.copy()

    def clear(self) -> None:
        """
        Efface tous les items traites.

        Utilise principalement pour les tests.
        """
        self._processed_ids = set()
        self._save()


class InMemoryItemTracker(ItemTrackerPort):
    """
    Adapter en memoire pour les tests.

    Ne persiste pas les donnees sur disque.
    """

    def __init__(self, item_type: str = "item"):
        """
        Initialise le tracker en memoire.

        Args:
            item_type: Type d'item (pour identification).
        """
        self._item_type = item_type
        self._processed_ids: Set[str] = set()

    @property
    def item_type(self) -> str:
        """Retourne le type d'item."""
        return self._item_type

    def is_processed(self, item_id: str) -> bool:
        """Verifie si un item a deja ete traite."""
        return item_id in self._processed_ids

    def mark_processed(self, item_id: str) -> None:
        """Marque un item comme traite."""
        self._processed_ids.add(item_id)

    def count(self) -> int:
        """Retourne le nombre d'items traites."""
        return len(self._processed_ids)

    def get_all_ids(self) -> Set[str]:
        """Retourne tous les IDs d'items traites."""
        return self._processed_ids.copy()

    def clear(self) -> None:
        """Efface tous les items traites."""
        self._processed_ids = set()


# Alias pour compatibilite avec le code existant
# Ces classes heritent directement de JsonItemTracker/InMemoryItemTracker
# avec une configuration specifique

def create_email_tracker(filepath: Path) -> JsonItemTracker:
    """Factory pour creer un tracker d'emails."""
    return JsonItemTracker(filepath=filepath, item_type="email")


def create_draft_tracker(filepath: Path) -> JsonItemTracker:
    """Factory pour creer un tracker de brouillons."""
    return JsonItemTracker(filepath=filepath, item_type="draft")
