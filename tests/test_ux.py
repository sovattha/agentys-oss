# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour les modules UX (notifications, progression, erreurs).

pytest tests/test_ux.py -v
"""

from unittest.mock import patch

from app.infrastructure.notifications import (
    NotificationManager,
    NotificationConfig,
    NotificationType,
    FallbackNotifier,
)
from app.infrastructure.errors import (
    AgentysError,
    AuthenticationError,
    LLMError,
    EmailError,
    ConfigurationError,
    DatabaseError,
    NetworkError,
    ErrorCode,
    format_error,
    get_resolution,
    classify_exception,
    wrap_exception,
)


# ============================================================================
# TESTS NOTIFICATIONS
# ============================================================================

class TestNotificationConfig:
    """Tests pour NotificationConfig."""

    def test_default_config(self):
        """Config par défaut."""
        config = NotificationConfig()
        assert config.enabled is True
        assert config.sound is True
        assert config.timeout_seconds == 5
        assert config.app_name == "Agentys"

    def test_custom_config(self):
        """Config personnalisée."""
        config = NotificationConfig(
            enabled=False,
            sound=False,
            timeout_seconds=10,
        )
        assert config.enabled is False
        assert config.sound is False
        assert config.timeout_seconds == 10


class TestNotificationManager:
    """Tests pour NotificationManager."""

    def test_manager_creation(self):
        """Création du manager."""
        manager = NotificationManager()
        assert manager.config.enabled is True
        assert manager._notifier is not None

    def test_disabled_notifications(self):
        """Notifications désactivées."""
        config = NotificationConfig(enabled=False)
        manager = NotificationManager(config=config)
        result = manager.send("Test", "Message")
        assert result is False

    def test_draft_created_notification(self):
        """Notification brouillon créé."""
        config = NotificationConfig(enabled=True)
        manager = NotificationManager(config=config)

        with patch.object(manager._notifier, 'send', return_value=True) as mock_send:
            result = manager.draft_created("john@example.com", "Meeting Tomorrow")
            assert result is True
            mock_send.assert_called_once()
            args = mock_send.call_args
            assert "john@example.com" in args[0][1]  # message

    def test_error_notification(self):
        """Notification d'erreur."""
        config = NotificationConfig(enabled=True)
        manager = NotificationManager(config=config)

        with patch.object(manager._notifier, 'send', return_value=True) as mock_send:
            result = manager.error("Connection failed")
            assert result is True
            mock_send.assert_called_once()
            call_args = mock_send.call_args[0]
            assert call_args[2] == NotificationType.ERROR

    def test_budget_warning_notification(self):
        """Notification warning budget."""
        config = NotificationConfig(enabled=True)
        manager = NotificationManager(config=config)

        with patch.object(manager._notifier, 'send', return_value=True) as mock_send:
            result = manager.budget_warning(45.0, 50.0)
            assert result is True
            call_args = mock_send.call_args[0]
            assert "90%" in call_args[1]  # 45/50 = 90%
            assert call_args[2] == NotificationType.WARNING

    def test_callback_registration(self):
        """Enregistrement de callbacks."""
        manager = NotificationManager()
        callback_called = []

        def my_callback(title, message):
            callback_called.append((title, message))

        manager.register_callback(NotificationType.SUCCESS, my_callback)

        with patch.object(manager._notifier, 'send', return_value=True):
            manager.send("Test", "Message", NotificationType.SUCCESS)

        assert len(callback_called) == 1
        assert callback_called[0] == ("Test", "Message")


class TestFallbackNotifier:
    """Tests pour FallbackNotifier."""

    def test_fallback_send(self):
        """Envoi via fallback (log)."""
        notifier = FallbackNotifier()
        result = notifier.send("Test", "Message", NotificationType.INFO)
        assert result is True

    def test_fallback_all_types(self):
        """Test tous les types de notification."""
        notifier = FallbackNotifier()
        for ntype in NotificationType:
            result = notifier.send("Test", "Message", ntype)
            assert result is True


# ============================================================================
# TESTS PROGRESSION
# ============================================================================

class TestErrorCodes:
    """Tests pour les codes d'erreur."""

    def test_error_code_values(self):
        """Vérification des valeurs des codes."""
        assert ErrorCode.AUTH_001.value == "AUTH_001"
        assert ErrorCode.LLM_001.value == "LLM_001"
        assert ErrorCode.UNKNOWN.value == "UNKNOWN"


class TestAgentysError:
    """Tests pour AgentysError."""

    def test_error_creation(self):
        """Création d'une erreur."""
        error = AgentysError("Test error", code=ErrorCode.AUTH_001)
        assert error.message == "Test error"
        assert error.code == ErrorCode.AUTH_001

    def test_error_with_details(self):
        """Erreur avec détails."""
        error = AgentysError(
            "Test error",
            code=ErrorCode.LLM_001,
            details={"retry_after": 30},
        )
        assert error.details["retry_after"] == 30

    def test_error_with_cause(self):
        """Erreur avec cause."""
        cause = ValueError("Original error")
        error = AgentysError("Wrapped error", cause=cause)
        assert error.cause is cause

    def test_error_str(self):
        """Représentation string."""
        error = AgentysError("Test", code=ErrorCode.AUTH_001)
        assert "[AUTH_001]" in str(error)

    def test_error_to_dict(self):
        """Conversion en dictionnaire."""
        error = AgentysError(
            "Test",
            code=ErrorCode.LLM_002,
            details={"key": "value"},
        )
        d = error.to_dict()
        assert d["code"] == "LLM_002"
        assert d["message"] == "Test"
        assert d["details"]["key"] == "value"


class TestSpecificErrors:
    """Tests pour les erreurs spécifiques."""

    def test_authentication_error(self):
        """AuthenticationError."""
        error = AuthenticationError("Token expired")
        assert isinstance(error, AgentysError)
        assert error.code == ErrorCode.AUTH_001

    def test_llm_error(self):
        """LLMError."""
        error = LLMError("Rate limit", code=ErrorCode.LLM_001)
        assert isinstance(error, AgentysError)

    def test_email_error(self):
        """EmailError."""
        error = EmailError("Draft failed")
        assert isinstance(error, AgentysError)

    def test_configuration_error(self):
        """ConfigurationError."""
        error = ConfigurationError("Missing env var")
        assert isinstance(error, AgentysError)

    def test_database_error(self):
        """DatabaseError."""
        error = DatabaseError("Locked")
        assert isinstance(error, AgentysError)

    def test_network_error(self):
        """NetworkError."""
        error = NetworkError("Connection refused")
        assert isinstance(error, AgentysError)


class TestErrorResolution:
    """Tests pour la résolution d'erreurs."""

    def test_get_resolution(self):
        """Récupération de résolution."""
        resolution = get_resolution(ErrorCode.AUTH_001)
        assert "title" in resolution
        assert "description" in resolution
        assert "steps" in resolution

    def test_get_resolution_unknown(self):
        """Résolution pour erreur inconnue."""
        resolution = get_resolution(ErrorCode.UNKNOWN)
        assert resolution["title"] == "Erreur inconnue"

    def test_all_codes_have_resolution(self):
        """Tous les codes ont une résolution."""
        for code in ErrorCode:
            resolution = get_resolution(code)
            assert "title" in resolution
            assert "description" in resolution


class TestErrorFormatting:
    """Tests pour le formatage d'erreurs."""

    def test_format_basic_error(self):
        """Formatage d'erreur basique."""
        error = AgentysError("Test error", code=ErrorCode.AUTH_001)
        formatted = format_error(error)

        assert "[AUTH_001]" in formatted
        assert "Test error" in formatted
        assert "Token Gmail" in formatted  # Resolution title

    def test_format_with_details(self):
        """Formatage avec détails."""
        error = AgentysError(
            "Test",
            code=ErrorCode.LLM_001,
            details={"retry_after": 30},
        )
        formatted = format_error(error)

        assert "Détails" in formatted
        assert "retry_after" in formatted

    def test_format_with_cause(self):
        """Formatage avec cause."""
        cause = ValueError("Original")
        error = AgentysError("Wrapped", cause=cause)
        formatted = format_error(error)

        assert "Cause" in formatted
        assert "ValueError" in formatted

    def test_format_without_resolution(self):
        """Formatage sans résolution."""
        error = AgentysError("Test", code=ErrorCode.AUTH_001)
        formatted = format_error(error, include_resolution=False)

        assert "Étapes" not in formatted

    def test_format_standard_exception(self):
        """Formatage d'exception standard."""
        error = ValueError("Standard error")
        formatted = format_error(error)

        assert "Standard error" in formatted


class TestExceptionClassification:
    """Tests pour la classification d'exceptions."""

    def test_classify_token_expired(self):
        """Classification token expiré."""
        e = Exception("token expired")
        code = classify_exception(e)
        assert code == ErrorCode.AUTH_001

    def test_classify_unauthorized(self):
        """Classification 401."""
        e = Exception("HTTP 401 Unauthorized")
        code = classify_exception(e)
        assert code == ErrorCode.AUTH_002

    def test_classify_rate_limit(self):
        """Classification rate limit."""
        e = Exception("Rate limit exceeded, retry after 30s")
        code = classify_exception(e)
        assert code == ErrorCode.LLM_001

    def test_classify_overload(self):
        """Classification API overloaded."""
        e = Exception("API is overloaded (529)")
        code = classify_exception(e)
        assert code == ErrorCode.LLM_002

    def test_classify_connection_refused(self):
        """Classification connection refused."""
        e = Exception("Connection refused to localhost:11434")
        code = classify_exception(e)
        assert code == ErrorCode.NET_001

    def test_classify_database_locked(self):
        """Classification database locked."""
        e = Exception("database is locked")
        code = classify_exception(e)
        assert code == ErrorCode.DB_001

    def test_classify_unknown(self):
        """Classification erreur inconnue."""
        e = Exception("Some random error")
        code = classify_exception(e)
        assert code == ErrorCode.UNKNOWN


class TestWrapException:
    """Tests pour wrap_exception."""

    def test_wrap_standard_exception(self):
        """Wrapping d'exception standard."""
        original = ValueError("Test")
        wrapped = wrap_exception(original)

        assert isinstance(wrapped, AgentysError)
        assert wrapped.cause is original

    def test_wrap_already_wrapped(self):
        """Exception déjà wrappée."""
        original = AuthenticationError("Already wrapped")
        wrapped = wrap_exception(original)

        assert wrapped is original

    def test_wrap_with_classification(self):
        """Wrapping avec classification automatique."""
        original = Exception("database is locked")
        wrapped = wrap_exception(original)

        assert wrapped.code == ErrorCode.DB_001


# ============================================================================
# TESTS CONTEXT MANAGERS
# ============================================================================

