# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests TDD pour la gestion des erreurs des adaptateurs LLM.

Phase RED: Ces tests définissent le comportement attendu pour la gestion des erreurs.
Les adaptateurs doivent traduire les exceptions techniques en exceptions Domain.

Clean Architecture:
- Les adaptateurs (Infrastructure) traduisent les erreurs techniques
  en exceptions Domain compréhensibles par les Use Cases
- Les Use Cases ne connaissent que les exceptions Domain

Erreurs testées:
- Authentification (API key invalide)
- Rate limiting (429)
- Service indisponible (5xx)
- Timeout
- Connexion impossible
- Réponse malformée
- Contexte dépassé
- Modèle non trouvé
"""

import pytest
from unittest.mock import Mock, patch
import json

from app.domain.exceptions import (
    LLMError,
    LLMAuthenticationError,
    LLMRateLimitError,
    LLMUnavailableError,
    LLMConnectionError,
    LLMTimeoutError,
    LLMContextLengthError,
    LLMResponseError,
    LLMModelNotFoundError,
)


# =============================================================================
# Tests des exceptions LLM Domain
# =============================================================================


class TestLLMExceptions:
    """Tests unitaires pour les exceptions LLM Domain."""

    def test_llm_error_base_class(self):
        """LLMError doit avoir message, provider et code."""
        error = LLMError("Test error", provider="test-provider")
        assert error.message == "Test error"
        assert error.provider == "test-provider"
        assert error.code == "LLM_ERROR"
        assert str(error) == "Test error"

    def test_llm_authentication_error(self):
        """LLMAuthenticationError doit inclure le provider."""
        error = LLMAuthenticationError(provider="claude")
        assert "claude" in error.message.lower() or "claude" in str(error).lower()
        assert error.provider == "claude"
        assert error.code == "LLM_AUTH_ERROR"

    def test_llm_rate_limit_error_with_retry_after(self):
        """LLMRateLimitError peut inclure retry_after."""
        error = LLMRateLimitError(provider="ollama", retry_after=30)
        assert error.retry_after == 30
        assert "30" in error.message
        assert error.code == "LLM_RATE_LIMIT"

    def test_llm_rate_limit_error_without_retry_after(self):
        """LLMRateLimitError fonctionne sans retry_after."""
        error = LLMRateLimitError(provider="claude")
        assert error.retry_after is None
        assert error.code == "LLM_RATE_LIMIT"

    def test_llm_unavailable_error(self):
        """LLMUnavailableError pour les erreurs 5xx."""
        error = LLMUnavailableError(provider="claude")
        assert error.provider == "claude"
        assert error.code == "LLM_UNAVAILABLE"

    def test_llm_connection_error_with_url(self):
        """LLMConnectionError peut inclure l'URL."""
        error = LLMConnectionError(provider="ollama", url="http://localhost:11434")
        assert error.url == "http://localhost:11434"
        assert "localhost" in error.message
        assert error.code == "LLM_CONNECTION_ERROR"

    def test_llm_timeout_error_with_seconds(self):
        """LLMTimeoutError peut inclure la durée."""
        error = LLMTimeoutError(provider="claude", timeout_seconds=120)
        assert error.timeout_seconds == 120
        assert "120" in error.message
        assert error.code == "LLM_TIMEOUT"

    def test_llm_context_length_error_with_tokens(self):
        """LLMContextLengthError peut inclure les compteurs de tokens."""
        error = LLMContextLengthError(
            provider="claude",
            max_tokens=100000,
            actual_tokens=150000
        )
        assert error.max_tokens == 100000
        assert error.actual_tokens == 150000
        assert "100000" in error.message
        assert "150000" in error.message
        assert error.code == "LLM_CONTEXT_LENGTH"

    def test_llm_response_error(self):
        """LLMResponseError pour les réponses malformées."""
        error = LLMResponseError(provider="ollama", message="Missing content field")
        assert "Missing content field" in error.message
        assert error.code == "LLM_RESPONSE_ERROR"

    def test_llm_model_not_found_error(self):
        """LLMModelNotFoundError doit inclure le nom du modèle."""
        error = LLMModelNotFoundError(provider="ollama", model="nonexistent:latest")
        assert error.model == "nonexistent:latest"
        assert "nonexistent" in error.message
        assert error.code == "LLM_MODEL_NOT_FOUND"

    def test_llm_exceptions_inherit_from_domain_error(self):
        """Toutes les exceptions LLM doivent hériter de DomainError."""
        from app.domain.exceptions import DomainError

        exceptions = [
            LLMError("test", "provider"),
            LLMAuthenticationError("provider"),
            LLMRateLimitError("provider"),
            LLMUnavailableError("provider"),
            LLMConnectionError("provider"),
            LLMTimeoutError("provider"),
            LLMContextLengthError("provider"),
            LLMResponseError("provider"),
            LLMModelNotFoundError("provider", "model"),
        ]

        for exc in exceptions:
            assert isinstance(exc, DomainError), f"{type(exc).__name__} must inherit DomainError"
            assert isinstance(exc, LLMError), f"{type(exc).__name__} must inherit LLMError"


# =============================================================================
# Tests ClaudeAdapter - Gestion des erreurs
# =============================================================================


class TestClaudeAdapterErrorHandling:
    """Tests TDD pour la gestion des erreurs de ClaudeAdapter.

    Ces tests utilisent le pattern de mock sur _client après création de l'adapter.
    L'adapter doit traduire les exceptions Anthropic en exceptions Domain LLM.
    """

    @pytest.fixture
    def claude_adapter_with_mock(self):
        """Crée un ClaudeAdapter avec un client mocké."""
        anthropic = pytest.importorskip("anthropic")

        with patch.object(anthropic, "Anthropic") as mock_anthropic_cls:
            mock_client = Mock()
            mock_anthropic_cls.return_value = mock_client

            from app.adapters.llm.claude_adapter import ClaudeAdapter
            adapter = ClaudeAdapter(api_key="test-key")

            yield adapter, mock_client

    def test_authentication_error_invalid_api_key(self, claude_adapter_with_mock):
        """Une API key invalide doit lever LLMAuthenticationError."""
        import anthropic
        adapter, mock_client = claude_adapter_with_mock

        # Simulate Anthropic AuthenticationError
        mock_client.messages.create.side_effect = anthropic.AuthenticationError(
            message="Invalid API key",
            response=Mock(status_code=401),
            body={"error": {"message": "Invalid API key"}}
        )

        with pytest.raises(LLMAuthenticationError) as exc_info:
            adapter.complete(system="test", user="test")

        assert exc_info.value.provider == "claude"
        assert exc_info.value.code == "LLM_AUTH_ERROR"

    def test_rate_limit_error_429(self, claude_adapter_with_mock):
        """Une erreur 429 doit lever LLMRateLimitError."""
        import anthropic
        adapter, mock_client = claude_adapter_with_mock

        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.headers = {"retry-after": "30"}

        mock_client.messages.create.side_effect = anthropic.RateLimitError(
            message="Rate limit exceeded",
            response=mock_response,
            body={"error": {"message": "Rate limit exceeded"}}
        )

        with pytest.raises(LLMRateLimitError) as exc_info:
            adapter.complete(system="test", user="test")

        assert exc_info.value.provider == "claude"

    def test_service_unavailable_500(self, claude_adapter_with_mock):
        """Une erreur 500 doit lever LLMUnavailableError."""
        import anthropic
        adapter, mock_client = claude_adapter_with_mock

        mock_client.messages.create.side_effect = anthropic.InternalServerError(
            message="Internal server error",
            response=Mock(status_code=500),
            body={}
        )

        with pytest.raises(LLMUnavailableError) as exc_info:
            adapter.complete(system="test", user="test")

        assert exc_info.value.provider == "claude"

    def test_service_unavailable_503(self, claude_adapter_with_mock):
        """Une erreur 503 doit lever LLMUnavailableError."""
        import anthropic
        adapter, mock_client = claude_adapter_with_mock

        mock_client.messages.create.side_effect = anthropic.APIStatusError(
            message="Service unavailable",
            response=Mock(status_code=503),
            body={}
        )

        with pytest.raises(LLMUnavailableError) as exc_info:
            adapter.complete(system="test", user="test")

        assert exc_info.value.provider == "claude"

    def test_connection_error(self, claude_adapter_with_mock):
        """Une erreur de connexion doit lever LLMConnectionError."""
        import anthropic
        adapter, mock_client = claude_adapter_with_mock

        mock_client.messages.create.side_effect = anthropic.APIConnectionError(
            message="Connection refused",
            request=Mock()
        )

        with pytest.raises(LLMConnectionError) as exc_info:
            adapter.complete(system="test", user="test")

        assert exc_info.value.provider == "claude"

    def test_timeout_error(self, claude_adapter_with_mock):
        """Un timeout doit lever LLMTimeoutError."""
        import anthropic
        adapter, mock_client = claude_adapter_with_mock

        mock_client.messages.create.side_effect = anthropic.APITimeoutError(
            request=Mock()
        )

        with pytest.raises(LLMTimeoutError) as exc_info:
            adapter.complete(system="test", user="test")

        assert exc_info.value.provider == "claude"

    def test_context_length_exceeded(self, claude_adapter_with_mock):
        """Un prompt trop long doit lever LLMContextLengthError."""
        import anthropic
        adapter, mock_client = claude_adapter_with_mock

        mock_client.messages.create.side_effect = anthropic.BadRequestError(
            message="prompt is too long: 150000 tokens > 100000 maximum",
            response=Mock(status_code=400),
            body={"error": {"message": "prompt is too long"}}
        )

        with pytest.raises(LLMContextLengthError) as exc_info:
            adapter.complete(system="test", user="test")

        assert exc_info.value.provider == "claude"

    def test_model_not_found(self, claude_adapter_with_mock):
        """Un modèle inexistant doit lever LLMModelNotFoundError."""
        import anthropic
        adapter, mock_client = claude_adapter_with_mock

        mock_client.messages.create.side_effect = anthropic.NotFoundError(
            message="model not found: nonexistent-model",
            response=Mock(status_code=404),
            body={"error": {"message": "model not found"}}
        )

        # Changer le modèle après création pour ce test
        adapter._model = "nonexistent-model"

        with pytest.raises(LLMModelNotFoundError) as exc_info:
            adapter.complete(system="test", user="test")

        assert exc_info.value.provider == "claude"
        assert exc_info.value.model == "nonexistent-model"

    def test_malformed_response_no_content(self, claude_adapter_with_mock):
        """Une réponse sans content doit lever LLMResponseError."""
        adapter, mock_client = claude_adapter_with_mock

        # Response with empty content array
        mock_response = Mock()
        mock_response.content = []
        mock_response.usage = Mock(input_tokens=10, output_tokens=0)
        mock_client.messages.create.return_value = mock_response

        with pytest.raises(LLMResponseError) as exc_info:
            adapter.complete(system="test", user="test")

        assert exc_info.value.provider == "claude"

    def test_malformed_response_missing_text(self, claude_adapter_with_mock):
        """Une réponse sans text doit lever LLMResponseError."""
        adapter, mock_client = claude_adapter_with_mock

        # Response content without text attribute
        mock_content = Mock(spec=[])  # No text attribute
        mock_response = Mock()
        mock_response.content = [mock_content]
        mock_response.usage = Mock(input_tokens=10, output_tokens=5)
        mock_client.messages.create.return_value = mock_response

        with pytest.raises(LLMResponseError) as exc_info:
            adapter.complete(system="test", user="test")

        assert exc_info.value.provider == "claude"


# =============================================================================
# Tests OllamaAdapter - Gestion des erreurs
# =============================================================================


class TestOllamaAdapterErrorHandling:
    """Tests TDD pour la gestion des erreurs de OllamaAdapter."""

    @pytest.fixture
    def mock_requests_post(self):
        """Mock requests.post seulement (pas tout le module)."""
        with patch("app.adapters.llm.ollama_adapter.requests.post") as mock:
            yield mock

    @pytest.fixture
    def mock_requests_get(self):
        """Mock requests.get seulement."""
        with patch("app.adapters.llm.ollama_adapter.requests.get") as mock:
            yield mock

    def test_connection_error(self, mock_requests_post):
        """Une erreur de connexion doit lever LLMConnectionError."""
        import requests
        from app.adapters.llm.ollama_adapter import OllamaAdapter

        mock_requests_post.side_effect = requests.exceptions.ConnectionError("Connection refused")

        adapter = OllamaAdapter(base_url="http://localhost:11434")

        with pytest.raises(LLMConnectionError) as exc_info:
            adapter.complete(system="test", user="test")

        assert exc_info.value.provider == "ollama"
        assert "localhost:11434" in exc_info.value.url

    def test_timeout_error(self, mock_requests_post):
        """Un timeout doit lever LLMTimeoutError."""
        import requests
        from app.adapters.llm.ollama_adapter import OllamaAdapter

        mock_requests_post.side_effect = requests.exceptions.Timeout("Request timed out")

        adapter = OllamaAdapter()

        with pytest.raises(LLMTimeoutError) as exc_info:
            adapter.complete(system="test", user="test")

        assert exc_info.value.provider == "ollama"

    def test_http_error_500(self, mock_requests_post):
        """Une erreur HTTP 500 doit lever LLMUnavailableError."""
        import requests
        from app.adapters.llm.ollama_adapter import OllamaAdapter

        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=mock_response
        )
        mock_requests_post.return_value = mock_response

        adapter = OllamaAdapter()

        with pytest.raises(LLMUnavailableError) as exc_info:
            adapter.complete(system="test", user="test")

        assert exc_info.value.provider == "ollama"

    def test_http_error_503(self, mock_requests_post):
        """Une erreur HTTP 503 doit lever LLMUnavailableError."""
        import requests
        from app.adapters.llm.ollama_adapter import OllamaAdapter

        mock_response = Mock()
        mock_response.status_code = 503
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=mock_response
        )
        mock_requests_post.return_value = mock_response

        adapter = OllamaAdapter()

        with pytest.raises(LLMUnavailableError) as exc_info:
            adapter.complete(system="test", user="test")

        assert exc_info.value.provider == "ollama"

    def test_http_error_429_rate_limit(self, mock_requests_post):
        """Une erreur HTTP 429 doit lever LLMRateLimitError."""
        import requests
        from app.adapters.llm.ollama_adapter import OllamaAdapter

        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "60"}
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=mock_response
        )
        mock_requests_post.return_value = mock_response

        adapter = OllamaAdapter()

        with pytest.raises(LLMRateLimitError) as exc_info:
            adapter.complete(system="test", user="test")

        assert exc_info.value.provider == "ollama"

    def test_http_error_404_model_not_found(self, mock_requests_post):
        """Une erreur HTTP 404 doit lever LLMModelNotFoundError."""
        import requests
        from app.adapters.llm.ollama_adapter import OllamaAdapter

        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.text = "model 'nonexistent:latest' not found"
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=mock_response
        )
        mock_requests_post.return_value = mock_response

        adapter = OllamaAdapter(model="nonexistent:latest")

        with pytest.raises(LLMModelNotFoundError) as exc_info:
            adapter.complete(system="test", user="test")

        assert exc_info.value.provider == "ollama"
        assert exc_info.value.model == "nonexistent:latest"

    def test_json_decode_error(self, mock_requests_post):
        """Une réponse JSON invalide doit lever LLMResponseError."""
        from app.adapters.llm.ollama_adapter import OllamaAdapter

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()
        mock_response.json.side_effect = json.JSONDecodeError("Invalid JSON", "", 0)
        mock_requests_post.return_value = mock_response

        adapter = OllamaAdapter()

        with pytest.raises(LLMResponseError) as exc_info:
            adapter.complete(system="test", user="test")

        assert exc_info.value.provider == "ollama"

    def test_malformed_response_missing_message(self, mock_requests_post):
        """Une réponse sans 'message' doit lever LLMResponseError."""
        from app.adapters.llm.ollama_adapter import OllamaAdapter

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {"wrong_key": "data"}  # No "message" key
        mock_requests_post.return_value = mock_response

        adapter = OllamaAdapter()

        with pytest.raises(LLMResponseError) as exc_info:
            adapter.complete(system="test", user="test")

        assert exc_info.value.provider == "ollama"

    def test_malformed_response_missing_content(self, mock_requests_post):
        """Une réponse sans 'content' dans message doit lever LLMResponseError."""
        from app.adapters.llm.ollama_adapter import OllamaAdapter

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {"message": {"role": "assistant"}}  # No "content"
        mock_requests_post.return_value = mock_response

        adapter = OllamaAdapter()

        with pytest.raises(LLMResponseError) as exc_info:
            adapter.complete(system="test", user="test")

        assert exc_info.value.provider == "ollama"

    def test_is_available_returns_false_on_error(self, mock_requests_get):
        """is_available doit retourner False sur erreur (pas d'exception)."""
        import requests
        from app.adapters.llm.ollama_adapter import OllamaAdapter

        mock_requests_get.side_effect = requests.exceptions.ConnectionError()

        adapter = OllamaAdapter()
        result = adapter.is_available()

        assert result is False

    def test_list_models_returns_empty_on_error(self, mock_requests_get):
        """list_models doit retourner [] sur erreur (pas d'exception)."""
        import requests
        from app.adapters.llm.ollama_adapter import OllamaAdapter

        mock_requests_get.side_effect = requests.exceptions.ConnectionError()

        adapter = OllamaAdapter()
        result = adapter.list_models()

        assert result == []


# =============================================================================
# Tests des Adapters de Classification avec erreurs LLM
# =============================================================================


class TestLLMClassifierAdapterErrorPropagation:
    """Tests pour la propagation des erreurs LLM dans les classifiers."""

    @pytest.fixture
    def mock_llm_port(self):
        """Mock du LLMPort."""
        mock = Mock()
        mock.name = "mock-llm"
        mock.model = "mock-model"
        return mock

    @pytest.fixture
    def test_email(self):
        """Email de test valide."""
        from app.domain.entities import Email
        return Email(
            id="test-123",
            sender="sender@test.com",
            subject="Test Subject",
            body="Test body content"
        )

    def test_classifier_propagates_llm_authentication_error(self, mock_llm_port, test_email):
        """Le classifier doit propager LLMAuthenticationError."""
        from app.adapters.classification.llm_classifier_adapter import LLMClassifierAdapter

        mock_llm_port.complete.side_effect = LLMAuthenticationError(provider="mock-llm")

        adapter = LLMClassifierAdapter(llm=mock_llm_port)

        # Le classifier ne doit PAS masquer l'erreur en retournant default
        with pytest.raises(LLMAuthenticationError):
            adapter.classify(test_email)

    def test_classifier_propagates_llm_rate_limit_error(self, mock_llm_port, test_email):
        """Le classifier doit propager LLMRateLimitError."""
        from app.adapters.classification.llm_classifier_adapter import LLMClassifierAdapter

        mock_llm_port.complete.side_effect = LLMRateLimitError(provider="mock-llm")

        adapter = LLMClassifierAdapter(llm=mock_llm_port)

        with pytest.raises(LLMRateLimitError):
            adapter.classify(test_email)

    def test_classifier_propagates_llm_unavailable_error(self, mock_llm_port, test_email):
        """Le classifier doit propager LLMUnavailableError."""
        from app.adapters.classification.llm_classifier_adapter import LLMClassifierAdapter

        mock_llm_port.complete.side_effect = LLMUnavailableError(provider="mock-llm")

        adapter = LLMClassifierAdapter(llm=mock_llm_port)

        with pytest.raises(LLMUnavailableError):
            adapter.classify(test_email)

    def test_prioritizer_propagates_llm_errors(self, mock_llm_port, test_email):
        """Le prioritizer doit propager les erreurs LLM."""
        from app.adapters.classification.llm_prioritization_adapter import LLMPrioritizationAdapter

        mock_llm_port.complete.side_effect = LLMConnectionError(provider="mock-llm")

        adapter = LLMPrioritizationAdapter(llm=mock_llm_port)

        with pytest.raises(LLMConnectionError):
            adapter.analyze(test_email)

    def test_email_analyzer_propagates_llm_errors(self, mock_llm_port, test_email):
        """L'email analyzer doit propager les erreurs LLM."""
        from app.adapters.classification.llm_email_analyzer_adapter import LLMEmailAnalyzerAdapter
        from app.adapters.classification.llm_classifier_adapter import LLMClassifierAdapter
        from app.adapters.classification.llm_prioritization_adapter import LLMPrioritizationAdapter

        # LLMEmailAnalyzerAdapter utilise classifier et prioritizer
        mock_llm_port.complete.side_effect = LLMTimeoutError(provider="mock-llm")

        classifier = LLMClassifierAdapter(llm=mock_llm_port)
        prioritizer = LLMPrioritizationAdapter(llm=mock_llm_port)
        adapter = LLMEmailAnalyzerAdapter(classifier=classifier, prioritizer=prioritizer)

        with pytest.raises(LLMTimeoutError):
            adapter.analyze(test_email)


# =============================================================================
# Tests d'intégration: Traduction complète des erreurs
# =============================================================================


class TestErrorTranslationIntegration:
    """Tests d'intégration pour vérifier la chaîne complète de traduction d'erreurs."""

    def test_anthropic_sdk_errors_translated_to_domain_exceptions(self):
        """Les erreurs du SDK Anthropic doivent être traduites en exceptions Domain."""
        # Ce test vérifie que l'ensemble de la traduction fonctionne
        from app.domain.exceptions import DomainError

        # Toutes ces exceptions doivent hériter de DomainError
        assert issubclass(LLMAuthenticationError, DomainError)
        assert issubclass(LLMRateLimitError, DomainError)
        assert issubclass(LLMUnavailableError, DomainError)
        assert issubclass(LLMConnectionError, DomainError)
        assert issubclass(LLMTimeoutError, DomainError)
        assert issubclass(LLMContextLengthError, DomainError)
        assert issubclass(LLMResponseError, DomainError)
        assert issubclass(LLMModelNotFoundError, DomainError)

    def test_exceptions_have_unique_codes(self):
        """Chaque type d'exception LLM doit avoir un code unique."""
        codes = set()
        exceptions = [
            LLMAuthenticationError("p"),
            LLMRateLimitError("p"),
            LLMUnavailableError("p"),
            LLMConnectionError("p"),
            LLMTimeoutError("p"),
            LLMContextLengthError("p"),
            LLMResponseError("p"),
            LLMModelNotFoundError("p", "m"),
        ]

        for exc in exceptions:
            assert exc.code not in codes, f"Duplicate code: {exc.code}"
            codes.add(exc.code)


# =============================================================================
# Tests de comportement: Pas de bare except
# =============================================================================


class TestNoBareExcepts:
    """Tests pour vérifier qu'il n'y a pas de bare except dans les adaptateurs."""

    def test_ollama_is_available_catches_specific_exceptions(self):
        """is_available doit catch des exceptions spécifiques, pas bare except."""
        import inspect
        from app.adapters.llm.ollama_adapter import OllamaAdapter

        source = inspect.getsource(OllamaAdapter.is_available)

        # Le code ne doit pas contenir de bare except
        # On vérifie que "except:" seul n'apparaît pas
        lines = source.split('\n')
        for line in lines:
            stripped = line.strip()
            if stripped == "except:" or stripped.startswith("except:"):
                pytest.fail(f"Bare except found in is_available: {line}")

    def test_ollama_list_models_catches_specific_exceptions(self):
        """list_models doit catch des exceptions spécifiques, pas bare except."""
        import inspect
        from app.adapters.llm.ollama_adapter import OllamaAdapter

        source = inspect.getsource(OllamaAdapter.list_models)

        lines = source.split('\n')
        for line in lines:
            stripped = line.strip()
            if stripped == "except:" or stripped.startswith("except:"):
                pytest.fail(f"Bare except found in list_models: {line}")


# =============================================================================
# Tests de validation des entrées
# =============================================================================


class TestInputValidation:
    """Tests pour la validation des entrées des adaptateurs."""

    @pytest.fixture
    def claude_adapter_with_mock(self):
        """Crée un ClaudeAdapter avec un client mocké."""
        anthropic = pytest.importorskip("anthropic")

        with patch.object(anthropic, "Anthropic") as mock_anthropic_cls:
            mock_client = Mock()
            mock_anthropic_cls.return_value = mock_client

            from app.adapters.llm.claude_adapter import ClaudeAdapter
            adapter = ClaudeAdapter(api_key="test-key")

            yield adapter, mock_client

    def test_claude_adapter_empty_system_prompt(self, claude_adapter_with_mock):
        """ClaudeAdapter doit accepter un system prompt vide."""
        from app.domain.ports import LLMResponse
        adapter, mock_client = claude_adapter_with_mock

        mock_response = Mock()
        mock_response.content = [Mock(text="response")]
        mock_response.usage = Mock(input_tokens=5, output_tokens=10)
        mock_client.messages.create.return_value = mock_response

        # Ne doit pas lever d'exception
        result = adapter.complete(system="", user="test")
        assert isinstance(result, LLMResponse)

    def test_claude_adapter_empty_user_prompt(self, claude_adapter_with_mock):
        """ClaudeAdapter doit accepter un user prompt vide."""
        from app.domain.ports import LLMResponse
        adapter, mock_client = claude_adapter_with_mock

        mock_response = Mock()
        mock_response.content = [Mock(text="response")]
        mock_response.usage = Mock(input_tokens=5, output_tokens=10)
        mock_client.messages.create.return_value = mock_response

        result = adapter.complete(system="test", user="")
        assert isinstance(result, LLMResponse)

    def test_claude_adapter_max_tokens_validation(self, claude_adapter_with_mock):
        """ClaudeAdapter doit valider max_tokens."""
        from app.domain.exceptions import InvalidBoundsError
        adapter, mock_client = claude_adapter_with_mock

        # max_tokens <= 0 devrait lever une erreur
        with pytest.raises((InvalidBoundsError, ValueError)):
            adapter.complete(system="test", user="test", max_tokens=0)

        with pytest.raises((InvalidBoundsError, ValueError)):
            adapter.complete(system="test", user="test", max_tokens=-1)
