# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Adapters LLM."""

import os
from typing import Optional

from app.domain.ports import LLMPort

from .claude_adapter import ClaudeAdapter
from .claude_code_adapter import ClaudeCodeAdapter
from .mock_adapter import MockLLMAdapter
from .ollama_adapter import OllamaAdapter


def get_llm_adapter(provider: Optional[str] = None) -> LLMPort:
    """
    Factory pour obtenir un adapter LLM.

    Args:
        provider: Le provider à utiliser ('claude', 'claude-code', 'ollama').
                  Par défaut, utilise la variable d'environnement LLM_PROVIDER.

    Returns:
        Instance de LLMPort configurée.

    Raises:
        ValueError: Si le provider n'est pas supporté.
    """
    provider = provider or os.getenv("LLM_PROVIDER", "claude")

    if provider == "mock" or os.getenv("AGENTYS_MOCK_LLM", "").lower() in {"1", "true", "yes", "on"}:
        return MockLLMAdapter()
    elif provider == "claude":
        return ClaudeAdapter()
    elif provider == "claude-code":
        return ClaudeCodeAdapter()
    elif provider == "ollama":
        return OllamaAdapter()
    else:
        raise ValueError(f"LLM provider non supporté: {provider}")


__all__ = [
    "ClaudeAdapter",
    "ClaudeCodeAdapter",
    "MockLLMAdapter",
    "OllamaAdapter",
    "get_llm_adapter",
]
