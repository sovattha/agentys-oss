# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour le module yaml_config.
"""

import pytest
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

# Skip si PyYAML non disponible
pytest.importorskip("yaml")

from app.infrastructure.yaml_config import (
    YamlConfigLoader,
    generate_default_config,
    create_default_config_file,
)


# ============================================================================
# TESTS YAML CONFIG LOADER
# ============================================================================

class TestYamlConfigLoader:
    """Tests pour YamlConfigLoader."""

    @pytest.fixture
    def temp_dir(self):
        """Crée un répertoire temporaire."""
        with TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def config_file(self, temp_dir):
        """Crée un fichier de configuration de test."""
        config_path = temp_dir / "settings.yaml"
        config_path.write_text("""
llm:
  provider: claude
  model: claude-opus-4-20250514

daemon:
  poll_interval: 120
  skip_low_priority: true
  confidence_threshold: 80

logging:
  level: DEBUG

notifications:
  enabled: true
  sound: false
""", encoding="utf-8")
        return config_path

    def test_load_config(self, config_file):
        """Test chargement de configuration."""
        loader = YamlConfigLoader(config_file)
        assert loader.load() is True

    def test_get_simple_value(self, config_file):
        """Test récupération valeur simple."""
        loader = YamlConfigLoader(config_file)
        loader.load()

        assert loader.get("llm.provider") == "claude"
        assert loader.get("daemon.poll_interval") == 120

    def test_get_nested_value(self, config_file):
        """Test récupération valeur imbriquée."""
        loader = YamlConfigLoader(config_file)
        loader.load()

        assert loader.get("logging.level") == "DEBUG"

    def test_get_default_value(self, config_file):
        """Test valeur par défaut si clé manquante."""
        loader = YamlConfigLoader(config_file)
        loader.load()

        assert loader.get("nonexistent.key", "default") == "default"
        assert loader.get("llm.unknown", 42) == 42

    def test_get_int(self, config_file):
        """Test récupération entier."""
        loader = YamlConfigLoader(config_file)
        loader.load()

        assert loader.get_int("daemon.poll_interval") == 120
        assert loader.get_int("daemon.confidence_threshold") == 80
        assert loader.get_int("nonexistent", 99) == 99

    def test_get_bool(self, config_file):
        """Test récupération booléen."""
        loader = YamlConfigLoader(config_file)
        loader.load()

        assert loader.get_bool("daemon.skip_low_priority") is True
        assert loader.get_bool("notifications.enabled") is True
        assert loader.get_bool("notifications.sound") is False
        assert loader.get_bool("nonexistent", True) is True

    def test_get_section(self, config_file):
        """Test récupération section entière."""
        loader = YamlConfigLoader(config_file)
        loader.load()

        daemon_section = loader.get_section("daemon")
        assert isinstance(daemon_section, dict)
        assert daemon_section["poll_interval"] == 120
        assert daemon_section["skip_low_priority"] is True

    def test_set_value(self, config_file):
        """Test modification valeur en mémoire."""
        loader = YamlConfigLoader(config_file)
        loader.load()

        loader.set("daemon.poll_interval", 300)
        assert loader.get("daemon.poll_interval") == 300

        loader.set("new.nested.value", "test")
        assert loader.get("new.nested.value") == "test"

    def test_to_dict(self, config_file):
        """Test conversion en dictionnaire."""
        loader = YamlConfigLoader(config_file)
        loader.load()

        config_dict = loader.to_dict()
        assert isinstance(config_dict, dict)
        assert "llm" in config_dict
        assert "daemon" in config_dict

    def test_save_config(self, temp_dir, config_file):
        """Test sauvegarde configuration."""
        loader = YamlConfigLoader(config_file)
        loader.load()
        loader.set("daemon.poll_interval", 180)

        new_file = temp_dir / "new_settings.yaml"
        assert loader.save(new_file) is True
        assert new_file.exists()

        # Recharger et vérifier
        new_loader = YamlConfigLoader(new_file)
        new_loader.load()
        assert new_loader.get("daemon.poll_interval") == 180

    def test_validate_valid_config(self, config_file):
        """Test validation config valide."""
        loader = YamlConfigLoader(config_file)
        loader.load()
        loader.set("llm.anthropic_api_key", "sk-ant-test")

        errors = loader.validate()
        assert len(errors) == 0

    def test_validate_invalid_config(self, temp_dir):
        """Test validation config invalide."""
        config_path = temp_dir / "invalid.yaml"
        config_path.write_text("""
llm:
  provider: claude
  # pas de clé API

daemon:
  poll_interval: 5
  confidence_threshold: 150
""", encoding="utf-8")

        loader = YamlConfigLoader(config_path)
        loader.load()
        errors = loader.validate()

        assert len(errors) > 0

    def test_file_not_found(self, temp_dir):
        """Test fichier non trouvé."""
        loader = YamlConfigLoader(temp_dir / "nonexistent.yaml")
        assert loader.load() is False

    def test_invalid_yaml(self, temp_dir):
        """Test YAML invalide."""
        config_path = temp_dir / "invalid.yaml"
        config_path.write_text("{ invalid: yaml: format", encoding="utf-8")

        loader = YamlConfigLoader(config_path)
        assert loader.load() is False

    def test_empty_yaml(self, temp_dir):
        """Test YAML vide."""
        config_path = temp_dir / "empty.yaml"
        config_path.write_text("", encoding="utf-8")

        loader = YamlConfigLoader(config_path)
        assert loader.load() is True
        assert loader.get("any.key", "default") == "default"


# ============================================================================
# TESTS VARIABLES D'ENVIRONNEMENT
# ============================================================================

class TestEnvVariableResolution:
    """Tests pour la résolution des variables d'environnement."""

    @pytest.fixture
    def temp_dir(self):
        """Crée un répertoire temporaire."""
        with TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_env_var_resolution(self, temp_dir):
        """Test résolution ${VAR}."""
        config_path = temp_dir / "settings.yaml"
        config_path.write_text("""
llm:
  api_key: ${TEST_API_KEY}
  provider: claude
""", encoding="utf-8")

        with patch.dict(os.environ, {"TEST_API_KEY": "sk-secret-key"}):
            loader = YamlConfigLoader(config_path)
            loader.load()

            assert loader.get("llm.api_key") == "sk-secret-key"

    def test_env_var_with_default(self, temp_dir):
        """Test résolution ${VAR:-default}."""
        config_path = temp_dir / "settings.yaml"
        config_path.write_text("""
daemon:
  interval: ${POLL_INTERVAL:-60}
  env_val: ${EXISTING_VAR:-fallback}
""", encoding="utf-8")

        with patch.dict(os.environ, {"EXISTING_VAR": "exists"}, clear=False):
            loader = YamlConfigLoader(config_path)
            loader.load()

            assert loader.get("daemon.interval") == "60"
            assert loader.get("daemon.env_val") == "exists"

    def test_env_var_not_found_no_default(self, temp_dir):
        """Test variable non trouvée sans défaut."""
        config_path = temp_dir / "settings.yaml"
        config_path.write_text("""
test:
  missing: ${MISSING_VAR}
""", encoding="utf-8")

        # Supprimer la variable si elle existe
        env = {k: v for k, v in os.environ.items() if k != "MISSING_VAR"}
        with patch.dict(os.environ, env, clear=True):
            loader = YamlConfigLoader(config_path)
            loader.load()

            assert loader.get("test.missing") == ""


# ============================================================================
# TESTS FONCTIONS UTILITAIRES
# ============================================================================

class TestUtilityFunctions:
    """Tests pour les fonctions utilitaires."""

    @pytest.fixture
    def temp_dir(self):
        """Crée un répertoire temporaire."""
        with TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_generate_default_config(self):
        """Test génération configuration par défaut."""
        config = generate_default_config()

        assert isinstance(config, dict)
        assert "llm" in config
        assert "daemon" in config
        assert "logging" in config
        assert "security" in config

        assert config["daemon"]["poll_interval"] == 60
        assert config["daemon"]["confidence_threshold"] == 70

    def test_create_default_config_file(self, temp_dir):
        """Test création fichier par défaut."""
        config_path = temp_dir / "config" / "settings.yaml"

        assert create_default_config_file(config_path) is True
        assert config_path.exists()

        # Vérifier le contenu
        loader = YamlConfigLoader(config_path)
        loader.load()
        assert loader.get("daemon.poll_interval") == 60

    def test_create_default_config_no_overwrite(self, temp_dir):
        """Test pas d'écrasement si fichier existe."""
        config_path = temp_dir / "settings.yaml"
        config_path.write_text("existing: content", encoding="utf-8")

        assert create_default_config_file(config_path) is False
        assert config_path.read_text() == "existing: content"


# ============================================================================
# TESTS TYPES SPÉCIAUX
# ============================================================================

class TestSpecialTypes:
    """Tests pour les types de données spéciaux."""

    @pytest.fixture
    def temp_dir(self):
        """Crée un répertoire temporaire."""
        with TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_list_values(self, temp_dir):
        """Test récupération listes."""
        config_path = temp_dir / "settings.yaml"
        config_path.write_text("""
categories:
  - URGENT
  - IMPORTANT
  - NORMAL

empty_list: []
""", encoding="utf-8")

        loader = YamlConfigLoader(config_path)
        loader.load()

        categories = loader.get_list("categories")
        assert len(categories) == 3
        assert "URGENT" in categories

        empty = loader.get_list("empty_list")
        assert len(empty) == 0

        missing = loader.get_list("nonexistent", ["default"])
        assert missing == ["default"]

    def test_get_float(self, temp_dir):
        """Test récupération flottant."""
        config_path = temp_dir / "settings.yaml"
        config_path.write_text("""
rates:
  multiplier: 2.5
  percentage: 80.5
""", encoding="utf-8")

        loader = YamlConfigLoader(config_path)
        loader.load()

        assert loader.get_float("rates.multiplier") == 2.5
        assert loader.get_float("rates.percentage") == 80.5
        assert loader.get_float("nonexistent", 1.0) == 1.0
