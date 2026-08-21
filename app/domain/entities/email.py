# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Entité Email."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List
import re

from app.domain.exceptions import EmptyValueError, InvalidFormatError


# Regex simple pour validation email (RFC 5322 simplifiée)
EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_email_format(email: str, field_name: str) -> None:
    """Valide le format d'une adresse email."""
    if not EMAIL_REGEX.match(email):
        raise InvalidFormatError(
            field=field_name,
            expected_format="email@domain.com",
            actual_value=email
        )


@dataclass
class Email:
    """Représente un email reçu.

    Validation:
    - id: non vide, non None
    - sender: non vide, format email valide
    - subject/body: peuvent être vides
    """
    id: str
    subject: str
    body: str
    sender: str
    recipients: List[str] = field(default_factory=list)
    cc: List[str] = field(default_factory=list)
    received_at: Optional[datetime] = None
    thread_id: Optional[str] = None
    is_read: bool = False

    def __post_init__(self):
        """Validation après initialisation."""
        # Validation id
        if self.id is None:
            raise EmptyValueError("id", "Email id cannot be None")
        if not isinstance(self.id, str):
            raise TypeError(f"id must be a string, got {type(self.id).__name__}")
        if not self.id.strip():
            raise EmptyValueError("id", "Email id cannot be empty")

        # Validation sender
        if not self.sender or not self.sender.strip():
            raise EmptyValueError("sender", "Email sender cannot be empty")
        _validate_email_format(self.sender, "sender")

    @property
    def is_cc_only(self) -> bool:
        """Vérifie si l'utilisateur est uniquement en copie."""
        # Logique simplifiée - à adapter selon le contexte
        return len(self.recipients) == 0 and len(self.cc) > 0

    @property
    def content_for_processing(self) -> str:
        """Retourne le contenu formaté pour le traitement IA."""
        return f"De: {self.sender}\nSujet: {self.subject}\n\n{self.body}"
