# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Entités Draft et Critique."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from app.domain.exceptions import InvalidBoundsError


class DraftStatus(Enum):
    """Statut d'un brouillon."""
    PENDING = "pending"
    VALIDATED_V1 = "validated_v1"
    CORRECTED_V2 = "corrected_v2"
    REJECTED = "rejected"


@dataclass
class Draft:
    """Représente un brouillon de réponse.

    Validation:
    - version: >= 1
    """
    content: str
    version: int = 1

    def __post_init__(self):
        """Validation après initialisation."""
        if self.version < 1:
            raise InvalidBoundsError(
                field="version",
                value=self.version,
                min_val=1,
                message=f"Draft version must be >= 1, got {self.version}"
            )

    def __str__(self) -> str:
        return self.content


@dataclass
class Critique:
    """Représente l'évaluation d'un brouillon."""
    raw_response: str
    is_valid: bool
    reason: Optional[str] = None

    @classmethod
    def from_response(cls, response: str) -> "Critique":
        """Parse la réponse du critic agent."""
        response = response.strip()
        is_valid = response.upper().startswith("VALID")
        reason = None if is_valid else response
        return cls(raw_response=response, is_valid=is_valid, reason=reason)

    def __str__(self) -> str:
        return self.raw_response


@dataclass
class ProcessingResult:
    """Résultat du traitement complet d'un email."""
    email_id: str
    draft_v1: Draft
    critique: Critique
    draft_final: Draft
    status: DraftStatus

    @property
    def was_corrected(self) -> bool:
        """Indique si une correction a été nécessaire."""
        return self.status == DraftStatus.CORRECTED_V2
