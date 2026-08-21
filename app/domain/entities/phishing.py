# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Entités pour la détection de phishing."""

from dataclasses import dataclass
from typing import List

from app.domain.exceptions import InvalidBoundsError


@dataclass
class SuspiciousUrl:
    """URL suspecte détectée avec ses raisons."""
    url: str
    reasons: List[str]
    risk_score: int

    def __post_init__(self):
        if not 0 <= self.risk_score <= 100:
            raise InvalidBoundsError("risk_score", self.risk_score, 0, 100)

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "reasons": self.reasons,
            "risk_score": self.risk_score
        }


@dataclass
class PhishingResult:
    """Résultat complet de l'analyse de phishing."""
    risk_score: int
    suspicious_urls: List[SuspiciousUrl]
    is_phishing: bool
    analysis_summary: str

    def __post_init__(self):
        if not 0 <= self.risk_score <= 100:
            raise InvalidBoundsError("risk_score", self.risk_score, 0, 100)

    @classmethod
    def default(cls) -> "PhishingResult":
        return cls(
            risk_score=0,
            suspicious_urls=[],
            is_phishing=False,
            analysis_summary="No analysis performed"
        )

    def to_dict(self) -> dict:
        return {
            "risk_score": self.risk_score,
            "suspicious_urls": [url.to_dict() for url in self.suspicious_urls],
            "is_phishing": self.is_phishing,
            "analysis_summary": self.analysis_summary
        }
