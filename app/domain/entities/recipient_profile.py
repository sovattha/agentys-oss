"""Profil psychologique du destinataire (DISC) pour adapter la réponse (#190).

Research behavioral (DISC) mappe le style de communication préféré à 4 archétypes :

- **D (Dominance)**  : direct, résultats, pas de politesses
- **I (Influence)**  : enthousiaste, collaboratif, social proof
- **S (Steadiness)** : calme, rassurant, pas de pression
- **C (Conscientiousness)** : analytique, données, syntaxe structurée

Le profil est inféré à partir des emails reçus du destinataire (signaux
linguistiques). Phase 1 : heuristique gratuite. Phase 2 : Claude pour nuance.
Phase 3 : scraping LinkedIn pour enrichissement (légal permitting).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, Optional

from app.domain.exceptions import InvalidBoundsError


class DISCType(str, Enum):
    """Archétype DISC dominant. UNKNOWN = pas assez de signal pour décider."""
    DOMINANCE = "D"
    INFLUENCE = "I"
    STEADINESS = "S"
    CONSCIENTIOUSNESS = "C"
    UNKNOWN = "?"


@dataclass(frozen=True)
class DISCScores:
    """Scores bruts sur chaque dimension, utiles pour débugger le classifieur."""
    dominance: float
    influence: float
    steadiness: float
    conscientiousness: float

    def __post_init__(self):
        for name, value in (
            ("dominance", self.dominance),
            ("influence", self.influence),
            ("steadiness", self.steadiness),
            ("conscientiousness", self.conscientiousness),
        ):
            if not 0.0 <= value <= 1.0:
                raise InvalidBoundsError(name, value, 0.0, 1.0)

    def dominant(self) -> DISCType:
        """Retourne l'archétype dominant, ou UNKNOWN si ambigu (spread < 0.1)."""
        items = {
            DISCType.DOMINANCE: self.dominance,
            DISCType.INFLUENCE: self.influence,
            DISCType.STEADINESS: self.steadiness,
            DISCType.CONSCIENTIOUSNESS: self.conscientiousness,
        }
        ordered = sorted(items.items(), key=lambda kv: kv[1], reverse=True)
        top, second = ordered[0], ordered[1]
        if top[1] - second[1] < 0.1 or top[1] < 0.2:
            return DISCType.UNKNOWN
        return top[0]

    def confidence(self) -> float:
        """Spread entre top et second score — proxy de certitude."""
        values = sorted(
            [self.dominance, self.influence, self.steadiness, self.conscientiousness],
            reverse=True,
        )
        return round(values[0] - values[1], 3)

    def to_dict(self) -> dict:
        return {
            "dominance": self.dominance,
            "influence": self.influence,
            "steadiness": self.steadiness,
            "conscientiousness": self.conscientiousness,
        }


@dataclass(frozen=True)
class RecipientProfile:
    """Profil psychologique inféré d'un contact."""
    email: str
    disc: DISCType
    disc_scores: Optional[DISCScores] = None
    confidence: float = 0.0
    sample_size: int = 0  # Nombre d'emails analysés.
    source: str = "heuristic"  # "heuristic" | "llm" | "linkedin" | "manual"
    updated_at: Optional[datetime] = None

    def __post_init__(self):
        if not 0.0 <= self.confidence <= 1.0:
            raise InvalidBoundsError("confidence", self.confidence, 0.0, 1.0)
        if self.sample_size < 0:
            raise ValueError("sample_size must be >= 0")

    def is_reliable(self, min_confidence: float = 0.1, min_samples: int = 3) -> bool:
        """True si le profil a assez de signal pour influencer la génération.

        Seuils bas volontairement : mieux vaut un signal faible qu'aucun signal,
        tant qu'on propage la confidence au Drafter qui peut pondérer.
        """
        return (
            self.disc != DISCType.UNKNOWN
            and self.confidence >= min_confidence
            and self.sample_size >= min_samples
        )

    def to_prompt_block(self) -> str:
        """Rend un bloc injectable dans le system prompt du Drafter.

        Retourne chaîne vide si le profil n'est pas fiable — on évite de polluer
        le prompt avec une inférence incertaine qui pourrait dégrader la sortie.
        """
        if not self.is_reliable():
            return ""
        advice = _DISC_WRITING_ADVICE.get(self.disc, "")
        return (
            "<PROFIL_DESTINATAIRE>\n"
            f"DISC={self.disc.value} | confidence={self.confidence:.2f} | "
            f"base={self.sample_size} emails\n"
            f"Adapte la réponse : {advice}\n"
            "</PROFIL_DESTINATAIRE>"
        )

    def to_dict(self) -> dict:
        return {
            "email": self.email,
            "disc": self.disc.value,
            "disc_scores": self.disc_scores.to_dict() if self.disc_scores else None,
            "confidence": self.confidence,
            "sample_size": self.sample_size,
            "source": self.source,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# Conseils de rédaction par archétype, injectés dans le prompt quand un profil
# fiable est disponible. Volontairement concis (1 phrase) pour le token budget.
_DISC_WRITING_ADVICE: Dict[DISCType, str] = {
    DISCType.DOMINANCE: (
        "sois direct, orienté résultat ; bullets courts ; une CTA claire ; "
        "zéro politesse superflue."
    ),
    DISCType.INFLUENCE: (
        "ton conversationnel, chaleureux ; partenariat et social proof ; "
        "ok pour un élément engageant (émoji léger si le contexte s'y prête)."
    ),
    DISCType.STEADINESS: (
        "ton calme et rassurant ; structure pas à pas ; insiste sur "
        "fiabilité et réduction du risque ; AUCUNE urgence artificielle."
    ),
    DISCType.CONSCIENTIOUSNESS: (
        "contenu dense et précis ; chiffres ou références si disponibles ; "
        "syntaxe structurée ; AUCUNE hyperbole ni superlatifs."
    ),
}
