# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests complets pour LegacyTokenCounterAdapter.

Ces tests vérifient toutes les fonctionnalités de l'adapter:
- Comptage de tokens (input, output, total)
- Calcul des coûts
- Breakdown par agent et par modèle
- Historique des utilisations
- Gestion du modèle
- Compatibilité avec TokenUsage
"""

import pytest
from app.infrastructure.adapters.token_counter_adapter import LegacyTokenCounterAdapter
from app.domain.entities.token_usage import TokenUsage


class TestLegacyTokenCounterAdapterInit:
    """Tests pour l'initialisation de l'adapter."""

    def test_init_without_token_usage(self):
        """Initialisation sans TokenUsage crée une nouvelle instance."""
        adapter = LegacyTokenCounterAdapter()
        assert adapter._usage is not None
        assert isinstance(adapter._usage, TokenUsage)

    def test_init_with_token_usage(self):
        """Initialisation avec un TokenUsage existant le wrappe."""
        usage = TokenUsage()
        usage.add(100, 50, "claude-sonnet-4-20250514")

        adapter = LegacyTokenCounterAdapter(token_usage=usage)
        assert adapter._usage is usage
        assert adapter.get_total() >= 150

    def test_init_creates_empty_history(self):
        """L'historique est vide à l'initialisation."""
        adapter = LegacyTokenCounterAdapter()
        assert adapter._history == []

    def test_init_creates_empty_by_agent(self):
        """Le breakdown par agent est vide à l'initialisation."""
        adapter = LegacyTokenCounterAdapter()
        assert adapter._by_agent == {}

    def test_init_creates_empty_by_model(self):
        """Le breakdown par modèle est vide à l'initialisation."""
        adapter = LegacyTokenCounterAdapter()
        assert adapter._by_model == {}


class TestLegacyTokenCounterAdapterAdd:
    """Tests pour la méthode add."""

    def test_add_updates_token_usage(self):
        """add() met à jour le TokenUsage sous-jacent."""
        adapter = LegacyTokenCounterAdapter()
        adapter.add(100, 50, "claude-sonnet-4-20250514")

        assert adapter.get_total() >= 150

    def test_add_records_in_history(self):
        """add() enregistre dans l'historique."""
        adapter = LegacyTokenCounterAdapter()
        adapter.add(100, 50, "claude-sonnet-4-20250514", "drafter")

        assert len(adapter._history) == 1
        assert adapter._history[0]["input"] == 100
        assert adapter._history[0]["output"] == 50
        assert adapter._history[0]["total"] == 150
        assert adapter._history[0]["model"] == "claude-sonnet-4-20250514"
        assert adapter._history[0]["agent"] == "drafter"

    def test_add_with_agent_creates_agent_breakdown(self):
        """add() avec agent crée le breakdown par agent."""
        adapter = LegacyTokenCounterAdapter()
        adapter.add(100, 50, "claude-sonnet-4-20250514", "drafter")

        assert "drafter" in adapter._by_agent
        assert adapter._by_agent["drafter"]["input"] == 100
        assert adapter._by_agent["drafter"]["output"] == 50
        assert adapter._by_agent["drafter"]["total"] == 150

    def test_add_multiple_same_agent_accumulates(self):
        """Plusieurs add() du même agent s'accumulent."""
        adapter = LegacyTokenCounterAdapter()
        adapter.add(100, 50, "claude-sonnet-4-20250514", "drafter")
        adapter.add(200, 100, "claude-sonnet-4-20250514", "drafter")

        assert adapter._by_agent["drafter"]["input"] == 300
        assert adapter._by_agent["drafter"]["output"] == 150
        assert adapter._by_agent["drafter"]["total"] == 450

    def test_add_different_agents(self):
        """add() avec différents agents crée des entrées séparées."""
        adapter = LegacyTokenCounterAdapter()
        adapter.add(100, 50, "claude-sonnet-4-20250514", "drafter")
        adapter.add(200, 100, "claude-sonnet-4-20250514", "critic")

        assert "drafter" in adapter._by_agent
        assert "critic" in adapter._by_agent
        assert adapter._by_agent["drafter"]["total"] == 150
        assert adapter._by_agent["critic"]["total"] == 300

    def test_add_with_model_creates_model_breakdown(self):
        """add() avec modèle crée le breakdown par modèle."""
        adapter = LegacyTokenCounterAdapter()
        adapter.add(100, 50, "claude-sonnet-4-20250514")

        assert "claude-sonnet-4-20250514" in adapter._by_model
        assert adapter._by_model["claude-sonnet-4-20250514"]["input"] == 100
        assert adapter._by_model["claude-sonnet-4-20250514"]["output"] == 50
        assert adapter._by_model["claude-sonnet-4-20250514"]["total"] == 150

    def test_add_multiple_same_model_accumulates(self):
        """Plusieurs add() du même modèle s'accumulent."""
        adapter = LegacyTokenCounterAdapter()
        adapter.add(100, 50, "claude-sonnet-4-20250514")
        adapter.add(200, 100, "claude-sonnet-4-20250514")

        assert adapter._by_model["claude-sonnet-4-20250514"]["input"] == 300
        assert adapter._by_model["claude-sonnet-4-20250514"]["output"] == 150
        assert adapter._by_model["claude-sonnet-4-20250514"]["total"] == 450

    def test_add_different_models(self):
        """add() avec différents modèles crée des entrées séparées."""
        adapter = LegacyTokenCounterAdapter()
        adapter.add(100, 50, "claude-sonnet-4-20250514")
        adapter.add(200, 100, "claude-opus-4-20250514")

        assert "claude-sonnet-4-20250514" in adapter._by_model
        assert "claude-opus-4-20250514" in adapter._by_model

    def test_add_without_agent_no_agent_breakdown(self):
        """add() sans agent ne crée pas de breakdown agent."""
        adapter = LegacyTokenCounterAdapter()
        adapter.add(100, 50, "claude-sonnet-4-20250514", "")

        assert adapter._by_agent == {}

    def test_add_without_model_no_model_breakdown(self):
        """add() sans modèle ne crée pas de breakdown modèle."""
        adapter = LegacyTokenCounterAdapter()
        adapter.add(100, 50, "", "drafter")

        assert adapter._by_model == {}


class TestLegacyTokenCounterAdapterGetters:
    """Tests pour les méthodes get_*."""

    def test_get_total(self):
        """get_total() retourne le total correct."""
        adapter = LegacyTokenCounterAdapter()
        adapter.add(100, 50, "claude-sonnet-4-20250514")
        adapter.add(200, 100, "claude-sonnet-4-20250514")

        assert adapter.get_total() >= 450

    def test_get_input_tokens(self):
        """get_input_tokens() retourne le total des tokens en entrée."""
        adapter = LegacyTokenCounterAdapter()
        adapter.add(100, 50, "claude-sonnet-4-20250514")
        adapter.add(200, 100, "claude-sonnet-4-20250514")

        assert adapter.get_input_tokens() == 300

    def test_get_output_tokens(self):
        """get_output_tokens() retourne le total des tokens en sortie."""
        adapter = LegacyTokenCounterAdapter()
        adapter.add(100, 50, "claude-sonnet-4-20250514")
        adapter.add(200, 100, "claude-sonnet-4-20250514")

        assert adapter.get_output_tokens() == 150


class TestLegacyTokenCounterAdapterCost:
    """Tests pour les méthodes de coût."""

    def test_get_cost(self):
        """get_cost() retourne le coût calculé."""
        adapter = LegacyTokenCounterAdapter()
        adapter.add(1000, 500, "claude-sonnet-4-20250514")

        cost = adapter.get_cost()
        assert isinstance(cost, float)
        assert cost >= 0

    def test_get_cost_by_model(self):
        """get_cost_by_model() retourne le coût par modèle."""
        adapter = LegacyTokenCounterAdapter()
        adapter.add(1000, 500, "claude-sonnet-4-20250514")

        costs = adapter.get_cost_by_model()
        assert isinstance(costs, dict)
        assert "claude-sonnet-4-20250514" in costs
        assert isinstance(costs["claude-sonnet-4-20250514"], float)
        assert costs["claude-sonnet-4-20250514"] >= 0

    def test_get_cost_by_model_multiple_models(self):
        """get_cost_by_model() avec plusieurs modèles."""
        adapter = LegacyTokenCounterAdapter()
        adapter.add(1000, 500, "claude-sonnet-4-20250514")
        adapter.add(500, 250, "claude-opus-4-20250514")

        costs = adapter.get_cost_by_model()
        assert "claude-sonnet-4-20250514" in costs
        assert "claude-opus-4-20250514" in costs

    def test_get_cost_by_model_empty(self):
        """get_cost_by_model() sans modèle retourne dict vide."""
        adapter = LegacyTokenCounterAdapter()

        costs = adapter.get_cost_by_model()
        assert costs == {}

    def test_get_cost_by_model_unknown_model(self):
        """get_cost_by_model() avec modèle inconnu utilise défaut."""
        adapter = LegacyTokenCounterAdapter()
        adapter.add(1000, 500, "unknown-model")

        costs = adapter.get_cost_by_model()
        assert "unknown-model" in costs
        assert costs["unknown-model"] >= 0


class TestLegacyTokenCounterAdapterBreakdown:
    """Tests pour les méthodes de breakdown."""

    def test_get_breakdown(self):
        """get_breakdown() retourne le breakdown complet."""
        adapter = LegacyTokenCounterAdapter()
        adapter.add(100, 50, "claude-sonnet-4-20250514", "drafter")

        breakdown = adapter.get_breakdown()
        assert "total" in breakdown
        assert "input" in breakdown
        assert "output" in breakdown
        assert "cost" in breakdown
        assert "model" in breakdown
        assert "by_model" in breakdown
        assert "by_agent" in breakdown

    def test_get_breakdown_by_agent(self):
        """get_breakdown_by_agent() retourne le breakdown par agent."""
        adapter = LegacyTokenCounterAdapter()
        adapter.add(100, 50, "claude-sonnet-4-20250514", "drafter")
        adapter.add(200, 100, "claude-sonnet-4-20250514", "critic")

        breakdown = adapter.get_breakdown_by_agent()
        assert "drafter" in breakdown
        assert "critic" in breakdown
        assert breakdown["drafter"]["total"] == 150
        assert breakdown["critic"]["total"] == 300

    def test_get_breakdown_by_agent_empty(self):
        """get_breakdown_by_agent() sans agent retourne dict vide."""
        adapter = LegacyTokenCounterAdapter()
        adapter.add(100, 50, "claude-sonnet-4-20250514", "")

        breakdown = adapter.get_breakdown_by_agent()
        assert breakdown == {}


class TestLegacyTokenCounterAdapterHistory:
    """Tests pour l'historique."""

    def test_get_history_default_limit(self):
        """get_history() retourne les 10 dernières entrées par défaut."""
        adapter = LegacyTokenCounterAdapter()
        for i in range(15):
            adapter.add(100, 50, "claude-sonnet-4-20250514", f"agent-{i}")

        history = adapter.get_history()
        assert len(history) == 10

    def test_get_history_custom_limit(self):
        """get_history() respecte la limite personnalisée."""
        adapter = LegacyTokenCounterAdapter()
        for i in range(15):
            adapter.add(100, 50, "claude-sonnet-4-20250514", f"agent-{i}")

        history = adapter.get_history(limit=5)
        assert len(history) == 5

    def test_get_history_returns_most_recent(self):
        """get_history() retourne les plus récentes."""
        adapter = LegacyTokenCounterAdapter()
        for i in range(15):
            adapter.add(i, i, "claude-sonnet-4-20250514", f"agent-{i}")

        history = adapter.get_history(limit=3)
        # Les 3 dernières sont agent-12, agent-13, agent-14
        assert history[0]["agent"] == "agent-12"
        assert history[1]["agent"] == "agent-13"
        assert history[2]["agent"] == "agent-14"

    def test_get_history_empty(self):
        """get_history() avec historique vide."""
        adapter = LegacyTokenCounterAdapter()

        history = adapter.get_history()
        assert history == []


class TestLegacyTokenCounterAdapterReset:
    """Tests pour reset."""

    def test_reset_clears_token_usage(self):
        """reset() remet le compteur à zéro."""
        adapter = LegacyTokenCounterAdapter()
        adapter.add(100, 50, "claude-sonnet-4-20250514", "drafter")

        adapter.reset()

        assert adapter.get_total() == 0

    def test_reset_clears_history(self):
        """reset() vide l'historique."""
        adapter = LegacyTokenCounterAdapter()
        adapter.add(100, 50, "claude-sonnet-4-20250514", "drafter")

        adapter.reset()

        assert adapter._history == []

    def test_reset_clears_by_agent(self):
        """reset() vide le breakdown par agent."""
        adapter = LegacyTokenCounterAdapter()
        adapter.add(100, 50, "claude-sonnet-4-20250514", "drafter")

        adapter.reset()

        assert adapter._by_agent == {}

    def test_reset_clears_by_model(self):
        """reset() vide le breakdown par modèle."""
        adapter = LegacyTokenCounterAdapter()
        adapter.add(100, 50, "claude-sonnet-4-20250514")

        adapter.reset()

        assert adapter._by_model == {}


class TestLegacyTokenCounterAdapterModel:
    """Tests pour la gestion du modèle."""

    def test_get_model(self):
        """get_model() retourne le modèle actuel."""
        adapter = LegacyTokenCounterAdapter()
        adapter.add(100, 50, "claude-sonnet-4-20250514")

        model = adapter.get_model()
        assert model == "claude-sonnet-4-20250514"

    def test_get_model_empty(self):
        """get_model() retourne vide si pas de modèle défini."""
        adapter = LegacyTokenCounterAdapter()

        model = adapter.get_model()
        assert model == ""

    def test_set_model(self):
        """set_model() définit le modèle."""
        adapter = LegacyTokenCounterAdapter()
        adapter.set_model("claude-opus-4-20250514")

        assert adapter.get_model() == "claude-opus-4-20250514"

    def test_set_model_updates_usage(self):
        """set_model() met à jour le TokenUsage sous-jacent."""
        adapter = LegacyTokenCounterAdapter()
        adapter.set_model("claude-opus-4-20250514")

        assert adapter._usage.model == "claude-opus-4-20250514"


class TestLegacyTokenCounterAdapterCompatibility:
    """Tests pour la compatibilité avec TokenUsage."""

    def test_token_usage_property(self):
        """La propriété token_usage retourne l'instance sous-jacente."""
        usage = TokenUsage()
        adapter = LegacyTokenCounterAdapter(token_usage=usage)

        assert adapter.token_usage is usage

    def test_token_usage_property_default(self):
        """token_usage retourne l'instance créée par défaut."""
        adapter = LegacyTokenCounterAdapter()

        assert adapter.token_usage is adapter._usage

    def test_str_representation(self):
        """__str__() retourne la représentation textuelle."""
        adapter = LegacyTokenCounterAdapter()
        adapter.add(100, 50, "claude-sonnet-4-20250514")

        result = str(adapter)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_str_empty(self):
        """__str__() fonctionne avec compteur vide."""
        adapter = LegacyTokenCounterAdapter()

        result = str(adapter)
        assert isinstance(result, str)


class TestLegacyTokenCounterAdapterEdgeCases:
    """Tests des edge cases."""

    def test_add_zero_tokens(self):
        """add() avec zéro tokens."""
        adapter = LegacyTokenCounterAdapter()
        adapter.add(0, 0, "claude-sonnet-4-20250514")

        assert adapter.get_total() == 0

    def test_add_negative_tokens_raises_error(self):
        """add() avec tokens négatifs lève une erreur."""
        from app.domain.exceptions import InvalidBoundsError

        adapter = LegacyTokenCounterAdapter()
        # Le domain valide que les tokens sont >= 0
        with pytest.raises(InvalidBoundsError):
            adapter.add(-100, -50, "claude-sonnet-4-20250514")

    def test_add_large_numbers(self):
        """add() avec de grands nombres."""
        adapter = LegacyTokenCounterAdapter()
        adapter.add(10000000, 5000000, "claude-sonnet-4-20250514")

        assert adapter.get_input_tokens() == 10000000
        assert adapter.get_output_tokens() == 5000000

    def test_get_history_limit_larger_than_entries(self):
        """get_history() avec limite plus grande que le nombre d'entrées."""
        adapter = LegacyTokenCounterAdapter()
        adapter.add(100, 50, "claude-sonnet-4-20250514")

        history = adapter.get_history(limit=100)
        assert len(history) == 1

    def test_multiple_reset_calls(self):
        """Plusieurs appels à reset() consécutifs."""
        adapter = LegacyTokenCounterAdapter()
        adapter.add(100, 50, "claude-sonnet-4-20250514")

        adapter.reset()
        adapter.reset()
        adapter.reset()

        assert adapter.get_total() == 0
        assert adapter._history == []

    def test_add_after_reset(self):
        """add() après reset() fonctionne normalement."""
        adapter = LegacyTokenCounterAdapter()
        adapter.add(100, 50, "claude-sonnet-4-20250514")
        adapter.reset()
        adapter.add(200, 100, "claude-opus-4-20250514")

        assert adapter.get_input_tokens() == 200
        assert adapter.get_output_tokens() == 100

    def test_empty_string_model(self):
        """Modèle avec chaîne vide."""
        adapter = LegacyTokenCounterAdapter()
        adapter.add(100, 50, "")

        assert adapter._by_model == {}

    def test_empty_string_agent(self):
        """Agent avec chaîne vide."""
        adapter = LegacyTokenCounterAdapter()
        adapter.add(100, 50, "claude-sonnet-4-20250514", "")

        assert adapter._by_agent == {}

    def test_special_characters_in_agent(self):
        """Agent avec caractères spéciaux."""
        adapter = LegacyTokenCounterAdapter()
        adapter.add(100, 50, "claude-sonnet-4-20250514", "agent-with-émojis-🤖")

        assert "agent-with-émojis-🤖" in adapter._by_agent

    def test_special_characters_in_model(self):
        """Modèle avec caractères spéciaux."""
        adapter = LegacyTokenCounterAdapter()
        adapter.add(100, 50, "custom/model@v2.0")

        assert "custom/model@v2.0" in adapter._by_model


class TestLegacyTokenCounterAdapterImplementsPort:
    """Tests vérifiant l'implémentation du port."""

    def test_implements_token_counter_port(self):
        """L'adapter implémente TokenCounterPort."""
        from app.domain.ports.token_counter_port import TokenCounterPort

        assert issubclass(LegacyTokenCounterAdapter, TokenCounterPort)

    def test_has_all_required_methods(self):
        """L'adapter a toutes les méthodes requises du port."""
        adapter = LegacyTokenCounterAdapter()

        # Méthodes de comptage
        assert hasattr(adapter, "add")
        assert hasattr(adapter, "get_total")
        assert hasattr(adapter, "get_input_tokens")
        assert hasattr(adapter, "get_output_tokens")

        # Méthodes de coût
        assert hasattr(adapter, "get_cost")
        assert hasattr(adapter, "get_cost_by_model")

        # Méthodes de breakdown
        assert hasattr(adapter, "get_breakdown")
        assert hasattr(adapter, "get_breakdown_by_agent")
        assert hasattr(adapter, "get_history")

        # Méthodes de gestion
        assert hasattr(adapter, "reset")
        assert hasattr(adapter, "get_model")
        assert hasattr(adapter, "set_model")
