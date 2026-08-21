# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Port ContactAnalyzer - Interface pour l'analyse du contexte de contact.

Ce port définit le contrat pour analyser l'historique des échanges
avec un contact spécifique et en extraire le contexte relationnel.
"""

from abc import ABC, abstractmethod
from typing import Sequence

from app.domain.entities import ContactContext
from app.db.models.email import Email


class ContactAnalyzerPort(ABC):
    """
    Interface abstraite pour l'analyse du contexte de contact.

    Tout adapter d'analyse de contact doit implémenter cette interface.
    L'implémentation principale utilise Claude API pour l'analyse.
    """

    @abstractmethod
    async def analyze(
        self,
        contact_email: str,
        account_id: int,
        emails: Sequence[Email],
        timeout_seconds: int = 30,
    ) -> ContactContext:
        """
        Analyse l'historique des échanges avec un contact.

        Cette méthode analyse les emails fournis pour extraire:
        - Le ton dominant de la relation
        - Les sujets récurrents
        - La force de la relation

        Args:
            contact_email: Adresse email du contact à analyser.
            account_id: ID du compte email de l'utilisateur.
            emails: Séquence d'emails échangés avec le contact.
            timeout_seconds: Timeout en secondes (défaut: 30).

        Returns:
            ContactContext avec le résultat de l'analyse.
            Si timeout, retourne un contexte partiel avec is_complete=False.

        Raises:
            ValueError: Si contact_email est vide ou invalide.
        """
        pass

    def is_available(self) -> bool:
        """Vérifie si l'analyzer est disponible et configuré."""
        return True
