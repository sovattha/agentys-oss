# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Ports (interfaces) pour le système d'apprentissage automatique.

Ces ports définissent les contrats que les adapters doivent implémenter.
Ils respectent la Dependency Rule de la Clean Architecture.
"""

from abc import ABC, abstractmethod
from typing import List, Optional

from app.domain.entities.learning import (
    LearnedPattern,
    PromptAdjustment,
    LearningInsights,
    ReviewRequirement,
    LearningStats,
    PatternType,
)


class LearningPatternStorePort(ABC):
    """
    Port pour le stockage des patterns appris.

    Responsabilités:
    - Persister les patterns
    - Récupérer les patterns par type
    - Compter les patterns
    """

    @abstractmethod
    def save(self, pattern: LearnedPattern) -> str:
        """
        Sauvegarde un pattern.

        Args:
            pattern: Le pattern à sauvegarder.

        Returns:
            L'ID du pattern sauvegardé.
        """
        pass

    @abstractmethod
    def save_many(self, patterns: List[LearnedPattern]) -> List[str]:
        """
        Sauvegarde plusieurs patterns.

        Args:
            patterns: Les patterns à sauvegarder.

        Returns:
            Les IDs des patterns sauvegardés.
        """
        pass

    @abstractmethod
    def get_by_id(self, pattern_id: str) -> Optional[LearnedPattern]:
        """
        Récupère un pattern par son ID.

        Args:
            pattern_id: L'ID du pattern.

        Returns:
            Le pattern ou None si non trouvé.
        """
        pass

    @abstractmethod
    def list_all(self, limit: int = 100) -> List[LearnedPattern]:
        """
        Liste tous les patterns.

        Args:
            limit: Nombre maximum de patterns à retourner.

        Returns:
            Liste des patterns.
        """
        pass

    @abstractmethod
    def get_by_type(self, pattern_type: PatternType) -> List[LearnedPattern]:
        """
        Récupère les patterns par type.

        Args:
            pattern_type: Type de pattern (GOOD ou BAD).

        Returns:
            Liste des patterns de ce type.
        """
        pass

    @abstractmethod
    def update(self, pattern: LearnedPattern) -> bool:
        """
        Met à jour un pattern existant.

        Args:
            pattern: Le pattern mis à jour.

        Returns:
            True si la mise à jour a réussi.
        """
        pass

    @abstractmethod
    def count(self) -> int:
        """
        Compte le nombre total de patterns.

        Returns:
            Nombre de patterns.
        """
        pass

    @abstractmethod
    def count_by_type(self) -> dict:
        """
        Compte les patterns par type.

        Returns:
            Dictionnaire {type: count}.
        """
        pass


class AdjustmentStorePort(ABC):
    """
    Port pour le stockage des ajustements de prompt.

    Responsabilités:
    - Persister les ajustements
    - Récupérer les ajustements actifs
    - Activer/désactiver des ajustements
    """

    @abstractmethod
    def save(self, adjustment: PromptAdjustment) -> str:
        """
        Sauvegarde un ajustement.

        Args:
            adjustment: L'ajustement à sauvegarder.

        Returns:
            L'ID de l'ajustement.
        """
        pass

    @abstractmethod
    def get_by_id(self, adjustment_id: str) -> Optional[PromptAdjustment]:
        """
        Récupère un ajustement par son ID.

        Args:
            adjustment_id: L'ID de l'ajustement.

        Returns:
            L'ajustement ou None si non trouvé.
        """
        pass

    @abstractmethod
    def get_active(self) -> List[PromptAdjustment]:
        """
        Récupère tous les ajustements actifs.

        Returns:
            Liste des ajustements actifs.
        """
        pass

    @abstractmethod
    def list_all(self) -> List[PromptAdjustment]:
        """
        Liste tous les ajustements.

        Returns:
            Liste de tous les ajustements.
        """
        pass

    @abstractmethod
    def update(self, adjustment: PromptAdjustment) -> bool:
        """
        Met à jour un ajustement.

        Args:
            adjustment: L'ajustement mis à jour.

        Returns:
            True si la mise à jour a réussi.
        """
        pass

    @abstractmethod
    def count_active(self) -> int:
        """
        Compte le nombre d'ajustements actifs.

        Returns:
            Nombre d'ajustements actifs.
        """
        pass


class LearningFeedbackProviderPort(ABC):
    """
    Port pour accéder aux feedbacks utilisateur.

    Ce port abstrait l'accès aux feedbacks stockés dans l'historique
    ou dans le système de fine-tuning.
    """

    @abstractmethod
    def get_all(self, limit: int = 1000) -> List:
        """
        Récupère tous les feedbacks.

        Args:
            limit: Nombre maximum de feedbacks.

        Returns:
            Liste des feedbacks.
        """
        pass

    @abstractmethod
    def get_with_comments(self, limit: int = 100) -> List:
        """
        Récupère les feedbacks avec commentaires.

        Args:
            limit: Nombre maximum de feedbacks.

        Returns:
            Liste des feedbacks ayant un commentaire.
        """
        pass

    @abstractmethod
    def count(self) -> int:
        """
        Compte le nombre total de feedbacks.

        Returns:
            Nombre de feedbacks.
        """
        pass

    @abstractmethod
    def get_satisfaction_rate(self) -> float:
        """
        Calcule le taux de satisfaction global.

        Returns:
            Taux de satisfaction (0-100).
        """
        pass


class LearningServicePort(ABC):
    """
    Port pour le service d'apprentissage.

    Ce port définit les opérations de haut niveau du système
    d'apprentissage, utilisées par le daemon.
    """

    @abstractmethod
    def analyze_feedback(self) -> LearningInsights:
        """
        Analyse tous les feedbacks disponibles.

        Returns:
            Insights issus de l'analyse.
        """
        pass

    @abstractmethod
    def extract_patterns(self) -> List[LearnedPattern]:
        """
        Extrait des patterns des feedbacks.

        Returns:
            Liste des nouveaux patterns extraits.
        """
        pass

    @abstractmethod
    def generate_adjustment(self) -> Optional[PromptAdjustment]:
        """
        Génère un ajustement de prompt basé sur les patterns.

        Returns:
            L'ajustement généré ou None.
        """
        pass

    @abstractmethod
    def should_require_review(
        self,
        email_content: str,
        priority_score: int,
    ) -> ReviewRequirement:
        """
        Détermine si un email nécessite une review humaine.

        Args:
            email_content: Contenu de l'email.
            priority_score: Score de priorité (0-100).

        Returns:
            Exigence de review avec raisons.
        """
        pass

    @abstractmethod
    def get_active_adjustments(self) -> List[str]:
        """
        Récupère les textes des ajustements actifs.

        Returns:
            Liste des textes d'ajustement.
        """
        pass

    @abstractmethod
    def get_stats(self) -> LearningStats:
        """
        Récupère les statistiques d'apprentissage.

        Returns:
            Statistiques complètes.
        """
        pass

    @abstractmethod
    def enhance_prompt(self, base_prompt: str) -> str:
        """
        Enrichit un prompt avec les ajustements appris.

        Args:
            base_prompt: Le prompt de base.

        Returns:
            Le prompt enrichi.
        """
        pass
