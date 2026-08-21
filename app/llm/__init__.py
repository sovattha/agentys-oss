# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Module LLM - Abstraction multi-providers.

Supporte :
- Claude (Anthropic) : Nécessite ANTHROPIC_API_KEY
- Ollama : Modèles locaux, pas de clé API requise

Configuration via variables d'environnement :
- LLM_PROVIDER : 'claude' ou 'ollama' (défaut: claude)
- LLM_MODEL : Modèle à utiliser (ex: mixtral:latest, claude-sonnet-4-6)
- OLLAMA_BASE_URL : URL Ollama (défaut: http://localhost:11434)
"""

from .base import LLMProvider, LLMResponse
from .claude_provider import ClaudeProvider
from .ollama_provider import OllamaProvider
from .factory import get_llm_provider, is_api_key_required

__all__ = [
    "LLMProvider",
    "LLMResponse",
    "ClaudeProvider",
    "OllamaProvider",
    "get_llm_provider",
    "is_api_key_required",
]
