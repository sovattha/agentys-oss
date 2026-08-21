# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Ports pour la classification et la priorisation des emails.

Ces ports définissent les contrats pour les services d'analyse d'emails.
"""

from abc import ABC, abstractmethod

from app.domain.entities import Email, Classification, Priority, EmailAnalysis


class ClassifierPort(ABC):
    """
    Interface abstraite pour un service de classification d'emails.

    Tout adapter de classification (LLM-based, rule-based, ML-based...)
    doit implémenter cette interface.
    """

    @abstractmethod
    def classify(self, email: Email, is_cc: bool = False) -> Classification:
        """
        Classifie un email dans une catégorie.

        Args:
            email: L'email à classifier.
            is_cc: True si l'utilisateur est en copie (pas destinataire direct).

        Returns:
            Classification avec la catégorie, confiance et raison.
        """
        pass


class PrioritizationPort(ABC):
    """
    Interface abstraite pour un service de priorisation d'emails.

    Tout adapter de priorisation (LLM-based, rule-based, ML-based...)
    doit implémenter cette interface.
    """

    @abstractmethod
    def analyze(self, email: Email) -> Priority:
        """
        Analyse la priorité d'un email.

        Args:
            email: L'email à analyser.

        Returns:
            Priority avec les scores d'urgence, VIP, sentiment et priorité globale.
        """
        pass


class EmailAnalyzerPort(ABC):
    """
    Interface combinée pour l'analyse complète d'un email.

    Cette interface combine classification et priorisation en une seule opération.
    """

    @abstractmethod
    def analyze(self, email: Email, is_cc: bool = False) -> EmailAnalysis:
        """
        Effectue une analyse complète de l'email (classification + priorité).

        Args:
            email: L'email à analyser.
            is_cc: True si l'utilisateur est en copie.

        Returns:
            EmailAnalysis avec classification et priorité.
        """
        pass
