# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Use Cases pour le système d'apprentissage automatique.

Cette couche contient la logique métier pour :
- Analyser les feedbacks utilisateur
- Extraire des patterns des corrections
- Générer des ajustements de prompt
- Déterminer si une review humaine est nécessaire

Règle : Cette couche dépend uniquement du domaine (entities + ports).
"""

from dataclasses import dataclass
from typing import List, Optional, Dict, Any
import json
import re

from app.domain.entities.learning import (
    LearningInsights,
    LearnedPattern,
    PromptAdjustment,
    ReviewRequirement,
    PatternType,
)
from app.domain.ports.learning_port import (
    LearningPatternStorePort,
    AdjustmentStorePort,
    LearningFeedbackProviderPort,
)
from app.domain.ports.llm_port import LLMPort


# Valeurs par défaut (configuration injectée via les use cases)
DEFAULT_CONFIDENCE_THRESHOLD = 70

# Seuil de fréquence minimum pour suggérer un pattern (3+ détections)
# Correspond à "seuil_pattern_detection" dans la config d'apprentissage
MIN_PATTERN_FREQUENCY = 3

DEFAULT_SENSITIVE_WORDS = [
    "contrat", "juridique", "avocat", "urgent", "deadline",
    "licenciement", "litige", "plainte", "tribunal"
]


# =============================================================================
# HELPERS
# =============================================================================


def _extract_rating(feedback) -> Optional[int]:
    """
    Extrait le rating d'un feedback de manière unifiée.

    Supporte les attributs 'rating' et 'feedback_rating' pour
    la compatibilité avec différentes structures de feedback.

    Args:
        feedback: Objet feedback avec rating ou feedback_rating.

    Returns:
        Le rating ou None si non disponible.
    """
    rating = getattr(feedback, "rating", None)
    if rating is None:
        rating = getattr(feedback, "feedback_rating", None)
    return rating


def _extract_json_from_response(response: str) -> Optional[Dict[str, Any]]:
    """
    Extrait un objet JSON depuis une réponse LLM.

    Gère les cas où le JSON est encapsulé dans des backticks markdown.

    Args:
        response: Réponse brute du LLM.

    Returns:
        Dictionnaire parsé ou None si parsing échoue.
    """
    clean_response = response.strip()

    # Retirer les backticks markdown si présents
    json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', clean_response)
    if json_match:
        clean_response = json_match.group(1)

    try:
        return json.loads(clean_response)
    except json.JSONDecodeError:
        return None


# =============================================================================
# ANALYZE FEEDBACK USE CASE
# =============================================================================


@dataclass
class AnalyzeFeedbackUseCase:
    """
    Use case pour analyser les feedbacks utilisateur.

    Analyse les feedbacks stockés et génère des insights sur
    la qualité des réponses générées.
    """
    feedback_store: LearningFeedbackProviderPort

    def execute(self, limit: int = 1000) -> LearningInsights:
        """
        Analyse les feedbacks et retourne des insights.

        Args:
            limit: Nombre maximum de feedbacks à analyser.

        Returns:
            LearningInsights avec les statistiques.
        """
        feedbacks = self.feedback_store.get_all(limit=limit)

        if not feedbacks:
            return LearningInsights()

        good_count, bad_count, neutral_count = self._count_by_rating(feedbacks)
        total = good_count + bad_count + neutral_count

        v1_good_rate = self._calculate_good_rate_for_version(feedbacks, "V1")
        v2_good_rate = self._calculate_good_rate_for_version(feedbacks, "V2")

        return LearningInsights(
            total_with_feedback=total,
            good_count=good_count,
            bad_count=bad_count,
            neutral_count=neutral_count,
            v1_good_rate=v1_good_rate,
            v2_good_rate=v2_good_rate,
        )

    def _count_by_rating(self, feedbacks) -> tuple:
        """Compte les feedbacks par catégorie de rating."""
        good_count = 0
        bad_count = 0
        neutral_count = 0

        for feedback in feedbacks:
            rating = _extract_rating(feedback)
            if rating is None:
                continue

            if rating >= 4:
                good_count += 1
            elif rating <= 2:
                bad_count += 1
            else:
                neutral_count += 1

        return good_count, bad_count, neutral_count

    def _calculate_good_rate_for_version(self, feedbacks, version: str) -> int:
        """Calcule le taux de satisfaction pour une version donnée."""
        version_feedbacks = [
            f for f in feedbacks
            if hasattr(f, "status") and version in str(getattr(f, "status", ""))
        ]

        if not version_feedbacks:
            return 0

        good_count = len([
            f for f in version_feedbacks
            if (_extract_rating(f) or 0) >= 4
        ])
        return round(good_count / len(version_feedbacks) * 100)


# =============================================================================
# EXTRACT PATTERNS USE CASE
# =============================================================================


@dataclass
class ExtractPatternsUseCase:
    """
    Use case pour extraire des patterns des feedbacks.

    Utilise un LLM pour analyser les feedbacks textuels et
    identifier des patterns récurrents.
    """
    feedback_store: LearningFeedbackProviderPort
    pattern_store: LearningPatternStorePort
    llm: LLMPort

    def execute(self, limit: int = 100) -> List[LearnedPattern]:
        """
        Extrait des patterns des feedbacks.

        Args:
            limit: Nombre maximum de feedbacks à analyser.

        Returns:
            Liste des patterns extraits.
        """
        feedbacks = self.feedback_store.get_with_comments(limit=limit)

        if not feedbacks:
            return []

        # Construire le texte pour l'analyse
        feedback_text = self._build_feedback_text(feedbacks[:20])

        if not feedback_text.strip():
            return []

        # Appeler le LLM pour extraire les patterns
        try:
            response = self.llm.complete(
                system="Tu es un analyseur de feedbacks. Extrait les patterns récurrents.",
                user=self._build_extraction_prompt(feedback_text),
                max_tokens=1000,
            )

            patterns = self._parse_patterns(response.content)

            # Sauvegarder les patterns
            if patterns:
                self.pattern_store.save_many(patterns)

            return patterns

        except Exception:
            return []

    def _build_feedback_text(self, feedbacks) -> str:
        """Construit le texte des feedbacks pour l'analyse."""
        lines = []
        for f in feedbacks:
            rating = _extract_rating(f) or "?"
            comment = getattr(f, "comment", getattr(f, "feedback", ""))
            draft = getattr(f, "draft_final", "")[:200] if hasattr(f, "draft_final") else ""

            if comment:
                lines.append(f"Rating: {rating}/5\nFeedback: {comment}\nDraft: {draft}...")

        return "\n\n".join(lines)

    def _build_extraction_prompt(self, feedback_text: str) -> str:
        """Construit le prompt pour l'extraction de patterns."""
        return f"""Analyse ces feedbacks sur des emails générés par IA et identifie les patterns récurrents.

{feedback_text}

Retourne un JSON avec:
{{
  "good_patterns": ["pattern 1", "pattern 2"],
  "bad_patterns": ["pattern 1", "pattern 2"],
  "suggestions": ["suggestion 1", "suggestion 2"]
}}

Retourne UNIQUEMENT le JSON."""

    def _parse_patterns(self, response: str) -> List[LearnedPattern]:
        """Parse la réponse du LLM en patterns."""
        result = _extract_json_from_response(response)
        if result is None:
            return []

        patterns = []

        for pattern_text in result.get("good_patterns", []):
            patterns.append(LearnedPattern.create(
                pattern_type=PatternType.GOOD,
                trigger=pattern_text,
                correction="",
            ))

        suggestions = result.get("suggestions", [])
        for i, pattern_text in enumerate(result.get("bad_patterns", [])):
            correction = suggestions[i] if i < len(suggestions) else ""
            patterns.append(LearnedPattern.create(
                pattern_type=PatternType.BAD,
                trigger=pattern_text,
                correction=correction,
            ))

        return patterns


# =============================================================================
# SHOULD REQUIRE REVIEW USE CASE
# =============================================================================


@dataclass
class ShouldRequireReviewUseCase:
    """
    Use case pour déterminer si un email nécessite une review humaine.

    Vérifie plusieurs critères :
    - Priorité élevée
    - Contenu sensible
    - Faible confiance du système
    """
    insights_provider: LearningFeedbackProviderPort
    confidence_threshold: int = DEFAULT_CONFIDENCE_THRESHOLD
    sensitive_words: List[str] = None

    def __post_init__(self):
        if self.sensitive_words is None:
            self.sensitive_words = DEFAULT_SENSITIVE_WORDS

    def execute(
        self,
        email_content: str,
        priority_score: int,
    ) -> ReviewRequirement:
        """
        Détermine si une review est nécessaire.

        Args:
            email_content: Contenu de l'email.
            priority_score: Score de priorité (0-100).

        Returns:
            ReviewRequirement avec la décision et les raisons.
        """
        requirement = ReviewRequirement(
            needs_review=False,
            priority_score=priority_score,
        )

        # Critère 1: Priorité très haute
        if priority_score >= 90:
            requirement.needs_review = True
            requirement.add_reason("Email de priorité très haute (>= 90)")

        # Critère 2: Contenu sensible
        content_lower = email_content.lower()
        for word in self.sensitive_words:
            if word in content_lower:
                requirement.needs_review = True
                requirement.add_reason(f"Contenu sensible détecté: '{word}'")
                break  # Un seul mot suffit

        # Critère 3: Faible confiance du système
        satisfaction_rate = self.insights_provider.get_satisfaction_rate()
        if satisfaction_rate < self.confidence_threshold:
            requirement.needs_review = True
            requirement.add_reason(
                f"Confiance système faible ({satisfaction_rate:.0f}% < {self.confidence_threshold}%)"
            )

        return requirement


# =============================================================================
# GENERATE ADJUSTMENT USE CASE
# =============================================================================


@dataclass
class GenerateAdjustmentUseCase:
    """
    Use case pour générer un ajustement de prompt.

    Analyse les patterns négatifs et génère des ajustements
    pour améliorer les réponses futures.
    """
    pattern_store: LearningPatternStorePort
    adjustment_store: AdjustmentStorePort

    def execute(self) -> Optional[PromptAdjustment]:
        """
        Génère un ajustement basé sur les patterns négatifs.

        Seuls les patterns détectés au moins MIN_PATTERN_FREQUENCY fois (3+)
        sont considérés pour générer des ajustements (seuil de confiance).

        Returns:
            L'ajustement généré ou None si pas de pattern fiable.
        """
        bad_patterns = self.pattern_store.get_by_type(PatternType.BAD)

        if not bad_patterns:
            return None

        # Filtrer les patterns avec fréquence suffisante (seuil de confiance)
        reliable_patterns = [
            p for p in bad_patterns
            if p.frequency >= MIN_PATTERN_FREQUENCY
        ]

        if not reliable_patterns:
            return None

        # Trouver le pattern le plus fréquent parmi les fiables
        most_common = max(reliable_patterns, key=lambda p: p.frequency)

        # Créer l'ajustement
        adjustment = PromptAdjustment.create(
            section="DRAFTER_SYSTEM_PROMPT",
            adjustment=f"Évite: {most_common.trigger}. {most_common.correction}".strip(),
            reason=f"Pattern détecté {most_common.frequency} fois",
        )

        # Sauvegarder
        self.adjustment_store.save(adjustment)

        return adjustment


# =============================================================================
# GET LEARNING STATS USE CASE
# =============================================================================


@dataclass
class GetLearningStatsUseCase:
    """
    Use case pour récupérer les statistiques d'apprentissage.
    """
    pattern_store: LearningPatternStorePort
    adjustment_store: AdjustmentStorePort
    feedback_store: LearningFeedbackProviderPort
    confidence_threshold: int = DEFAULT_CONFIDENCE_THRESHOLD

    def execute(self) -> Dict[str, Any]:
        """
        Récupère les statistiques complètes.

        Returns:
            Dictionnaire avec toutes les statistiques.
        """
        # Compter les patterns
        patterns_count = self.pattern_store.count()
        count_by_type = self.pattern_store.count_by_type()

        # Compter les ajustements actifs
        active_adjustments = self.adjustment_store.count_active()

        # Analyser les feedbacks
        analyze_use_case = AnalyzeFeedbackUseCase(
            feedback_store=self.feedback_store
        )
        insights = analyze_use_case.execute()

        return {
            "patterns_count": patterns_count,
            "good_patterns": count_by_type.get("good", 0),
            "bad_patterns": count_by_type.get("bad", 0),
            "active_adjustments": active_adjustments,
            "confidence_threshold": self.confidence_threshold,
            "total_with_feedback": insights.total_with_feedback,
            "good_count": insights.good_count,
            "bad_count": insights.bad_count,
            "neutral_count": insights.neutral_count,
            "v1_good_rate": insights.v1_good_rate,
            "v2_good_rate": insights.v2_good_rate,
        }


# =============================================================================
# GET ACTIVE ADJUSTMENTS USE CASE
# =============================================================================


@dataclass
class GetActiveAdjustmentsUseCase:
    """
    Use case pour récupérer les textes des ajustements actifs.

    Retourne uniquement les textes d'ajustement (sans métadonnées)
    pour la compatibilité avec l'ancien LearningManager.
    """
    adjustment_store: AdjustmentStorePort

    def execute(self) -> List[str]:
        """
        Récupère les textes des ajustements actifs.

        Returns:
            Liste des textes d'ajustement.
        """
        adjustments = self.adjustment_store.get_active()
        return [a.adjustment for a in adjustments]


# =============================================================================
# ENHANCE PROMPT USE CASE
# =============================================================================


@dataclass
class EnhancePromptUseCase:
    """
    Use case pour enrichir un prompt avec les ajustements appris.
    """
    adjustment_store: AdjustmentStorePort

    def execute(self, base_prompt: str) -> str:
        """
        Enrichit le prompt avec les ajustements actifs.

        Args:
            base_prompt: Le prompt de base.

        Returns:
            Le prompt enrichi.
        """
        adjustments = self.adjustment_store.get_active()

        if not adjustments:
            return base_prompt

        adjustments_text = "\n".join([f"- {a.adjustment}" for a in adjustments])

        return f"""{base_prompt}

## Règles apprises (basées sur les feedbacks)
{adjustments_text}"""
