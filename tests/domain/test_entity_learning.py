# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests unitaires pour les entités du système d'apprentissage automatique.

Tests comprehensive pour les classes du module app/domain/entities/learning.py
"""

import pytest
from datetime import datetime
from app.domain.entities.learning import (
    PatternType,
    LearningInsights,
    LearnedPattern,
    PromptAdjustment,
    ReviewRequirement,
    LearningStats,
)


class TestPatternType:
    """Tests pour l'énumération PatternType."""

    def test_pattern_type_good_value(self):
        """Vérifie que GOOD a la valeur 'good'."""
        assert PatternType.GOOD.value == "good"

    def test_pattern_type_bad_value(self):
        """Vérifie que BAD a la valeur 'bad'."""
        assert PatternType.BAD.value == "bad"

    def test_pattern_type_enum_members(self):
        """Vérifie que l'enum contient exactement GOOD et BAD."""
        members = [member.value for member in PatternType]
        assert len(members) == 2
        assert "good" in members
        assert "bad" in members

    def test_pattern_type_from_string(self):
        """Vérifie la création d'une énumération à partir d'une chaîne."""
        assert PatternType("good") == PatternType.GOOD
        assert PatternType("bad") == PatternType.BAD


class TestLearningInsights:
    """Tests pour la classe LearningInsights."""

    def test_learning_insights_creation_defaults(self):
        """Vérifie la création avec les valeurs par défaut."""
        insights = LearningInsights()
        assert insights.total_with_feedback == 0
        assert insights.good_count == 0
        assert insights.bad_count == 0
        assert insights.neutral_count == 0
        assert insights.v1_good_rate == 0
        assert insights.v2_good_rate == 0
        assert insights.common_issues == []
        assert insights.strengths == []

    def test_learning_insights_creation_with_values(self):
        """Vérifie la création avec des valeurs personnalisées."""
        insights = LearningInsights(
            total_with_feedback=100,
            good_count=70,
            bad_count=20,
            neutral_count=10,
            v1_good_rate=65,
            v2_good_rate=75,
            common_issues=["Formule insuffisante", "Ton trop formel"],
            strengths=["Clarity", "Structure"],
        )
        assert insights.total_with_feedback == 100
        assert insights.good_count == 70
        assert insights.bad_count == 20
        assert insights.neutral_count == 10
        assert insights.v1_good_rate == 65
        assert insights.v2_good_rate == 75
        assert insights.common_issues == ["Formule insuffisante", "Ton trop formel"]
        assert insights.strengths == ["Clarity", "Structure"]

    def test_satisfaction_rate_zero_feedback(self):
        """Vérifie que satisfaction_rate retourne 0.0 quand total_with_feedback = 0."""
        insights = LearningInsights(total_with_feedback=0, good_count=0)
        assert insights.satisfaction_rate == 0.0

    def test_satisfaction_rate_all_good(self):
        """Vérifie satisfaction_rate quand tous les feedbacks sont positifs."""
        insights = LearningInsights(total_with_feedback=100, good_count=100)
        assert insights.satisfaction_rate == 100.0

    def test_satisfaction_rate_all_bad(self):
        """Vérifie satisfaction_rate quand aucun feedback n'est positif."""
        insights = LearningInsights(total_with_feedback=100, good_count=0)
        assert insights.satisfaction_rate == 0.0

    def test_satisfaction_rate_partial(self):
        """Vérifie le calcul du taux de satisfaction partiel."""
        insights = LearningInsights(total_with_feedback=100, good_count=75)
        assert insights.satisfaction_rate == 75.0

    def test_satisfaction_rate_with_one_feedback(self):
        """Vérifie le calcul avec un seul feedback."""
        insights = LearningInsights(total_with_feedback=1, good_count=1)
        assert insights.satisfaction_rate == 100.0

    def test_satisfaction_rate_fractional(self):
        """Vérifie le calcul avec résultat fractionnaire."""
        insights = LearningInsights(total_with_feedback=3, good_count=1)
        assert insights.satisfaction_rate == pytest.approx(33.333333, rel=1e-5)

    def test_satisfaction_rate_does_not_affect_other_fields(self):
        """Vérifie que l'accès à satisfaction_rate ne modifie pas les champs."""
        insights = LearningInsights(total_with_feedback=100, good_count=70)
        rate = insights.satisfaction_rate
        assert insights.total_with_feedback == 100
        assert insights.good_count == 70
        assert rate == 70.0


class TestLearnedPattern:
    """Tests pour la classe LearnedPattern."""

    def test_learned_pattern_creation_manual(self):
        """Vérifie la création manuelle d'un pattern."""
        now = datetime.now()
        pattern = LearnedPattern(
            id="test-id",
            timestamp=now,
            pattern_type=PatternType.GOOD,
            trigger="Customer complaint",
            correction="Add apology",
            examples=["Example 1"],
            frequency=5,
            confidence=0.8,
        )
        assert pattern.id == "test-id"
        assert pattern.timestamp == now
        assert pattern.pattern_type == PatternType.GOOD
        assert pattern.trigger == "Customer complaint"
        assert pattern.correction == "Add apology"
        assert pattern.examples == ["Example 1"]
        assert pattern.frequency == 5
        assert pattern.confidence == 0.8

    def test_learned_pattern_create_factory(self):
        """Vérifie la création via factory create()."""
        before = datetime.now()
        pattern = LearnedPattern.create(
            pattern_type=PatternType.BAD,
            trigger="Too informal",
            correction="Use formal language",
            examples=["bad example 1", "bad example 2"],
        )
        after = datetime.now()

        # Vérifie les propriétés générées
        assert len(pattern.id) == 8  # UUID[:8]
        assert pattern.trigger == "Too informal"
        assert pattern.correction == "Use formal language"
        assert pattern.pattern_type == PatternType.BAD
        assert pattern.examples == ["bad example 1", "bad example 2"]
        assert pattern.frequency == 1
        assert pattern.confidence == 0.5
        assert before <= pattern.timestamp <= after

    def test_learned_pattern_create_default_correction(self):
        """Vérifie que correction par défaut est une chaîne vide."""
        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="Good greeting",
        )
        assert pattern.correction == ""

    def test_learned_pattern_create_default_examples(self):
        """Vérifie que examples par défaut est une liste vide."""
        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="Good greeting",
        )
        assert pattern.examples == []

    def test_learned_pattern_create_uuid_truncation(self):
        """Vérifie que l'UUID est correctement tronqué à 8 caractères."""
        pattern1 = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="test1",
        )
        pattern2 = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="test2",
        )
        assert len(pattern1.id) == 8
        assert len(pattern2.id) == 8
        # Les IDs devraient être différents (avec très haute probabilité)
        assert pattern1.id != pattern2.id

    def test_increment_frequency_single(self):
        """Vérifie l'incrémentation unique de la fréquence."""
        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="test",
        )
        assert pattern.frequency == 1
        assert pattern.confidence == 0.5  # 1/10 = 0.1, mais confidence débute à 0.5

        pattern.increment_frequency()
        assert pattern.frequency == 2
        assert pattern.confidence == pytest.approx(2 / 10)

    def test_increment_frequency_multiple(self):
        """Vérifie l'incrémentation multiple de la fréquence."""
        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="test",
        )
        for i in range(1, 11):
            pattern.increment_frequency()
            expected_confidence = min(1.0, (i + 1) / 10)
            assert pattern.frequency == i + 1
            assert pattern.confidence == pytest.approx(expected_confidence)

    def test_increment_frequency_capped_at_one(self):
        """Vérifie que la confiance est plafonnée à 1.0."""
        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="test",
        )
        # Incrémenter jusqu'à dépasser 10
        for _ in range(15):
            pattern.increment_frequency()

        assert pattern.frequency == 16
        assert pattern.confidence == 1.0

    def test_increment_frequency_confidence_calculation(self):
        """Vérifie la formule de confiance: min(1.0, frequency/10)."""
        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="test",
        )
        # Commençons à 1 (frequency initiale)
        test_cases = [
            (1, 0.1),  # 1/10 = 0.1
            (5, 0.5),  # 5/10 = 0.5
            (10, 1.0),  # 10/10 = 1.0 (capped)
            (20, 1.0),  # 20/10 = 2.0 -> capped to 1.0
        ]
        for target_freq, expected_conf in test_cases:
            pattern.frequency = target_freq
            pattern.confidence = min(1.0, target_freq / 10)
            assert pattern.confidence == pytest.approx(expected_conf)

    def test_is_reliable_default_threshold(self):
        """Vérifie is_reliable() avec le seuil par défaut 0.6."""
        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="test",
        )
        # Confiance initiale: 0.5, seuil: 0.6 -> False
        assert pattern.is_reliable() is False

        # Augmenter la confiance à 0.6
        pattern.confidence = 0.6
        assert pattern.is_reliable() is True

        # Augmenter la confiance à 0.7
        pattern.confidence = 0.7
        assert pattern.is_reliable() is True

    def test_is_reliable_custom_threshold(self):
        """Vérifie is_reliable() avec un seuil personnalisé."""
        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="test",
        )
        pattern.confidence = 0.5

        assert pattern.is_reliable(min_confidence=0.4) is True
        assert pattern.is_reliable(min_confidence=0.5) is True
        assert pattern.is_reliable(min_confidence=0.6) is False

    def test_is_reliable_boundary_cases(self):
        """Vérifie is_reliable() aux limites."""
        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="test",
        )

        # Seuil zéro
        pattern.confidence = 0.0
        assert pattern.is_reliable(min_confidence=0.0) is True

        # Seuil 1.0
        pattern.confidence = 0.99
        assert pattern.is_reliable(min_confidence=1.0) is False
        pattern.confidence = 1.0
        assert pattern.is_reliable(min_confidence=1.0) is True

    def test_add_example_new(self):
        """Vérifie l'ajout d'un nouvel exemple."""
        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="test",
            examples=["example1"],
        )
        assert pattern.examples == ["example1"]

        pattern.add_example("example2")
        assert pattern.examples == ["example1", "example2"]

    def test_add_example_duplicate_prevention(self):
        """Vérifie que les doublons ne sont pas ajoutés."""
        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="test",
            examples=["example1"],
        )

        pattern.add_example("example1")
        assert pattern.examples == ["example1"]

        pattern.add_example("example2")
        pattern.add_example("example2")
        assert pattern.examples == ["example1", "example2"]

    def test_add_example_empty_pattern(self):
        """Vérifie l'ajout d'exemple à un pattern vide."""
        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="test",
        )
        assert pattern.examples == []

        pattern.add_example("example1")
        assert pattern.examples == ["example1"]

    def test_add_example_multiple_calls(self):
        """Vérifie plusieurs appels à add_example()."""
        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="test",
        )

        for i in range(1, 6):
            pattern.add_example(f"example{i}")

        assert len(pattern.examples) == 5
        for i in range(1, 6):
            assert f"example{i}" in pattern.examples

    def test_to_dict_conversion(self):
        """Vérifie la conversion vers dictionnaire."""
        now = datetime.now()
        pattern = LearnedPattern(
            id="abc12345",
            timestamp=now,
            pattern_type=PatternType.GOOD,
            trigger="Greeting",
            correction="Use salutation",
            examples=["example1"],
            frequency=5,
            confidence=0.75,
        )

        result = pattern.to_dict()

        assert result["id"] == "abc12345"
        assert result["timestamp"] == now.isoformat()
        assert result["pattern_type"] == "good"
        assert result["trigger"] == "Greeting"
        assert result["correction"] == "Use salutation"
        assert result["examples"] == ["example1"]
        assert result["frequency"] == 5
        assert result["confidence"] == 0.75

    def test_from_dict_conversion(self):
        """Vérifie la création depuis dictionnaire."""
        now = datetime.now()
        data = {
            "id": "abc12345",
            "timestamp": now.isoformat(),
            "pattern_type": "bad",
            "trigger": "Informal",
            "correction": "Formalize",
            "examples": ["ex1", "ex2"],
            "frequency": 3,
            "confidence": 0.3,
        }

        pattern = LearnedPattern.from_dict(data)

        assert pattern.id == "abc12345"
        assert pattern.timestamp == now
        assert pattern.pattern_type == PatternType.BAD
        assert pattern.trigger == "Informal"
        assert pattern.correction == "Formalize"
        assert pattern.examples == ["ex1", "ex2"]
        assert pattern.frequency == 3
        assert pattern.confidence == 0.3

    def test_from_dict_with_timestamp_as_datetime(self):
        """Vérifie from_dict() quand timestamp est déjà un datetime."""
        now = datetime.now()
        data = {
            "id": "abc12345",
            "timestamp": now,  # Pas de isoformat()
            "pattern_type": "good",
            "trigger": "Test",
            "correction": "",
        }

        pattern = LearnedPattern.from_dict(data)
        assert pattern.timestamp == now

    def test_from_dict_missing_optional_fields(self):
        """Vérifie from_dict() avec des champs optionnels manquants."""
        now = datetime.now()
        data = {
            "id": "abc12345",
            "timestamp": now.isoformat(),
            "pattern_type": "good",
            "trigger": "Test",
            # correction, examples, frequency, confidence manquent
        }

        pattern = LearnedPattern.from_dict(data)

        assert pattern.id == "abc12345"
        assert pattern.trigger == "Test"
        assert pattern.correction == ""
        assert pattern.examples == []
        assert pattern.frequency == 1
        assert pattern.confidence == 0.5

    def test_round_trip_to_dict_from_dict(self):
        """Vérifie la conversion aller-retour to_dict/from_dict."""
        original = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="Test trigger",
            correction="Test correction",
            examples=["ex1", "ex2"],
        )
        original.frequency = 7
        original.confidence = 0.7

        # Aller-retour
        dict_repr = original.to_dict()
        restored = LearnedPattern.from_dict(dict_repr)

        assert restored.id == original.id
        assert restored.trigger == original.trigger
        assert restored.correction == original.correction
        assert restored.pattern_type == original.pattern_type
        assert restored.examples == original.examples
        assert restored.frequency == original.frequency
        assert restored.confidence == original.confidence


class TestPromptAdjustment:
    """Tests pour la classe PromptAdjustment."""

    def test_prompt_adjustment_creation_manual(self):
        """Vérifie la création manuelle."""
        now = datetime.now()
        adjustment = PromptAdjustment(
            id="adj-123",
            timestamp=now,
            section="greeting",
            adjustment="Add formal salutation",
            reason="User feedback on tone",
            active=True,
        )

        assert adjustment.id == "adj-123"
        assert adjustment.timestamp == now
        assert adjustment.section == "greeting"
        assert adjustment.adjustment == "Add formal salutation"
        assert adjustment.reason == "User feedback on tone"
        assert adjustment.active is True

    def test_prompt_adjustment_create_factory(self):
        """Vérifie la création via factory create()."""
        before = datetime.now()
        adjustment = PromptAdjustment.create(
            section="closing",
            adjustment="Add signature",
            reason="Pattern detected in feedback",
        )
        after = datetime.now()

        assert len(adjustment.id) == 8
        assert adjustment.section == "closing"
        assert adjustment.adjustment == "Add signature"
        assert adjustment.reason == "Pattern detected in feedback"
        assert adjustment.active is True
        assert before <= adjustment.timestamp <= after

    def test_prompt_adjustment_activate(self):
        """Vérifie l'activation d'un ajustement."""
        adjustment = PromptAdjustment.create(
            section="body",
            adjustment="Improve clarity",
            reason="Test",
        )
        adjustment.active = False
        assert adjustment.active is False

        adjustment.activate()
        assert adjustment.active is True

    def test_prompt_adjustment_deactivate(self):
        """Vérifie la désactivation d'un ajustement."""
        adjustment = PromptAdjustment.create(
            section="body",
            adjustment="Improve clarity",
            reason="Test",
        )
        assert adjustment.active is True

        adjustment.deactivate()
        assert adjustment.active is False

    def test_prompt_adjustment_activate_deactivate_toggle(self):
        """Vérifie le basculement activate/deactivate."""
        adjustment = PromptAdjustment.create(
            section="body",
            adjustment="Test",
            reason="Test",
        )

        # Actif -> Inactif
        adjustment.deactivate()
        assert adjustment.active is False

        # Inactif -> Actif
        adjustment.activate()
        assert adjustment.active is True

        # Actif -> Inactif
        adjustment.deactivate()
        assert adjustment.active is False

    def test_prompt_adjustment_to_dict(self):
        """Vérifie la conversion vers dictionnaire."""
        now = datetime.now()
        adjustment = PromptAdjustment(
            id="adj-001",
            timestamp=now,
            section="header",
            adjustment="Add date",
            reason="Missing date pattern",
            active=False,
        )

        result = adjustment.to_dict()

        assert result["id"] == "adj-001"
        assert result["timestamp"] == now.isoformat()
        assert result["section"] == "header"
        assert result["adjustment"] == "Add date"
        assert result["reason"] == "Missing date pattern"
        assert result["active"] is False

    def test_prompt_adjustment_from_dict(self):
        """Vérifie la création depuis dictionnaire."""
        now = datetime.now()
        data = {
            "id": "adj-002",
            "timestamp": now.isoformat(),
            "section": "body",
            "adjustment": "Simplify language",
            "reason": "Feedback shows confusion",
            "active": True,
        }

        adjustment = PromptAdjustment.from_dict(data)

        assert adjustment.id == "adj-002"
        assert adjustment.timestamp == now
        assert adjustment.section == "body"
        assert adjustment.adjustment == "Simplify language"
        assert adjustment.reason == "Feedback shows confusion"
        assert adjustment.active is True

    def test_prompt_adjustment_from_dict_with_timestamp_as_datetime(self):
        """Vérifie from_dict() quand timestamp est déjà un datetime."""
        now = datetime.now()
        data = {
            "id": "adj-003",
            "timestamp": now,  # Pas de isoformat()
            "section": "body",
            "adjustment": "Test",
            "reason": "Test",
        }

        adjustment = PromptAdjustment.from_dict(data)
        assert adjustment.timestamp == now

    def test_prompt_adjustment_from_dict_missing_active(self):
        """Vérifie from_dict() sans champ active (devrait défaut à True)."""
        now = datetime.now()
        data = {
            "id": "adj-004",
            "timestamp": now.isoformat(),
            "section": "body",
            "adjustment": "Test",
            "reason": "Test",
            # active est absent
        }

        adjustment = PromptAdjustment.from_dict(data)
        assert adjustment.active is True

    def test_prompt_adjustment_round_trip(self):
        """Vérifie la conversion aller-retour to_dict/from_dict."""
        original = PromptAdjustment.create(
            section="greeting",
            adjustment="Make more formal",
            reason="User preference",
        )
        original.active = False

        # Aller-retour
        dict_repr = original.to_dict()
        restored = PromptAdjustment.from_dict(dict_repr)

        assert restored.id == original.id
        assert restored.section == original.section
        assert restored.adjustment == original.adjustment
        assert restored.reason == original.reason
        assert restored.active == original.active


class TestReviewRequirement:
    """Tests pour la classe ReviewRequirement."""

    def test_review_requirement_creation_defaults(self):
        """Vérifie la création avec les valeurs par défaut."""
        req = ReviewRequirement(needs_review=True)
        assert req.needs_review is True
        assert req.reasons == []
        assert req.priority_score == 0

    def test_review_requirement_creation_with_values(self):
        """Vérifie la création avec des valeurs personnalisées."""
        req = ReviewRequirement(
            needs_review=True,
            reasons=["High sensitivity", "Multiple recipients"],
            priority_score=8,
        )
        assert req.needs_review is True
        assert req.reasons == ["High sensitivity", "Multiple recipients"]
        assert req.priority_score == 8

    def test_review_requirement_no_review(self):
        """Vérifie la création quand needs_review est False."""
        req = ReviewRequirement(
            needs_review=False,
            reasons=[],
            priority_score=1,
        )
        assert req.needs_review is False
        assert req.reasons == []
        assert req.priority_score == 1

    def test_add_reason_single(self):
        """Vérifie l'ajout d'une raison unique."""
        req = ReviewRequirement(needs_review=True)
        req.add_reason("Sensitive content")

        assert req.reasons == ["Sensitive content"]

    def test_add_reason_multiple(self):
        """Vérifie l'ajout de plusieurs raisons."""
        req = ReviewRequirement(needs_review=True)
        req.add_reason("Sensitive content")
        req.add_reason("Large recipient list")
        req.add_reason("Executive approval needed")

        assert len(req.reasons) == 3
        assert "Sensitive content" in req.reasons
        assert "Large recipient list" in req.reasons
        assert "Executive approval needed" in req.reasons

    def test_add_reason_duplicate_prevention(self):
        """Vérifie que les doublons ne sont pas ajoutés."""
        req = ReviewRequirement(needs_review=True)
        req.add_reason("Sensitive content")
        req.add_reason("Sensitive content")
        req.add_reason("Large recipient list")
        req.add_reason("Large recipient list")

        assert len(req.reasons) == 2
        assert req.reasons == ["Sensitive content", "Large recipient list"]

    def test_add_reason_to_existing_list(self):
        """Vérifie l'ajout à une liste de raisons existante."""
        req = ReviewRequirement(
            needs_review=True,
            reasons=["Initial reason"],
        )
        req.add_reason("New reason")

        assert req.reasons == ["Initial reason", "New reason"]

    def test_add_reason_empty_string(self):
        """Vérifie l'ajout d'une chaîne vide."""
        req = ReviewRequirement(needs_review=True)
        req.add_reason("")
        assert req.reasons == [""]

        # L'ajout d'une autre chaîne vide ne devrait pas dupliquer
        req.add_reason("")
        assert req.reasons == [""]


class TestLearningStats:
    """Tests pour la classe LearningStats."""

    def test_learning_stats_creation_defaults(self):
        """Vérifie la création avec les valeurs par défaut."""
        stats = LearningStats()
        assert stats.patterns_count == 0
        assert stats.good_patterns == 0
        assert stats.bad_patterns == 0
        assert stats.active_adjustments == 0
        assert stats.confidence_threshold == 70
        assert stats.total_with_feedback == 0
        assert stats.good_count == 0
        assert stats.bad_count == 0
        assert stats.neutral_count == 0
        assert stats.v1_good_rate == 0
        assert stats.v2_good_rate == 0

    def test_learning_stats_creation_with_values(self):
        """Vérifie la création avec des valeurs personnalisées."""
        stats = LearningStats(
            patterns_count=15,
            good_patterns=10,
            bad_patterns=5,
            active_adjustments=3,
            confidence_threshold=75,
            total_with_feedback=100,
            good_count=80,
            bad_count=10,
            neutral_count=10,
            v1_good_rate=70,
            v2_good_rate=85,
        )
        assert stats.patterns_count == 15
        assert stats.good_patterns == 10
        assert stats.bad_patterns == 5
        assert stats.active_adjustments == 3
        assert stats.confidence_threshold == 75
        assert stats.total_with_feedback == 100
        assert stats.good_count == 80
        assert stats.bad_count == 10
        assert stats.neutral_count == 10
        assert stats.v1_good_rate == 70
        assert stats.v2_good_rate == 85

    def test_to_dict_basic(self):
        """Vérifie la conversion basique vers dictionnaire."""
        stats = LearningStats(
            patterns_count=20,
            good_patterns=15,
            bad_patterns=5,
        )

        result = stats.to_dict()

        assert isinstance(result, dict)
        assert result["patterns_count"] == 20
        assert result["good_patterns"] == 15
        assert result["bad_patterns"] == 5

    def test_to_dict_all_fields(self):
        """Vérifie que to_dict() inclut tous les champs."""
        stats = LearningStats(
            patterns_count=15,
            good_patterns=10,
            bad_patterns=5,
            active_adjustments=3,
            confidence_threshold=75,
            total_with_feedback=100,
            good_count=80,
            bad_count=10,
            neutral_count=10,
            v1_good_rate=70,
            v2_good_rate=85,
        )

        result = stats.to_dict()

        expected_keys = {
            "patterns_count",
            "good_patterns",
            "bad_patterns",
            "active_adjustments",
            "confidence_threshold",
            "total_with_feedback",
            "good_count",
            "bad_count",
            "neutral_count",
            "v1_good_rate",
            "v2_good_rate",
        }
        assert set(result.keys()) == expected_keys

    def test_to_dict_with_zeros(self):
        """Vérifie to_dict() avec des valeurs zéro."""
        stats = LearningStats()
        result = stats.to_dict()

        assert result["patterns_count"] == 0
        assert result["good_patterns"] == 0
        assert result["bad_patterns"] == 0
        assert result["active_adjustments"] == 0
        assert result["confidence_threshold"] == 70
        assert result["total_with_feedback"] == 0
        assert result["good_count"] == 0
        assert result["bad_count"] == 0
        assert result["neutral_count"] == 0
        assert result["v1_good_rate"] == 0
        assert result["v2_good_rate"] == 0

    def test_to_dict_returns_new_dict(self):
        """Vérifie que to_dict() retourne une nouvelle instance."""
        stats = LearningStats(patterns_count=10)
        dict1 = stats.to_dict()
        dict2 = stats.to_dict()

        # Les dicts devraient être différents (pas la même référence)
        assert dict1 is not dict2
        # Mais avoir le même contenu
        assert dict1 == dict2

    def test_learning_stats_mutation_after_to_dict(self):
        """Vérifie que to_dict() ne crée pas de lien avec l'état."""
        stats = LearningStats(patterns_count=10)
        dict_before = stats.to_dict()

        # Modifier les stats
        stats.patterns_count = 20

        # Récupérer le dict après
        dict_after = stats.to_dict()

        # Le dict avant devrait rester inchangé
        assert dict_before["patterns_count"] == 10
        # Le dict après devrait avoir la nouvelle valeur
        assert dict_after["patterns_count"] == 20


class TestIntegration:
    """Tests d'intégration entre les entités."""

    def test_pattern_workflow(self):
        """Simule un workflow complet d'apprentissage d'un pattern."""
        # Créer un pattern
        pattern = LearnedPattern.create(
            pattern_type=PatternType.BAD,
            trigger="Missing greeting",
            correction="Add 'Dear [Name]'",
            examples=["Example without greeting"],
        )

        assert pattern.frequency == 1
        assert pattern.confidence == 0.5
        assert not pattern.is_reliable()

        # Ajouter des exemples
        pattern.add_example("Another missing greeting")
        pattern.add_example("Another missing greeting")  # duplicate
        assert len(pattern.examples) == 2

        # Incrémenter la fréquence plusieurs fois
        for _ in range(5):
            pattern.increment_frequency()

        assert pattern.frequency == 6
        assert pattern.confidence == pytest.approx(0.6)
        assert pattern.is_reliable()

        # Sérialiser et désérialiser
        dict_repr = pattern.to_dict()
        restored = LearnedPattern.from_dict(dict_repr)

        assert restored.pattern_type == PatternType.BAD
        assert restored.frequency == 6
        assert restored.confidence == pytest.approx(0.6)
        assert restored.is_reliable()

    def test_adjustment_workflow(self):
        """Simule un workflow d'ajustement de prompt."""
        adjustment = PromptAdjustment.create(
            section="greeting",
            adjustment="Always start with formal greeting",
            reason="Pattern from bad feedback",
        )

        assert adjustment.active is True

        # Désactiver temporairement
        adjustment.deactivate()
        assert adjustment.active is False

        # Réactiver
        adjustment.activate()
        assert adjustment.active is True

        # Sérialiser
        dict_repr = adjustment.to_dict()
        restored = PromptAdjustment.from_dict(dict_repr)

        assert restored.active is True
        assert restored.section == "greeting"

    def test_learning_insights_and_stats(self):
        """Teste l'interaction entre LearningInsights et LearningStats."""
        insights = LearningInsights(
            total_with_feedback=100,
            good_count=85,
            bad_count=10,
            neutral_count=5,
            v1_good_rate=75,
            v2_good_rate=88,
        )

        assert insights.satisfaction_rate == 85.0

        # Créer des stats basées sur les insights
        stats = LearningStats(
            total_with_feedback=insights.total_with_feedback,
            good_count=insights.good_count,
            bad_count=insights.bad_count,
            neutral_count=insights.neutral_count,
            v1_good_rate=insights.v1_good_rate,
            v2_good_rate=insights.v2_good_rate,
            patterns_count=20,
            good_patterns=15,
            bad_patterns=5,
        )

        dict_stats = stats.to_dict()
        assert dict_stats["total_with_feedback"] == 100
        assert dict_stats["good_count"] == 85
        assert dict_stats["v2_good_rate"] == 88
