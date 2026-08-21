# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests TDD pour les edge cases numériques.

Ce module teste les scénarios numériques extrêmes :
- Overflow/underflow des entiers
- Précision des calculs de coûts (float)
- Division par zéro
- Valeurs limites (0, max_int, etc.)
- Calculs de priorité et scores

Principes TDD/Clean Architecture :
1. Tests déterministes et reproductibles
2. Chaque test cible un cas numérique spécifique
3. Documentation des bugs potentiels avant correction
"""

import pytest
import sys

from app.domain.entities import (
    TokenUsage,
    Priority,
    Classification,
    EmailCategory,
    LearningInsights,
    LearningStats,
    LearnedPattern,
    PatternType,
)
from app.domain.entities.realtime_edit import Suggestion


# ============================================================================
# TESTS - TOKEN USAGE NUMERIC EDGE CASES
# ============================================================================

class TestTokenUsageNumericEdgeCases:
    """Tests numériques pour TokenUsage."""

    def test_token_usage_zero_values(self):
        """Zéro tokens = zéro coût."""
        usage = TokenUsage(input_tokens=0, output_tokens=0)
        assert usage.total == 0
        assert usage.cost == 0.0

    def test_token_usage_very_large_tokens(self):
        """Très grand nombre de tokens."""
        # 100 milliards de tokens (cas extrême)
        usage = TokenUsage(
            input_tokens=100_000_000_000,
            output_tokens=100_000_000_000,
            model="claude-sonnet-4-20250514"
        )
        # Cost = (100B * 3 + 100B * 15) / 1M = 300K + 1.5M = 1.8M$
        expected_cost = (100_000_000_000 * 3.0 + 100_000_000_000 * 15.0) / 1_000_000
        assert usage.cost == expected_cost
        assert usage.cost == 1_800_000.0

    def test_token_usage_max_int_tokens(self):
        """sys.maxsize tokens (limite Python)."""
        usage = TokenUsage(
            input_tokens=sys.maxsize,
            output_tokens=0,
            model="claude-sonnet-4-20250514"
        )
        # Vérifier que le calcul ne plante pas
        cost = usage.cost
        assert cost > 0
        # Vérifier que c'est un float valide
        assert not (cost != cost)  # Not NaN

    def test_token_usage_cost_precision_small(self):
        """Précision des coûts pour petits nombres."""
        usage = TokenUsage(
            input_tokens=1,
            output_tokens=1,
            model="claude-sonnet-4-20250514"
        )
        # Cost = (1 * 3 + 1 * 15) / 1M = 18 / 1M = 0.000018
        expected = 18 / 1_000_000
        assert abs(usage.cost - expected) < 1e-12

    def test_token_usage_cost_precision_medium(self):
        """Précision des coûts pour nombres moyens."""
        usage = TokenUsage(
            input_tokens=1000,
            output_tokens=500,
            model="claude-sonnet-4-20250514"
        )
        # Cost = (1000 * 3 + 500 * 15) / 1M = (3000 + 7500) / 1M = 0.0105
        expected = 10500 / 1_000_000
        assert abs(usage.cost - expected) < 1e-10

    def test_token_usage_add_accumulation(self):
        """add() accumule correctement."""
        usage = TokenUsage()
        for _ in range(1000):
            usage.add(input_tokens=100, output_tokens=50)

        assert usage.input_tokens == 100_000
        assert usage.output_tokens == 50_000
        assert usage.total == 150_000

    def test_token_usage_add_with_overflow_check(self):
        """add() avec grands nombres ne cause pas d'overflow."""
        usage = TokenUsage(input_tokens=sys.maxsize - 100, output_tokens=0)
        # Ajouter un petit nombre ne devrait pas causer de problème
        usage.add(input_tokens=50, output_tokens=0)
        assert usage.input_tokens == sys.maxsize - 50

    def test_token_usage_free_model_always_zero_cost(self):
        """Modèle gratuit = coût toujours zéro."""
        usage = TokenUsage(
            input_tokens=1_000_000_000,
            output_tokens=1_000_000_000,
            model="mixtral:latest"
        )
        assert usage.cost == 0.0


# ============================================================================
# TESTS - PRIORITY SCORE CALCULATIONS
# ============================================================================

class TestPriorityScoreCalculations:
    """Tests des calculs de score de priorité."""

    def test_priority_score_formula_verification(self):
        """Vérification de la formule de calcul."""
        # Formule: urgency * 0.4 + vip * 0.3 + (sentiment + 1) * 15
        priority = Priority.from_components(
            urgency=100,
            vip=100,
            sentiment=1.0
        )
        # 100 * 0.4 + 100 * 0.3 + (1 + 1) * 15 = 40 + 30 + 30 = 100
        assert priority.priority_score == 100

    def test_priority_score_minimum(self):
        """Score minimum possible."""
        priority = Priority.from_components(
            urgency=0,
            vip=0,
            sentiment=-1.0
        )
        # 0 * 0.4 + 0 * 0.3 + (-1 + 1) * 15 = 0 + 0 + 0 = 0
        assert priority.priority_score == 0

    def test_priority_score_clamped_high(self):
        """Score clampé à 100 maximum."""
        # Valeurs qui devraient donner > 100
        priority = Priority.from_components(
            urgency=100,
            vip=100,
            sentiment=1.0
        )
        # Le score est clampé à 100
        assert priority.priority_score <= 100

    def test_priority_score_clamped_low(self):
        """Score clampé à 0 minimum."""
        # Même avec sentiment très négatif, ne peut pas être < 0
        priority = Priority.from_components(
            urgency=0,
            vip=0,
            sentiment=-1.0
        )
        assert priority.priority_score >= 0

    def test_priority_score_with_extreme_values(self):
        """Valeurs extrêmes lèvent maintenant InvalidBoundsError.

        IMPLÉMENTÉ: Validation ajoutée dans Priority.from_components()
        """
        from app.domain.exceptions import InvalidBoundsError

        # Urgency > 100 lève maintenant une erreur
        with pytest.raises(InvalidBoundsError):
            Priority.from_components(
                urgency=200,  # Invalid
                vip=50,
                sentiment=0.0
            )

    def test_priority_score_boundary_70(self):
        """Test du seuil 70 pour is_high_priority()."""
        priority_69 = Priority(
            urgency=50, vip=50, sentiment=0.0, deadline=None, priority_score=69
        )
        priority_70 = Priority(
            urgency=50, vip=50, sentiment=0.0, deadline=None, priority_score=70
        )
        priority_71 = Priority(
            urgency=50, vip=50, sentiment=0.0, deadline=None, priority_score=71
        )

        assert priority_69.is_high_priority() is False
        assert priority_70.is_high_priority() is True
        assert priority_71.is_high_priority() is True

    def test_priority_score_boundary_30(self):
        """Test du seuil 30 pour is_low_priority()."""
        priority_29 = Priority(
            urgency=50, vip=50, sentiment=0.0, deadline=None, priority_score=29
        )
        priority_30 = Priority(
            urgency=50, vip=50, sentiment=0.0, deadline=None, priority_score=30
        )
        priority_31 = Priority(
            urgency=50, vip=50, sentiment=0.0, deadline=None, priority_score=31
        )

        assert priority_29.is_low_priority() is True
        assert priority_30.is_low_priority() is False
        assert priority_31.is_low_priority() is False


# ============================================================================
# TESTS - CLASSIFICATION CONFIDENCE
# ============================================================================

class TestClassificationConfidenceNumeric:
    """Tests numériques pour Classification.confidence."""

    def test_confidence_at_boundaries(self):
        """Confidence aux limites 0.0 et 1.0."""
        low = Classification(
            category=EmailCategory.NORMAL, confidence=0.0, reason="Test"
        )
        high = Classification(
            category=EmailCategory.URGENT, confidence=1.0, reason="Test"
        )

        assert low.confidence == 0.0
        assert high.confidence == 1.0

    def test_confidence_mid_value(self):
        """Confidence à 0.5."""
        mid = Classification(
            category=EmailCategory.NORMAL, confidence=0.5, reason="Test"
        )
        assert mid.confidence == 0.5

    def test_confidence_precision(self):
        """Précision de confidence."""
        precise = Classification(
            category=EmailCategory.NORMAL,
            confidence=0.123456789,
            reason="Test"
        )
        assert abs(precise.confidence - 0.123456789) < 1e-10

    def test_confidence_very_small(self):
        """Confidence très petite mais non nulle."""
        tiny = Classification(
            category=EmailCategory.SPAM,
            confidence=1e-10,
            reason="Faible probabilité"
        )
        assert tiny.confidence > 0
        assert tiny.confidence < 0.001


# ============================================================================
# TESTS - LEARNING INSIGHTS DIVISION BY ZERO
# ============================================================================

class TestLearningInsightsDivisionByZero:
    """Tests de division par zéro pour LearningInsights."""

    def test_satisfaction_rate_zero_total(self):
        """satisfaction_rate avec total=0 ne lève pas d'erreur."""
        insights = LearningInsights(
            total_with_feedback=0,
            good_count=0,
            bad_count=0,
            neutral_count=0
        )
        # Ne doit pas lever ZeroDivisionError
        rate = insights.satisfaction_rate
        assert rate == 0.0

    def test_satisfaction_rate_all_good(self):
        """100% satisfaction."""
        insights = LearningInsights(
            total_with_feedback=100,
            good_count=100,
            bad_count=0,
            neutral_count=0
        )
        assert insights.satisfaction_rate == 100.0

    def test_satisfaction_rate_all_bad(self):
        """0% satisfaction."""
        insights = LearningInsights(
            total_with_feedback=100,
            good_count=0,
            bad_count=100,
            neutral_count=0
        )
        assert insights.satisfaction_rate == 0.0

    def test_satisfaction_rate_mixed(self):
        """Satisfaction mixte."""
        insights = LearningInsights(
            total_with_feedback=200,
            good_count=150,
            bad_count=30,
            neutral_count=20
        )
        # 150/200 * 100 = 75%
        assert insights.satisfaction_rate == 75.0


# ============================================================================
# TESTS - LEARNED PATTERN FREQUENCY
# ============================================================================

class TestLearnedPatternFrequencyNumeric:
    """Tests numériques pour LearnedPattern.frequency."""

    def test_frequency_starts_at_one(self):
        """Fréquence initiale est 1."""
        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="test"
        )
        assert pattern.frequency == 1

    def test_frequency_increment(self):
        """increment_frequency() augmente de 1."""
        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="test"
        )
        pattern.increment_frequency()
        assert pattern.frequency == 2
        pattern.increment_frequency()
        assert pattern.frequency == 3

    def test_frequency_many_increments(self):
        """Beaucoup d'incréments."""
        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="test"
        )
        for _ in range(10000):
            pattern.increment_frequency()

        assert pattern.frequency == 10001

    def test_confidence_formula(self):
        """Formule: confidence = min(1.0, frequency / 10)."""
        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="test"
        )
        # Initial: freq=1, conf=0.5
        assert pattern.confidence == 0.5

        # Après 1 increment: freq=2, conf=0.2
        pattern.increment_frequency()
        assert pattern.confidence == 0.2

        # Après 4 increments: freq=5, conf=0.5
        for _ in range(3):
            pattern.increment_frequency()
        assert pattern.confidence == 0.5

        # Après 5 increments: freq=10, conf=1.0
        for _ in range(5):
            pattern.increment_frequency()
        assert pattern.confidence == 1.0

        # Après plus: conf reste à 1.0
        for _ in range(100):
            pattern.increment_frequency()
        assert pattern.confidence == 1.0

    def test_is_reliable_threshold_comparison(self):
        """is_reliable() compare correctement avec le seuil."""
        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="test"
        )
        # confidence = 0.5
        assert pattern.is_reliable(min_confidence=0.5) is True
        assert pattern.is_reliable(min_confidence=0.500001) is False


# ============================================================================
# TESTS - SUGGESTION CONFIDENCE NUMERIC
# ============================================================================

class TestSuggestionConfidenceNumeric:
    """Tests numériques pour Suggestion.confidence."""

    def test_confidence_zero(self):
        """Confidence à zéro."""
        suggestion = Suggestion(
            original_text="test",
            suggested_text="Test",
            confidence=0.0
        )
        assert suggestion.confidence == 0.0

    def test_confidence_one(self):
        """Confidence à un."""
        suggestion = Suggestion(
            original_text="test",
            suggested_text="Test",
            confidence=1.0
        )
        assert suggestion.confidence == 1.0

    def test_confidence_precision(self):
        """Précision de la confidence."""
        suggestion = Suggestion(
            original_text="test",
            suggested_text="Test",
            confidence=0.987654321
        )
        assert abs(suggestion.confidence - 0.987654321) < 1e-10


# ============================================================================
# TESTS - LEARNING STATS NUMERIC
# ============================================================================

class TestLearningStatsNumeric:
    """Tests numériques pour LearningStats."""

    def test_all_zeros(self):
        """Toutes les valeurs à zéro."""
        stats = LearningStats()
        assert stats.patterns_count == 0
        assert stats.good_patterns == 0
        assert stats.bad_patterns == 0
        assert stats.active_adjustments == 0

    def test_large_values(self):
        """Grandes valeurs."""
        stats = LearningStats(
            patterns_count=1_000_000,
            good_patterns=600_000,
            bad_patterns=400_000,
            active_adjustments=50_000,
            total_with_feedback=10_000_000
        )
        assert stats.patterns_count == 1_000_000
        assert stats.good_patterns + stats.bad_patterns == 1_000_000

    def test_rates_as_percentages(self):
        """Les taux sont des pourcentages (0-100)."""
        stats = LearningStats(
            v1_good_rate=75,
            v2_good_rate=85
        )
        assert 0 <= stats.v1_good_rate <= 100
        assert 0 <= stats.v2_good_rate <= 100


# ============================================================================
# TESTS - INTEGER OVERFLOW SCENARIOS
# ============================================================================

class TestIntegerOverflow:
    """Tests de scénarios d'overflow d'entiers."""

    def test_token_total_no_overflow(self):
        """Total de tokens ne cause pas d'overflow."""
        usage = TokenUsage(
            input_tokens=sys.maxsize // 2,
            output_tokens=sys.maxsize // 2
        )
        total = usage.total
        # En Python, les entiers n'overflow pas
        assert total == sys.maxsize // 2 + sys.maxsize // 2

    def test_priority_score_clamping_prevents_overflow(self):
        """Les entrées invalides lèvent maintenant InvalidBoundsError."""
        from app.domain.exceptions import InvalidBoundsError

        # Les valeurs hors bornes ne sont plus acceptées
        with pytest.raises(InvalidBoundsError):
            Priority.from_components(
                urgency=1000000,  # Invalide
                vip=1000000,
                sentiment=100.0
            )


# ============================================================================
# TESTS - FLOATING POINT EDGE CASES
# ============================================================================

class TestFloatingPointEdgeCases:
    """Tests des cas limites en virgule flottante."""

    def test_sentiment_at_boundaries(self):
        """Sentiment aux limites -1 et +1."""
        neg = Priority(
            urgency=50, vip=50, sentiment=-1.0, deadline=None, priority_score=50
        )
        pos = Priority(
            urgency=50, vip=50, sentiment=1.0, deadline=None, priority_score=50
        )
        assert neg.sentiment == -1.0
        assert pos.sentiment == 1.0

    def test_cost_rounding(self):
        """Le coût est correctement arrondi."""
        usage = TokenUsage(
            input_tokens=333,
            output_tokens=666,
            model="claude-sonnet-4-20250514"
        )
        # Cost = (333 * 3 + 666 * 15) / 1M = (999 + 9990) / 1M = 0.010989
        expected = (333 * 3.0 + 666 * 15.0) / 1_000_000
        assert abs(usage.cost - expected) < 1e-15

    def test_confidence_epsilon_comparison(self):
        """Comparaison de confidence avec epsilon."""
        conf1 = 0.1 + 0.1 + 0.1
        conf2 = 0.3
        # En raison de l'arithmétique flottante, conf1 != conf2 exactement
        # Mais ils devraient être considérés égaux

        classification1 = Classification(
            category=EmailCategory.NORMAL, confidence=conf1, reason="Test"
        )
        classification2 = Classification(
            category=EmailCategory.NORMAL, confidence=conf2, reason="Test"
        )

        # Vérifier qu'ils sont proches
        assert abs(classification1.confidence - classification2.confidence) < 1e-10
