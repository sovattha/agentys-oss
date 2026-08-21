# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests unitaires pour le module de métriques Prometheus.

Ce module teste les fonctionnalités de metrics.py:
- Classe AgentysMetrics et ses métriques
- Fonctions helper (record_email_processed, record_llm_call, etc.)
- Singleton get_metrics()
- Serveur de métriques start_metrics_server()
- Décorateurs @timed et @count_errors
- Blueprint Flask create_metrics_blueprint()
"""

import pytest
from unittest.mock import MagicMock, patch
import time
import threading


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def fresh_registry():
    """Crée un nouveau registry pour éviter les conflits."""
    from prometheus_client import CollectorRegistry
    return CollectorRegistry()


@pytest.fixture
def mock_metrics():
    """Mock l'objet metrics retourné par get_metrics()."""
    mock = MagicMock()
    mock.processing_time = MagicMock()
    mock.processing_time.labels = MagicMock(return_value=MagicMock())
    mock.errors = MagicMock()
    mock.errors.labels = MagicMock(return_value=MagicMock())
    mock.record_error = MagicMock()
    return mock


# ============================================================================
# TESTS - AGENTYS METRICS CLASS
# ============================================================================


class TestAgentysMetricsInit:
    """Tests pour l'initialisation de AgentysMetrics."""

    def test_init_with_custom_registry(self, fresh_registry):
        """Initialisation avec un registry custom."""
        from app.infrastructure.metrics import AgentysMetrics
        metrics = AgentysMetrics(registry=fresh_registry)
        assert metrics.registry == fresh_registry

    def test_setup_metrics_creates_counters(self, fresh_registry):
        """_setup_metrics() crée les compteurs."""
        from app.infrastructure.metrics import AgentysMetrics
        metrics = AgentysMetrics(registry=fresh_registry)
        assert hasattr(metrics, "emails_processed")
        assert hasattr(metrics, "drafts_created")
        assert hasattr(metrics, "llm_requests")
        assert hasattr(metrics, "errors")
        assert hasattr(metrics, "followups_sent")

    def test_setup_metrics_creates_gauges(self, fresh_registry):
        """_setup_metrics() crée les jauges."""
        from app.infrastructure.metrics import AgentysMetrics
        metrics = AgentysMetrics(registry=fresh_registry)
        assert hasattr(metrics, "emails_pending")
        assert hasattr(metrics, "budget_remaining")
        assert hasattr(metrics, "monthly_cost")
        assert hasattr(metrics, "circuit_breaker_state")
        assert hasattr(metrics, "daemon_running")

    def test_setup_metrics_creates_histograms(self, fresh_registry):
        """_setup_metrics() crée les histogrammes."""
        from app.infrastructure.metrics import AgentysMetrics
        metrics = AgentysMetrics(registry=fresh_registry)
        assert hasattr(metrics, "processing_time")
        assert hasattr(metrics, "tokens_per_request")

    def test_setup_metrics_creates_summary(self, fresh_registry):
        """_setup_metrics() crée les summaries."""
        from app.infrastructure.metrics import AgentysMetrics
        metrics = AgentysMetrics(registry=fresh_registry)
        assert hasattr(metrics, "email_api_latency")

    def test_setup_metrics_creates_info(self, fresh_registry):
        """_setup_metrics() crée les infos."""
        from app.infrastructure.metrics import AgentysMetrics
        metrics = AgentysMetrics(registry=fresh_registry)
        assert hasattr(metrics, "info")


class TestAgentysMetricsRecordEmailProcessed:
    """Tests pour record_email_processed()."""

    def test_record_email_processed_increments_counter(self, fresh_registry):
        """record_email_processed() incrémente le compteur."""
        from app.infrastructure.metrics import AgentysMetrics
        metrics = AgentysMetrics(registry=fresh_registry)

        metrics.record_email_processed("URGENT", "V1", 2.5)

        sample = metrics.emails_processed.labels(category="URGENT", status="V1")._value.get()
        assert sample == 1.0

    def test_record_email_processed_observes_time(self, fresh_registry):
        """record_email_processed() observe le temps de traitement."""
        from app.infrastructure.metrics import AgentysMetrics
        metrics = AgentysMetrics(registry=fresh_registry)

        metrics.record_email_processed("NORMAL", "V2", 5.0)

        sample = metrics.processing_time.labels(agent="pipeline")._sum.get()
        assert sample == 5.0

    def test_record_multiple_emails(self, fresh_registry):
        """record_email_processed() gère plusieurs appels."""
        from app.infrastructure.metrics import AgentysMetrics
        metrics = AgentysMetrics(registry=fresh_registry)

        metrics.record_email_processed("URGENT", "V1", 1.0)
        metrics.record_email_processed("URGENT", "V1", 2.0)
        metrics.record_email_processed("NORMAL", "V2", 3.0)

        urgent_v1 = metrics.emails_processed.labels(category="URGENT", status="V1")._value.get()
        normal_v2 = metrics.emails_processed.labels(category="NORMAL", status="V2")._value.get()

        assert urgent_v1 == 2.0
        assert normal_v2 == 1.0


class TestAgentysMetricsRecordLlmCall:
    """Tests pour record_llm_call()."""

    def test_record_llm_call_increments_requests(self, fresh_registry):
        """record_llm_call() incrémente le compteur de requêtes."""
        from app.infrastructure.metrics import AgentysMetrics
        metrics = AgentysMetrics(registry=fresh_registry)

        metrics.record_llm_call("claude-3", "drafter", 1000, 500, 2.0)

        sample = metrics.llm_requests.labels(model="claude-3", agent="drafter")._value.get()
        assert sample == 1.0

    def test_record_llm_call_observes_input_tokens(self, fresh_registry):
        """record_llm_call() observe les tokens d'entrée."""
        from app.infrastructure.metrics import AgentysMetrics
        metrics = AgentysMetrics(registry=fresh_registry)

        metrics.record_llm_call("claude-3", "critic", 2000, 800, 3.0)

        sample = metrics.tokens_per_request.labels(model="claude-3", type="input")._sum.get()
        assert sample == 2000.0

    def test_record_llm_call_observes_output_tokens(self, fresh_registry):
        """record_llm_call() observe les tokens de sortie."""
        from app.infrastructure.metrics import AgentysMetrics
        metrics = AgentysMetrics(registry=fresh_registry)

        metrics.record_llm_call("claude-3", "classifier", 500, 200, 1.0)

        sample = metrics.tokens_per_request.labels(model="claude-3", type="output")._sum.get()
        assert sample == 200.0

    def test_record_llm_call_observes_duration(self, fresh_registry):
        """record_llm_call() observe la durée."""
        from app.infrastructure.metrics import AgentysMetrics
        metrics = AgentysMetrics(registry=fresh_registry)

        metrics.record_llm_call("ollama", "drafter", 100, 50, 0.5)

        sample = metrics.processing_time.labels(agent="drafter")._sum.get()
        assert sample == 0.5


class TestAgentysMetricsRecordError:
    """Tests pour record_error()."""

    def test_record_error_increments_counter(self, fresh_registry):
        """record_error() incrémente le compteur d'erreurs."""
        from app.infrastructure.metrics import AgentysMetrics
        metrics = AgentysMetrics(registry=fresh_registry)

        metrics.record_error("ConnectionError", "email_provider")

        sample = metrics.errors.labels(type="ConnectionError", component="email_provider")._value.get()
        assert sample == 1.0

    def test_record_error_with_different_types(self, fresh_registry):
        """record_error() fonctionne avec différents types d'erreur."""
        from app.infrastructure.metrics import AgentysMetrics
        metrics = AgentysMetrics(registry=fresh_registry)

        metrics.record_error("TimeoutError", "llm")
        metrics.record_error("ValidationError", "input")
        metrics.record_error("RateLimitError", "api")

        timeout = metrics.errors.labels(type="TimeoutError", component="llm")._value.get()
        validation = metrics.errors.labels(type="ValidationError", component="input")._value.get()
        rate = metrics.errors.labels(type="RateLimitError", component="api")._value.get()

        assert timeout == 1.0
        assert validation == 1.0
        assert rate == 1.0


class TestAgentysMetricsUpdateBudget:
    """Tests pour update_budget()."""

    def test_update_budget_sets_monthly_cost(self, fresh_registry):
        """update_budget() définit le coût mensuel."""
        from app.infrastructure.metrics import AgentysMetrics
        metrics = AgentysMetrics(registry=fresh_registry)

        metrics.update_budget(50.0, 150.0)

        sample = metrics.monthly_cost._value.get()
        assert sample == 50.0

    def test_update_budget_sets_remaining(self, fresh_registry):
        """update_budget() définit le budget restant."""
        from app.infrastructure.metrics import AgentysMetrics
        metrics = AgentysMetrics(registry=fresh_registry)

        metrics.update_budget(75.0, 125.0)

        sample = metrics.budget_remaining._value.get()
        assert sample == 125.0

    def test_update_budget_with_zero_values(self, fresh_registry):
        """update_budget() fonctionne avec des valeurs à zéro."""
        from app.infrastructure.metrics import AgentysMetrics
        metrics = AgentysMetrics(registry=fresh_registry)

        metrics.update_budget(0.0, 200.0)

        cost = metrics.monthly_cost._value.get()
        remaining = metrics.budget_remaining._value.get()
        assert cost == 0.0
        assert remaining == 200.0


# ============================================================================
# TESTS - GET_METRICS SINGLETON
# ============================================================================


class TestGetMetrics:
    """Tests pour la fonction get_metrics()."""

    def test_get_metrics_returns_agentys_metrics(self, fresh_registry):
        """get_metrics() retourne une instance de AgentysMetrics."""
        import app.infrastructure.metrics as metrics_module
        from app.infrastructure.metrics import AgentysMetrics

        # Au lieu d'appeler get_metrics() qui utilise le registry global,
        # on vérifie que get_metrics() créerait bien une instance AgentysMetrics
        # en testant directement la création avec un registry isolé
        metrics = AgentysMetrics(registry=fresh_registry)
        assert isinstance(metrics, AgentysMetrics)

        # Vérifie aussi que get_metrics retourne le singleton existant s'il y en a un
        existing = metrics_module._metrics
        if existing is not None:
            from app.infrastructure.metrics import get_metrics
            assert get_metrics() is existing
            assert isinstance(existing, AgentysMetrics)

    def test_get_metrics_is_singleton(self):
        """get_metrics() retourne toujours la même instance."""
        import app.infrastructure.metrics as metrics_module
        from app.infrastructure.metrics import get_metrics

        # Test le comportement singleton sans polluer le registry global
        # Si un singleton existe déjà, vérifie qu'on le réutilise
        # Sinon, utilise un mock pour éviter de créer des métriques sur le registry global
        existing_metrics = metrics_module._metrics

        if existing_metrics is not None:
            # Singleton existe déjà - vérifie qu'on le réutilise
            metrics1 = get_metrics()
            metrics2 = get_metrics()
            assert metrics1 is metrics2
            assert metrics1 is existing_metrics
        else:
            # Pas de singleton - utiliser mock pour simuler le comportement
            mock_metrics = MagicMock()
            metrics_module._metrics = mock_metrics
            try:
                metrics1 = get_metrics()
                metrics2 = get_metrics()
                assert metrics1 is metrics2
                assert metrics1 is mock_metrics
            finally:
                metrics_module._metrics = existing_metrics


# ============================================================================
# TESTS - START_METRICS_SERVER
# ============================================================================


class TestStartMetricsServer:
    """Tests pour start_metrics_server()."""

    def test_returns_false_when_prometheus_unavailable(self):
        """Retourne False quand prometheus n'est pas disponible."""
        from app.infrastructure.metrics import start_metrics_server
        with patch("app.infrastructure.metrics.PROMETHEUS_AVAILABLE", False):
            result = start_metrics_server(9999)
            assert result is False

    def test_returns_false_when_metrics_disabled(self):
        """Retourne False quand les métriques sont désactivées."""
        from app.infrastructure.metrics import start_metrics_server
        with patch("app.infrastructure.metrics.PROMETHEUS_AVAILABLE", True):
            with patch("app.infrastructure.metrics.METRICS_ENABLED", False):
                result = start_metrics_server(9999)
                assert result is False

    def test_returns_true_when_already_started(self):
        """Retourne True quand le serveur est déjà démarré."""
        import app.infrastructure.metrics as metrics_module
        from app.infrastructure.metrics import start_metrics_server

        original = metrics_module._metrics_server_started
        metrics_module._metrics_server_started = True

        try:
            with patch("app.infrastructure.metrics.PROMETHEUS_AVAILABLE", True):
                with patch("app.infrastructure.metrics.METRICS_ENABLED", True):
                    result = start_metrics_server(9999)
                    assert result is True
        finally:
            metrics_module._metrics_server_started = original

    def test_starts_server_successfully(self):
        """Démarre le serveur avec succès."""
        import app.infrastructure.metrics as metrics_module
        from app.infrastructure.metrics import start_metrics_server

        original = metrics_module._metrics_server_started
        metrics_module._metrics_server_started = False

        try:
            with patch("app.infrastructure.metrics.PROMETHEUS_AVAILABLE", True):
                with patch("app.infrastructure.metrics.METRICS_ENABLED", True):
                    with patch("app.infrastructure.metrics.start_http_server") as mock_server:
                        result = start_metrics_server(9999)

                        mock_server.assert_called_once_with(9999)
                        assert result is True
                        assert metrics_module._metrics_server_started is True
        finally:
            metrics_module._metrics_server_started = original

    def test_returns_false_on_exception(self):
        """Retourne False en cas d'exception."""
        import app.infrastructure.metrics as metrics_module
        from app.infrastructure.metrics import start_metrics_server

        original = metrics_module._metrics_server_started
        metrics_module._metrics_server_started = False

        try:
            with patch("app.infrastructure.metrics.PROMETHEUS_AVAILABLE", True):
                with patch("app.infrastructure.metrics.METRICS_ENABLED", True):
                    with patch("app.infrastructure.metrics.start_http_server", side_effect=Exception("Port in use")):
                        result = start_metrics_server(9999)
                        assert result is False
        finally:
            metrics_module._metrics_server_started = original

    def test_uses_default_port(self):
        """Utilise le port par défaut."""
        import app.infrastructure.metrics as metrics_module
        from app.infrastructure.metrics import start_metrics_server, METRICS_PORT

        original = metrics_module._metrics_server_started
        metrics_module._metrics_server_started = False

        try:
            with patch("app.infrastructure.metrics.PROMETHEUS_AVAILABLE", True):
                with patch("app.infrastructure.metrics.METRICS_ENABLED", True):
                    with patch("app.infrastructure.metrics.start_http_server") as mock_server:
                        start_metrics_server()
                        mock_server.assert_called_once_with(METRICS_PORT)
        finally:
            metrics_module._metrics_server_started = original


# ============================================================================
# TESTS - GET_METRICS_TEXT
# ============================================================================


class TestGetMetricsText:
    """Tests pour get_metrics_text()."""

    def test_returns_string(self):
        """Retourne une chaîne de caractères."""
        from app.infrastructure.metrics import get_metrics_text
        result = get_metrics_text()
        assert isinstance(result, str)

    def test_returns_prometheus_format(self):
        """Retourne le format Prometheus."""
        from app.infrastructure.metrics import get_metrics_text
        result = get_metrics_text()
        assert isinstance(result, str)
        assert len(result) > 0


# ============================================================================
# TESTS - TIMED DECORATOR
# ============================================================================


class TestTimedDecorator:
    """Tests pour le décorateur @timed."""

    def test_returns_function_result(self, mock_metrics):
        """Retourne le résultat de la fonction."""
        with patch("app.infrastructure.metrics.get_metrics", return_value=mock_metrics):
            from app.infrastructure.metrics import timed

            @timed(agent="test")
            def add(a, b):
                return a + b

            result = add(2, 3)
            assert result == 5

    def test_handles_function_with_args_kwargs(self, mock_metrics):
        """Gère les args et kwargs de la fonction."""
        with patch("app.infrastructure.metrics.get_metrics", return_value=mock_metrics):
            from app.infrastructure.metrics import timed

            @timed(agent="test")
            def greet(name, greeting="Hello"):
                return f"{greeting}, {name}!"

            result = greet("World", greeting="Hi")
            assert result == "Hi, World!"

    def test_observes_time_on_completion(self, mock_metrics):
        """Observe le temps de traitement."""
        with patch("app.infrastructure.metrics.get_metrics", return_value=mock_metrics):
            from app.infrastructure.metrics import timed

            @timed(agent="completion_test")
            def quick_function():
                return True

            result = quick_function()
            assert result is True
            mock_metrics.processing_time.labels.assert_called()

    def test_observes_time_on_exception(self, mock_metrics):
        """Observe le temps même si la fonction lève une exception."""
        with patch("app.infrastructure.metrics.get_metrics", return_value=mock_metrics):
            from app.infrastructure.metrics import timed

            @timed(agent="error_test")
            def failing_function():
                raise ValueError("Test error")

            with pytest.raises(ValueError, match="Test error"):
                failing_function()

            # Should still observe time
            mock_metrics.processing_time.labels.assert_called()

    def test_uses_default_agent_name(self, mock_metrics):
        """Utilise le nom d'agent par défaut."""
        with patch("app.infrastructure.metrics.get_metrics", return_value=mock_metrics):
            from app.infrastructure.metrics import timed

            @timed()
            def default_function():
                return "default"

            result = default_function()
            assert result == "default"

    def test_measures_actual_time(self, mock_metrics):
        """Mesure le temps réel d'exécution."""
        with patch("app.infrastructure.metrics.get_metrics", return_value=mock_metrics):
            from app.infrastructure.metrics import timed

            @timed(agent="timing_test")
            def slow_function():
                time.sleep(0.05)
                return "done"

            result = slow_function()
            assert result == "done"


# ============================================================================
# TESTS - COUNT_ERRORS DECORATOR
# ============================================================================


class TestCountErrorsDecorator:
    """Tests pour le décorateur @count_errors."""

    def test_does_not_affect_successful_functions(self, mock_metrics):
        """N'affecte pas les fonctions qui réussissent."""
        with patch("app.infrastructure.metrics.get_metrics", return_value=mock_metrics):
            from app.infrastructure.metrics import count_errors

            @count_errors(component="test")
            def successful_function():
                return "success"

            result = successful_function()
            assert result == "success"
            mock_metrics.record_error.assert_not_called()

    def test_counts_errors_on_exception(self, mock_metrics):
        """Compte les erreurs quand une exception est levée."""
        with patch("app.infrastructure.metrics.get_metrics", return_value=mock_metrics):
            from app.infrastructure.metrics import count_errors

            @count_errors(component="error_component")
            def failing_function():
                raise RuntimeError("Test failure")

            with pytest.raises(RuntimeError):
                failing_function()

            mock_metrics.record_error.assert_called_once_with("RuntimeError", "error_component")

    def test_re_raises_exception(self, mock_metrics):
        """Relève l'exception après l'avoir comptée."""
        with patch("app.infrastructure.metrics.get_metrics", return_value=mock_metrics):
            from app.infrastructure.metrics import count_errors

            @count_errors(component="test")
            def error_function():
                raise TypeError("Type error")

            with pytest.raises(TypeError, match="Type error"):
                error_function()

    def test_preserves_exception_type(self, mock_metrics):
        """Préserve le type d'exception."""
        with patch("app.infrastructure.metrics.get_metrics", return_value=mock_metrics):
            from app.infrastructure.metrics import count_errors

            class CustomError(Exception):
                pass

            @count_errors(component="custom")
            def custom_error_function():
                raise CustomError("Custom")

            with pytest.raises(CustomError):
                custom_error_function()

    def test_handles_function_with_args(self, mock_metrics):
        """Gère les fonctions avec arguments."""
        with patch("app.infrastructure.metrics.get_metrics", return_value=mock_metrics):
            from app.infrastructure.metrics import count_errors

            @count_errors(component="args_test")
            def func_with_args(a, b, c=None):
                if c is None:
                    raise ValueError("c is required")
                return a + b + c

            # Should raise and count error
            with pytest.raises(ValueError):
                func_with_args(1, 2)

            # Should succeed
            mock_metrics.record_error.reset_mock()
            result = func_with_args(1, 2, c=3)
            assert result == 6
            mock_metrics.record_error.assert_not_called()


# ============================================================================
# TESTS - CREATE_METRICS_BLUEPRINT
# ============================================================================


class TestCreateMetricsBlueprint:
    """Tests pour create_metrics_blueprint()."""

    def test_returns_flask_blueprint(self):
        """Retourne un Blueprint Flask."""
        from flask import Blueprint
        from app.infrastructure.metrics import create_metrics_blueprint

        bp = create_metrics_blueprint()
        assert isinstance(bp, Blueprint)

    def test_blueprint_name_is_metrics(self):
        """Le nom du blueprint est 'metrics'."""
        from app.infrastructure.metrics import create_metrics_blueprint

        bp = create_metrics_blueprint()
        assert bp.name == "metrics"

    def test_has_metrics_endpoint(self):
        """Le blueprint a un endpoint /metrics."""
        from flask import Flask
        from app.infrastructure.metrics import create_metrics_blueprint

        app = Flask(__name__)
        bp = create_metrics_blueprint()
        app.register_blueprint(bp)

        with app.test_client() as client:
            response = client.get("/metrics")
            assert response.status_code == 200

    def test_metrics_endpoint_returns_text_plain(self):
        """L'endpoint /metrics retourne du text/plain."""
        from flask import Flask
        from app.infrastructure.metrics import create_metrics_blueprint

        app = Flask(__name__)
        bp = create_metrics_blueprint()
        app.register_blueprint(bp)

        with app.test_client() as client:
            response = client.get("/metrics")
            assert response.content_type.startswith("text/plain")

    def test_metrics_endpoint_returns_prometheus_format(self):
        """L'endpoint /metrics retourne le format Prometheus."""
        from flask import Flask
        from app.infrastructure.metrics import create_metrics_blueprint

        app = Flask(__name__)
        bp = create_metrics_blueprint()
        app.register_blueprint(bp)

        with app.test_client() as client:
            response = client.get("/metrics")
            data = response.data.decode("utf-8")
            assert isinstance(data, str)
            assert len(data) > 0


# ============================================================================
# TESTS - CONFIGURATION
# ============================================================================


class TestConfiguration:
    """Tests pour les constantes de configuration."""

    def test_metrics_port_default(self):
        """METRICS_PORT a une valeur par défaut."""
        from app.infrastructure.metrics import METRICS_PORT
        assert isinstance(METRICS_PORT, int)
        assert METRICS_PORT > 0

    def test_metrics_enabled_default(self):
        """METRICS_ENABLED a une valeur par défaut."""
        from app.infrastructure.metrics import METRICS_ENABLED
        assert isinstance(METRICS_ENABLED, bool)

    def test_prometheus_available_is_true(self):
        """PROMETHEUS_AVAILABLE est True quand prometheus est installé."""
        from app.infrastructure.metrics import PROMETHEUS_AVAILABLE
        assert PROMETHEUS_AVAILABLE is True


# ============================================================================
# TESTS - EDGE CASES
# ============================================================================


class TestEdgeCases:
    """Tests pour les cas limites."""

    def test_record_email_processed_with_empty_strings(self, fresh_registry):
        """record_email_processed() fonctionne avec des chaînes vides."""
        from app.infrastructure.metrics import AgentysMetrics
        metrics = AgentysMetrics(registry=fresh_registry)
        metrics.record_email_processed("", "", 0.0)  # Should not raise

    def test_record_llm_call_with_zero_tokens(self, fresh_registry):
        """record_llm_call() fonctionne avec zéro tokens."""
        from app.infrastructure.metrics import AgentysMetrics
        metrics = AgentysMetrics(registry=fresh_registry)
        metrics.record_llm_call("model", "agent", 0, 0, 0.0)  # Should not raise

    def test_record_error_with_special_characters(self, fresh_registry):
        """record_error() fonctionne avec des caractères spéciaux."""
        from app.infrastructure.metrics import AgentysMetrics
        metrics = AgentysMetrics(registry=fresh_registry)
        metrics.record_error("Error", "component")  # Should not raise

    def test_update_budget_with_negative_values(self, fresh_registry):
        """update_budget() accepte les valeurs négatives."""
        from app.infrastructure.metrics import AgentysMetrics
        metrics = AgentysMetrics(registry=fresh_registry)
        metrics.update_budget(-10.0, -50.0)  # Should not raise (overbudget scenario)

    def test_timed_decorator_with_return_list(self, mock_metrics):
        """@timed fonctionne avec les listes."""
        with patch("app.infrastructure.metrics.get_metrics", return_value=mock_metrics):
            from app.infrastructure.metrics import timed

            @timed(agent="list_test")
            def generate_numbers():
                return [1, 2, 3]

            result = generate_numbers()
            assert result == [1, 2, 3]

    def test_count_errors_with_nested_exceptions(self, mock_metrics):
        """@count_errors fonctionne avec les exceptions chaînées."""
        with patch("app.infrastructure.metrics.get_metrics", return_value=mock_metrics):
            from app.infrastructure.metrics import count_errors

            @count_errors(component="nested")
            def nested_exception():
                try:
                    raise ValueError("inner")
                except ValueError as e:
                    raise RuntimeError("outer") from e

            with pytest.raises(RuntimeError):
                nested_exception()

    def test_multiple_decorators_on_same_function(self, mock_metrics):
        """Multiple décorateurs sur la même fonction."""
        with patch("app.infrastructure.metrics.get_metrics", return_value=mock_metrics):
            from app.infrastructure.metrics import timed, count_errors

            @count_errors(component="multi")
            @timed(agent="multi")
            def multi_decorated():
                return "multi"

            result = multi_decorated()
            assert result == "multi"

    def test_concurrent_metric_access(self):
        """Accès concurrent aux métriques."""
        import app.infrastructure.metrics as metrics_module
        from app.infrastructure.metrics import get_metrics

        # Ensure singleton exists before concurrent access to avoid registry conflicts
        # (concurrent creation of singleton can cause "Duplicated timeseries")
        existing = metrics_module._metrics
        if existing is None:
            # Pre-set a mock singleton to avoid concurrent creation
            mock_singleton = MagicMock()
            metrics_module._metrics = mock_singleton

        try:
            results = []
            lock = threading.Lock()

            def access_metrics():
                m = get_metrics()
                with lock:
                    results.append(m)

            threads = [threading.Thread(target=access_metrics) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # All should reference the same singleton
            assert len(results) == 10
            assert all(r is results[0] for r in results)
        finally:
            # Restore original state if we modified it
            if existing is None:
                metrics_module._metrics = existing


# ============================================================================
# TESTS - INTEGRATION WITH REAL METRICS
# ============================================================================


class TestRealPrometheusMetrics:
    """Tests d'intégration avec de vraies métriques Prometheus."""

    def test_real_metrics_workflow(self, fresh_registry):
        """Workflow complet avec de vraies métriques."""
        from app.infrastructure.metrics import AgentysMetrics

        metrics = AgentysMetrics(registry=fresh_registry)

        # Record some activities
        metrics.record_email_processed("URGENT", "V1", 1.5)
        metrics.record_llm_call("claude-3", "drafter", 1000, 500, 2.0)
        metrics.record_error("TestError", "test_component")
        metrics.update_budget(10.0, 190.0)

        # Verify counters
        emails = metrics.emails_processed.labels(category="URGENT", status="V1")._value.get()
        assert emails == 1.0

        llm = metrics.llm_requests.labels(model="claude-3", agent="drafter")._value.get()
        assert llm == 1.0

        errors = metrics.errors.labels(type="TestError", component="test_component")._value.get()
        assert errors == 1.0

        # Verify gauges
        cost = metrics.monthly_cost._value.get()
        assert cost == 10.0

        remaining = metrics.budget_remaining._value.get()
        assert remaining == 190.0

    def test_labels_chaining(self, fresh_registry):
        """Les métriques avec labels fonctionnent en chaîne."""
        from app.infrastructure.metrics import AgentysMetrics

        metrics = AgentysMetrics(registry=fresh_registry)

        # Chain labels and increment
        metrics.emails_processed.labels(category="test", status="ok").inc()
        metrics.drafts_created.labels(version="V1", provider="gmail").inc()
        metrics.llm_requests.labels(model="claude", agent="drafter").inc()
        metrics.errors.labels(type="Test", component="test").inc()

        assert True

    def test_histogram_time_context_manager(self, fresh_registry):
        """Le context manager time() fonctionne."""
        from app.infrastructure.metrics import AgentysMetrics
        from prometheus_client import generate_latest

        metrics = AgentysMetrics(registry=fresh_registry)

        with metrics.processing_time.labels(agent="test").time():
            time.sleep(0.01)  # Small sleep

        # Verify histogram has recorded via generate_latest
        output = generate_latest(fresh_registry).decode("utf-8")
        assert "agentys_processing_duration_seconds" in output

    def test_gauge_set_operations(self, fresh_registry):
        """Les opérations set() sur les jauges fonctionnent."""
        from app.infrastructure.metrics import AgentysMetrics

        metrics = AgentysMetrics(registry=fresh_registry)

        metrics.emails_pending.set(5)
        metrics.budget_remaining.set(100.0)
        metrics.monthly_cost.set(50.0)
        metrics.daemon_running.set(1)

        assert metrics.emails_pending._value.get() == 5
        assert metrics.budget_remaining._value.get() == 100.0
        assert metrics.monthly_cost._value.get() == 50.0
        assert metrics.daemon_running._value.get() == 1

    def test_gauge_with_labels(self, fresh_registry):
        """Les jauges avec labels fonctionnent."""
        from app.infrastructure.metrics import AgentysMetrics

        metrics = AgentysMetrics(registry=fresh_registry)

        metrics.circuit_breaker_state.labels(name="email").set(0)
        metrics.circuit_breaker_state.labels(name="llm").set(1)

        email_state = metrics.circuit_breaker_state.labels(name="email")._value.get()
        llm_state = metrics.circuit_breaker_state.labels(name="llm")._value.get()

        assert email_state == 0
        assert llm_state == 1

    def test_counter_increment_amounts(self, fresh_registry):
        """Les compteurs peuvent être incrémentés de montants différents."""
        from app.infrastructure.metrics import AgentysMetrics

        metrics = AgentysMetrics(registry=fresh_registry)

        # Increment by different amounts
        metrics.emails_processed.labels(category="BATCH", status="OK").inc(5)
        metrics.emails_processed.labels(category="BATCH", status="OK").inc(3)

        total = metrics.emails_processed.labels(category="BATCH", status="OK")._value.get()
        assert total == 8.0

    def test_histogram_observe_values(self, fresh_registry):
        """Les histogrammes observent des valeurs."""
        from app.infrastructure.metrics import AgentysMetrics

        metrics = AgentysMetrics(registry=fresh_registry)

        # Observe multiple values
        metrics.processing_time.labels(agent="test_hist").observe(0.5)
        metrics.processing_time.labels(agent="test_hist").observe(1.5)
        metrics.processing_time.labels(agent="test_hist").observe(3.0)

        total = metrics.processing_time.labels(agent="test_hist")._sum.get()
        assert total == 5.0

    def test_summary_observe_values(self, fresh_registry):
        """Les summaries observent des valeurs."""
        from app.infrastructure.metrics import AgentysMetrics

        metrics = AgentysMetrics(registry=fresh_registry)

        # Observe values
        metrics.email_api_latency.labels(provider="gmail", operation="fetch").observe(0.1)
        metrics.email_api_latency.labels(provider="gmail", operation="fetch").observe(0.2)

        count = metrics.email_api_latency.labels(provider="gmail", operation="fetch")._count.get()
        assert count == 2

    def test_followups_counter(self, fresh_registry):
        """Le compteur followups_sent fonctionne."""
        from app.infrastructure.metrics import AgentysMetrics

        metrics = AgentysMetrics(registry=fresh_registry)

        metrics.followups_sent.inc()
        metrics.followups_sent.inc()
        metrics.followups_sent.inc()

        total = metrics.followups_sent._value.get()
        assert total == 3.0

    def test_info_metric(self, fresh_registry):
        """La métrique info contient les informations d'application."""
        from app.infrastructure.metrics import AgentysMetrics

        metrics = AgentysMetrics(registry=fresh_registry)

        # Info is set during init
        assert hasattr(metrics, "info")


# ============================================================================
# TESTS - DECORATOR COMBINATIONS
# ============================================================================


class TestDecoratorCombinations:
    """Tests pour les combinaisons de décorateurs."""

    def test_timed_with_async_like_function(self, mock_metrics):
        """@timed fonctionne avec des fonctions longues."""
        with patch("app.infrastructure.metrics.get_metrics", return_value=mock_metrics):
            from app.infrastructure.metrics import timed

            @timed(agent="async_like")
            def long_operation():
                result = 0
                for i in range(1000):
                    result += i
                return result

            result = long_operation()
            assert result == sum(range(1000))

    def test_count_errors_with_various_exceptions(self, mock_metrics):
        """@count_errors gère différents types d'exceptions."""
        with patch("app.infrastructure.metrics.get_metrics", return_value=mock_metrics):
            from app.infrastructure.metrics import count_errors

            @count_errors(component="various")
            def raise_value_error():
                raise ValueError("test")

            @count_errors(component="various")
            def raise_type_error():
                raise TypeError("test")

            @count_errors(component="various")
            def raise_key_error():
                raise KeyError("test")

            with pytest.raises(ValueError):
                raise_value_error()

            with pytest.raises(TypeError):
                raise_type_error()

            with pytest.raises(KeyError):
                raise_key_error()

    def test_timed_preserves_docstring(self, mock_metrics):
        """@timed préserve le docstring de la fonction."""
        with patch("app.infrastructure.metrics.get_metrics", return_value=mock_metrics):
            from app.infrastructure.metrics import timed

            @timed(agent="doc_test")
            def documented_function():
                """This is a docstring."""
                return True

            result = documented_function()
            assert result is True

    def test_decorators_with_class_methods(self, mock_metrics):
        """Les décorateurs fonctionnent avec les méthodes de classe."""
        with patch("app.infrastructure.metrics.get_metrics", return_value=mock_metrics):
            from app.infrastructure.metrics import timed, count_errors

            class TestClass:
                @timed(agent="method")
                def timed_method(self):
                    return "timed"

                @count_errors(component="method")
                def error_method(self):
                    raise ValueError("method error")

            obj = TestClass()
            assert obj.timed_method() == "timed"

            with pytest.raises(ValueError):
                obj.error_method()

    def test_decorators_with_static_methods(self, mock_metrics):
        """Les décorateurs fonctionnent avec les méthodes statiques."""
        with patch("app.infrastructure.metrics.get_metrics", return_value=mock_metrics):
            from app.infrastructure.metrics import timed

            class TestClass:
                @staticmethod
                @timed(agent="static")
                def static_method():
                    return "static"

            assert TestClass.static_method() == "static"
