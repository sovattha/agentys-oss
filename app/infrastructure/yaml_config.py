# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Configuration YAML alternative pour Agentys.

Ce module permet de charger la configuration depuis un fichier YAML,
offrant une alternative au fichier .env.

Usage:
    from app.infrastructure.yaml_config import YamlConfigLoader, load_yaml_config

    # Charger depuis un fichier
    config = load_yaml_config("config/settings.yaml")

    # Accéder aux valeurs
    api_key = config.get("anthropic_api_key")
    poll_interval = config.get("daemon.poll_interval", 60)
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
import logging

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

from app.config import CONFIG_DIR


# ============================================================================
# CONFIGURATION
# ============================================================================

YAML_CONFIG_FILE = CONFIG_DIR / "settings.yaml"
YAML_CONFIG_SCHEMA_FILE = CONFIG_DIR / "settings.schema.yaml"


# ============================================================================
# LOADER YAML
# ============================================================================

@dataclass
class ConfigValue:
    """Représente une valeur de configuration avec métadonnées."""
    value: Any
    source: str  # "yaml", "env", "default"
    path: str    # Chemin dans la config (ex: "daemon.poll_interval")


class YamlConfigLoader:
    """
    Chargeur de configuration YAML avec support pour:
    - Variables d'environnement (${VAR})
    - Valeurs par défaut
    - Validation de schéma
    - Héritage de configuration
    """

    def __init__(self, config_file: Optional[Path] = None):
        """
        Initialise le loader de configuration.

        Args:
            config_file: Chemin vers le fichier YAML (optionnel)
        """
        self.config_file = config_file or YAML_CONFIG_FILE
        self._config: Dict[str, Any] = {}
        self._sources: Dict[str, str] = {}  # Garde trace de la source de chaque valeur
        self._loaded = False
        self.logger = logging.getLogger(__name__)

        if not YAML_AVAILABLE:
            self.logger.warning("PyYAML non installé - configuration YAML désactivée")

    def load(self) -> bool:
        """
        Charge la configuration depuis le fichier YAML.

        Returns:
            True si le chargement a réussi, False sinon
        """
        if not YAML_AVAILABLE:
            return False

        if not self.config_file.exists():
            self.logger.debug(f"Fichier config YAML non trouvé: {self.config_file}")
            return False

        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                raw_config = yaml.safe_load(f)

            if raw_config is None:
                raw_config = {}

            # Résoudre les variables d'environnement
            self._config = self._resolve_env_vars(raw_config)
            self._loaded = True

            self.logger.info(f"Configuration YAML chargée depuis {self.config_file}")
            return True

        except yaml.YAMLError as e:
            self.logger.error(f"Erreur de parsing YAML: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Erreur lors du chargement YAML: {e}")
            return False

    def get(self, path: str, default: Any = None) -> Any:
        """
        Récupère une valeur de configuration par son chemin.

        Args:
            path: Chemin vers la valeur (ex: "daemon.poll_interval")
            default: Valeur par défaut si non trouvée

        Returns:
            La valeur de configuration
        """
        if not self._loaded:
            self.load()

        keys = path.split(".")
        value = self._config

        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
                if value is None:
                    return default
            else:
                return default

        return value if value is not None else default

    def get_int(self, path: str, default: int = 0) -> int:
        """Récupère une valeur entière."""
        try:
            return int(self.get(path, default))
        except (TypeError, ValueError):
            return default

    def get_float(self, path: str, default: float = 0.0) -> float:
        """Récupère une valeur flottante."""
        try:
            return float(self.get(path, default))
        except (TypeError, ValueError):
            return default

    def get_bool(self, path: str, default: bool = False) -> bool:
        """Récupère une valeur booléenne."""
        value = self.get(path, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes", "on")
        return bool(value)

    def get_list(self, path: str, default: Optional[List] = None) -> List:
        """Récupère une liste."""
        value = self.get(path, default or [])
        if isinstance(value, list):
            return value
        return default or []

    def get_section(self, section: str) -> Dict[str, Any]:
        """Récupère une section entière de la configuration."""
        value = self.get(section, {})
        return value if isinstance(value, dict) else {}

    def set(self, path: str, value: Any) -> None:
        """
        Définit une valeur de configuration (en mémoire uniquement).

        Args:
            path: Chemin vers la valeur
            value: Nouvelle valeur
        """
        keys = path.split(".")
        config = self._config

        for key in keys[:-1]:
            if key not in config or not isinstance(config[key], dict):
                config[key] = {}
            config = config[key]

        config[keys[-1]] = value
        self._sources[path] = "runtime"

    def to_dict(self) -> Dict[str, Any]:
        """Retourne la configuration complète en dictionnaire."""
        if not self._loaded:
            self.load()
        return self._config.copy()

    def save(self, file_path: Optional[Path] = None) -> bool:
        """
        Sauvegarde la configuration dans un fichier YAML.

        Args:
            file_path: Chemin de destination (utilise config_file par défaut)

        Returns:
            True si la sauvegarde a réussi
        """
        if not YAML_AVAILABLE:
            return False

        target = file_path or self.config_file

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, 'w', encoding='utf-8') as f:
                yaml.dump(self._config, f, default_flow_style=False, allow_unicode=True)
            return True
        except Exception as e:
            self.logger.error(f"Erreur lors de la sauvegarde YAML: {e}")
            return False

    def validate(self, schema: Optional[Dict] = None) -> List[str]:
        """
        Valide la configuration contre un schéma.

        Args:
            schema: Schéma de validation (optionnel)

        Returns:
            Liste des erreurs de validation
        """
        errors = []

        # Validation basique
        required_if_claude = ["anthropic_api_key"]
        if self.get("llm.provider", "claude").lower() == "claude":
            for key in required_if_claude:
                if not self.get(f"llm.{key}"):
                    errors.append(f"llm.{key} requis pour le provider Claude")

        # Validation des plages de valeurs
        poll_interval = self.get_int("daemon.poll_interval", 60)
        if poll_interval < 10:
            errors.append("daemon.poll_interval doit être >= 10")

        confidence = self.get_int("daemon.confidence_threshold", 70)
        if not 0 <= confidence <= 100:
            errors.append("daemon.confidence_threshold doit être entre 0 et 100")

        return errors

    def _resolve_env_vars(self, config: Any, path: str = "") -> Any:
        """
        Résout les variables d'environnement dans la configuration.

        Supporte le format ${VAR} et ${VAR:-default}
        """
        if isinstance(config, dict):
            return {
                k: self._resolve_env_vars(v, f"{path}.{k}" if path else k)
                for k, v in config.items()
            }
        elif isinstance(config, list):
            return [self._resolve_env_vars(item, path) for item in config]
        elif isinstance(config, str):
            return self._resolve_string_env_vars(config)
        else:
            return config

    def _resolve_string_env_vars(self, value: str) -> str:
        """Résout les variables d'environnement dans une chaîne."""
        import re

        # Pattern: ${VAR} ou ${VAR:-default}
        pattern = r'\$\{([^}:]+)(?::-([^}]*))?\}'

        def replace(match):
            var_name = match.group(1)
            default = match.group(2) or ""
            return os.getenv(var_name, default)

        return re.sub(pattern, replace, value)


# ============================================================================
# FONCTIONS UTILITAIRES
# ============================================================================

_yaml_config: Optional[YamlConfigLoader] = None


def load_yaml_config(config_file: Optional[Path] = None) -> YamlConfigLoader:
    """
    Charge et retourne la configuration YAML.

    Args:
        config_file: Chemin vers le fichier YAML (optionnel)

    Returns:
        Instance de YamlConfigLoader
    """
    global _yaml_config

    if _yaml_config is None or config_file:
        _yaml_config = YamlConfigLoader(config_file)
        _yaml_config.load()

    return _yaml_config


def get_yaml_config() -> YamlConfigLoader:
    """Retourne l'instance singleton de la configuration YAML."""
    return load_yaml_config()


def generate_default_config() -> Dict[str, Any]:
    """
    Génère une configuration par défaut.

    Returns:
        Dictionnaire de configuration par défaut
    """
    return {
        "llm": {
            "provider": "claude",
            "anthropic_api_key": "${ANTHROPIC_API_KEY}",
            "model": "claude-opus-4-7",
            "model_fast": "claude-sonnet-4-6",
        },
        "email": {
            "provider": "gmail",
            "credentials_path": "credentials.json",
            "token_path": "token.json",
        },
        "daemon": {
            "poll_interval": 60,
            "skip_low_priority": False,
            "learning_interval": 50,
            "confidence_threshold": 70,
            "max_emails_per_poll": 50,
        },
        "retry": {
            "max_attempts": 3,
            "backoff_factor": 2.0,
            "initial_delay": 1.0,
            "max_delay": 60.0,
        },
        "logging": {
            "level": "INFO",
            "format": "standard",
            "to_file": True,
            "to_console": True,
        },
        "security": {
            "data_retention_days": 90,
            "encryption_enabled": True,
        },
        "costs": {
            "monthly_budget_usd": 50.0,
            "alert_threshold": 0.8,
        },
        "notifications": {
            "enabled": True,
            "sound": True,
        },
    }


def create_default_config_file(file_path: Optional[Path] = None) -> bool:
    """
    Crée un fichier de configuration par défaut.

    Args:
        file_path: Chemin de destination

    Returns:
        True si la création a réussi
    """
    if not YAML_AVAILABLE:
        return False

    target = file_path or YAML_CONFIG_FILE

    if target.exists():
        return False  # Ne pas écraser

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, 'w', encoding='utf-8') as f:
            yaml.dump(
                generate_default_config(),
                f,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False
            )
        return True
    except Exception:
        return False
