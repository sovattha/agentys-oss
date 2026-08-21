# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Entités du domaine pour le système d'apprentissage automatique.

Ce module définit les entités métier pour l'analyse des feedbacks,
l'extraction de patterns et l'amélioration continue des réponses.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any
import uuid


class PatternType(Enum):
    """Type de pattern appris."""
    GOOD = "good"  # Pattern positif à encourager
    BAD = "bad"  # Pattern négatif à éviter


@dataclass
class LearningInsights:
    """
    Insights issus de l'analyse des feedbacks utilisateur.

    Attributes:
        total_with_feedback: Total d'emails avec feedback
        good_count: Nombre de feedbacks positifs (4-5 étoiles)
        bad_count: Nombre de feedbacks négatifs (1-2 étoiles)
        neutral_count: Nombre de feedbacks neutres (3 étoiles)
        v1_good_rate: Taux de satisfaction des brouillons V1 (%)
        v2_good_rate: Taux de satisfaction des brouillons V2 (%)
        common_issues: Problèmes récurrents identifiés
        strengths: Points forts identifiés
    """
    total_with_feedback: int = 0
    good_count: int = 0
    bad_count: int = 0
    neutral_count: int = 0
    v1_good_rate: int = 0
    v2_good_rate: int = 0
    common_issues: List[str] = field(default_factory=list)
    strengths: List[str] = field(default_factory=list)

    @property
    def satisfaction_rate(self) -> float:
        """Calcule le taux de satisfaction global."""
        if self.total_with_feedback == 0:
            return 0.0
        return (self.good_count / self.total_with_feedback) * 100


@dataclass
class LearnedPattern:
    """
    Pattern appris des feedbacks utilisateur.

    Attributes:
        id: Identifiant unique
        timestamp: Date de création
        pattern_type: Type de pattern (good/bad)
        trigger: Ce qui déclenche le pattern
        correction: La correction à appliquer (pour les bad patterns)
        examples: Exemples de ce pattern
        frequency: Nombre de fois observé
        confidence: Score de confiance (0.0 - 1.0)
    """
    id: str
    timestamp: datetime
    pattern_type: PatternType
    trigger: str
    correction: str
    examples: List[str] = field(default_factory=list)
    frequency: int = 1
    confidence: float = 0.5

    @classmethod
    def create(
        cls,
        pattern_type: PatternType,
        trigger: str,
        correction: str = "",
        examples: Optional[List[str]] = None,
    ) -> "LearnedPattern":
        """Crée un nouveau pattern appris."""
        return cls(
            id=str(uuid.uuid4())[:8],
            timestamp=datetime.now(),
            pattern_type=pattern_type,
            trigger=trigger,
            correction=correction,
            examples=examples or [],
        )

    def increment_frequency(self) -> None:
        """Incrémente la fréquence et ajuste la confiance."""
        self.frequency += 1
        # Confiance augmente avec la fréquence (max 1.0 à 10 occurrences)
        self.confidence = min(1.0, self.frequency / 10)

    def is_reliable(self, min_confidence: float = 0.6) -> bool:
        """Vérifie si le pattern est suffisamment fiable."""
        return self.confidence >= min_confidence

    def add_example(self, example: str) -> None:
        """Ajoute un exemple au pattern."""
        if example not in self.examples:
            self.examples.append(example)

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour la sérialisation."""
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "pattern_type": self.pattern_type.value,
            "trigger": self.trigger,
            "correction": self.correction,
            "examples": self.examples,
            "frequency": self.frequency,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LearnedPattern":
        """Crée une instance depuis un dictionnaire."""
        return cls(
            id=data["id"],
            timestamp=datetime.fromisoformat(data["timestamp"]) if isinstance(data["timestamp"], str) else data["timestamp"],
            pattern_type=PatternType(data["pattern_type"]),
            trigger=data["trigger"],
            correction=data.get("correction", ""),
            examples=data.get("examples", []),
            frequency=data.get("frequency", 1),
            confidence=data.get("confidence", 0.5),
        )


@dataclass
class PromptAdjustment:
    """
    Ajustement de prompt basé sur l'apprentissage.

    Attributes:
        id: Identifiant unique
        timestamp: Date de création
        section: Section du prompt à modifier
        adjustment: Texte de l'ajustement
        reason: Raison de l'ajustement
        active: Si l'ajustement est actif
    """
    id: str
    timestamp: datetime
    section: str
    adjustment: str
    reason: str
    active: bool = True

    @classmethod
    def create(
        cls,
        section: str,
        adjustment: str,
        reason: str,
    ) -> "PromptAdjustment":
        """Crée un nouvel ajustement de prompt."""
        return cls(
            id=str(uuid.uuid4())[:8],
            timestamp=datetime.now(),
            section=section,
            adjustment=adjustment,
            reason=reason,
        )

    def deactivate(self) -> None:
        """Désactive l'ajustement."""
        self.active = False

    def activate(self) -> None:
        """Active l'ajustement."""
        self.active = True

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour la sérialisation."""
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "section": self.section,
            "adjustment": self.adjustment,
            "reason": self.reason,
            "active": self.active,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PromptAdjustment":
        """Crée une instance depuis un dictionnaire."""
        return cls(
            id=data["id"],
            timestamp=datetime.fromisoformat(data["timestamp"]) if isinstance(data["timestamp"], str) else data["timestamp"],
            section=data["section"],
            adjustment=data["adjustment"],
            reason=data["reason"],
            active=data.get("active", True),
        )


@dataclass
class ReviewRequirement:
    """
    Exigence de review humaine pour un email.

    Attributes:
        needs_review: Si une review est nécessaire
        reasons: Raisons de la review
        priority_score: Score de priorité de l'email
    """
    needs_review: bool
    reasons: List[str] = field(default_factory=list)
    priority_score: int = 0

    def add_reason(self, reason: str) -> None:
        """Ajoute une raison à la review."""
        if reason not in self.reasons:
            self.reasons.append(reason)


@dataclass
class LearningStats:
    """
    Statistiques d'apprentissage.

    Attributes:
        patterns_count: Nombre total de patterns
        good_patterns: Nombre de patterns positifs
        bad_patterns: Nombre de patterns négatifs
        active_adjustments: Nombre d'ajustements actifs
        confidence_threshold: Seuil de confiance configuré
        total_with_feedback: Total d'emails avec feedback
        good_count: Nombre de feedbacks positifs
        bad_count: Nombre de feedbacks négatifs
        neutral_count: Nombre de feedbacks neutres
        v1_good_rate: Taux de satisfaction V1
        v2_good_rate: Taux de satisfaction V2
    """
    patterns_count: int = 0
    good_patterns: int = 0
    bad_patterns: int = 0
    active_adjustments: int = 0
    confidence_threshold: int = 70
    total_with_feedback: int = 0
    good_count: int = 0
    bad_count: int = 0
    neutral_count: int = 0
    v1_good_rate: int = 0
    v2_good_rate: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire."""
        return {
            "patterns_count": self.patterns_count,
            "good_patterns": self.good_patterns,
            "bad_patterns": self.bad_patterns,
            "active_adjustments": self.active_adjustments,
            "confidence_threshold": self.confidence_threshold,
            "total_with_feedback": self.total_with_feedback,
            "good_count": self.good_count,
            "bad_count": self.bad_count,
            "neutral_count": self.neutral_count,
            "v1_good_rate": self.v1_good_rate,
            "v2_good_rate": self.v2_good_rate,
        }
