# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour les exceptions du domaine.

pytest tests/test_domain_exceptions.py -v
"""


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
    """Tests pour DomainError (classe de base)."""

    def test_create_with_message(self):
        """DomainError créé avec message."""
        err = DomainError("Something went wrong")

        assert str(err) == "Something went wrong"
        assert err.message == "Something went wrong"
        assert err.code == "DOMAIN_ERROR"

    def test_create_with_custom_code(self):
        """DomainError avec code personnalisé."""
        err = DomainError("Error message", code="CUSTOM_CODE")

        assert err.code == "CUSTOM_CODE"

    def test_is_exception(self):
        """DomainError est une exception."""
        err = DomainError("test")
        assert isinstance(err, Exception)


class TestValidationError:
    """Tests pour ValidationError."""

    def test_create_with_message_only(self):
        """ValidationError avec message seul."""
        err = ValidationError("Invalid data")

        assert str(err) == "Invalid data"
        assert err.field == ""
        assert err.code == "VALIDATION_ERROR"

    def test_create_with_field(self):
        """ValidationError avec champ spécifié."""
        err = ValidationError("Invalid value", field="email")

        assert err.field == "email"

    def test_create_with_custom_code(self):
        """ValidationError avec code personnalisé."""
        err = ValidationError("Error", field="name", code="CUSTOM")

        assert err.code == "CUSTOM"

    def test_inherits_from_domain_error(self):
        """ValidationError hérite de DomainError."""
        err = ValidationError("test")
        assert isinstance(err, DomainError)


class TestEmptyValueError:
    """Tests pour EmptyValueError."""

    def test_create_with_field(self):
        """EmptyValueError avec champ seul."""
        err = EmptyValueError("username")

        assert err.field == "username"
        assert err.code == "EMPTY_VALUE"
        assert "username cannot be empty" in str(err)

    def test_create_with_custom_message(self):
        """EmptyValueError avec message personnalisé."""
        err = EmptyValueError("email", message="L'email est requis")

        assert str(err) == "L'email est requis"
        assert err.field == "email"

    def test_inherits_from_validation_error(self):
        """EmptyValueError hérite de ValidationError."""
        err = EmptyValueError("test")
        assert isinstance(err, ValidationError)


class TestInvalidBoundsError:
    """Tests pour InvalidBoundsError."""

    def test_create_with_min_and_max(self):
        """InvalidBoundsError avec min et max."""
        err = InvalidBoundsError("age", value=150, min_val=0, max_val=120)

        assert err.field == "age"
        assert err.value == 150
        assert err.min_val == 0
        assert err.max_val == 120
        assert err.code == "INVALID_BOUNDS"
        assert "[0, 120]" in str(err)
        assert "150" in str(err)

    def test_create_with_min_only(self):
        """InvalidBoundsError avec min seul."""
        err = InvalidBoundsError("count", value=-5, min_val=0)

        assert ">= 0" in str(err)
        assert "-5" in str(err)

    def test_create_with_max_only(self):
        """InvalidBoundsError avec max seul."""
        err = InvalidBoundsError("percentage", value=150, max_val=100)

        assert "<= 100" in str(err)
        assert "150" in str(err)

    def test_create_with_custom_message(self):
        """InvalidBoundsError avec message personnalisé."""
        err = InvalidBoundsError("score", value=200, message="Score invalide")

        assert str(err) == "Score invalide"

    def test_inherits_from_validation_error(self):
        """InvalidBoundsError hérite de ValidationError."""
        err = InvalidBoundsError("test", value=0)
        assert isinstance(err, ValidationError)


class TestInvalidFormatError:
    """Tests pour InvalidFormatError."""

    def test_create_with_expected_format(self):
        """InvalidFormatError avec format attendu."""
        err = InvalidFormatError("email", expected_format="user@domain.com")

        assert err.field == "email"
        assert err.expected_format == "user@domain.com"
        assert err.code == "INVALID_FORMAT"
        assert "user@domain.com" in str(err)

    def test_create_with_actual_value(self):
        """InvalidFormatError avec valeur actuelle."""
        err = InvalidFormatError("date", expected_format="YYYY-MM-DD", actual_value="2024/01/15")

        assert err.actual_value == "2024/01/15"
        assert "2024/01/15" in str(err)

    def test_inherits_from_validation_error(self):
        """InvalidFormatError hérite de ValidationError."""
        err = InvalidFormatError("test", expected_format="format")
        assert isinstance(err, ValidationError)


class TestEntityNotFoundError:
    """Tests pour EntityNotFoundError."""

    def test_create(self):
        """EntityNotFoundError avec type et id."""
        err = EntityNotFoundError("Email", "abc123")

        assert err.entity_type == "Email"
        assert err.entity_id == "abc123"
        assert err.code == "NOT_FOUND"
        assert "Email" in str(err)
        assert "abc123" in str(err)

    def test_inherits_from_domain_error(self):
        """EntityNotFoundError hérite de DomainError."""
        err = EntityNotFoundError("Entity", "id")
        assert isinstance(err, DomainError)


class TestBusinessRuleViolationError:
    """Tests pour BusinessRuleViolationError."""

    def test_create_with_rule(self):
        """BusinessRuleViolationError avec règle."""
        err = BusinessRuleViolationError("MAX_EMAILS_PER_DAY")

        assert err.rule == "MAX_EMAILS_PER_DAY"
        assert err.code == "BUSINESS_RULE_VIOLATION"
        assert "MAX_EMAILS_PER_DAY" in str(err)

    def test_create_with_custom_message(self):
        """BusinessRuleViolationError avec message personnalisé."""
        err = BusinessRuleViolationError("LIMIT", message="Limite atteinte")

        assert str(err) == "Limite atteinte"

    def test_inherits_from_domain_error(self):
        """BusinessRuleViolationError hérite de DomainError."""
        err = BusinessRuleViolationError("rule")
        assert isinstance(err, DomainError)


class TestConcurrencyError:
    """Tests pour ConcurrencyError."""

    def test_create(self):
        """ConcurrencyError avec type et id."""
        err = ConcurrencyError("Draft", "draft-123")

        assert err.entity_type == "Draft"
        assert err.entity_id == "draft-123"
        assert err.code == "CONCURRENCY_ERROR"
        assert "Draft" in str(err)
        assert "draft-123" in str(err)

    def test_inherits_from_domain_error(self):
        """ConcurrencyError hérite de DomainError."""
        err = ConcurrencyError("Entity", "id")
        assert isinstance(err, DomainError)


class TestLLMError:
    """Tests pour LLMError (classe de base LLM)."""

    def test_create_with_message(self):
        """LLMError avec message."""
        err = LLMError("API error")

        assert str(err) == "API error"
        assert err.provider == ""
        assert err.code == "LLM_ERROR"

    def test_create_with_provider(self):
        """LLMError avec provider."""
        err = LLMError("Error", provider="claude")

        assert err.provider == "claude"

    def test_inherits_from_domain_error(self):
        """LLMError hérite de DomainError."""
        err = LLMError("test")
        assert isinstance(err, DomainError)


class TestLLMAuthenticationError:
    """Tests pour LLMAuthenticationError."""

    def test_create_with_provider(self):
        """LLMAuthenticationError avec provider."""
        err = LLMAuthenticationError("claude")

        assert err.provider == "claude"
        assert err.code == "LLM_AUTH_ERROR"
        assert "claude" in str(err)
        assert "Authentication failed" in str(err)

    def test_create_with_custom_message(self):
        """LLMAuthenticationError avec message personnalisé."""
        err = LLMAuthenticationError("ollama", message="Clé API invalide")

        assert str(err) == "Clé API invalide"

    def test_inherits_from_llm_error(self):
        """LLMAuthenticationError hérite de LLMError."""
        err = LLMAuthenticationError("provider")
        assert isinstance(err, LLMError)


class TestLLMRateLimitError:
    """Tests pour LLMRateLimitError."""

    def test_create_with_provider(self):
        """LLMRateLimitError avec provider."""
        err = LLMRateLimitError("claude")

        assert err.provider == "claude"
        assert err.retry_after is None
        assert err.code == "LLM_RATE_LIMIT"
        assert "Rate limit" in str(err)

    def test_create_with_retry_after(self):
        """LLMRateLimitError avec retry_after."""
        err = LLMRateLimitError("claude", retry_after=60)

        assert err.retry_after == 60
        assert "60 seconds" in str(err)

    def test_create_with_custom_message(self):
        """LLMRateLimitError avec message personnalisé."""
        err = LLMRateLimitError("ollama", message="Trop de requêtes")

        assert str(err) == "Trop de requêtes"

    def test_inherits_from_llm_error(self):
        """LLMRateLimitError hérite de LLMError."""
        err = LLMRateLimitError("provider")
        assert isinstance(err, LLMError)


class TestLLMUnavailableError:
    """Tests pour LLMUnavailableError."""

    def test_create_with_provider(self):
        """LLMUnavailableError avec provider."""
        err = LLMUnavailableError("claude")

        assert err.provider == "claude"
        assert err.code == "LLM_UNAVAILABLE"
        assert "unavailable" in str(err)

    def test_create_with_custom_message(self):
        """LLMUnavailableError avec message personnalisé."""
        err = LLMUnavailableError("ollama", message="Service en maintenance")

        assert str(err) == "Service en maintenance"

    def test_inherits_from_llm_error(self):
        """LLMUnavailableError hérite de LLMError."""
        err = LLMUnavailableError("provider")
        assert isinstance(err, LLMError)


class TestLLMConnectionError:
    """Tests pour LLMConnectionError."""

    def test_create_with_provider(self):
        """LLMConnectionError avec provider."""
        err = LLMConnectionError("ollama")

        assert err.provider == "ollama"
        assert err.url == ""
        assert err.code == "LLM_CONNECTION_ERROR"
        assert "Cannot connect" in str(err)

    def test_create_with_url(self):
        """LLMConnectionError avec URL."""
        err = LLMConnectionError("ollama", url="http://localhost:11434")

        assert err.url == "http://localhost:11434"
        assert "http://localhost:11434" in str(err)

    def test_create_with_custom_message(self):
        """LLMConnectionError avec message personnalisé."""
        err = LLMConnectionError("claude", message="Connexion refusée")

        assert str(err) == "Connexion refusée"

    def test_inherits_from_llm_error(self):
        """LLMConnectionError hérite de LLMError."""
        err = LLMConnectionError("provider")
        assert isinstance(err, LLMError)


class TestLLMTimeoutError:
    """Tests pour LLMTimeoutError."""

    def test_create_with_provider(self):
        """LLMTimeoutError avec provider."""
        err = LLMTimeoutError("claude")

        assert err.provider == "claude"
        assert err.timeout_seconds is None
        assert err.code == "LLM_TIMEOUT"
        assert "timed out" in str(err)

    def test_create_with_timeout_seconds(self):
        """LLMTimeoutError avec timeout_seconds."""
        err = LLMTimeoutError("claude", timeout_seconds=30)

        assert err.timeout_seconds == 30
        assert "30 seconds" in str(err)

    def test_create_with_custom_message(self):
        """LLMTimeoutError avec message personnalisé."""
        err = LLMTimeoutError("ollama", message="Timeout de 60s dépassé")

        assert str(err) == "Timeout de 60s dépassé"

    def test_inherits_from_llm_error(self):
        """LLMTimeoutError hérite de LLMError."""
        err = LLMTimeoutError("provider")
        assert isinstance(err, LLMError)


class TestLLMContextLengthError:
    """Tests pour LLMContextLengthError."""

    def test_create_with_provider(self):
        """LLMContextLengthError avec provider."""
        err = LLMContextLengthError("claude")

        assert err.provider == "claude"
        assert err.max_tokens is None
        assert err.actual_tokens is None
        assert err.code == "LLM_CONTEXT_LENGTH"
        assert "Context length exceeded" in str(err)

    def test_create_with_tokens(self):
        """LLMContextLengthError avec tokens."""
        err = LLMContextLengthError("claude", max_tokens=100000, actual_tokens=150000)

        assert err.max_tokens == 100000
        assert err.actual_tokens == 150000
        assert "100000" in str(err)
        assert "150000" in str(err)

    def test_create_with_custom_message(self):
        """LLMContextLengthError avec message personnalisé."""
        err = LLMContextLengthError("ollama", message="Prompt trop long")

        assert str(err) == "Prompt trop long"

    def test_inherits_from_llm_error(self):
        """LLMContextLengthError hérite de LLMError."""
        err = LLMContextLengthError("provider")
        assert isinstance(err, LLMError)


class TestLLMResponseError:
    """Tests pour LLMResponseError."""

    def test_create_with_provider(self):
        """LLMResponseError avec provider."""
        err = LLMResponseError("claude")

        assert err.provider == "claude"
        assert err.code == "LLM_RESPONSE_ERROR"
        assert "Invalid response" in str(err)

    def test_create_with_custom_message(self):
        """LLMResponseError avec message personnalisé."""
        err = LLMResponseError("ollama", message="JSON malformé")

        assert str(err) == "JSON malformé"

    def test_inherits_from_llm_error(self):
        """LLMResponseError hérite de LLMError."""
        err = LLMResponseError("provider")
        assert isinstance(err, LLMError)


class TestLLMModelNotFoundError:
    """Tests pour LLMModelNotFoundError."""

    def test_create(self):
        """LLMModelNotFoundError avec provider et model."""
        err = LLMModelNotFoundError("ollama", model="llama-999")

        assert err.provider == "ollama"
        assert err.model == "llama-999"
        assert err.code == "LLM_MODEL_NOT_FOUND"
        assert "llama-999" in str(err)
        assert "not found" in str(err)

    def test_create_with_custom_message(self):
        """LLMModelNotFoundError avec message personnalisé."""
        err = LLMModelNotFoundError("claude", model="x", message="Modèle inconnu")

        assert str(err) == "Modèle inconnu"

    def test_inherits_from_llm_error(self):
        """LLMModelNotFoundError hérite de LLMError."""
        err = LLMModelNotFoundError("provider", model="model")
        assert isinstance(err, LLMError)


class TestInsufficientPermissionError:
    """Tests pour InsufficientPermissionError."""

    def test_create(self):
        """InsufficientPermissionError avec holder et action."""
        err = InsufficientPermissionError("user-123", "delete_email")

        assert err.holder_id == "user-123"
        assert err.action == "delete_email"
        assert err.code == "INSUFFICIENT_PERMISSION"
        assert "user-123" in str(err)
        assert "delete_email" in str(err)

    def test_inherits_from_domain_error(self):
        """InsufficientPermissionError hérite de DomainError."""
        err = InsufficientPermissionError("holder", "action")
        assert isinstance(err, DomainError)


class TestAliases:
    """Tests pour les aliases de rétrocompatibilité."""

    def test_domain_validation_error_is_validation_error(self):
        """DomainValidationError est un alias de ValidationError."""
        assert DomainValidationError is ValidationError

    def test_can_catch_as_domain_validation_error(self):
        """On peut attraper ValidationError via DomainValidationError."""
        try:
            raise ValidationError("test")
        except DomainValidationError as e:
            assert str(e) == "test"


class TestExceptionHierarchy:
    """Tests pour la hiérarchie des exceptions."""

    def test_all_llm_errors_catchable_by_llm_error(self):
        """Toutes les erreurs LLM sont attrapables par LLMError."""
        llm_exceptions = [
            LLMAuthenticationError("p"),
            LLMRateLimitError("p"),
            LLMUnavailableError("p"),
            LLMConnectionError("p"),
            LLMTimeoutError("p"),
            LLMContextLengthError("p"),
            LLMResponseError("p"),
            LLMModelNotFoundError("p", "m"),
        ]

        for exc in llm_exceptions:
            assert isinstance(exc, LLMError)

    def test_all_validation_errors_catchable_by_validation_error(self):
        """Toutes les erreurs de validation sont attrapables par ValidationError."""
        validation_exceptions = [
            EmptyValueError("f"),
            InvalidBoundsError("f", value=0),
            InvalidFormatError("f", expected_format="fmt"),
        ]

        for exc in validation_exceptions:
            assert isinstance(exc, ValidationError)

    def test_all_errors_catchable_by_domain_error(self):
        """Toutes les erreurs sont attrapables par DomainError."""
        all_exceptions = [
            ValidationError("msg"),
            EmptyValueError("f"),
            InvalidBoundsError("f", value=0),
            InvalidFormatError("f", expected_format="fmt"),
            EntityNotFoundError("t", "id"),
            BusinessRuleViolationError("rule"),
            ConcurrencyError("t", "id"),
            LLMError("msg"),
            LLMAuthenticationError("p"),
            LLMRateLimitError("p"),
            LLMUnavailableError("p"),
            LLMConnectionError("p"),
            LLMTimeoutError("p"),
            LLMContextLengthError("p"),
            LLMResponseError("p"),
            LLMModelNotFoundError("p", "m"),
            InsufficientPermissionError("h", "a"),
        ]

        for exc in all_exceptions:
            assert isinstance(exc, DomainError)
