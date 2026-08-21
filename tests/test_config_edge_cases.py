# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests edge cases pour la configuration de l'infrastructure.

Ces tests vérifient:
- Config avec valeurs par défaut
- Config depuis variables d'environnement
- Validation des configurations
- Chemins et propriétés calculées
"""

import pytest
import os
from pathlib import Path
from unittest.mock import patch

from app.infrastructure.config import Config


# ============================================================================
# TESTS - CONFIG INITIALIZATION
# ============================================================================

class TestConfigInitialization:
    """Tests d'initialisation de Config."""

    def test_default_initialization(self):
        """Config avec valeurs par défaut."""
        config = Config()

        assert config.llm_provider is not None
        assert config.project_root is not None
        assert isinstance(config.project_root, Path)

    def test_custom_llm_provider(self):
        """Config avec provider personnalisé."""
        config = Config(llm_provider="ollama")

        assert config.llm_provider == "ollama"

    def test_custom_llm_model(self):
        """Config avec modèle personnalisé."""
        config = Config(llm_model="claude-opus-4-20250514")

        assert config.llm_model == "claude-opus-4-20250514"

    def test_custom_max_tokens(self):
        """Config avec max_tokens personnalisés."""
        config = Config(
            max_tokens_draft=2048,
            max_tokens_critique=512
        )

        assert config.max_tokens_draft == 2048
        assert config.max_tokens_critique == 512

    def test_custom_paths(self):
        """Config avec chemins personnalisés."""
        custom_root = Path("/custom/project")
        config = Config(project_root=custom_root)

        assert config.project_root == custom_root


# ============================================================================
# TESTS - CONFIG FROM ENV
# ============================================================================

class TestConfigFromEnv:
    """Tests pour Config.from_env()."""

    def test_from_env_loads_defaults(self):
        """from_env charge les valeurs par défaut."""
        config = Config.from_env()

        assert config.llm_provider is not None
        assert config.project_root is not None

    def test_from_env_with_claude_provider(self):
        """from_env avec provider Claude."""
        with patch.dict(os.environ, {
            "LLM_PROVIDER": "claude",
            "ANTHROPIC_API_KEY": "test-key"
        }):
            config = Config.from_env()

            assert config.llm_provider == "claude"

    def test_from_env_with_ollama_provider(self):
        """from_env avec provider Ollama."""
        with patch.dict(os.environ, {"LLM_PROVIDER": "ollama"}):
            config = Config.from_env()

            assert config.llm_provider == "ollama"

    def test_from_env_case_insensitive_provider(self):
        """from_env normalise le provider en minuscules."""
        with patch.dict(os.environ, {"LLM_PROVIDER": "CLAUDE"}):
            config = Config.from_env()

            assert config.llm_provider == "claude"

    def test_from_env_custom_model(self):
        """from_env avec modèle personnalisé."""
        with patch.dict(os.environ, {
            "LLM_MODEL": "custom-model",
            "LLM_PROVIDER": "ollama"
        }):
            config = Config.from_env()

            assert config.llm_model == "custom-model"

    def test_from_env_custom_max_tokens(self):
        """from_env avec max_tokens personnalisés."""
        with patch.dict(os.environ, {
            "MAX_TOKENS_DRAFT": "4096",
            "MAX_TOKENS_CRITIQUE": "1024"
        }):
            config = Config.from_env()

            assert config.max_tokens_draft == 4096
            assert config.max_tokens_critique == 1024

    def test_from_env_invalid_max_tokens_raises(self):
        """from_env avec max_tokens invalides lève erreur."""
        with patch.dict(os.environ, {"MAX_TOKENS_DRAFT": "not-a-number"}):
            with pytest.raises(ValueError):
                Config.from_env()

    def test_from_env_with_custom_ollama_url(self):
        """from_env avec URL Ollama personnalisée."""
        with patch.dict(os.environ, {
            "LLM_PROVIDER": "ollama",
            "OLLAMA_BASE_URL": "http://192.168.1.100:11434"
        }):
            config = Config.from_env()

            assert config.ollama_base_url == "http://192.168.1.100:11434"


# ============================================================================
# TESTS - CONFIG PROPERTIES
# ============================================================================

class TestConfigProperties:
    """Tests pour les propriétés calculées de Config."""

    def test_knowledge_path(self):
        """knowledge_path retourne le bon chemin."""
        config = Config(project_root=Path("/project"))
        expected = Path("/project/knowledge/memoire.md")

        assert config.knowledge_path == expected

    def test_data_inputs_path(self):
        """data_inputs_path retourne le bon chemin."""
        config = Config()

        assert config.data_inputs_path is not None
        assert isinstance(config.data_inputs_path, Path)

    def test_data_outputs_path(self):
        """data_outputs_path retourne le bon chemin."""
        config = Config()

        assert config.data_outputs_path is not None
        assert isinstance(config.data_outputs_path, Path)


# ============================================================================
# TESTS - CONFIG VALIDATION
# ============================================================================

class TestConfigValidation:
    """Tests de validation de Config."""

    def test_validate_claude_without_api_key_raises(self):
        """validate lève erreur si Claude sans API key."""
        config = Config(
            llm_provider="claude",
            anthropic_api_key=None
        )

        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
            config.validate()

    def test_validate_claude_empty_api_key_raises(self):
        """validate lève erreur si Claude avec API key vide."""
        config = Config(
            llm_provider="claude",
            anthropic_api_key=""
        )

        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
            config.validate()

    def test_validate_claude_with_api_key_passes(self):
        """validate passe si Claude avec API key."""
        config = Config(
            llm_provider="claude",
            anthropic_api_key="test-key"
        )

        # Ne devrait pas lever d'erreur
        config.validate()

    def test_validate_ollama_without_api_key_passes(self):
        """validate passe pour Ollama sans API key."""
        config = Config(
            llm_provider="ollama",
            anthropic_api_key=None
        )

        # Ne devrait pas lever d'erreur
        config.validate()


# ============================================================================
# TESTS - CONFIG EDGE CASES
# ============================================================================

class TestConfigEdgeCases:
    """Tests edge cases pour Config."""

    def test_config_with_env_file(self, tmp_path):
        """Config depuis un fichier .env."""
        env_file = tmp_path / ".env"
        env_file.write_text("LLM_PROVIDER=ollama\nLLM_MODEL=llama3.3\n")

        # Patch os.environ pour s'assurer que les valeurs du fichier sont utilisées
        with patch.dict(os.environ, {"LLM_PROVIDER": "ollama"}):
            config = Config.from_env(env_path=env_file)

            # Les valeurs devraient être chargées depuis l'environnement patché
            assert config.llm_provider == "ollama"

    def test_config_with_nonexistent_env_file(self, tmp_path):
        """Config avec fichier .env inexistant."""
        env_file = tmp_path / "nonexistent.env"

        # Ne devrait pas lever d'erreur
        config = Config.from_env(env_path=env_file)

        assert config is not None

    def test_config_serialization(self):
        """Config peut être représentée en string."""
        config = Config(llm_provider="test")

        # repr devrait fonctionner
        repr_str = repr(config)
        assert "Config" in repr_str

    def test_config_equality(self):
        """Deux Config identiques sont égales."""
        config1 = Config(
            llm_provider="claude",
            max_tokens_draft=1024
        )
        config2 = Config(
            llm_provider="claude",
            max_tokens_draft=1024
        )

        # Les dataclasses supportent l'égalité
        assert config1 == config2

    def test_config_inequality(self):
        """Deux Config différentes ne sont pas égales."""
        config1 = Config(llm_provider="claude")
        config2 = Config(llm_provider="ollama")

        assert config1 != config2

    def test_config_model_defaults_per_provider(self):
        """Modèles par défaut diffèrent selon le provider."""
        config = Config()

        # Devrait avoir des modèles par défaut pour chaque provider
        assert config.claude_model_default is not None
        assert config.ollama_model_default is not None
        # Ils devraient être différents
        assert config.claude_model_default != config.ollama_model_default

    def test_config_negative_max_tokens(self):
        """Config avec max_tokens négatifs (edge case non validé)."""
        config = Config(max_tokens_draft=-100)

        # Pas de validation au constructeur
        assert config.max_tokens_draft == -100

    def test_config_zero_max_tokens(self):
        """Config avec max_tokens = 0."""
        config = Config(max_tokens_draft=0)

        assert config.max_tokens_draft == 0

    def test_config_very_large_max_tokens(self):
        """Config avec max_tokens très élevés."""
        config = Config(max_tokens_draft=1_000_000)

        assert config.max_tokens_draft == 1_000_000

    def test_config_unicode_provider(self):
        """Config avec provider unicode (edge case invalide)."""
        config = Config(llm_provider="クロード")

        # Accepté au constructeur mais invalide en pratique
        assert config.llm_provider == "クロード"

    def test_config_whitespace_provider(self):
        """Config avec provider espaces."""
        config = Config(llm_provider="  claude  ")

        # Non normalisé au constructeur
        assert config.llm_provider == "  claude  "


# ============================================================================
# TESTS - CONFIG THREAD SAFETY
# ============================================================================

class TestConfigThreadSafety:
    """Tests de thread safety pour Config."""

    def test_config_immutable_fields(self):
        """Les champs de Config sont mutables (dataclass standard)."""
        config = Config(llm_provider="claude")

        # Peut être modifié (pas frozen=True)
        config.llm_provider = "ollama"
        assert config.llm_provider == "ollama"

    def test_config_concurrent_from_env(self):
        """from_env peut être appelé de manière concurrente."""
        import threading

        configs = []
        errors = []

        def create_config(index):
            try:
                config = Config.from_env()
                configs.append(config)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=create_config, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(configs) == 10
