# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour le module LLM.

Ces tests utilisent des mocks pour éviter les appels réels aux APIs.
pytest tests/test_llm.py -v
"""

import os
import sys
import pytest
from unittest.mock import MagicMock, patch

from app.llm.base import LLMResponse, LLMProvider
from app.llm.factory import is_api_key_required


class TestLLMResponse:
    """Tests pour la dataclass LLMResponse."""

    def test_create_with_required_fields(self):
        """LLMResponse créé avec seulement le content."""
        response = LLMResponse(content="Hello world")

        assert response.content == "Hello world"
        assert response.input_tokens == 0
        assert response.output_tokens == 0
        assert response.model == ""

    def test_create_with_all_fields(self):
        """LLMResponse créé avec tous les champs."""
        response = LLMResponse(
            content="Réponse générée",
            input_tokens=100,
            output_tokens=50,
            model="claude-sonnet-4-20250514"
        )

        assert response.content == "Réponse générée"
        assert response.input_tokens == 100
        assert response.output_tokens == 50
        assert response.model == "claude-sonnet-4-20250514"

    def test_empty_content(self):
        """LLMResponse avec content vide est valide."""
        response = LLMResponse(content="")

        assert response.content == ""


class TestLLMProviderInterface:
    """Tests pour l'interface abstraite LLMProvider."""

    def test_cannot_instantiate_abstract_class(self):
        """LLMProvider ne peut pas être instancié directement."""
        with pytest.raises(TypeError):
            LLMProvider()

    def test_concrete_implementation_required_methods(self):
        """Une implémentation concrète doit définir les méthodes abstraites."""
        class IncompleteProvider(LLMProvider):
            pass

        with pytest.raises(TypeError):
            IncompleteProvider()

    def test_complete_implementation(self):
        """Une implémentation complète fonctionne."""
        class MockProvider(LLMProvider):
            @property
            def name(self) -> str:
                return "mock"

            @property
            def model(self) -> str:
                return "mock-model"

            def complete(self, system: str, user: str, max_tokens: int = 1024) -> LLMResponse:
                return LLMResponse(content=f"Mock: {user}")

        provider = MockProvider()
        assert provider.name == "mock"
        assert provider.model == "mock-model"
        assert provider.is_available() is True

        response = provider.complete(system="Be helpful", user="Hello")
        assert response.content == "Mock: Hello"


@pytest.fixture
def mock_anthropic():
    """Fixture pour mocker le module anthropic avant import."""
    mock_module = MagicMock()
    mock_client = MagicMock()
    mock_module.Anthropic.return_value = mock_client

    with patch.dict(sys.modules, {"anthropic": mock_module}):
        yield mock_module, mock_client


class TestClaudeProvider:
    """Tests pour ClaudeProvider."""

    def test_requires_api_key(self, mock_anthropic):
        """ClaudeProvider lève une erreur sans clé API."""
        with patch.dict(os.environ, {}, clear=True):
            # Recharger le module avec le mock
            if "app.llm.claude_provider" in sys.modules:
                del sys.modules["app.llm.claude_provider"]
            from app.llm.claude_provider import ClaudeProvider

            with pytest.raises(ValueError, match="ANTHROPIC_API_KEY requise"):
                ClaudeProvider()

    def test_init_with_api_key_param(self, mock_anthropic):
        """ClaudeProvider accepte une clé API en paramètre."""
        mock_module, mock_client = mock_anthropic

        if "app.llm.claude_provider" in sys.modules:
            del sys.modules["app.llm.claude_provider"]
        from app.llm.claude_provider import ClaudeProvider

        provider = ClaudeProvider(api_key="test-key")

        assert provider.name == "claude"
        assert provider.is_available() is True
        # ClaudeProvider passe maintenant aussi `timeout=60.0` au SDK Anthropic
        # (audit P3 : protège contre les requêtes infinies en cas de panne réseau).
        # On vérifie juste l'api_key sans contraindre les autres kwargs.
        call_kwargs = mock_module.Anthropic.call_args.kwargs
        assert call_kwargs["api_key"] == "test-key"

    def test_init_with_env_api_key(self, mock_anthropic):
        """ClaudeProvider utilise la clé API de l'environnement."""
        mock_module, _ = mock_anthropic

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "env-key"}):
            if "app.llm.claude_provider" in sys.modules:
                del sys.modules["app.llm.claude_provider"]
            from app.llm.claude_provider import ClaudeProvider

            ClaudeProvider()
            call_kwargs = mock_module.Anthropic.call_args.kwargs
            assert call_kwargs["api_key"] == "env-key"

    def test_default_model(self, mock_anthropic):
        """ClaudeProvider utilise le modèle par défaut."""
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}, clear=True):
            if "app.llm.claude_provider" in sys.modules:
                del sys.modules["app.llm.claude_provider"]
            from app.llm.claude_provider import ClaudeProvider

            provider = ClaudeProvider()
            assert provider.model == "claude-sonnet-4-6"

    def test_custom_model(self, mock_anthropic):
        """ClaudeProvider accepte un modèle personnalisé."""
        if "app.llm.claude_provider" in sys.modules:
            del sys.modules["app.llm.claude_provider"]
        from app.llm.claude_provider import ClaudeProvider

        provider = ClaudeProvider(api_key="test-key", model="claude-3-opus-20240229")
        assert provider.model == "claude-3-opus-20240229"

    def test_model_from_env(self, mock_anthropic):
        """ClaudeProvider utilise le modèle de l'environnement."""
        with patch.dict(os.environ, {"LLM_MODEL": "claude-3-haiku-20240307", "ANTHROPIC_API_KEY": "test-key"}):
            if "app.llm.claude_provider" in sys.modules:
                del sys.modules["app.llm.claude_provider"]
            from app.llm.claude_provider import ClaudeProvider

            provider = ClaudeProvider()
            assert provider.model == "claude-3-haiku-20240307"

    def test_complete_calls_api(self, mock_anthropic):
        """complete() appelle l'API Anthropic correctement."""
        mock_module, mock_client = mock_anthropic

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Réponse générée")]
        mock_response.usage.input_tokens = 50
        mock_response.usage.output_tokens = 100
        mock_client.messages.create.return_value = mock_response

        if "app.llm.claude_provider" in sys.modules:
            del sys.modules["app.llm.claude_provider"]
        from app.llm.claude_provider import ClaudeProvider

        provider = ClaudeProvider(api_key="test-key")
        response = provider.complete(
            system="Tu es un assistant.",
            user="Bonjour!",
            max_tokens=500
        )

        mock_client.messages.create.assert_called_once_with(
            model="claude-sonnet-4-6",
            max_tokens=500,
            system="Tu es un assistant.",
            messages=[{"role": "user", "content": "Bonjour!"}]
        )

        assert response.content == "Réponse générée"
        assert response.input_tokens == 50
        assert response.output_tokens == 100


class TestOllamaProvider:
    """Tests pour OllamaProvider."""

    def test_default_values(self):
        """OllamaProvider utilise les valeurs par défaut."""
        from app.llm.ollama_provider import OllamaProvider

        # Utiliser explicitement le modèle par défaut
        provider = OllamaProvider(model="mixtral:latest")

        assert provider.name == "ollama"
        assert provider.model == "mixtral:latest"
        assert provider._base_url == "http://localhost:11434"

    def test_custom_model(self):
        """OllamaProvider accepte un modèle personnalisé."""
        from app.llm.ollama_provider import OllamaProvider
        provider = OllamaProvider(model="llama2:7b")

        assert provider.model == "llama2:7b"

    def test_custom_base_url(self):
        """OllamaProvider accepte une URL personnalisée."""
        from app.llm.ollama_provider import OllamaProvider
        provider = OllamaProvider(base_url="http://192.168.1.100:11434")

        assert provider._base_url == "http://192.168.1.100:11434"

    def test_model_from_env(self):
        """OllamaProvider utilise le modèle de l'environnement."""
        with patch.dict(os.environ, {"LLM_MODEL": "codellama:13b"}, clear=True):
            from app.llm.ollama_provider import OllamaProvider
            provider = OllamaProvider()

            assert provider.model == "codellama:13b"

    def test_base_url_from_env(self):
        """OllamaProvider utilise l'URL de l'environnement."""
        with patch.dict(os.environ, {"OLLAMA_BASE_URL": "http://remote:11434"}, clear=True):
            from app.llm.ollama_provider import OllamaProvider
            provider = OllamaProvider()

            assert provider._base_url == "http://remote:11434"

    def test_complete_calls_api(self):
        """complete() appelle l'API Ollama correctement."""
        with patch("app.llm.ollama_provider.requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "message": {"content": "Réponse Ollama"},
                "prompt_eval_count": 30,
                "eval_count": 60
            }
            mock_post.return_value = mock_response

            from app.llm.ollama_provider import OllamaProvider
            # Utiliser explicitement le modèle pour éviter les interférences
            provider = OllamaProvider(model="mixtral:latest")

            response = provider.complete(
                system="Tu es un assistant.",
                user="Bonjour!",
                max_tokens=256
            )

            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert call_args[0][0] == "http://localhost:11434/api/chat"
            payload = call_args[1]["json"]
            assert payload["model"] == "mixtral:latest"
            assert payload["options"]["num_predict"] == 256

            assert response.content == "Réponse Ollama"
            assert response.input_tokens == 30
            assert response.output_tokens == 60

    def test_complete_connection_error(self):
        """complete() gère les erreurs de connexion."""
        import requests

        with patch("app.llm.ollama_provider.requests.post") as mock_post:
            mock_post.side_effect = requests.exceptions.ConnectionError()

            from app.llm.ollama_provider import OllamaProvider
            provider = OllamaProvider()

            with pytest.raises(ConnectionError, match="Impossible de se connecter"):
                provider.complete(system="test", user="test")

    def test_complete_timeout_error(self):
        """complete() gère les timeouts."""
        import requests

        with patch("app.llm.ollama_provider.requests.post") as mock_post:
            mock_post.side_effect = requests.exceptions.Timeout()

            from app.llm.ollama_provider import OllamaProvider
            provider = OllamaProvider()

            with pytest.raises(TimeoutError, match="Timeout"):
                provider.complete(system="test", user="test")

    def test_is_available_true(self):
        """is_available() retourne True si Ollama répond."""
        with patch("app.llm.ollama_provider.requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response

            from app.llm.ollama_provider import OllamaProvider
            provider = OllamaProvider()

            assert provider.is_available() is True
            mock_get.assert_called_once_with(
                "http://localhost:11434/api/tags",
                timeout=5
            )

    def test_is_available_false(self):
        """is_available() retourne False si Ollama ne répond pas."""
        import requests

        with patch("app.llm.ollama_provider.requests.get") as mock_get:
            mock_get.side_effect = requests.exceptions.ConnectionError()

            from app.llm.ollama_provider import OllamaProvider
            provider = OllamaProvider()

            assert provider.is_available() is False

    def test_list_models(self):
        """list_models() retourne la liste des modèles."""
        with patch("app.llm.ollama_provider.requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "models": [
                    {"name": "llama2:7b"},
                    {"name": "mixtral:latest"}
                ]
            }
            mock_get.return_value = mock_response

            from app.llm.ollama_provider import OllamaProvider
            provider = OllamaProvider()

            models = provider.list_models()
            assert models == ["llama2:7b", "mixtral:latest"]

    def test_list_models_error(self):
        """list_models() retourne une liste vide en cas d'erreur."""
        import requests

        with patch("app.llm.ollama_provider.requests.get") as mock_get:
            mock_get.side_effect = requests.exceptions.ConnectionError()

            from app.llm.ollama_provider import OllamaProvider
            provider = OllamaProvider()

            models = provider.list_models()
            assert models == []


class TestFactory:
    """Tests pour la factory LLM."""

    def test_get_claude_provider(self, mock_anthropic):
        """get_llm_provider retourne un ClaudeProvider."""
        if "app.llm.claude_provider" in sys.modules:
            del sys.modules["app.llm.claude_provider"]
        if "app.llm.factory" in sys.modules:
            del sys.modules["app.llm.factory"]

        from app.llm.factory import get_llm_provider

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            provider = get_llm_provider(provider_type="claude")
            assert provider.name == "claude"

    def test_get_ollama_provider(self):
        """get_llm_provider retourne un OllamaProvider."""
        from app.llm.factory import get_llm_provider
        provider = get_llm_provider(provider_type="ollama")

        assert provider.name == "ollama"

    def test_default_provider_from_env(self):
        """get_llm_provider utilise LLM_PROVIDER de l'environnement."""
        from app.llm.factory import get_llm_provider

        with patch.dict(os.environ, {"LLM_PROVIDER": "ollama"}):
            provider = get_llm_provider()
            assert provider.name == "ollama"

    def test_default_provider_is_claude(self, mock_anthropic):
        """Le provider par défaut est Claude."""
        if "app.llm.claude_provider" in sys.modules:
            del sys.modules["app.llm.claude_provider"]
        if "app.llm.factory" in sys.modules:
            del sys.modules["app.llm.factory"]

        from app.llm.factory import get_llm_provider

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}, clear=True):
            provider = get_llm_provider()
            assert provider.name == "claude"

    def test_unknown_provider_raises_error(self):
        """get_llm_provider lève une erreur pour un provider inconnu."""
        from app.llm.factory import get_llm_provider

        with pytest.raises(ValueError, match="Provider LLM inconnu"):
            get_llm_provider(provider_type="unknown")

    def test_provider_type_case_insensitive(self):
        """Le type de provider est insensible à la casse."""
        from app.llm.factory import get_llm_provider

        provider1 = get_llm_provider(provider_type="OLLAMA")
        provider2 = get_llm_provider(provider_type="Ollama")
        provider3 = get_llm_provider(provider_type="ollama")

        assert provider1.name == "ollama"
        assert provider2.name == "ollama"
        assert provider3.name == "ollama"

    def test_is_api_key_required_claude(self):
        """is_api_key_required retourne True pour Claude."""
        with patch.dict(os.environ, {"LLM_PROVIDER": "claude"}):
            assert is_api_key_required() is True

    def test_is_api_key_required_ollama(self):
        """is_api_key_required retourne False pour Ollama."""
        with patch.dict(os.environ, {"LLM_PROVIDER": "ollama"}):
            assert is_api_key_required() is False

    def test_is_api_key_required_default(self):
        """is_api_key_required retourne True par défaut (Claude)."""
        with patch.dict(os.environ, {}, clear=True):
            assert is_api_key_required() is True
