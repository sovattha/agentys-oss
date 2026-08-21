# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Factory pour créer le provider LLM approprié.
"""

import os
from .base import LLMProvider
from .claude_provider import ClaudeProvider
from .ollama_provider import OllamaProvider


def get_llm_provider(
    provider_type: str = None,
    model: str = None
) -> LLMProvider:
    """
    Crée et retourne le provider LLM approprié.

    Args:
        provider_type: Type de provider ('claude' ou 'ollama').
                      Défaut: LLM_PROVIDER env var ou 'claude'
        model: Modèle à utiliser. Défaut: LLM_MODEL env var ou défaut du provider

    Returns:
        Instance du provider LLM.

    Raises:
        ValueError: Si le type de provider est inconnu.
    """
    provider_type = provider_type or os.getenv("LLM_PROVIDER", "claude")
    provider_type = provider_type.lower()

    if provider_type == "claude":
        return ClaudeProvider(model=model)

    elif provider_type == "ollama":
        return OllamaProvider(model=model)

    else:
        raise ValueError(
            f"Provider LLM inconnu: {provider_type}. "
            "Valeurs supportées: 'claude', 'ollama'"
        )


def is_api_key_required() -> bool:
    """Vérifie si une clé API est requise selon le provider configuré."""
    provider_type = os.getenv("LLM_PROVIDER", "claude").lower()
    return provider_type == "claude"
