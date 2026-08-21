# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests unitaires pour HealthCheckUseCase.

Couvre:
- Vérification de la santé du email provider
- Vérification de la santé du LLM
- État de santé global du système
- Gestion des erreurs et exceptions
"""

from unittest.mock import MagicMock
from app.application.health_check import (
    HealthCheckUseCase,
    HealthStatus,
    SystemHealthStatus,
)
from app.domain.ports import EmailPort, LLMPort
from app.domain.ports.llm_port import LLMResponse


class TestHealthStatus:
    """Tests de la classe HealthStatus."""

    def test_health_status_healthy_true(self):
        """HealthStatus peut indiquer un état sain."""
        status = HealthStatus(healthy=True, message="All good")
        assert status.healthy is True
        assert status.message == "All good"

    def test_health_status_healthy_false(self):
        """HealthStatus peut indiquer un état non sain."""
        status = HealthStatus(healthy=False, message="Connection failed")
        assert status.healthy is False
        assert status.message == "Connection failed"

    def test_health_status_default_message(self):
        """HealthStatus a un message par défaut vide."""
        status = HealthStatus(healthy=True)
        assert status.message == ""

    def test_health_status_empty_message(self):
        """HealthStatus peut avoir un message vide."""
        status = HealthStatus(healthy=True, message="")
        assert status.message == ""


class TestSystemHealthStatus:
    """Tests de la classe SystemHealthStatus."""

    def test_system_health_status_both_healthy(self):
        """SystemHealthStatus reconnaît quand tout est sain."""
        email_status = HealthStatus(healthy=True)
        llm_status = HealthStatus(healthy=True)
        system = SystemHealthStatus(
            email_provider=email_status,
            llm=llm_status
        )
        assert system.overall_healthy is True
        assert system.status == "healthy"

    def test_system_health_status_email_unhealthy(self):
        """SystemHealthStatus reconnaît quand email est non sain."""
        email_status = HealthStatus(healthy=False, message="Auth failed")
        llm_status = HealthStatus(healthy=True)
        system = SystemHealthStatus(
            email_provider=email_status,
            llm=llm_status
        )
        assert system.overall_healthy is False
        assert system.status == "degraded"

    def test_system_health_status_llm_unhealthy(self):
        """SystemHealthStatus reconnaît quand LLM est non sain."""
        email_status = HealthStatus(healthy=True)
        llm_status = HealthStatus(healthy=False, message="No response")
        system = SystemHealthStatus(
            email_provider=email_status,
            llm=llm_status
        )
        assert system.overall_healthy is False
        assert system.status == "degraded"

    def test_system_health_status_both_unhealthy(self):
        """SystemHealthStatus reconnaît quand tout est non sain."""
        email_status = HealthStatus(healthy=False, message="Email error")
        llm_status = HealthStatus(healthy=False, message="LLM error")
        system = SystemHealthStatus(
            email_provider=email_status,
            llm=llm_status
        )
        assert system.overall_healthy is False
        assert system.status == "degraded"

    def test_system_health_status_properties(self):
        """SystemHealthStatus a les propriétés requises."""
        email_status = HealthStatus(healthy=True)
        llm_status = HealthStatus(healthy=True)
        system = SystemHealthStatus(
            email_provider=email_status,
            llm=llm_status
        )
        assert hasattr(system, "overall_healthy")
        assert hasattr(system, "status")
        assert isinstance(system.overall_healthy, bool)
        assert isinstance(system.status, str)


class TestHealthCheckUseCaseEmailProvider:
    """Tests de check_email_provider() du HealthCheckUseCase."""

    def test_check_email_provider_healthy(self):
        """check_email_provider() retourne healthy=True si authenticate() retourne True."""
        mock_provider = MagicMock(spec=EmailPort)
        mock_provider.authenticate.return_value = True

        def factory():
            return mock_provider
        usecase = HealthCheckUseCase(factory, MagicMock())

        result = usecase.check_email_provider()

        assert result.healthy is True
        assert result.message == ""
        mock_provider.authenticate.assert_called_once()

    def test_check_email_provider_unhealthy_false(self):
        """check_email_provider() retourne healthy=False si authenticate() retourne False."""
        mock_provider = MagicMock(spec=EmailPort)
        mock_provider.authenticate.return_value = False

        def factory():
            return mock_provider
        usecase = HealthCheckUseCase(factory, MagicMock())

        result = usecase.check_email_provider()

        assert result.healthy is False
        assert result.message == "Authentication failed"

    def test_check_email_provider_exception_caught(self):
        """check_email_provider() retourne healthy=False si une exception est levée."""
        mock_provider = MagicMock(spec=EmailPort)
        mock_provider.authenticate.side_effect = Exception("Connection timeout")

        def factory():
            return mock_provider
        usecase = HealthCheckUseCase(factory, MagicMock())

        result = usecase.check_email_provider()

        assert result.healthy is False
        assert "Connection timeout" in result.message

    def test_check_email_provider_factory_exception(self):
        """check_email_provider() gère les exceptions du factory."""
        def failing_factory():
            raise RuntimeError("Factory failed to create provider")

        usecase = HealthCheckUseCase(failing_factory, MagicMock())

        result = usecase.check_email_provider()

        assert result.healthy is False
        assert "Factory failed to create provider" in result.message

    def test_check_email_provider_message_structure(self):
        """check_email_provider() retourne toujours un HealthStatus."""
        mock_provider = MagicMock(spec=EmailPort)
        mock_provider.authenticate.return_value = True

        def factory():
            return mock_provider
        usecase = HealthCheckUseCase(factory, MagicMock())

        result = usecase.check_email_provider()

        assert isinstance(result, HealthStatus)
        assert hasattr(result, "healthy")
        assert hasattr(result, "message")

    def test_check_email_provider_called_correctly(self):
        """check_email_provider() appelle la factory et authenticate()."""
        mock_provider = MagicMock(spec=EmailPort)
        mock_provider.authenticate.return_value = True

        factory = MagicMock(return_value=mock_provider)
        usecase = HealthCheckUseCase(factory, MagicMock())

        usecase.check_email_provider()

        factory.assert_called_once()
        mock_provider.authenticate.assert_called_once()

    def test_check_email_provider_value_error(self):
        """check_email_provider() gère ValueError."""
        mock_provider = MagicMock(spec=EmailPort)
        mock_provider.authenticate.side_effect = ValueError("Invalid credentials")

        def factory():
            return mock_provider
        usecase = HealthCheckUseCase(factory, MagicMock())

        result = usecase.check_email_provider()

        assert result.healthy is False
        assert "Invalid credentials" in result.message

    def test_check_email_provider_attribute_error(self):
        """check_email_provider() gère AttributeError."""
        def bad_factory():
            obj = MagicMock()
            obj.authenticate.side_effect = AttributeError("Missing method")
            return obj

        usecase = HealthCheckUseCase(bad_factory, MagicMock())

        result = usecase.check_email_provider()

        assert result.healthy is False
        assert "Missing method" in result.message


class TestHealthCheckUseCaseLLM:
    """Tests de check_llm() du HealthCheckUseCase."""

    def test_check_llm_healthy_with_response(self):
        """check_llm() retourne healthy=True si response.content n'est pas vide."""
        mock_llm = MagicMock(spec=LLMPort)
        mock_response = MagicMock()
        mock_response.content = "OK"
        mock_llm.complete.return_value = mock_response

        def factory():
            return mock_llm
        usecase = HealthCheckUseCase(MagicMock(), factory)

        result = usecase.check_llm()

        assert result.healthy is True
        assert result.message == ""
        mock_llm.complete.assert_called_once()

    def test_check_llm_unhealthy_empty_response(self):
        """check_llm() retourne healthy=False si response.content est vide."""
        mock_llm = MagicMock(spec=LLMPort)
        mock_response = MagicMock()
        mock_response.content = ""
        mock_llm.complete.return_value = mock_response

        def factory():
            return mock_llm
        usecase = HealthCheckUseCase(MagicMock(), factory)

        result = usecase.check_llm()

        assert result.healthy is False
        assert result.message == "Empty response"

    def test_check_llm_unhealthy_none_response(self):
        """check_llm() retourne healthy=False si response est None."""
        mock_llm = MagicMock(spec=LLMPort)
        mock_llm.complete.return_value = None

        def factory():
            return mock_llm
        usecase = HealthCheckUseCase(MagicMock(), factory)

        result = usecase.check_llm()

        assert result.healthy is False
        assert result.message == "Empty response"

    def test_check_llm_exception_caught(self):
        """check_llm() retourne healthy=False si une exception est levée."""
        mock_llm = MagicMock(spec=LLMPort)
        mock_llm.complete.side_effect = Exception("API rate limited")

        def factory():
            return mock_llm
        usecase = HealthCheckUseCase(MagicMock(), factory)

        result = usecase.check_llm()

        assert result.healthy is False
        assert "API rate limited" in result.message

    def test_check_llm_factory_exception(self):
        """check_llm() gère les exceptions du factory."""
        def failing_factory():
            raise RuntimeError("Factory error")

        usecase = HealthCheckUseCase(MagicMock(), failing_factory)

        result = usecase.check_llm()

        assert result.healthy is False
        assert "Factory error" in result.message

    def test_check_llm_message_structure(self):
        """check_llm() retourne toujours un HealthStatus."""
        mock_llm = MagicMock(spec=LLMPort)
        mock_response = MagicMock()
        mock_response.content = "OK"
        mock_llm.complete.return_value = mock_response

        def factory():
            return mock_llm
        usecase = HealthCheckUseCase(MagicMock(), factory)

        result = usecase.check_llm()

        assert isinstance(result, HealthStatus)
        assert hasattr(result, "healthy")
        assert hasattr(result, "message")

    def test_check_llm_called_with_correct_params(self):
        """check_llm() appelle complete() avec les bons paramètres."""
        mock_llm = MagicMock(spec=LLMPort)
        mock_response = MagicMock()
        mock_response.content = "OK"
        mock_llm.complete.return_value = mock_response

        def factory():
            return mock_llm
        usecase = HealthCheckUseCase(MagicMock(), factory)

        usecase.check_llm()

        # Vérifie que complete() a été appelé
        mock_llm.complete.assert_called_once()
        # Récupère les arguments
        call_args = mock_llm.complete.call_args
        assert call_args[1]["max_tokens"] == 10

    def test_check_llm_response_with_content(self):
        """check_llm() utilise response.content pour vérifier la santé."""
        mock_llm = MagicMock(spec=LLMPort)
        response = LLMResponse(content="Test response", input_tokens=5, output_tokens=3)
        mock_llm.complete.return_value = response

        def factory():
            return mock_llm
        usecase = HealthCheckUseCase(MagicMock(), factory)

        result = usecase.check_llm()

        assert result.healthy is True

    def test_check_llm_timeout_exception(self):
        """check_llm() gère les timeouts."""
        mock_llm = MagicMock(spec=LLMPort)
        mock_llm.complete.side_effect = TimeoutError("Request timeout")

        def factory():
            return mock_llm
        usecase = HealthCheckUseCase(MagicMock(), factory)

        result = usecase.check_llm()

        assert result.healthy is False
        assert "Request timeout" in result.message

    def test_check_llm_connection_error(self):
        """check_llm() gère les erreurs de connexion."""
        mock_llm = MagicMock(spec=LLMPort)
        mock_llm.complete.side_effect = ConnectionError("Failed to connect")

        def factory():
            return mock_llm
        usecase = HealthCheckUseCase(MagicMock(), factory)

        result = usecase.check_llm()

        assert result.healthy is False
        assert "Failed to connect" in result.message


class TestHealthCheckUseCaseExecute:
    """Tests de execute() du HealthCheckUseCase."""

    def test_execute_both_healthy(self):
        """execute() retourne SystemHealthStatus avec les deux composants sains."""
        mock_email = MagicMock(spec=EmailPort)
        mock_email.authenticate.return_value = True

        mock_llm = MagicMock(spec=LLMPort)
        mock_response = MagicMock()
        mock_response.content = "OK"
        mock_llm.complete.return_value = mock_response

        def email_factory():
            return mock_email
        def llm_factory():
            return mock_llm

        usecase = HealthCheckUseCase(email_factory, llm_factory)
        result = usecase.execute()

        assert isinstance(result, SystemHealthStatus)
        assert result.overall_healthy is True
        assert result.status == "healthy"
        assert result.email_provider.healthy is True
        assert result.llm.healthy is True

    def test_execute_email_unhealthy_only(self):
        """execute() retourne status=degraded si email est non sain."""
        mock_email = MagicMock(spec=EmailPort)
        mock_email.authenticate.return_value = False

        mock_llm = MagicMock(spec=LLMPort)
        mock_response = MagicMock()
        mock_response.content = "OK"
        mock_llm.complete.return_value = mock_response

        def email_factory():
            return mock_email
        def llm_factory():
            return mock_llm

        usecase = HealthCheckUseCase(email_factory, llm_factory)
        result = usecase.execute()

        assert result.overall_healthy is False
        assert result.status == "degraded"
        assert result.email_provider.healthy is False
        assert result.llm.healthy is True

    def test_execute_llm_unhealthy_only(self):
        """execute() retourne status=degraded si LLM est non sain."""
        mock_email = MagicMock(spec=EmailPort)
        mock_email.authenticate.return_value = True

        mock_llm = MagicMock(spec=LLMPort)
        mock_llm.complete.side_effect = Exception("LLM error")

        def email_factory():
            return mock_email
        def llm_factory():
            return mock_llm

        usecase = HealthCheckUseCase(email_factory, llm_factory)
        result = usecase.execute()

        assert result.overall_healthy is False
        assert result.status == "degraded"
        assert result.email_provider.healthy is True
        assert result.llm.healthy is False

    def test_execute_both_unhealthy(self):
        """execute() retourne status=degraded si les deux sont non sains."""
        mock_email = MagicMock(spec=EmailPort)
        mock_email.authenticate.side_effect = Exception("Email error")

        mock_llm = MagicMock(spec=LLMPort)
        mock_llm.complete.side_effect = Exception("LLM error")

        def email_factory():
            return mock_email
        def llm_factory():
            return mock_llm

        usecase = HealthCheckUseCase(email_factory, llm_factory)
        result = usecase.execute()

        assert result.overall_healthy is False
        assert result.status == "degraded"
        assert result.email_provider.healthy is False
        assert result.llm.healthy is False

    def test_execute_returns_system_health_status(self):
        """execute() retourne toujours un SystemHealthStatus."""
        mock_email = MagicMock(spec=EmailPort)
        mock_email.authenticate.return_value = True

        mock_llm = MagicMock(spec=LLMPort)
        mock_response = MagicMock()
        mock_response.content = "OK"
        mock_llm.complete.return_value = mock_response

        def email_factory():
            return mock_email
        def llm_factory():
            return mock_llm

        usecase = HealthCheckUseCase(email_factory, llm_factory)
        result = usecase.execute()

        assert isinstance(result, SystemHealthStatus)
        assert hasattr(result, "email_provider")
        assert hasattr(result, "llm")
        assert isinstance(result.email_provider, HealthStatus)
        assert isinstance(result.llm, HealthStatus)

    def test_execute_does_not_swallow_errors(self):
        """execute() gère les exceptions sans les re-lever."""
        mock_email = MagicMock(spec=EmailPort)
        mock_email.authenticate.side_effect = RuntimeError("Unexpected error")

        mock_llm = MagicMock(spec=LLMPort)
        mock_llm.complete.side_effect = RuntimeError("Unexpected LLM error")

        def email_factory():
            return mock_email
        def llm_factory():
            return mock_llm

        usecase = HealthCheckUseCase(email_factory, llm_factory)

        # Ne doit pas lever d'exception
        result = usecase.execute()

        assert result.email_provider.healthy is False
        assert result.llm.healthy is False

    def test_execute_calls_both_factories(self):
        """execute() appelle les deux factories."""
        email_factory = MagicMock()
        mock_email = MagicMock(spec=EmailPort)
        mock_email.authenticate.return_value = True
        email_factory.return_value = mock_email

        llm_factory = MagicMock()
        mock_llm = MagicMock(spec=LLMPort)
        mock_response = MagicMock()
        mock_response.content = "OK"
        mock_llm.complete.return_value = mock_response
        llm_factory.return_value = mock_llm

        usecase = HealthCheckUseCase(email_factory, llm_factory)
        usecase.execute()

        email_factory.assert_called_once()
        llm_factory.assert_called_once()


class TestHealthCheckUseCaseInitialization:
    """Tests d'initialisation du HealthCheckUseCase."""

    def test_usecase_initialization(self):
        """HealthCheckUseCase peut être initialisé avec deux factories."""
        email_factory = MagicMock()
        llm_factory = MagicMock()

        usecase = HealthCheckUseCase(email_factory, llm_factory)

        assert usecase is not None
        assert hasattr(usecase, "check_email_provider")
        assert hasattr(usecase, "check_llm")
        assert hasattr(usecase, "execute")

    def test_usecase_stores_factories(self):
        """HealthCheckUseCase stocke les factories pour utilisation ultérieure."""
        email_factory = MagicMock()
        llm_factory = MagicMock()

        usecase = HealthCheckUseCase(email_factory, llm_factory)

        # Les factories sont utilisées lors des appels
        mock_email = MagicMock(spec=EmailPort)
        mock_email.authenticate.return_value = True
        email_factory.return_value = mock_email

        usecase.check_email_provider()

        email_factory.assert_called()

    def test_usecase_methods_are_callable(self):
        """Les méthodes du use case sont appelables."""
        def email_factory():
            return MagicMock(spec=EmailPort)
        def llm_factory():
            return MagicMock(spec=LLMPort)

        usecase = HealthCheckUseCase(email_factory, llm_factory)

        assert callable(usecase.check_email_provider)
        assert callable(usecase.check_llm)
        assert callable(usecase.execute)


class TestHealthCheckIntegration:
    """Tests d'intégration du health check."""

    def test_realistic_all_healthy_scenario(self):
        """Scénario réaliste: tous les services sont sains."""
        mock_email = MagicMock(spec=EmailPort)
        mock_email.authenticate.return_value = True

        mock_llm = MagicMock(spec=LLMPort)
        mock_llm.complete.return_value = LLMResponse(
            content="OK",
            input_tokens=10,
            output_tokens=2
        )

        usecase = HealthCheckUseCase(
            lambda: mock_email,
            lambda: mock_llm
        )

        result = usecase.execute()

        assert result.overall_healthy is True
        assert result.status == "healthy"
        assert result.email_provider.message == ""
        assert result.llm.message == ""

    def test_realistic_partial_failure_scenario(self):
        """Scénario réaliste: un service échoue, l'autre fonctionne."""
        mock_email = MagicMock(spec=EmailPort)
        mock_email.authenticate.side_effect = ConnectionError("SMTP connection failed")

        mock_llm = MagicMock(spec=LLMPort)
        mock_llm.complete.return_value = LLMResponse(content="OK")

        usecase = HealthCheckUseCase(
            lambda: mock_email,
            lambda: mock_llm
        )

        result = usecase.execute()

        assert result.overall_healthy is False
        assert result.status == "degraded"
        assert result.email_provider.healthy is False
        assert result.llm.healthy is True
        assert "SMTP connection failed" in result.email_provider.message

    def test_realistic_complete_failure_scenario(self):
        """Scénario réaliste: tous les services échouent."""
        mock_email = MagicMock(spec=EmailPort)
        mock_email.authenticate.side_effect = Exception("Gmail API unavailable")

        mock_llm = MagicMock(spec=LLMPort)
        mock_llm.complete.side_effect = Exception("Claude API down")

        usecase = HealthCheckUseCase(
            lambda: mock_email,
            lambda: mock_llm
        )

        result = usecase.execute()

        assert result.overall_healthy is False
        assert result.status == "degraded"
        assert result.email_provider.healthy is False
        assert result.llm.healthy is False

    def test_health_check_independent_checks(self):
        """Les vérifications email et LLM sont indépendantes."""
        mock_email = MagicMock(spec=EmailPort)
        mock_email.authenticate.return_value = True

        mock_llm = MagicMock(spec=LLMPort)
        mock_llm.complete.return_value = LLMResponse(content="OK")

        usecase = HealthCheckUseCase(
            lambda: mock_email,
            lambda: mock_llm
        )

        # Appels indépendants
        email_result = usecase.check_email_provider()
        llm_result = usecase.check_llm()

        assert email_result.healthy is True
        assert llm_result.healthy is True

        # Résultat global
        system_result = usecase.execute()
        assert system_result.overall_healthy is True

    def test_error_messages_preserved(self):
        """Les messages d'erreur sont préservés correctement."""
        mock_email = MagicMock(spec=EmailPort)
        error_msg = "Invalid OAuth token: token_expired"
        mock_email.authenticate.side_effect = Exception(error_msg)

        usecase = HealthCheckUseCase(lambda: mock_email, MagicMock())

        result = usecase.check_email_provider()

        assert error_msg in result.message
