# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Port pour la détection de données sensibles."""

from abc import ABC, abstractmethod

from app.domain.entities.sensitive_data import SensitiveDataDetection


class SensitiveDataDetectorPort(ABC):
    """Interface abstraite pour un service de détection de données sensibles."""

    @abstractmethod
    def detect(self, draft_content: str, recipient: str) -> SensitiveDataDetection:
        """
        Analyse un brouillon pour détecter les données sensibles.

        Args:
            draft_content: Le contenu du brouillon à analyser.
            recipient: L'adresse email du destinataire.

        Returns:
            SensitiveDataDetection avec le résultat de l'analyse.
        """
        pass
