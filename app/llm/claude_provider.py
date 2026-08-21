# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Provider LLM pour Claude (Anthropic).
"""

import os
from .base import LLMProvider, LLMResponse


class ClaudeProvider(LLMProvider):
    """Provider utilisant l'API Claude d'Anthropic."""

    def __init__(self, model: str = None, api_key: str = None):
        """
        Initialise le provider Claude.

        Args:
            model: Le modèle à utiliser (défaut: claude-sonnet-4-6)
            api_key: Clé API Anthropic (défaut: ANTHROPIC_API_KEY)
        """
        from anthropic import Anthropic

        self._model = model or os.getenv("LLM_MODEL", "claude-sonnet-4-6")
        self._api_key = api_key or os.getenv("ANTHROPIC_API_KEY")

        if not self._api_key:
            raise ValueError("ANTHROPIC_API_KEY requise pour le provider Claude")

        # Audit HIGH-6 (2026-04-25): explicit 60 s timeout. SDK default 600 s.
        self._client = Anthropic(api_key=self._api_key, timeout=60.0)

    @property
    def name(self) -> str:
        return "claude"

    @property
    def model(self) -> str:
        return self._model

    def complete(
        self,
        system: str,
        user: str,
        max_tokens: int = 1024
    ) -> LLMResponse:
        """Génère une complétion via l'API Claude."""
        response = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}]
        )

        if not response.content or not hasattr(response.content[0], "text"):
            return LLMResponse(
                content="",
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                model=self._model
            )

        return LLMResponse(
            content=response.content[0].text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=self._model
        )

    def is_available(self) -> bool:
        """Vérifie si la clé API est configurée."""
        return bool(self._api_key)
