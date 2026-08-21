"""Entités pour l'analyse de contexte IA.

Story 4-7: ContextAnalyzer Agent
Task 1: Créer entity ContextAnalysisResult

Ces dataclasses représentent les entrées et sorties
du ContextAnalyzerAgent.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class RelationshipType(Enum):
    """Type de relation détectée avec un contact.

    Représente la nature de la relation professionnelle ou personnelle
    identifiée à partir de l'historique des échanges.
    """

    COLLEAGUE = "colleague"
    CLIENT = "client"
    MANAGER = "manager"
    FRIEND = "friend"
    UNKNOWN = "unknown"


@dataclass
class ContextAnalysisInput:
    """Entrée pour l'analyse de contexte.

    Contient toutes les données nécessaires pour analyser le contexte
    d'une relation avec un contact spécifique.

    Attributes:
        account_id: ID du compte email utilisateur.
        contact_email: Adresse email du contact à analyser.
        emails: Liste des emails de l'historique (max 20).
        user_instructions: Instructions utilisateur optionnelles.
        session_id: Identifiant de session pour le cache.
    """

    account_id: int
    contact_email: str
    emails: List[Dict[str, Any]]
    user_instructions: Optional[str] = None
    session_id: Optional[str] = None

    def __post_init__(self):
        """Validation après initialisation."""
        if not self.contact_email or not self.contact_email.strip():
            raise ValueError("contact_email cannot be empty")
        if "@" not in self.contact_email:
            raise ValueError("contact_email must be a valid email address")
        if self.account_id <= 0:
            raise ValueError("account_id must be positive")

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour sérialisation JSON."""
        return {
            "account_id": self.account_id,
            "contact_email": self.contact_email,
            "emails": self.emails,
            "user_instructions": self.user_instructions,
            "session_id": self.session_id,
        }


@dataclass
class ContextAnalysisResult:
    """Résultat de l'analyse de contexte.

    Contient les informations extraites de l'analyse de l'historique
    des échanges avec un contact.

    Attributes:
        contact_context: Description du contexte de la relation.
        style_hints: Indices de style de communication détectés.
        relationship_type: Type de relation identifié.
        confidence: Score de confiance de l'analyse (0.0-1.0).
        raw_analysis: Données brutes de l'analyse (optionnel).
        analysis_duration_ms: Durée de l'analyse en ms.
        tokens_used: Nombre de tokens Claude utilisés.
        cached: True si résultat provient du cache.
        analyzed_at: Timestamp de l'analyse.
    """

    contact_context: str
    style_hints: List[str]
    relationship_type: RelationshipType
    confidence: float
    raw_analysis: Optional[Dict[str, Any]] = None
    analysis_duration_ms: int = 0
    tokens_used: int = 0
    cached: bool = False
    analyzed_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def __post_init__(self):
        """Validation après initialisation."""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        if self.analysis_duration_ms < 0:
            raise ValueError("analysis_duration_ms must be non-negative")
        if self.tokens_used < 0:
            raise ValueError("tokens_used must be non-negative")
        # Convert string to enum if needed
        if isinstance(self.relationship_type, str):
            self.relationship_type = RelationshipType(self.relationship_type)

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour sérialisation JSON."""
        return {
            "contact_context": self.contact_context,
            "style_hints": self.style_hints,
            "relationship_type": self.relationship_type.value,
            "confidence": self.confidence,
            "raw_analysis": self.raw_analysis,
            "analysis_duration_ms": self.analysis_duration_ms,
            "tokens_used": self.tokens_used,
            "cached": self.cached,
            "analyzed_at": self.analyzed_at.isoformat(),
        }

    def is_high_confidence(self, threshold: float = 0.7) -> bool:
        """Vérifie si l'analyse a une confiance élevée.

        Args:
            threshold: Seuil de confiance (défaut 0.7).

        Returns:
            True si confidence >= threshold.
        """
        return self.confidence >= threshold

    @classmethod
    def create_fallback(
        cls,
        reason: str,
    ) -> "ContextAnalysisResult":
        """Crée un résultat fallback en cas d'erreur.

        Utilisé quand l'API Claude échoue et qu'on doit
        retourner un résultat minimal.

        Args:
            reason: Raison du fallback (ex: "API timeout").

        Returns:
            ContextAnalysisResult avec valeurs par défaut et confidence=0.
        """
        return cls(
            contact_context="Unable to analyze context",
            style_hints=[],
            relationship_type=RelationshipType.UNKNOWN,
            confidence=0.0,
            raw_analysis={"fallback_reason": reason},
            cached=False,
        )
