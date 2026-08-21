# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour le HealthCheckUseCase.

pytest tests/test_health_check.py -v
"""

import pytest
from unittest.mock import Mock

from app.application.health_check import (
    HealthCheckUseCase,
    HealthStatus,
    SystemHealthStatus,
)
from app.domain.ports import LLMPort, LLMResponse, EmailPort


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_email_provider():
    """Crée un mock d'email provider."""
    provider = Mock(spec=EmailPort)
    provider.authenticate.return_value = True
    return provider


@pytest.fixture
def mock_llm():
    """Crée un mock de LLM."""
    llm = Mock(spec=LLMPort)
    llm.complete.return_value = LLMResponse(content="OK", input_tokens=5, output_tokens=1)
    return llm


@pytest.fixture
def health_check_use_case(mock_email_provider, mock_llm):
    """Crée un use case de health check avec des mocks."""
    return HealthCheckUseCase(
        email_provider_factory=lambda: mock_email_provider,
        llm_factory=lambda: mock_llm,
    )


# ============================================================================
# TESTS DATA CLASSES
# ============================================================================

class TestHealthStatus:
    """Tests pour HealthStatus."""

    def test_health_status_creation(self):
        """Test création d'un HealthStatus."""
        status = HealthStatus(healthy=True)
        assert status.healthy is True
        assert status.message == ""

    def test_health_status_with_message(self):
        """Test création avec message."""
        status = HealthStatus(healthy=False, message="Connection failed")
        assert status.healthy is False
        assert status.message == "Connection failed"


class TestSystemHealthStatus:
    """Tests pour SystemHealthStatus."""

    def test_system_healthy(self):
        """Test système entièrement sain."""
        status = SystemHealthStatus(
            email_provider=HealthStatus(healthy=True),
            llm=HealthStatus(healthy=True),
        )
        assert status.overall_healthy is True
        assert status.status == "healthy"

    def test_system_degraded_email(self):
        """Test système dégradé - email en erreur."""
        status = SystemHealthStatus(
            email_provider=HealthStatus(healthy=False, message="Auth failed"),
            llm=HealthStatus(healthy=True),
        )
        assert status.overall_healthy is False
        assert status.status == "degraded"

    def test_system_degraded_llm(self):
        """Test système dégradé - LLM en erreur."""
        status = SystemHealthStatus(
            email_provider=HealthStatus(healthy=True),
            llm=HealthStatus(healthy=False, message="API error"),
        )
        assert status.overall_healthy is False
        assert status.status == "degraded"

    def test_system_fully_degraded(self):
        """Test système entièrement dégradé."""
        status = SystemHealthStatus(
            email_provider=HealthStatus(healthy=False),
            llm=HealthStatus(healthy=False),
        )
        assert status.overall_healthy is False
        assert status.status == "degraded"


# ============================================================================
# TESTS HEALTH CHECK USE CASE
# ============================================================================

class TestHealthCheckUseCase:
    """Tests pour HealthCheckUseCase."""

    def test_check_email_provider_healthy(self, mock_email_provider):
        """Test check email provider sain."""
        use_case = HealthCheckUseCase(
            email_provider_factory=lambda: mock_email_provider,
            llm_factory=lambda: Mock(),
        )

        result = use_case.check_email_provider()

        assert result.healthy is True
        assert result.message == ""
        mock_email_provider.authenticate.assert_called_once()

    def test_check_email_provider_unhealthy(self):
        """Test check email provider en erreur."""
        mock_provider = Mock()
        mock_provider.authenticate.return_value = False

        use_case = HealthCheckUseCase(
            email_provider_factory=lambda: mock_provider,
            llm_factory=lambda: Mock(),
        )

        result = use_case.check_email_provider()

        assert result.healthy is False
        assert result.message == "Authentication failed"

    def test_check_email_provider_exception(self):
        """Test check email provider avec exception."""
        mock_provider = Mock()
        mock_provider.authenticate.side_effect = Exception("Connection refused")

        use_case = HealthCheckUseCase(
            email_provider_factory=lambda: mock_provider,
            llm_factory=lambda: Mock(),
        )

        result = use_case.check_email_provider()

        assert result.healthy is False
        assert "Connection refused" in result.message

    def test_check_llm_healthy(self, mock_llm):
        """Test check LLM sain."""
        use_case = HealthCheckUseCase(
            email_provider_factory=lambda: Mock(),
            llm_factory=lambda: mock_llm,
        )

        result = use_case.check_llm()

        assert result.healthy is True
        assert result.message == ""
        mock_llm.complete.assert_called_once()

    def test_check_llm_empty_response(self):
        """Test check LLM avec réponse vide."""
        mock_llm = Mock()
        mock_llm.complete.return_value = LLMResponse(content="", input_tokens=5, output_tokens=0)

        use_case = HealthCheckUseCase(
            email_provider_factory=lambda: Mock(),
            llm_factory=lambda: mock_llm,
        )

        result = use_case.check_llm()

        assert result.healthy is False
        assert result.message == "Empty response"

    def test_check_llm_exception(self):
        """Test check LLM avec exception."""
        mock_llm = Mock()
        mock_llm.complete.side_effect = Exception("API rate limit exceeded")

        use_case = HealthCheckUseCase(
            email_provider_factory=lambda: Mock(),
            llm_factory=lambda: mock_llm,
        )

        result = use_case.check_llm()

        assert result.healthy is False
        assert "rate limit" in result.message

    def test_execute_all_healthy(self, health_check_use_case):
        """Test execute avec tous les composants sains."""
        result = health_check_use_case.execute()

        assert result.overall_healthy is True
        assert result.status == "healthy"
        assert result.email_provider.healthy is True
        assert result.llm.healthy is True

    def test_execute_partial_failure(self, mock_llm):
        """Test execute avec échec partiel."""
        mock_provider = Mock()
        mock_provider.authenticate.return_value = False

        use_case = HealthCheckUseCase(
            email_provider_factory=lambda: mock_provider,
            llm_factory=lambda: mock_llm,
        )

        result = use_case.execute()

        assert result.overall_healthy is False
        assert result.status == "degraded"
        assert result.email_provider.healthy is False
        assert result.llm.healthy is True

    def test_factory_called_for_each_check(self):
        """Test que les factories sont appelées pour chaque check."""
        email_factory = Mock(return_value=Mock(authenticate=Mock(return_value=True)))
        llm_factory = Mock(return_value=Mock(complete=Mock(return_value=LLMResponse(content="OK"))))

        use_case = HealthCheckUseCase(
            email_provider_factory=email_factory,
            llm_factory=llm_factory,
        )

        use_case.execute()

        email_factory.assert_called_once()
        llm_factory.assert_called_once()

    def test_llm_complete_correct_parameters(self, mock_llm):
        """Test que le LLM est appelé avec les bons paramètres."""
        use_case = HealthCheckUseCase(
            email_provider_factory=lambda: Mock(authenticate=Mock(return_value=True)),
            llm_factory=lambda: mock_llm,
        )

        use_case.check_llm()

        mock_llm.complete.assert_called_once_with(
            system="You are a test assistant.",
            user="Reply with OK",
            max_tokens=10
        )


# ============================================================================
# TESTS D'INTÉGRATION
# ============================================================================

class TestHealthCheckIntegration:
    """Tests d'intégration pour le health check."""

    def test_full_healthy_workflow(self):
        """Test workflow complet avec tous composants sains."""
        # Setup
        email_provider = Mock()
        email_provider.authenticate.return_value = True

        llm = Mock()
        llm.complete.return_value = LLMResponse(content="OK", input_tokens=5, output_tokens=1)

        use_case = HealthCheckUseCase(
            email_provider_factory=lambda: email_provider,
            llm_factory=lambda: llm,
        )

        # Execute
        result = use_case.execute()

        # Verify
        assert result.status == "healthy"
        assert result.email_provider.healthy
        assert result.llm.healthy

    def test_full_degraded_workflow(self):
        """Test workflow complet avec composants en échec."""
        # Setup
        email_provider = Mock()
        email_provider.authenticate.side_effect = Exception("IMAP error")

        llm = Mock()
        llm.complete.side_effect = Exception("API key invalid")

        use_case = HealthCheckUseCase(
            email_provider_factory=lambda: email_provider,
            llm_factory=lambda: llm,
        )

        # Execute
        result = use_case.execute()

        # Verify
        assert result.status == "degraded"
        assert not result.email_provider.healthy
        assert "IMAP error" in result.email_provider.message
        assert not result.llm.healthy
        assert "API key invalid" in result.llm.message


# ============================================================================
# TESTS EDGE CASES SUPPLÉMENTAIRES
# ============================================================================

class TestHealthCheckEdgeCases:
    """Tests edge cases pour le health check."""

    def _create_use_case(self, email_factory=None, llm_factory=None):
        """Helper pour créer un HealthCheckUseCase avec des factories par défaut."""
        return HealthCheckUseCase(
            email_provider_factory=email_factory or (lambda: Mock()),
            llm_factory=llm_factory or (lambda: Mock()),
        )

    def test_email_factory_raises_exception(self):
        """Test quand la factory email lève une exception."""
        def failing_factory():
            raise RuntimeError("Factory failed to create provider")

        use_case = self._create_use_case(email_factory=failing_factory)

        result = use_case.check_email_provider()

        assert result.healthy is False
        assert "Factory failed" in result.message

    def test_llm_factory_raises_exception(self):
        """Test quand la factory LLM lève une exception."""
        def failing_factory():
            raise RuntimeError("Factory failed to create LLM")

        use_case = self._create_use_case(llm_factory=failing_factory)

        result = use_case.check_llm()

        assert result.healthy is False
        assert "Factory failed" in result.message

    def test_llm_response_is_none(self):
        """Test quand la réponse LLM est None."""
        mock_llm = Mock()
        mock_llm.complete.return_value = None

        use_case = self._create_use_case(llm_factory=lambda: mock_llm)

        result = use_case.check_llm()

        assert result.healthy is False
        assert result.message == "Empty response"

    def test_email_authenticate_returns_none(self):
        """Test quand authenticate() retourne None (valeur falsy).

        Note: Le code actuel assigne directement la valeur de retour à healthy,
        donc None est propagé. C'est un comportement potentiellement problématique
        mais documenté par ce test.
        """
        mock_provider = Mock()
        mock_provider.authenticate.return_value = None

        use_case = self._create_use_case(email_factory=lambda: mock_provider)

        result = use_case.check_email_provider()

        # Current behavior: None is assigned directly to healthy
        # This could be a bug - ideally should be converted to False
        assert result.healthy is None
        assert result.message == "Authentication failed"

    def test_exception_with_unicode_message(self):
        """Test exception avec message unicode/caractères spéciaux."""
        mock_provider = Mock()
        mock_provider.authenticate.side_effect = Exception("Échec: connexion 日本語 emoji 🔥")

        use_case = self._create_use_case(email_factory=lambda: mock_provider)

        result = use_case.check_email_provider()

        assert result.healthy is False
        assert "Échec" in result.message
        assert "日本語" in result.message

    def test_timeout_exception(self):
        """Test exception de timeout."""
        from socket import timeout as SocketTimeout

        mock_llm = Mock()
        mock_llm.complete.side_effect = SocketTimeout("Connection timed out")

        use_case = self._create_use_case(llm_factory=lambda: mock_llm)

        result = use_case.check_llm()

        assert result.healthy is False
        assert "timed out" in result.message

    def test_llm_response_content_is_none(self):
        """Test quand response.content est None."""
        mock_llm = Mock()
        mock_llm.complete.return_value = LLMResponse(content=None, input_tokens=5, output_tokens=0)

        use_case = self._create_use_case(llm_factory=lambda: mock_llm)

        result = use_case.check_llm()

        assert result.healthy is False
        assert result.message == "Empty response"

    def test_llm_response_content_whitespace_only(self):
        """Test quand response.content contient uniquement des espaces."""
        mock_llm = Mock()
        mock_llm.complete.return_value = LLMResponse(content="   \n\t  ", input_tokens=5, output_tokens=3)

        use_case = self._create_use_case(llm_factory=lambda: mock_llm)

        result = use_case.check_llm()

        # Whitespace-only content is truthy, so should be healthy
        # (current implementation uses bool(response.content) which is True for "   ")
        assert result.healthy is True

    def test_exception_with_empty_message(self):
        """Test exception avec message vide."""
        mock_provider = Mock()
        mock_provider.authenticate.side_effect = Exception("")

        use_case = self._create_use_case(email_factory=lambda: mock_provider)

        result = use_case.check_email_provider()

        assert result.healthy is False
        # Empty message is still a valid exception
        assert result.message == ""

    def test_keyboard_interrupt_propagates(self):
        """Test que KeyboardInterrupt n'est pas attrapée."""
        mock_provider = Mock()
        mock_provider.authenticate.side_effect = KeyboardInterrupt()

        use_case = self._create_use_case(email_factory=lambda: mock_provider)

        # KeyboardInterrupt should propagate, not be caught
        with pytest.raises(KeyboardInterrupt):
            use_case.check_email_provider()

    def test_system_exit_propagates(self):
        """Test que SystemExit n'est pas attrapée."""
        mock_llm = Mock()
        mock_llm.complete.side_effect = SystemExit(1)

        use_case = self._create_use_case(llm_factory=lambda: mock_llm)

        # SystemExit should propagate, not be caught
        with pytest.raises(SystemExit):
            use_case.check_llm()

    def test_execute_with_all_factories_failing(self):
        """Test execute quand toutes les factories échouent."""
        def failing_email_factory():
            raise RuntimeError("Email factory failed")

        def failing_llm_factory():
            raise RuntimeError("LLM factory failed")

        use_case = self._create_use_case(
            email_factory=failing_email_factory,
            llm_factory=failing_llm_factory,
        )

        result = use_case.execute()

        assert result.status == "degraded"
        assert not result.email_provider.healthy
        assert "Email factory failed" in result.email_provider.message
        assert not result.llm.healthy
        assert "LLM factory failed" in result.llm.message
