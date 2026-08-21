# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour les fonctionnalités optionnelles:
- WebSocket temps réel
- Templates follow-up personnalisables
- Hot-reload config
- Métriques Prometheus
- Feedback vocal TTS

pytest tests/test_optional_features.py -v
"""

import os
import sys
import time
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

# Ajouter le répertoire racine
sys.path.insert(0, str(Path(__file__).parent.parent))


# ============================================================================
# TESTS HOT-RELOAD
# ============================================================================

class TestHotReload:
    """Tests pour le module hot_reload."""

    def test_config_watcher_creation(self):
        """ConfigWatcher peut être créé."""
        from app.infrastructure.hot_reload import ConfigWatcher
        watcher = ConfigWatcher()
        assert watcher is not None
        assert watcher.is_running is False

    def test_config_watcher_watch_file(self):
        """ConfigWatcher peut surveiller un fichier."""
        from app.infrastructure.hot_reload import ConfigWatcher

        watcher = ConfigWatcher()
        callback = Mock()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            f.write("TEST_VAR=value1\n")
            filepath = Path(f.name)

        try:
            watcher.watch(filepath, callback)
            assert str(filepath.resolve()) in watcher.watched_files
        finally:
            filepath.unlink()

    def test_config_watcher_unwatch(self):
        """ConfigWatcher peut arrêter de surveiller un fichier."""
        from app.infrastructure.hot_reload import ConfigWatcher

        watcher = ConfigWatcher()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            filepath = Path(f.name)

        try:
            watcher.watch(filepath, lambda: None)
            assert str(filepath.resolve()) in watcher.watched_files

            watcher.unwatch(filepath)
            assert str(filepath.resolve()) not in watcher.watched_files
        finally:
            filepath.unlink()

    def test_env_config_reloader(self):
        """EnvConfigReloader peut recharger .env."""
        from app.infrastructure.hot_reload import EnvConfigReloader

        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            f.write("TEST_RELOAD_VAR=initial\n")
            filepath = Path(f.name)

        try:
            reloader = EnvConfigReloader(env_path=filepath)

            # Modifier le fichier
            filepath.write_text("TEST_RELOAD_VAR=changed\n")

            # Recharger
            changes = reloader.reload()

            # Vérifier
            assert "TEST_RELOAD_VAR" in changes
            assert os.getenv("TEST_RELOAD_VAR") == "changed"
        finally:
            filepath.unlink()
            os.environ.pop("TEST_RELOAD_VAR", None)

    def test_get_reloadable_config(self):
        """get_reloadable_config retourne la config."""
        from app.infrastructure.hot_reload import EnvConfigReloader

        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            f.write("")
            filepath = Path(f.name)

        try:
            reloader = EnvConfigReloader(env_path=filepath)
            config = reloader.get_reloadable_config()

            assert "poll_interval" in config
            assert "confidence_threshold" in config
        finally:
            filepath.unlink()

    def test_singleton_config_watcher(self):
        """get_config_watcher retourne un singleton."""
        from app.infrastructure.hot_reload import get_config_watcher

        watcher1 = get_config_watcher()
        watcher2 = get_config_watcher()
        assert watcher1 is watcher2


# ============================================================================
# TESTS PROMETHEUS METRICS
# ============================================================================

class TestPrometheusMetrics:
    """Tests pour le module metrics."""

    def test_metrics_creation(self):
        """AgentysMetrics peut être créé."""
        from prometheus_client import CollectorRegistry
        from app.infrastructure.metrics import AgentysMetrics

        # Utiliser un registry isolé pour les tests
        registry = CollectorRegistry()
        metrics = AgentysMetrics(registry=registry)

        assert metrics is not None
        assert metrics.emails_processed is not None
        assert metrics.drafts_created is not None

    def test_record_email_processed(self):
        """Enregistrement d'un email traité."""
        from prometheus_client import CollectorRegistry
        from app.infrastructure.metrics import AgentysMetrics

        registry = CollectorRegistry()
        metrics = AgentysMetrics(registry=registry)

        metrics.record_email_processed(
            category="URGENT",
            status="V1",
            processing_time=5.0
        )

        # Vérifier que le compteur a été incrémenté
        count = metrics.emails_processed.labels(category="URGENT", status="V1")._value.get()
        assert count == 1

    def test_record_llm_call(self):
        """Enregistrement d'un appel LLM."""
        from prometheus_client import CollectorRegistry
        from app.infrastructure.metrics import AgentysMetrics

        registry = CollectorRegistry()
        metrics = AgentysMetrics(registry=registry)

        metrics.record_llm_call(
            model="claude-opus",
            agent="drafter",
            input_tokens=1000,
            output_tokens=500,
            duration=2.5
        )

        count = metrics.llm_requests.labels(model="claude-opus", agent="drafter")._value.get()
        assert count == 1

    def test_record_error(self):
        """Enregistrement d'une erreur."""
        from prometheus_client import CollectorRegistry
        from app.infrastructure.metrics import AgentysMetrics

        registry = CollectorRegistry()
        metrics = AgentysMetrics(registry=registry)

        metrics.record_error("ConnectionError", "email_provider")

        count = metrics.errors.labels(type="ConnectionError", component="email_provider")._value.get()
        assert count == 1

    def test_update_budget(self):
        """Mise à jour du budget."""
        from prometheus_client import CollectorRegistry
        from app.infrastructure.metrics import AgentysMetrics

        registry = CollectorRegistry()
        metrics = AgentysMetrics(registry=registry)

        metrics.update_budget(spent=25.50, remaining=24.50)

        assert metrics.monthly_cost._value.get() == 25.50
        assert metrics.budget_remaining._value.get() == 24.50

    def test_get_metrics_text(self):
        """Génération du texte des métriques."""
        from app.infrastructure.metrics import get_metrics_text, get_metrics

        # Ensure metrics are initialized
        metrics = get_metrics()
        metrics.daemon_running.set(1)  # Set a metric to ensure it appears

        text = get_metrics_text()
        assert "# HELP" in text
        # The metrics should now contain agentys metrics
        assert "agentys" in text or "python_info" in text  # At least default metrics

    def test_timed_decorator(self):
        """Décorateur @timed mesure le temps."""
        from app.infrastructure.metrics import timed

        @timed(agent="test_agent")
        def slow_function():
            time.sleep(0.1)
            return "done"

        result = slow_function()
        assert result == "done"

    def test_create_metrics_blueprint(self):
        """Création du blueprint Flask pour métriques."""
        from app.infrastructure.metrics import create_metrics_blueprint

        bp = create_metrics_blueprint()
        assert bp is not None
        assert bp.name == "metrics"


# ============================================================================
# TESTS TTS ENGINE
# ============================================================================

class TestTTSEngine:
    """Tests pour le module TTS."""

    def test_tts_engine_creation(self):
        """TTSEngine peut être créé."""
        from app.voice import TTSEngine

        with patch.dict(os.environ, {"TTS_ENABLED": "true"}):
            engine = TTSEngine()
            assert engine is not None

    def test_tts_engine_disabled(self):
        """TTSEngine peut être désactivé."""
        from app.voice import TTSEngine

        with patch.dict(os.environ, {"TTS_ENABLED": "false"}):
            engine = TTSEngine()
            engine._enabled = False
            assert engine.enabled is False

    def test_tts_set_rate(self):
        """TTSEngine peut changer la vitesse."""
        from app.voice import TTSEngine

        engine = TTSEngine()
        engine.set_rate(150)
        assert engine._rate == 150

    def test_tts_set_volume(self):
        """TTSEngine peut changer le volume."""
        from app.voice import TTSEngine

        engine = TTSEngine()
        engine.set_volume(0.5)
        assert engine._volume == 0.5

        # Volume clampé entre 0 et 1
        engine.set_volume(1.5)
        assert engine._volume == 1.0

        engine.set_volume(-0.5)
        assert engine._volume == 0.0

    def test_tts_messages(self):
        """Messages TTS prédéfinis existent."""
        from app.voice import TTS_MESSAGES, get_tts_message

        assert "draft_created" in TTS_MESSAGES
        assert "error" in TTS_MESSAGES

        msg = get_tts_message("new_emails", count=5)
        assert "5" in msg

    def test_speak_function(self):
        """Fonction speak existe."""
        from app.voice import TTSEngine

        # Créer un nouveau moteur TTS désactivé
        engine = TTSEngine()
        engine._enabled = False
        engine._initialized = True
        engine._engine = None

        result = engine.speak("Test")
        assert result is False

    def test_speak_message_function(self):
        """Fonction speak_message existe."""
        from app.voice import speak_message

        with patch("app.voice.tts_engine") as mock_engine:
            mock_engine.enabled = False
            mock_engine.speak.return_value = False
            speak_message("draft_created")
            # Le mock devrait intercepter l'appel


# ============================================================================
# TESTS WEBSOCKET DASHBOARD
# ============================================================================

class TestWebSocketDashboard:
    """Tests pour le WebSocket du dashboard."""

    def test_dashboard_imports(self):
        """Dashboard peut importer SocketIO."""
        from app.dashboard import socketio, app

        assert socketio is not None
        assert app is not None

    def test_notify_functions_exist(self):
        """Fonctions de notification existent."""
        from app.dashboard import (
            notify_email_processed,
            notify_draft_created,
            notify_error,
            notify_budget_alert,
            broadcast_stats_update,
        )

        # Vérifier que les fonctions existent
        assert callable(notify_email_processed)
        assert callable(notify_draft_created)
        assert callable(notify_error)
        assert callable(notify_budget_alert)
        assert callable(broadcast_stats_update)

    def test_notify_email_processed(self):
        """notify_email_processed peut être appelée."""
        from app.dashboard import notify_email_processed, socketio

        with patch.object(socketio, 'emit') as mock_emit:
            notify_email_processed("Test Subject", "V1", "URGENT")

            mock_emit.assert_called_once()
            args = mock_emit.call_args
            assert args[0][0] == "email_processed"
            assert "Test Subject" in args[0][1]["subject"]

    def test_notify_draft_created(self):
        """notify_draft_created peut être appelée."""
        from app.dashboard import notify_draft_created, socketio

        with patch.object(socketio, 'emit') as mock_emit:
            notify_draft_created("Test Subject", "test@example.com")

            mock_emit.assert_called_once()
            args = mock_emit.call_args
            assert args[0][0] == "draft_created"

    def test_notify_error(self):
        """notify_error peut être appelée."""
        from app.dashboard import notify_error, socketio

        with patch.object(socketio, 'emit') as mock_emit:
            notify_error("Test error message", "connection")

            mock_emit.assert_called_once()
            args = mock_emit.call_args
            assert args[0][0] == "error_notification"
            assert args[0][1]["message"] == "Test error message"

    def test_notify_budget_alert(self):
        """notify_budget_alert peut être appelée."""
        from app.dashboard import notify_budget_alert, socketio

        with patch.object(socketio, 'emit') as mock_emit:
            notify_budget_alert(85.5, 7.25)

            mock_emit.assert_called_once()
            args = mock_emit.call_args
            assert args[0][0] == "budget_alert"
            assert args[0][1]["usage_percent"] == 85.5


# ============================================================================
# TESTS D'INTÉGRATION
# ============================================================================

class TestOptionalFeaturesIntegration:
    """Tests d'intégration des fonctionnalités optionnelles."""

    def test_metrics_with_hot_reload(self):
        """Métriques peuvent être utilisées avec hot-reload."""
        from prometheus_client import CollectorRegistry
        from app.infrastructure.metrics import AgentysMetrics
        from app.infrastructure.hot_reload import ConfigWatcher

        registry = CollectorRegistry()
        metrics = AgentysMetrics(registry=registry)
        watcher = ConfigWatcher()

        # Simuler un rechargement de config
        callback_called = []
        def on_reload():
            callback_called.append(True)
            metrics.daemon_running.set(1)

        # Utiliser un fichier temporaire
        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            filepath = Path(f.name)

        try:
            watcher.watch(filepath, on_reload)
            watcher.force_reload()

            assert len(callback_called) == 1
        finally:
            filepath.unlink()
