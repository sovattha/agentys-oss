# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests unitaires pour l'entite StyleSimilarityScore.
"""

import pytest
from app.domain.entities.style_similarity import StyleSimilarityScore


class TestStyleSimilarityScore:
    """Tests pour StyleSimilarityScore."""

    def test_create_with_all_fields(self):
        """Cree un score avec tous les champs."""
        score = StyleSimilarityScore(
            overall_score=85.0,
            greeting_match=True,
            closing_match=True,
            formality_match=True,
            vocabulary_overlap=0.75,
            analysis_details={"note": "Good match"},
        )

        assert score.overall_score == 85.0
        assert score.greeting_match is True
        assert score.closing_match is True
        assert score.formality_match is True
        assert score.vocabulary_overlap == 0.75
        assert score.analysis_details == {"note": "Good match"}

    def test_create_with_defaults(self):
        """Cree un score avec valeurs par defaut."""
        score = StyleSimilarityScore(overall_score=50.0)

        assert score.overall_score == 50.0
        assert score.greeting_match is False
        assert score.closing_match is False
        assert score.formality_match is False
        assert score.vocabulary_overlap == 0.0
        assert score.analysis_details == {}

    def test_overall_score_validation_min(self):
        """overall_score doit etre >= 0."""
        with pytest.raises(ValueError, match="overall_score must be between 0 and 100"):
            StyleSimilarityScore(overall_score=-5.0)

    def test_overall_score_validation_max(self):
        """overall_score doit etre <= 100."""
        with pytest.raises(ValueError, match="overall_score must be between 0 and 100"):
            StyleSimilarityScore(overall_score=105.0)

    def test_vocabulary_overlap_validation_min(self):
        """vocabulary_overlap doit etre >= 0."""
        with pytest.raises(ValueError, match="vocabulary_overlap must be between 0 and 1"):
            StyleSimilarityScore(overall_score=50.0, vocabulary_overlap=-0.1)

    def test_vocabulary_overlap_validation_max(self):
        """vocabulary_overlap doit etre <= 1."""
        with pytest.raises(ValueError, match="vocabulary_overlap must be between 0 and 1"):
            StyleSimilarityScore(overall_score=50.0, vocabulary_overlap=1.5)

    def test_is_acceptable_above_threshold(self):
        """is_acceptable retourne True si score >= threshold."""
        score = StyleSimilarityScore(overall_score=75.0)
        assert score.is_acceptable(70.0) is True
        assert score.is_acceptable(75.0) is True

    def test_is_acceptable_below_threshold(self):
        """is_acceptable retourne False si score < threshold."""
        score = StyleSimilarityScore(overall_score=65.0)
        assert score.is_acceptable(70.0) is False

    def test_is_acceptable_default_threshold(self):
        """is_acceptable utilise 70.0 par defaut."""
        score_pass = StyleSimilarityScore(overall_score=70.0)
        score_fail = StyleSimilarityScore(overall_score=69.9)

        assert score_pass.is_acceptable() is True
        assert score_fail.is_acceptable() is False

    def test_to_dict(self):
        """Serialise en dictionnaire."""
        score = StyleSimilarityScore(
            overall_score=80.0,
            greeting_match=True,
            closing_match=False,
            formality_match=True,
            vocabulary_overlap=0.6,
            analysis_details={"key": "value"},
        )

        result = score.to_dict()

        assert result == {
            "overall_score": 80.0,
            "greeting_match": True,
            "closing_match": False,
            "formality_match": True,
            "vocabulary_overlap": 0.6,
            "analysis_details": {"key": "value"},
        }

    def test_from_dict(self):
        """Deserialise depuis un dictionnaire."""
        data = {
            "overall_score": 90.0,
            "greeting_match": True,
            "closing_match": True,
            "formality_match": False,
            "vocabulary_overlap": 0.85,
            "analysis_details": {"extra": "info"},
        }

        score = StyleSimilarityScore.from_dict(data)

        assert score.overall_score == 90.0
        assert score.greeting_match is True
        assert score.closing_match is True
        assert score.formality_match is False
        assert score.vocabulary_overlap == 0.85
        assert score.analysis_details == {"extra": "info"}

    def test_from_dict_with_defaults(self):
        """Deserialise avec valeurs manquantes."""
        data = {"overall_score": 55.0}

        score = StyleSimilarityScore.from_dict(data)

        assert score.overall_score == 55.0
        assert score.greeting_match is False
        assert score.closing_match is False
        assert score.formality_match is False
        assert score.vocabulary_overlap == 0.0
        assert score.analysis_details == {}

    def test_create_default(self):
        """Cree un score par defaut (aucune correspondance)."""
        score = StyleSimilarityScore.create_default()

        assert score.overall_score == 0.0
        assert score.greeting_match is False
        assert score.closing_match is False
        assert score.formality_match is False
        assert score.vocabulary_overlap == 0.0
        assert score.analysis_details == {}

    def test_create_perfect(self):
        """Cree un score parfait (100% match)."""
        score = StyleSimilarityScore.create_perfect()

        assert score.overall_score == 100.0
        assert score.greeting_match is True
        assert score.closing_match is True
        assert score.formality_match is True
        assert score.vocabulary_overlap == 1.0

    def test_matches_count(self):
        """Compte le nombre de criteres correspondants."""
        score_all = StyleSimilarityScore(
            overall_score=100.0,
            greeting_match=True,
            closing_match=True,
            formality_match=True,
        )
        score_partial = StyleSimilarityScore(
            overall_score=50.0,
            greeting_match=True,
            closing_match=False,
            formality_match=True,
        )
        score_none = StyleSimilarityScore(overall_score=0.0)

        assert score_all.matches_count == 3
        assert score_partial.matches_count == 2
        assert score_none.matches_count == 0

    def test_summary(self):
        """Genere un resume lisible."""
        score = StyleSimilarityScore(
            overall_score=75.0,
            greeting_match=True,
            closing_match=False,
            formality_match=True,
            vocabulary_overlap=0.65,
        )

        summary = score.summary

        assert "75.0%" in summary
        assert "2/3" in summary  # 2 matches out of 3 criteria
