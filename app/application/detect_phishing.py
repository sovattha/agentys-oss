# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Use Case : Détection de phishing dans un email."""

from dataclasses import dataclass

from app.domain.entities import PhishingResult
from app.domain.services import PhishingDetector
from app.interfaces.email_provider import StandardEmail


@dataclass
class DetectPhishingUseCase:
    """Use case pour détecter le phishing dans un email."""

    detector: PhishingDetector

    def execute(self, email: StandardEmail) -> PhishingResult:
        """
        Analyse un email pour détecter le phishing.

        Args:
            email: L'email à analyser.

        Returns:
            PhishingResult avec le score de risque et les URLs suspectes.
        """
        return self.detector.analyze_email(
            subject=email.subject,
            body=email.body
        )
