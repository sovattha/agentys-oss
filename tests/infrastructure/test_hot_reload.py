# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests exhaustifs pour le module hot_reload.

Tests pour atteindre une couverture >95%.
"""

import os
import sys
import time
import tempfile
import threading
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

# Add root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ============================================================================
# WATCHDOG AVAILABILITY TESTS
# ============================================================================


class TestWatchdogAvailability:
    """Tests for watchdog import fallback."""

    def test_watchdog_available_flag(self):
        """Test WATCHDOG_AVAILABLE flag is set."""
        from app.infrastructure import hot_reload
        # The flag should be boolean
        assert isinstance(hot_reload.WATCHDOG_AVAILABLE, bool)

    def test_watchdog_unavailable_fallback(self):
        """Test module works when watchdog is not installed."""
        # Save original values
        import app.infrastructure.hot_reload as module
        original_available = module.WATCHDOG_AVAILABLE
        original_observer = module.Observer
        original_handler = module.FileSystemEventHandler
        original_event = module.FileModifiedEvent

        # Simulate watchdog not being available
        module.WATCHDOG_AVAILABLE = False
        module.Observer = None
        module.FileSystemEventHandler = object
        module.FileModifiedEvent = None

        try:
            # Create watcher - should work without watchdog
            watcher = module.ConfigWatcher()
            assert watcher is not None
        finally:
            # Restore original values
            module.WATCHDOG_AVAILABLE = original_available
            module.Observer = original_observer
            module.FileSystemEventHandler = original_handler
            module.FileModifiedEvent = original_event


# ============================================================================
# WATCHEDFILE DATACLASS TESTS
# ============================================================================


class TestWatchedFile:
    """Tests for WatchedFile dataclass."""

    def test_watched_file_creation(self):
        """Test WatchedFile can be created."""
        from app.infrastructure.hot_reload import WatchedFile

        wf = WatchedFile(path=Path("/test/path"))
        assert wf.path == Path("/test/path")
        assert wf.last_modified == 0
        assert wf.callbacks == []

    def test_watched_file_with_callbacks(self):
        """Test WatchedFile with callbacks."""
        from app.infrastructure.hot_reload import WatchedFile

        callback = Mock()
        wf = WatchedFile(
            path=Path("/test/path"),
            last_modified=123.456,
            callbacks=[callback]
        )

        assert wf.last_modified == 123.456
        assert len(wf.callbacks) == 1
        assert wf.callbacks[0] is callback


# ============================================================================
# CONFIGFILEHANDLER TESTS
# ============================================================================


class TestConfigFileHandler:
    """Tests for ConfigFileHandler class."""

    def test_handler_creation(self):
        """Test ConfigFileHandler can be created."""
        from app.infrastructure.hot_reload import ConfigFileHandler, ConfigWatcher

        watcher = ConfigWatcher()
        handler = ConfigFileHandler(watcher)

        assert handler.config_watcher is watcher

    def test_on_modified_with_file_modified_event(self):
        """Test on_modified handles FileModifiedEvent."""
        import app.infrastructure.hot_reload as module

        if not module.WATCHDOG_AVAILABLE:
            pytest.skip("watchdog not installed")

        from app.infrastructure.hot_reload import ConfigFileHandler, ConfigWatcher

        watcher = ConfigWatcher()
        handler = ConfigFileHandler(watcher)

        # Mock the watcher's _handle_file_change method
        watcher._handle_file_change = Mock()

        # Create a mock FileModifiedEvent
        mock_event = Mock()
        mock_event.src_path = "/test/file.txt"

        # Patch isinstance check
        with patch.object(module, 'FileModifiedEvent', type(mock_event)):
            handler.on_modified(mock_event)

        watcher._handle_file_change.assert_called_once_with(Path("/test/file.txt"))

    def test_on_modified_ignores_non_file_events(self):
        """Test on_modified ignores non-file events."""
        import app.infrastructure.hot_reload as module

        # Simulate watchdog unavailable
        original = module.WATCHDOG_AVAILABLE
        module.WATCHDOG_AVAILABLE = False

        try:
            from app.infrastructure.hot_reload import ConfigFileHandler, ConfigWatcher

            watcher = ConfigWatcher()
            handler = ConfigFileHandler(watcher)
            watcher._handle_file_change = Mock()

            # Create a mock event that's not a FileModifiedEvent
            mock_event = Mock()
            mock_event.src_path = "/test/file.txt"

            handler.on_modified(mock_event)

            # Should not be called since WATCHDOG_AVAILABLE is False
            watcher._handle_file_change.assert_not_called()
        finally:
            module.WATCHDOG_AVAILABLE = original


# ============================================================================
# CONFIGWATCHER TESTS
# ============================================================================


class TestConfigWatcher:
    """Tests for ConfigWatcher class."""

    def test_init_default_values(self):
        """Test ConfigWatcher initializes with default values."""
        from app.infrastructure.hot_reload import ConfigWatcher

        watcher = ConfigWatcher()

        assert watcher.watched_files == {}
        assert watcher.observer is None
        assert watcher.debounce_delay == 1.0
        assert watcher._last_reload == {}
        assert watcher._running is False
        assert watcher._config_cache == {}

    def test_init_custom_debounce(self):
        """Test ConfigWatcher with custom debounce delay."""
        from app.infrastructure.hot_reload import ConfigWatcher

        watcher = ConfigWatcher(debounce_delay=2.5)

        assert watcher.debounce_delay == 2.5

    def test_watch_new_file(self):
        """Test watching a new file."""
        from app.infrastructure.hot_reload import ConfigWatcher

        watcher = ConfigWatcher()
        callback = Mock()

        with tempfile.NamedTemporaryFile(delete=False) as f:
            filepath = Path(f.name)

        try:
            watcher.watch(filepath, callback)

            key = str(filepath.resolve())
            assert key in watcher.watched_files
            assert callback in watcher.watched_files[key].callbacks
        finally:
            filepath.unlink()

    def test_watch_file_that_does_not_exist(self):
        """Test watching a file that does not exist."""
        from app.infrastructure.hot_reload import ConfigWatcher

        watcher = ConfigWatcher()
        callback = Mock()

        filepath = Path("/nonexistent/file.txt")

        # Should not raise, just set last_modified to 0
        watcher.watch(filepath, callback)

        key = str(filepath.resolve())
        assert key in watcher.watched_files
        assert watcher.watched_files[key].last_modified == 0

    def test_watch_multiple_callbacks_same_file(self):
        """Test multiple callbacks for same file."""
        from app.infrastructure.hot_reload import ConfigWatcher

        watcher = ConfigWatcher()
        callback1 = Mock()
        callback2 = Mock()

        with tempfile.NamedTemporaryFile(delete=False) as f:
            filepath = Path(f.name)

        try:
            watcher.watch(filepath, callback1)
            watcher.watch(filepath, callback2)

            key = str(filepath.resolve())
            assert len(watcher.watched_files[key].callbacks) == 2
            assert callback1 in watcher.watched_files[key].callbacks
            assert callback2 in watcher.watched_files[key].callbacks
        finally:
            filepath.unlink()

    def test_unwatch_existing_file(self):
        """Test unwatching an existing file."""
        from app.infrastructure.hot_reload import ConfigWatcher

        watcher = ConfigWatcher()

        with tempfile.NamedTemporaryFile(delete=False) as f:
            filepath = Path(f.name)

        try:
            watcher.watch(filepath, lambda: None)
            key = str(filepath.resolve())
            assert key in watcher.watched_files

            watcher.unwatch(filepath)
            assert key not in watcher.watched_files
        finally:
            filepath.unlink()

    def test_unwatch_non_existing_file(self):
        """Test unwatching a file that's not being watched."""
        from app.infrastructure.hot_reload import ConfigWatcher

        watcher = ConfigWatcher()

        # Should not raise
        watcher.unwatch(Path("/nonexistent/file.txt"))

    def test_start_when_already_running(self):
        """Test start does nothing when already running."""
        from app.infrastructure.hot_reload import ConfigWatcher

        watcher = ConfigWatcher()
        watcher._running = True

        watcher.start()

        # Should still be running, observer should still be None
        assert watcher._running is True
        assert watcher.observer is None

    def test_start_without_watchdog(self):
        """Test start logs warning when watchdog unavailable."""
        import app.infrastructure.hot_reload as module

        original = module.WATCHDOG_AVAILABLE
        module.WATCHDOG_AVAILABLE = False

        try:
            from app.infrastructure.hot_reload import ConfigWatcher

            watcher = ConfigWatcher()
            watcher.start()

            # Should be marked as running to avoid repeated warnings
            assert watcher._running is True
            assert watcher.observer is None
        finally:
            module.WATCHDOG_AVAILABLE = original

    def test_start_with_watchdog(self):
        """Test start initializes observer when watchdog available."""
        import app.infrastructure.hot_reload as module

        if not module.WATCHDOG_AVAILABLE:
            pytest.skip("watchdog not installed")

        from app.infrastructure.hot_reload import ConfigWatcher

        watcher = ConfigWatcher()

        with tempfile.NamedTemporaryFile(delete=False) as f:
            filepath = Path(f.name)

        try:
            watcher.watch(filepath, lambda: None)
            watcher.start()

            assert watcher._running is True
            assert watcher.observer is not None

            watcher.stop()
        finally:
            filepath.unlink()

    def test_stop_when_not_running(self):
        """Test stop does nothing when not running."""
        from app.infrastructure.hot_reload import ConfigWatcher

        watcher = ConfigWatcher()

        # Should not raise
        watcher.stop()

        assert watcher._running is False

    def test_stop_when_running(self):
        """Test stop shuts down observer."""
        import app.infrastructure.hot_reload as module

        if not module.WATCHDOG_AVAILABLE:
            pytest.skip("watchdog not installed")

        from app.infrastructure.hot_reload import ConfigWatcher

        watcher = ConfigWatcher()

        with tempfile.NamedTemporaryFile(delete=False) as f:
            filepath = Path(f.name)

        try:
            watcher.watch(filepath, lambda: None)
            watcher.start()
            assert watcher._running is True

            watcher.stop()
            assert watcher._running is False
        finally:
            filepath.unlink()

    def test_handle_file_change_unknown_file(self):
        """Test _handle_file_change ignores unknown files."""
        from app.infrastructure.hot_reload import ConfigWatcher

        watcher = ConfigWatcher()
        callback = Mock()

        # Don't watch any file
        watcher._handle_file_change(Path("/unknown/file.txt"))

        # Callback should not be called
        callback.assert_not_called()

    def test_handle_file_change_debounce(self):
        """Test _handle_file_change debounces rapid changes."""
        from app.infrastructure.hot_reload import ConfigWatcher

        watcher = ConfigWatcher(debounce_delay=1.0)
        callback = Mock()

        with tempfile.NamedTemporaryFile(delete=False) as f:
            filepath = Path(f.name)

        try:
            watcher.watch(filepath, callback)

            # First change should trigger callback
            watcher._handle_file_change(filepath)
            assert callback.call_count == 1

            # Immediate second change should be debounced
            watcher._handle_file_change(filepath)
            assert callback.call_count == 1  # Still 1, debounced
        finally:
            filepath.unlink()

    def test_handle_file_change_after_debounce(self):
        """Test _handle_file_change works after debounce delay."""
        from app.infrastructure.hot_reload import ConfigWatcher

        watcher = ConfigWatcher(debounce_delay=0.1)
        callback = Mock()

        with tempfile.NamedTemporaryFile(delete=False) as f:
            filepath = Path(f.name)

        try:
            watcher.watch(filepath, callback)

            # First change
            watcher._handle_file_change(filepath)
            assert callback.call_count == 1

            # Wait for debounce to expire
            time.sleep(0.2)

            # Second change should now work
            watcher._handle_file_change(filepath)
            assert callback.call_count == 2
        finally:
            filepath.unlink()

    def test_handle_file_change_callback_exception(self):
        """Test _handle_file_change catches callback exceptions."""
        from app.infrastructure.hot_reload import ConfigWatcher

        watcher = ConfigWatcher(debounce_delay=0)

        def failing_callback():
            raise Exception("Callback error")

        with tempfile.NamedTemporaryFile(delete=False) as f:
            filepath = Path(f.name)

        try:
            watcher.watch(filepath, failing_callback)

            # Should not raise
            watcher._handle_file_change(filepath)
        finally:
            filepath.unlink()

    def test_handle_file_change_multiple_callbacks(self):
        """Test _handle_file_change calls all callbacks."""
        from app.infrastructure.hot_reload import ConfigWatcher

        watcher = ConfigWatcher(debounce_delay=0)
        callback1 = Mock()
        callback2 = Mock()

        with tempfile.NamedTemporaryFile(delete=False) as f:
            filepath = Path(f.name)

        try:
            watcher.watch(filepath, callback1)
            watcher.watch(filepath, callback2)

            watcher._handle_file_change(filepath)

            callback1.assert_called_once()
            callback2.assert_called_once()
        finally:
            filepath.unlink()

    def test_force_reload_specific_file(self):
        """Test force_reload for specific file."""
        from app.infrastructure.hot_reload import ConfigWatcher

        watcher = ConfigWatcher()
        callback = Mock()

        with tempfile.NamedTemporaryFile(delete=False) as f:
            filepath = Path(f.name)

        try:
            watcher.watch(filepath, callback)
            watcher.force_reload(filepath)

            callback.assert_called_once()
        finally:
            filepath.unlink()

    def test_force_reload_specific_file_not_watched(self):
        """Test force_reload for file that's not watched."""
        from app.infrastructure.hot_reload import ConfigWatcher

        watcher = ConfigWatcher()

        # Should not raise
        watcher.force_reload(Path("/nonexistent/file.txt"))

    def test_force_reload_all_files(self):
        """Test force_reload for all files."""
        from app.infrastructure.hot_reload import ConfigWatcher

        watcher = ConfigWatcher()
        callback1 = Mock()
        callback2 = Mock()

        with tempfile.NamedTemporaryFile(delete=False) as f1:
            filepath1 = Path(f1.name)
        with tempfile.NamedTemporaryFile(delete=False) as f2:
            filepath2 = Path(f2.name)

        try:
            watcher.watch(filepath1, callback1)
            watcher.watch(filepath2, callback2)
            watcher.force_reload()

            callback1.assert_called_once()
            callback2.assert_called_once()
        finally:
            filepath1.unlink()
            filepath2.unlink()

    def test_force_reload_callback_exception(self):
        """Test force_reload catches callback exceptions."""
        from app.infrastructure.hot_reload import ConfigWatcher

        watcher = ConfigWatcher()

        def failing_callback():
            raise Exception("Error")

        good_callback = Mock()

        with tempfile.NamedTemporaryFile(delete=False) as f:
            filepath = Path(f.name)

        try:
            watcher.watch(filepath, failing_callback)
            watcher.watch(filepath, good_callback)

            # Should not raise, should still call good_callback
            watcher.force_reload(filepath)
            good_callback.assert_called_once()
        finally:
            filepath.unlink()

    def test_force_reload_all_with_callback_exception(self):
        """Test force_reload all files with callback exception."""
        from app.infrastructure.hot_reload import ConfigWatcher

        watcher = ConfigWatcher()

        def failing_callback():
            raise Exception("Error")

        with tempfile.NamedTemporaryFile(delete=False) as f:
            filepath = Path(f.name)

        try:
            watcher.watch(filepath, failing_callback)

            # Should not raise
            watcher.force_reload()
        finally:
            filepath.unlink()

    def test_is_running_property(self):
        """Test is_running property."""
        from app.infrastructure.hot_reload import ConfigWatcher

        watcher = ConfigWatcher()

        assert watcher.is_running is False

        watcher._running = True
        assert watcher.is_running is True


# ============================================================================
# ENVCONFIGRELOADER TESTS
# ============================================================================


class TestEnvConfigReloader:
    """Tests for EnvConfigReloader class."""

    def test_init_with_default_path(self):
        """Test EnvConfigReloader initializes with default path."""
        from app.infrastructure.hot_reload import EnvConfigReloader
        from app.config import PROJECT_ROOT

        reloader = EnvConfigReloader()

        assert reloader.env_path == PROJECT_ROOT / ".env"

    def test_init_with_custom_path(self):
        """Test EnvConfigReloader with custom path."""
        from app.infrastructure.hot_reload import EnvConfigReloader

        custom_path = Path("/custom/.env")
        reloader = EnvConfigReloader(env_path=custom_path)

        assert reloader.env_path == custom_path

    def test_store_original_values(self):
        """Test _store_original stores tracked env vars."""
        from app.infrastructure.hot_reload import EnvConfigReloader

        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            f.write("")
            filepath = Path(f.name)

        try:
            # Set a tracked env var
            os.environ["DAEMON_POLL_INTERVAL"] = "120"

            reloader = EnvConfigReloader(env_path=filepath)

            assert "DAEMON_POLL_INTERVAL" in reloader._original_values
            assert reloader._original_values["DAEMON_POLL_INTERVAL"] == "120"
        finally:
            filepath.unlink()
            os.environ.pop("DAEMON_POLL_INTERVAL", None)

    def test_reload_file_not_exists(self):
        """Test reload returns empty dict if file doesn't exist."""
        from app.infrastructure.hot_reload import EnvConfigReloader

        reloader = EnvConfigReloader(env_path=Path("/nonexistent/.env"))
        changes = reloader.reload()

        assert changes == {}

    def test_reload_detects_changes(self):
        """Test reload detects and applies changes."""
        from app.infrastructure.hot_reload import EnvConfigReloader

        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            f.write("TEST_HOT_RELOAD_VAR=initial\n")
            filepath = Path(f.name)

        try:
            reloader = EnvConfigReloader(env_path=filepath)

            # Modify the file
            filepath.write_text("TEST_HOT_RELOAD_VAR=changed\n")

            changes = reloader.reload()

            assert "TEST_HOT_RELOAD_VAR" in changes
            assert changes["TEST_HOT_RELOAD_VAR"][1] == "changed"
            assert os.getenv("TEST_HOT_RELOAD_VAR") == "changed"
        finally:
            filepath.unlink()
            os.environ.pop("TEST_HOT_RELOAD_VAR", None)

    def test_reload_skips_comments_and_empty_lines(self):
        """Test reload skips comments and empty lines."""
        from app.infrastructure.hot_reload import EnvConfigReloader

        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            f.write("# This is a comment\n")
            f.write("\n")
            f.write("  \n")
            f.write("VALID_VAR=value\n")
            filepath = Path(f.name)

        try:
            reloader = EnvConfigReloader(env_path=filepath)
            changes = reloader.reload()

            assert "VALID_VAR" in changes
            assert os.getenv("VALID_VAR") == "value"
        finally:
            filepath.unlink()
            os.environ.pop("VALID_VAR", None)

    def test_reload_strips_quotes(self):
        """Test reload strips quotes from values."""
        from app.infrastructure.hot_reload import EnvConfigReloader

        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            f.write("QUOTED_VAR='single quotes'\n")
            f.write('DOUBLE_QUOTED="double quotes"\n')
            filepath = Path(f.name)

        try:
            reloader = EnvConfigReloader(env_path=filepath)
            reloader.reload()

            assert os.getenv("QUOTED_VAR") == "single quotes"
            assert os.getenv("DOUBLE_QUOTED") == "double quotes"
        finally:
            filepath.unlink()
            os.environ.pop("QUOTED_VAR", None)
            os.environ.pop("DOUBLE_QUOTED", None)

    def test_reload_handles_equals_in_value(self):
        """Test reload handles = in value."""
        from app.infrastructure.hot_reload import EnvConfigReloader

        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            f.write("URL_VAR=http://example.com?a=1&b=2\n")
            filepath = Path(f.name)

        try:
            reloader = EnvConfigReloader(env_path=filepath)
            reloader.reload()

            assert os.getenv("URL_VAR") == "http://example.com?a=1&b=2"
        finally:
            filepath.unlink()
            os.environ.pop("URL_VAR", None)

    def test_get_reloadable_config(self):
        """Test get_reloadable_config returns current config."""
        from app.infrastructure.hot_reload import EnvConfigReloader

        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            f.write("")
            filepath = Path(f.name)

        try:
            # Set some env vars
            os.environ["DAEMON_POLL_INTERVAL"] = "30"
            os.environ["CONFIDENCE_THRESHOLD"] = "80"
            os.environ["NOTIFICATIONS_ENABLED"] = "true"

            reloader = EnvConfigReloader(env_path=filepath)
            config = reloader.get_reloadable_config()

            assert config["poll_interval"] == 30
            assert config["confidence_threshold"] == 80
            assert config["notifications_enabled"] is True
        finally:
            filepath.unlink()
            os.environ.pop("DAEMON_POLL_INTERVAL", None)
            os.environ.pop("CONFIDENCE_THRESHOLD", None)
            os.environ.pop("NOTIFICATIONS_ENABLED", None)

    def test_get_reloadable_config_defaults(self):
        """Test get_reloadable_config uses defaults when env not set."""
        from app.infrastructure.hot_reload import EnvConfigReloader

        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            f.write("")
            filepath = Path(f.name)

        try:
            # Ensure env vars are not set
            for key in ["DAEMON_POLL_INTERVAL", "CONFIDENCE_THRESHOLD", "MONTHLY_BUDGET_USD"]:
                os.environ.pop(key, None)

            reloader = EnvConfigReloader(env_path=filepath)
            config = reloader.get_reloadable_config()

            assert config["poll_interval"] == 60  # default
            assert config["confidence_threshold"] == 70  # default
            assert config["monthly_budget"] == 0.0  # default
        finally:
            filepath.unlink()


# ============================================================================
# SINGLETON TESTS
# ============================================================================


class TestSingletons:
    """Tests for singleton functions."""

    def test_get_config_watcher_singleton(self):
        """Test get_config_watcher returns singleton."""
        import app.infrastructure.hot_reload as module

        # Reset singleton
        module._config_watcher = None

        watcher1 = module.get_config_watcher()
        watcher2 = module.get_config_watcher()

        assert watcher1 is watcher2

        # Cleanup
        module._config_watcher = None

    def test_get_env_reloader_singleton(self):
        """Test get_env_reloader returns singleton."""
        import app.infrastructure.hot_reload as module

        # Reset singleton
        module._env_reloader = None

        reloader1 = module.get_env_reloader()
        reloader2 = module.get_env_reloader()

        assert reloader1 is reloader2

        # Cleanup
        module._env_reloader = None


# ============================================================================
# SETUP HOT RELOAD TESTS
# ============================================================================


class TestSetupHotReload:
    """Tests for setup_hot_reload function."""

    def test_setup_hot_reload_returns_watcher(self):
        """Test setup_hot_reload returns ConfigWatcher."""
        import app.infrastructure.hot_reload as module

        # Reset singletons
        module._config_watcher = None
        module._env_reloader = None

        watcher = module.setup_hot_reload()

        assert watcher is not None
        assert isinstance(watcher, module.ConfigWatcher)

        # Cleanup
        module._config_watcher = None
        module._env_reloader = None

    def test_setup_hot_reload_watches_env_if_exists(self):
        """Test setup_hot_reload watches .env if it exists."""
        import app.infrastructure.hot_reload as module
        from app.config import PROJECT_ROOT

        # Reset singletons
        module._config_watcher = None
        module._env_reloader = None

        env_file = PROJECT_ROOT / ".env"

        if env_file.exists():
            watcher = module.setup_hot_reload()

            assert str(env_file.resolve()) in watcher.watched_files

        # Cleanup
        module._config_watcher = None
        module._env_reloader = None

    def test_setup_hot_reload_watches_knowledge_if_exists(self):
        """Test setup_hot_reload watches knowledge base if it exists."""
        import app.infrastructure.hot_reload as module
        from app.config import KNOWLEDGE_DIR

        # Reset singletons
        module._config_watcher = None
        module._env_reloader = None

        knowledge_file = KNOWLEDGE_DIR / "memoire.md"

        if knowledge_file.exists():
            watcher = module.setup_hot_reload()

            assert str(knowledge_file.resolve()) in watcher.watched_files

        # Cleanup
        module._config_watcher = None
        module._env_reloader = None


# ============================================================================
# EDGE CASES AND INTEGRATION TESTS
# ============================================================================


class TestEdgeCases:
    """Tests for edge cases and integration scenarios."""

    def test_thread_safety_watch(self):
        """Test watch is thread-safe."""
        from app.infrastructure.hot_reload import ConfigWatcher

        watcher = ConfigWatcher()
        callbacks = []

        with tempfile.NamedTemporaryFile(delete=False) as f:
            filepath = Path(f.name)

        try:
            def add_watch():
                callback = Mock()
                callbacks.append(callback)
                watcher.watch(filepath, callback)

            threads = [threading.Thread(target=add_watch) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            key = str(filepath.resolve())
            assert len(watcher.watched_files[key].callbacks) == 10
        finally:
            filepath.unlink()

    def test_concurrent_file_changes(self):
        """Test handling concurrent file changes."""
        from app.infrastructure.hot_reload import ConfigWatcher

        watcher = ConfigWatcher(debounce_delay=0)
        call_count = {"count": 0}

        def callback():
            call_count["count"] += 1

        with tempfile.NamedTemporaryFile(delete=False) as f:
            filepath = Path(f.name)

        try:
            watcher.watch(filepath, callback)

            # Simulate concurrent changes
            threads = [
                threading.Thread(target=watcher._handle_file_change, args=(filepath,))
                for _ in range(5)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # At least one should have been called
            assert call_count["count"] >= 1
        finally:
            filepath.unlink()

    def test_reload_long_value_truncation_log(self):
        """Test reload truncates long values in log."""
        from app.infrastructure.hot_reload import EnvConfigReloader

        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            # Write a value longer than 20 chars
            f.write("LONG_VALUE_VAR=this_is_a_very_long_value_that_should_be_truncated_in_log\n")
            filepath = Path(f.name)

        try:
            reloader = EnvConfigReloader(env_path=filepath)
            changes = reloader.reload()

            assert "LONG_VALUE_VAR" in changes
            # Value should be set fully despite truncation in log
            assert os.getenv("LONG_VALUE_VAR") == "this_is_a_very_long_value_that_should_be_truncated_in_log"
        finally:
            filepath.unlink()
            os.environ.pop("LONG_VALUE_VAR", None)

    def test_force_reload_with_no_watched_files(self):
        """Test force_reload with no watched files."""
        from app.infrastructure.hot_reload import ConfigWatcher

        watcher = ConfigWatcher()

        # Should not raise
        watcher.force_reload()

    def test_unwatch_already_unwatched(self):
        """Test unwatching a file that was already unwatched."""
        from app.infrastructure.hot_reload import ConfigWatcher

        watcher = ConfigWatcher()

        with tempfile.NamedTemporaryFile(delete=False) as f:
            filepath = Path(f.name)

        try:
            watcher.watch(filepath, lambda: None)
            watcher.unwatch(filepath)
            watcher.unwatch(filepath)  # Second unwatch should be no-op
        finally:
            filepath.unlink()
