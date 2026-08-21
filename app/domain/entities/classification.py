# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Entités pour la classification et priorisation des emails."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional
from datetime import datetime

from app.domain.exceptions import InvalidBoundsError, EmptyValueError


class EmailCategory(Enum):
    """Catégories possibles pour un email."""
    URGENT = "URGENT"           # Demande urgente, problème critique
    IMPORTANT = "IMPORTANT"     # Demande client, question business
    NORMAL = "NORMAL"           # Email standard nécessitant une réponse
    NEWSLETTER = "NEWSLETTER"   # Newsletter, digest, notification automatique
    PROMO = "PROMO"             # Email marketing, promotion
    CC_ONLY = "CC_ONLY"         # L'utilisateur est juste en copie
    SPAM = "SPAM"               # Spam évident


@dataclass
class Classification:
    """Résultat de la classification d'un email.

    Validation:
    - confidence: doit être dans [0.0, 1.0]
    - reason: doit être une string (non None)
    """
    category: EmailCategory
    confidence: float  # 0.0 à 1.0
    reason: str

    def __post_init__(self):
        """Validation après initialisation."""
        # Validation confidence
        if not 0.0 <= self.confidence <= 1.0:
            raise InvalidBoundsError(
                field="confidence",
                value=self.confidence,
                min_val=0.0,
                max_val=1.0
            )

        # Validation reason
        if self.reason is None:
            raise TypeError("reason cannot be None, use empty string if needed")

    @classmethod
    def default(cls) -> "Classification":
        """Retourne une classification par défaut."""
        return cls(
            category=EmailCategory.NORMAL,
            confidence=0.5,
            reason="Classification par défaut"
        )

    def should_skip(self) -> bool:
        """Indique si l'email doit être ignoré selon sa catégorie."""
        return self.category in [
            EmailCategory.NEWSLETTER,
            EmailCategory.PROMO,
            EmailCategory.SPAM,
            EmailCategory.CC_ONLY,
        ]

    def to_dict(self) -> dict:
        """Convertit en dictionnaire pour sérialisation."""
        return {
            "category": self.category.value,
            "confidence": self.confidence,
            "reason": self.reason,
        }


@dataclass
class Priority:
    """Résultat de l'analyse de priorité d'un email.

    Validation:
    - urgency: [0, 100]
    - vip: [0, 100]
    - sentiment: [-1.0, 1.0]
    - priority_score: [0, 100]
    - deadline: format ISO ou None
    """
    urgency: int           # 0-100 : score d'urgence
    vip: int               # 0-100 : importance de l'expéditeur
    sentiment: float       # -1 à 1 : -1=négatif, 0=neutre, 1=positif
    deadline: Optional[str]  # Date limite si mentionnée (format ISO)
    priority_score: int    # 0-100 : score global de priorité

    def __post_init__(self):
        """Validation après initialisation."""
        # Validation urgency
        if not 0 <= self.urgency <= 100:
            raise InvalidBoundsError("urgency", self.urgency, 0, 100)

        # Validation vip
        if not 0 <= self.vip <= 100:
            raise InvalidBoundsError("vip", self.vip, 0, 100)

        # Validation sentiment
        if not -1.0 <= self.sentiment <= 1.0:
            raise InvalidBoundsError("sentiment", self.sentiment, -1.0, 1.0)

        # Validation priority_score
        if not 0 <= self.priority_score <= 100:
            raise InvalidBoundsError("priority_score", self.priority_score, 0, 100)

        # Validation deadline format (si présent et non vide)
        if self.deadline and self.deadline.strip():
            self._validate_deadline_format()

    def _validate_deadline_format(self) -> None:
        """Valide que deadline est au format ISO."""
        from app.domain.exceptions import InvalidFormatError
        try:
            # Essaie de parser comme ISO
            datetime.fromisoformat(self.deadline.replace('Z', '+00:00'))
        except ValueError:
            raise InvalidFormatError(
                field="deadline",
                expected_format="ISO 8601 (YYYY-MM-DDTHH:MM:SS)",
                actual_value=self.deadline
            )

    @classmethod
    def default(cls) -> "Priority":
        """Retourne une priorité par défaut (moyenne)."""
        return cls(
            urgency=50,
            vip=50,
            sentiment=0.0,
            deadline=None,
            priority_score=50
        )

    @classmethod
    def from_components(
        cls,
        urgency: int,
        vip: int,
        sentiment: float,
        deadline: Optional[str] = None
    ) -> "Priority":
        """
        Crée une Priority avec calcul automatique du score.

        La formule est : (urgency * 0.4 + vip * 0.3 + (sentiment + 1) * 15)

        Raises:
            InvalidBoundsError: si les valeurs sont hors bornes
        """
        # Validation des entrées AVANT le calcul
        if not 0 <= urgency <= 100:
            raise InvalidBoundsError("urgency", urgency, 0, 100)
        if not 0 <= vip <= 100:
            raise InvalidBoundsError("vip", vip, 0, 100)
        if not -1.0 <= sentiment <= 1.0:
            raise InvalidBoundsError("sentiment", sentiment, -1.0, 1.0)

        priority_score = int(urgency * 0.4 + vip * 0.3 + (sentiment + 1) * 15)
        # Clamp entre 0 et 100
        priority_score = max(0, min(100, priority_score))

        return cls(
            urgency=urgency,
            vip=vip,
            sentiment=sentiment,
            deadline=deadline,
            priority_score=priority_score
        )

    def is_high_priority(self) -> bool:
        """Indique si l'email est hautement prioritaire (score >= 70)."""
        return self.priority_score >= 70

    def is_low_priority(self) -> bool:
        """Indique si l'email est peu prioritaire (score < 30)."""
        return self.priority_score < 30

    def to_dict(self) -> dict:
        """Convertit en dictionnaire pour sérialisation."""
        return {
            "urgency": self.urgency,
            "vip": self.vip,
            "sentiment": self.sentiment,
            "deadline": self.deadline,
            "priority_score": self.priority_score,
        }


class IntentCategory(Enum):
    """Intent structurel d'un email entrant, utilisé pour router la génération du draft.

    Distinct de :class:`EmailCategory` qui classe pour triage (urgent/newsletter/spam).
    ``IntentCategory`` classe pour action : quel framework de réponse appliquer.
    """
    INQUIRY = "INQUIRY"              # Question pricing/scope/capabilities sans historique
    NEGOTIATION = "NEGOTIATION"      # Budget/discount/timeline/alternatives
    FOLLOW_UP = "FOLLOW_UP"          # Check-in, relance temporelle
    OBJECTION = "OBJECTION"          # Hésitation/concern/sentiment négatif
    ESCALATION = "ESCALATION"        # Demande humain, détresse, menace
    INFORMATIONAL = "INFORMATIONAL"  # Partage d'info, pas d'action demandée
    OTHER = "OTHER"                  # Fallback quand non classifiable


@dataclass
class IntentClassification:
    """Résultat de la classification d'intent d'un email.

    Conçu pour alimenter le routage du DrafterAgent vers des protocoles
    de génération adaptés (framework copywriting, triggers, action).

    Validation:
    - confidence: [0.0, 1.0]
    - reasoning: string non-None (peut être vide)
    """
    intent: IntentCategory
    confidence: float
    reasoning: str

    def __post_init__(self):
        if not 0.0 <= self.confidence <= 1.0:
            raise InvalidBoundsError(
                field="confidence",
                value=self.confidence,
                min_val=0.0,
                max_val=1.0,
            )
        if self.reasoning is None:
            raise TypeError("reasoning cannot be None, use empty string if needed")

    @classmethod
    def default(cls) -> "IntentClassification":
        """Fallback en cas d'échec de classification — INQUIRY low confidence."""
        return cls(
            intent=IntentCategory.OTHER,
            confidence=0.3,
            reasoning="Classification par défaut",
        )

    def requires_human_escalation(self) -> bool:
        """True si le draft doit être bloqué et un humain alerté."""
        return self.intent == IntentCategory.ESCALATION and self.confidence >= 0.6

    def to_dict(self) -> dict:
        return {
            "intent": self.intent.value,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "IntentClassification":
        """Parse depuis la sortie LLM.

        Tolérant : valeurs manquantes ou non reconnues retombent sur les
        défauts plutôt que de lever une exception (l'appelant décide du
        fallback via ``default()``).
        """
        raw_intent = str(data.get("intent", "OTHER")).upper()
        try:
            intent = IntentCategory(raw_intent)
        except ValueError:
            intent = IntentCategory.OTHER
        confidence = float(data.get("confidence", 0.3))
        confidence = max(0.0, min(1.0, confidence))
        reasoning = str(data.get("reasoning") or "")
        return cls(intent=intent, confidence=confidence, reasoning=reasoning)


@dataclass
class EmailAnalysis:
    """Analyse complète d'un email (classification + priorité).

    Validation:
    - email_id: non vide
    """
    email_id: str
    classification: Classification
    priority: Priority
    analyzed_at: str = ""

    def __post_init__(self):
        # Validation email_id
        if not self.email_id or not self.email_id.strip():
            raise EmptyValueError("email_id", "EmailAnalysis email_id cannot be empty")

        if not self.analyzed_at:
            self.analyzed_at = datetime.now().isoformat()

    def should_process(self) -> bool:
        """Indique si l'email doit être traité (pas spam, newsletter, etc.)."""
        return not self.classification.should_skip()

    def to_dict(self) -> dict:
        """Convertit en dictionnaire pour sérialisation."""
        return {
            "email_id": self.email_id,
            "classification": self.classification.to_dict(),
            "priority": self.priority.to_dict(),
            "analyzed_at": self.analyzed_at,
        }
