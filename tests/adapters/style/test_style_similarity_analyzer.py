# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests unitaires pour StyleSimilarityAnalyzer.

Story 4-4: Style Adaptation Engine
AC4: Score de similarité avec le style appris > 70%
"""

import pytest
from datetime import datetime

from app.adapters.style.style_similarity_analyzer import StyleSimilarityAnalyzer
from app.domain.entities.writing_style import WritingStyleProfile, FormalityLevel
from app.domain.entities.style_similarity import StyleSimilarityScore


class TestStyleSimilarityAnalyzer:
    """Tests pour StyleSimilarityAnalyzer."""

    @pytest.fixture
    def formal_profile(self) -> WritingStyleProfile:
        """Profil de style formel."""
        return WritingStyleProfile(
            account_id=1,
            analyzed_at=datetime.utcnow(),
            email_count=10,
            formality_level=FormalityLevel.FORMAL,
            preferred_greetings=["Bonjour", "Madame, Monsieur"],
            preferred_closings=["Cordialement", "Bien à vous"],
            common_words=["vous", "votre", "respectueusement", "veuillez"],
            avg_sentence_length=15.0,
        )

    @pytest.fixture
    def casual_profile(self) -> WritingStyleProfile:
        """Profil de style décontracté."""
        return WritingStyleProfile(
            account_id=2,
            analyzed_at=datetime.utcnow(),
            email_count=10,
            formality_level=FormalityLevel.CASUAL,
            preferred_greetings=["Salut", "Hello", "Coucou"],
            preferred_closings=["À+", "Bises", "++"],
            common_words=["tu", "ton", "toi", "sympa", "cool"],
            avg_sentence_length=8.0,
        )

    @pytest.fixture
    def analyzer(self) -> StyleSimilarityAnalyzer:
        """Instance de l'analyzer."""
        return StyleSimilarityAnalyzer()

    # ========================================================================
    # Tests de base
    # ========================================================================

    def test_analyzer_instantiation(self, analyzer):
        """L'analyzer peut être instancié."""
        assert analyzer is not None
        assert isinstance(analyzer, StyleSimilarityAnalyzer)

    def test_analyze_returns_style_similarity_score(self, analyzer, formal_profile):
        """analyze() retourne un StyleSimilarityScore."""
        draft = "Bonjour,\n\nMerci pour votre message.\n\nCordialement"

        result = analyzer.analyze(draft, formal_profile)

        assert isinstance(result, StyleSimilarityScore)

    # ========================================================================
    # Tests de détection des salutations
    # ========================================================================

    def test_greeting_match_with_preferred_greeting(self, analyzer, formal_profile):
        """Détecte une salutation préférée."""
        draft = "Bonjour,\n\nMerci pour votre message.\n\nCordialement"

        result = analyzer.analyze(draft, formal_profile)

        assert result.greeting_match is True

    def test_greeting_match_with_alternate_greeting(self, analyzer, formal_profile):
        """Détecte une salutation alternative du profil."""
        draft = "Madame, Monsieur,\n\nJe vous contacte...\n\nCordialement"

        result = analyzer.analyze(draft, formal_profile)

        assert result.greeting_match is True

    def test_greeting_no_match_with_wrong_greeting(self, analyzer, formal_profile):
        """Ne détecte pas une salutation non préférée."""
        draft = "Salut,\n\nÇa va?\n\nÀ+"

        result = analyzer.analyze(draft, formal_profile)

        assert result.greeting_match is False

    # ========================================================================
    # Tests de détection des clôtures
    # ========================================================================

    def test_closing_match_with_preferred_closing(self, analyzer, formal_profile):
        """Détecte une formule de clôture préférée."""
        draft = "Bonjour,\n\nMerci.\n\nCordialement"

        result = analyzer.analyze(draft, formal_profile)

        assert result.closing_match is True

    def test_closing_match_with_alternate_closing(self, analyzer, formal_profile):
        """Détecte une clôture alternative du profil."""
        draft = "Bonjour,\n\nMerci.\n\nBien à vous"

        result = analyzer.analyze(draft, formal_profile)

        assert result.closing_match is True

    def test_closing_no_match_with_wrong_closing(self, analyzer, formal_profile):
        """Ne détecte pas une clôture non préférée."""
        draft = "Bonjour,\n\nMerci.\n\nÀ+"

        result = analyzer.analyze(draft, formal_profile)

        assert result.closing_match is False

    # ========================================================================
    # Tests de détection du niveau de formalité
    # ========================================================================

    def test_formality_match_formal_with_vous(self, analyzer, formal_profile):
        """Détecte le vouvoiement pour un profil formel."""
        draft = "Je vous remercie pour votre réponse. Veuillez agréer..."

        result = analyzer.analyze(draft, formal_profile)

        assert result.formality_match is True

    def test_formality_no_match_formal_with_tu(self, analyzer, formal_profile):
        """Ne matche pas le tutoiement pour un profil formel."""
        draft = "Merci pour ta réponse. Tu peux me rappeler?"

        result = analyzer.analyze(draft, formal_profile)

        assert result.formality_match is False

    def test_formality_match_casual_with_tu(self, analyzer, casual_profile):
        """Détecte le tutoiement pour un profil décontracté."""
        draft = "Salut! Merci pour ton message. Tu es dispo demain?"

        result = analyzer.analyze(draft, casual_profile)

        assert result.formality_match is True

    def test_formality_no_match_casual_with_vous(self, analyzer, casual_profile):
        """Ne matche pas le vouvoiement pour un profil décontracté."""
        draft = "Je vous remercie pour votre message."

        result = analyzer.analyze(draft, casual_profile)

        assert result.formality_match is False

    # ========================================================================
    # Tests de chevauchement du vocabulaire
    # ========================================================================

    def test_vocabulary_overlap_high(self, analyzer, formal_profile):
        """Calcule un bon overlap pour vocabulaire commun."""
        draft = "Veuillez trouver ci-joint votre document. Respectueusement."

        result = analyzer.analyze(draft, formal_profile)

        assert result.vocabulary_overlap >= 0.3  # Au moins 30%

    def test_vocabulary_overlap_low(self, analyzer, formal_profile):
        """Calcule un faible overlap pour vocabulaire différent."""
        draft = "Hey! Super cool ton truc!"

        result = analyzer.analyze(draft, formal_profile)

        assert result.vocabulary_overlap < 0.3

    def test_vocabulary_overlap_zero_with_no_words(self, analyzer, formal_profile):
        """Overlap de 0 si aucun mot commun."""
        draft = "Test simple."

        result = analyzer.analyze(draft, formal_profile)

        assert result.vocabulary_overlap == 0.0

    # ========================================================================
    # Tests du score global
    # ========================================================================

    def test_overall_score_perfect_match(self, analyzer, formal_profile):
        """Score élevé pour correspondance parfaite."""
        draft = "Bonjour,\n\nJe vous remercie pour votre message. Veuillez trouver ci-joint le document.\n\nCordialement"

        result = analyzer.analyze(draft, formal_profile)

        assert result.overall_score >= 70.0
        assert result.is_acceptable()

    def test_overall_score_poor_match(self, analyzer, formal_profile):
        """Score faible pour mauvaise correspondance."""
        draft = "Salut! Cool ton message. À+"

        result = analyzer.analyze(draft, formal_profile)

        assert result.overall_score < 50.0
        assert not result.is_acceptable()

    def test_overall_score_between_0_and_100(self, analyzer, formal_profile):
        """Le score global est toujours entre 0 et 100."""
        drafts = [
            "Bonjour, Cordialement",
            "Salut! À+",
            "",
            "Un texte quelconque.",
        ]

        for draft in drafts:
            result = analyzer.analyze(draft, formal_profile)
            assert 0 <= result.overall_score <= 100

    # ========================================================================
    # Tests des cas limites
    # ========================================================================

    def test_analyze_empty_draft(self, analyzer, formal_profile):
        """Gère un brouillon vide."""
        result = analyzer.analyze("", formal_profile)

        assert isinstance(result, StyleSimilarityScore)
        assert result.overall_score == 0.0
        assert result.greeting_match is False
        assert result.closing_match is False

    def test_analyze_empty_profile_preferences(self, analyzer):
        """Gère un profil sans préférences."""
        empty_profile = WritingStyleProfile(
            account_id=1,
            analyzed_at=datetime.utcnow(),
            email_count=0,
            preferred_greetings=[],
            preferred_closings=[],
            common_words=[],
        )
        draft = "Bonjour, voici ma réponse. Cordialement"

        result = analyzer.analyze(draft, empty_profile)

        assert isinstance(result, StyleSimilarityScore)
        # Sans préférences, pas de match possible
        assert result.greeting_match is False
        assert result.closing_match is False

    def test_analysis_details_populated(self, analyzer, formal_profile):
        """Les détails d'analyse sont renseignés."""
        draft = "Bonjour,\n\nMerci.\n\nCordialement"

        result = analyzer.analyze(draft, formal_profile)

        assert "detected_greeting" in result.analysis_details
        assert "detected_closing" in result.analysis_details
        assert "detected_formality" in result.analysis_details
