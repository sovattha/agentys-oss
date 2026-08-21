# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Adapter pour la persistance des emails traites.

Implemente ProcessedEmailsTrackerPort avec stockage JSON.

Clean Architecture:
- Couche Infrastructure
- Implemente le port defini dans le domaine
- Herite des trackers generiques pour eviter la duplication

Refactoring: Duplicated Code (Clone Type 2)
- Avant: 157 lignes de code duplique avec item_tracker_adapter.py
- Apres: ~50 lignes utilisant l'heritage
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from app.domain.ports import ProcessedEmailsTrackerPort
from app.infrastructure.adapters.item_tracker_adapter import (
    JsonItemTracker,
    InMemoryItemTracker,
)


class JsonProcessedEmailsTracker(JsonItemTracker, ProcessedEmailsTrackerPort):
    """
    Adapter JSON pour le tracker d'emails traites.

    Herite de JsonItemTracker pour la logique de persistance.
    Implemente ProcessedEmailsTrackerPort pour le typage semantique.
    Surcharge _save pour maintenir la retrocompatibilite avec processed_ids.
    """

    def __init__(self, filepath: Path):
        """
        Initialise le tracker d'emails.

        Args:
            filepath: Chemin du fichier JSON de persistance.
        """
        super().__init__(filepath=filepath, item_type="email")

    def _save(self) -> None:
        """Sauvegarde avec cle legacy processed_ids pour retrocompatibilite."""
        data: Dict[str, Any] = {
            "processed_ids": sorted(list(self._processed_ids)),
            "last_updated": datetime.now().isoformat(),
            "count": len(self._processed_ids),
        }
        self._filepath.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )


class InMemoryProcessedEmailsTracker(InMemoryItemTracker, ProcessedEmailsTrackerPort):
    """
    Adapter en memoire pour les tests.

    Herite de InMemoryItemTracker pour la logique.
    Implemente ProcessedEmailsTrackerPort pour le typage semantique.
    """

    def __init__(self):
        """Initialise le tracker en memoire."""
        super().__init__(item_type="email")
