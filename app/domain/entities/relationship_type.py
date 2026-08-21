# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Entités pour la détection du type de relation avec un contact.

Ces entités représentent le type de relation professionnelle ou personnelle
détecté avec un contact, permettant d'ajuster le ton des brouillons.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List


class RelationshipType(str, Enum):
    """Type de relation avec un contact.

    Permet de classifier la nature de la relation pour
    ajuster automatiquement le ton des communications.
    """
    COLLEAGUE = "colleague"        # Collègue de travail
    CLIENT = "client"              # Client/prospect
    FRIEND = "friend"              # Ami personnel
    MANAGER = "manager"            # Manager/supérieur hiérarchique
    VENDOR = "vendor"              # Fournisseur/prestataire
    UNKNOWN = "unknown"            # Non déterminé


class CommunicationFrequency(str, Enum):
    """Fréquence de communication avec un contact."""
    DAILY = "daily"          # Communication quotidienne
    WEEKLY = "weekly"        # Communication hebdomadaire
    MONTHLY = "monthly"      # Communication mensuelle
    SPORADIC = "sporadic"    # Communication irrégulière


@dataclass
class RelationshipDetection:
    """Résultat de la détection de relation avec un contact.

    Contient le type de relation détecté, le score de confiance,
    et les métadonnées sur les patterns de communication.

    Attributes:
        contact_email: Adresse email du contact.
        account_id: ID du compte utilisateur.
        relationship_type: Type de relation détecté.
        confidence: Score de confiance (0.0-1.0).
        communication_frequency: Fréquence des échanges.
        typical_hours: Heures typiques de communication (0-23).
        is_user_override: True si l'utilisateur a corrigé manuellement.
        detected_at: Timestamp de la détection.
    """
    contact_email: str
    account_id: int
    relationship_type: RelationshipType
    confidence: float
    communication_frequency: CommunicationFrequency
    typical_hours: List[int] = field(default_factory=list)
    is_user_override: bool = False
    detected_at: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self):
        """Validation après initialisation."""
        # Validate email
        if not self.contact_email or not self.contact_email.strip():
            raise ValueError("contact_email cannot be empty")
        if "@" not in self.contact_email:
            raise ValueError("contact_email must be a valid email address")

        # Validate confidence
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")

        # Validate typical_hours
        if self.typical_hours:
            for hour in self.typical_hours:
                if not 0 <= hour <= 23:
                    raise ValueError("typical_hours must contain values between 0-23")

        # Convert string to enum if needed
        if isinstance(self.relationship_type, str):
            self.relationship_type = RelationshipType(self.relationship_type)
        if isinstance(self.communication_frequency, str):
            self.communication_frequency = CommunicationFrequency(self.communication_frequency)

    def to_dict(self) -> dict:
        """Convertit en dictionnaire pour sérialisation JSON."""
        return {
            "contact_email": self.contact_email,
            "account_id": self.account_id,
            "relationship_type": self.relationship_type.value,
            "confidence": self.confidence,
            "communication_frequency": self.communication_frequency.value,
            "typical_hours": self.typical_hours,
            "is_user_override": self.is_user_override,
            "detected_at": self.detected_at.isoformat(),
        }
