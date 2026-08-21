# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour le module monitoring.
"""

import pytest
import time
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from app.infrastructure.monitoring import (
    HealthStatus,
    FailureType,
    HealthCheck,
    FailureEvent,
    MonitoringStatus,
    HealthMonitor,
    get_health_monitor,
    check_disk_space,
    check_memory_usage,
    check_api_connectivity,
)


# ============================================================================
# TESTS HEALTH CHECK
# ============================================================================

class TestHealthCheck:
    """Tests pour HealthCheck."""

    def test_health_check_creation(self):
        """Test création d'un health check."""
        check = HealthCheck(
            component="test",
            status=HealthStatus.HEALTHY,
            message="OK"
        )

        assert check.component == "test"
        assert check.status == HealthStatus.HEALTHY
        assert check.message == "OK"
        assert check.timestamp  # Auto-rempli

    def test_health_check_with_details(self):
        """Test health check avec détails."""
        check = HealthCheck(
            component="api",
            status=HealthStatus.DEGRADED,
            message="Latence élevée",
            details={"latency_ms": 500}
        )

        assert check.details["latency_ms"] == 500


# ============================================================================
# TESTS FAILURE EVENT
# ============================================================================

class TestFailureEvent:
    """Tests pour FailureEvent."""

    def test_failure_event_creation(self):
        """Test création d'un événement d'échec."""
        event = FailureEvent(
            component="daemon",
            failure_type=FailureType.TIMEOUT,
            message="Timeout after 30s"
        )

        assert event.component == "daemon"
        assert event.failure_type == FailureType.TIMEOUT
        assert event.resolved is False
        assert event.timestamp

    def test_failure_types(self):
        """Test différents types d'échecs."""
        types = [
            FailureType.TIMEOUT,
            FailureType.EXCEPTION,
            FailureType.THRESHOLD_EXCEEDED,
            FailureType.SILENT_FAILURE,
            FailureType.CONNECTIVITY,
            FailureType.RATE_LIMIT,
        ]

        for ft in types:
            event = FailureEvent(
                component="test",
                failure_type=ft,
                message="Test"
            )
            assert event.failure_type == ft


# ============================================================================
# TESTS HEALTH MONITOR
# ============================================================================

class TestHealthMonitor:
    """Tests pour HealthMonitor."""

    @pytest.fixture
    def monitor(self):
        """Crée un moniteur de test."""
        return HealthMonitor(check_interval=0.1)

    def test_register_component(self, monitor):
        """Test enregistrement de composant."""
        def check_func():
            return HealthCheck(
                component="test",
                status=HealthStatus.HEALTHY,
                message="OK"
            )

        monitor.register_component("test", check_func)
        assert "test" in monitor._components

    def test_unregister_component(self, monitor):
        """Test désenregistrement de composant."""
        def check_func():
            return HealthCheck(
                component="test",
                status=HealthStatus.HEALTHY
            )

        monitor.register_component("test", check_func)
        monitor.unregister_component("test")
        assert "test" not in monitor._components

    def test_heartbeat(self, monitor):
        """Test heartbeat."""
        monitor.heartbeat("daemon")
        assert "daemon" in monitor._heartbeats
        assert monitor._failure_counts.get("daemon", 0) == 0

    def test_record_failure(self, monitor):
        """Test enregistrement d'échec."""
        monitor.record_failure(
            "api",
            FailureType.CONNECTIVITY,
            "Connection refused"
        )

        assert monitor._failure_counts["api"] == 1
        history = monitor.get_failure_history("api")
        assert len(history) == 1
        assert history[0].failure_type == FailureType.CONNECTIVITY

    def test_record_success(self, monitor):
        """Test enregistrement de succès."""
        monitor._failure_counts["api"] = 5
        monitor.record_success("api")

        assert monitor._failure_counts["api"] == 0

    def test_get_status(self, monitor):
        """Test récupération du statut."""
        def healthy_check():
            return HealthCheck(
                component="test",
                status=HealthStatus.HEALTHY,
                message="OK"
            )

        monitor.register_component("test", healthy_check)
        status = monitor.get_status()

        assert isinstance(status, MonitoringStatus)
        assert status.healthy is True
        assert "test" in status.components

    def test_get_status_unhealthy(self, monitor):
        """Test statut avec composant malsain."""
        def unhealthy_check():
            return HealthCheck(
                component="broken",
                status=HealthStatus.UNHEALTHY,
                message="Service down"
            )

        monitor.register_component("broken", unhealthy_check)
        status = monitor.get_status()

        assert status.healthy is False
        assert status.status == HealthStatus.UNHEALTHY
        assert len(status.issues) > 0

    def test_get_status_degraded(self, monitor):
        """Test statut dégradé."""
        def degraded_check():
            return HealthCheck(
                component="slow",
                status=HealthStatus.DEGRADED,
                message="High latency"
            )

        monitor.register_component("slow", degraded_check)
        status = monitor.get_status()

        assert status.status == HealthStatus.DEGRADED

    def test_failure_threshold_alert(self, monitor):
        """Test alerte quand seuil atteint."""
        alert_callback = Mock()
        monitor.alert_callback = alert_callback
        monitor.failure_threshold = 3

        for _ in range(3):
            monitor.record_failure(
                "failing",
                FailureType.EXCEPTION,
                "Error"
            )

        alert_callback.assert_called_once()
        event = alert_callback.call_args[0][0]
        assert event.component == "failing"

    def test_get_failure_history(self, monitor):
        """Test historique des échecs."""
        for i in range(5):
            monitor.record_failure(
                "test",
                FailureType.EXCEPTION,
                f"Error {i}"
            )

        history = monitor.get_failure_history()
        assert len(history) == 5

        limited = monitor.get_failure_history(limit=2)
        assert len(limited) == 2

    def test_get_failure_history_filtered(self, monitor):
        """Test historique filtré par composant."""
        monitor.record_failure("api", FailureType.CONNECTIVITY, "Error 1")
        monitor.record_failure("daemon", FailureType.TIMEOUT, "Error 2")
        monitor.record_failure("api", FailureType.CONNECTIVITY, "Error 3")

        history = monitor.get_failure_history(component="api")
        assert len(history) == 2

    def test_get_component_stats(self, monitor):
        """Test statistiques par composant."""
        def check_func():
            return HealthCheck(
                component="test",
                status=HealthStatus.HEALTHY
            )

        monitor.register_component("test", check_func)
        monitor.record_failure("test", FailureType.EXCEPTION, "Error")
        monitor.record_failure("test", FailureType.EXCEPTION, "Error")

        stats = monitor.get_component_stats("test")
        assert stats["failure_count"] == 2
        assert stats["total_failures"] == 2
        assert stats["registered"] is True


# ============================================================================
# TESTS MONITORING LIFECYCLE
# ============================================================================

class TestMonitoringLifecycle:
    """Tests pour le cycle de vie du monitoring."""

    def test_start_stop(self):
        """Test démarrage et arrêt."""
        monitor = HealthMonitor(check_interval=0.1)

        monitor.start()
        assert monitor._running is True
        assert monitor._thread is not None

        time.sleep(0.05)

        monitor.stop()
        assert monitor._running is False

    def test_double_start(self):
        """Test double démarrage (devrait être ignoré)."""
        monitor = HealthMonitor(check_interval=0.1)

        monitor.start()
        thread1 = monitor._thread

        monitor.start()  # Devrait être ignoré
        thread2 = monitor._thread

        assert thread1 is thread2

        monitor.stop()

    def test_monitor_runs_checks(self):
        """Test que le monitor exécute les checks."""
        monitor = HealthMonitor(check_interval=0.1)
        check_count = {"count": 0}

        def counting_check():
            check_count["count"] += 1
            return HealthCheck(
                component="counter",
                status=HealthStatus.HEALTHY
            )

        monitor.register_component("counter", counting_check)
        monitor.start()

        time.sleep(0.25)
        monitor.stop()

        assert check_count["count"] >= 2


# ============================================================================
# TESTS HEARTBEAT MONITORING
# ============================================================================

class TestHeartbeatMonitoring:
    """Tests pour le monitoring par heartbeat."""

    def test_heartbeat_timeout_detection(self):
        """Test détection timeout heartbeat."""
        monitor = HealthMonitor(check_interval=0.1)

        # Enregistrer un heartbeat ancien
        monitor._heartbeats["stale"] = datetime.now() - timedelta(seconds=60)

        issues = monitor._check_heartbeats()
        assert len(issues) > 0
        assert "stale" in issues[0]

    def test_heartbeat_fresh(self):
        """Test heartbeat récent (pas de problème)."""
        monitor = HealthMonitor(check_interval=1.0)

        monitor.heartbeat("fresh")
        issues = monitor._check_heartbeats()
        assert len(issues) == 0


# ============================================================================
# TESTS HEALTH CHECKS PRÉDÉFINIS
# ============================================================================

class TestPredefinedHealthChecks:
    """Tests pour les health checks prédéfinis."""

    def test_check_disk_space(self):
        """Test check espace disque."""
        check_func = check_disk_space("/", 80, 95)
        result = check_func()

        assert isinstance(result, HealthCheck)
        assert result.component == "disk_space"
        assert result.status in [HealthStatus.HEALTHY, HealthStatus.DEGRADED, HealthStatus.UNHEALTHY]
        assert "usage_percent" in result.details

    def test_check_disk_space_with_thresholds(self):
        """Test check disque avec seuils."""
        check_func = check_disk_space("/", warning_threshold=1, critical_threshold=2)
        result = check_func()

        # Avec des seuils très bas, ça devrait être critique
        assert result.status in [HealthStatus.DEGRADED, HealthStatus.UNHEALTHY]

    @pytest.mark.skipif(
        True,  # Skip car psutil peut ne pas être installé
        reason="psutil optionnel"
    )
    def test_check_memory_usage(self):
        """Test check mémoire (si psutil disponible)."""
        import importlib.util
        if importlib.util.find_spec("psutil") is None:
            pytest.skip("psutil non disponible")
        check_func = check_memory_usage(80, 95)
        result = check_func()

        assert isinstance(result, HealthCheck)
        assert result.component == "memory"
        assert "usage_percent" in result.details

    def test_check_api_connectivity_success(self):
        """Test check connectivité API (succès)."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__ = Mock()
            mock_urlopen.return_value.__exit__ = Mock(return_value=False)

            check_func = check_api_connectivity("https://api.example.com", 5.0, "test_api")
            result = check_func()

            assert result.component == "test_api"
            assert result.status == HealthStatus.HEALTHY

    def test_check_api_connectivity_failure(self):
        """Test check connectivité API (échec)."""
        import urllib.error

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

            check_func = check_api_connectivity("https://api.example.com", 5.0, "test_api")
            result = check_func()

            assert result.status == HealthStatus.UNHEALTHY
            assert "inaccessible" in result.message.lower()


# ============================================================================
# TESTS SINGLETON
# ============================================================================

class TestSingleton:
    """Tests pour le singleton."""

    def test_get_health_monitor_singleton(self):
        """Test singleton health monitor."""
        import app.infrastructure.monitoring as monitoring_module
        monitoring_module._health_monitor = None

        monitor1 = get_health_monitor()
        monitor2 = get_health_monitor()

        assert monitor1 is monitor2


# ============================================================================
# TESTS EDGE CASES
# ============================================================================

class TestEdgeCases:
    """Tests pour les cas limites."""

    def test_check_func_exception(self):
        """Test exception dans check func."""
        monitor = HealthMonitor(check_interval=0.1)

        def failing_check():
            raise RuntimeError("Check failed")

        monitor.register_component("failing", failing_check)
        status = monitor.get_status()

        assert "failing" in status.components
        assert status.components["failing"].status == HealthStatus.UNKNOWN

    def test_alert_callback_exception(self):
        """Test exception dans callback d'alerte."""
        monitor = HealthMonitor(check_interval=0.1)

        def failing_callback(event):
            raise RuntimeError("Callback failed")

        monitor.alert_callback = failing_callback
        monitor.failure_threshold = 1

        # Ne devrait pas lever d'exception
        monitor.record_failure("test", FailureType.EXCEPTION, "Error")

    def test_empty_failure_history(self):
        """Test historique vide."""
        monitor = HealthMonitor()
        history = monitor.get_failure_history()
        assert history == []

    def test_component_stats_unregistered(self):
        """Test stats composant non enregistré."""
        monitor = HealthMonitor()
        stats = monitor.get_component_stats("unknown")

        assert stats["registered"] is False
        assert stats["failure_count"] == 0
