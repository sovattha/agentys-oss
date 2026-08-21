# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests edge cases pour les utilitaires de configuration app/config.py.

Ces tests vérifient:
- get_env_int avec valeurs invalides
- get_env_float avec valeurs invalides
- get_env_bool avec variations de valeurs
- validate_config edge cases
"""

import os

import pytest
from unittest.mock import patch

from app.config import (
    get_env,
    get_env_int,
    get_env_float,
    get_env_bool,
    get_email_content_storage_mode,
    get_ai_artifact_retention_days,
    get_pending_draft_active_retention_days,
    get_pending_draft_terminal_retention_days,
    should_persist_email_content,
    third_party_ai_training_allowed,
    validate_config,
    DaemonConfig,
    RetryConfig,
    CircuitBreakerConfig,
    RateLimitConfig,
    LoggingConfig,
    PROJECT_ROOT,
    APP_DIR,
    KNOWLEDGE_DIR,
    DATA_DIR,
    CONFIG_DIR,
    LOGS_DIR,
)


# ============================================================================
# TESTS - GET_ENV_INT EDGE CASES
# ============================================================================


class TestGetEnvInt:
    """Tests pour la fonction get_env_int."""

    @pytest.mark.parametrize(
        "env_value,default,expected,clear",
        [
            ("42", 0, 42, False),  # valid int
            ("0", 99, 0, False),  # zero
            ("-50", 0, -50, False),  # negative
            ("007", 0, 7, False),  # leading zeros
            ("9999999999999", 0, 9999999999999, False),  # very large
        ],
        ids=[
            "valid_int",
            "zero",
            "negative",
            "leading_zeros",
            "very_large_number",
        ],
    )
    def test_get_env_int_valid_values(self, env_value, default, expected, clear):
        """get_env_int convertit correctement les valeurs valides."""
        with patch.dict(os.environ, {"TEST_INT": env_value}, clear=clear):
            assert get_env_int("TEST_INT", default) == expected

    @pytest.mark.parametrize(
        "env_value,default",
        [
            ("not_a_number", 100),
            ("3.14", 0),  # float string not valid for int
            ("", 42),
            ("  ", 7),
        ],
        ids=[
            "invalid_string",
            "float_string",
            "empty_string",
            "whitespace",
        ],
    )
    def test_get_env_int_returns_default(self, env_value, default):
        """get_env_int retourne la valeur par défaut pour les valeurs invalides."""
        with patch.dict(os.environ, {"TEST_INT": env_value}):
            assert get_env_int("TEST_INT", default) == default

    def test_get_env_int_missing_key_returns_default(self):
        """get_env_int retourne la valeur par défaut si la clé est absente."""
        with patch.dict(os.environ, {}, clear=True):
            assert get_env_int("NONEXISTENT_KEY", 99) == 99


# ============================================================================
# TESTS - GET_ENV_FLOAT EDGE CASES
# ============================================================================


class TestGetEnvFloat:
    """Tests pour la fonction get_env_float."""

    @pytest.mark.parametrize(
        "env_value,default,expected",
        [
            ("3.14", 0.0, 3.14),
            ("42", 0.0, 42.0),  # int string converts to float
            ("-2.5", 0.0, -2.5),
            ("0.0", 99.9, 0.0),
            ("1.5e-3", 0.0, 0.0015),  # scientific notation
        ],
        ids=[
            "valid_float",
            "int_string",
            "negative",
            "zero",
            "scientific_notation",
        ],
    )
    def test_get_env_float_valid_values(self, env_value, default, expected):
        """get_env_float convertit correctement les valeurs valides."""
        with patch.dict(os.environ, {"TEST_FLOAT": env_value}):
            assert get_env_float("TEST_FLOAT", default) == pytest.approx(expected)

    @pytest.mark.parametrize(
        "env_value,default",
        [
            ("not_a_float", 1.0),
            ("", 5.5),
        ],
        ids=[
            "invalid_string",
            "empty_string",
        ],
    )
    def test_get_env_float_returns_default(self, env_value, default):
        """get_env_float retourne la valeur par défaut pour les valeurs invalides."""
        with patch.dict(os.environ, {"TEST_FLOAT": env_value}):
            assert get_env_float("TEST_FLOAT", default) == pytest.approx(default)

    def test_get_env_float_missing_key_returns_default(self):
        """get_env_float retourne la valeur par défaut si la clé est absente."""
        with patch.dict(os.environ, {}, clear=True):
            assert get_env_float("NONEXISTENT_KEY", 2.5) == pytest.approx(2.5)


# ============================================================================
# TESTS - GET_ENV_BOOL EDGE CASES
# ============================================================================


class TestGetEnvBool:
    """Tests pour la fonction get_env_bool."""

    @pytest.mark.parametrize(
        "env_value",
        ["true", "TRUE", "True", "1", "yes", "YES", "on", "ON"],
    )
    def test_get_env_bool_true_values(self, env_value):
        """get_env_bool reconnaît les valeurs true."""
        with patch.dict(os.environ, {"TEST_BOOL": env_value}):
            assert get_env_bool("TEST_BOOL", False) is True

    @pytest.mark.parametrize(
        "env_value",
        ["false", "FALSE", "0", "no", "off", "anything_else", "", "  "],
    )
    def test_get_env_bool_false_values(self, env_value):
        """get_env_bool retourne False pour les valeurs non-true."""
        with patch.dict(os.environ, {"TEST_BOOL": env_value}):
            assert get_env_bool("TEST_BOOL", True) is False

    @pytest.mark.parametrize(
        "default,expected",
        [(True, True), (False, False)],
    )
    def test_get_env_bool_missing_key_returns_default(self, default, expected):
        """get_env_bool retourne la valeur par défaut si la clé est absente."""
        with patch.dict(os.environ, {}, clear=True):
            assert get_env_bool("NONEXISTENT_KEY", default) is expected


class TestPendingDraftRetentionConfig:
    """Tests pour les TTL de brouillons persistés."""

    def test_defaults_are_30_days(self, monkeypatch):
        monkeypatch.delenv("AGENTYS_PENDING_DRAFT_ACTIVE_RETENTION_DAYS", raising=False)
        monkeypatch.delenv("AGENTYS_PENDING_DRAFT_TERMINAL_RETENTION_DAYS", raising=False)

        assert get_pending_draft_active_retention_days() == 30
        assert get_pending_draft_terminal_retention_days() == 30

    def test_values_are_clamped_to_at_least_one_day(self, monkeypatch):
        monkeypatch.setenv("AGENTYS_PENDING_DRAFT_ACTIVE_RETENTION_DAYS", "0")
        monkeypatch.setenv("AGENTYS_PENDING_DRAFT_TERMINAL_RETENTION_DAYS", "-7")

        assert get_pending_draft_active_retention_days() == 1
        assert get_pending_draft_terminal_retention_days() == 1


class TestAiArtifactRetentionConfig:
    """Tests pour la rétention des artefacts IA."""

    def test_default_is_90_days(self, monkeypatch):
        monkeypatch.delenv("AGENTYS_AI_ARTIFACT_RETENTION_DAYS", raising=False)
        assert get_ai_artifact_retention_days() == 90

    def test_value_is_clamped_to_at_least_one_day(self, monkeypatch):
        monkeypatch.setenv("AGENTYS_AI_ARTIFACT_RETENTION_DAYS", "0")
        assert get_ai_artifact_retention_days() == 1


# ============================================================================
# TESTS - GET_ENV EDGE CASES
# ============================================================================


class TestGetEnv:
    """Tests pour la fonction get_env."""

    @pytest.mark.parametrize(
        "env_value,default,expected",
        [
            ("test_value", "default", "test_value"),
            ("été 日本語 🎉", "", "été 日本語 🎉"),  # unicode
        ],
        ids=["simple_value", "unicode"],
    )
    def test_get_env_returns_value(self, env_value, default, expected):
        """get_env retourne la valeur de l'environnement."""
        with patch.dict(os.environ, {"TEST_VAR": env_value}):
            assert get_env("TEST_VAR", default) == expected

    def test_get_env_returns_default(self):
        """get_env retourne la valeur par défaut si clé absente."""
        with patch.dict(os.environ, {}, clear=True):
            assert get_env("NONEXISTENT", "my_default") == "my_default"

    def test_get_env_empty_default(self):
        """get_env avec défaut vide."""
        with patch.dict(os.environ, {}, clear=True):
            assert get_env("NONEXISTENT") == ""


# ============================================================================
# TESTS - VALIDATE_CONFIG EDGE CASES
# ============================================================================


class TestValidateConfig:
    """Tests pour validate_config."""

    def test_validate_config_returns_list(self):
        """validate_config retourne une liste."""
        result = validate_config(raise_on_error=False)
        assert isinstance(result, list)

    def test_validate_config_with_valid_config(self):
        """validate_config ne lève pas d'erreur avec config valide."""
        with patch.dict(
            os.environ, {"LLM_PROVIDER": "ollama", "EMAIL_PROVIDER_TYPE": "MOCK"}
        ):
            # Ne devrait pas lever d'exception
            validate_config(raise_on_error=False)

    def test_validate_config_invalid_email_provider(self):
        """validate_config détecte un provider email invalide."""
        import app.config as config_module

        original = config_module.EMAIL_PROVIDER_TYPE

        try:
            config_module.EMAIL_PROVIDER_TYPE = "INVALID_PROVIDER"
            errors = validate_config(raise_on_error=False)
            error_messages = " ".join(errors)
            assert (
                "EMAIL_PROVIDER_TYPE" in error_messages
                or "invalide" in error_messages.lower()
            )
        finally:
            config_module.EMAIL_PROVIDER_TYPE = original

    def test_email_content_storage_defaults_to_metadata_only(self):
        """Le cloud ne persiste pas les bodies sans opt-in legacy."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", None)
            assert get_email_content_storage_mode() == "metadata_only"
            assert should_persist_email_content() is False

    def test_email_content_storage_legacy_is_explicit(self):
        """Le cache complet legacy reste disponible seulement via env."""
        with patch.dict(
            os.environ,
            {"AGENTYS_EMAIL_CONTENT_STORAGE_MODE": "legacy_full_cache"},
        ):
            assert get_email_content_storage_mode() == "legacy_full_cache"
            assert should_persist_email_content() is True

    def test_validate_config_invalid_email_content_storage_mode(self):
        """validate_config rejette les modes de stockage inconnus."""
        with patch.dict(
            os.environ,
            {"AGENTYS_EMAIL_CONTENT_STORAGE_MODE": "full"},
        ):
            errors = validate_config(raise_on_error=False)

        assert "AGENTYS_EMAIL_CONTENT_STORAGE_MODE" in " ".join(errors)

    def test_validate_config_blocks_legacy_full_cache_in_production(self):
        """La prod ne peut pas activer le cache complet sans opt-in audit."""
        with patch.dict(
            os.environ,
            {
                "ENVIRONMENT": "production",
                "AGENTYS_EMAIL_CONTENT_STORAGE_MODE": "legacy_full_cache",
                "AGENTYS_ALLOW_LEGACY_EMAIL_CONTENT_CACHE": "false",
            },
        ):
            errors = validate_config(raise_on_error=False)

        assert "legacy_full_cache" in " ".join(errors)

    def test_third_party_ai_training_is_disabled_by_default(self):
        """Aucun fournisseur IA ne peut entraîner sur les données sans opt-in."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AGENTYS_ALLOW_THIRD_PARTY_AI_TRAINING", None)
            assert third_party_ai_training_allowed() is False

    def test_validate_config_blocks_third_party_ai_training_in_production(self):
        """La prod doit rester non-training pour les données utilisateur."""
        with patch.dict(
            os.environ,
            {
                "ENVIRONMENT": "production",
                "AGENTYS_ALLOW_THIRD_PARTY_AI_TRAINING": "true",
            },
        ):
            errors = validate_config(raise_on_error=False)

        assert "THIRD_PARTY_AI_TRAINING" in " ".join(errors)


# ============================================================================
# TESTS - DAEMON CONFIG EDGE CASES
# ============================================================================


class TestDaemonConfigEdgeCases:
    """Tests pour DaemonConfig."""

    def test_daemon_config_defaults(self):
        """DaemonConfig a des valeurs par défaut raisonnables."""
        config = DaemonConfig()

        assert config.poll_interval == 60
        assert config.skip_low_priority is True
        assert config.learning_interval == 50
        assert config.confidence_threshold == 70
        assert config.max_emails_per_poll == 50

    def test_daemon_config_custom_values(self):
        """DaemonConfig accepte des valeurs personnalisées."""
        config = DaemonConfig(
            poll_interval=30, skip_low_priority=True, confidence_threshold=80
        )

        assert config.poll_interval == 30
        assert config.skip_low_priority is True
        assert config.confidence_threshold == 80

    def test_daemon_config_frozen(self):
        """DaemonConfig est frozen (immutable)."""
        config = DaemonConfig()

        with pytest.raises(Exception):  # FrozenInstanceError
            config.poll_interval = 100


# ============================================================================
# TESTS - RETRY CONFIG EDGE CASES
# ============================================================================


class TestRetryConfigEdgeCases:
    """Tests pour RetryConfig."""

    def test_retry_config_defaults(self):
        """RetryConfig a des valeurs par défaut."""
        config = RetryConfig()

        assert config.max_attempts == 3
        assert config.backoff_factor == 2.0
        assert config.initial_delay == 1.0
        assert config.max_delay == 60.0

    def test_retry_config_frozen(self):
        """RetryConfig est frozen (immutable)."""
        config = RetryConfig()

        with pytest.raises(Exception):
            config.max_attempts = 10


# ============================================================================
# TESTS - CIRCUIT BREAKER CONFIG EDGE CASES
# ============================================================================


class TestCircuitBreakerConfigEdgeCases:
    """Tests pour CircuitBreakerConfig."""

    def test_circuit_breaker_config_defaults(self):
        """CircuitBreakerConfig a des valeurs par défaut."""
        config = CircuitBreakerConfig()

        assert config.failure_threshold == 5
        assert config.recovery_timeout == 60
        assert config.half_open_max_calls == 3

    def test_circuit_breaker_config_frozen(self):
        """CircuitBreakerConfig est frozen (immutable)."""
        config = CircuitBreakerConfig()

        with pytest.raises(Exception):
            config.failure_threshold = 100


# ============================================================================
# TESTS - RATE LIMIT CONFIG EDGE CASES
# ============================================================================


class TestRateLimitConfigEdgeCases:
    """Tests pour RateLimitConfig."""

    def test_rate_limit_config_defaults(self):
        """RateLimitConfig a des valeurs par défaut."""
        config = RateLimitConfig()

        assert config.claude_requests_per_minute == 50
        assert config.claude_tokens_per_minute == 100000
        assert config.gmail_requests_per_second == 10


# ============================================================================
# TESTS - LOGGING CONFIG EDGE CASES
# ============================================================================


class TestLoggingConfigEdgeCases:
    """Tests pour LoggingConfig."""

    def test_logging_config_defaults(self):
        """LoggingConfig a des valeurs par défaut."""
        config = LoggingConfig()

        assert config.level == "INFO"
        assert config.format_style == "standard"
        assert config.log_to_file is True
        assert config.log_to_console is True

    def test_logging_config_custom(self):
        """LoggingConfig accepte des valeurs personnalisées."""
        config = LoggingConfig(level="DEBUG", format_style="json", log_to_file=False)

        assert config.level == "DEBUG"
        assert config.format_style == "json"
        assert config.log_to_file is False


# ============================================================================
# TESTS - PATH CONSTANTS
# ============================================================================


class TestPathConstants:
    """Tests pour les constantes de chemin."""

    def test_project_root_exists(self):
        """PROJECT_ROOT existe."""
        assert PROJECT_ROOT.exists()

    def test_app_dir_exists(self):
        """APP_DIR existe."""
        assert APP_DIR.exists()

    def test_knowledge_dir_path(self):
        """KNOWLEDGE_DIR a le bon chemin."""
        expected = PROJECT_ROOT / "knowledge"
        assert KNOWLEDGE_DIR == expected

    def test_data_dir_is_created(self):
        """DATA_DIR est créé."""
        assert DATA_DIR.exists()

    def test_config_dir_is_created(self):
        """CONFIG_DIR est créé."""
        assert CONFIG_DIR.exists()

    def test_logs_dir_is_created(self):
        """LOGS_DIR est créé."""
        assert LOGS_DIR.exists()
