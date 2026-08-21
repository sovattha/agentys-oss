# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Interface abstraite pour les providers LLM.

Permet de supporter plusieurs backends (Claude, Ollama, etc.)
avec une API unifiée.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LLMResponse:
    """Réponse standardisée d'un LLM."""
    content: str
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    # Mirror of the canonical field on app.domain.ports.llm_port.LLMResponse
    # (kept in sync to avoid a structural drift if a future caller imports
    # this legacy module — see grep at audit-2026-05-04).
    stop_reason: str = ""


class LLMProvider(ABC):
    """Interface abstraite pour un provider LLM."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Nom du provider (ex: 'claude', 'ollama')."""
        pass

    @property
    @abstractmethod
    def model(self) -> str:
        """Modèle utilisé."""
        pass

    @abstractmethod
    def complete(
        self,
        system: str,
        user: str,
        max_tokens: int = 1024
    ) -> LLMResponse:
        """
        Génère une complétion.

        Args:
            system: Le prompt système.
            user: Le message utilisateur.
            max_tokens: Nombre maximum de tokens en sortie.

        Returns:
            LLMResponse avec le contenu et les métadonnées.
        """
        pass

    def is_available(self) -> bool:
        """Vérifie si le provider est disponible et configuré."""
        return True
