# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Entités pour la transparence du contexte IA.

Ces entités représentent les données de transparence affichées à l'utilisateur
pour comprendre quel contexte a été utilisé pour générer un brouillon.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional


# Types de relation valides
VALID_RELATIONSHIP_TYPES = {
    "colleague", "client", "friend", "manager", "vendor", "unknown"
}

# Fréquences de communication valides
VALID_COMMUNICATION_FREQUENCIES = {
    "daily", "weekly", "monthly", "sporadic"
}


@dataclass
class AnalyzedEmailSummary:
    """Résumé d'un email analysé pour le contexte.

    Contient les informations essentielles d'un email utilisé
    dans l'analyse de contexte.

    Attributes:
        email_id: Identifiant unique de l'email.
        subject: Sujet de l'email.
        sender: Adresse email de l'expéditeur.
        date: Date de l'email.
        relevant_excerpts: Extraits pertinents de l'email.
        relevance_score: Score de pertinence (0.0-1.0).
    """
    email_id: str
    subject: str
    sender: str
    date: datetime
    relevant_excerpts: List[str]
    relevance_score: float

    def __post_init__(self):
        """Validation après initialisation."""
        if not self.email_id or not self.email_id.strip():
            raise ValueError("email_id cannot be empty")
        if not self.sender or "@" not in self.sender:
            raise ValueError("sender must be a valid email address")
        if not 0.0 <= self.relevance_score <= 1.0:
            raise ValueError("relevance_score must be between 0.0 and 1.0")

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour sérialisation JSON."""
        return {
            "email_id": self.email_id,
            "subject": self.subject,
            "sender": self.sender,
            "date": self.date.isoformat(),
            "relevant_excerpts": self.relevant_excerpts,
            "relevance_score": self.relevance_score,
        }


@dataclass
class StyleProfileSummary:
    """Résumé du profil de style d'écriture.

    Contient un aperçu du profil de style de l'utilisateur
    pour affichage dans le panneau de transparence.

    Attributes:
        formality_level: Niveau de formalité (formal, casual, mixed).
        characteristic_phrases: Phrases caractéristiques du style.
        greeting_style: Style de salutation préféré.
        closing_style: Style de formule de clôture préféré.
        confidence: Score de confiance du profil (0.0-1.0).
    """
    formality_level: str
    characteristic_phrases: List[str]
    greeting_style: str
    closing_style: str
    confidence: float

    def __post_init__(self):
        """Validation après initialisation."""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour sérialisation JSON."""
        return {
            "formality_level": self.formality_level,
            "characteristic_phrases": self.characteristic_phrases,
            "greeting_style": self.greeting_style,
            "closing_style": self.closing_style,
            "confidence": self.confidence,
        }


@dataclass
class RelationshipSummary:
    """Résumé de la relation détectée avec un contact.

    Contient un aperçu de la relation pour affichage
    dans le panneau de transparence.

    Attributes:
        relationship_type: Type de relation (colleague, client, etc.).
        confidence: Score de confiance de la détection (0.0-1.0).
        communication_frequency: Fréquence de communication.
    """
    relationship_type: str
    confidence: float
    communication_frequency: str

    def __post_init__(self):
        """Validation après initialisation."""
        if self.relationship_type not in VALID_RELATIONSHIP_TYPES:
            raise ValueError(
                f"relationship_type must be one of: {VALID_RELATIONSHIP_TYPES}"
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        if self.communication_frequency not in VALID_COMMUNICATION_FREQUENCIES:
            raise ValueError(
                f"communication_frequency must be one of: {VALID_COMMUNICATION_FREQUENCIES}"
            )

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour sérialisation JSON."""
        return {
            "relationship_type": self.relationship_type,
            "confidence": self.confidence,
            "communication_frequency": self.communication_frequency,
        }


@dataclass
class ContextTransparencyData:
    """Données de transparence du contexte IA.

    Contient toutes les informations sur le contexte utilisé
    pour générer un brouillon, permettant à l'utilisateur de
    comprendre et valider les choix de l'IA.

    Attributes:
        session_id: Identifiant de la session de génération.
        contact_email: Email du contact concerné.
        analyzed_emails: Liste des emails analysés.
        style_profile: Résumé du profil de style (optionnel).
        relationship: Résumé de la relation détectée (optionnel).
        analysis_timestamp: Timestamp de l'analyse.
        total_context_tokens: Nombre total de tokens utilisés.
    """
    session_id: str
    contact_email: str
    analyzed_emails: List[AnalyzedEmailSummary]
    style_profile: Optional[StyleProfileSummary]
    relationship: Optional[RelationshipSummary]
    analysis_timestamp: datetime
    total_context_tokens: int

    def __post_init__(self):
        """Validation après initialisation."""
        if not self.session_id or not self.session_id.strip():
            raise ValueError("session_id cannot be empty")
        if not self.contact_email or "@" not in self.contact_email:
            raise ValueError("contact_email must be a valid email address")
        if self.total_context_tokens < 0:
            raise ValueError("total_context_tokens must be non-negative")

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour sérialisation JSON."""
        return {
            "session_id": self.session_id,
            "contact_email": self.contact_email,
            "analyzed_emails": [e.to_dict() for e in self.analyzed_emails],
            "style_profile": self.style_profile.to_dict() if self.style_profile else None,
            "relationship": self.relationship.to_dict() if self.relationship else None,
            "analysis_timestamp": self.analysis_timestamp.isoformat(),
            "total_context_tokens": self.total_context_tokens,
        }
