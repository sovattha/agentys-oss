# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour le module retry avec backoff exponentiel.
"""

import pytest
from unittest.mock import MagicMock
import time

from app.infrastructure.retry import (
    with_retry,
    retry_call,
    RetryExhaustedError,
    is_rate_limit_error,
    get_retry_delay_from_error,
)


class TestWithRetryDecorator:
    """Tests pour le décorateur @with_retry."""

    def test_success_on_first_try(self):
        """Fonction réussit au premier essai."""
        call_count = 0

        @with_retry(max_attempts=3)
        def succeed():
            nonlocal call_count
            call_count += 1
            return "success"

        result = succeed()

        assert result == "success"
        assert call_count == 1

    def test_success_after_retries(self):
        """Fonction réussit après quelques échecs."""
        call_count = 0

        @with_retry(max_attempts=3, initial_delay=0.01)
        def fail_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Temporary failure")
            return "success"

        result = fail_then_succeed()

        assert result == "success"
        assert call_count == 3

    def test_exhausted_retries_raises(self):
        """Exception levée après épuisement des tentatives."""

        @with_retry(max_attempts=3, initial_delay=0.01)
        def always_fail():
            raise ConnectionError("Always fails")

        with pytest.raises(RetryExhaustedError) as exc_info:
            always_fail()

        assert "3 tentatives" in str(exc_info.value)
        assert exc_info.value.last_exception is not None

    def test_retryable_exceptions_filter(self):
        """Seules les exceptions spécifiées sont retryées."""
        call_count = 0

        @with_retry(
            max_attempts=3,
            initial_delay=0.01,
            retryable_exceptions=(ConnectionError,)
        )
        def fail_with_value_error():
            nonlocal call_count
            call_count += 1
            raise ValueError("Not retryable")

        with pytest.raises(ValueError):
            fail_with_value_error()

        # Ne devrait être appelé qu'une fois (pas de retry)
        assert call_count == 1

    def test_on_retry_callback(self):
        """Callback appelé avant chaque retry."""
        retry_log = []

        def on_retry(exc, attempt):
            retry_log.append((str(exc), attempt))

        @with_retry(
            max_attempts=3,
            initial_delay=0.01,
            on_retry=on_retry
        )
        def fail_twice():
            if len(retry_log) < 2:
                raise ConnectionError("Temporary")
            return "success"

        result = fail_twice()

        assert result == "success"
        assert len(retry_log) == 2
        assert retry_log[0][1] == 1  # Premier retry
        assert retry_log[1][1] == 2  # Deuxième retry

    def test_backoff_factor(self):
        """Vérifier que le délai augmente exponentiellement."""
        delays = []
        start_time = time.time()

        @with_retry(
            max_attempts=4,
            backoff_factor=2.0,
            initial_delay=0.05,
            max_delay=10.0
        )
        def fail_and_track_time():
            elapsed = time.time() - start_time
            delays.append(elapsed)
            if len(delays) < 4:
                raise ConnectionError("Fail")
            return "success"

        fail_and_track_time()

        # Les délais devraient croître: 0.05, 0.1, 0.2
        # Vérifier que le 3ème délai est plus long que le 2ème
        if len(delays) >= 3:
            delay2 = delays[2] - delays[1]
            delay3 = delays[3] - delays[2]
            assert delay3 >= delay2 * 0.8  # Tolérance de 20%

    def test_max_delay_respected(self):
        """Le délai ne dépasse pas max_delay."""
        call_times = []

        @with_retry(
            max_attempts=5,
            backoff_factor=10.0,
            initial_delay=0.05,
            max_delay=0.1
        )
        def fail_many_times():
            call_times.append(time.time())
            if len(call_times) < 5:
                raise ConnectionError("Fail")
            return "success"

        fail_many_times()

        # Vérifier que les délais ne dépassent pas max_delay + tolérance
        for i in range(1, len(call_times)):
            delay = call_times[i] - call_times[i - 1]
            assert delay < 0.2  # max_delay + marge


class TestRetryCall:
    """Tests pour la fonction retry_call."""

    def test_retry_call_success(self):
        """retry_call réussit."""
        mock_func = MagicMock(return_value="result")

        result = retry_call(
            mock_func,
            args=(1, 2),
            kwargs={"key": "value"},
            max_attempts=3,
            initial_delay=0.01
        )

        assert result == "result"
        mock_func.assert_called_once_with(1, 2, key="value")

    def test_retry_call_with_retries(self):
        """retry_call avec retries."""
        mock_func = MagicMock(side_effect=[
            ConnectionError("Fail 1"),
            ConnectionError("Fail 2"),
            "success"
        ])

        result = retry_call(
            mock_func,
            max_attempts=3,
            initial_delay=0.01
        )

        assert result == "success"
        assert mock_func.call_count == 3

    def test_retry_call_exhausted(self):
        """retry_call épuisé."""
        mock_func = MagicMock(side_effect=ConnectionError("Always fail"))

        with pytest.raises(RetryExhaustedError):
            retry_call(
                mock_func,
                max_attempts=2,
                initial_delay=0.01
            )


class TestRateLimitHelpers:
    """Tests pour les fonctions helper de rate limit."""

    def test_is_rate_limit_error_true(self):
        """Détection des erreurs de rate limit."""
        rate_limit_errors = [
            Exception("Rate limit exceeded"),
            Exception("429 Too Many Requests"),
            Exception("API rate_limit reached"),
            Exception("Quota exceeded for this minute"),
            Exception("Server overloaded, try again"),
        ]

        for error in rate_limit_errors:
            assert is_rate_limit_error(error) is True

    def test_is_rate_limit_error_false(self):
        """Non-détection des erreurs normales."""
        normal_errors = [
            Exception("Connection refused"),
            Exception("Timeout error"),
            ValueError("Invalid parameter"),
        ]

        for error in normal_errors:
            assert is_rate_limit_error(error) is False

    def test_get_retry_delay_from_error_with_seconds(self):
        """Extraction du délai de retry depuis le message."""
        error = Exception("Rate limited. Retry after 30 seconds")
        delay = get_retry_delay_from_error(error, default=10.0)
        assert delay == 30.0

    def test_get_retry_delay_from_error_default(self):
        """Délai par défaut si non spécifié."""
        error = Exception("Rate limit exceeded")
        delay = get_retry_delay_from_error(error, default=60.0)
        assert delay == 60.0


class TestRetryExhaustedError:
    """Tests pour RetryExhaustedError."""

    def test_error_message(self):
        """Message d'erreur correct."""
        original = ValueError("Original error")
        error = RetryExhaustedError("Failed after 3 attempts", last_exception=original)

        assert "Failed after 3 attempts" in str(error)
        assert error.last_exception is original

    def test_error_without_last_exception(self):
        """Erreur sans exception originale."""
        error = RetryExhaustedError("Failed")
        assert error.last_exception is None
