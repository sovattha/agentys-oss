# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Unit tests for ConnectivityService.

Tests network connectivity monitoring and status tracking.
"""

import pytest
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.services.connectivity_service import (
    ConnectivityService,
    ConnectivityStatus,
    get_connectivity_service,
    init_connectivity_service,
)


class TestConnectivityStatus:
    """Tests for ConnectivityStatus dataclass."""

    def test_default_values(self):
        """Test default values."""
        status = ConnectivityStatus()
        assert status.is_online is True
        assert status.last_check_at is None
        assert status.last_online_at is None
        assert status.last_offline_at is None
        assert status.check_interval_seconds == 30
        assert status.consecutive_failures == 0

    def test_custom_values(self):
        """Test with custom values."""
        now = datetime.now(timezone.utc)
        status = ConnectivityStatus(
            is_online=False,
            last_check_at=now,
            last_online_at=now,
            last_offline_at=now,
            check_interval_seconds=60,
            consecutive_failures=3,
        )
        assert status.is_online is False
        assert status.last_check_at == now
        assert status.consecutive_failures == 3


class TestConnectivityService:
    """Tests for ConnectivityService class."""

    @pytest.fixture
    def connectivity_service(self):
        """Create connectivity service instance."""
        return ConnectivityService(
            check_interval=1,  # Short interval for tests
            health_endpoint="http://localhost:5050/api/health",
            failure_threshold=2,
        )

    def test_init_default_values(self):
        """Test default initialization."""
        service = ConnectivityService()
        assert service.check_interval == 30
        assert service.health_endpoint == "http://localhost:5050/api/health"
        assert service.failure_threshold == 2
        assert service.is_online is True

    def test_init_custom_values(self):
        """Test custom initialization."""
        on_online = MagicMock()
        on_offline = MagicMock()
        service = ConnectivityService(
            check_interval=60,
            health_endpoint="http://custom:8080/health",
            failure_threshold=5,
            on_online=on_online,
            on_offline=on_offline,
        )
        assert service.check_interval == 60
        assert service.health_endpoint == "http://custom:8080/health"
        assert service.failure_threshold == 5
        assert service._on_online is on_online
        assert service._on_offline is on_offline

    def test_is_online_property(self, connectivity_service):
        """Test is_online property."""
        assert connectivity_service.is_online is True
        connectivity_service._status.is_online = False
        assert connectivity_service.is_online is False

    def test_status_property(self, connectivity_service):
        """Test status property."""
        status = connectivity_service.status
        assert isinstance(status, ConnectivityStatus)
        assert status.is_online is True

    def test_on_status_change_registers_callback(self, connectivity_service):
        """Test callback registration."""
        callback = MagicMock()
        connectivity_service.on_status_change(callback)
        assert callback in connectivity_service._callbacks

    def test_remove_callback(self, connectivity_service):
        """Test callback removal."""
        callback = MagicMock()
        connectivity_service.on_status_change(callback)
        connectivity_service.remove_callback(callback)
        assert callback not in connectivity_service._callbacks

    def test_remove_callback_not_registered(self, connectivity_service):
        """Test removing callback that was never registered."""
        callback = MagicMock()
        # Should not raise
        connectivity_service.remove_callback(callback)

    @patch("app.services.connectivity_service.requests.get")
    def test_check_connectivity_success(self, mock_get, connectivity_service):
        """Test successful connectivity check."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        result = connectivity_service._check_connectivity()

        assert result is True
        mock_get.assert_called_once()

    @patch("app.services.connectivity_service.requests.get")
    @patch("app.services.connectivity_service.socket.socket")
    def test_check_connectivity_fallback_to_dns(self, mock_socket_cls, mock_get, connectivity_service):
        """Test fallback to TCP connect when HTTP fails.

        Audit MED-6 (2026-04-25): replaced gethostbyname (which can hang
        ≥10 s on bad /etc/resolv.conf) by TCP connect to 1.1.1.1:53.
        """
        import requests
        mock_get.side_effect = requests.RequestException("Connection failed")
        mock_sock = mock_socket_cls.return_value
        mock_sock.connect.return_value = None  # Successful connect

        result = connectivity_service._check_connectivity()

        assert result is True
        mock_sock.settimeout.assert_called_once_with(3)
        mock_sock.connect.assert_called_once_with(("1.1.1.1", 53))
        mock_sock.close.assert_called_once()

    @patch("app.services.connectivity_service.requests.get")
    @patch("app.services.connectivity_service.socket.socket")
    def test_check_connectivity_both_fail(self, mock_socket_cls, mock_get, connectivity_service):
        """Test when both HTTP and TCP fallback fail."""
        import requests
        mock_get.side_effect = requests.RequestException("Connection failed")
        mock_sock = mock_socket_cls.return_value
        mock_sock.connect.side_effect = OSError("TCP connect failed")

        result = connectivity_service._check_connectivity()

        assert result is False

    @patch.object(ConnectivityService, "_check_connectivity")
    def test_perform_check_updates_timestamps(self, mock_check, connectivity_service):
        """Test that perform_check updates timestamps."""
        mock_check.return_value = True

        connectivity_service._perform_check()

        assert connectivity_service._status.last_check_at is not None

    @patch.object(ConnectivityService, "_check_connectivity")
    def test_perform_check_online_resets_failures(self, mock_check, connectivity_service):
        """Test that successful check resets consecutive failures."""
        mock_check.return_value = True
        connectivity_service._status.consecutive_failures = 5

        connectivity_service._perform_check()

        assert connectivity_service._status.consecutive_failures == 0

    @patch.object(ConnectivityService, "_check_connectivity")
    def test_perform_check_offline_increments_failures(self, mock_check, connectivity_service):
        """Test that failed check increments consecutive failures."""
        mock_check.return_value = False

        connectivity_service._perform_check()

        assert connectivity_service._status.consecutive_failures == 1

    @patch.object(ConnectivityService, "_check_connectivity")
    def test_transition_online_to_offline(self, mock_check, connectivity_service):
        """Test transition from online to offline."""
        mock_check.return_value = False
        callback = MagicMock()
        connectivity_service.on_status_change(callback)

        # First failure
        connectivity_service._perform_check()
        assert connectivity_service.is_online is True  # Still online (threshold not reached)

        # Second failure (reaches threshold)
        connectivity_service._perform_check()
        assert connectivity_service.is_online is False
        callback.assert_called_with(False)

    @patch.object(ConnectivityService, "_check_connectivity")
    def test_transition_offline_to_online(self, mock_check, connectivity_service):
        """Test transition from offline to online."""
        # Start offline
        connectivity_service._status.is_online = False
        mock_check.return_value = True
        callback = MagicMock()
        connectivity_service.on_status_change(callback)

        connectivity_service._perform_check()

        assert connectivity_service.is_online is True
        callback.assert_called_with(True)

    @patch.object(ConnectivityService, "_check_connectivity")
    def test_on_online_callback_called(self, mock_check, connectivity_service):
        """Test on_online callback is called when going online."""
        on_online = MagicMock()
        connectivity_service._on_online = on_online
        connectivity_service._status.is_online = False
        mock_check.return_value = True

        connectivity_service._perform_check()

        on_online.assert_called_once()

    @patch.object(ConnectivityService, "_check_connectivity")
    def test_on_offline_callback_called(self, mock_check, connectivity_service):
        """Test on_offline callback is called when going offline."""
        on_offline = MagicMock()
        connectivity_service._on_offline = on_offline
        connectivity_service.failure_threshold = 1
        mock_check.return_value = False

        connectivity_service._perform_check()

        on_offline.assert_called_once()

    @patch.object(ConnectivityService, "_check_connectivity")
    def test_callback_exception_handled(self, mock_check, connectivity_service):
        """Test that callback exceptions don't break the service."""
        mock_check.return_value = True
        connectivity_service._status.is_online = False

        callback = MagicMock(side_effect=Exception("Callback error"))
        connectivity_service.on_status_change(callback)

        # Should not raise
        connectivity_service._perform_check()

    @patch.object(ConnectivityService, "_check_connectivity")
    def test_check_now(self, mock_check, connectivity_service):
        """Test immediate connectivity check."""
        mock_check.return_value = True

        result = connectivity_service.check_now()

        assert result is True
        mock_check.assert_called_once()

    def test_start_creates_thread(self, connectivity_service):
        """Test that start creates a background thread."""
        with patch.object(connectivity_service, "_check_loop"):
            connectivity_service.start()

            assert connectivity_service._check_thread is not None
            assert connectivity_service._check_thread.daemon is True

            # Clean up
            connectivity_service.stop()

    def test_start_already_running(self, connectivity_service):
        """Test starting when already running."""
        with patch.object(connectivity_service, "_check_loop"):
            connectivity_service.start()
            connectivity_service.start()  # Should not create new thread

            # Clean up
            connectivity_service.stop()

    @patch.object(ConnectivityService, "_perform_check")
    def test_stop_stops_thread(self, mock_check):
        """Test that stop terminates the thread."""
        service = ConnectivityService(check_interval=1)
        service.start()

        # Wait a bit for thread to start
        time.sleep(0.1)

        service.stop(timeout=1.0)

        # Thread should be stopped
        assert service._stop_flag.is_set()


class TestGlobalConnectivityService:
    """Tests for global connectivity service functions."""

    def teardown_method(self):
        """Clean up global instance after each test."""
        import app.services.connectivity_service as module
        if module._connectivity_service is not None:
            module._connectivity_service.stop()
            module._connectivity_service = None

    def test_get_connectivity_service_returns_none_initially(self):
        """Test that get_connectivity_service returns None when not initialized."""
        import app.services.connectivity_service as module
        module._connectivity_service = None

        result = get_connectivity_service()
        assert result is None

    def test_init_connectivity_service_creates_instance(self):
        """Test that init creates a new instance."""
        service = init_connectivity_service(check_interval=60)

        assert service is not None
        assert service.check_interval == 60

    def test_init_connectivity_service_replaces_instance(self):
        """Test that init replaces existing instance."""
        service1 = init_connectivity_service(check_interval=30)
        service2 = init_connectivity_service(check_interval=60)

        assert service1 is not service2
        assert service2.check_interval == 60

    def test_get_after_init_returns_same_instance(self):
        """Test that get returns the initialized instance."""
        service1 = init_connectivity_service(check_interval=45)
        service2 = get_connectivity_service()

        assert service1 is service2
