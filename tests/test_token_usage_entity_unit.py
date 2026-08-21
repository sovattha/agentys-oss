# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour l'entité TokenUsage."""

import pytest
from app.domain.entities.token_usage import TokenUsage, MODEL_COSTS
from app.domain.exceptions import InvalidBoundsError


class TestTokenUsageCreation:
    """Tests pour la création de TokenUsage."""

    def test_default_creation(self):
        usage = TokenUsage()
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0
        assert usage.model == ""

    def test_creation_with_values(self):
        usage = TokenUsage(input_tokens=100, output_tokens=50, model="claude-sonnet-4-20250514")
        assert usage.input_tokens == 100
        assert usage.output_tokens == 50
        assert usage.model == "claude-sonnet-4-20250514"

    def test_negative_input_tokens_raises(self):
        with pytest.raises(InvalidBoundsError):
            TokenUsage(input_tokens=-1, output_tokens=0)

    def test_negative_output_tokens_raises(self):
        with pytest.raises(InvalidBoundsError):
            TokenUsage(input_tokens=0, output_tokens=-1)

    def test_zero_tokens_valid(self):
        usage = TokenUsage(input_tokens=0, output_tokens=0)
        assert usage.total == 0


class TestTokenUsageProperties:
    """Tests pour les propriétés de TokenUsage."""

    def test_input_alias(self):
        usage = TokenUsage(input_tokens=100)
        assert usage.input == 100

    def test_output_alias(self):
        usage = TokenUsage(output_tokens=200)
        assert usage.output == 200

    def test_total(self):
        usage = TokenUsage(input_tokens=100, output_tokens=200)
        assert usage.total == 300

    def test_total_zero(self):
        usage = TokenUsage()
        assert usage.total == 0

    def test_cost_sonnet(self):
        usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000, model="claude-sonnet-4-20250514")
        # input: 3.0$/M, output: 15.0$/M → 3 + 15 = 18
        assert usage.cost == pytest.approx(18.0)

    def test_cost_haiku(self):
        usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000, model="claude-haiku-4-5-20251001")
        # input: 1.00$/M, output: 5.00$/M -> 1.0 + 5.0 = 6.0
        assert usage.cost == pytest.approx(6.0)

    def test_cost_ollama_free(self):
        usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000, model="mixtral:latest")
        assert usage.cost == 0.0

    def test_cost_unknown_model_defaults_to_sonnet(self):
        usage = TokenUsage(input_tokens=1_000_000, output_tokens=0, model="unknown-model")
        sonnet_input_cost = MODEL_COSTS["claude-sonnet-4-20250514"]["input"]
        assert usage.cost == pytest.approx(sonnet_input_cost)

    def test_cost_zero_tokens(self):
        usage = TokenUsage(model="claude-sonnet-4-20250514")
        assert usage.cost == 0.0


class TestTokenUsageAdd:
    """Tests pour la méthode add."""

    def test_add_tokens(self):
        usage = TokenUsage()
        usage.add(100, 50, "claude-sonnet-4-20250514")
        assert usage.input_tokens == 100
        assert usage.output_tokens == 50
        assert usage.model == "claude-sonnet-4-20250514"

    def test_add_accumulates(self):
        usage = TokenUsage()
        usage.add(100, 50)
        usage.add(200, 100)
        assert usage.input_tokens == 300
        assert usage.output_tokens == 150

    def test_add_negative_input_raises(self):
        usage = TokenUsage()
        with pytest.raises(InvalidBoundsError):
            usage.add(-1, 0)

    def test_add_negative_output_raises(self):
        usage = TokenUsage()
        with pytest.raises(InvalidBoundsError):
            usage.add(0, -1)

    def test_add_updates_model(self):
        usage = TokenUsage()
        usage.add(10, 10, "model-a")
        assert usage.model == "model-a"
        usage.add(10, 10, "model-b")
        assert usage.model == "model-b"

    def test_add_empty_model_preserves_existing(self):
        usage = TokenUsage(model="model-a")
        usage.add(10, 10, "")
        assert usage.model == "model-a"


class TestTokenUsageReset:
    """Tests pour la méthode reset."""

    def test_reset(self):
        usage = TokenUsage(input_tokens=100, output_tokens=50, model="test")
        usage.reset()
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0
        assert usage.model == ""

    def test_reset_idempotent(self):
        usage = TokenUsage()
        usage.reset()
        assert usage.total == 0


class TestTokenUsageStr:
    """Tests pour __str__."""

    def test_str_with_model(self):
        usage = TokenUsage(input_tokens=1000, output_tokens=500, model="claude-sonnet-4-20250514")
        s = str(usage)
        assert "1,000" in s
        assert "500" in s
        assert "sonnet" in s

    def test_str_zero_cost(self):
        usage = TokenUsage(input_tokens=0, output_tokens=0, model="mixtral:latest")
        s = str(usage)
        assert "0" in s

    def test_str_no_model(self):
        usage = TokenUsage(input_tokens=100, output_tokens=50)
        s = str(usage)
        assert "100" in s
