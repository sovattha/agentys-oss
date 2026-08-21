# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Entités pour la détection de données sensibles."""

from dataclasses import dataclass
from typing import List
from enum import Enum

from app.domain.exceptions import InvalidBoundsError


class SensitiveDataType(Enum):
    """Types de données sensibles détectables."""
    FINANCIAL = "financial"
    PERSONAL = "personal"
    COMMERCIAL_SECRET = "commercial"
    CREDENTIAL = "credential"


@dataclass
class SensitiveDataItem:
    """Donnée sensible détectée avec son contexte."""
    data_type: SensitiveDataType
    description: str
    snippet: str

    def to_dict(self) -> dict:
        return {
            "data_type": self.data_type.value,
            "description": self.description,
            "snippet": self.snippet
        }


@dataclass
class SensitiveDataDetection:
    """Résultat complet de l'analyse de données sensibles."""
    is_sensitive: bool
    confidence: float
    detected_items: List[SensitiveDataItem]
    analysis_summary: str

    def __post_init__(self):
        if not 0 <= self.confidence <= 1:
            raise InvalidBoundsError("confidence", self.confidence, 0, 1)

    @classmethod
    def default(cls) -> "SensitiveDataDetection":
        return cls(
            is_sensitive=False,
            confidence=0.0,
            detected_items=[],
            analysis_summary="No analysis performed"
        )

    def to_dict(self) -> dict:
        return {
            "is_sensitive": self.is_sensitive,
            "confidence": self.confidence,
            "detected_items": [item.to_dict() for item in self.detected_items],
            "analysis_summary": self.analysis_summary
        }
