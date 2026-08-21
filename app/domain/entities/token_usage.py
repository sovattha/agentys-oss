# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Entité TokenUsage pour le suivi de consommation."""

from dataclasses import dataclass
from typing import Dict

from app.domain.exceptions import InvalidBoundsError


# Coûts des modèles ($ par million de tokens)
# Source de vérité : app/infrastructure/cost_manager.py — garder synchronisé
# Note: anciens IDs (Sonnet 4.0, Opus 4.0) conservés pour les usages historiques
# loggés avant la migration vers Sonnet 4.6 / Opus 4.7.
MODEL_COSTS: Dict[str, Dict[str, float]] = {
    # Claude models (prix 2025-2026)
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "claude-opus-4-7": {"input": 15.0, "output": 75.0},
    "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00},
    # Anciens IDs (rétrocompat données historiques)
    "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
    "claude-opus-4-20250514": {"input": 15.0, "output": 75.0},
    "claude-3-5-sonnet-20241022": {"input": 3.0, "output": 15.0},
    "claude-3-5-haiku-20241022": {"input": 0.80, "output": 4.00},
    "claude-3-haiku-20240307": {"input": 0.25, "output": 1.25},
    "claude-3-opus-20240229": {"input": 15.0, "output": 75.0},
    # Ollama models (gratuits)
    "mixtral:latest": {"input": 0.0, "output": 0.0},
    "llama3.3:70b": {"input": 0.0, "output": 0.0},
    "mistral:latest": {"input": 0.0, "output": 0.0},
}


# Multiplicateurs Anthropic prompt caching (cf. https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching).
# Valables pour tous les modèles Claude — appliqués au tarif input du modèle.
_CACHE_READ_PRICE_MULTIPLIER = 0.1   # 90% de remise sur les tokens lus depuis le cache
_CACHE_WRITE_PRICE_MULTIPLIER = 1.25  # 25% de premium sur les tokens écrits dans le cache (5min TTL)


@dataclass
class TokenUsage:
    """Suivi de l'utilisation des tokens.

    Validation:
    - input_tokens: >= 0
    - output_tokens: >= 0
    - cache_read_tokens, cache_creation_tokens: >= 0

    Note pricing: `input_tokens` ne contient PAS les tokens cache_read/cache_creation
    (ils sont comptés séparément avec leur propre tarif). C'est la convention
    Anthropic SDK : `usage.input_tokens` = tokens fresh, `usage.cache_read_input_tokens`
    et `usage.cache_creation_input_tokens` sont distincts.
    """
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0

    def __post_init__(self):
        """Validation après initialisation."""
        if self.input_tokens < 0:
            raise InvalidBoundsError(
                field="input_tokens",
                value=self.input_tokens,
                min_val=0
            )
        if self.output_tokens < 0:
            raise InvalidBoundsError(
                field="output_tokens",
                value=self.output_tokens,
                min_val=0
            )
        if self.cache_read_tokens < 0:
            raise InvalidBoundsError(
                field="cache_read_tokens",
                value=self.cache_read_tokens,
                min_val=0
            )
        if self.cache_creation_tokens < 0:
            raise InvalidBoundsError(
                field="cache_creation_tokens",
                value=self.cache_creation_tokens,
                min_val=0
            )

    # Aliases pour rétrocompatibilité avec TokenCounter
    @property
    def input(self) -> int:
        """Alias pour input_tokens (rétrocompatibilité)."""
        return self.input_tokens

    @property
    def output(self) -> int:
        """Alias pour output_tokens (rétrocompatibilité)."""
        return self.output_tokens

    @property
    def total(self) -> int:
        """Total des tokens utilisés (input + cache + output)."""
        return self.input_tokens + self.output_tokens + self.cache_read_tokens + self.cache_creation_tokens

    @property
    def cache_hit_rate(self) -> float:
        """Ratio cache_read / (input + cache_read + cache_creation), entre 0 et 1.

        Renvoie 0.0 si aucun token input n'a été consommé (évite division par zéro).
        """
        denom = self.input_tokens + self.cache_read_tokens + self.cache_creation_tokens
        if denom <= 0:
            return 0.0
        return self.cache_read_tokens / denom

    @property
    def cost(self) -> float:
        """Coût estimé en dollars (défaut: Sonnet pour modèles inconnus).

        Applique les multiplicateurs Anthropic pour le prompt caching :
        cache_read = 0.1× input, cache_creation = 1.25× input.
        """
        default_costs = MODEL_COSTS.get("claude-sonnet-4-6", {"input": 3.0, "output": 15.0})
        costs = MODEL_COSTS.get(self.model, default_costs)
        input_price = costs["input"]
        return (
            self.input_tokens * input_price
            + self.cache_read_tokens * input_price * _CACHE_READ_PRICE_MULTIPLIER
            + self.cache_creation_tokens * input_price * _CACHE_WRITE_PRICE_MULTIPLIER
            + self.output_tokens * costs["output"]
        ) / 1_000_000

    def add(
        self,
        input_tokens: int,
        output_tokens: int,
        model: str = "",
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
    ) -> None:
        """Ajoute des tokens au compteur.

        Les paramètres `cache_*` sont optionnels (défaut 0) pour rester
        rétrocompatible avec les callers existants.

        Raises:
            InvalidBoundsError: si les valeurs sont négatives
        """
        if input_tokens < 0:
            raise InvalidBoundsError(
                field="input_tokens",
                value=input_tokens,
                min_val=0
            )
        if output_tokens < 0:
            raise InvalidBoundsError(
                field="output_tokens",
                value=output_tokens,
                min_val=0
            )
        if cache_read_tokens < 0:
            raise InvalidBoundsError(
                field="cache_read_tokens",
                value=cache_read_tokens,
                min_val=0
            )
        if cache_creation_tokens < 0:
            raise InvalidBoundsError(
                field="cache_creation_tokens",
                value=cache_creation_tokens,
                min_val=0
            )

        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cache_read_tokens += cache_read_tokens
        self.cache_creation_tokens += cache_creation_tokens
        if model:
            self.model = model

    def reset(self) -> None:
        """Remet le compteur à zéro."""
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_read_tokens = 0
        self.cache_creation_tokens = 0
        self.model = ""

    def __str__(self) -> str:
        cost_str = f"${self.cost:.4f}" if self.cost > 0 else ""

        # Extraire un nom court du modèle
        if self.model:
            parts = self.model.split("-")
            if len(parts) > 1:
                model_short = parts[1]
            else:
                model_short = self.model.split(":")[0]
        else:
            model_short = ""

        parts = [f"Tokens: {self.input_tokens:,}↓ {self.output_tokens:,}↑"]
        if cost_str:
            parts.append(cost_str)
        if model_short:
            parts.append(model_short)

        return f"[{' | '.join(parts)}]"
