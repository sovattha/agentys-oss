# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Adapter d'analyse complète d'emails basé sur LLM.

Implémente EmailAnalyzerPort en combinant classification et priorisation.

Deux chemins :
  1. Legacy 2-call : `classifier` + `prioritizer` séparés (2 appels LLM).
  2. P0.1 unifié  : `unified` (UnifiedEmailAnalyzerAgent, 1 appel LLM).
     Quand le champ ``unified`` est injecté, il prend la précédence et
     fusionne classification + intent + prio + tasks dans un seul appel.

Issue #684 : activer le chemin unifié par défaut côté Container.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from app.domain.entities import (
    Classification,
    Email,
    EmailAnalysis,
    EmailCategory,
    Priority,
)
from app.domain.ports import ClassifierPort, EmailAnalyzerPort, PrioritizationPort

logger = logging.getLogger(__name__)


@dataclass
class LLMEmailAnalyzerAdapter(EmailAnalyzerPort):
    """
    Adapter d'analyse combinant classification et priorisation.

    Mode "unifié" (issue #684) :
        Si ``unified`` (UnifiedEmailAnalyzerAgent) est injecté, l'adapter
        fait 1 seul appel LLM qui produit category + priority dans la
        même réponse. C'est le chemin par défaut câblé par Container.

    Mode "legacy 2-call" :
        Si ``unified`` est None, l'adapter exécute classifier + prioritizer
        séquentiellement (2 appels LLM). Conservé pour rétro-compat avec
        les tests existants qui injectent les deux ports séparément.
    """
    classifier: Optional[ClassifierPort] = None
    prioritizer: Optional[PrioritizationPort] = None
    unified: Optional[Any] = None  # app.agents.UnifiedEmailAnalyzerAgent

    def analyze(self, email: Email, is_cc: bool = False) -> EmailAnalysis:
        """
        Effectue une analyse complète de l'email.

        Args:
            email: L'email à analyser.
            is_cc: True si l'utilisateur est en copie.

        Returns:
            EmailAnalysis avec classification et priorité.
        """
        if self.unified is not None:
            return self._analyze_unified(email, is_cc)

        if self.classifier is None or self.prioritizer is None:
            raise ValueError(
                "LLMEmailAnalyzerAdapter requires either `unified` "
                "or both `classifier` and `prioritizer` to be set"
            )

        # Legacy 2-call path
        classification = self.classifier.classify(email, is_cc)
        priority = self.prioritizer.analyze(email)

        return EmailAnalysis(
            email_id=email.id,
            classification=classification,
            priority=priority,
        )

    def _analyze_unified(self, email: Email, is_cc: bool) -> EmailAnalysis:
        """
        Chemin unifié (1 appel LLM via UnifiedEmailAnalyzerAgent).

        On reconstruit Classification + Priority à partir du dict sanitizé
        retourné par l'agent. Sur erreur LLM ou parse, l'agent renvoie
        ses valeurs par défaut (NORMAL/50/50/0/None/50) — la construction
        de Classification/Priority ne lève donc jamais.
        """
        email_content = f"Sujet: {email.subject}\nCorps: {email.body[:2000]}"
        result = self.unified.analyze(
            email_content=email_content,
            sender=email.sender,
            is_cc=is_cc,
        )

        classification = self._build_classification(result)
        priority = self._build_priority(result)

        return EmailAnalysis(
            email_id=email.id,
            classification=classification,
            priority=priority,
        )

    @staticmethod
    def _build_classification(result: dict) -> Classification:
        """Construit Classification depuis le dict unifié.

        Valeurs hors vocabulaire fermé tombent sur NORMAL / 0.5 — c'est
        le comportement aussi de LLMClassifierAdapter._parse_response.
        """
        raw_cat = str(result.get("category") or "NORMAL").upper()
        try:
            category = EmailCategory(raw_cat)
        except ValueError:
            category = EmailCategory.NORMAL

        confidence = result.get("category_confidence", 0.5)
        try:
            confidence = max(0.0, min(1.0, float(confidence)))
        except (TypeError, ValueError):
            confidence = 0.5

        return Classification(
            category=category,
            confidence=confidence,
            reason="unified analyzer",
        )

    @staticmethod
    def _build_priority(result: dict) -> Priority:
        """Construit Priority depuis le dict unifié.

        Le champ ``deadline`` du LLM peut être non-ISO ("demain", "next week").
        Priority.__post_init__ valide le format ISO et lèverait une
        InvalidFormatError — on filtre en amont.
        """
        urgency = int(result.get("urgency", 50))
        urgency = max(0, min(100, urgency))

        vip = int(result.get("vip", 50))
        vip = max(0, min(100, vip))

        try:
            sentiment = float(result.get("sentiment", 0))
        except (TypeError, ValueError):
            sentiment = 0.0
        sentiment = max(-1.0, min(1.0, sentiment))

        priority_score = int(result.get("priority_score", 50))
        priority_score = max(0, min(100, priority_score))

        deadline = result.get("deadline")
        if deadline:
            try:
                datetime.fromisoformat(str(deadline).replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                logger.debug(
                    "UnifiedEmailAnalyzer returned non-ISO deadline %r, "
                    "dropping to None",
                    deadline,
                )
                deadline = None
        else:
            deadline = None

        return Priority(
            urgency=urgency,
            vip=vip,
            sentiment=sentiment,
            deadline=deadline,
            priority_score=priority_score,
        )
