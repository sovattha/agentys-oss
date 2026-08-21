# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour le module circuit_breaker."""

import time
import pytest

from app.infrastructure.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
    CircuitOpenError,
    CircuitBreakerStats,
    get_circuit_breaker,
    circuit_breaker,
    get_all_circuit_breakers,
    reset_all_circuit_breakers,
    _circuit_breakers,
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def cb():
    """Circuit breaker avec seuils bas pour tests rapides."""
    return CircuitBreaker(
        name="test_service",
        failure_threshold=3,
        recovery_timeout=1,
        half_open_max_calls=2,
    )


@pytest.fixture(autouse=True)
def clean_registry():
    """Nettoie le registre global entre les tests."""
    _circuit_breakers.clear()
    yield
    _circuit_breakers.clear()


# ============================================================================
# TESTS — ÉTAT INITIAL
# ============================================================================

class TestCircuitBreakerInit:
    def test_initial_state_is_closed(self, cb):
        assert cb.state == CircuitState.CLOSED

    def test_initial_stats_are_zero(self, cb):
        stats = cb.stats
        assert stats.total_calls == 0
        assert stats.successful_calls == 0
        assert stats.failed_calls == 0
        assert stats.rejected_calls == 0
        assert stats.state_changes == 0

    def test_name_is_set(self, cb):
        assert cb.name == "test_service"

    def test_custom_thresholds(self, cb):
        assert cb.failure_threshold == 3
        assert cb.recovery_timeout == 1
        assert cb.half_open_max_calls == 2


# ============================================================================
# TESTS — APPELS RÉUSSIS (CLOSED)
# ============================================================================

class TestCircuitBreakerSuccess:
    def test_successful_call_returns_result(self, cb):
        result = cb.call(lambda: 42)
        assert result == 42

    def test_successful_call_increments_stats(self, cb):
        cb.call(lambda: "ok")
        stats = cb.stats
        assert stats.total_calls == 1
        assert stats.successful_calls == 1
        assert stats.failed_calls == 0

    def test_multiple_successful_calls(self, cb):
        for i in range(5):
            cb.call(lambda: i)
        assert cb.stats.successful_calls == 5
        assert cb.state == CircuitState.CLOSED

    def test_success_resets_failure_count(self, cb):
        # 2 échecs (sous le seuil de 3)
        for _ in range(2):
            try:
                cb.call(self._failing_func)
            except RuntimeError:
                pass
        # 1 succès remet le compteur à 0
        cb.call(lambda: "ok")
        # 3 échecs supplémentaires ne devraient pas ouvrir (compteur reset)
        for _ in range(2):
            try:
                cb.call(self._failing_func)
            except RuntimeError:
                pass
        assert cb.state == CircuitState.CLOSED

    @staticmethod
    def _failing_func():
        raise RuntimeError("boom")


# ============================================================================
# TESTS — TRANSITION CLOSED → OPEN
# ============================================================================

class TestCircuitBreakerOpenTransition:
    def test_opens_after_threshold_failures(self, cb):
        for _ in range(3):
            with pytest.raises(RuntimeError):
                cb.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        assert cb.state == CircuitState.OPEN

    def test_open_circuit_rejects_calls(self, cb):
        # Atteindre le seuil
        self._trigger_open(cb)
        with pytest.raises(CircuitOpenError) as exc_info:
            cb.call(lambda: "should not execute")
        assert "test_service" in str(exc_info.value)
        assert exc_info.value.service_name == "test_service"

    def test_open_increments_rejected_stats(self, cb):
        self._trigger_open(cb)
        try:
            cb.call(lambda: None)
        except CircuitOpenError:
            pass
        assert cb.stats.rejected_calls >= 1

    def test_excluded_exceptions_dont_count(self):
        cb = CircuitBreaker(
            name="test",
            failure_threshold=2,
            recovery_timeout=1,
            excluded_exceptions=(ValueError,),
        )
        # ValueError ne compte pas
        for _ in range(5):
            with pytest.raises(ValueError):
                cb.call(self._raise_value_error)
        assert cb.state == CircuitState.CLOSED

    def test_non_excluded_exceptions_count(self):
        cb = CircuitBreaker(
            name="test",
            failure_threshold=2,
            recovery_timeout=1,
            excluded_exceptions=(ValueError,),
        )
        for _ in range(2):
            with pytest.raises(TypeError):
                cb.call(self._raise_type_error)
        assert cb.state == CircuitState.OPEN

    @staticmethod
    def _trigger_open(cb):
        for _ in range(cb.failure_threshold):
            try:
                cb.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
            except RuntimeError:
                pass

    @staticmethod
    def _raise_value_error():
        raise ValueError("excluded")

    @staticmethod
    def _raise_type_error():
        raise TypeError("not excluded")


# ============================================================================
# TESTS — TRANSITION OPEN → HALF_OPEN
# ============================================================================

class TestCircuitBreakerHalfOpen:
    def test_transitions_to_half_open_after_timeout(self, cb):
        self._trigger_open(cb)
        assert cb.state == CircuitState.OPEN
        # Attendre le recovery_timeout (1s)
        time.sleep(1.1)
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_allows_limited_calls(self, cb):
        self._trigger_open(cb)
        time.sleep(1.1)
        # half_open_max_calls = 2, devrait accepter 2 appels
        result1 = cb.call(lambda: "first")
        result2 = cb.call(lambda: "second")
        assert result1 == "first"
        assert result2 == "second"

    def test_half_open_success_closes_circuit(self, cb):
        self._trigger_open(cb)
        time.sleep(1.1)
        # 2 succès (= half_open_max_calls) ferment le circuit
        cb.call(lambda: "ok")
        cb.call(lambda: "ok")
        assert cb.state == CircuitState.CLOSED

    def test_half_open_failure_reopens_circuit(self, cb):
        self._trigger_open(cb)
        time.sleep(1.1)
        assert cb.state == CircuitState.HALF_OPEN
        with pytest.raises(RuntimeError):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        assert cb.state == CircuitState.OPEN

    @staticmethod
    def _trigger_open(cb):
        for _ in range(cb.failure_threshold):
            try:
                cb.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
            except RuntimeError:
                pass


# ============================================================================
# TESTS — RESET
# ============================================================================

class TestCircuitBreakerReset:
    def test_reset_closes_open_circuit(self, cb):
        for _ in range(3):
            try:
                cb.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
            except RuntimeError:
                pass
        assert cb.state == CircuitState.OPEN
        cb.reset()
        assert cb.state == CircuitState.CLOSED

    def test_reset_allows_calls_again(self, cb):
        for _ in range(3):
            try:
                cb.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
            except RuntimeError:
                pass
        cb.reset()
        result = cb.call(lambda: "back to normal")
        assert result == "back to normal"


# ============================================================================
# TESTS — REGISTRE GLOBAL
# ============================================================================

class TestCircuitBreakerRegistry:
    def test_get_circuit_breaker_creates_new(self):
        cb = get_circuit_breaker("my_service")
        assert cb.name == "my_service"

    def test_get_circuit_breaker_returns_same_instance(self):
        cb1 = get_circuit_breaker("service_a")
        cb2 = get_circuit_breaker("service_a")
        assert cb1 is cb2

    def test_get_all_returns_all(self):
        get_circuit_breaker("svc1")
        get_circuit_breaker("svc2")
        all_cbs = get_all_circuit_breakers()
        assert "svc1" in all_cbs
        assert "svc2" in all_cbs

    def test_reset_all_resets_every_breaker(self):
        cb1 = get_circuit_breaker("svc1", failure_threshold=1, recovery_timeout=60)
        try:
            cb1.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        except RuntimeError:
            pass
        assert cb1.state == CircuitState.OPEN
        reset_all_circuit_breakers()
        assert cb1.state == CircuitState.CLOSED


# ============================================================================
# TESTS — DÉCORATEUR
# ============================================================================

class TestCircuitBreakerDecorator:
    def test_decorator_wraps_function(self):
        @circuit_breaker("decorated_svc", failure_threshold=2, recovery_timeout=1)
        def my_func():
            return "decorated"

        result = my_func()
        assert result == "decorated"

    def test_decorator_exposes_circuit_breaker(self):
        @circuit_breaker("exposed_svc")
        def my_func():
            return True

        assert hasattr(my_func, "circuit_breaker")
        assert isinstance(my_func.circuit_breaker, CircuitBreaker)

    def test_decorator_opens_on_failures(self):
        @circuit_breaker("fail_svc", failure_threshold=2, recovery_timeout=60)
        def failing_func():
            raise RuntimeError("oops")

        for _ in range(2):
            with pytest.raises(RuntimeError):
                failing_func()

        assert failing_func.circuit_breaker.state == CircuitState.OPEN


# ============================================================================
# TESTS — CIRCUIT OPEN ERROR
# ============================================================================

class TestCircuitOpenError:
    def test_error_message_contains_service_name(self):
        err = CircuitOpenError("gmail", 30.5)
        assert "gmail" in str(err)
        assert "30.5" in str(err)

    def test_error_attributes(self):
        err = CircuitOpenError("outlook", 10.0)
        assert err.service_name == "outlook"
        assert err.remaining_time == 10.0


# ============================================================================
# TESTS — STATS
# ============================================================================

class TestCircuitBreakerStatsDataclass:
    def test_default_values(self):
        stats = CircuitBreakerStats()
        assert stats.total_calls == 0
        assert stats.current_state == CircuitState.CLOSED
        assert stats.last_failure_time is None
        assert stats.last_success_time is None

    def test_stats_track_state_changes(self, cb):
        # 3 failures → OPEN (1 state change)
        for _ in range(3):
            try:
                cb.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
            except RuntimeError:
                pass
        assert cb.stats.state_changes >= 1
