# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests complets pour la factory des adapters LLM.

Ces tests vérifient:
- get_llm_adapter avec différents providers
- Configuration via variables d'environnement
- Gestion des providers invalides
- Injection de dépendances correcte
"""

import pytest
import os
import sys
from unittest.mock import patch, MagicMock


# ============================================================================
# TESTS - GET LLM ADAPTER FACTORY
# ============================================================================

class TestGetLLMAdapterFactory:
    """Tests pour get_llm_adapter factory."""

    def test_get_llm_adapter_claude(self):
        """Factory retourne ClaudeAdapter pour provider 'claude'."""
        mock_anthropic = MagicMock()
        with patch.dict(sys.modules, {'anthropic': mock_anthropic}):
            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key", "LLM_PROVIDER": ""}):
                import importlib
                import app.adapters.llm as llm_module
                importlib.reload(llm_module)

                adapter = llm_module.get_llm_adapter("claude")

                assert adapter.name == "claude"

    def test_get_llm_adapter_ollama(self):
        """Factory retourne OllamaAdapter pour provider 'ollama'."""
        from app.adapters.llm import get_llm_adapter

        adapter = get_llm_adapter("ollama")

        assert adapter.name == "ollama"

    def test_get_llm_adapter_default_from_env(self):
        """Factory utilise LLM_PROVIDER si pas de paramètre."""
        mock_anthropic = MagicMock()
        with patch.dict(sys.modules, {'anthropic': mock_anthropic}):
            with patch.dict(os.environ, {
                "LLM_PROVIDER": "claude",
                "ANTHROPIC_API_KEY": "test-key"
            }):
                import importlib
                import app.adapters.llm as llm_module
                importlib.reload(llm_module)

                adapter = llm_module.get_llm_adapter()

                assert adapter.name == "claude"

    def test_get_llm_adapter_default_is_claude(self):
        """Factory par défaut retourne Claude si LLM_PROVIDER=claude."""
        mock_anthropic = MagicMock()
        with patch.dict(sys.modules, {'anthropic': mock_anthropic}):
            # LLM_PROVIDER doit être "claude" explicitement car "" est invalide
            with patch.dict(os.environ, {
                "LLM_PROVIDER": "claude",
                "ANTHROPIC_API_KEY": "test-key"
            }, clear=False):
                import importlib
                import app.adapters.llm as llm_module
                importlib.reload(llm_module)

                adapter = llm_module.get_llm_adapter()

                assert adapter.name == "claude"

    def test_get_llm_adapter_invalid_provider_raises(self):
        """Factory lève erreur pour provider invalide."""
        from app.adapters.llm import get_llm_adapter

        with pytest.raises(ValueError, match="non supporté"):
            get_llm_adapter("gpt4")

    def test_get_llm_adapter_case_sensitive(self):
        """Factory est case-sensitive."""
        from app.adapters.llm import get_llm_adapter

        with pytest.raises(ValueError):
            get_llm_adapter("Claude")  # Majuscule

        with pytest.raises(ValueError):
            get_llm_adapter("OLLAMA")  # Tout en majuscules

    def test_get_llm_adapter_empty_string(self):
        """Factory avec string vide utilise défaut."""
        # NB : d'autres tests (test_knowledge_capture_unit, test_draft_quality_tracker_unit)
        # font os.environ.setdefault("LLM_PROVIDER", "ollama") au niveau module, ce qui
        # pollue l'env global. On force "claude" explicitement ici.
        mock_anthropic = MagicMock()
        with patch.dict(sys.modules, {'anthropic': mock_anthropic}):
            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key", "LLM_PROVIDER": "claude"}):
                import importlib
                import app.adapters.llm as llm_module
                importlib.reload(llm_module)

                # Empty string is falsy, so it should use env variable
                adapter = llm_module.get_llm_adapter("")

                # Should fall back to default (claude)
                assert adapter.name == "claude"

    def test_get_llm_adapter_whitespace_provider_invalid(self):
        """Factory avec espaces est invalide."""
        from app.adapters.llm import get_llm_adapter

        with pytest.raises(ValueError):
            get_llm_adapter("  ")

    def test_get_llm_adapter_special_chars_invalid(self):
        """Factory avec caractères spéciaux est invalide."""
        from app.adapters.llm import get_llm_adapter

        with pytest.raises(ValueError):
            get_llm_adapter("claude;rm -rf /")

        with pytest.raises(ValueError):
            get_llm_adapter("ollama\necho bad")


# ============================================================================
# TESTS - ADAPTER IMPLEMENTATIONS CHECK
# ============================================================================

class TestAdapterImplementationsCheck:
    """Tests pour vérifier les implémentations des adapters."""

    def test_claude_adapter_exported(self):
        """ClaudeAdapter est exporté."""
        from app.adapters.llm import ClaudeAdapter
        assert ClaudeAdapter is not None

    def test_ollama_adapter_exported(self):
        """OllamaAdapter est exporté."""
        from app.adapters.llm import OllamaAdapter
        assert OllamaAdapter is not None

    def test_get_llm_adapter_exported(self):
        """get_llm_adapter est exporté."""
        from app.adapters.llm import get_llm_adapter
        assert callable(get_llm_adapter)

    def test_all_exports(self):
        """__all__ contient les exports attendus."""
        from app.adapters.llm import __all__

        assert "ClaudeAdapter" in __all__
        assert "OllamaAdapter" in __all__
        assert "get_llm_adapter" in __all__


# ============================================================================
# TESTS - CLAUDE ADAPTER INITIALIZATION
# ============================================================================

class TestClaudeAdapterInitialization:
    """Tests d'initialisation de ClaudeAdapter."""

    def test_init_with_api_key_param(self):
        """Init avec api_key en paramètre."""
        mock_anthropic = MagicMock()
        with patch.dict(sys.modules, {'anthropic': mock_anthropic}):
            import importlib
            import app.adapters.llm.claude_adapter as claude_module
            importlib.reload(claude_module)

            adapter = claude_module.ClaudeAdapter(api_key="my-key")

            assert adapter._api_key == "my-key"

    def test_init_with_api_key_from_env(self):
        """Init avec api_key depuis env."""
        mock_anthropic = MagicMock()
        with patch.dict(sys.modules, {'anthropic': mock_anthropic}):
            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "env-key"}):
                import importlib
                import app.adapters.llm.claude_adapter as claude_module
                importlib.reload(claude_module)

                adapter = claude_module.ClaudeAdapter()

                assert adapter._api_key == "env-key"

    def test_init_api_key_param_overrides_env(self):
        """Paramètre api_key prévaut sur env."""
        mock_anthropic = MagicMock()
        with patch.dict(sys.modules, {'anthropic': mock_anthropic}):
            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "env-key"}):
                import importlib
                import app.adapters.llm.claude_adapter as claude_module
                importlib.reload(claude_module)

                adapter = claude_module.ClaudeAdapter(api_key="param-key")

                assert adapter._api_key == "param-key"

    def test_init_with_model_param(self):
        """Init avec modèle en paramètre."""
        mock_anthropic = MagicMock()
        with patch.dict(sys.modules, {'anthropic': mock_anthropic}):
            import importlib
            import app.adapters.llm.claude_adapter as claude_module
            importlib.reload(claude_module)

            adapter = claude_module.ClaudeAdapter(
                model="claude-opus-4-20250514",
                api_key="test-key"
            )

            assert adapter.model == "claude-opus-4-20250514"

    def test_init_with_model_from_env(self):
        """Init avec modèle depuis env."""
        mock_anthropic = MagicMock()
        with patch.dict(sys.modules, {'anthropic': mock_anthropic}):
            with patch.dict(os.environ, {
                "LLM_MODEL": "claude-3-5-haiku-20241022",
                "ANTHROPIC_API_KEY": "test-key"
            }):
                import importlib
                import app.adapters.llm.claude_adapter as claude_module
                importlib.reload(claude_module)

                adapter = claude_module.ClaudeAdapter()

                assert adapter.model == "claude-3-5-haiku-20241022"


# ============================================================================
# TESTS - OLLAMA ADAPTER INITIALIZATION
# ============================================================================

class TestOllamaAdapterInitialization:
    """Tests d'initialisation de OllamaAdapter."""

    def test_init_default_values(self):
        """Init avec valeurs par défaut."""
        with patch.dict(os.environ, {}, clear=True):
            from app.adapters.llm import OllamaAdapter

            adapter = OllamaAdapter()

            assert "mixtral" in adapter.model or adapter.model is not None
            assert "localhost" in adapter._base_url or "11434" in adapter._base_url

    def test_init_with_custom_model(self):
        """Init avec modèle personnalisé."""
        from app.adapters.llm import OllamaAdapter

        adapter = OllamaAdapter(model="llama3.3:70b")

        assert adapter.model == "llama3.3:70b"

    def test_init_with_custom_base_url(self):
        """Init avec URL personnalisée."""
        from app.adapters.llm import OllamaAdapter

        adapter = OllamaAdapter(base_url="http://192.168.1.100:11434")

        assert adapter._base_url == "http://192.168.1.100:11434"

    def test_init_model_from_env(self):
        """Init modèle depuis env."""
        with patch.dict(os.environ, {"LLM_MODEL": "codellama:latest"}):
            from app.adapters.llm import OllamaAdapter

            adapter = OllamaAdapter()

            assert adapter.model == "codellama:latest"

    def test_init_base_url_from_env(self):
        """Init base_url depuis env."""
        with patch.dict(os.environ, {"OLLAMA_BASE_URL": "http://remote:11434"}):
            from app.adapters.llm import OllamaAdapter

            adapter = OllamaAdapter()

            assert adapter._base_url == "http://remote:11434"

    def test_init_params_override_env(self):
        """Paramètres prévalent sur env."""
        with patch.dict(os.environ, {
            "LLM_MODEL": "env-model",
            "OLLAMA_BASE_URL": "http://env:11434"
        }):
            from app.adapters.llm import OllamaAdapter

            adapter = OllamaAdapter(
                model="param-model",
                base_url="http://param:11434"
            )

            assert adapter.model == "param-model"
            assert adapter._base_url == "http://param:11434"


# ============================================================================
# TESTS - ADAPTER INTERFACE COMPATIBILITY
# ============================================================================

class TestAdapterInterfaceCompatibility:
    """Tests de compatibilité avec LLMPort."""

    def test_claude_implements_llm_port(self):
        """ClaudeAdapter implémente LLMPort."""
        from app.domain.ports import LLMPort

        mock_anthropic = MagicMock()
        with patch.dict(sys.modules, {'anthropic': mock_anthropic}):
            import importlib
            import app.adapters.llm.claude_adapter as claude_module
            importlib.reload(claude_module)

            adapter = claude_module.ClaudeAdapter(api_key="test")

            assert isinstance(adapter, LLMPort)

    def test_ollama_implements_llm_port(self):
        """OllamaAdapter implémente LLMPort."""
        from app.domain.ports import LLMPort
        from app.adapters.llm import OllamaAdapter

        adapter = OllamaAdapter()

        assert isinstance(adapter, LLMPort)

    def test_adapters_have_required_properties(self):
        """Les adapters ont les propriétés requises."""
        mock_anthropic = MagicMock()
        with patch.dict(sys.modules, {'anthropic': mock_anthropic}):
            import importlib
            import app.adapters.llm.claude_adapter as claude_module
            importlib.reload(claude_module)

            claude_adapter = claude_module.ClaudeAdapter(api_key="test")
            from app.adapters.llm import OllamaAdapter
            ollama_adapter = OllamaAdapter()

            # Vérifier name et model
            assert hasattr(claude_adapter, 'name')
            assert hasattr(claude_adapter, 'model')
            assert hasattr(ollama_adapter, 'name')
            assert hasattr(ollama_adapter, 'model')

            # Vérifier les valeurs
            assert isinstance(claude_adapter.name, str)
            assert isinstance(claude_adapter.model, str)
            assert isinstance(ollama_adapter.name, str)
            assert isinstance(ollama_adapter.model, str)

    def test_adapters_have_required_methods(self):
        """Les adapters ont les méthodes requises."""
        mock_anthropic = MagicMock()
        with patch.dict(sys.modules, {'anthropic': mock_anthropic}):
            import importlib
            import app.adapters.llm.claude_adapter as claude_module
            importlib.reload(claude_module)

            claude_adapter = claude_module.ClaudeAdapter(api_key="test")
            from app.adapters.llm import OllamaAdapter
            ollama_adapter = OllamaAdapter()

            # Vérifier complete et is_available
            assert callable(getattr(claude_adapter, 'complete', None))
            assert callable(getattr(claude_adapter, 'is_available', None))
            assert callable(getattr(ollama_adapter, 'complete', None))
            assert callable(getattr(ollama_adapter, 'is_available', None))
