# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Use Case : Analyse de l'historique des échanges avec un contact.

Ce use case orchestre la récupération des emails et l'analyse
du contexte relationnel avec un contact spécifique.
"""

import logging
import time
from dataclasses import dataclass

from app.db.repositories.email_repository import EmailRepository
from app.domain.entities import ContactContext
from app.domain.ports import ContactAnalyzerPort

logger = logging.getLogger(__name__)

# Constants
DEFAULT_EMAIL_LIMIT = 20
DEFAULT_TIMEOUT_SECONDS = 30


@dataclass
class AnalyzeContactHistoryUseCase:
    """
    Use case pour analyser l'historique des échanges avec un contact.

    Ce use case:
    1. Récupère les N derniers emails avec le contact
    2. Délègue l'analyse au ContactAnalyzerPort
    3. Retourne le ContactContext résultant

    Attributes:
        email_repository: Repository pour accéder aux emails.
        contact_analyzer: Adapter pour l'analyse du contexte.
    """
    email_repository: EmailRepository
    contact_analyzer: ContactAnalyzerPort

    async def execute(
        self,
        contact_email: str,
        account_id: int,
        limit: int = DEFAULT_EMAIL_LIMIT,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> ContactContext:
        """
        Analyse l'historique des échanges avec un contact.

        Args:
            contact_email: Adresse email du contact à analyser.
            account_id: ID du compte email de l'utilisateur.
            limit: Nombre maximum d'emails à analyser (défaut: 20).
            timeout_seconds: Timeout en secondes (défaut: 30).

        Returns:
            ContactContext avec le résultat de l'analyse.

        Raises:
            ValueError: Si contact_email est vide ou invalide.
        """
        start_time = time.time()

        # Validation
        if not contact_email or not contact_email.strip():
            raise ValueError("contact_email cannot be empty")
        if "@" not in contact_email:
            raise ValueError("contact_email must be a valid email address")
        if limit <= 0:
            raise ValueError("limit must be positive")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

        logger.info(
            f"Analyzing contact history for {contact_email} "
            f"(account_id={account_id}, limit={limit})"
        )

        # Récupérer les emails avec le contact
        emails = self.email_repository.get_with_contact(
            contact_email=contact_email,
            account_id=account_id,
            limit=limit,
        )

        email_count = len(emails)
        logger.info(f"Found {email_count} emails with contact {contact_email}")

        # Si aucun email, retourner un contexte vide
        if email_count == 0:
            elapsed_ms = int((time.time() - start_time) * 1000)
            return ContactContext.create_incomplete(
                contact_email=contact_email,
                account_id=account_id,
                email_count=0,
                analysis_duration_ms=elapsed_ms,
            )

        # Déléguer l'analyse à l'adapter
        context = await self.contact_analyzer.analyze(
            contact_email=contact_email,
            account_id=account_id,
            emails=emails,
            timeout_seconds=timeout_seconds,
        )

        elapsed_ms = int((time.time() - start_time) * 1000)
        logger.info(
            f"Contact analysis completed in {elapsed_ms}ms "
            f"(complete={context.is_complete})"
        )

        return context
