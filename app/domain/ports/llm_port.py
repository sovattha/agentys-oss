# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Port LLM - Interface pour les providers de modèles de langage.

Ce port définit le contrat que tout adapter LLM doit implémenter,
qu'il s'agisse de Claude, Ollama, OpenAI, ou autre.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Sequence, Union


@dataclass(frozen=True)
class SystemSegment:
    """A single segment of a multi-block system prompt.

    Anthropic's `system` field accepts a list of content blocks, each of
    which may carry a `cache_control: {type: "ephemeral"}` marker. The
    cache key is the prefix from the start of the array up to (and
    including) any marked block — so multiple markers split the prompt
    into independently-cacheable prefixes.

    Use case: a Drafter prompt has a stable "knowledge_base" segment + a
    per-account "voice profile" + a per-email "instructions" segment. With
    one cache marker (current behavior) any change anywhere invalidates
    the whole prefix. With three markers the unchanged prefixes still hit
    cache.

    Anthropic limits the number of cache breakpoints to 4 per request.
    The adapter validates this; callers can mark up to 4 segments as
    `cacheable=True`.

    `cacheable=False` segments are still sent (they're part of the
    prompt) but don't get a marker — the cache prefix simply ends at
    whichever earlier segment was the last cacheable one.
    """
    text: str
    cacheable: bool = True


# Type alias used by complete()'s `system` parameter.
# - `str` → single block (legacy / backward-compat path)
# - `Sequence[SystemSegment]` → multi-block path
SystemPrompt = Union[str, Sequence[SystemSegment]]


@dataclass
class LLMResponse:
    """Réponse standardisée d'un LLM.

    Les champs `cache_*` sont peuplés par les providers qui supportent le
    prompt caching (Claude). `input_tokens` représente uniquement les tokens
    facturés au tarif input plein — les tokens lus depuis le cache ne sont
    PAS inclus dedans (ils sont comptés séparément à 0.1× le prix input).
    """
    content: str
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    # Provider-native stop reason. Anthropic emits "end_turn" (normal),
    # "max_tokens" (truncated), "stop_sequence", or "tool_use". Adapters
    # that can't report this (Ollama legacy paths) leave it empty.
    stop_reason: str = ""
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    usage_recorded: bool = False


@dataclass
class LLMStreamChunk:
    """Chunk de réponse streaming d'un LLM."""
    text: str
    input_tokens: int = 0  # Disponible sur le premier chunk
    output_tokens_so_far: int = 0
    is_final: bool = False
    model: str = ""
    cache_read_input_tokens: int = 0  # Disponible sur le premier chunk
    cache_creation_input_tokens: int = 0  # Disponible sur le premier chunk
    usage_recorded: bool = False
    # F-03 (audit 2026-05-14): provider-native stop reason, only meaningful
    # on the FINAL chunk (is_final=True). Anthropic emits "end_turn" (normal),
    # "max_tokens" (truncated), "stop_sequence", "tool_use". Defaults to
    # None for adapters / paths that don't populate it (Ollama legacy,
    # mock paths). Consumers MUST treat None as "unknown, assume not
    # truncated" to stay backward-compat with adapters that didn't carry
    # the field pre-fix. The compose-streaming truncation contract
    # (`_compose_stream_bg`) reads this to set `truncated: true` on the
    # `draft_complete` WS event so the frontend can warn instead of
    # silently rendering a half-word reply.
    stop_reason: str | None = None


class LLMPort(ABC):
    """
    Interface abstraite pour un provider LLM.

    Tout adapter LLM (Claude, Ollama, OpenAI...) doit implémenter cette interface.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Nom du provider (ex: 'claude', 'ollama')."""
        pass

    @property
    @abstractmethod
    def model(self) -> str:
        """Identifiant du modèle utilisé."""
        pass

    @abstractmethod
    def complete(
        self,
        system: "SystemPrompt",
        user: str,
        max_tokens: int = 1024,
        temperature: float | None = None,
    ) -> LLMResponse:
        """
        Génère une complétion.

        Args:
            system: Le prompt système. Soit `str` (un seul bloc cacheable)
                soit `Sequence[SystemSegment]` (multi-block, jusqu'à
                4 cache breakpoints — Anthropic only).
            user: Le message utilisateur.
            max_tokens: Nombre maximum de tokens en sortie.
            temperature: Température de sampling (0.0-1.0). None = défaut du provider.

        Returns:
            LLMResponse avec le contenu et les métadonnées.
        """
        pass

    def stream(
        self,
        system: "SystemPrompt",
        user: str,
        max_tokens: int = 1024,
        temperature: float | None = None,
    ):
        """
        Génère une complétion en streaming.

        Cette méthode est optionnelle. L'implémentation par défaut
        fait un fallback vers complete() en retournant un seul chunk.

        Args:
            system: Idem que complete().
            user: Le message utilisateur.
            max_tokens: Nombre maximum de tokens en sortie.

        Yields:
            LLMStreamChunk avec le texte et les métadonnées.
        """
        # Fallback: appel synchrone avec un seul chunk
        response = self.complete(system, user, max_tokens, temperature=temperature)
        yield LLMStreamChunk(
            text=response.content,
            input_tokens=response.input_tokens,
            output_tokens_so_far=response.output_tokens,
            is_final=True,
            model=response.model,
            cache_read_input_tokens=response.cache_read_input_tokens,
            cache_creation_input_tokens=response.cache_creation_input_tokens,
        )

    def is_available(self) -> bool:
        """Vérifie si le provider est disponible et configuré."""
        return True
