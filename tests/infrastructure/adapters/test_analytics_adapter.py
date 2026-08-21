# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests TDD pour LegacyAnalyticsAdapter.

Ce module teste:
1. Implementation du port AnalyticsPort
2. Conversions QualityScore <-> Dict
3. Conversions HumanEdit <-> Dict
4. Operations de metriques de qualite
5. Comparaisons IA vs humain
6. Metriques de performance
7. Tendances et statistiques
8. Edge cases et gestion des erreurs

TDD: Tests ecrits pour couvrir 100% du code.
Clean Architecture: Infrastructure layer (Adapters).
"""

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.infrastructure.adapters.analytics_adapter import LegacyAnalyticsAdapter
from app.domain.entities.analytics import (
    QualityScore,
    QualityMetrics,
    AIVsHumanComparison,
    HumanEdit,
    PerformanceMetrics,
)
from app.domain.ports.analytics_port import AnalyticsPort


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def temp_dir(tmp_path) -> Path:
    """Cree un repertoire temporaire pour les donnees."""
    return tmp_path / "analytics"


@pytest.fixture
def adapter(temp_dir) -> LegacyAnalyticsAdapter:
    """Cree un adapter avec repertoire temporaire."""
    return LegacyAnalyticsAdapter(data_dir=temp_dir)


@pytest.fixture
def sample_score() -> QualityScore:
    """Cree un score de qualite de test."""
    return QualityScore(
        draft_id="draft-123",
        overall_score=85.0,
        tone_score=90.0,
        completeness_score=80.0,
        professionalism_score=85.0,
        relevance_score=85.0,
        user_rating=4,
        was_edited=True,
        edit_ratio=0.15,
        timestamp="2024-01-15T10:30:00",
    )


@pytest.fixture
def sample_edit() -> HumanEdit:
    """Cree une modification humaine de test."""
    return HumanEdit(
        id="edit-456",
        draft_id="draft-123",
        original_draft="Hello world, how are you?",
        edited_draft="Hello there, how are you doing?",
        edit_distance=10,
        edit_ratio=0.25,
        word_changes=2,
        timestamp="2024-01-15T11:00:00",
        editor_notes="Changed greeting",
    )


@pytest.fixture
def excellent_score() -> QualityScore:
    """Score excellent (>=90)."""
    return QualityScore(
        draft_id="draft-excellent",
        overall_score=95.0,
        timestamp="2024-01-15T12:00:00",
    )


@pytest.fixture
def good_score() -> QualityScore:
    """Score bon (>=75, <90)."""
    return QualityScore(
        draft_id="draft-good",
        overall_score=80.0,
        timestamp="2024-01-15T12:00:00",
    )


@pytest.fixture
def acceptable_score() -> QualityScore:
    """Score acceptable (>=50, <75)."""
    return QualityScore(
        draft_id="draft-acceptable",
        overall_score=60.0,
        timestamp="2024-01-15T12:00:00",
    )


@pytest.fixture
def needs_improvement_score() -> QualityScore:
    """Score a ameliorer (<50)."""
    return QualityScore(
        draft_id="draft-needs-improvement",
        overall_score=40.0,
        timestamp="2024-01-15T12:00:00",
    )


# =============================================================================
# TESTS - IMPLEMENTS PORT
# =============================================================================


class TestImplementsAnalyticsPort:
    """Tests verifiant que LegacyAnalyticsAdapter implemente AnalyticsPort."""

    def test_inherits_from_analytics_port(self, adapter):
        """L'adapter herite de AnalyticsPort."""
        assert isinstance(adapter, AnalyticsPort)

    def test_has_get_quality_metrics_method(self, adapter):
        """Methode get_quality_metrics existe."""
        assert hasattr(adapter, "get_quality_metrics")
        assert callable(adapter.get_quality_metrics)

    def test_has_get_detailed_quality_metrics_method(self, adapter):
        """Methode get_detailed_quality_metrics existe."""
        assert hasattr(adapter, "get_detailed_quality_metrics")
        assert callable(adapter.get_detailed_quality_metrics)

    def test_has_record_quality_score_method(self, adapter):
        """Methode record_quality_score existe."""
        assert hasattr(adapter, "record_quality_score")
        assert callable(adapter.record_quality_score)

    def test_has_get_quality_score_method(self, adapter):
        """Methode get_quality_score existe."""
        assert hasattr(adapter, "get_quality_score")
        assert callable(adapter.get_quality_score)

    def test_has_get_ai_vs_human_comparison_method(self, adapter):
        """Methode get_ai_vs_human_comparison existe."""
        assert hasattr(adapter, "get_ai_vs_human_comparison")
        assert callable(adapter.get_ai_vs_human_comparison)

    def test_has_get_detailed_comparison_method(self, adapter):
        """Methode get_detailed_comparison existe."""
        assert hasattr(adapter, "get_detailed_comparison")
        assert callable(adapter.get_detailed_comparison)

    def test_has_record_human_edit_method(self, adapter):
        """Methode record_human_edit existe."""
        assert hasattr(adapter, "record_human_edit")
        assert callable(adapter.record_human_edit)

    def test_has_get_human_edits_method(self, adapter):
        """Methode get_human_edits existe."""
        assert hasattr(adapter, "get_human_edits")
        assert callable(adapter.get_human_edits)

    def test_has_get_performance_metrics_method(self, adapter):
        """Methode get_performance_metrics existe."""
        assert hasattr(adapter, "get_performance_metrics")
        assert callable(adapter.get_performance_metrics)

    def test_has_get_trend_method(self, adapter):
        """Methode get_trend existe."""
        assert hasattr(adapter, "get_trend")
        assert callable(adapter.get_trend)


# =============================================================================
# TESTS - INITIALIZATION
# =============================================================================


class TestInitialization:
    """Tests pour l'initialisation de l'adapter."""

    def test_creates_data_directory(self, temp_dir):
        """Le repertoire de donnees est cree."""
        LegacyAnalyticsAdapter(data_dir=temp_dir)
        assert temp_dir.exists()
        assert temp_dir.is_dir()

    def test_quality_file_constant(self, adapter):
        """Constante QUALITY_FILE est definie."""
        assert adapter.QUALITY_FILE == "quality_metrics.json"

    def test_edits_file_constant(self, adapter):
        """Constante EDITS_FILE est definie."""
        assert adapter.EDITS_FILE == "human_edits.json"

    def test_default_data_directory(self):
        """Utilise le repertoire par defaut si aucun n'est fourni."""
        adapter = LegacyAnalyticsAdapter()
        # Verifie que le repertoire existe
        assert adapter.data_dir.exists()
        # Verifie que c'est dans le sous-dossier analytics
        assert adapter.data_dir.name == "analytics"


# =============================================================================
# TESTS - SCORE CONVERSION
# =============================================================================


class TestScoreConversion:
    """Tests pour la conversion QualityScore <-> Dict."""

    def test_score_to_dict_all_fields(self, adapter, sample_score):
        """Conversion score -> dict preserve tous les champs."""
        result = adapter._score_to_dict(sample_score)

        assert result["draft_id"] == "draft-123"
        assert result["overall_score"] == 85.0
        assert result["tone_score"] == 90.0
        assert result["completeness_score"] == 80.0
        assert result["professionalism_score"] == 85.0
        assert result["relevance_score"] == 85.0
        assert result["user_rating"] == 4
        assert result["was_edited"] is True
        assert result["edit_ratio"] == 0.15
        assert result["timestamp"] == "2024-01-15T10:30:00"

    def test_score_to_dict_without_timestamp(self, adapter):
        """Conversion score sans timestamp genere un timestamp."""
        score = QualityScore(draft_id="test", overall_score=80.0)
        result = adapter._score_to_dict(score)

        assert "timestamp" in result
        assert result["timestamp"]  # Non vide

    def test_dict_to_score_all_fields(self, adapter):
        """Conversion dict -> score preserve tous les champs."""
        data = {
            "draft_id": "draft-123",
            "overall_score": 85.0,
            "tone_score": 90.0,
            "completeness_score": 80.0,
            "professionalism_score": 85.0,
            "relevance_score": 85.0,
            "user_rating": 4,
            "was_edited": True,
            "edit_ratio": 0.15,
            "timestamp": "2024-01-15T10:30:00",
        }
        result = adapter._dict_to_score(data)

        assert result.draft_id == "draft-123"
        assert result.overall_score == 85.0
        assert result.tone_score == 90.0
        assert result.completeness_score == 80.0
        assert result.professionalism_score == 85.0
        assert result.relevance_score == 85.0
        assert result.user_rating == 4
        assert result.was_edited is True
        assert result.edit_ratio == 0.15
        assert result.timestamp == "2024-01-15T10:30:00"

    def test_dict_to_score_missing_fields(self, adapter):
        """Conversion dict incomplet utilise valeurs par defaut."""
        data = {"draft_id": "test"}
        result = adapter._dict_to_score(data)

        assert result.draft_id == "test"
        assert result.overall_score == 0.0
        assert result.tone_score == 0.0
        assert result.user_rating is None
        assert result.was_edited is False

    def test_dict_to_score_empty_dict(self, adapter):
        """Conversion dict vide utilise valeurs par defaut."""
        result = adapter._dict_to_score({})

        assert result.draft_id == ""
        assert result.overall_score == 0.0


# =============================================================================
# TESTS - EDIT CONVERSION
# =============================================================================


class TestEditConversion:
    """Tests pour la conversion HumanEdit <-> Dict."""

    def test_edit_to_dict_all_fields(self, adapter, sample_edit):
        """Conversion edit -> dict preserve tous les champs."""
        result = adapter._edit_to_dict(sample_edit)

        assert result["id"] == "edit-456"
        assert result["draft_id"] == "draft-123"
        assert result["original_draft"] == "Hello world, how are you?"
        assert result["edited_draft"] == "Hello there, how are you doing?"
        assert result["edit_distance"] == 10
        assert result["edit_ratio"] == 0.25
        assert result["word_changes"] == 2
        assert result["timestamp"] == "2024-01-15T11:00:00"
        assert result["editor_notes"] == "Changed greeting"

    def test_edit_to_dict_without_timestamp(self, adapter):
        """Conversion edit sans timestamp genere un timestamp."""
        edit = HumanEdit(id="e1", draft_id="d1", original_draft="", edited_draft="")
        result = adapter._edit_to_dict(edit)

        assert "timestamp" in result
        assert result["timestamp"]

    def test_dict_to_edit_all_fields(self, adapter):
        """Conversion dict -> edit preserve tous les champs."""
        data = {
            "id": "edit-456",
            "draft_id": "draft-123",
            "original_draft": "Hello world",
            "edited_draft": "Hello there",
            "edit_distance": 5,
            "edit_ratio": 0.2,
            "word_changes": 1,
            "timestamp": "2024-01-15T11:00:00",
            "editor_notes": "Test",
        }
        result = adapter._dict_to_edit(data)

        assert result.id == "edit-456"
        assert result.draft_id == "draft-123"
        assert result.original_draft == "Hello world"
        assert result.edited_draft == "Hello there"
        assert result.edit_distance == 5
        assert result.edit_ratio == 0.2
        assert result.word_changes == 1
        assert result.timestamp == "2024-01-15T11:00:00"
        assert result.editor_notes == "Test"

    def test_dict_to_edit_missing_fields(self, adapter):
        """Conversion dict incomplet utilise valeurs par defaut."""
        data = {"id": "e1"}
        result = adapter._dict_to_edit(data)

        assert result.id == "e1"
        assert result.draft_id == ""
        assert result.edit_distance == 0
        assert result.edit_ratio == 0.0

    def test_dict_to_edit_empty_dict(self, adapter):
        """Conversion dict vide utilise valeurs par defaut."""
        result = adapter._dict_to_edit({})

        assert result.id == ""
        assert result.original_draft == ""


# =============================================================================
# TESTS - QUALITY METRICS
# =============================================================================


class TestQualityMetrics:
    """Tests pour les operations de metriques de qualite."""

    def test_get_quality_metrics_empty(self, adapter):
        """Metriques vides si pas de donnees."""
        result = adapter.get_quality_metrics()

        assert result["avg_score"] == 0.0
        assert result["total_drafts"] == 0
        assert result["by_level"]["excellent"] == 0
        assert result["by_level"]["good"] == 0
        assert result["by_level"]["acceptable"] == 0
        assert result["by_level"]["needs_improvement"] == 0

    def test_get_quality_metrics_with_data(self, adapter, sample_score):
        """Metriques calculees avec des donnees."""
        adapter.record_quality_score(sample_score)
        result = adapter.get_quality_metrics()

        assert result["total_drafts"] == 1
        assert result["avg_score"] == 85.0
        assert result["by_level"]["good"] == 1

    def test_get_quality_metrics_multiple_levels(
        self, adapter, excellent_score, good_score,
        acceptable_score, needs_improvement_score
    ):
        """Metriques reparties par niveau de qualite."""
        adapter.record_quality_score(excellent_score)
        adapter.record_quality_score(good_score)
        adapter.record_quality_score(acceptable_score)
        adapter.record_quality_score(needs_improvement_score)

        result = adapter.get_quality_metrics()

        assert result["total_drafts"] == 4
        assert result["by_level"]["excellent"] == 1
        assert result["by_level"]["good"] == 1
        assert result["by_level"]["acceptable"] == 1
        assert result["by_level"]["needs_improvement"] == 1

        expected_avg = (95.0 + 80.0 + 60.0 + 40.0) / 4
        assert result["avg_score"] == round(expected_avg, 1)

    def test_get_detailed_quality_metrics_empty(self, adapter):
        """Metriques detaillees vides."""
        result = adapter.get_detailed_quality_metrics()

        assert isinstance(result, QualityMetrics)
        assert result.avg_score == 0.0
        assert result.total_drafts == 0
        assert result.avg_user_rating == 0.0
        assert result.rated_count == 0

    def test_get_detailed_quality_metrics_with_ratings(self, adapter):
        """Metriques detaillees avec notes utilisateur."""
        score1 = QualityScore(draft_id="d1", overall_score=90.0, user_rating=5, timestamp="2024-01-15T10:00:00")
        score2 = QualityScore(draft_id="d2", overall_score=80.0, user_rating=4, timestamp="2024-01-15T11:00:00")
        score3 = QualityScore(draft_id="d3", overall_score=70.0, timestamp="2024-01-15T12:00:00")

        adapter.record_quality_score(score1)
        adapter.record_quality_score(score2)
        adapter.record_quality_score(score3)

        result = adapter.get_detailed_quality_metrics()

        assert result.total_drafts == 3
        assert result.rated_count == 2
        assert result.avg_user_rating == 4.5  # (5 + 4) / 2

    def test_record_quality_score(self, adapter, sample_score):
        """Enregistrement d'un score."""
        adapter.record_quality_score(sample_score)

        result = adapter.get_quality_score("draft-123")
        assert result is not None
        assert result.draft_id == "draft-123"
        assert result.overall_score == 85.0

    def test_record_quality_score_multiple(self, adapter):
        """Enregistrement de plusieurs scores."""
        score1 = QualityScore(draft_id="d1", overall_score=90.0, timestamp="2024-01-15T10:00:00")
        score2 = QualityScore(draft_id="d2", overall_score=80.0, timestamp="2024-01-15T11:00:00")

        adapter.record_quality_score(score1)
        adapter.record_quality_score(score2)

        assert adapter.get_quality_score("d1") is not None
        assert adapter.get_quality_score("d2") is not None

    def test_get_quality_score_not_found(self, adapter):
        """Score non trouve retourne None."""
        result = adapter.get_quality_score("nonexistent")
        assert result is None

    def test_get_quality_score_found(self, adapter, sample_score):
        """Score trouve retourne l'objet."""
        adapter.record_quality_score(sample_score)
        result = adapter.get_quality_score("draft-123")

        assert result is not None
        assert result.draft_id == "draft-123"
        assert result.overall_score == 85.0
        assert result.tone_score == 90.0


# =============================================================================
# TESTS - CALCULATE QUALITY LEVEL COUNTS
# =============================================================================


class TestCalculateQualityLevelCounts:
    """Tests pour _calculate_quality_level_counts."""

    def test_empty_scores(self, adapter):
        """Liste vide retourne tous les niveaux a 0."""
        result = LegacyAnalyticsAdapter._calculate_quality_level_counts([])

        assert result["excellent"] == 0
        assert result["good"] == 0
        assert result["acceptable"] == 0
        assert result["needs_improvement"] == 0

    def test_excellent_threshold(self, adapter):
        """Score >= 90 est excellent."""
        scores = [
            {"overall_score": 90},
            {"overall_score": 95},
            {"overall_score": 100},
        ]
        result = LegacyAnalyticsAdapter._calculate_quality_level_counts(scores)

        assert result["excellent"] == 3

    def test_good_threshold(self, adapter):
        """Score >= 75 et < 90 est bon."""
        scores = [
            {"overall_score": 75},
            {"overall_score": 80},
            {"overall_score": 89},
        ]
        result = LegacyAnalyticsAdapter._calculate_quality_level_counts(scores)

        assert result["good"] == 3

    def test_acceptable_threshold(self, adapter):
        """Score >= 50 et < 75 est acceptable."""
        scores = [
            {"overall_score": 50},
            {"overall_score": 60},
            {"overall_score": 74},
        ]
        result = LegacyAnalyticsAdapter._calculate_quality_level_counts(scores)

        assert result["acceptable"] == 3

    def test_needs_improvement_threshold(self, adapter):
        """Score < 50 necessite amelioration."""
        scores = [
            {"overall_score": 0},
            {"overall_score": 25},
            {"overall_score": 49},
        ]
        result = LegacyAnalyticsAdapter._calculate_quality_level_counts(scores)

        assert result["needs_improvement"] == 3

    def test_missing_score_defaults_to_zero(self, adapter):
        """Score manquant est traite comme 0."""
        scores = [{}]
        result = LegacyAnalyticsAdapter._calculate_quality_level_counts(scores)

        assert result["needs_improvement"] == 1


# =============================================================================
# TESTS - AI VS HUMAN COMPARISON
# =============================================================================


class TestAIVsHumanComparison:
    """Tests pour les comparaisons IA vs humain."""

    def test_get_ai_vs_human_comparison_empty(self, adapter):
        """Comparaison vide si pas de donnees."""
        result = adapter.get_ai_vs_human_comparison()

        assert result["total_drafts"] == 0
        assert result["edited_count"] == 0
        assert result["edit_rate"] == 0.0
        assert result["avg_edit_ratio"] == 0.0

    def test_get_ai_vs_human_comparison_with_data(self, adapter):
        """Comparaison avec donnees."""
        score1 = QualityScore(draft_id="d1", overall_score=80.0, was_edited=True, timestamp="2024-01-15T10:00:00")
        score2 = QualityScore(draft_id="d2", overall_score=90.0, was_edited=False, timestamp="2024-01-15T11:00:00")

        edit = HumanEdit(
            id="e1", draft_id="d1", original_draft="a", edited_draft="b",
            edit_ratio=0.3, timestamp="2024-01-15T10:00:00"
        )

        adapter.record_quality_score(score1)
        adapter.record_quality_score(score2)
        adapter.record_human_edit(edit)

        result = adapter.get_ai_vs_human_comparison()

        assert result["total_drafts"] == 2
        assert result["edited_count"] == 1
        assert result["edit_rate"] == 50.0  # 1/2 * 100
        assert result["avg_edit_ratio"] == 0.3

    def test_get_detailed_comparison_empty(self, adapter):
        """Comparaison detaillee vide."""
        result = adapter.get_detailed_comparison()

        assert isinstance(result, AIVsHumanComparison)
        assert result.total_drafts == 0
        assert result.avg_word_changes == 0.0
        assert result.common_edit_types == []

    def test_get_detailed_comparison_with_data(self, adapter):
        """Comparaison detaillee avec donnees."""
        score = QualityScore(draft_id="d1", overall_score=80.0, was_edited=True, timestamp="2024-01-15T10:00:00")
        edit = HumanEdit(
            id="e1", draft_id="d1", original_draft="a", edited_draft="b",
            word_changes=5, edit_ratio=0.2, timestamp="2024-01-15T10:00:00"
        )

        adapter.record_quality_score(score)
        adapter.record_human_edit(edit)

        result = adapter.get_detailed_comparison()

        assert result.edited_count == 1
        assert result.avg_word_changes == 5.0

    def test_record_human_edit(self, adapter, sample_edit):
        """Enregistrement d'une modification humaine."""
        adapter.record_human_edit(sample_edit)

        edits = adapter.get_human_edits()
        assert len(edits) == 1
        assert edits[0].id == "edit-456"

    def test_record_human_edit_multiple(self, adapter):
        """Enregistrement de plusieurs modifications."""
        edit1 = HumanEdit(id="e1", draft_id="d1", original_draft="a", edited_draft="b", timestamp="2024-01-15T10:00:00")
        edit2 = HumanEdit(id="e2", draft_id="d2", original_draft="c", edited_draft="d", timestamp="2024-01-15T11:00:00")

        adapter.record_human_edit(edit1)
        adapter.record_human_edit(edit2)

        edits = adapter.get_human_edits()
        assert len(edits) == 2

    def test_get_human_edits_empty(self, adapter):
        """Liste vide si pas de modifications."""
        result = adapter.get_human_edits()
        assert result == []

    def test_get_human_edits_with_limit(self, adapter):
        """Limite le nombre de modifications retournees."""
        for i in range(10):
            edit = HumanEdit(
                id=f"e{i}", draft_id=f"d{i}",
                original_draft="a", edited_draft="b",
                timestamp=f"2024-01-15T{i:02d}:00:00"
            )
            adapter.record_human_edit(edit)

        result = adapter.get_human_edits(limit=5)
        assert len(result) == 5

    def test_get_human_edits_order(self, adapter):
        """Modifications retournees dans l'ordre d'insertion (LIFO)."""
        edit1 = HumanEdit(id="e1", draft_id="d1", original_draft="a", edited_draft="b", timestamp="2024-01-15T10:00:00")
        edit2 = HumanEdit(id="e2", draft_id="d2", original_draft="c", edited_draft="d", timestamp="2024-01-15T11:00:00")

        adapter.record_human_edit(edit1)
        adapter.record_human_edit(edit2)

        edits = adapter.get_human_edits()
        # Plus recent en premier (insert at 0)
        assert edits[0].id == "e2"
        assert edits[1].id == "e1"


# =============================================================================
# TESTS - PERFORMANCE METRICS
# =============================================================================


class TestPerformanceMetrics:
    """Tests pour les metriques de performance."""

    def test_get_performance_metrics_empty(self, adapter):
        """Metriques vides si pas de donnees."""
        result = adapter.get_performance_metrics(period_days=30)

        assert isinstance(result, PerformanceMetrics)
        assert result.total_drafts == 0
        assert result.avg_quality_score == 0.0

    def test_get_performance_metrics_with_data(self, adapter):
        """Metriques calculees sur la periode."""
        now = datetime.now().isoformat()
        score1 = QualityScore(
            draft_id="d1", overall_score=80.0,
            user_rating=4, was_edited=True,
            timestamp=now
        )
        score2 = QualityScore(
            draft_id="d2", overall_score=90.0,
            user_rating=5, was_edited=False,
            timestamp=now
        )

        adapter.record_quality_score(score1)
        adapter.record_quality_score(score2)

        result = adapter.get_performance_metrics(period_days=30)

        assert result.total_drafts == 2
        assert result.avg_quality_score == 85.0
        assert result.avg_user_rating == 4.5
        assert result.edit_rate == 50.0

    def test_get_performance_metrics_filters_by_period(self, adapter):
        """Seules les donnees de la periode sont incluses."""
        now = datetime.now()
        recent = now.isoformat()
        old = (now - timedelta(days=60)).isoformat()

        score_recent = QualityScore(draft_id="d1", overall_score=80.0, timestamp=recent)
        score_old = QualityScore(draft_id="d2", overall_score=90.0, timestamp=old)

        adapter.record_quality_score(score_recent)
        adapter.record_quality_score(score_old)

        result = adapter.get_performance_metrics(period_days=30)

        assert result.total_drafts == 1
        assert result.avg_quality_score == 80.0

    def test_get_performance_metrics_no_rated(self, adapter):
        """Moyenne note = 0 si pas de notes."""
        now = datetime.now().isoformat()
        score = QualityScore(draft_id="d1", overall_score=80.0, timestamp=now)

        adapter.record_quality_score(score)

        result = adapter.get_performance_metrics(period_days=30)

        assert result.avg_user_rating == 0.0


# =============================================================================
# TESTS - TREND
# =============================================================================


class TestTrend:
    """Tests pour les tendances."""

    def test_get_trend_empty(self, adapter):
        """Tendance vide si pas de donnees."""
        result = adapter.get_trend("quality_score", days=30)
        assert result == []

    def test_get_trend_quality_score(self, adapter):
        """Tendance du score de qualite."""
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")

        score1 = QualityScore(
            draft_id="d1", overall_score=80.0,
            timestamp=f"{today}T10:00:00"
        )
        score2 = QualityScore(
            draft_id="d2", overall_score=90.0,
            timestamp=f"{today}T11:00:00"
        )

        adapter.record_quality_score(score1)
        adapter.record_quality_score(score2)

        result = adapter.get_trend("quality_score", days=30)

        assert len(result) == 1
        assert result[0]["date"] == today
        assert result[0]["value"] == 85.0  # (80 + 90) / 2

    def test_get_trend_user_rating(self, adapter):
        """Tendance des notes utilisateur."""
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")

        score1 = QualityScore(
            draft_id="d1", overall_score=80.0, user_rating=4,
            timestamp=f"{today}T10:00:00"
        )
        score2 = QualityScore(
            draft_id="d2", overall_score=90.0, user_rating=5,
            timestamp=f"{today}T11:00:00"
        )

        adapter.record_quality_score(score1)
        adapter.record_quality_score(score2)

        result = adapter.get_trend("user_rating", days=30)

        assert len(result) == 1
        assert result[0]["value"] == 4.5

    def test_get_trend_user_rating_no_ratings(self, adapter):
        """Tendance note = 0 si pas de notes ce jour."""
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")

        score = QualityScore(
            draft_id="d1", overall_score=80.0,
            timestamp=f"{today}T10:00:00"
        )

        adapter.record_quality_score(score)

        result = adapter.get_trend("user_rating", days=30)

        assert len(result) == 1
        assert result[0]["value"] == 0

    def test_get_trend_count(self, adapter):
        """Tendance du nombre de brouillons."""
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")

        score1 = QualityScore(draft_id="d1", overall_score=80.0, timestamp=f"{today}T10:00:00")
        score2 = QualityScore(draft_id="d2", overall_score=90.0, timestamp=f"{today}T11:00:00")

        adapter.record_quality_score(score1)
        adapter.record_quality_score(score2)

        result = adapter.get_trend("unknown_metric", days=30)

        assert len(result) == 1
        assert result[0]["value"] == 2  # Count

    def test_get_trend_multiple_days(self, adapter):
        """Tendance sur plusieurs jours."""
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")

        score1 = QualityScore(draft_id="d1", overall_score=70.0, timestamp=f"{yesterday}T10:00:00")
        score2 = QualityScore(draft_id="d2", overall_score=90.0, timestamp=f"{today}T10:00:00")

        adapter.record_quality_score(score1)
        adapter.record_quality_score(score2)

        result = adapter.get_trend("quality_score", days=30)

        assert len(result) == 2
        # Trie par date
        assert result[0]["date"] == yesterday
        assert result[0]["value"] == 70.0
        assert result[1]["date"] == today
        assert result[1]["value"] == 90.0

    def test_get_trend_filters_by_period(self, adapter):
        """Seules les donnees de la periode sont incluses."""
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        old_date = (now - timedelta(days=60)).strftime("%Y-%m-%d")

        score_recent = QualityScore(draft_id="d1", overall_score=80.0, timestamp=f"{today}T10:00:00")
        score_old = QualityScore(draft_id="d2", overall_score=90.0, timestamp=f"{old_date}T10:00:00")

        adapter.record_quality_score(score_recent)
        adapter.record_quality_score(score_old)

        result = adapter.get_trend("quality_score", days=30)

        assert len(result) == 1
        assert result[0]["date"] == today


# =============================================================================
# TESTS - EDGE CASES
# =============================================================================


class TestEdgeCases:
    """Tests pour les cas limites."""

    def test_persistence_across_instances(self, temp_dir):
        """Donnees persistees entre instances."""
        adapter1 = LegacyAnalyticsAdapter(data_dir=temp_dir)
        score = QualityScore(draft_id="d1", overall_score=80.0, timestamp="2024-01-15T10:00:00")
        adapter1.record_quality_score(score)

        # Nouvelle instance
        adapter2 = LegacyAnalyticsAdapter(data_dir=temp_dir)
        result = adapter2.get_quality_score("d1")

        assert result is not None
        assert result.overall_score == 80.0

    def test_special_characters_in_edit(self, adapter):
        """Modification avec caracteres speciaux."""
        edit = HumanEdit(
            id="e1", draft_id="d1",
            original_draft="Hello 🎉 émojis & spéciaux!",
            edited_draft="Hello émojis et spéciaux 👋",
            timestamp="2024-01-15T10:00:00"
        )

        adapter.record_human_edit(edit)
        result = adapter.get_human_edits()[0]

        assert "🎉" in result.original_draft
        assert "👋" in result.edited_draft

    def test_empty_strings_in_score(self, adapter):
        """Score avec chaines vides."""
        score = QualityScore(draft_id="", overall_score=0.0, timestamp="")
        adapter.record_quality_score(score)

        result = adapter.get_quality_score("")
        assert result is not None

    def test_boundary_scores(self, adapter):
        """Scores aux limites des seuils."""
        scores = [
            QualityScore(draft_id="d90", overall_score=90.0, timestamp="2024-01-15T10:00:00"),  # Exactement 90
            QualityScore(draft_id="d75", overall_score=75.0, timestamp="2024-01-15T11:00:00"),  # Exactement 75
            QualityScore(draft_id="d50", overall_score=50.0, timestamp="2024-01-15T12:00:00"),  # Exactement 50
            QualityScore(draft_id="d0", overall_score=0.0, timestamp="2024-01-15T13:00:00"),    # Zero
        ]

        for score in scores:
            adapter.record_quality_score(score)

        result = adapter.get_quality_metrics()

        assert result["by_level"]["excellent"] == 1  # 90
        assert result["by_level"]["good"] == 1       # 75
        assert result["by_level"]["acceptable"] == 1 # 50
        assert result["by_level"]["needs_improvement"] == 1  # 0

    def test_large_number_of_records(self, adapter):
        """Gestion d'un grand nombre d'enregistrements."""
        for i in range(100):
            score = QualityScore(
                draft_id=f"d{i}",
                overall_score=float(i),
                timestamp=f"2024-01-15T{i % 24:02d}:00:00"
            )
            adapter.record_quality_score(score)

        result = adapter.get_quality_metrics()
        assert result["total_drafts"] == 100

    def test_score_without_optional_fields(self, adapter):
        """Score avec seulement les champs requis."""
        score = QualityScore(draft_id="minimal")
        adapter.record_quality_score(score)

        result = adapter.get_quality_score("minimal")
        assert result is not None
        assert result.user_rating is None
        assert result.was_edited is False

    def test_edit_without_optional_fields(self, adapter):
        """Edit avec seulement les champs requis."""
        edit = HumanEdit(
            id="minimal",
            draft_id="d1",
            original_draft="",
            edited_draft=""
        )
        adapter.record_human_edit(edit)

        result = adapter.get_human_edits()[0]
        assert result.editor_notes == ""
        assert result.word_changes == 0

    def test_get_trend_with_empty_timestamp(self, adapter):
        """Tendance avec timestamp vide (ne devrait pas crasher)."""
        score = QualityScore(draft_id="d1", overall_score=80.0, timestamp="")
        adapter.record_quality_score(score)

        # Ne devrait pas lever d'exception
        result = adapter.get_trend("quality_score", days=30)
        assert isinstance(result, list)


# =============================================================================
# TESTS - HELPER METHODS
# =============================================================================


class TestHelperMethods:
    """Tests pour les methodes helper privees."""

    def test_load_quality_empty(self, adapter):
        """Charge une liste vide si fichier n'existe pas."""
        result = adapter._load_quality()
        assert result == []

    def test_save_and_load_quality(self, adapter):
        """Sauvegarde et charge les scores."""
        scores = [{"draft_id": "d1", "overall_score": 80.0}]
        adapter._save_quality(scores)
        result = adapter._load_quality()

        assert len(result) == 1
        assert result[0]["draft_id"] == "d1"

    def test_load_edits_empty(self, adapter):
        """Charge une liste vide si fichier n'existe pas."""
        result = adapter._load_edits()
        assert result == []

    def test_save_and_load_edits(self, adapter):
        """Sauvegarde et charge les edits."""
        edits = [{"id": "e1", "draft_id": "d1"}]
        adapter._save_edits(edits)
        result = adapter._load_edits()

        assert len(result) == 1
        assert result[0]["id"] == "e1"
