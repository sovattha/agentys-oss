# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Adapter pour le comptage des tokens.

Wrappe le TokenUsage existant et implemente TokenCounterPort.
"""

from typing import Dict, Any, List

from app.domain.ports.token_counter_port import TokenCounterPort
from app.domain.entities.token_usage import TokenUsage, MODEL_COSTS


class LegacyTokenCounterAdapter(TokenCounterPort):
    """
    Adapter qui wrappe TokenUsage.

    Implemente TokenCounterPort en utilisant l'entite TokenUsage
    existante du domaine.
    """

    def __init__(self, token_usage: TokenUsage = None):
        """
        Initialise l'adapter.

        Args:
            token_usage: Instance de TokenUsage a utiliser.
                        Si None, cree une nouvelle instance.
        """
        self._usage = token_usage or TokenUsage()
        self._history: List[Dict[str, Any]] = []
        self._by_agent: Dict[str, Dict[str, int]] = {}
        self._by_model: Dict[str, Dict[str, int]] = {}

    # =========================================================================
    # Comptage
    # =========================================================================

    def add(
        self,
        input_tokens: int,
        output_tokens: int,
        model: str = "",
        agent: str = "",
    ) -> None:
        """Ajoute des tokens au compteur."""
        self._usage.add(input_tokens, output_tokens, model)

        # Historique
        self._history.append({
            "input": input_tokens,
            "output": output_tokens,
            "total": input_tokens + output_tokens,
            "model": model,
            "agent": agent,
        })

        # Breakdown par agent
        if agent:
            if agent not in self._by_agent:
                self._by_agent[agent] = {"input": 0, "output": 0, "total": 0}
            self._by_agent[agent]["input"] += input_tokens
            self._by_agent[agent]["output"] += output_tokens
            self._by_agent[agent]["total"] += input_tokens + output_tokens

        # Breakdown par modele
        if model:
            if model not in self._by_model:
                self._by_model[model] = {"input": 0, "output": 0, "total": 0}
            self._by_model[model]["input"] += input_tokens
            self._by_model[model]["output"] += output_tokens
            self._by_model[model]["total"] += input_tokens + output_tokens

    def get_total(self) -> int:
        """Recupere le total des tokens utilises."""
        return self._usage.total

    def get_input_tokens(self) -> int:
        """Recupere le total des tokens en entree."""
        return self._usage.input_tokens

    def get_output_tokens(self) -> int:
        """Recupere le total des tokens en sortie."""
        return self._usage.output_tokens

    # =========================================================================
    # Couts
    # =========================================================================

    def get_cost(self) -> float:
        """Calcule le cout total en dollars."""
        return self._usage.cost

    def get_cost_by_model(self) -> Dict[str, float]:
        """Recupere le cout par modele."""
        costs = {}
        for model, tokens in self._by_model.items():
            model_costs = MODEL_COSTS.get(
                model,
                MODEL_COSTS.get("claude-sonnet-4-6", {"input": 3.0, "output": 15.0})
            )
            cost = (
                tokens["input"] * model_costs["input"] +
                tokens["output"] * model_costs["output"]
            ) / 1_000_000
            costs[model] = round(cost, 4)
        return costs

    # =========================================================================
    # Breakdown
    # =========================================================================

    def get_breakdown(self) -> Dict[str, Any]:
        """Recupere le breakdown complet."""
        return {
            "total": self._usage.total,
            "input": self._usage.input_tokens,
            "output": self._usage.output_tokens,
            "cost": round(self._usage.cost, 4),
            "model": self._usage.model,
            "by_model": dict(self._by_model),
            "by_agent": dict(self._by_agent),
        }

    def get_breakdown_by_agent(self) -> Dict[str, Dict[str, int]]:
        """Recupere le breakdown par agent."""
        return dict(self._by_agent)

    def get_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Recupere l'historique recent des utilisations."""
        return self._history[-limit:]

    # =========================================================================
    # Gestion
    # =========================================================================

    def reset(self) -> None:
        """Remet le compteur a zero."""
        self._usage.reset()
        self._history.clear()
        self._by_agent.clear()
        self._by_model.clear()

    def get_model(self) -> str:
        """Recupere le modele actuel."""
        return self._usage.model

    def set_model(self, model: str) -> None:
        """Definit le modele actuel."""
        self._usage.model = model

    # =========================================================================
    # Compatibilite avec le TokenUsage existant
    # =========================================================================

    @property
    def token_usage(self) -> TokenUsage:
        """Retourne l'instance TokenUsage sous-jacente."""
        return self._usage

    def __str__(self) -> str:
        """Representation textuelle."""
        return str(self._usage)
