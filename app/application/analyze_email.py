# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Use Case : Analyse d'un email (Classification + Priorité).
"""

from dataclasses import dataclass
from typing import Optional

from app.domain.entities import Email, Classification, Priority, EmailAnalysis
from app.domain.ports import ClassifierPort, EmailAnalyzerPort, PrioritizationPort


@dataclass
class ClassifyEmailUseCase:
    """
    Use case pour classifier un email dans une catégorie.

    Ce use case utilise un ClassifierPort pour déterminer
    la catégorie de l'email (URGENT, IMPORTANT, NORMAL, etc.).
    """
    classifier: ClassifierPort

    def execute(self, email: Email, is_cc: bool = False) -> Classification:
        """
        Classifie un email.

        Args:
            email: L'email à classifier.
            is_cc: True si l'utilisateur est en copie.

        Returns:
            Classification avec catégorie, confiance et raison.
        """
        return self.classifier.classify(email, is_cc)


@dataclass
class PrioritizeEmailUseCase:
    """
    Use case pour déterminer la priorité d'un email.

    Ce use case utilise un PrioritizationPort pour analyser
    l'urgence, l'importance de l'expéditeur, le sentiment, etc.
    """
    prioritizer: PrioritizationPort

    def execute(self, email: Email) -> Priority:
        """
        Analyse la priorité d'un email.

        Args:
            email: L'email à analyser.

        Returns:
            Priority avec scores de priorité.
        """
        return self.prioritizer.analyze(email)


@dataclass
class AnalyzeEmailUseCase:
    """
    Use case combiné pour analyser un email (classification + priorité).

    Deux chemins :
      - ``analyzer`` (EmailAnalyzerPort, recommandé issue #684) : 1 appel
        LLM unifié via UnifiedEmailAnalyzerAgent. Câblé par Container.
      - ``classifier`` + ``prioritizer`` (legacy 2 appels) : conservé pour
        rétro-compat avec les tests qui injectent les deux ports séparément.

    Quand ``analyzer`` est fourni, il prend la précédence sur
    classifier+prioritizer.
    """
    classifier: Optional[ClassifierPort] = None
    prioritizer: Optional[PrioritizationPort] = None
    analyzer: Optional[EmailAnalyzerPort] = None

    def execute(self, email: Email, is_cc: bool = False) -> EmailAnalysis:
        """
        Effectue une analyse complète de l'email.

        Args:
            email: L'email à analyser.
            is_cc: True si l'utilisateur est en copie.

        Returns:
            EmailAnalysis avec classification et priorité.
        """
        if self.analyzer is not None:
            return self.analyzer.analyze(email, is_cc)

        if self.classifier is None or self.prioritizer is None:
            raise ValueError(
                "AnalyzeEmailUseCase requires either `analyzer` "
                "or both `classifier` and `prioritizer` to be set"
            )

        classification = self.classifier.classify(email, is_cc)
        priority = self.prioritizer.analyze(email)

        return EmailAnalysis(
            email_id=email.id,
            classification=classification,
            priority=priority
        )
