# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Adapters de stockage pour le système d'apprentissage.

Ces adapters implémentent les ports définis dans le domaine.
Ils gèrent la persistance des patterns et ajustements en JSON.

Note: Ces adapters réutilisent la classe de base JsonFileStore
définie dans json_file_store.py pour éviter la duplication de code.
"""

from pathlib import Path
from typing import List, Optional, Dict, Any

from app.domain.entities.learning import (
    LearnedPattern,
    PromptAdjustment,
    PatternType,
)
from app.domain.ports.learning_port import (
    LearningPatternStorePort,
    AdjustmentStorePort,
    LearningFeedbackProviderPort,
)
from app.config import should_persist_email_content
from app.infrastructure.adapters.json_file_store import JsonFileStore


# =============================================================================
# PATTERN STORE
# =============================================================================


class JsonLearningPatternStore(JsonFileStore[LearnedPattern], LearningPatternStorePort):
    """
    Adapter de stockage JSON pour les patterns appris.

    Persiste les patterns dans un fichier JSON.
    Hérite de JsonFileStore pour réutiliser la logique de persistance.
    """

    def __init__(self, filepath: Path):
        """Initialise le store et crée le fichier s'il n'existe pas."""
        super().__init__(filepath)
        self._ensure_file()
        self._purge_examples_if_metadata_only()

    def _ensure_file(self) -> None:
        """S'assure que le fichier existe avec un tableau JSON vide."""
        if not self._filepath.exists():
            self._filepath.write_text("[]", encoding="utf-8")

    def _entity_to_dict(self, entity: LearnedPattern) -> Dict[str, Any]:
        """Convertit un LearnedPattern en dictionnaire."""
        data = entity.to_dict()
        if not should_persist_email_content():
            data["examples"] = []
        return data

    def _dict_to_entity(self, data: Dict[str, Any]) -> LearnedPattern:
        """Convertit un dictionnaire en LearnedPattern (gère la rétrocompatibilité)."""
        from datetime import datetime
        # Gestion de la rétrocompatibilité: created_at -> timestamp
        if "timestamp" not in data:
            if "created_at" in data:
                data = {**data, "timestamp": data["created_at"]}
            else:
                # Fallback pour données legacy sans timestamp
                data = {**data, "timestamp": datetime.now().isoformat()}
        if not should_persist_email_content():
            data = {**data, "examples": []}
        return LearnedPattern.from_dict(data)

    def _purge_examples_if_metadata_only(self) -> None:
        """Réécrit les fichiers legacy pour supprimer les exemples libres."""
        if should_persist_email_content():
            return

        records = self._load_raw()
        changed = False
        for record in records:
            if record.get("examples"):
                record["examples"] = []
                changed = True
        if changed:
            self._save_raw(records)

    def save(self, pattern: LearnedPattern) -> str:
        """Sauvegarde un pattern."""
        self._append(pattern)
        return pattern.id

    def save_many(self, patterns: List[LearnedPattern]) -> List[str]:
        """Sauvegarde plusieurs patterns."""
        records = self._load_raw()
        ids = []
        for pattern in patterns:
            records.append(self._entity_to_dict(pattern))
            ids.append(pattern.id)
        self._save_raw(records)
        return ids

    def get_by_id(self, pattern_id: str) -> Optional[LearnedPattern]:
        """Récupère un pattern par son ID."""
        return self._find_by_key("id", pattern_id)

    def list_all(self, limit: int = 100) -> List[LearnedPattern]:
        """Liste tous les patterns."""
        return self._load_all()[:limit]

    def get_by_type(self, pattern_type: PatternType) -> List[LearnedPattern]:
        """Récupère les patterns par type."""
        return [
            p for p in self._load_all()
            if p.pattern_type == pattern_type
        ]

    def update(self, pattern: LearnedPattern) -> bool:
        """Met à jour un pattern existant."""
        return self._update_by_key("id", pattern.id, self._entity_to_dict(pattern))

    def count(self) -> int:
        """Compte le nombre total de patterns."""
        return self._count()

    def count_by_type(self) -> dict:
        """Compte les patterns par type (good, bad)."""
        counts = {"good": 0, "bad": 0}
        # Utiliser _load_raw() pour éviter les erreurs de conversion
        for data in self._load_raw():
            ptype = data.get("pattern_type", "")
            if ptype in counts:
                counts[ptype] += 1
        return counts


# =============================================================================
# ADJUSTMENT STORE
# =============================================================================


class JsonAdjustmentStore(JsonFileStore[PromptAdjustment], AdjustmentStorePort):
    """
    Adapter de stockage JSON pour les ajustements de prompt.

    Persiste les ajustements dans un fichier JSON.
    Hérite de JsonFileStore pour réutiliser la logique de persistance.
    """

    def __init__(self, filepath: Path):
        """Initialise le store et crée le fichier s'il n'existe pas."""
        super().__init__(filepath)
        self._ensure_file()

    def _ensure_file(self) -> None:
        """S'assure que le fichier existe avec un tableau JSON vide."""
        if not self._filepath.exists():
            self._filepath.write_text("[]", encoding="utf-8")

    def _entity_to_dict(self, entity: PromptAdjustment) -> Dict[str, Any]:
        """Convertit un PromptAdjustment en dictionnaire."""
        return entity.to_dict()

    def _dict_to_entity(self, data: Dict[str, Any]) -> PromptAdjustment:
        """Convertit un dictionnaire en PromptAdjustment (gère la rétrocompatibilité)."""
        # Gestion de la rétrocompatibilité: created_at -> timestamp
        if "timestamp" not in data and "created_at" in data:
            data = {**data, "timestamp": data["created_at"]}
        return PromptAdjustment.from_dict(data)

    def save(self, adjustment: PromptAdjustment) -> str:
        """Sauvegarde un ajustement."""
        self._append(adjustment)
        return adjustment.id

    def get_by_id(self, adjustment_id: str) -> Optional[PromptAdjustment]:
        """Récupère un ajustement par son ID."""
        return self._find_by_key("id", adjustment_id)

    def get_active(self) -> List[PromptAdjustment]:
        """Récupère tous les ajustements actifs."""
        return [a for a in self._load_all() if a.active]

    def list_all(self) -> List[PromptAdjustment]:
        """Liste tous les ajustements."""
        return self._load_all()

    def update(self, adjustment: PromptAdjustment) -> bool:
        """Met à jour un ajustement."""
        return self._update_by_key("id", adjustment.id, self._entity_to_dict(adjustment))

    def count_active(self) -> int:
        """Compte le nombre d'ajustements actifs."""
        return len(self.get_active())


# =============================================================================
# HISTORY FEEDBACK ADAPTER
# =============================================================================


class HistoryFeedbackAdapter(LearningFeedbackProviderPort):
    """
    Adapter qui fournit les feedbacks depuis l'historique des drafts.

    Cet adapter fait le pont entre le système d'apprentissage
    et l'historique existant (app.history).
    """

    def __init__(self, history_provider=None):
        """
        Initialise l'adapter.

        Args:
            history_provider: Le provider d'historique (optionnel, lazy loading).
        """
        self._history = history_provider

    def _get_history(self):
        """Récupère le provider d'historique (lazy loading)."""
        if self._history is None:
            try:
                from app.history import draft_history
                self._history = draft_history
            except ImportError:
                # Fallback: retourne un mock
                class MockHistory:
                    def get_all(self, limit=1000):
                        return []
                self._history = MockHistory()
        return self._history

    def get_all(self, limit: int = 1000) -> List:
        """Récupère tous les feedbacks."""
        history = self._get_history()
        records = history.get_all(limit=limit)
        # Filtrer ceux avec un feedback
        return [r for r in records if getattr(r, "feedback_rating", None) is not None]

    def get_with_comments(self, limit: int = 100) -> List:
        """Récupère les feedbacks avec commentaires."""
        history = self._get_history()
        records = history.get_all(limit=limit)
        return [
            r for r in records
            if getattr(r, "feedback_rating", None) is not None
            and getattr(r, "feedback", None)
        ]

    def count(self) -> int:
        """Compte le nombre total de feedbacks."""
        return len(self.get_all())

    def get_satisfaction_rate(self) -> float:
        """Calcule le taux de satisfaction global."""
        feedbacks = self.get_all()
        if not feedbacks:
            return 100.0  # Par défaut, on considère 100% si pas de données

        good = len([f for f in feedbacks if getattr(f, "feedback_rating", 0) >= 4])
        return (good / len(feedbacks)) * 100
