# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Port pour le systeme d'analytics.

Ce port definit le contrat pour les metriques de qualite
et la comparaison IA vs modifications humaines.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional

from app.domain.entities.analytics import (
    QualityScore,
    QualityMetrics,
    AIVsHumanComparison,
    HumanEdit,
    PerformanceMetrics,
)


class AnalyticsPort(ABC):
    """
    Port pour les analytics et metriques de qualite.

    Responsabilites:
    - Calculer les metriques de qualite
    - Comparer les reponses IA vs modifications humaines
    - Enregistrer les scores de qualite
    - Tracker les modifications humaines
    """

    # =========================================================================
    # Metriques de qualite
    # =========================================================================

    @abstractmethod
    def get_quality_metrics(self) -> Dict[str, Any]:
        """
        Recupere les metriques de qualite agregees.

        Returns:
            Dictionnaire avec:
            - avg_score: Score moyen
            - total_drafts: Nombre total
            - by_level: Repartition par niveau
        """
        pass

    @abstractmethod
    def get_detailed_quality_metrics(self) -> QualityMetrics:
        """
        Recupere les metriques de qualite detaillees.

        Returns:
            Objet QualityMetrics complet.
        """
        pass

    @abstractmethod
    def record_quality_score(self, score: QualityScore) -> None:
        """
        Enregistre un score de qualite.

        Args:
            score: Score de qualite a enregistrer.
        """
        pass

    @abstractmethod
    def get_quality_score(self, draft_id: str) -> Optional[QualityScore]:
        """
        Recupere le score de qualite d'un brouillon.

        Args:
            draft_id: ID du brouillon.

        Returns:
            Le score ou None si non trouve.
        """
        pass

    # =========================================================================
    # Comparaison IA vs Humain
    # =========================================================================

    @abstractmethod
    def get_ai_vs_human_comparison(self) -> Dict[str, Any]:
        """
        Compare les reponses IA avec les modifications humaines.

        Returns:
            Dictionnaire avec:
            - edit_rate: Taux de modification
            - avg_edit_ratio: Ratio moyen de modification
            - common_changes: Types de modifications frequentes
        """
        pass

    @abstractmethod
    def get_detailed_comparison(self) -> AIVsHumanComparison:
        """
        Recupere la comparaison detaillee IA vs humain.

        Returns:
            Objet AIVsHumanComparison complet.
        """
        pass

    @abstractmethod
    def record_human_edit(self, edit: HumanEdit) -> None:
        """
        Enregistre une modification humaine.

        Args:
            edit: Modification a enregistrer.
        """
        pass

    @abstractmethod
    def get_human_edits(self, limit: int = 100) -> List[HumanEdit]:
        """
        Recupere les modifications humaines recentes.

        Args:
            limit: Nombre maximum.

        Returns:
            Liste des modifications.
        """
        pass

    # =========================================================================
    # Performance
    # =========================================================================

    @abstractmethod
    def get_performance_metrics(
        self,
        period_days: int = 30,
    ) -> PerformanceMetrics:
        """
        Recupere les metriques de performance sur une periode.

        Args:
            period_days: Nombre de jours a analyser.

        Returns:
            Metriques de performance.
        """
        pass

    @abstractmethod
    def get_trend(self, metric: str, days: int = 30) -> List[Dict[str, Any]]:
        """
        Recupere la tendance d'une metrique.

        Args:
            metric: Nom de la metrique.
            days: Nombre de jours.

        Returns:
            Liste de points {date, value}.
        """
        pass
