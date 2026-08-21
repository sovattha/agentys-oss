# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests edge cases pour CompleteDraftUseCase et HealthCheckUseCase.

Ces tests vérifient:
- CompleteDraft avec différents formats d'input
- Parsing de réponses LLM diverses
- HealthCheck avec providers fonctionnels/défaillants
- Gestion des erreurs et cas limites
"""

import pytest
from unittest.mock import MagicMock

from app.domain.entities import (
    DraftInput,
    DraftInputTone,
    CompletedDraft,
    TokenUsage,
)
from app.domain.ports import LLMPort, LLMResponse, EmailPort
from app.application import CompleteDraftUseCase
from app.application.health_check import (
    HealthCheckUseCase,
    HealthStatus,
    SystemHealthStatus,
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_llm():
    """LLM mocké."""
    mock = MagicMock(spec=LLMPort)
    mock.name = "mock-llm"
    mock.model = "mock-model"
    mock.complete.return_value = LLMResponse(
        content="OBJET: Test Subject\n\nBonjour,\n\nCeci est le contenu.\n\nCordialement",
        input_tokens=100,
        output_tokens=50,
        model="mock-model"
    )
    return mock


@pytest.fixture
def token_usage():
    """TokenUsage de test."""
    return TokenUsage()


@pytest.fixture
def sample_draft_input():
    """DraftInput de test."""
    return DraftInput(
        raw_input="Brouillon: meeting demain",
        key_points=["Confirmer le meeting", "Demain 10h"],
        recipient="Jean Dupont",
        subject_hint="Confirmation meeting",
        tone=DraftInputTone.FORMAL
    )


# ============================================================================
# TESTS - COMPLETE DRAFT USE CASE
# ============================================================================

class TestCompleteDraftUseCase:
    """Tests pour CompleteDraftUseCase avec edge cases."""

    def test_execute_success(self, mock_llm, token_usage, sample_draft_input):
        """Exécution réussie."""
        use_case = CompleteDraftUseCase(
            llm=mock_llm,
            token_usage=token_usage
        )
        result = use_case.execute(sample_draft_input)

        assert isinstance(result, CompletedDraft)
        assert result.subject == "Test Subject"
        assert "contenu" in result.body
        mock_llm.complete.assert_called_once()

    def test_execute_tracks_tokens(self, mock_llm, token_usage, sample_draft_input):
        """Les tokens sont trackés."""
        use_case = CompleteDraftUseCase(
            llm=mock_llm,
            token_usage=token_usage
        )
        use_case.execute(sample_draft_input)

        assert token_usage.input_tokens == 100
        assert token_usage.output_tokens == 50

    def test_execute_with_empty_key_points(self, mock_llm, token_usage):
        """Exécution avec key_points vides."""
        draft_input = DraftInput(
            raw_input="Envoyer un email de confirmation",
            key_points=[],
            tone=DraftInputTone.NEUTRAL
        )
        use_case = CompleteDraftUseCase(
            llm=mock_llm,
            token_usage=token_usage
        )
        result = use_case.execute(draft_input)

        assert isinstance(result, CompletedDraft)

    def test_execute_with_knowledge_base(self, mock_llm, token_usage, sample_draft_input):
        """Exécution avec knowledge base."""
        use_case = CompleteDraftUseCase(
            llm=mock_llm,
            knowledge_base="# Company Policy\n\nTu represents Acme Inc.",
            token_usage=token_usage
        )
        use_case.execute(sample_draft_input)

        call_args = mock_llm.complete.call_args
        system_prompt = call_args.kwargs["system"]
        assert "CONTEXTE ENTREPRISE" in system_prompt
        assert "Acme Inc" in system_prompt

    def test_parse_response_standard_format(self, mock_llm, token_usage, sample_draft_input):
        """Parsing du format standard OBJET: + corps."""
        mock_llm.complete.return_value = LLMResponse(
            content="OBJET: Ma demande de réunion\n\nBonjour Jean,\n\nJ'aimerais...\n\nCordialement",
            input_tokens=100,
            output_tokens=50,
            model="mock"
        )
        use_case = CompleteDraftUseCase(
            llm=mock_llm,
            token_usage=token_usage
        )
        result = use_case.execute(sample_draft_input)

        assert result.subject == "Ma demande de réunion"
        assert "Bonjour Jean" in result.body

    def test_parse_response_objet_with_space(self, mock_llm, token_usage, sample_draft_input):
        """Parsing avec 'OBJET :' (espace avant deux-points)."""
        mock_llm.complete.return_value = LLMResponse(
            content="OBJET : Sujet avec espace\n\nCorps du message",
            input_tokens=100,
            output_tokens=50,
            model="mock"
        )
        use_case = CompleteDraftUseCase(
            llm=mock_llm,
            token_usage=token_usage
        )
        result = use_case.execute(sample_draft_input)

        assert result.subject == "Sujet avec espace"

    def test_parse_response_lowercase_objet(self, mock_llm, token_usage, sample_draft_input):
        """Parsing avec 'objet:' en minuscules."""
        mock_llm.complete.return_value = LLMResponse(
            content="objet: sujet minuscule\n\nCorps",
            input_tokens=100,
            output_tokens=50,
            model="mock"
        )
        use_case = CompleteDraftUseCase(
            llm=mock_llm,
            token_usage=token_usage
        )
        result = use_case.execute(sample_draft_input)

        assert result.subject == "sujet minuscule"

    def test_parse_response_no_objet_uses_hint(self, mock_llm, token_usage, sample_draft_input):
        """Sans OBJET:, utilise le subject_hint."""
        mock_llm.complete.return_value = LLMResponse(
            content="Bonjour,\n\nVoici mon message.\n\nCordialement",
            input_tokens=100,
            output_tokens=50,
            model="mock"
        )
        use_case = CompleteDraftUseCase(
            llm=mock_llm,
            token_usage=token_usage
        )
        result = use_case.execute(sample_draft_input)

        assert result.subject == "Confirmation meeting"  # subject_hint

    def test_parse_response_no_objet_uses_first_point(self, mock_llm, token_usage):
        """Sans OBJET: ni hint, utilise le premier point clé."""
        draft_input = DraftInput(
            raw_input="test",
            key_points=["Premier point important à mentionner dans le sujet"],
            tone=DraftInputTone.NEUTRAL
        )
        mock_llm.complete.return_value = LLMResponse(
            content="Message sans objet",
            input_tokens=100,
            output_tokens=50,
            model="mock"
        )
        use_case = CompleteDraftUseCase(
            llm=mock_llm,
            token_usage=token_usage
        )
        result = use_case.execute(draft_input)

        # Premiers 50 chars + "..."
        assert "Premier point important" in result.subject

    def test_parse_response_empty(self, mock_llm, token_usage, sample_draft_input):
        """Réponse LLM vide."""
        mock_llm.complete.return_value = LLMResponse(
            content="",
            input_tokens=100,
            output_tokens=0,
            model="mock"
        )
        use_case = CompleteDraftUseCase(
            llm=mock_llm,
            token_usage=token_usage
        )
        result = use_case.execute(sample_draft_input)

        # Devrait utiliser fallbacks
        assert result.subject == "Confirmation meeting"
        assert result.body == ""

    def test_execute_all_tones(self, mock_llm, token_usage):
        """Test avec tous les tons disponibles."""
        for tone in DraftInputTone:
            draft_input = DraftInput(
                raw_input="test",
                key_points=["Point"],
                tone=tone
            )
            use_case = CompleteDraftUseCase(
                llm=mock_llm,
                token_usage=token_usage
            )
            result = use_case.execute(draft_input)

            assert result.tone_used == tone

    def test_execute_preserves_recipient(self, mock_llm, token_usage, sample_draft_input):
        """Le destinataire est préservé."""
        use_case = CompleteDraftUseCase(
            llm=mock_llm,
            token_usage=token_usage
        )
        result = use_case.execute(sample_draft_input)

        assert result.recipient == "Jean Dupont"

    def test_llm_raises_exception(self, mock_llm, token_usage, sample_draft_input):
        """LLM lève une exception."""
        mock_llm.complete.side_effect = Exception("API Error")
        use_case = CompleteDraftUseCase(
            llm=mock_llm,
            token_usage=token_usage
        )

        with pytest.raises(Exception, match="API Error"):
            use_case.execute(sample_draft_input)

    def test_token_usage_auto_created(self, mock_llm, sample_draft_input):
        """TokenUsage créé automatiquement si non fourni."""
        use_case = CompleteDraftUseCase(llm=mock_llm)
        assert use_case.token_usage is not None
        assert isinstance(use_case.token_usage, TokenUsage)

    def test_max_tokens_passed_to_llm(self, mock_llm, token_usage, sample_draft_input):
        """max_tokens passé au LLM."""
        use_case = CompleteDraftUseCase(
            llm=mock_llm,
            max_tokens=2048,
            token_usage=token_usage
        )
        use_case.execute(sample_draft_input)

        call_kwargs = mock_llm.complete.call_args[1]
        assert call_kwargs["max_tokens"] == 2048

    def test_parse_multiline_objet(self, mock_llm, token_usage, sample_draft_input):
        """OBJET: avec sauts de ligne après."""
        mock_llm.complete.return_value = LLMResponse(
            content="OBJET: Sujet test\n\n\n\nCorps après plusieurs lignes vides",
            input_tokens=100,
            output_tokens=50,
            model="mock"
        )
        use_case = CompleteDraftUseCase(
            llm=mock_llm,
            token_usage=token_usage
        )
        result = use_case.execute(sample_draft_input)

        assert result.subject == "Sujet test"
        assert "Corps après" in result.body

    def test_parse_unicode_content(self, mock_llm, token_usage, sample_draft_input):
        """Contenu unicode."""
        mock_llm.complete.return_value = LLMResponse(
            content="OBJET: Réunion 日本語\n\nBonjour 🎉 émojis",
            input_tokens=100,
            output_tokens=50,
            model="mock"
        )
        use_case = CompleteDraftUseCase(
            llm=mock_llm,
            token_usage=token_usage
        )
        result = use_case.execute(sample_draft_input)

        assert "日本語" in result.subject
        assert "🎉" in result.body


# ============================================================================
# TESTS - HEALTH STATUS ENTITY
# ============================================================================

class TestHealthStatus:
    """Tests pour l'entité HealthStatus."""

    def test_health_status_healthy(self):
        """HealthStatus healthy."""
        status = HealthStatus(healthy=True)
        assert status.healthy is True
        assert status.message == ""

    def test_health_status_unhealthy_with_message(self):
        """HealthStatus unhealthy avec message."""
        status = HealthStatus(healthy=False, message="Connection refused")
        assert status.healthy is False
        assert status.message == "Connection refused"

    def test_health_status_healthy_with_message(self):
        """HealthStatus healthy avec message (info)."""
        status = HealthStatus(healthy=True, message="Connected to backup server")
        assert status.healthy is True
        assert "backup" in status.message


# ============================================================================
# TESTS - SYSTEM HEALTH STATUS ENTITY
# ============================================================================

class TestSystemHealthStatus:
    """Tests pour l'entité SystemHealthStatus."""

    def test_all_healthy(self):
        """Tous les composants sont sains."""
        status = SystemHealthStatus(
            email_provider=HealthStatus(healthy=True),
            llm=HealthStatus(healthy=True)
        )
        assert status.overall_healthy is True
        assert status.status == "healthy"

    def test_email_unhealthy(self):
        """Email provider défaillant."""
        status = SystemHealthStatus(
            email_provider=HealthStatus(healthy=False, message="Auth failed"),
            llm=HealthStatus(healthy=True)
        )
        assert status.overall_healthy is False
        assert status.status == "degraded"

    def test_llm_unhealthy(self):
        """LLM défaillant."""
        status = SystemHealthStatus(
            email_provider=HealthStatus(healthy=True),
            llm=HealthStatus(healthy=False, message="API down")
        )
        assert status.overall_healthy is False
        assert status.status == "degraded"

    def test_all_unhealthy(self):
        """Tous les composants défaillants."""
        status = SystemHealthStatus(
            email_provider=HealthStatus(healthy=False),
            llm=HealthStatus(healthy=False)
        )
        assert status.overall_healthy is False
        assert status.status == "degraded"


# ============================================================================
# TESTS - HEALTH CHECK USE CASE
# ============================================================================

class TestHealthCheckUseCase:
    """Tests pour HealthCheckUseCase avec edge cases."""

    @pytest.fixture
    def mock_email_provider(self):
        """Email provider mocké."""
        mock = MagicMock(spec=EmailPort)
        mock.authenticate.return_value = True
        return mock

    @pytest.fixture
    def mock_llm_healthy(self):
        """LLM mocké healthy."""
        mock = MagicMock(spec=LLMPort)
        mock.complete.return_value = LLMResponse(
            content="OK",
            input_tokens=10,
            output_tokens=1,
            model="test"
        )
        return mock

    def test_execute_all_healthy(self, mock_email_provider, mock_llm_healthy):
        """Tous les services sont sains."""
        use_case = HealthCheckUseCase(
            email_provider_factory=lambda: mock_email_provider,
            llm_factory=lambda: mock_llm_healthy
        )
        result = use_case.execute()

        assert result.overall_healthy is True
        assert result.email_provider.healthy is True
        assert result.llm.healthy is True

    def test_check_email_provider_auth_fails(self, mock_email_provider):
        """Email provider échoue à l'authentification."""
        mock_email_provider.authenticate.return_value = False

        use_case = HealthCheckUseCase(
            email_provider_factory=lambda: mock_email_provider,
            llm_factory=lambda: MagicMock()
        )
        result = use_case.check_email_provider()

        assert result.healthy is False
        assert "Authentication failed" in result.message

    def test_check_email_provider_raises_exception(self):
        """Email provider lève une exception."""
        def failing_factory():
            raise ConnectionError("Cannot connect to SMTP server")

        use_case = HealthCheckUseCase(
            email_provider_factory=failing_factory,
            llm_factory=lambda: MagicMock()
        )
        result = use_case.check_email_provider()

        assert result.healthy is False
        assert "SMTP" in result.message

    def test_check_llm_empty_response(self, mock_llm_healthy):
        """LLM retourne réponse vide."""
        mock_llm_healthy.complete.return_value = LLMResponse(
            content="",
            input_tokens=10,
            output_tokens=0,
            model="test"
        )

        use_case = HealthCheckUseCase(
            email_provider_factory=lambda: MagicMock(),
            llm_factory=lambda: mock_llm_healthy
        )
        result = use_case.check_llm()

        assert result.healthy is False
        assert "Empty response" in result.message

    def test_check_llm_raises_exception(self):
        """LLM lève une exception."""
        mock_llm = MagicMock(spec=LLMPort)
        mock_llm.complete.side_effect = Exception("Rate limited")

        use_case = HealthCheckUseCase(
            email_provider_factory=lambda: MagicMock(),
            llm_factory=lambda: mock_llm
        )
        result = use_case.check_llm()

        assert result.healthy is False
        assert "Rate limited" in result.message

    def test_check_llm_none_response(self):
        """LLM retourne None."""
        mock_llm = MagicMock(spec=LLMPort)
        mock_llm.complete.return_value = None

        use_case = HealthCheckUseCase(
            email_provider_factory=lambda: MagicMock(),
            llm_factory=lambda: mock_llm
        )
        result = use_case.check_llm()

        assert result.healthy is False

    def test_execute_email_fails_llm_ok(self, mock_email_provider, mock_llm_healthy):
        """Email défaillant, LLM OK."""
        mock_email_provider.authenticate.side_effect = Exception("Timeout")

        use_case = HealthCheckUseCase(
            email_provider_factory=lambda: mock_email_provider,
            llm_factory=lambda: mock_llm_healthy
        )
        result = use_case.execute()

        assert result.overall_healthy is False
        assert result.email_provider.healthy is False
        assert result.llm.healthy is True

    def test_execute_email_ok_llm_fails(self, mock_email_provider, mock_llm_healthy):
        """Email OK, LLM défaillant."""
        mock_llm_healthy.complete.side_effect = Exception("API Error")

        use_case = HealthCheckUseCase(
            email_provider_factory=lambda: mock_email_provider,
            llm_factory=lambda: mock_llm_healthy
        )
        result = use_case.execute()

        assert result.overall_healthy is False
        assert result.email_provider.healthy is True
        assert result.llm.healthy is False

    def test_execute_both_fail(self):
        """Les deux services échouent."""
        def failing_email():
            raise Exception("Email down")

        def failing_llm():
            raise Exception("LLM down")

        use_case = HealthCheckUseCase(
            email_provider_factory=failing_email,
            llm_factory=failing_llm
        )
        result = use_case.execute()

        assert result.overall_healthy is False
        assert result.email_provider.healthy is False
        assert result.llm.healthy is False

    def test_factories_called_each_time(self, mock_email_provider, mock_llm_healthy):
        """Les factories sont appelées à chaque check."""
        email_calls = []
        llm_calls = []

        def email_factory():
            email_calls.append(1)
            return mock_email_provider

        def llm_factory():
            llm_calls.append(1)
            return mock_llm_healthy

        use_case = HealthCheckUseCase(
            email_provider_factory=email_factory,
            llm_factory=llm_factory
        )

        use_case.execute()
        use_case.execute()

        assert len(email_calls) == 2
        assert len(llm_calls) == 2

    def test_check_individual_components(self, mock_email_provider, mock_llm_healthy):
        """Test des checks individuels."""
        use_case = HealthCheckUseCase(
            email_provider_factory=lambda: mock_email_provider,
            llm_factory=lambda: mock_llm_healthy
        )

        email_status = use_case.check_email_provider()
        llm_status = use_case.check_llm()

        assert email_status.healthy is True
        assert llm_status.healthy is True
