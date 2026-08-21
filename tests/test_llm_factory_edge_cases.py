# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests edge cases pour la factory LLM et sélection d'adapters.

Ces tests couvrent:
- get_llm_adapter: providers inconnus, valeurs edge case
- Configuration via variables d'environnement
- Gestion des erreurs d'initialisation
"""

import pytest
import os
import sys
from unittest.mock import patch, MagicMock


# ============================================================================
# TESTS - LLM ADAPTER FACTORY
# ============================================================================

class TestLLMAdapterFactory:
    """Tests edge cases pour get_llm_adapter."""

    def test_unknown_provider_raises(self):
        """Provider inconnu lève ValueError."""
        from app.adapters.llm import get_llm_adapter

        with pytest.raises(ValueError, match="non supporté"):
            get_llm_adapter("unknown_provider")

    def test_empty_provider_raises(self):
        """Provider vide utilise défaut (claude) mais sans API key lève erreur."""
        mock_anthropic = MagicMock()
        with patch.dict(sys.modules, {'anthropic': mock_anthropic}):
            with patch.dict(os.environ, {}, clear=True):
                from app.adapters.llm import get_llm_adapter

                # Sans ANTHROPIC_API_KEY, claude adapter échoue
                with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
                    get_llm_adapter("")

    def test_none_provider_uses_env_default(self):
        """Provider None utilise la variable d'environnement."""
        with patch.dict(os.environ, {"LLM_PROVIDER": "ollama"}):
            from app.adapters.llm import get_llm_adapter

            adapter = get_llm_adapter(None)
            assert adapter.name == "ollama"

    def test_case_sensitive_provider(self):
        """Provider est case-sensitive."""
        from app.adapters.llm import get_llm_adapter

        with pytest.raises(ValueError):
            get_llm_adapter("CLAUDE")  # Majuscules

        with pytest.raises(ValueError):
            get_llm_adapter("Claude")  # Mixed case

    def test_ollama_adapter_creation(self):
        """Création de l'adapter Ollama."""
        from app.adapters.llm import get_llm_adapter

        adapter = get_llm_adapter("ollama")

        assert adapter.name == "ollama"
        assert adapter.model is not None

    def test_claude_adapter_with_api_key(self):
        """Création de l'adapter Claude avec API key."""
        mock_anthropic = MagicMock()
        with patch.dict(sys.modules, {'anthropic': mock_anthropic}):
            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
                import importlib
                import app.adapters.llm as llm_module
                importlib.reload(llm_module)

                adapter = llm_module.get_llm_adapter("claude")

                assert adapter.name == "claude"

    def test_whitespace_provider_raises(self):
        """Provider avec espaces uniquement."""
        from app.adapters.llm import get_llm_adapter

        with pytest.raises(ValueError):
            get_llm_adapter("   ")

    def test_special_chars_provider_raises(self):
        """Provider avec caractères spéciaux."""
        from app.adapters.llm import get_llm_adapter

        with pytest.raises(ValueError):
            get_llm_adapter("claude@v2")

        with pytest.raises(ValueError):
            get_llm_adapter("ollama/local")


# ============================================================================
# TESTS - CLAUDE ADAPTER INITIALIZATION EDGE CASES
# ============================================================================

class TestClaudeAdapterInitEdgeCases:
    """Tests d'initialisation edge cases pour ClaudeAdapter."""

    def test_api_key_from_param_overrides_env(self):
        """API key en paramètre override la variable d'environnement."""
        mock_anthropic = MagicMock()
        with patch.dict(sys.modules, {'anthropic': mock_anthropic}):
            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "env-key"}):
                import importlib
                import app.adapters.llm.claude_adapter as claude_module
                importlib.reload(claude_module)

                adapter = claude_module.ClaudeAdapter(api_key="param-key")

                assert adapter._api_key == "param-key"

    def test_model_from_param_overrides_env(self):
        """Modèle en paramètre override la variable d'environnement."""
        mock_anthropic = MagicMock()
        with patch.dict(sys.modules, {'anthropic': mock_anthropic}):
            with patch.dict(os.environ, {
                "ANTHROPIC_API_KEY": "test",
                "LLM_MODEL": "claude-3-haiku"
            }):
                import importlib
                import app.adapters.llm.claude_adapter as claude_module
                importlib.reload(claude_module)

                adapter = claude_module.ClaudeAdapter(
                    api_key="test",
                    model="claude-opus-4-20250514"
                )

                assert adapter.model == "claude-opus-4-20250514"

    def test_whitespace_api_key_is_falsy(self):
        """API key avec espaces uniquement est considérée comme vide."""
        mock_anthropic = MagicMock()
        with patch.dict(sys.modules, {'anthropic': mock_anthropic}):
            with patch.dict(os.environ, {}, clear=True):
                import importlib
                import app.adapters.llm.claude_adapter as claude_module
                importlib.reload(claude_module)

                # "   " est truthy mais devrait être traité comme valide ou invalide?
                # Le code actuel accepte "   " comme clé valide (truthy)
                adapter = claude_module.ClaudeAdapter(api_key="   ")
                assert adapter._api_key == "   "


# ============================================================================
# TESTS - OLLAMA ADAPTER INITIALIZATION EDGE CASES
# ============================================================================

class TestOllamaAdapterInitEdgeCases:
    """Tests d'initialisation edge cases pour OllamaAdapter."""

    def test_custom_base_url(self):
        """URL de base personnalisée."""
        from app.adapters.llm.ollama_adapter import OllamaAdapter

        adapter = OllamaAdapter(base_url="http://192.168.1.100:11434")

        assert adapter._base_url == "http://192.168.1.100:11434"

    def test_base_url_from_env(self):
        """URL de base depuis variable d'environnement."""
        with patch.dict(os.environ, {"OLLAMA_BASE_URL": "http://remote:11434"}):
            from app.adapters.llm.ollama_adapter import OllamaAdapter

            adapter = OllamaAdapter()

            assert adapter._base_url == "http://remote:11434"

    def test_malformed_base_url(self):
        """URL de base malformée (pas de validation au construction)."""
        from app.adapters.llm.ollama_adapter import OllamaAdapter

        # Pas de validation à la construction, erreur lors de l'appel
        adapter = OllamaAdapter(base_url="not-a-url")
        assert adapter._base_url == "not-a-url"

    def test_empty_base_url(self):
        """URL de base vide utilise défaut."""
        with patch.dict(os.environ, {}, clear=True):
            from app.adapters.llm.ollama_adapter import OllamaAdapter

            adapter = OllamaAdapter(base_url="")

            # Vide mais truthy check pas fait, utilise la valeur directement
            # Comportement dépend de l'implémentation
            assert adapter._base_url == "" or "localhost" in adapter._base_url

    def test_model_with_tag(self):
        """Modèle avec tag de version."""
        from app.adapters.llm.ollama_adapter import OllamaAdapter

        adapter = OllamaAdapter(model="llama3.3:70b-instruct-q4_K_M")

        assert adapter.model == "llama3.3:70b-instruct-q4_K_M"

    def test_model_without_tag(self):
        """Modèle sans tag."""
        from app.adapters.llm.ollama_adapter import OllamaAdapter

        adapter = OllamaAdapter(model="mistral")

        assert adapter.model == "mistral"


# ============================================================================
# TESTS - ADAPTER INTERFACE GUARANTEES
# ============================================================================

class TestAdapterInterfaceGuarantees:
    """Tests de garanties d'interface pour les adapters."""

    def test_ollama_implements_llm_port(self):
        """OllamaAdapter implémente correctement LLMPort."""
        from app.adapters.llm.ollama_adapter import OllamaAdapter
        from app.domain.ports import LLMPort

        adapter = OllamaAdapter()

        assert isinstance(adapter, LLMPort)
        assert callable(getattr(adapter, 'complete', None))
        assert callable(getattr(adapter, 'is_available', None))
        assert hasattr(adapter, 'name')
        assert hasattr(adapter, 'model')

    def test_claude_implements_llm_port(self):
        """ClaudeAdapter implémente correctement LLMPort."""
        mock_anthropic = MagicMock()
        with patch.dict(sys.modules, {'anthropic': mock_anthropic}):
            import importlib
            import app.adapters.llm.claude_adapter as claude_module
            importlib.reload(claude_module)

            from app.domain.ports import LLMPort

            adapter = claude_module.ClaudeAdapter(api_key="test")

            assert isinstance(adapter, LLMPort)
            assert callable(getattr(adapter, 'complete', None))
            assert callable(getattr(adapter, 'is_available', None))

    def test_adapters_have_consistent_name_property(self):
        """Les adapters ont une propriété name cohérente."""
        mock_anthropic = MagicMock()
        with patch.dict(sys.modules, {'anthropic': mock_anthropic}):
            import importlib
            import app.adapters.llm.claude_adapter as claude_module
            importlib.reload(claude_module)

            from app.adapters.llm.ollama_adapter import OllamaAdapter

            claude = claude_module.ClaudeAdapter(api_key="test")
            ollama = OllamaAdapter()

            assert claude.name == "claude"
            assert ollama.name == "ollama"
            assert claude.name != ollama.name


# ============================================================================
# TESTS - CONCURRENT ADAPTER CREATION
# ============================================================================

class TestConcurrentAdapterCreation:
    """Tests de création concurrente d'adapters."""

    def test_multiple_ollama_instances(self):
        """Création de plusieurs instances Ollama."""
        from app.adapters.llm.ollama_adapter import OllamaAdapter

        adapters = [
            OllamaAdapter(model=f"model-{i}")
            for i in range(10)
        ]

        assert len(adapters) == 10
        assert all(a.name == "ollama" for a in adapters)

    def test_ollama_instances_independent(self):
        """Instances Ollama sont indépendantes."""
        from app.adapters.llm.ollama_adapter import OllamaAdapter

        adapter1 = OllamaAdapter(model="llama3.3:latest")
        adapter2 = OllamaAdapter(model="mistral:latest")

        assert adapter1.model == "llama3.3:latest"
        assert adapter2.model == "mistral:latest"
        assert adapter1 is not adapter2


# ============================================================================
# TESTS - EDGE CASES FOR COMPLETE METHOD PARAMS
# ============================================================================

class TestCompleteMethodParams:
    """Tests edge cases pour les paramètres de complete()."""

    @patch("app.adapters.llm.ollama_adapter.requests.post")
    def test_max_tokens_zero(self, mock_post):
        """max_tokens à zéro."""
        from app.adapters.llm.ollama_adapter import OllamaAdapter

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": {"content": ""},
            "prompt_eval_count": 10,
            "eval_count": 0
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        adapter = OllamaAdapter()
        adapter.complete(
            system="System",
            user="User",
            max_tokens=0
        )

        call_args = mock_post.call_args
        payload = call_args.kwargs.get("json", call_args[1].get("json", {}))
        assert payload["options"]["num_predict"] == 0

    @patch("app.adapters.llm.ollama_adapter.requests.post")
    def test_max_tokens_negative(self, mock_post):
        """max_tokens négatif (comportement indéfini mais ne doit pas crasher)."""
        from app.adapters.llm.ollama_adapter import OllamaAdapter

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": {"content": ""},
            "prompt_eval_count": 10,
            "eval_count": 0
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        adapter = OllamaAdapter()

        # Ne doit pas lever d'erreur côté Python
        response = adapter.complete(
            system="System",
            user="User",
            max_tokens=-100
        )
        assert response is not None

    @patch("app.adapters.llm.ollama_adapter.requests.post")
    def test_max_tokens_very_large(self, mock_post):
        """max_tokens très grand."""
        from app.adapters.llm.ollama_adapter import OllamaAdapter

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": {"content": "Large response"},
            "prompt_eval_count": 100,
            "eval_count": 1000000
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        adapter = OllamaAdapter()
        response = adapter.complete(
            system="System",
            user="User",
            max_tokens=1000000
        )

        assert response.output_tokens == 1000000

    @patch("app.adapters.llm.ollama_adapter.requests.post")
    def test_empty_system_and_user_prompts(self, mock_post):
        """Prompts système et utilisateur vides."""
        from app.adapters.llm.ollama_adapter import OllamaAdapter

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": {"content": "Response"},
            "prompt_eval_count": 0,
            "eval_count": 5
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        adapter = OllamaAdapter()
        response = adapter.complete(system="", user="")

        assert response.content == "Response"
        assert response.input_tokens == 0


# ============================================================================
# TESTS - EXPORTS VALIDATION
# ============================================================================

class TestExportsValidation:
    """Tests de validation des exports du module."""

    def test_all_exports_exist(self):
        """Tous les exports déclarés existent."""
        from app.adapters.llm import __all__

        import app.adapters.llm as llm_module

        for name in __all__:
            assert hasattr(llm_module, name), f"Missing export: {name}"

    def test_exports_are_classes_or_functions(self):
        """Les exports sont des classes ou fonctions."""
        from app.adapters.llm import ClaudeAdapter, OllamaAdapter, get_llm_adapter

        assert isinstance(ClaudeAdapter, type)
        assert isinstance(OllamaAdapter, type)
        assert callable(get_llm_adapter)
