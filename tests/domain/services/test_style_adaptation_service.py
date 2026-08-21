# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests unitaires pour StyleAdaptationService.

Story 4-4: Style Adaptation Engine
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.domain.services.style_adaptation_service import StyleAdaptationService
from app.domain.entities.writing_style import WritingStyleProfile, FormalityLevel
from app.domain.entities.style_similarity import StyleSimilarityScore


class TestStyleAdaptationService:
    """Tests pour StyleAdaptationService."""

    @pytest.fixture
    def mock_writing_style_service(self):
        """Mock du WritingStyleService."""
        service = MagicMock()
        return service

    @pytest.fixture
    def mock_similarity_analyzer(self):
        """Mock du StyleSimilarityAnalyzer."""
        analyzer = MagicMock()
        return analyzer

    @pytest.fixture
    def mock_drafter_agent(self):
        """Mock du DrafterAgent."""
        agent = MagicMock()
        agent.draft.return_value = "Bonjour,\n\nMerci pour votre message.\n\nCordialement"
        return agent

    @pytest.fixture
    def sample_profile(self) -> WritingStyleProfile:
        """Profil de style sample."""
        return WritingStyleProfile(
            account_id=1,
            analyzed_at=datetime.now(timezone.utc),
            email_count=10,
            formality_level=FormalityLevel.FORMAL,
            preferred_greetings=["Bonjour"],
            preferred_closings=["Cordialement"],
            common_words=["vous", "votre"],
        )

    @pytest.fixture
    def service(
        self, mock_writing_style_service, mock_similarity_analyzer, mock_drafter_agent
    ) -> StyleAdaptationService:
        """Service avec mocks injectés."""
        return StyleAdaptationService(
            writing_style_service=mock_writing_style_service,
            similarity_analyzer=mock_similarity_analyzer,
            drafter_agent=mock_drafter_agent,
        )

    # ========================================================================
    # Tests d'instanciation
    # ========================================================================

    def test_service_instantiation(self, service):
        """Le service peut être instancié."""
        assert service is not None
        assert isinstance(service, StyleAdaptationService)

    # ========================================================================
    # Tests de get_style_context
    # ========================================================================

    def test_get_style_context_returns_context_when_profile_exists(
        self, service, mock_writing_style_service, sample_profile
    ):
        """get_style_context retourne le contexte si le profil existe."""
        mock_writing_style_service.get_prompt_context.return_value = (
            "Style: formel, vouvoiement"
        )

        result = service.get_style_context(account_id=1)

        assert result == "Style: formel, vouvoiement"
        mock_writing_style_service.get_prompt_context.assert_called_once_with(1)

    def test_get_style_context_returns_none_when_no_profile(
        self, service, mock_writing_style_service
    ):
        """get_style_context retourne None si pas de profil."""
        mock_writing_style_service.get_prompt_context.return_value = None

        result = service.get_style_context(account_id=999)

        assert result is None

    @patch("app.domain.services.style_adaptation_service.STYLE_ADAPTATION_ENABLED", False)
    def test_get_style_context_returns_none_when_disabled(
        self, mock_writing_style_service, mock_similarity_analyzer, mock_drafter_agent
    ):
        """get_style_context retourne None si l'adaptation est désactivée."""
        service = StyleAdaptationService(
            writing_style_service=mock_writing_style_service,
            similarity_analyzer=mock_similarity_analyzer,
            drafter_agent=mock_drafter_agent,
        )
        mock_writing_style_service.get_prompt_context.return_value = "Some context"

        result = service.get_style_context(account_id=1)

        assert result is None
        # Ne doit pas appeler le service si désactivé
        mock_writing_style_service.get_prompt_context.assert_not_called()

    # ========================================================================
    # Tests de draft_with_style
    # ========================================================================

    def test_draft_with_style_uses_style_context(
        self, service, mock_writing_style_service, mock_drafter_agent
    ):
        """draft_with_style utilise le contexte de style."""
        mock_writing_style_service.get_prompt_context.return_value = (
            "Style: décontracté"
        )

        result = service.draft_with_style(
            account_id=1, email_content="Email original"
        )

        mock_drafter_agent.draft.assert_called_once_with(
            "Email original", style_context="Style: décontracté"
        )
        assert "Merci" in result

    def test_draft_with_style_without_profile_uses_standard_draft(
        self, service, mock_writing_style_service, mock_drafter_agent
    ):
        """draft_with_style sans profil utilise le draft standard."""
        mock_writing_style_service.get_prompt_context.return_value = None

        service.draft_with_style(
            account_id=1, email_content="Email original"
        )

        # Appel sans style_context (ou avec None)
        mock_drafter_agent.draft.assert_called_once_with(
            "Email original", style_context=None
        )

    def test_draft_with_style_respects_use_style_false(
        self, service, mock_writing_style_service, mock_drafter_agent
    ):
        """draft_with_style respecte use_style=False."""
        mock_writing_style_service.get_prompt_context.return_value = "Some style"

        service.draft_with_style(
            account_id=1, email_content="Email", use_style=False
        )

        # Doit appeler sans style_context
        mock_drafter_agent.draft.assert_called_once_with("Email", style_context=None)
        # Ne doit pas chercher le style
        mock_writing_style_service.get_prompt_context.assert_not_called()

    # ========================================================================
    # Tests de calculate_similarity
    # ========================================================================

    def test_calculate_similarity_returns_score(
        self, service, mock_writing_style_service, mock_similarity_analyzer, sample_profile
    ):
        """calculate_similarity retourne un score."""
        mock_writing_style_service.get_profile.return_value = sample_profile
        mock_similarity_analyzer.analyze.return_value = StyleSimilarityScore(
            overall_score=85.0,
            greeting_match=True,
            closing_match=True,
            formality_match=True,
            vocabulary_overlap=0.5,
        )

        result = service.calculate_similarity(
            account_id=1, draft="Bonjour, Cordialement"
        )

        assert result.overall_score == 85.0
        mock_similarity_analyzer.analyze.assert_called_once()

    def test_calculate_similarity_without_profile_returns_default(
        self, service, mock_writing_style_service, mock_similarity_analyzer
    ):
        """calculate_similarity sans profil retourne un score par défaut."""
        mock_writing_style_service.get_profile.return_value = None

        result = service.calculate_similarity(
            account_id=999, draft="Test draft"
        )

        # Score par défaut car pas de profil
        assert isinstance(result, StyleSimilarityScore)
        # L'analyzer ne doit pas être appelé
        mock_similarity_analyzer.analyze.assert_not_called()

    # ========================================================================
    # Tests de is_style_acceptable
    # ========================================================================

    def test_is_style_acceptable_above_threshold(
        self, service, mock_writing_style_service, mock_similarity_analyzer, sample_profile
    ):
        """is_style_acceptable retourne True si score > seuil."""
        mock_writing_style_service.get_profile.return_value = sample_profile
        mock_similarity_analyzer.analyze.return_value = StyleSimilarityScore(
            overall_score=80.0,
            greeting_match=True,
            closing_match=True,
            formality_match=True,
            vocabulary_overlap=0.5,
        )

        result = service.is_style_acceptable(account_id=1, draft="Draft")

        assert result is True

    def test_is_style_acceptable_below_threshold(
        self, service, mock_writing_style_service, mock_similarity_analyzer, sample_profile
    ):
        """is_style_acceptable retourne False si score < seuil."""
        mock_writing_style_service.get_profile.return_value = sample_profile
        mock_similarity_analyzer.analyze.return_value = StyleSimilarityScore(
            overall_score=50.0,
            greeting_match=False,
            closing_match=False,
            formality_match=True,
            vocabulary_overlap=0.1,
        )

        result = service.is_style_acceptable(account_id=1, draft="Draft")

        assert result is False

    def test_is_style_acceptable_with_custom_threshold(
        self, service, mock_writing_style_service, mock_similarity_analyzer, sample_profile
    ):
        """is_style_acceptable accepte un seuil personnalisé."""
        mock_writing_style_service.get_profile.return_value = sample_profile
        mock_similarity_analyzer.analyze.return_value = StyleSimilarityScore(
            overall_score=60.0,
            greeting_match=True,
            closing_match=False,
            formality_match=True,
            vocabulary_overlap=0.3,
        )

        # Avec seuil 50, acceptable
        assert service.is_style_acceptable(account_id=1, draft="Draft", threshold=50.0) is True
        # Avec seuil 70, non acceptable
        assert service.is_style_acceptable(account_id=1, draft="Draft", threshold=70.0) is False
