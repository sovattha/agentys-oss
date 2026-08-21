# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour app.domain.entities.token_usage."""

import pytest
from app.domain.entities.token_usage import TokenUsage, MODEL_COSTS
from app.domain.exceptions import InvalidBoundsError


class TestTokenUsage:
    """Tests pour TokenUsage."""

    # --- Création et validation ---

    def test_create_default(self):
        usage = TokenUsage()
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0
        assert usage.model == ""

    def test_create_with_values(self):
        usage = TokenUsage(input_tokens=100, output_tokens=50, model="claude-sonnet-4-20250514")
        assert usage.input_tokens == 100
        assert usage.output_tokens == 50

    def test_negative_input_raises(self):
        with pytest.raises(InvalidBoundsError):
            TokenUsage(input_tokens=-1, output_tokens=0)

    def test_negative_output_raises(self):
        with pytest.raises(InvalidBoundsError):
            TokenUsage(input_tokens=0, output_tokens=-1)

    # --- Aliases ---

    def test_input_alias(self):
        usage = TokenUsage(input_tokens=42)
        assert usage.input == 42

    def test_output_alias(self):
        usage = TokenUsage(output_tokens=99)
        assert usage.output == 99

    # --- Total ---

    def test_total(self):
        usage = TokenUsage(input_tokens=100, output_tokens=200)
        assert usage.total == 300

    def test_total_zero(self):
        usage = TokenUsage()
        assert usage.total == 0

    # --- Cost ---

    def test_cost_known_model(self):
        usage = TokenUsage(input_tokens=1_000_000, output_tokens=0, model="claude-sonnet-4-20250514")
        # 1M input tokens * $3/M = $3.0
        assert usage.cost == pytest.approx(3.0)

    def test_cost_ollama_free(self):
        usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000, model="mixtral:latest")
        assert usage.cost == 0.0

    def test_cost_unknown_model_uses_sonnet_default(self):
        usage = TokenUsage(input_tokens=1_000_000, output_tokens=0, model="unknown-model")
        expected = MODEL_COSTS["claude-sonnet-4-20250514"]["input"]
        assert usage.cost == pytest.approx(expected)

    def test_cost_zero_tokens(self):
        usage = TokenUsage(model="claude-opus-4-20250514")
        assert usage.cost == 0.0

    # --- Add ---

    def test_add_tokens(self):
        usage = TokenUsage()
        usage.add(input_tokens=100, output_tokens=50)
        assert usage.input_tokens == 100
        assert usage.output_tokens == 50

    def test_add_accumulates(self):
        usage = TokenUsage(input_tokens=10, output_tokens=5)
        usage.add(input_tokens=20, output_tokens=15)
        assert usage.input_tokens == 30
        assert usage.output_tokens == 20

    def test_add_updates_model(self):
        usage = TokenUsage()
        usage.add(input_tokens=0, output_tokens=0, model="claude-haiku-4-5-20251001")
        assert usage.model == "claude-haiku-4-5-20251001"

    def test_add_negative_input_raises(self):
        usage = TokenUsage()
        with pytest.raises(InvalidBoundsError):
            usage.add(input_tokens=-1, output_tokens=0)

    def test_add_negative_output_raises(self):
        usage = TokenUsage()
        with pytest.raises(InvalidBoundsError):
            usage.add(input_tokens=0, output_tokens=-1)

    def test_add_empty_model_keeps_existing(self):
        usage = TokenUsage(model="original")
        usage.add(input_tokens=10, output_tokens=5)
        assert usage.model == "original"

    # --- Reset ---

    def test_reset(self):
        usage = TokenUsage(input_tokens=100, output_tokens=50, model="test")
        usage.reset()
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0
        assert usage.model == ""

    # --- __str__ ---

    def test_str_with_model_and_cost(self):
        usage = TokenUsage(input_tokens=1000, output_tokens=500, model="claude-sonnet-4-20250514")
        s = str(usage)
        assert "1,000" in s
        assert "500" in s

    def test_str_no_model(self):
        usage = TokenUsage(input_tokens=10, output_tokens=5)
        s = str(usage)
        assert "10" in s
        assert "5" in s
