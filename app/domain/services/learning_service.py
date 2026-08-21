# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Service façade pour le système d'apprentissage.

Ce service expose une API compatible avec l'ancien LearningManager
tout en utilisant la Clean Architecture en interne.

Il permet au daemon d'utiliser les nouvelles implémentations
sans modification majeure du code existant.
"""

from typing import List, Optional, Dict, Any

from app.domain.entities.learning import (
    LearningInsights,
    LearnedPattern,
    PromptAdjustment,
    ReviewRequirement,
)


class LearningService:
    """
    Service façade pour le système d'apprentissage.

    Cette classe fournit une API compatible avec l'ancien LearningManager
    pour faciliter la migration du daemon et autres consommateurs.

    Usage:
        container = get_container()
        service = container.get_learning_service()
        insights = service.analyze_feedback()
    """

    def __init__(
        self,
        analyze_use_case,
        extract_use_case,
        should_review_use_case,
        generate_adjustment_use_case,
        stats_use_case,
        enhance_prompt_use_case,
        get_active_adjustments_use_case=None,
    ):
        """
        Initialise le service avec les use cases.

        Args:
            analyze_use_case: Use case d'analyse des feedbacks.
            extract_use_case: Use case d'extraction de patterns.
            should_review_use_case: Use case de détermination de review.
            generate_adjustment_use_case: Use case de génération d'ajustements.
            stats_use_case: Use case de récupération des stats.
            enhance_prompt_use_case: Use case d'amélioration de prompt.
            get_active_adjustments_use_case: Use case pour récupérer les ajustements actifs.
        """
        self._analyze = analyze_use_case
        self._extract = extract_use_case
        self._should_review = should_review_use_case
        self._generate_adjustment = generate_adjustment_use_case
        self._stats = stats_use_case
        self._enhance_prompt = enhance_prompt_use_case
        self._get_active_adjustments = get_active_adjustments_use_case

    def analyze_feedback(self) -> Dict[str, Any]:
        """
        Analyse les feedbacks et retourne les insights.

        Compatible avec l'ancien LearningManager.analyze_feedback().

        Returns:
            Dictionnaire avec les statistiques.
        """
        insights: LearningInsights = self._analyze.execute()
        return {
            "total_with_feedback": insights.total_with_feedback,
            "good_count": insights.good_count,
            "bad_count": insights.bad_count,
            "neutral_count": insights.neutral_count,
            "v1_good_rate": insights.v1_good_rate,
            "v2_good_rate": insights.v2_good_rate,
            "common_issues": insights.common_issues,
            "strengths": insights.strengths,
        }

    def extract_patterns_from_feedback(self) -> List[LearnedPattern]:
        """
        Extrait des patterns des feedbacks.

        Compatible avec l'ancien LearningManager.extract_patterns_from_feedback().

        Returns:
            Liste des patterns extraits.
        """
        return self._extract.execute()

    def generate_prompt_adjustment(self) -> Optional[PromptAdjustment]:
        """
        Génère un ajustement de prompt.

        Compatible avec l'ancien LearningManager.generate_prompt_adjustment().

        Returns:
            L'ajustement généré ou None.
        """
        return self._generate_adjustment.execute()

    def should_require_review(
        self,
        email_content: str,
        priority_score: int,
    ) -> bool:
        """
        Détermine si un email nécessite une review humaine.

        Compatible avec l'ancien LearningManager.should_require_review().

        Args:
            email_content: Contenu de l'email.
            priority_score: Score de priorité (0-100).

        Returns:
            True si review nécessaire.
        """
        requirement: ReviewRequirement = self._should_review.execute(
            email_content=email_content,
            priority_score=priority_score,
        )
        return requirement.needs_review

    def get_review_requirement(
        self,
        email_content: str,
        priority_score: int,
    ) -> ReviewRequirement:
        """
        Détermine si un email nécessite une review (avec détails).

        Retourne l'objet complet avec les raisons.

        Args:
            email_content: Contenu de l'email.
            priority_score: Score de priorité (0-100).

        Returns:
            ReviewRequirement avec la décision et les raisons.
        """
        return self._should_review.execute(
            email_content=email_content,
            priority_score=priority_score,
        )

    def get_active_adjustments(self) -> List[str]:
        """
        Récupère les textes des ajustements actifs.

        Compatible avec l'ancien LearningManager.get_active_adjustments().

        Returns:
            Liste des textes d'ajustement.
        """
        if self._get_active_adjustments is not None:
            return self._get_active_adjustments.execute()

        # Fallback: utiliser enhance_prompt pour rétrocompatibilité
        enhanced = self._enhance_prompt.execute("")
        if enhanced == "":
            return []

        # Parser les ajustements depuis le texte enrichi
        adjustments = []
        lines = enhanced.split("\n")
        for line in lines:
            if line.strip().startswith("- "):
                adjustments.append(line.strip()[2:])
        return adjustments

    def get_stats(self) -> Dict[str, Any]:
        """
        Récupère les statistiques d'apprentissage.

        Compatible avec l'ancien LearningManager.get_stats().

        Returns:
            Dictionnaire avec toutes les statistiques.
        """
        return self._stats.execute()

    def enhance_prompt(self, base_prompt: str) -> str:
        """
        Améliore le prompt avec les ajustements appris.

        Cette méthode remplace l'ancienne fonction standalone
        get_enhanced_drafter_prompt, qui violait la Clean Architecture.

        Args:
            base_prompt: Le prompt de base à enrichir.

        Returns:
            Le prompt enrichi avec les règles apprises.
        """
        return self._enhance_prompt.execute(base_prompt)
