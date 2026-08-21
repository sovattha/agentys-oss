# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour app.domain.exceptions."""


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


# ── DomainError ──────────────────────────────────────────────────────────────

class TestDomainError:
    def test_message_and_code(self):
        err = DomainError("something broke")
        assert err.message == "something broke"
        assert err.code == "DOMAIN_ERROR"
        assert str(err) == "something broke"

    def test_custom_code(self):
        err = DomainError("oops", code="CUSTOM")
        assert err.code == "CUSTOM"

    def test_is_exception(self):
        assert issubclass(DomainError, Exception)


# ── ValidationError ──────────────────────────────────────────────────────────

class TestValidationError:
    def test_defaults(self):
        err = ValidationError("bad input")
        assert err.field == ""
        assert err.code == "VALIDATION_ERROR"
        assert err.message == "bad input"

    def test_with_field(self):
        err = ValidationError("too long", field="name")
        assert err.field == "name"

    def test_inherits_domain_error(self):
        assert issubclass(ValidationError, DomainError)

    def test_alias(self):
        assert DomainValidationError is ValidationError


# ── EmptyValueError ──────────────────────────────────────────────────────────

class TestEmptyValueError:
    def test_default_message(self):
        err = EmptyValueError("email")
        assert "email" in err.message
        assert "cannot be empty" in err.message
        assert err.field == "email"
        assert err.code == "EMPTY_VALUE"

    def test_custom_message(self):
        err = EmptyValueError("email", message="Email requis")
        assert err.message == "Email requis"


# ── InvalidBoundsError ───────────────────────────────────────────────────────

class TestInvalidBoundsError:
    def test_with_both_bounds(self):
        err = InvalidBoundsError("score", 150, min_val=0, max_val=100)
        assert err.value == 150
        assert err.min_val == 0
        assert err.max_val == 100
        assert "[0, 100]" in err.message
        assert "150" in err.message
        assert err.code == "INVALID_BOUNDS"

    def test_with_min_only(self):
        err = InvalidBoundsError("age", -1, min_val=0)
        assert ">= 0" in err.message

    def test_with_max_only(self):
        err = InvalidBoundsError("count", 999, max_val=50)
        assert "<= 50" in err.message

    def test_custom_message(self):
        err = InvalidBoundsError("x", 5, message="custom msg")
        assert err.message == "custom msg"

    def test_no_bounds(self):
        err = InvalidBoundsError("x", 5)
        assert "x must be" in err.message


# ── InvalidFormatError ───────────────────────────────────────────────────────

class TestInvalidFormatError:
    def test_basic(self):
        err = InvalidFormatError("email", "user@domain.com")
        assert "email" in err.message
        assert "user@domain.com" in err.message
        assert err.expected_format == "user@domain.com"
        assert err.code == "INVALID_FORMAT"

    def test_with_actual_value(self):
        err = InvalidFormatError("date", "YYYY-MM-DD", actual_value="not-a-date")
        assert "not-a-date" in err.message


# ── EntityNotFoundError ──────────────────────────────────────────────────────

class TestEntityNotFoundError:
    def test_message(self):
        err = EntityNotFoundError("Email", "abc-123")
        assert err.entity_type == "Email"
        assert err.entity_id == "abc-123"
        assert "Email" in err.message
        assert "abc-123" in err.message
        assert err.code == "NOT_FOUND"


# ── BusinessRuleViolationError ───────────────────────────────────────────────

class TestBusinessRuleViolationError:
    def test_default_message(self):
        err = BusinessRuleViolationError("max_retries_exceeded")
        assert err.rule == "max_retries_exceeded"
        assert "max_retries_exceeded" in err.message
        assert err.code == "BUSINESS_RULE_VIOLATION"

    def test_custom_message(self):
        err = BusinessRuleViolationError("limit", message="Too many")
        assert err.message == "Too many"


# ── ConcurrencyError ────────────────────────────────────────────────────────

class TestConcurrencyError:
    def test_message(self):
        err = ConcurrencyError("Draft", "draft-42")
        assert err.entity_type == "Draft"
        assert err.entity_id == "draft-42"
        assert "Draft" in err.message
        assert "draft-42" in err.message
        assert err.code == "CONCURRENCY_ERROR"


# ── LLM Errors ──────────────────────────────────────────────────────────────

class TestLLMError:
    def test_base(self):
        err = LLMError("fail", provider="claude")
        assert err.provider == "claude"
        assert err.code == "LLM_ERROR"

    def test_inherits_domain_error(self):
        assert issubclass(LLMError, DomainError)


class TestLLMAuthenticationError:
    def test_default_message(self):
        err = LLMAuthenticationError("claude")
        assert "Authentication failed" in err.message
        assert err.provider == "claude"
        assert err.code == "LLM_AUTH_ERROR"

    def test_custom_message(self):
        err = LLMAuthenticationError("ollama", message="Bad key")
        assert err.message == "Bad key"


class TestLLMBillingError:
    def test_default(self):
        err = LLMBillingError("claude")
        assert err.code == "LLM_BILLING_ERROR"
        assert "claude" in err.message


class TestLLMRateLimitError:
    def test_without_retry(self):
        err = LLMRateLimitError("claude")
        assert err.retry_after is None
        assert err.code == "LLM_RATE_LIMIT"

    def test_with_retry(self):
        err = LLMRateLimitError("claude", retry_after=30)
        assert err.retry_after == 30
        assert "30 seconds" in err.message


class TestLLMUnavailableError:
    def test_default(self):
        err = LLMUnavailableError("ollama")
        assert "unavailable" in err.message
        assert err.code == "LLM_UNAVAILABLE"


class TestLLMConnectionError:
    def test_without_url(self):
        err = LLMConnectionError("ollama")
        assert "Cannot connect" in err.message

    def test_with_url(self):
        err = LLMConnectionError("ollama", url="http://localhost:11434")
        assert "localhost:11434" in err.message
        assert err.url == "http://localhost:11434"
        assert err.code == "LLM_CONNECTION_ERROR"


class TestLLMTimeoutError:
    def test_without_seconds(self):
        err = LLMTimeoutError("claude")
        assert "timed out" in err.message
        assert err.timeout_seconds is None

    def test_with_seconds(self):
        err = LLMTimeoutError("claude", timeout_seconds=60)
        assert "60 seconds" in err.message
        assert err.timeout_seconds == 60
        assert err.code == "LLM_TIMEOUT"


class TestLLMContextLengthError:
    def test_without_tokens(self):
        err = LLMContextLengthError("claude")
        assert "Context length exceeded" in err.message

    def test_with_tokens(self):
        err = LLMContextLengthError("claude", max_tokens=100000, actual_tokens=150000)
        assert "100000" in err.message
        assert "150000" in err.message
        assert err.max_tokens == 100000
        assert err.actual_tokens == 150000
        assert err.code == "LLM_CONTEXT_LENGTH"


class TestLLMResponseError:
    def test_default(self):
        err = LLMResponseError("claude")
        assert "Invalid response" in err.message
        assert err.code == "LLM_RESPONSE_ERROR"


class TestLLMModelNotFoundError:
    def test_default(self):
        err = LLMModelNotFoundError("ollama", "gpt-5")
        assert err.model == "gpt-5"
        assert "gpt-5" in err.message
        assert err.code == "LLM_MODEL_NOT_FOUND"


# ── InsufficientPermissionError ──────────────────────────────────────────────

class TestInsufficientPermissionError:
    def test_message(self):
        err = InsufficientPermissionError("user-1", "delete_account")
        assert err.holder_id == "user-1"
        assert err.action == "delete_account"
        assert "user-1" in err.message
        assert "delete_account" in err.message
        assert err.code == "INSUFFICIENT_PERMISSION"


# ── Hierarchy checks ────────────────────────────────────────────────────────

class TestExceptionHierarchy:
    """Vérifie que la hiérarchie d'héritage est correcte."""

    def test_all_inherit_domain_error(self):
        subclasses = [
            ValidationError, EmptyValueError, InvalidBoundsError,
            InvalidFormatError, EntityNotFoundError,
            BusinessRuleViolationError, ConcurrencyError,
            LLMError, InsufficientPermissionError,
        ]
        for cls in subclasses:
            assert issubclass(cls, DomainError), f"{cls.__name__} should inherit DomainError"

    def test_validation_subtypes(self):
        for cls in [EmptyValueError, InvalidBoundsError, InvalidFormatError]:
            assert issubclass(cls, ValidationError)

    def test_llm_subtypes(self):
        llm_classes = [
            LLMAuthenticationError, LLMBillingError, LLMRateLimitError,
            LLMUnavailableError, LLMConnectionError, LLMTimeoutError,
            LLMContextLengthError, LLMResponseError, LLMModelNotFoundError,
        ]
        for cls in llm_classes:
            assert issubclass(cls, LLMError), f"{cls.__name__} should inherit LLMError"

    def test_catchable_as_exception(self):
        """Toutes les exceptions domain doivent être catchable via except Exception."""
        try:
            raise EntityNotFoundError("Test", "123")
        except Exception as e:
            assert "Test" in str(e)
