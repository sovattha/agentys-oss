# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests unitaires pour les entités du système d'analytics.

Tests des entités QualityScore, HumanEdit, PerformanceMetrics,
QualityMetrics et AIVsHumanComparison.
"""

import pytest
from app.domain.entities.analytics import (
    QualityScore,
    HumanEdit,
    PerformanceMetrics,
    QualityMetrics,
    AIVsHumanComparison,
)


class TestQualityScore:
    """Tests pour la classe QualityScore."""

    def test_quality_score_creation_with_defaults(self):
        """Test la création d'un QualityScore avec valeurs par défaut."""
        score = QualityScore(draft_id="draft_123")

        assert score.draft_id == "draft_123"
        assert score.overall_score == 0.0
        assert score.tone_score == 0.0
        assert score.completeness_score == 0.0
        assert score.professionalism_score == 0.0
        assert score.relevance_score == 0.0
        assert score.user_rating is None
        assert score.was_edited is False
        assert score.edit_ratio == 0.0
        assert score.timestamp == ""

    def test_quality_score_creation_with_all_values(self):
        """Test la création d'un QualityScore avec toutes les valeurs."""
        score = QualityScore(
            draft_id="draft_456",
            overall_score=85.5,
            tone_score=90.0,
            completeness_score=80.0,
            professionalism_score=88.0,
            relevance_score=85.0,
            user_rating=4,
            was_edited=True,
            edit_ratio=0.15,
            timestamp="2026-03-24T10:30:00Z"
        )

        assert score.draft_id == "draft_456"
        assert score.overall_score == 85.5
        assert score.tone_score == 90.0
        assert score.completeness_score == 80.0
        assert score.professionalism_score == 88.0
        assert score.relevance_score == 85.0
        assert score.user_rating == 4
        assert score.was_edited is True
        assert score.edit_ratio == 0.15
        assert score.timestamp == "2026-03-24T10:30:00Z"

    def test_quality_level_excellent(self):
        """Test quality_level pour score >= 90 (excellent)."""
        score = QualityScore(draft_id="draft_1", overall_score=90.0)
        assert score.quality_level == "excellent"

        score = QualityScore(draft_id="draft_2", overall_score=95.5)
        assert score.quality_level == "excellent"

        score = QualityScore(draft_id="draft_3", overall_score=100.0)
        assert score.quality_level == "excellent"

    def test_quality_level_excellent_boundary(self):
        """Test quality_level à la limite inférieure de excellent (90)."""
        score = QualityScore(draft_id="draft_boundary", overall_score=90.0)
        assert score.quality_level == "excellent"

    def test_quality_level_good(self):
        """Test quality_level pour score 75-89 (good)."""
        score = QualityScore(draft_id="draft_1", overall_score=75.0)
        assert score.quality_level == "good"

        score = QualityScore(draft_id="draft_2", overall_score=80.0)
        assert score.quality_level == "good"

        score = QualityScore(draft_id="draft_3", overall_score=89.9)
        assert score.quality_level == "good"

    def test_quality_level_good_boundaries(self):
        """Test quality_level à la limite inférieure et supérieure de good."""
        score = QualityScore(draft_id="draft_min", overall_score=75.0)
        assert score.quality_level == "good"

        score = QualityScore(draft_id="draft_max", overall_score=89.99)
        assert score.quality_level == "good"

    def test_quality_level_acceptable(self):
        """Test quality_level pour score 50-74 (acceptable)."""
        score = QualityScore(draft_id="draft_1", overall_score=50.0)
        assert score.quality_level == "acceptable"

        score = QualityScore(draft_id="draft_2", overall_score=60.0)
        assert score.quality_level == "acceptable"

        score = QualityScore(draft_id="draft_3", overall_score=74.9)
        assert score.quality_level == "acceptable"

    def test_quality_level_acceptable_boundaries(self):
        """Test quality_level à la limite inférieure et supérieure de acceptable."""
        score = QualityScore(draft_id="draft_min", overall_score=50.0)
        assert score.quality_level == "acceptable"

        score = QualityScore(draft_id="draft_max", overall_score=74.99)
        assert score.quality_level == "acceptable"

    def test_quality_level_needs_improvement(self):
        """Test quality_level pour score < 50 (needs_improvement)."""
        score = QualityScore(draft_id="draft_1", overall_score=0.0)
        assert score.quality_level == "needs_improvement"

        score = QualityScore(draft_id="draft_2", overall_score=25.0)
        assert score.quality_level == "needs_improvement"

        score = QualityScore(draft_id="draft_3", overall_score=49.9)
        assert score.quality_level == "needs_improvement"

    def test_quality_level_needs_improvement_boundary(self):
        """Test quality_level à la limite supérieure de needs_improvement."""
        score = QualityScore(draft_id="draft_boundary", overall_score=49.99)
        assert score.quality_level == "needs_improvement"

    def test_quality_level_all_boundary_transitions(self):
        """Test les transitions à chaque limite de catégorie."""
        # Transition needs_improvement -> acceptable (49.99 -> 50.0)
        score_low = QualityScore(draft_id="low", overall_score=49.99)
        score_high = QualityScore(draft_id="high", overall_score=50.0)
        assert score_low.quality_level == "needs_improvement"
        assert score_high.quality_level == "acceptable"

        # Transition acceptable -> good (74.99 -> 75.0)
        score_low = QualityScore(draft_id="low", overall_score=74.99)
        score_high = QualityScore(draft_id="high", overall_score=75.0)
        assert score_low.quality_level == "acceptable"
        assert score_high.quality_level == "good"

        # Transition good -> excellent (89.99 -> 90.0)
        score_low = QualityScore(draft_id="low", overall_score=89.99)
        score_high = QualityScore(draft_id="high", overall_score=90.0)
        assert score_low.quality_level == "good"
        assert score_high.quality_level == "excellent"

    def test_quality_score_with_user_rating_values(self):
        """Test QualityScore avec différentes ratings utilisateur."""
        for rating in [1, 2, 3, 4, 5]:
            score = QualityScore(draft_id="draft", user_rating=rating)
            assert score.user_rating == rating

    def test_quality_score_with_edited_flag(self):
        """Test QualityScore avec le flag was_edited."""
        score_not_edited = QualityScore(draft_id="d1", was_edited=False)
        score_edited = QualityScore(draft_id="d2", was_edited=True)

        assert score_not_edited.was_edited is False
        assert score_edited.was_edited is True


class TestHumanEdit:
    """Tests pour la classe HumanEdit."""

    def test_human_edit_creation_with_defaults(self):
        """Test la création d'un HumanEdit avec valeurs par défaut."""
        edit = HumanEdit(
            id="edit_123",
            draft_id="draft_456",
            original_draft="Hello world",
            edited_draft="Hello beautiful world"
        )

        assert edit.id == "edit_123"
        assert edit.draft_id == "draft_456"
        assert edit.original_draft == "Hello world"
        assert edit.edited_draft == "Hello beautiful world"
        assert edit.edit_distance == 0
        assert edit.edit_ratio == 0.0
        assert edit.word_changes == 0
        assert edit.timestamp == ""
        assert edit.editor_notes == ""

    def test_human_edit_creation_with_all_values(self):
        """Test la création d'un HumanEdit avec toutes les valeurs."""
        edit = HumanEdit(
            id="edit_789",
            draft_id="draft_101",
            original_draft="Original text",
            edited_draft="Modified text",
            edit_distance=5,
            edit_ratio=0.25,
            word_changes=2,
            timestamp="2026-03-24T11:00:00Z",
            editor_notes="Fixed grammar and tone"
        )

        assert edit.id == "edit_789"
        assert edit.draft_id == "draft_101"
        assert edit.original_draft == "Original text"
        assert edit.edited_draft == "Modified text"
        assert edit.edit_distance == 5
        assert edit.edit_ratio == 0.25
        assert edit.word_changes == 2
        assert edit.timestamp == "2026-03-24T11:00:00Z"
        assert edit.editor_notes == "Fixed grammar and tone"

    def test_similarity_property_no_changes(self):
        """Test similarity property quand edit_ratio = 0 (pas de changement)."""
        edit = HumanEdit(
            id="e1",
            draft_id="d1",
            original_draft="text",
            edited_draft="text",
            edit_ratio=0.0
        )

        assert edit.similarity == 1.0

    def test_similarity_property_complete_change(self):
        """Test similarity property quand edit_ratio = 1 (changement total)."""
        edit = HumanEdit(
            id="e2",
            draft_id="d2",
            original_draft="original",
            edited_draft="completely different",
            edit_ratio=1.0
        )

        assert edit.similarity == 0.0

    def test_similarity_property_partial_change(self):
        """Test similarity property avec changements partiels."""
        test_cases = [
            (0.1, 0.9),
            (0.25, 0.75),
            (0.5, 0.5),
            (0.75, 0.25),
            (0.9, 0.1),
        ]

        for edit_ratio, expected_similarity in test_cases:
            edit = HumanEdit(
                id="e",
                draft_id="d",
                original_draft="text",
                edited_draft="modified",
                edit_ratio=edit_ratio
            )
            assert edit.similarity == pytest.approx(expected_similarity)

    def test_similarity_property_formula(self):
        """Test que similarity = 1.0 - edit_ratio pour tous les cas."""
        for edit_ratio in [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]:
            edit = HumanEdit(
                id="e",
                draft_id="d",
                original_draft="x",
                edited_draft="y",
                edit_ratio=edit_ratio
            )
            assert edit.similarity == pytest.approx(1.0 - edit_ratio)


class TestPerformanceMetrics:
    """Tests pour la classe PerformanceMetrics."""

    def test_performance_metrics_creation_minimal(self):
        """Test la création minimal de PerformanceMetrics."""
        metrics = PerformanceMetrics(
            period_start="2026-03-01",
            period_end="2026-03-31"
        )

        assert metrics.period_start == "2026-03-01"
        assert metrics.period_end == "2026-03-31"
        assert metrics.total_drafts == 0
        assert metrics.avg_quality_score == 0.0
        assert metrics.avg_user_rating == 0.0
        assert metrics.edit_rate == 0.0
        assert metrics.avg_edit_ratio == 0.0
        assert metrics.v1_acceptance_rate == 0.0
        assert metrics.response_time_avg == 0.0
        assert metrics.improvement_trend == 0.0

    def test_performance_metrics_creation_full(self):
        """Test la création complète de PerformanceMetrics."""
        metrics = PerformanceMetrics(
            period_start="2026-03-01",
            period_end="2026-03-31",
            total_drafts=150,
            avg_quality_score=82.5,
            avg_user_rating=4.2,
            edit_rate=0.30,
            avg_edit_ratio=0.15,
            v1_acceptance_rate=0.75,
            response_time_avg=2.5,
            improvement_trend=0.08
        )

        assert metrics.period_start == "2026-03-01"
        assert metrics.period_end == "2026-03-31"
        assert metrics.total_drafts == 150
        assert metrics.avg_quality_score == 82.5
        assert metrics.avg_user_rating == 4.2
        assert metrics.edit_rate == 0.30
        assert metrics.avg_edit_ratio == 0.15
        assert metrics.v1_acceptance_rate == 0.75
        assert metrics.response_time_avg == 2.5
        assert metrics.improvement_trend == 0.08

    def test_performance_metrics_default_factories(self):
        """Test que les valeurs par défaut sont correctement initialisées."""
        m1 = PerformanceMetrics(period_start="2026-01-01", period_end="2026-01-31")
        m2 = PerformanceMetrics(period_start="2026-01-01", period_end="2026-01-31")

        # Vérifier que ce ne sont pas les mêmes objets (indépendance)
        assert m1 is not m2
        assert m1.total_drafts == m2.total_drafts


class TestQualityMetrics:
    """Tests pour la classe QualityMetrics."""

    def test_quality_metrics_creation_defaults(self):
        """Test la création de QualityMetrics avec valeurs par défaut."""
        metrics = QualityMetrics()

        assert metrics.avg_score == 0.0
        assert metrics.total_drafts == 0
        assert metrics.excellent_count == 0
        assert metrics.good_count == 0
        assert metrics.acceptable_count == 0
        assert metrics.needs_improvement_count == 0
        assert metrics.avg_user_rating == 0.0
        assert metrics.rated_count == 0

    def test_quality_metrics_creation_full(self):
        """Test la création complète de QualityMetrics."""
        metrics = QualityMetrics(
            avg_score=78.5,
            total_drafts=200,
            excellent_count=50,
            good_count=80,
            acceptable_count=50,
            needs_improvement_count=20,
            avg_user_rating=4.1,
            rated_count=150
        )

        assert metrics.avg_score == 78.5
        assert metrics.total_drafts == 200
        assert metrics.excellent_count == 50
        assert metrics.good_count == 80
        assert metrics.acceptable_count == 50
        assert metrics.needs_improvement_count == 20
        assert metrics.avg_user_rating == 4.1
        assert metrics.rated_count == 150

    def test_quality_metrics_distribution(self):
        """Test des distributions réalistes de qualité."""
        # Distribution pyramidale typique
        metrics = QualityMetrics(
            total_drafts=100,
            excellent_count=10,
            good_count=30,
            acceptable_count=40,
            needs_improvement_count=20
        )

        assert (metrics.excellent_count + metrics.good_count +
                metrics.acceptable_count + metrics.needs_improvement_count) <= metrics.total_drafts


class TestAIVsHumanComparison:
    """Tests pour la classe AIVsHumanComparison."""

    def test_ai_vs_human_creation_defaults(self):
        """Test la création d'AIVsHumanComparison avec valeurs par défaut."""
        comparison = AIVsHumanComparison()

        assert comparison.total_drafts == 0
        assert comparison.edited_count == 0
        assert comparison.edit_rate == 0.0
        assert comparison.avg_edit_ratio == 0.0
        assert comparison.avg_word_changes == 0.0
        assert comparison.common_edit_types == []

    def test_ai_vs_human_creation_full(self):
        """Test la création complète d'AIVsHumanComparison."""
        comparison = AIVsHumanComparison(
            total_drafts=500,
            edited_count=150,
            edit_rate=0.30,
            avg_edit_ratio=0.18,
            avg_word_changes=12.5,
            common_edit_types=["grammar", "tone", "clarity"]
        )

        assert comparison.total_drafts == 500
        assert comparison.edited_count == 150
        assert comparison.edit_rate == 0.30
        assert comparison.avg_edit_ratio == 0.18
        assert comparison.avg_word_changes == 12.5
        assert comparison.common_edit_types == ["grammar", "tone", "clarity"]

    def test_ai_vs_human_common_edit_types_list(self):
        """Test que common_edit_types est bien une liste modifiable."""
        comparison = AIVsHumanComparison()

        assert isinstance(comparison.common_edit_types, list)
        assert len(comparison.common_edit_types) == 0

        # Vérifier l'indépendance des instances
        comparison2 = AIVsHumanComparison()
        comparison.common_edit_types.append("test")
        assert "test" not in comparison2.common_edit_types

    def test_ai_vs_human_comparison_realistic_values(self):
        """Test des valeurs réalistes de comparaison."""
        comparison = AIVsHumanComparison(
            total_drafts=1000,
            edited_count=250,
            edit_rate=0.25,
            avg_edit_ratio=0.12,
            avg_word_changes=8.5,
            common_edit_types=["tone", "grammar", "clarity", "conciseness"]
        )

        # Vérifier la cohérence (edited_count <= total_drafts)
        assert comparison.edited_count <= comparison.total_drafts
        # Vérifier que edit_rate correspond à peu près
        assert comparison.edit_rate == pytest.approx(
            comparison.edited_count / comparison.total_drafts,
            abs=0.01
        ) or (comparison.total_drafts == 0)


class TestQualityScoreEdgeCases:
    """Tests pour les cas limites et les valeurs extrêmes."""

    def test_quality_score_with_zero_score(self):
        """Test QualityScore avec un score de 0."""
        score = QualityScore(draft_id="d0", overall_score=0.0)
        assert score.quality_level == "needs_improvement"

    def test_quality_score_with_max_score(self):
        """Test QualityScore avec un score de 100."""
        score = QualityScore(draft_id="d100", overall_score=100.0)
        assert score.quality_level == "excellent"

    def test_quality_score_with_negative_rating(self):
        """Test que user_rating peut être négatif si fourni."""
        score = QualityScore(draft_id="d", user_rating=-1)
        assert score.user_rating == -1

    def test_quality_score_with_high_rating(self):
        """Test que user_rating peut être > 5 si fourni."""
        score = QualityScore(draft_id="d", user_rating=10)
        assert score.user_rating == 10

    def test_quality_score_very_precise_boundaries(self):
        """Test les limites avec haute précision."""
        epsilon = 0.00001

        # Juste avant excellent
        score = QualityScore(draft_id="d", overall_score=90.0 - epsilon)
        assert score.quality_level == "good"

        # Juste à excellent
        score = QualityScore(draft_id="d", overall_score=90.0)
        assert score.quality_level == "excellent"

        # Juste après excellent
        score = QualityScore(draft_id="d", overall_score=90.0 + epsilon)
        assert score.quality_level == "excellent"


class TestHumanEditEdgeCases:
    """Tests pour les cas limites de HumanEdit."""

    def test_human_edit_with_empty_strings(self):
        """Test HumanEdit avec des chaînes vides."""
        edit = HumanEdit(
            id="",
            draft_id="",
            original_draft="",
            edited_draft=""
        )

        assert edit.id == ""
        assert edit.draft_id == ""
        assert edit.similarity == 1.0  # edit_ratio est 0.0 par défaut

    def test_human_edit_with_large_edit_distance(self):
        """Test HumanEdit avec une grande distance de Levenshtein."""
        edit = HumanEdit(
            id="e",
            draft_id="d",
            original_draft="x" * 1000,
            edited_draft="y" * 1000,
            edit_distance=1000,
            edit_ratio=0.99
        )

        assert edit.similarity == pytest.approx(0.01)

    def test_human_edit_with_negative_edit_ratio(self):
        """Test que edit_ratio peut techniquement être négatif (bien que peu probable)."""
        edit = HumanEdit(
            id="e",
            draft_id="d",
            original_draft="x",
            edited_draft="y",
            edit_ratio=-0.1
        )

        assert edit.similarity == 1.1


class TestEntitiesImmutability:
    """Tests pour vérifier le comportement des dataclasses."""

    def test_quality_score_is_mutable(self):
        """Test que QualityScore est mutable après création."""
        score = QualityScore(draft_id="d")
        score.overall_score = 85.0
        assert score.overall_score == 85.0

    def test_human_edit_is_mutable(self):
        """Test que HumanEdit est mutable après création."""
        edit = HumanEdit(id="e", draft_id="d", original_draft="x", edited_draft="y")
        edit.editor_notes = "Updated notes"
        assert edit.editor_notes == "Updated notes"
