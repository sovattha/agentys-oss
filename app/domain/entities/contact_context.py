# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Entités pour l'analyse du contexte de contact.

Ces entités représentent le résultat de l'analyse de l'historique
des échanges avec un contact spécifique.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class DominantTone(str, Enum):
    """Ton dominant d'une relation email."""
    FORMAL = "formal"
    FRIENDLY = "friendly"
    PROFESSIONAL = "professional"
    CASUAL = "casual"


@dataclass
class TopicInfo:
    """Information sur un sujet récurrent dans les échanges.

    Attributes:
        topic: Le sujet identifié.
        frequency: Nombre d'occurrences dans les emails analysés.
        last_mentioned: Date de la dernière mention (optionnel).
    """
    topic: str
    frequency: int
    last_mentioned: Optional[datetime] = None

    def __post_init__(self):
        """Validation après initialisation."""
        if not self.topic or not self.topic.strip():
            raise ValueError("topic cannot be empty")
        if self.frequency < 0:
            raise ValueError("frequency must be non-negative")

    def to_dict(self) -> dict:
        """Convertit en dictionnaire pour sérialisation JSON."""
        return {
            "topic": self.topic,
            "frequency": self.frequency,
            "last_mentioned": self.last_mentioned.isoformat() if self.last_mentioned else None,
        }


@dataclass
class ContactContext:
    """Contexte analysé d'une relation avec un contact.

    Représente le résultat de l'analyse de l'historique des échanges
    avec un contact spécifique, incluant le ton, les sujets récurrents,
    et les métadonnées de la relation.

    Attributes:
        contact_email: Adresse email du contact analysé.
        account_id: ID du compte email utilisateur.
        email_count: Nombre d'emails analysés.
        dominant_tone: Ton dominant de la relation.
        tone_confidence: Score de confiance (0.0-1.0).
        recurring_topics: Liste des sujets récurrents.
        relationship_strength: Force de la relation (0-100).
        first_interaction: Date du premier échange.
        last_interaction: Date du dernier échange.
        analysis_duration_ms: Durée de l'analyse en millisecondes.
        is_complete: True si l'analyse est complète, False si timeout/partielle.
        analyzed_at: Timestamp de l'analyse.
    """
    contact_email: str
    account_id: int
    email_count: int
    dominant_tone: DominantTone
    tone_confidence: float
    recurring_topics: list[TopicInfo] = field(default_factory=list)
    relationship_strength: int = 0
    first_interaction: Optional[datetime] = None
    last_interaction: Optional[datetime] = None
    analysis_duration_ms: int = 0
    is_complete: bool = True
    analyzed_at: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self):
        """Validation après initialisation."""
        if not self.contact_email or not self.contact_email.strip():
            raise ValueError("contact_email cannot be empty")
        if "@" not in self.contact_email:
            raise ValueError("contact_email must be a valid email address")
        if self.email_count < 0:
            raise ValueError("email_count must be non-negative")
        if not 0.0 <= self.tone_confidence <= 1.0:
            raise ValueError("tone_confidence must be between 0.0 and 1.0")
        if not 0 <= self.relationship_strength <= 100:
            raise ValueError("relationship_strength must be between 0 and 100")
        if self.analysis_duration_ms < 0:
            raise ValueError("analysis_duration_ms must be non-negative")
        # Convert string tone to enum if needed
        if isinstance(self.dominant_tone, str):
            self.dominant_tone = DominantTone(self.dominant_tone)

    def to_dict(self) -> dict:
        """Convertit en dictionnaire pour sérialisation JSON."""
        return {
            "contact_email": self.contact_email,
            "account_id": self.account_id,
            "email_count": self.email_count,
            "dominant_tone": self.dominant_tone.value,
            "tone_confidence": self.tone_confidence,
            "recurring_topics": [t.to_dict() for t in self.recurring_topics],
            "relationship_strength": self.relationship_strength,
            "first_interaction": self.first_interaction.isoformat() if self.first_interaction else None,
            "last_interaction": self.last_interaction.isoformat() if self.last_interaction else None,
            "analysis_duration_ms": self.analysis_duration_ms,
            "is_complete": self.is_complete,
            "analyzed_at": self.analyzed_at.isoformat(),
        }

    @classmethod
    def create_incomplete(
        cls,
        contact_email: str,
        account_id: int,
        email_count: int,
        analysis_duration_ms: int,
    ) -> "ContactContext":
        """Crée un contexte partiel suite à un timeout.

        Args:
            contact_email: Adresse email du contact.
            account_id: ID du compte email.
            email_count: Nombre d'emails qui ont pu être analysés.
            analysis_duration_ms: Durée de l'analyse avant timeout.

        Returns:
            ContactContext avec is_complete=False et valeurs par défaut.
        """
        return cls(
            contact_email=contact_email,
            account_id=account_id,
            email_count=email_count,
            dominant_tone=DominantTone.PROFESSIONAL,  # Valeur par défaut sûre
            tone_confidence=0.0,
            recurring_topics=[],
            relationship_strength=0,
            analysis_duration_ms=analysis_duration_ms,
            is_complete=False,
        )
