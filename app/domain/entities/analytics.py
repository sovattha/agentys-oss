# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Entites pour le systeme d'analytics et de qualite.

Ces entites representent les metriques de qualite
des reponses generees par l'IA.
"""

from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class QualityScore:
    """
    Score de qualite d'une reponse generee.

    Attributes:
        draft_id: ID du brouillon evalue.
        overall_score: Score global (0-100).
        tone_score: Score de ton (0-100).
        completeness_score: Score de completude (0-100).
        professionalism_score: Score de professionnalisme (0-100).
        relevance_score: Score de pertinence (0-100).
        user_rating: Note utilisateur (1-5).
        was_edited: Si le brouillon a ete modifie.
        edit_ratio: Ratio de modification (0-1).
        timestamp: Date/heure de l'evaluation.
    """

    draft_id: str
    overall_score: float = 0.0
    tone_score: float = 0.0
    completeness_score: float = 0.0
    professionalism_score: float = 0.0
    relevance_score: float = 0.0
    user_rating: Optional[int] = None
    was_edited: bool = False
    edit_ratio: float = 0.0
    timestamp: str = ""

    @property
    def quality_level(self) -> str:
        """
        Niveau de qualite textuel.

        Returns:
            "excellent", "good", "acceptable", ou "needs_improvement"
        """
        if self.overall_score >= 90:
            return "excellent"
        elif self.overall_score >= 75:
            return "good"
        elif self.overall_score >= 50:
            return "acceptable"
        else:
            return "needs_improvement"


@dataclass
class HumanEdit:
    """
    Enregistrement d'une modification humaine sur un brouillon IA.

    Attributes:
        id: Identifiant unique.
        draft_id: ID du brouillon original.
        original_draft: Brouillon IA original.
        edited_draft: Version modifiee par l'humain.
        edit_distance: Distance de Levenshtein.
        edit_ratio: Ratio de modification (0-1).
        word_changes: Nombre de mots changes.
        timestamp: Date/heure de la modification.
        editor_notes: Notes de l'editeur.
    """

    id: str
    draft_id: str
    original_draft: str
    edited_draft: str
    edit_distance: int = 0
    edit_ratio: float = 0.0
    word_changes: int = 0
    timestamp: str = ""
    editor_notes: str = ""

    @property
    def similarity(self) -> float:
        """Similarite entre original et modifie (1 = identique)."""
        return 1.0 - self.edit_ratio


@dataclass
class PerformanceMetrics:
    """
    Metriques de performance globales.

    Attributes:
        period_start: Debut de la periode.
        period_end: Fin de la periode.
        total_drafts: Nombre total de brouillons.
        avg_quality_score: Score de qualite moyen.
        avg_user_rating: Note utilisateur moyenne.
        edit_rate: Pourcentage de brouillons modifies.
        avg_edit_ratio: Ratio moyen de modification.
        v1_acceptance_rate: Pourcentage de V1 valides.
        response_time_avg: Temps moyen de generation (sec).
        improvement_trend: Tendance d'amelioration (-1 a 1).
    """

    period_start: str
    period_end: str
    total_drafts: int = 0
    avg_quality_score: float = 0.0
    avg_user_rating: float = 0.0
    edit_rate: float = 0.0
    avg_edit_ratio: float = 0.0
    v1_acceptance_rate: float = 0.0
    response_time_avg: float = 0.0
    improvement_trend: float = 0.0


@dataclass
class QualityMetrics:
    """Metriques de qualite agregees."""
    avg_score: float = 0.0
    total_drafts: int = 0
    excellent_count: int = 0
    good_count: int = 0
    acceptable_count: int = 0
    needs_improvement_count: int = 0
    avg_user_rating: float = 0.0
    rated_count: int = 0


@dataclass
class AIVsHumanComparison:
    """Comparaison IA vs modifications humaines."""
    total_drafts: int = 0
    edited_count: int = 0
    edit_rate: float = 0.0
    avg_edit_ratio: float = 0.0
    avg_word_changes: float = 0.0
    common_edit_types: List[str] = field(default_factory=list)
