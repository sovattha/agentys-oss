# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour les modules d'infrastructure.

Couvre:
- Circuit breaker
- Audit logger
- Rate limiter
- Logging config
"""

import pytest
import time
import threading

from app.infrastructure.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
    CircuitOpenError,
    circuit_breaker,
)
from app.infrastructure.audit import (
    AuditLogger,
    AuditEventType,
)
from app.infrastructure.rate_limiter import (
    SlidingWindowRateLimiter,
    TokenBucketRateLimiter,
    RateLimitExceededError,
    rate_limit,
    reset_all_rate_limiters,
)
from app.infrastructure.logging_config import (
    JsonFormatter,
    StandardFormatter,
    setup_logging,
)


class TestCircuitBreaker:
    """Tests pour le circuit breaker."""

    def test_initial_state_is_closed(self):
        """Le circuit commence fermé."""
        cb = CircuitBreaker("test", failure_threshold=3)
        assert cb.state == CircuitState.CLOSED

    def test_successful_calls_keep_circuit_closed(self):
        """Les appels réussis gardent le circuit fermé."""
        cb = CircuitBreaker("test", failure_threshold=3)

        def success():
            return "ok"

        for _ in range(10):
            result = cb.call(success)
            assert result == "ok"

        assert cb.state == CircuitState.CLOSED

    def test_failures_open_circuit(self):
        """Les échecs successifs ouvrent le circuit."""
        cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout=10)

        def fail():
            raise ValueError("error")

        # 3 échecs doivent ouvrir le circuit
        for _ in range(3):
            with pytest.raises(ValueError):
                cb.call(fail)

        assert cb.state == CircuitState.OPEN

    def test_open_circuit_rejects_calls(self):
        """Le circuit ouvert rejette les appels."""
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=100)

        def fail():
            raise ValueError("error")

        # Ouvrir le circuit
        with pytest.raises(ValueError):
            cb.call(fail)

        # Les appels suivants sont rejetés
        with pytest.raises(CircuitOpenError) as exc_info:
            cb.call(lambda: "ok")

        assert "test" in str(exc_info.value)

    def test_half_open_after_timeout(self):
        """Le circuit passe en half-open après le timeout."""
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.1)

        # Ouvrir le circuit
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("error")))

        # Attendre le timeout
        time.sleep(0.15)

        # Devrait être en half-open maintenant
        assert cb.state == CircuitState.HALF_OPEN

    def test_success_in_half_open_closes_circuit(self):
        """Un succès en half-open ferme le circuit."""
        cb = CircuitBreaker(
            "test",
            failure_threshold=1,
            recovery_timeout=0.1,
            half_open_max_calls=1
        )

        # Ouvrir le circuit
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("error")))

        time.sleep(0.15)

        # Appel réussi en half-open
        result = cb.call(lambda: "ok")
        assert result == "ok"
        assert cb.state == CircuitState.CLOSED

    def test_failure_in_half_open_reopens_circuit(self):
        """Un échec en half-open rouvre le circuit."""
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.1)

        # Ouvrir le circuit
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("error")))

        time.sleep(0.15)

        # Échec en half-open
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("error")))

        assert cb.state == CircuitState.OPEN

    def test_stats_tracking(self):
        """Les statistiques sont correctement suivies."""
        cb = CircuitBreaker("test", failure_threshold=5)

        # Appels réussis
        for _ in range(3):
            cb.call(lambda: "ok")

        stats = cb.stats
        assert stats.total_calls == 3
        assert stats.successful_calls == 3
        assert stats.failed_calls == 0

    def test_excluded_exceptions(self):
        """Les exceptions exclues ne comptent pas comme échec."""
        cb = CircuitBreaker(
            "test",
            failure_threshold=2,
            excluded_exceptions=(KeyError,)
        )

        # KeyError ne doit pas compter
        for _ in range(5):
            with pytest.raises(KeyError):
                cb.call(lambda: (_ for _ in ()).throw(KeyError("key")))

        assert cb.state == CircuitState.CLOSED

    def test_decorator(self):
        """Le décorateur circuit_breaker fonctionne."""
        @circuit_breaker("decorator_test", failure_threshold=2)
        def my_function():
            return "result"

        result = my_function()
        assert result == "result"

        # Vérifier que le circuit breaker est attaché
        assert hasattr(my_function, 'circuit_breaker')


class TestAuditLogger:
    """Tests pour l'audit logger."""

    def test_log_event(self, tmp_path):
        """Log d'un événement basique."""
        audit_file = tmp_path / "audit.json"
        logger = AuditLogger(filepath=audit_file)

        event = logger.log(
            AuditEventType.DRAFT_CREATED,
            success=True,
            details={"test": "value"}
        )

        assert event.event_type == "draft_created"
        assert event.success is True
        assert event.details["test"] == "value"

    def test_log_draft_created(self, tmp_path):
        """Log de création de brouillon."""
        audit_file = tmp_path / "audit.json"
        logger = AuditLogger(filepath=audit_file)

        event = logger.log_draft_created(
            email_id="email123",
            draft_id="draft456",
            recipient="user@example.com",
            subject="Test Subject",
            duration_ms=500,
            status="V1",
            priority_score=75,
            category="NORMAL",
        )

        assert event.email_id == "email123"
        assert event.draft_id == "draft456"
        assert event.duration_ms == 500

    def test_log_draft_failed(self, tmp_path):
        """Log d'échec de brouillon."""
        audit_file = tmp_path / "audit.json"
        logger = AuditLogger(filepath=audit_file)

        event = logger.log_draft_failed(
            email_id="email123",
            recipient="user@example.com",
            error="API Error",
            duration_ms=100,
        )

        assert event.success is False
        assert event.error == "API Error"

    def test_get_events_filtered(self, tmp_path):
        """Récupération filtrée des événements."""
        audit_file = tmp_path / "audit.json"
        logger = AuditLogger(filepath=audit_file)

        # Créer plusieurs événements
        logger.log(AuditEventType.DRAFT_CREATED, success=True)
        logger.log(AuditEventType.DRAFT_FAILED, success=False)
        logger.log(AuditEventType.DRAFT_CREATED, success=True)

        # Filtrer par type
        created_events = logger.get_events(
            event_type=AuditEventType.DRAFT_CREATED
        )
        assert len(created_events) == 2

    def test_stats(self, tmp_path):
        """Statistiques d'audit."""
        audit_file = tmp_path / "audit.json"
        logger = AuditLogger(filepath=audit_file)

        logger.log(AuditEventType.DRAFT_CREATED, success=True)
        logger.log(AuditEventType.DRAFT_CREATED, success=True)
        logger.log(AuditEventType.DRAFT_FAILED, success=False)

        stats = logger.get_stats()
        assert stats["total_events"] == 3
        assert stats["success_count"] == 2
        assert stats["failure_count"] == 1

    def test_persistence(self, tmp_path):
        """Persistance des événements."""
        audit_file = tmp_path / "audit.json"

        # Premier logger
        logger1 = AuditLogger(filepath=audit_file)
        logger1.log(AuditEventType.DRAFT_CREATED, success=True)

        # Deuxième logger (devrait charger les événements)
        logger2 = AuditLogger(filepath=audit_file)
        events = logger2.get_events()

        assert len(events) == 1


class TestRateLimiter:
    """Tests pour le rate limiter."""

    def test_sliding_window_allows_within_limit(self):
        """Requêtes dans la limite sont autorisées."""
        limiter = SlidingWindowRateLimiter(
            "test",
            max_requests=5,
            window_seconds=1.0,
            blocking=False
        )

        for _ in range(5):
            assert limiter.acquire() is True

    def test_sliding_window_blocks_over_limit(self):
        """Requêtes au-delà de la limite sont bloquées."""
        limiter = SlidingWindowRateLimiter(
            "test",
            max_requests=3,
            window_seconds=10.0,
            blocking=False
        )

        # 3 requêtes OK
        for _ in range(3):
            limiter.acquire()

        # 4ème requête bloquée
        with pytest.raises(RateLimitExceededError):
            limiter.acquire()

    def test_sliding_window_expires_old_requests(self):
        """Les anciennes requêtes expirent."""
        limiter = SlidingWindowRateLimiter(
            "test",
            max_requests=2,
            window_seconds=0.1,
            blocking=False
        )

        # 2 requêtes
        limiter.acquire()
        limiter.acquire()

        # Attendre l'expiration
        time.sleep(0.15)

        # Devrait pouvoir en faire 2 de plus
        assert limiter.acquire() is True
        assert limiter.acquire() is True

    def test_token_bucket_allows_burst(self):
        """Le token bucket permet les bursts."""
        limiter = TokenBucketRateLimiter(
            "test",
            tokens_per_second=10,
            max_tokens=5,
            blocking=False
        )

        # Burst de 5 requêtes
        for _ in range(5):
            assert limiter.acquire() is True

    def test_token_bucket_refills(self):
        """Le bucket se remplit au fil du temps."""
        limiter = TokenBucketRateLimiter(
            "test",
            tokens_per_second=10,
            max_tokens=5,
            blocking=False
        )

        # Vider le bucket
        for _ in range(5):
            limiter.acquire()

        # Attendre le remplissage (0.2s = 2 tokens)
        time.sleep(0.25)

        # Devrait avoir 2 tokens disponibles
        assert limiter.acquire() is True
        assert limiter.acquire() is True

    def test_rate_limit_decorator(self):
        """Le décorateur rate_limit fonctionne."""
        reset_all_rate_limiters()

        call_count = 0

        @rate_limit("decorator_test", max_requests=3, window_seconds=10)
        def my_function():
            nonlocal call_count
            call_count += 1
            return call_count

        # 3 appels OK
        for i in range(3):
            result = my_function()
            assert result == i + 1

    def test_stats_tracking(self):
        """Les statistiques sont suivies."""
        limiter = SlidingWindowRateLimiter(
            "test",
            max_requests=2,
            window_seconds=10.0,
            blocking=False
        )

        limiter.acquire()
        limiter.acquire()

        try:
            limiter.acquire()
        except RateLimitExceededError:
            pass

        stats = limiter.stats
        assert stats.total_requests == 3
        assert stats.allowed_requests == 2
        assert stats.rejected_requests == 1


class TestLoggingConfig:
    """Tests pour la configuration du logging."""

    def test_json_formatter(self):
        """Le formateur JSON produit du JSON valide."""
        import json
        import logging

        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None
        )

        result = formatter.format(record)
        parsed = json.loads(result)

        assert parsed["level"] == "INFO"
        assert parsed["message"] == "Test message"
        assert "timestamp" in parsed

    def test_standard_formatter(self):
        """Le formateur standard produit un format lisible."""
        import logging

        formatter = StandardFormatter(use_colors=False)
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None
        )

        result = formatter.format(record)

        assert "INFO" in result
        assert "Test message" in result

    def test_setup_logging_preserves_pytest_capture_handler(self, tmp_path, monkeypatch):
        """setup_logging ne doit pas rendre caplog muet dans le full run."""
        import logging
        from _pytest.logging import LogCaptureHandler
        import app.infrastructure.logging_config as logging_config

        monkeypatch.setattr(logging_config, "LOGS_DIR", tmp_path)
        root_logger = logging.getLogger()
        original_handlers = list(root_logger.handlers)
        capture_handler = LogCaptureHandler()
        root_logger.addHandler(capture_handler)

        try:
            setup_logging(log_to_console=False, log_to_file=False)
            assert capture_handler in root_logger.handlers

            logging.getLogger("agentys.test").warning("capture still works")

            assert any(
                record.getMessage() == "capture still works"
                for record in capture_handler.records
            )
        finally:
            root_logger.handlers[:] = original_handlers


class TestCircuitBreakerIntegration:
    """Tests d'intégration pour le circuit breaker."""

    def test_thread_safety(self):
        """Le circuit breaker est thread-safe."""
        cb = CircuitBreaker("thread_test", failure_threshold=100)
        results = []
        errors = []

        def worker():
            try:
                for _ in range(100):
                    cb.call(lambda: "ok")
                results.append(True)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 5
        assert len(errors) == 0
        assert cb.stats.successful_calls == 500


class TestRateLimiterIntegration:
    """Tests d'intégration pour le rate limiter."""

    def test_thread_safety(self):
        """Le rate limiter est thread-safe."""
        limiter = SlidingWindowRateLimiter(
            "thread_test",
            max_requests=100,
            window_seconds=10.0,
            blocking=True
        )

        acquired = []

        def worker():
            for _ in range(20):
                if limiter.acquire():
                    acquired.append(True)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(acquired) == 100


# ============================================================================
# TESTS SECURITY - NOTIFICATION SANITIZATION
# ============================================================================

class TestNotificationSanitization:
    """Tests for command injection prevention in notifications."""

    def test_sanitize_applescript_escapes_quotes(self):
        """AppleScript sanitization escapes double quotes."""
        from app.infrastructure.notifications import _sanitize_for_applescript

        result = _sanitize_for_applescript('Test "quoted" text')
        assert result == 'Test \\"quoted\\" text'

    def test_sanitize_applescript_escapes_backslashes(self):
        """AppleScript sanitization escapes backslashes."""
        from app.infrastructure.notifications import _sanitize_for_applescript

        result = _sanitize_for_applescript('Path\\to\\file')
        assert result == 'Path\\\\to\\\\file'

    def test_sanitize_applescript_injection_attempt(self):
        """AppleScript sanitization prevents command injection."""
        from app.infrastructure.notifications import _sanitize_for_applescript

        # Attempt to inject AppleScript command
        malicious = '" & do shell script "rm -rf /" & "'
        result = _sanitize_for_applescript(malicious)

        # Should escape all quotes, preventing injection
        assert '\\" & do shell script \\"rm -rf /\\" & \\"' == result

    def test_sanitize_applescript_handles_none(self):
        """AppleScript sanitization handles None input."""
        from app.infrastructure.notifications import _sanitize_for_applescript

        result = _sanitize_for_applescript(None)
        assert result == ""

    def test_sanitize_applescript_handles_empty_string(self):
        """AppleScript sanitization handles empty string."""
        from app.infrastructure.notifications import _sanitize_for_applescript

        result = _sanitize_for_applescript("")
        assert result == ""

    def test_sanitize_powershell_escapes_backticks(self):
        """PowerShell sanitization escapes backticks."""
        from app.infrastructure.notifications import _sanitize_for_powershell

        result = _sanitize_for_powershell('Test `n newline')
        assert result == 'Test ``n newline'

    def test_sanitize_powershell_escapes_quotes(self):
        """PowerShell sanitization escapes double quotes."""
        from app.infrastructure.notifications import _sanitize_for_powershell

        result = _sanitize_for_powershell('Test "quoted" text')
        assert result == 'Test `"quoted`" text'

    def test_sanitize_powershell_escapes_dollar_signs(self):
        """PowerShell sanitization escapes dollar signs (variable expansion)."""
        from app.infrastructure.notifications import _sanitize_for_powershell

        result = _sanitize_for_powershell('$env:PATH')
        assert result == '`$env:PATH'

    def test_sanitize_powershell_escapes_single_quotes(self):
        """PowerShell sanitization escapes single quotes."""
        from app.infrastructure.notifications import _sanitize_for_powershell

        result = _sanitize_for_powershell("Test 'quoted' text")
        assert result == "Test `'quoted`' text"

    def test_sanitize_powershell_injection_attempt(self):
        """PowerShell sanitization prevents command injection."""
        from app.infrastructure.notifications import _sanitize_for_powershell

        # Attempt to inject PowerShell command via variable expansion
        malicious = '$(Remove-Item -Recurse -Force C:\\)'
        result = _sanitize_for_powershell(malicious)

        # Dollar sign should be escaped
        assert result == '`$(Remove-Item -Recurse -Force C:\\)'

    def test_sanitize_powershell_handles_none(self):
        """PowerShell sanitization handles None input."""
        from app.infrastructure.notifications import _sanitize_for_powershell

        result = _sanitize_for_powershell(None)
        assert result == ""

    def test_sanitize_powershell_handles_empty_string(self):
        """PowerShell sanitization handles empty string."""
        from app.infrastructure.notifications import _sanitize_for_powershell

        result = _sanitize_for_powershell("")
        assert result == ""

    def test_sanitize_powershell_complex_injection(self):
        """PowerShell sanitization handles complex injection attempts."""
        from app.infrastructure.notifications import _sanitize_for_powershell

        # Complex injection with multiple special chars
        malicious = '"); Invoke-Expression "whoami"; Write-Host ("'
        result = _sanitize_for_powershell(malicious)

        # All special characters should be escaped
        assert '`"' in result
        assert '`$' not in malicious or '`$' in result  # Dollar if present

    def test_sanitize_applescript_preserves_safe_chars(self):
        """AppleScript sanitization preserves safe characters."""
        from app.infrastructure.notifications import _sanitize_for_applescript

        safe_text = "Hello World! 123 @ # % & * () - _ + = [] {} ; : , . < > ?"
        result = _sanitize_for_applescript(safe_text)
        assert result == safe_text

    def test_sanitize_powershell_preserves_safe_chars(self):
        """PowerShell sanitization preserves safe characters."""
        from app.infrastructure.notifications import _sanitize_for_powershell

        safe_text = "Hello World! 123 @ # % & * () - _ + = [] {} ; : , . < > ?"
        result = _sanitize_for_powershell(safe_text)
        assert result == safe_text
