# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Entités pour la boucle de feedback sur les éditions utilisateur (#196)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class EditCategory(str, Enum):
    """Classification de la nature d'une édition utilisateur.

    L'analyse est heuristique (pas LLM) pour rester rapide et gratuite.
    Ordre de priorité dans :func:`classify_edit` :
    ``signature_override`` > ``content_addition`` > ``length_adjustment``
    > ``tone_shift`` > ``structure_change`` > ``minor_typo_fix`` > ``other``.
    """

    TONE_SHIFT = "tone_shift"
    LENGTH_ADJUSTMENT = "length_adjustment"
    STRUCTURE_CHANGE = "structure_change"
    CONTENT_ADDITION = "content_addition"
    SIGNATURE_OVERRIDE = "signature_override"
    MINOR_TYPO_FIX = "minor_typo_fix"
    OTHER = "other"


@dataclass(frozen=True)
class EditEvent:
    """Snapshot immuable d'un événement d'édition de draft."""

    draft_id: str
    account_id: int
    category: EditCategory
    magnitude: float  # |final_len - initial_len| / max(initial_len, 1)
    initial_length: int
    final_length: int
    intent: Optional[str] = None
    recipient_email: Optional[str] = None
    original_email_id: Optional[int] = None
    created_at: Optional[datetime] = None

    def __post_init__(self):
        if not self.draft_id or not self.draft_id.strip():
            raise ValueError("draft_id cannot be empty")
        if self.magnitude < 0:
            raise ValueError("magnitude must be >= 0")
        if self.initial_length < 0 or self.final_length < 0:
            raise ValueError("lengths must be >= 0")

    def to_dict(self) -> dict:
        return {
            "draft_id": self.draft_id,
            "account_id": self.account_id,
            "category": self.category.value,
            "magnitude": self.magnitude,
            "initial_length": self.initial_length,
            "final_length": self.final_length,
            "intent": self.intent,
            "recipient_email": self.recipient_email,
            "original_email_id": self.original_email_id,
        }
