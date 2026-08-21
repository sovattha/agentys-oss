# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Entite pour le score de similarite de style.

Ce module definit l'entite metier pour mesurer la correspondance
entre un brouillon genere et le style d'ecriture de l'utilisateur.
"""

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class StyleSimilarityScore:
    """
    Score de similarite entre un brouillon et le style de l'utilisateur.

    Mesure a quel point un brouillon genere correspond au style
    d'ecriture personnel de l'utilisateur.

    Attributes:
        overall_score: Score global de 0 a 100.
        greeting_match: La salutation correspond au style.
        closing_match: La formule de cloture correspond au style.
        formality_match: Le niveau de formalite correspond.
        vocabulary_overlap: Chevauchement du vocabulaire (0-1).
        analysis_details: Details supplementaires de l'analyse.
    """
    overall_score: float
    greeting_match: bool = False
    closing_match: bool = False
    formality_match: bool = False
    vocabulary_overlap: float = 0.0
    analysis_details: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validation apres initialisation."""
        if not 0 <= self.overall_score <= 100:
            raise ValueError("overall_score must be between 0 and 100")
        if not 0 <= self.vocabulary_overlap <= 1:
            raise ValueError("vocabulary_overlap must be between 0 and 1")

    def is_acceptable(self, threshold: float = 70.0) -> bool:
        """
        Verifie si le score est acceptable.

        Args:
            threshold: Seuil minimum (defaut 70.0).

        Returns:
            True si overall_score >= threshold.
        """
        return self.overall_score >= threshold

    @property
    def matches_count(self) -> int:
        """Nombre de criteres correspondants (sur 3)."""
        return sum([
            self.greeting_match,
            self.closing_match,
            self.formality_match,
        ])

    @property
    def summary(self) -> str:
        """Resume lisible du score."""
        return (
            f"Score: {self.overall_score}% - "
            f"{self.matches_count}/3 criteres "
            f"(vocab: {self.vocabulary_overlap:.0%})"
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour serialisation JSON."""
        return {
            "overall_score": self.overall_score,
            "greeting_match": self.greeting_match,
            "closing_match": self.closing_match,
            "formality_match": self.formality_match,
            "vocabulary_overlap": self.vocabulary_overlap,
            "analysis_details": self.analysis_details,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StyleSimilarityScore":
        """Cree une instance depuis un dictionnaire."""
        return cls(
            overall_score=data["overall_score"],
            greeting_match=data.get("greeting_match", False),
            closing_match=data.get("closing_match", False),
            formality_match=data.get("formality_match", False),
            vocabulary_overlap=data.get("vocabulary_overlap", 0.0),
            analysis_details=data.get("analysis_details", {}),
        )

    @classmethod
    def create_default(cls) -> "StyleSimilarityScore":
        """Cree un score par defaut (aucune correspondance)."""
        return cls(overall_score=0.0)

    @classmethod
    def create_perfect(cls) -> "StyleSimilarityScore":
        """Cree un score parfait (100% match)."""
        return cls(
            overall_score=100.0,
            greeting_match=True,
            closing_match=True,
            formality_match=True,
            vocabulary_overlap=1.0,
        )
