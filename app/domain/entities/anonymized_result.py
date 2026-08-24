# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Entité représentant le résultat d'une anonymisation de contenu."""
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.entities.sensitive_data import SensitiveDataDetection


@dataclass(frozen=True)
class AnonymizedResult:
    """Résultat de l'anonymisation avec token de restauration."""

    anonymized_content: str
    encrypted_token: str
    items_anonymized: int
    detection: "SensitiveDataDetection"

    def __post_init__(self):
        if self.items_anonymized < 0:
            raise ValueError("items_anonymized cannot be negative")

    @classmethod
    def empty(
        cls, original_content: str, detection: "SensitiveDataDetection"
    ) -> "AnonymizedResult":
        return cls(
            anonymized_content=original_content,
            encrypted_token="",
            items_anonymized=0,
            detection=detection,
        )

    @property
    def has_redactions(self) -> bool:
        return self.items_anonymized > 0

    def to_dict(self) -> dict:
        return {
            "anonymized_content": self.anonymized_content,
            "encrypted_token": self.encrypted_token,
            "items_anonymized": self.items_anonymized,
            "detection": self.detection.to_dict(),
        }
