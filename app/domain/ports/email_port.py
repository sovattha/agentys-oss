# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Port Email - Interface pour les providers email.

Ce port définit le contrat que tout adapter email doit implémenter,
qu'il s'agisse de Gmail, Outlook, IMAP/SMTP, ou autre.
"""

from abc import ABC, abstractmethod
from typing import List, Optional

from app.domain.entities import Email


class EmailPort(ABC):
    """
    Interface abstraite pour un provider email.

    Tout adapter email (Gmail, Outlook, IMAP...) doit implémenter cette interface.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Nom du provider (ex: 'gmail', 'outlook')."""
        pass

    @abstractmethod
    def authenticate(self) -> bool:
        """
        Authentifie le provider.

        Returns:
            True si l'authentification réussit.
        """
        pass

    @abstractmethod
    def get_unread_emails(self, limit: int = 10) -> List[Email]:
        """
        Récupère les emails non lus.

        Args:
            limit: Nombre maximum d'emails à récupérer.

        Returns:
            Liste d'objets Email.
        """
        pass

    @abstractmethod
    def create_draft(self, email: Email, reply_content: str) -> Optional[str]:
        """
        Crée un brouillon de réponse.

        Args:
            email: L'email auquel répondre.
            reply_content: Le contenu de la réponse.

        Returns:
            L'identifiant du brouillon créé, ou None en cas d'échec.
        """
        pass

    @abstractmethod
    def mark_as_read(self, email_id: str) -> bool:
        """
        Marque un email comme lu.

        Args:
            email_id: L'identifiant de l'email.

        Returns:
            True si l'opération réussit.
        """
        pass

    def is_available(self) -> bool:
        """Vérifie si le provider est disponible et configuré."""
        return True
