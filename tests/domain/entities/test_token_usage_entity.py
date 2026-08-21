# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests pour TokenUsage entity.

TDD: Tests complets pour la validation et le calcul des coûts tokens.
"""

import pytest
from app.domain.entities.token_usage import TokenUsage, MODEL_COSTS
from app.domain.exceptions import InvalidBoundsError


class TestTokenUsageInit:
    """Tests pour l'initialisation de TokenUsage."""

    def test_default_initialization(self):
        """Test création avec valeurs par défaut."""
        usage = TokenUsage()
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0
        assert usage.model == ""

    def test_explicit_initialization(self):
        """Test création avec valeurs explicites."""
        usage = TokenUsage(input_tokens=100, output_tokens=50, model="claude-sonnet-4-20250514")
        assert usage.input_tokens == 100
        assert usage.output_tokens == 50
        assert usage.model == "claude-sonnet-4-20250514"

    def test_negative_input_tokens_raises_error(self):
        """Test qu'input_tokens négatif lève InvalidBoundsError."""
        with pytest.raises(InvalidBoundsError) as exc_info:
            TokenUsage(input_tokens=-1)
        assert exc_info.value.field == "input_tokens"
        assert exc_info.value.value == -1
        assert exc_info.value.min_val == 0
        assert exc_info.value.code == "INVALID_BOUNDS"

    def test_negative_output_tokens_raises_error(self):
        """Test qu'output_tokens négatif lève InvalidBoundsError."""
        with pytest.raises(InvalidBoundsError) as exc_info:
            TokenUsage(output_tokens=-100)
        assert exc_info.value.field == "output_tokens"
        assert exc_info.value.value == -100
        assert exc_info.value.min_val == 0

    def test_both_negative_tokens_raises_error_on_first(self):
        """Test que le premier paramètre négatif est validé d'abord."""
        with pytest.raises(InvalidBoundsError) as exc_info:
            TokenUsage(input_tokens=-5, output_tokens=-10)
        assert exc_info.value.field == "input_tokens"

    def test_zero_tokens_valid(self):
        """Test que zéro est valide."""
        usage = TokenUsage(input_tokens=0, output_tokens=0)
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0

    def test_large_token_values_valid(self):
        """Test que les grandes valeurs sont acceptées."""
        usage = TokenUsage(input_tokens=1_000_000, output_tokens=5_000_000)
        assert usage.input_tokens == 1_000_000
        assert usage.output_tokens == 5_000_000


class TestTokenUsageProperties:
    """Tests pour les propriétés de TokenUsage."""

    def test_input_property_alias(self):
        """Test que input est un alias pour input_tokens."""
        usage = TokenUsage(input_tokens=100)
        assert usage.input == 100
        assert usage.input == usage.input_tokens

    def test_output_property_alias(self):
        """Test que output est un alias pour output_tokens."""
        usage = TokenUsage(output_tokens=50)
        assert usage.output == 50
        assert usage.output == usage.output_tokens

    def test_total_property_sum(self):
        """Test que total retourne la somme des tokens."""
        usage = TokenUsage(input_tokens=100, output_tokens=50)
        assert usage.total == 150

    def test_total_property_zero(self):
        """Test que total est zéro avec zéro token."""
        usage = TokenUsage()
        assert usage.total == 0

    def test_total_property_with_large_numbers(self):
        """Test total avec grandes valeurs."""
        usage = TokenUsage(input_tokens=1_000_000, output_tokens=2_000_000)
        assert usage.total == 3_000_000


class TestTokenUsageCost:
    """Tests pour le calcul du coût."""

    def test_cost_sonnet_model(self):
        """Test calcul du coût pour claude-sonnet-4-20250514."""
        usage = TokenUsage(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            model="claude-sonnet-4-20250514"
        )
        # (1M * 3.0 + 1M * 15.0) / 1_000_000 = 18.0
        assert usage.cost == 18.0

    def test_cost_haiku_model(self):
        """Test calcul du coût pour claude-haiku-4-5-20251001."""
        usage = TokenUsage(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            model="claude-haiku-4-5-20251001"
        )
        # (1M * 1.00 + 1M * 5.00) / 1_000_000 = 6.00
        assert usage.cost == 6.00

    def test_cost_opus_model(self):
        """Test calcul du coût pour claude-opus-4-20250514."""
        usage = TokenUsage(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            model="claude-opus-4-20250514"
        )
        # (1M * 15.0 + 1M * 75.0) / 1_000_000 = 90.0
        assert usage.cost == 90.0

    def test_cost_ollama_free(self):
        """Test que les modèles Ollama sont gratuits."""
        usage = TokenUsage(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            model="mixtral:latest"
        )
        assert usage.cost == 0.0

    def test_cost_unknown_model_defaults_to_sonnet(self):
        """Test que les modèles inconnus utilisent les coûts Sonnet par défaut."""
        usage = TokenUsage(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            model="unknown-model-xyz"
        )
        # Doit utiliser Sonnet par défaut: (1M * 3.0 + 1M * 15.0) / 1_000_000 = 18.0
        assert usage.cost == 18.0

    def test_cost_empty_model_defaults_to_sonnet(self):
        """Test que modèle vide utilise les coûts Sonnet."""
        usage = TokenUsage(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            model=""
        )
        assert usage.cost == 18.0

    def test_cost_zero_tokens(self):
        """Test que coût est zéro avec zéro token."""
        usage = TokenUsage(input_tokens=0, output_tokens=0, model="claude-sonnet-4-20250514")
        assert usage.cost == 0.0

    def test_cost_only_input_tokens(self):
        """Test coût avec seulement des tokens d'entrée."""
        usage = TokenUsage(input_tokens=1_000_000, output_tokens=0, model="claude-sonnet-4-20250514")
        # (1M * 3.0 + 0) / 1_000_000 = 3.0
        assert usage.cost == 3.0

    def test_cost_only_output_tokens(self):
        """Test coût avec seulement des tokens de sortie."""
        usage = TokenUsage(input_tokens=0, output_tokens=1_000_000, model="claude-sonnet-4-20250514")
        # (0 + 1M * 15.0) / 1_000_000 = 15.0
        assert usage.cost == 15.0

    def test_cost_fractional_calculation(self):
        """Test coût avec fraction de million."""
        usage = TokenUsage(
            input_tokens=500_000,
            output_tokens=500_000,
            model="claude-sonnet-4-20250514"
        )
        # (500k * 3.0 + 500k * 15.0) / 1_000_000 = 9.0
        assert usage.cost == 9.0

    def test_cost_claude_35_sonnet_same_as_sonnet_4(self):
        """Test que claude-3-5-sonnet a les mêmes coûts que sonnet-4."""
        usage_v5 = TokenUsage(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            model="claude-3-5-sonnet-20241022"
        )
        usage_v4 = TokenUsage(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            model="claude-sonnet-4-20250514"
        )
        assert usage_v5.cost == usage_v4.cost

    def test_cost_35_haiku_keeps_historical_price(self):
        """Test que Haiku 3.5 garde son prix historique distinct de Haiku 4.5."""
        usage_35 = TokenUsage(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            model="claude-3-5-haiku-20241022"
        )
        usage_4 = TokenUsage(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            model="claude-haiku-4-5-20251001"
        )
        assert usage_35.cost == 4.80
        assert usage_4.cost == 6.00


class TestTokenUsageAdd:
    """Tests pour la méthode add()."""

    def test_add_valid_tokens(self):
        """Test ajout valide de tokens."""
        usage = TokenUsage(input_tokens=100, output_tokens=50)
        usage.add(input_tokens=50, output_tokens=25)
        assert usage.input_tokens == 150
        assert usage.output_tokens == 75

    def test_add_zero_tokens(self):
        """Test ajout de zéro tokens."""
        usage = TokenUsage(input_tokens=100, output_tokens=50)
        usage.add(input_tokens=0, output_tokens=0)
        assert usage.input_tokens == 100
        assert usage.output_tokens == 50

    def test_add_with_model_update(self):
        """Test ajout avec mise à jour du modèle."""
        usage = TokenUsage(input_tokens=100, model="claude-haiku-4-5-20251001")
        usage.add(input_tokens=50, output_tokens=25, model="claude-sonnet-4-20250514")
        assert usage.input_tokens == 150
        assert usage.model == "claude-sonnet-4-20250514"

    def test_add_without_model_keeps_existing(self):
        """Test que modèle existant est conservé sans modèle fourni."""
        usage = TokenUsage(input_tokens=100, model="claude-sonnet-4-20250514")
        usage.add(input_tokens=50, output_tokens=25, model="")
        assert usage.model == "claude-sonnet-4-20250514"

    def test_add_negative_input_raises_error(self):
        """Test qu'ajout d'input_tokens négatif lève InvalidBoundsError."""
        usage = TokenUsage(input_tokens=100)
        with pytest.raises(InvalidBoundsError) as exc_info:
            usage.add(input_tokens=-1, output_tokens=0)
        assert exc_info.value.field == "input_tokens"
        assert exc_info.value.value == -1

    def test_add_negative_output_raises_error(self):
        """Test qu'ajout d'output_tokens négatif lève InvalidBoundsError."""
        usage = TokenUsage(output_tokens=50)
        with pytest.raises(InvalidBoundsError) as exc_info:
            usage.add(input_tokens=0, output_tokens=-10)
        assert exc_info.value.field == "output_tokens"
        assert exc_info.value.value == -10

    def test_add_both_negative_raises_error_on_first(self):
        """Test que le premier paramètre négatif est validé d'abord."""
        usage = TokenUsage()
        with pytest.raises(InvalidBoundsError) as exc_info:
            usage.add(input_tokens=-5, output_tokens=-10)
        assert exc_info.value.field == "input_tokens"

    def test_add_preserves_state_on_validation_error(self):
        """Test que l'état n'est pas modifié si la validation échoue."""
        usage = TokenUsage(input_tokens=100, output_tokens=50)
        try:
            usage.add(input_tokens=-1, output_tokens=25)
        except InvalidBoundsError:
            pass
        # L'état doit rester inchangé
        assert usage.input_tokens == 100
        assert usage.output_tokens == 50

    def test_add_multiple_times_accumulates(self):
        """Test que add() peut être appelé plusieurs fois et accumule."""
        usage = TokenUsage()
        usage.add(100, 50)
        usage.add(50, 25)
        usage.add(25, 10)
        assert usage.input_tokens == 175
        assert usage.output_tokens == 85
        assert usage.total == 260


class TestTokenUsageReset:
    """Tests pour la méthode reset()."""

    def test_reset_zeroes_all_values(self):
        """Test que reset() met tous les compteurs à zéro."""
        usage = TokenUsage(
            input_tokens=1000,
            output_tokens=500,
            model="claude-sonnet-4-20250514"
        )
        usage.reset()
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0
        assert usage.model == ""

    def test_reset_empty_usage(self):
        """Test reset sur usage vide."""
        usage = TokenUsage()
        usage.reset()
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0
        assert usage.model == ""

    def test_reset_and_add_again(self):
        """Test que add() fonctionne après reset()."""
        usage = TokenUsage(input_tokens=100, output_tokens=50)
        usage.reset()
        usage.add(200, 75)
        assert usage.input_tokens == 200
        assert usage.output_tokens == 75


class TestTokenUsageStr:
    """Tests pour __str__()."""

    def test_str_with_no_tokens(self):
        """Test format string sans tokens."""
        usage = TokenUsage()
        result = str(usage)
        assert "Tokens: 0" in result
        assert "↓ 0↑" in result

    def test_str_with_tokens_no_cost(self):
        """Test format string avec tokens, coût zéro (Ollama)."""
        usage = TokenUsage(input_tokens=1000, output_tokens=500, model="mixtral:latest")
        result = str(usage)
        assert "Tokens: 1,000" in result
        assert "500" in result
        assert "mixtral" in result

    def test_str_with_tokens_and_cost(self):
        """Test format string avec tokens et coût."""
        usage = TokenUsage(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            model="claude-sonnet-4-20250514"
        )
        result = str(usage)
        assert "Tokens:" in result
        assert "$" in result
        assert "sonnet" in result
        assert "18.0000" in result or "18" in result

    def test_str_format_with_formatting(self):
        """Test que le format inclut les séparateurs."""
        usage = TokenUsage(input_tokens=1234567, output_tokens=7654321)
        result = str(usage)
        # Doit inclure les virgules
        assert "1,234,567" in result or "1234567" in result

    def test_str_shows_arrows(self):
        """Test que les flèches de direction sont présentes."""
        usage = TokenUsage(input_tokens=100, output_tokens=50)
        result = str(usage)
        assert "↓" in result  # Input down
        assert "↑" in result  # Output up

    def test_str_format_with_haiku_model(self):
        """Test extraction du nom court du modèle pour Haiku."""
        usage = TokenUsage(
            input_tokens=100,
            output_tokens=100,
            model="claude-haiku-4-5-20251001"
        )
        result = str(usage)
        assert "haiku" in result

    def test_str_format_with_opus_model(self):
        """Test extraction du nom court du modèle pour Opus."""
        usage = TokenUsage(
            input_tokens=100,
            output_tokens=100,
            model="claude-opus-4-20250514"
        )
        result = str(usage)
        assert "opus" in result

    def test_str_with_ollama_model(self):
        """Test extraction du nom court pour Ollama (format différent)."""
        usage = TokenUsage(
            input_tokens=100,
            output_tokens=100,
            model="mixtral:latest"
        )
        result = str(usage)
        assert "mixtral" in result

    def test_str_brackets_present(self):
        """Test que le string est entouré de crochets."""
        usage = TokenUsage(input_tokens=100, output_tokens=50)
        result = str(usage)
        assert result.startswith("[")
        assert result.endswith("]")


class TestTokenUsageIntegration:
    """Tests d'intégration pour TokenUsage."""

    def test_complete_workflow(self):
        """Test d'un workflow complet d'utilisation."""
        # Initialisation
        usage = TokenUsage(model="claude-sonnet-4-20250514")
        assert usage.total == 0
        assert usage.cost == 0.0

        # Premier appel
        usage.add(1000, 500, model="claude-sonnet-4-20250514")
        assert usage.total == 1500
        cost1 = usage.cost

        # Deuxième appel
        usage.add(500, 250)
        assert usage.total == 2250
        cost2 = usage.cost
        assert cost2 > cost1

        # Reset
        usage.reset()
        assert usage.total == 0
        assert usage.cost == 0.0

    def test_cost_calculation_precision(self):
        """Test la précision du calcul du coût."""
        usage = TokenUsage(
            input_tokens=123_456,
            output_tokens=654_321,
            model="claude-haiku-4-5-20251001"
        )
        # (123456 * 1.00 + 654321 * 5.00) / 1_000_000
        expected = (123456 * 1.00 + 654321 * 5.00) / 1_000_000
        assert abs(usage.cost - expected) < 0.0001

    def test_model_costs_all_defined(self):
        """Test que tous les modèles dans MODEL_COSTS sont correctement définis."""
        for model_name, costs in MODEL_COSTS.items():
            assert "input" in costs
            assert "output" in costs
            assert costs["input"] >= 0
            assert costs["output"] >= 0

    def test_model_costs_sonic_has_higher_output_than_input(self):
        """Test que Sonnet a un coût output supérieur au coût input."""
        costs = MODEL_COSTS["claude-sonnet-4-20250514"]
        assert costs["output"] > costs["input"]

    def test_model_costs_opus_most_expensive(self):
        """Test qu'Opus est le modèle le plus cher."""
        opus_cost = (1_000_000 * MODEL_COSTS["claude-opus-4-20250514"]["input"] +
                     1_000_000 * MODEL_COSTS["claude-opus-4-20250514"]["output"]) / 1_000_000
        sonnet_cost = (1_000_000 * MODEL_COSTS["claude-sonnet-4-20250514"]["input"] +
                       1_000_000 * MODEL_COSTS["claude-sonnet-4-20250514"]["output"]) / 1_000_000
        assert opus_cost > sonnet_cost
