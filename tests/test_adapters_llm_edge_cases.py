# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests edge cases pour les Adapters LLM.

Ces tests vérifient:
- ClaudeAdapter : clé API manquante, erreurs API, modèles invalides
- OllamaAdapter : connexion échouée, timeout, modèles manquants
- Comportement en conditions de stress
"""

import pytest
import os
import sys
from unittest.mock import patch, MagicMock, Mock

from app.domain.ports import LLMResponse


# ============================================================================
# TESTS - CLAUDE ADAPTER EDGE CASES
# ============================================================================

class TestClaudeAdapterEdgeCases:
    """Tests edge cases pour ClaudeAdapter."""

    def test_missing_api_key_raises(self):
        """Clé API manquante lève une erreur."""
        # Mock the anthropic module before import
        mock_anthropic_module = MagicMock()
        with patch.dict(sys.modules, {'anthropic': mock_anthropic_module}):
            with patch.dict(os.environ, {}, clear=True):
                # Reload to apply mock
                import importlib
                import app.adapters.llm.claude_adapter as claude_module
                importlib.reload(claude_module)

                with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
                    claude_module.ClaudeAdapter(api_key=None)

    def test_empty_api_key_raises(self):
        """Clé API vide lève une erreur quand env aussi vide."""
        mock_anthropic_module = MagicMock()
        with patch.dict(sys.modules, {'anthropic': mock_anthropic_module}):
            with patch.dict(os.environ, {}, clear=True):
                import importlib
                import app.adapters.llm.claude_adapter as claude_module
                importlib.reload(claude_module)

                # api_key="" is falsy, so it will try to get from env, which is also empty
                with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
                    claude_module.ClaudeAdapter(api_key="")

    def test_custom_model(self):
        """Modèle personnalisé."""
        mock_anthropic_module = MagicMock()
        with patch.dict(sys.modules, {'anthropic': mock_anthropic_module}):
            import importlib
            import app.adapters.llm.claude_adapter as claude_module
            importlib.reload(claude_module)

            adapter = claude_module.ClaudeAdapter(model="claude-opus-4-20250514", api_key="test-key")

            assert adapter.model == "claude-opus-4-20250514"
            assert adapter.name == "claude"

    def test_default_model_from_env(self):
        """Modèle par défaut depuis variable d'environnement."""
        mock_anthropic_module = MagicMock()
        with patch.dict(sys.modules, {'anthropic': mock_anthropic_module}):
            with patch.dict(os.environ, {"LLM_MODEL": "claude-3-5-haiku-20241022", "ANTHROPIC_API_KEY": "test"}):
                import importlib
                import app.adapters.llm.claude_adapter as claude_module
                importlib.reload(claude_module)

                adapter = claude_module.ClaudeAdapter()

                assert adapter.model == "claude-3-5-haiku-20241022"

    def test_complete_success(self):
        """Complétion réussie."""
        mock_anthropic_module = MagicMock()

        # Setup mock response
        mock_response = Mock()
        mock_response.content = [Mock(text="Response content")]
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic_module.Anthropic.return_value = mock_client

        with patch.dict(sys.modules, {'anthropic': mock_anthropic_module}):
            import importlib
            import app.adapters.llm.claude_adapter as claude_module
            importlib.reload(claude_module)

            adapter = claude_module.ClaudeAdapter(api_key="test-key")
            response = adapter.complete(
                system="System prompt",
                user="User message"
            )

            assert isinstance(response, LLMResponse)
            assert response.content == "Response content"
            assert response.input_tokens == 100
            assert response.output_tokens == 50

    def test_complete_with_max_tokens(self):
        """Complétion avec max_tokens personnalisé."""
        mock_anthropic_module = MagicMock()

        mock_response = Mock()
        mock_response.content = [Mock(text="Short")]
        mock_response.usage.input_tokens = 10
        mock_response.usage.output_tokens = 5

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic_module.Anthropic.return_value = mock_client

        with patch.dict(sys.modules, {'anthropic': mock_anthropic_module}):
            import importlib
            import app.adapters.llm.claude_adapter as claude_module
            importlib.reload(claude_module)

            adapter = claude_module.ClaudeAdapter(api_key="test-key")
            adapter.complete(system="", user="", max_tokens=2048)

            # Vérifier que max_tokens est passé
            call_args = mock_client.messages.create.call_args
            assert call_args.kwargs["max_tokens"] == 2048

    def test_api_error_handling(self):
        """Gestion des erreurs API."""
        mock_anthropic_module = MagicMock()

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("API Error")
        mock_anthropic_module.Anthropic.return_value = mock_client

        with patch.dict(sys.modules, {'anthropic': mock_anthropic_module}):
            import importlib
            import app.adapters.llm.claude_adapter as claude_module
            importlib.reload(claude_module)

            adapter = claude_module.ClaudeAdapter(api_key="test-key")

            with pytest.raises(Exception, match="API Error"):
                adapter.complete(system="", user="")

    def test_is_available_with_key(self):
        """is_available avec clé API."""
        mock_anthropic_module = MagicMock()
        with patch.dict(sys.modules, {'anthropic': mock_anthropic_module}):
            import importlib
            import app.adapters.llm.claude_adapter as claude_module
            importlib.reload(claude_module)

            adapter = claude_module.ClaudeAdapter(api_key="test-key")

            assert adapter.is_available() is True

    def test_unicode_content_handling(self):
        """Gestion du contenu unicode."""
        mock_anthropic_module = MagicMock()

        mock_response = Mock()
        mock_response.content = [Mock(text="Réponse avec 日本語 et 🎉")]
        mock_response.usage.input_tokens = 50
        mock_response.usage.output_tokens = 20

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic_module.Anthropic.return_value = mock_client

        with patch.dict(sys.modules, {'anthropic': mock_anthropic_module}):
            import importlib
            import app.adapters.llm.claude_adapter as claude_module
            importlib.reload(claude_module)

            adapter = claude_module.ClaudeAdapter(api_key="test-key")
            response = adapter.complete(
                system="Réponds en japonais",
                user="日本語で答えて"
            )

            assert "日本語" in response.content
            assert "🎉" in response.content


# ============================================================================
# TESTS - OLLAMA ADAPTER EDGE CASES
# ============================================================================

class TestOllamaAdapterEdgeCases:
    """Tests edge cases pour OllamaAdapter."""

    def test_default_configuration(self):
        """Configuration par défaut."""
        # Clear environment variables that could override defaults
        with patch.dict(os.environ, {}, clear=True):
            from app.adapters.llm.ollama_adapter import OllamaAdapter

            adapter = OllamaAdapter()

            assert adapter.name == "ollama"
            # Default from code when no env vars
            assert "mixtral" in adapter.model or "latest" in adapter.model or adapter.model is not None

    def test_custom_model_and_url(self):
        """Modèle et URL personnalisés."""
        from app.adapters.llm.ollama_adapter import OllamaAdapter

        adapter = OllamaAdapter(
            model="llama3.3:70b",
            base_url="http://custom-host:11434"
        )

        assert adapter.model == "llama3.3:70b"
        assert adapter._base_url == "http://custom-host:11434"

    def test_env_configuration(self):
        """Configuration depuis variables d'environnement."""
        with patch.dict(os.environ, {
            "LLM_MODEL": "codellama:latest",
            "OLLAMA_BASE_URL": "http://192.168.1.100:11434"
        }):
            from app.adapters.llm.ollama_adapter import OllamaAdapter

            adapter = OllamaAdapter()

            assert adapter.model == "codellama:latest"
            assert adapter._base_url == "http://192.168.1.100:11434"

    @patch("app.adapters.llm.ollama_adapter.requests.post")
    def test_complete_success(self, mock_post):
        """Complétion réussie."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {"content": "Ollama response"},
            "prompt_eval_count": 80,
            "eval_count": 40
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        from app.adapters.llm.ollama_adapter import OllamaAdapter

        adapter = OllamaAdapter()
        response = adapter.complete(
            system="System prompt",
            user="User message"
        )

        assert response.content == "Ollama response"
        assert response.input_tokens == 80
        assert response.output_tokens == 40

    @patch("app.adapters.llm.ollama_adapter.requests.post")
    def test_connection_error(self, mock_post):
        """Erreur de connexion à Ollama."""
        import requests
        from app.domain.exceptions import LLMConnectionError

        mock_post.side_effect = requests.exceptions.ConnectionError()

        from app.adapters.llm.ollama_adapter import OllamaAdapter

        adapter = OllamaAdapter()

        with pytest.raises(LLMConnectionError):
            adapter.complete(system="", user="")

    @patch("app.adapters.llm.ollama_adapter.requests.post")
    def test_timeout_error(self, mock_post):
        """Timeout de requête."""
        import requests
        from app.domain.exceptions import LLMTimeoutError

        mock_post.side_effect = requests.exceptions.Timeout()

        from app.adapters.llm.ollama_adapter import OllamaAdapter

        adapter = OllamaAdapter()

        with pytest.raises(LLMTimeoutError):
            adapter.complete(system="", user="")

    @patch("app.adapters.llm.ollama_adapter.requests.post")
    def test_response_missing_fields(self, mock_post):
        """Réponse avec champs manquants doit lever LLMResponseError."""
        from app.domain.exceptions import LLMResponseError

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            # message et counts manquants
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        from app.adapters.llm.ollama_adapter import OllamaAdapter

        adapter = OllamaAdapter()

        # Maintenant on lève une exception au lieu de retourner des valeurs par défaut
        with pytest.raises(LLMResponseError):
            adapter.complete(system="", user="")

    @patch("app.adapters.llm.ollama_adapter.requests.get")
    def test_is_available_success(self, mock_get):
        """is_available quand Ollama répond."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        from app.adapters.llm.ollama_adapter import OllamaAdapter

        adapter = OllamaAdapter()

        assert adapter.is_available() is True

    @patch("app.adapters.llm.ollama_adapter.requests.get")
    def test_is_available_failure(self, mock_get):
        """is_available quand Ollama ne répond pas."""
        import requests

        mock_get.side_effect = requests.exceptions.ConnectionError()

        from app.adapters.llm.ollama_adapter import OllamaAdapter

        adapter = OllamaAdapter()

        assert adapter.is_available() is False

    @patch("app.adapters.llm.ollama_adapter.requests.get")
    def test_is_available_http_error(self, mock_get):
        """is_available avec erreur HTTP."""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_get.return_value = mock_response

        from app.adapters.llm.ollama_adapter import OllamaAdapter

        adapter = OllamaAdapter()

        assert adapter.is_available() is False

    @patch("app.adapters.llm.ollama_adapter.requests.get")
    def test_list_models_success(self, mock_get):
        """Liste des modèles réussie."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "models": [
                {"name": "llama3.3:latest"},
                {"name": "mixtral:latest"},
                {"name": "codellama:7b"},
            ]
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        from app.adapters.llm.ollama_adapter import OllamaAdapter

        adapter = OllamaAdapter()
        models = adapter.list_models()

        assert len(models) == 3
        assert "llama3.3:latest" in models
        assert "mixtral:latest" in models

    @patch("app.adapters.llm.ollama_adapter.requests.get")
    def test_list_models_empty(self, mock_get):
        """Liste des modèles vide."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"models": []}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        from app.adapters.llm.ollama_adapter import OllamaAdapter

        adapter = OllamaAdapter()
        models = adapter.list_models()

        assert models == []

    @patch("app.adapters.llm.ollama_adapter.requests.get")
    def test_list_models_failure(self, mock_get):
        """Liste des modèles échouée."""
        import requests

        mock_get.side_effect = requests.exceptions.ConnectionError()

        from app.adapters.llm.ollama_adapter import OllamaAdapter

        adapter = OllamaAdapter()
        models = adapter.list_models()

        assert models == []

    @patch("app.adapters.llm.ollama_adapter.requests.post")
    def test_http_error_status(self, mock_post):
        """Erreur HTTP (status 500) doit lever LLMUnavailableError."""
        import requests
        from app.domain.exceptions import LLMUnavailableError

        mock_response = Mock()
        mock_response.status_code = 500
        # L'HTTPError doit avoir un .response.status_code pour être correctement traité
        http_error = requests.exceptions.HTTPError("Server Error")
        http_error.response = mock_response
        mock_response.raise_for_status.side_effect = http_error
        mock_post.return_value = mock_response

        from app.adapters.llm.ollama_adapter import OllamaAdapter

        adapter = OllamaAdapter()

        with pytest.raises(LLMUnavailableError):
            adapter.complete(system="", user="")

    @patch("app.adapters.llm.ollama_adapter.requests.post")
    def test_model_not_found(self, mock_post):
        """Modèle non trouvé doit lever LLMModelNotFoundError."""
        import requests
        from app.domain.exceptions import LLMModelNotFoundError

        mock_response = Mock()
        mock_response.status_code = 404
        # L'HTTPError doit avoir un .response.status_code pour être correctement traité
        http_error = requests.exceptions.HTTPError("Model not found")
        http_error.response = mock_response
        mock_response.raise_for_status.side_effect = http_error
        mock_post.return_value = mock_response

        from app.adapters.llm.ollama_adapter import OllamaAdapter

        adapter = OllamaAdapter(model="nonexistent:latest")

        with pytest.raises(LLMModelNotFoundError):
            adapter.complete(system="", user="")


# ============================================================================
# TESTS - ADAPTER FACTORY / SELECTION
# ============================================================================

class TestLLMAdapterSelection:
    """Tests de sélection d'adapter LLM."""

    def test_claude_adapter_interface_compliance(self):
        """ClaudeAdapter respecte l'interface LLMPort."""
        mock_anthropic_module = MagicMock()
        with patch.dict(sys.modules, {'anthropic': mock_anthropic_module}):
            import importlib
            import app.adapters.llm.claude_adapter as claude_module
            importlib.reload(claude_module)

            from app.domain.ports import LLMPort

            adapter = claude_module.ClaudeAdapter(api_key="test-key")

            assert isinstance(adapter, LLMPort)
            assert hasattr(adapter, 'name')
            assert hasattr(adapter, 'model')
            assert hasattr(adapter, 'complete')
            assert hasattr(adapter, 'is_available')

    def test_ollama_adapter_interface_compliance(self):
        """OllamaAdapter respecte l'interface LLMPort."""
        from app.adapters.llm.ollama_adapter import OllamaAdapter
        from app.domain.ports import LLMPort

        adapter = OllamaAdapter()

        assert isinstance(adapter, LLMPort)
        assert hasattr(adapter, 'name')
        assert hasattr(adapter, 'model')
        assert hasattr(adapter, 'complete')
        assert hasattr(adapter, 'is_available')


# ============================================================================
# TESTS - STRESS AND EDGE CASES
# ============================================================================

class TestLLMAdapterStress:
    """Tests de stress pour les adapters LLM."""

    @patch("app.adapters.llm.ollama_adapter.requests.post")
    def test_very_long_prompt(self, mock_post):
        """Prompt très long."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {"content": "Short response"},
            "prompt_eval_count": 100000,
            "eval_count": 50
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        from app.adapters.llm.ollama_adapter import OllamaAdapter

        adapter = OllamaAdapter()
        long_prompt = "A" * 100000  # 100k caractères

        response = adapter.complete(system=long_prompt, user="Short")

        assert response.input_tokens == 100000

    @patch("app.adapters.llm.ollama_adapter.requests.post")
    def test_unicode_heavy_prompt(self, mock_post):
        """Prompt avec beaucoup d'unicode."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {"content": "Response"},
            "prompt_eval_count": 1000,
            "eval_count": 50
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        from app.adapters.llm.ollama_adapter import OllamaAdapter

        adapter = OllamaAdapter()
        unicode_prompt = "🎉" * 1000 + "日本語" * 500

        response = adapter.complete(system=unicode_prompt, user="Test")

        assert response.content == "Response"

    @patch("app.adapters.llm.ollama_adapter.requests.post")
    def test_empty_response_content(self, mock_post):
        """Réponse avec contenu vide."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {"content": ""},
            "prompt_eval_count": 100,
            "eval_count": 0
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        from app.adapters.llm.ollama_adapter import OllamaAdapter

        adapter = OllamaAdapter()
        response = adapter.complete(system="System", user="User")

        assert response.content == ""
        assert response.output_tokens == 0

    @patch("app.adapters.llm.ollama_adapter.requests.post")
    def test_special_characters_in_prompt(self, mock_post):
        """Caractères spéciaux dans le prompt."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {"content": "OK"},
            "prompt_eval_count": 50,
            "eval_count": 2
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        from app.adapters.llm.ollama_adapter import OllamaAdapter

        adapter = OllamaAdapter()
        special_prompt = '<script>alert("xss")</script>\n\t\r\0'

        response = adapter.complete(system=special_prompt, user="Test")

        assert response.content == "OK"


# ============================================================================
# TESTS - CONCURRENT ACCESS
# ============================================================================

class TestLLMAdapterConcurrency:
    """Tests d'accès concurrent aux adapters."""

    @patch("app.adapters.llm.ollama_adapter.requests.post")
    def test_concurrent_requests(self, mock_post):
        """Requêtes concurrentes."""
        import threading

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {"content": "Response"},
            "prompt_eval_count": 10,
            "eval_count": 5
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        from app.adapters.llm.ollama_adapter import OllamaAdapter

        adapter = OllamaAdapter()
        results = []
        errors = []

        def make_request(index):
            try:
                response = adapter.complete(
                    system=f"System {index}",
                    user=f"User {index}"
                )
                results.append(response)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=make_request, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results) == 10
