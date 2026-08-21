# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour le module analytics (qualité, comparaison IA/humain).
"""

import pytest
from unittest.mock import patch

from app.analytics import (
    HumanEdit,
    QualityScore,
    PerformanceMetrics,
    AnalyticsManager,
    get_analytics_manager,
)


# ============================================================================
# TESTS HUMAN EDIT
# ============================================================================

class TestHumanEdit:
    """Tests pour HumanEdit."""

    def test_human_edit_creation(self):
        """Test création d'un edit."""
        edit = HumanEdit(
            id="e1",
            draft_id="d1",
            original_draft="Hello world",
            edited_draft="Hello there",
            edit_distance=5,
            edit_ratio=0.25,
            word_changes=1,
        )
        assert edit.id == "e1"
        assert edit.draft_id == "d1"
        assert edit.edit_ratio == 0.25

    def test_human_edit_similarity(self):
        """Test calcul de similarité."""
        edit = HumanEdit(
            id="e1",
            draft_id="d1",
            original_draft="Test",
            edited_draft="Test2",
            edit_ratio=0.2,
        )
        assert edit.similarity == 0.8


# ============================================================================
# TESTS QUALITY SCORE
# ============================================================================

class TestQualityScore:
    """Tests pour QualityScore."""

    def test_quality_score_creation(self):
        """Test création d'un score."""
        score = QualityScore(
            draft_id="d1",
            overall_score=85.0,
            tone_score=90.0,
            completeness_score=80.0,
            professionalism_score=85.0,
            relevance_score=85.0,
        )
        assert score.overall_score == 85.0
        assert score.quality_level == "good"

    def test_quality_level_excellent(self):
        """Test niveau excellent."""
        score = QualityScore(draft_id="d1", overall_score=95.0)
        assert score.quality_level == "excellent"

    def test_quality_level_acceptable(self):
        """Test niveau acceptable."""
        score = QualityScore(draft_id="d1", overall_score=60.0)
        assert score.quality_level == "acceptable"

    def test_quality_level_needs_improvement(self):
        """Test niveau à améliorer."""
        score = QualityScore(draft_id="d1", overall_score=40.0)
        assert score.quality_level == "needs_improvement"


# ============================================================================
# TESTS PERFORMANCE METRICS
# ============================================================================

class TestPerformanceMetrics:
    """Tests pour PerformanceMetrics."""

    def test_performance_metrics_creation(self):
        """Test création de métriques."""
        metrics = PerformanceMetrics(
            period_start="2024-01-01",
            period_end="2024-01-31",
            total_drafts=100,
            avg_quality_score=80.0,
            avg_user_rating=4.2,
            edit_rate=15.0,
        )
        assert metrics.total_drafts == 100
        assert metrics.avg_quality_score == 80.0


# ============================================================================
# TESTS ANALYTICS MANAGER
# ============================================================================

class TestAnalyticsManager:
    """Tests pour le gestionnaire d'analytics."""

    @pytest.fixture
    def manager(self, tmp_path):
        """Crée un manager avec dossier temporaire."""
        with patch("app.analytics.ANALYTICS_DIR", tmp_path):
            with patch("app.analytics.HUMAN_EDITS_FILE", tmp_path / "human_edits.json"):
                with patch("app.analytics.QUALITY_METRICS_FILE", tmp_path / "quality_metrics.json"):
                    return AnalyticsManager()

    def test_record_human_edit(self, manager, tmp_path):
        """Test enregistrement d'une modification humaine."""
        with patch("app.analytics.HUMAN_EDITS_FILE", tmp_path / "human_edits.json"):
            with patch("app.analytics.QUALITY_METRICS_FILE", tmp_path / "quality_metrics.json"):
                edit = manager.record_human_edit(
                    draft_id="d1",
                    original_draft="Hello world, how are you today?",
                    edited_draft="Hello there, how are you doing today?",
                    editor_notes="Changed greeting",
                )

                assert edit.draft_id == "d1"
                assert edit.word_changes > 0
                assert 0 < edit.edit_ratio < 1

    def test_get_ai_vs_human_comparison_empty(self, manager, tmp_path):
        """Test comparaison vide."""
        with patch("app.analytics.HUMAN_EDITS_FILE", tmp_path / "human_edits.json"):
            comparison = manager.get_ai_vs_human_comparison()
            assert comparison["total_edits"] == 0
            assert comparison["avg_similarity"] == 100

    def test_get_ai_vs_human_comparison(self, manager, tmp_path):
        """Test comparaison avec données."""
        with patch("app.analytics.HUMAN_EDITS_FILE", tmp_path / "human_edits.json"):
            with patch("app.analytics.QUALITY_METRICS_FILE", tmp_path / "quality_metrics.json"):
                # Ajouter quelques modifications
                manager.record_human_edit("d1", "Original text", "Modified text")
                manager.record_human_edit("d2", "Another original", "Another modified")

                comparison = manager.get_ai_vs_human_comparison()
                assert comparison["total_edits"] == 2
                assert "distribution" in comparison

    def test_record_quality_score(self, manager, tmp_path):
        """Test enregistrement d'un score de qualité."""
        with patch("app.analytics.QUALITY_METRICS_FILE", tmp_path / "quality_metrics.json"):
            score = manager.record_quality_score(
                draft_id="d1",
                tone_score=90,
                completeness_score=85,
                professionalism_score=80,
                relevance_score=75,
            )

            assert score.draft_id == "d1"
            assert score.overall_score == 82.5  # Moyenne

    def test_record_quality_score_with_rating(self, manager, tmp_path):
        """Test score avec note utilisateur."""
        with patch("app.analytics.QUALITY_METRICS_FILE", tmp_path / "quality_metrics.json"):
            score = manager.record_quality_score(
                draft_id="d1",
                tone_score=80,
                completeness_score=80,
                professionalism_score=80,
                relevance_score=80,
                user_rating=5,  # Note parfaite
            )

            # Score ajusté avec note utilisateur (30% poids)
            # (80 * 0.7) + (100 * 0.3) = 56 + 30 = 86
            assert score.overall_score == 86.0

    def test_get_quality_stats_empty(self, manager, tmp_path):
        """Test stats de qualité vides."""
        with patch("app.analytics.QUALITY_METRICS_FILE", tmp_path / "quality_metrics.json"):
            stats = manager.get_quality_stats()
            assert stats["total_scored"] == 0
            assert stats["avg_overall_score"] == 0

    def test_get_quality_stats(self, manager, tmp_path):
        """Test stats de qualité avec données."""
        with patch("app.analytics.QUALITY_METRICS_FILE", tmp_path / "quality_metrics.json"):
            manager.record_quality_score("d1", 90, 90, 90, 90)
            manager.record_quality_score("d2", 70, 70, 70, 70)

            stats = manager.get_quality_stats()
            assert stats["total_scored"] == 2
            assert stats["avg_overall_score"] == 80.0

    def test_auto_score_draft(self, manager):
        """Test scoring automatique."""
        draft = """
        Bonjour Monsieur,

        Je vous remercie pour votre message concernant notre projet.
        Je reviendrai vers vous dans les plus brefs délais.

        Cordialement,
        Jean
        """

        context = {"subject": "Projet collaboration", "body": "Message concernant le projet"}

        score = manager.auto_score_draft(draft, context)

        assert score.overall_score > 0
        assert score.tone_score > 0
        assert score.completeness_score > 0
        assert score.professionalism_score > 0
        assert score.relevance_score > 0

    def test_auto_score_informal_draft(self, manager):
        """Test scoring brouillon informel."""
        draft = "lol ok mdr!!!"
        context = {}

        score = manager.auto_score_draft(draft, context)

        # Score devrait être bas pour le professionnalisme
        assert score.professionalism_score < 70

    def test_levenshtein_distance(self, manager):
        """Test distance de Levenshtein."""
        assert manager._levenshtein_distance("", "") == 0
        assert manager._levenshtein_distance("abc", "") == 3
        assert manager._levenshtein_distance("abc", "abc") == 0
        assert manager._levenshtein_distance("abc", "abd") == 1
        assert manager._levenshtein_distance("kitten", "sitting") == 3

    def test_score_tone(self, manager):
        """Test scoring du ton."""
        polite = "Merci beaucoup, cordialement"
        negative = "Malheureusement, c'est impossible"

        polite_score = manager._score_tone(polite)
        negative_score = manager._score_tone(negative)

        assert polite_score > negative_score

    def test_score_completeness(self, manager):
        """Test scoring de complétude."""
        complete = """
        Bonjour,

        Voici ma réponse détaillée à votre question.
        Je reste à votre disposition pour plus d'informations.

        Cordialement
        """
        incomplete = "ok"

        complete_score = manager._score_completeness(complete, {})
        incomplete_score = manager._score_completeness(incomplete, {})

        assert complete_score > incomplete_score

    def test_score_professionalism(self, manager):
        """Test scoring du professionnalisme."""
        professional = "Je vous prie d'agréer mes salutations distinguées."
        informal = "lol mdr haha!!!"

        pro_score = manager._score_professionalism(professional)
        informal_score = manager._score_professionalism(informal)

        assert pro_score > informal_score

    def test_score_relevance(self, manager):
        """Test scoring de pertinence."""
        context = {"subject": "Réunion projet Alpha", "body": "Discussion projet Alpha demain"}
        relevant = "Concernant le projet Alpha, je confirme ma présence à la réunion."
        irrelevant = "J'aime les pizzas."

        relevant_score = manager._score_relevance(relevant, context)
        irrelevant_score = manager._score_relevance(irrelevant, context)

        assert relevant_score > irrelevant_score

    @patch("app.analytics.draft_history")
    def test_get_performance_metrics(self, mock_history, manager, tmp_path):
        """Test métriques de performance."""
        mock_history.get_stats.return_value = {"total": 50, "v1_percent": 80}

        with patch("app.analytics.QUALITY_METRICS_FILE", tmp_path / "quality_metrics.json"):
            with patch("app.analytics.HUMAN_EDITS_FILE", tmp_path / "human_edits.json"):
                metrics = manager.get_performance_metrics(days=30)

                assert metrics.total_drafts == 50
                assert metrics.v1_acceptance_rate == 80

    @patch("app.analytics.draft_history")
    def test_get_analytics_summary(self, mock_history, manager, tmp_path):
        """Test résumé complet."""
        mock_history.get_stats.return_value = {"total": 10, "v1_percent": 75}

        with patch("app.analytics.QUALITY_METRICS_FILE", tmp_path / "quality_metrics.json"):
            with patch("app.analytics.HUMAN_EDITS_FILE", tmp_path / "human_edits.json"):
                summary = manager.get_analytics_summary()

                assert "quality" in summary
                assert "comparison" in summary
                assert "performance" in summary
                assert "recommendations" in summary

    def test_generate_recommendations_good(self, manager, tmp_path):
        """Test recommandations avec bonnes performances."""
        with patch.object(manager, "get_ai_vs_human_comparison") as mock_comp:
            with patch.object(manager, "get_quality_stats") as mock_quality:
                mock_comp.return_value = {"avg_edit_ratio": 10}
                mock_quality.return_value = {"avg_overall_score": 85, "avg_user_rating": 4.5}

                recs = manager._generate_recommendations()
                assert any("satisfaisantes" in r for r in recs)

    def test_generate_recommendations_needs_improvement(self, manager, tmp_path):
        """Test recommandations avec mauvaises performances."""
        with patch.object(manager, "get_ai_vs_human_comparison") as mock_comp:
            with patch.object(manager, "get_quality_stats") as mock_quality:
                mock_comp.return_value = {"avg_edit_ratio": 50}  # Taux élevé
                mock_quality.return_value = {"avg_overall_score": 60, "avg_user_rating": 2.5}

                recs = manager._generate_recommendations()
                assert len(recs) >= 2  # Au moins 2 recommandations


# ============================================================================
# TESTS SINGLETON
# ============================================================================

class TestSingleton:
    """Tests pour le singleton."""

    def test_get_analytics_manager_singleton(self):
        """Test singleton analytics manager."""
        # Reset singleton
        import app.analytics
        app.analytics._analytics_manager = None

        manager1 = get_analytics_manager()
        manager2 = get_analytics_manager()

        assert manager1 is manager2


# ============================================================================
# TESTS EDGE CASES
# ============================================================================

class TestEdgeCases:
    """Tests pour les cas limites."""

    @pytest.fixture
    def manager(self, tmp_path):
        """Crée un manager avec dossier temporaire."""
        with patch("app.analytics.ANALYTICS_DIR", tmp_path):
            with patch("app.analytics.HUMAN_EDITS_FILE", tmp_path / "human_edits.json"):
                with patch("app.analytics.QUALITY_METRICS_FILE", tmp_path / "quality_metrics.json"):
                    return AnalyticsManager()

    def test_empty_draft_scoring(self, manager):
        """Test scoring d'un brouillon vide."""
        score = manager.auto_score_draft("", {})
        assert score.overall_score >= 0

    def test_very_long_draft_scoring(self, manager):
        """Test scoring d'un très long brouillon."""
        long_draft = "Lorem ipsum. " * 1000
        score = manager.auto_score_draft(long_draft, {})
        assert score.overall_score >= 0

    def test_special_characters_in_edit(self, manager, tmp_path):
        """Test édition avec caractères spéciaux."""
        with patch("app.analytics.HUMAN_EDITS_FILE", tmp_path / "human_edits.json"):
            with patch("app.analytics.QUALITY_METRICS_FILE", tmp_path / "quality_metrics.json"):
                edit = manager.record_human_edit(
                    draft_id="d1",
                    original_draft="Hello 🎉 émojis & spéciaux!",
                    edited_draft="Hello émojis et spéciaux 👋",
                )
                assert edit.id

    def test_identical_edit(self, manager, tmp_path):
        """Test édition identique."""
        with patch("app.analytics.HUMAN_EDITS_FILE", tmp_path / "human_edits.json"):
            with patch("app.analytics.QUALITY_METRICS_FILE", tmp_path / "quality_metrics.json"):
                edit = manager.record_human_edit(
                    draft_id="d1",
                    original_draft="Same text",
                    edited_draft="Same text",
                )
                assert edit.edit_ratio == 0
                assert edit.similarity == 1.0

    def test_improvement_trend_single_metric(self, manager):
        """Test tendance avec une seule métrique."""
        metrics = [{"overall_score": 80}]
        trend = manager._calculate_improvement_trend(metrics)
        assert trend == 0.0

    def test_improvement_trend_improving(self, manager):
        """Test tendance positive."""
        metrics = [
            {"overall_score": 60},
            {"overall_score": 65},
            {"overall_score": 80},
            {"overall_score": 90},
        ]
        trend = manager._calculate_improvement_trend(metrics)
        assert trend > 0

    def test_improvement_trend_declining(self, manager):
        """Test tendance négative."""
        metrics = [
            {"overall_score": 90},
            {"overall_score": 85},
            {"overall_score": 60},
            {"overall_score": 50},
        ]
        trend = manager._calculate_improvement_trend(metrics)
        assert trend < 0
