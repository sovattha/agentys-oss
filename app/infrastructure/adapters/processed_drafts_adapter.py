# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Adapter pour la persistance des brouillons traites.

Ce module fournit des alias de compatibilite vers les adapters generiques.
L'implementation reelle est dans item_tracker_adapter.py.

Clean Architecture:
- Couche Infrastructure
- Herite des adapters generiques
- Maintient la compatibilite avec le code existant
"""

from pathlib import Path

from app.infrastructure.adapters.item_tracker_adapter import (
    JsonItemTracker,
    InMemoryItemTracker,
)


class JsonProcessedDraftsTracker(JsonItemTracker):
    """
    Adapter JSON pour le tracker de brouillons traites.

    Herite de JsonItemTracker avec item_type="draft".
    Maintenu pour compatibilite avec le code existant.
    """

    def __init__(self, filepath: Path):
        """
        Initialise le tracker de brouillons.

        Args:
            filepath: Chemin du fichier JSON de persistance.
        """
        super().__init__(filepath=filepath, item_type="draft")


class InMemoryProcessedDraftsTracker(InMemoryItemTracker):
    """
    Adapter en memoire pour les tests.

    Herite de InMemoryItemTracker avec item_type="draft".
    """

    def __init__(self):
        """Initialise le tracker en memoire."""
        super().__init__(item_type="draft")
