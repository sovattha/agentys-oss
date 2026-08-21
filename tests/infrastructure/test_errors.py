# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour le module errors (gestion d'erreurs explicites)."""


from app.infrastructure.errors import (
    ErrorCode,
    AgentysError,
    AuthenticationError,
    LLMError,
    EmailError,
    ConfigurationError,
    DatabaseError,
    NetworkError,
    RESOLUTIONS,
    get_resolution,
    format_error,
    log_error,
    classify_exception,
    wrap_exception,
)


# ============================================================================
# TESTS — ErrorCode Enum
# ============================================================================

class TestErrorCode:
    def test_auth_codes_exist(self):
        assert ErrorCode.AUTH_001.value == "AUTH_001"
        assert ErrorCode.AUTH_005.value == "AUTH_005"

    def test_llm_codes_exist(self):
        assert ErrorCode.LLM_001.value == "LLM_001"
        assert ErrorCode.LLM_006.value == "LLM_006"

    def test_email_codes_exist(self):
        assert ErrorCode.EMAIL_001.value == "EMAIL_001"

    def test_unknown_code(self):
        assert ErrorCode.UNKNOWN.value == "UNKNOWN"


# ============================================================================
# TESTS — Exceptions personnalisées
# ============================================================================

class TestAgentysError:
    def test_basic_creation(self):
        err = AgentysError("Something went wrong")
        assert err.message == "Something went wrong"
        assert err.code == ErrorCode.UNKNOWN
        assert err.details == {}
        assert err.cause is None

    def test_with_code(self):
        err = AgentysError("Token expired", code=ErrorCode.AUTH_001)
        assert err.code == ErrorCode.AUTH_001

    def test_with_details(self):
        err = AgentysError("fail", details={"file": "token.json"})
        assert err.details["file"] == "token.json"

    def test_with_cause(self):
        cause = ValueError("original")
        err = AgentysError("wrapped", cause=cause)
        assert err.cause is cause

    def test_str_format(self):
        err = AgentysError("Token expired", code=ErrorCode.AUTH_001)
        assert "[AUTH_001]" in str(err)
        assert "Token expired" in str(err)

    def test_to_dict(self):
        err = AgentysError(
            "fail", code=ErrorCode.LLM_001,
            details={"retry_after": 30},
            cause=RuntimeError("original"),
        )
        d = err.to_dict()
        assert d["code"] == "LLM_001"
        assert d["message"] == "fail"
        assert d["details"]["retry_after"] == 30
        assert "original" in d["cause"]

    def test_to_dict_no_cause(self):
        err = AgentysError("fail")
        d = err.to_dict()
        assert d["cause"] is None


class TestAuthenticationError:
    def test_default_code(self):
        err = AuthenticationError("expired")
        assert err.code == ErrorCode.AUTH_001

    def test_custom_code(self):
        err = AuthenticationError("bad creds", code=ErrorCode.AUTH_002)
        assert err.code == ErrorCode.AUTH_002

    def test_is_agentys_error(self):
        assert issubclass(AuthenticationError, AgentysError)


class TestLLMError:
    def test_default_code(self):
        err = LLMError("rate limited")
        assert err.code == ErrorCode.LLM_001


class TestEmailError:
    def test_default_code(self):
        err = EmailError("draft failed")
        assert err.code == ErrorCode.EMAIL_001


class TestConfigurationError:
    def test_default_code(self):
        err = ConfigurationError("missing env var")
        assert err.code == ErrorCode.CFG_001


class TestDatabaseError:
    def test_default_code(self):
        err = DatabaseError("locked")
        assert err.code == ErrorCode.DB_001


class TestNetworkError:
    def test_default_code(self):
        err = NetworkError("connection refused")
        assert err.code == ErrorCode.NET_001


# ============================================================================
# TESTS — Résolutions
# ============================================================================

class TestResolutions:
    def test_all_error_codes_have_resolutions(self):
        """Chaque code dans RESOLUTIONS doit avoir title et description."""
        for code, res in RESOLUTIONS.items():
            assert "title" in res, f"Missing title for {code}"
            assert "description" in res, f"Missing description for {code}"

    def test_get_resolution_known_code(self):
        res = get_resolution(ErrorCode.AUTH_001)
        assert res["title"] == "Token Gmail expiré"
        assert "steps" in res

    def test_get_resolution_unknown_fallback(self):
        res = get_resolution(ErrorCode.UNKNOWN)
        assert res["title"] == "Erreur inconnue"


# ============================================================================
# TESTS — format_error
# ============================================================================

class TestFormatError:
    def test_format_agentys_error(self):
        err = AuthenticationError("Token expired", code=ErrorCode.AUTH_001)
        output = format_error(err)
        assert "AUTH_001" in output
        assert "Token expired" in output
        assert "Token Gmail expiré" in output

    def test_format_with_details(self):
        err = AgentysError("fail", details={"file": "token.json"})
        output = format_error(err)
        assert "token.json" in output

    def test_format_with_cause(self):
        cause = RuntimeError("original error")
        err = AgentysError("wrapped", cause=cause)
        output = format_error(err)
        assert "original error" in output

    def test_format_without_resolution(self):
        err = AgentysError("simple")
        output = format_error(err, include_resolution=False)
        assert "Étapes de résolution" not in output

    def test_format_standard_exception(self):
        err = RuntimeError("standard error")
        output = format_error(err)
        assert "standard error" in output
        assert "Erreur inconnue" in output

    def test_format_includes_commands(self):
        err = AuthenticationError("expired", code=ErrorCode.AUTH_001)
        output = format_error(err)
        assert "rm token.json" in output

    def test_format_includes_doc_link(self):
        err = AuthenticationError("expired", code=ErrorCode.AUTH_001)
        output = format_error(err)
        assert "TROUBLESHOOTING" in output


# ============================================================================
# TESTS — classify_exception
# ============================================================================

class TestClassifyException:
    def test_expired_token(self):
        code = classify_exception(RuntimeError("Token expired"))
        assert code == ErrorCode.AUTH_001

    def test_invalid_token(self):
        code = classify_exception(RuntimeError("Token invalid"))
        assert code == ErrorCode.AUTH_001

    def test_unauthorized(self):
        code = classify_exception(RuntimeError("401 Unauthorized"))
        assert code == ErrorCode.AUTH_002

    def test_refresh_failed(self):
        code = classify_exception(RuntimeError("Refresh token failed"))
        assert code == ErrorCode.AUTH_003

    def test_permission_error(self):
        code = classify_exception(RuntimeError("Insufficient permission"))
        assert code == ErrorCode.AUTH_005

    def test_rate_limit(self):
        code = classify_exception(RuntimeError("Rate limit exceeded"))
        assert code == ErrorCode.LLM_001

    def test_429_status(self):
        code = classify_exception(RuntimeError("HTTP 429 Too Many Requests"))
        assert code == ErrorCode.LLM_001

    def test_overloaded(self):
        code = classify_exception(RuntimeError("API overloaded 529"))
        assert code == ErrorCode.LLM_002

    def test_api_key_invalid(self):
        code = classify_exception(RuntimeError("Invalid api_key"))
        assert code == ErrorCode.LLM_003

    def test_timeout(self):
        code = classify_exception(TimeoutError("Request timed out"))
        assert code == ErrorCode.LLM_004

    def test_connection_refused(self):
        code = classify_exception(ConnectionRefusedError("Connection refused"))
        assert code == ErrorCode.NET_001

    def test_dns_error(self):
        code = classify_exception(RuntimeError("DNS resolve failed"))
        assert code == ErrorCode.NET_002

    def test_ssl_error(self):
        code = classify_exception(RuntimeError("SSL certificate verify failed"))
        assert code == ErrorCode.NET_003

    def test_database_locked(self):
        code = classify_exception(RuntimeError("database is locked"))
        assert code == ErrorCode.DB_001

    def test_corrupt_database(self):
        code = classify_exception(RuntimeError("database corrupt"))
        assert code == ErrorCode.DB_002

    def test_unknown(self):
        code = classify_exception(RuntimeError("something random"))
        assert code == ErrorCode.UNKNOWN


# ============================================================================
# TESTS — wrap_exception
# ============================================================================

class TestWrapException:
    def test_wraps_standard_exception(self):
        original = ConnectionRefusedError("Connection refused")
        wrapped = wrap_exception(original)
        assert isinstance(wrapped, AgentysError)
        assert wrapped.code == ErrorCode.NET_001
        assert wrapped.cause is original

    def test_passthrough_agentys_error(self):
        original = LLMError("rate limited")
        wrapped = wrap_exception(original)
        assert wrapped is original

    def test_unknown_exception(self):
        original = ValueError("random")
        wrapped = wrap_exception(original)
        assert wrapped.code == ErrorCode.UNKNOWN


# ============================================================================
# TESTS — log_error
# ============================================================================

class TestLogError:
    def test_log_agentys_error(self):
        import logging
        test_logger = logging.getLogger("test_errors")
        err = LLMError("rate limited", code=ErrorCode.LLM_001)
        # Ne devrait pas lever d'exception
        log_error(err, logger=test_logger)

    def test_log_standard_error(self):
        err = RuntimeError("boom")
        log_error(err)  # Utilise le logger par défaut
