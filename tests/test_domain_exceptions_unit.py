# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour les exceptions de domaine."""

from app.domain.exceptions import (
    DomainError,
    ValidationError,
    EmptyValueError,
    InvalidBoundsError,
    InvalidFormatError,
    EntityNotFoundError,
    BusinessRuleViolationError,
    ConcurrencyError,
    LLMError,
    LLMAuthenticationError,
    LLMBillingError,
    LLMRateLimitError,
    LLMUnavailableError,
    LLMConnectionError,
    LLMTimeoutError,
    LLMContextLengthError,
    LLMResponseError,
    LLMModelNotFoundError,
    InsufficientPermissionError,
    DomainValidationError,
)


class TestDomainError:
    """Tests pour DomainError."""

    def test_message_and_code(self):
        err = DomainError("Something went wrong", "CUSTOM")
        assert err.message == "Something went wrong"
        assert err.code == "CUSTOM"
        assert str(err) == "Something went wrong"

    def test_default_code(self):
        err = DomainError("test")
        assert err.code == "DOMAIN_ERROR"

    def test_is_exception(self):
        err = DomainError("test")
        assert isinstance(err, Exception)


class TestValidationError:
    """Tests pour ValidationError."""

    def test_with_field(self):
        err = ValidationError("Invalid email", field="email")
        assert err.field == "email"
        assert err.code == "VALIDATION_ERROR"

    def test_default_field_empty(self):
        err = ValidationError("Error")
        assert err.field == ""

    def test_inherits_domain_error(self):
        err = ValidationError("test")
        assert isinstance(err, DomainError)


class TestEmptyValueError:
    """Tests pour EmptyValueError."""

    def test_default_message(self):
        err = EmptyValueError("name")
        assert "name" in str(err)
        assert "cannot be empty" in str(err)
        assert err.code == "EMPTY_VALUE"

    def test_custom_message(self):
        err = EmptyValueError("name", "Name is required")
        assert str(err) == "Name is required"

    def test_field(self):
        err = EmptyValueError("email")
        assert err.field == "email"


class TestInvalidBoundsError:
    """Tests pour InvalidBoundsError."""

    def test_min_and_max(self):
        err = InvalidBoundsError("score", 150, min_val=0, max_val=100)
        assert err.field == "score"
        assert err.value == 150
        assert err.min_val == 0
        assert err.max_val == 100
        assert "[0, 100]" in str(err)
        assert "150" in str(err)

    def test_min_only(self):
        err = InvalidBoundsError("age", -1, min_val=0)
        assert ">= 0" in str(err)

    def test_max_only(self):
        err = InvalidBoundsError("count", 200, max_val=100)
        assert "<= 100" in str(err)

    def test_custom_message(self):
        err = InvalidBoundsError("x", 0, message="Custom bounds error")
        assert str(err) == "Custom bounds error"

    def test_inherits_validation_error(self):
        err = InvalidBoundsError("x", 0)
        assert isinstance(err, ValidationError)
        assert err.code == "INVALID_BOUNDS"


class TestInvalidFormatError:
    """Tests pour InvalidFormatError."""

    def test_expected_format(self):
        err = InvalidFormatError("email", "user@domain.com", "not-an-email")
        assert err.expected_format == "user@domain.com"
        assert err.actual_value == "not-an-email"
        assert "user@domain.com" in str(err)
        assert "not-an-email" in str(err)

    def test_without_actual_value(self):
        err = InvalidFormatError("date", "YYYY-MM-DD")
        assert err.actual_value == ""
        assert "YYYY-MM-DD" in str(err)

    def test_code(self):
        err = InvalidFormatError("x", "format")
        assert err.code == "INVALID_FORMAT"


class TestEntityNotFoundError:
    """Tests pour EntityNotFoundError."""

    def test_entity_info(self):
        err = EntityNotFoundError("Email", "abc-123")
        assert err.entity_type == "Email"
        assert err.entity_id == "abc-123"
        assert "Email" in str(err)
        assert "abc-123" in str(err)
        assert err.code == "NOT_FOUND"


class TestBusinessRuleViolationError:
    """Tests pour BusinessRuleViolationError."""

    def test_default_message(self):
        err = BusinessRuleViolationError("max_retries_exceeded")
        assert err.rule == "max_retries_exceeded"
        assert "max_retries_exceeded" in str(err)
        assert err.code == "BUSINESS_RULE_VIOLATION"

    def test_custom_message(self):
        err = BusinessRuleViolationError("rule", "Custom message")
        assert str(err) == "Custom message"


class TestConcurrencyError:
    """Tests pour ConcurrencyError."""

    def test_concurrency_info(self):
        err = ConcurrencyError("Draft", "d-123")
        assert err.entity_type == "Draft"
        assert err.entity_id == "d-123"
        assert "Draft" in str(err)
        assert "d-123" in str(err)
        assert err.code == "CONCURRENCY_ERROR"


class TestLLMErrors:
    """Tests pour les exceptions LLM."""

    def test_llm_error_base(self):
        err = LLMError("LLM failed", "claude")
        assert err.provider == "claude"
        assert err.code == "LLM_ERROR"

    def test_llm_authentication_error(self):
        err = LLMAuthenticationError("claude")
        assert "Authentication" in str(err) or "claude" in str(err)
        assert err.code == "LLM_AUTH_ERROR"

    def test_llm_billing_error(self):
        err = LLMBillingError("claude")
        assert err.provider == "claude"
        assert err.code == "LLM_BILLING_ERROR"

    def test_llm_rate_limit_error(self):
        err = LLMRateLimitError("claude", retry_after=30)
        assert err.retry_after == 30
        assert "30" in str(err)
        assert err.code == "LLM_RATE_LIMIT"

    def test_llm_rate_limit_error_no_retry(self):
        err = LLMRateLimitError("claude")
        assert err.retry_after is None

    def test_llm_unavailable_error(self):
        err = LLMUnavailableError("ollama")
        assert err.provider == "ollama"
        assert err.code == "LLM_UNAVAILABLE"

    def test_llm_connection_error(self):
        err = LLMConnectionError("ollama", url="http://localhost:11434")
        assert err.url == "http://localhost:11434"
        assert err.code == "LLM_CONNECTION_ERROR"

    def test_llm_connection_error_no_url(self):
        err = LLMConnectionError("claude")
        assert err.url == ""

    def test_llm_timeout_error(self):
        err = LLMTimeoutError("claude", timeout_seconds=60)
        assert err.timeout_seconds == 60
        assert "60" in str(err)
        assert err.code == "LLM_TIMEOUT"

    def test_llm_context_length_error(self):
        err = LLMContextLengthError("claude", max_tokens=200000, actual_tokens=250000)
        assert err.max_tokens == 200000
        assert err.actual_tokens == 250000
        assert err.code == "LLM_CONTEXT_LENGTH"

    def test_llm_response_error(self):
        err = LLMResponseError("claude")
        assert err.provider == "claude"
        assert err.code == "LLM_RESPONSE_ERROR"

    def test_llm_model_not_found_error(self):
        err = LLMModelNotFoundError("ollama", "nonexistent:latest")
        assert err.model == "nonexistent:latest"
        assert err.code == "LLM_MODEL_NOT_FOUND"


class TestInsufficientPermissionError:
    """Tests pour InsufficientPermissionError."""

    def test_permission_info(self):
        err = InsufficientPermissionError("user-123", "delete_email")
        assert err.holder_id == "user-123"
        assert err.action == "delete_email"
        assert "user-123" in str(err)
        assert "delete_email" in str(err)
        assert err.code == "INSUFFICIENT_PERMISSION"


class TestDomainValidationErrorAlias:
    """Tests pour l'alias DomainValidationError."""

    def test_is_same_as_validation_error(self):
        assert DomainValidationError is ValidationError
