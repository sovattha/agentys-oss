# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Unit tests for Connectivity API endpoints.

Tests network connectivity status and offline action queue endpoints.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from flask import Flask

from app.api.auth import apply_auth_guard
from app.api.connectivity import connectivity_bp
from app.services.action_queue import ProcessResult


@pytest.fixture
def app():
    """Create test Flask application."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    apply_auth_guard(connectivity_bp)
    app.register_blueprint(connectivity_bp)
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


class TestConnectivityStatusEndpoint:
    """Tests for GET /api/connectivity/status endpoint."""

    @patch("app.api.connectivity.get_connectivity_service")
    @patch("app.api.connectivity.get_action_queue")
    def test_status_when_service_not_initialized(self, mock_queue, mock_service, client):
        """Test status when connectivity service is not initialized."""
        mock_service.return_value = None

        response = client.get("/api/connectivity/status")

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["status"]["is_online"] is True
        assert data["status"]["pending_actions_count"] == 0

    @patch("app.api.connectivity.get_connectivity_service")
    @patch("app.api.connectivity.get_action_queue")
    def test_status_online(self, mock_queue, mock_service, client):
        """Test status when online."""
        # Mock connectivity service
        service = MagicMock()
        status = MagicMock()
        status.is_online = True
        status.last_check_at = datetime.now(timezone.utc)
        status.last_online_at = datetime.now(timezone.utc)
        status.last_offline_at = None
        service.status = status
        mock_service.return_value = service

        # Mock action queue
        queue = MagicMock()
        queue.get_pending_count.return_value = 3
        mock_queue.return_value = queue

        response = client.get("/api/connectivity/status")

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["status"]["is_online"] is True
        assert data["status"]["pending_actions_count"] == 3
        assert data["status"]["last_check_at"] is not None

    @patch("app.api.connectivity.get_connectivity_service")
    @patch("app.api.connectivity.get_action_queue")
    def test_status_offline(self, mock_queue, mock_service, client):
        """Test status when offline."""
        service = MagicMock()
        status = MagicMock()
        status.is_online = False
        status.last_check_at = datetime.now(timezone.utc)
        status.last_online_at = None
        status.last_offline_at = datetime.now(timezone.utc)
        service.status = status
        mock_service.return_value = service

        queue = MagicMock()
        queue.get_pending_count.return_value = 10
        mock_queue.return_value = queue

        response = client.get("/api/connectivity/status")

        assert response.status_code == 200
        data = response.get_json()
        assert data["status"]["is_online"] is False
        assert data["status"]["pending_actions_count"] == 10


class TestConnectivityCheckEndpoint:
    """Tests for POST /api/connectivity/check endpoint."""

    @patch("app.api.connectivity.get_connectivity_service")
    def test_check_service_not_initialized(self, mock_service, client):
        """Test check when service not initialized."""
        mock_service.return_value = None

        response = client.post("/api/connectivity/check")

        assert response.status_code == 503
        data = response.get_json()
        assert data["success"] is False
        assert "not initialized" in data["error"]

    @patch("app.api.connectivity.get_connectivity_service")
    def test_check_returns_online(self, mock_service, client):
        """Test check returns online status."""
        service = MagicMock()
        service.check_now.return_value = True
        mock_service.return_value = service

        response = client.post("/api/connectivity/check")

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["is_online"] is True

    @patch("app.api.connectivity.get_connectivity_service")
    def test_check_returns_offline(self, mock_service, client):
        """Test check returns offline status."""
        service = MagicMock()
        service.check_now.return_value = False
        mock_service.return_value = service

        response = client.post("/api/connectivity/check")

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["is_online"] is False


class TestQueueSummaryEndpoint:
    """Tests for GET /api/connectivity/queue endpoint."""

    @patch("app.api.connectivity.get_connectivity_service")
    @patch("app.api.connectivity.get_action_queue")
    def test_queue_summary(self, mock_queue, mock_service, client):
        """Test queue summary endpoint."""
        service = MagicMock()
        service.is_online = True
        mock_service.return_value = service

        queue = MagicMock()
        queue.get_pending_count.return_value = 5
        mock_queue.return_value = queue

        response = client.get("/api/connectivity/queue")

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["queue"]["total_pending"] == 5
        assert data["queue"]["is_online"] is True

    @patch("app.api.connectivity.get_connectivity_service")
    @patch("app.api.connectivity.get_action_queue")
    def test_queue_summary_no_service(self, mock_queue, mock_service, client):
        """Test queue summary when connectivity service not initialized."""
        mock_service.return_value = None

        queue = MagicMock()
        queue.get_pending_count.return_value = 2
        mock_queue.return_value = queue

        response = client.get("/api/connectivity/queue")

        assert response.status_code == 200
        data = response.get_json()
        assert data["queue"]["is_online"] is True  # Assumes online when no service


class TestAccountQueueEndpoint:
    """Tests for GET /api/connectivity/queue/<account_id> endpoint."""

    @patch("app.api.connectivity.get_action_queue")
    def test_get_account_queue(self, mock_queue, client):
        """Test getting pending actions for an account."""
        action = MagicMock()
        action.id = 1
        action.action_type = "mark_read"
        action.email_id = "email123"
        action.status = "pending"
        action.retry_count = 0
        action.created_at = datetime.now(timezone.utc)
        action.error_message = None

        queue = MagicMock()
        queue.get_pending_count.return_value = 1
        queue.get_pending_actions.return_value = [action]
        mock_queue.return_value = queue

        response = client.get("/api/connectivity/queue/1")

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["account_id"] == 1
        assert data["queue"]["total_pending"] == 1
        assert len(data["queue"]["actions"]) == 1

    @patch("app.api.connectivity.get_action_queue")
    def test_get_account_queue_with_limit(self, mock_queue, client):
        """Test getting pending actions with custom limit."""
        queue = MagicMock()
        queue.get_pending_count.return_value = 0
        queue.get_pending_actions.return_value = []
        mock_queue.return_value = queue

        response = client.get("/api/connectivity/queue/1?limit=25")

        assert response.status_code == 200
        queue.get_pending_actions.assert_called_with(account_id=1, limit=25)

    @patch("app.api.connectivity.get_action_queue")
    def test_get_account_queue_limit_capped(self, mock_queue, client):
        """Test that limit is capped at 100."""
        queue = MagicMock()
        queue.get_pending_count.return_value = 0
        queue.get_pending_actions.return_value = []
        mock_queue.return_value = queue

        response = client.get("/api/connectivity/queue/1?limit=500")

        assert response.status_code == 200
        queue.get_pending_actions.assert_called_with(account_id=1, limit=100)


class TestCancelActionEndpoint:
    """Tests for DELETE /api/connectivity/queue/<account_id>/action/<action_id> endpoint."""

    @patch("app.api.connectivity.get_action_queue")
    def test_cancel_action_success(self, mock_queue, client):
        """Test successfully cancelling an action."""
        queue = MagicMock()
        queue.cancel_action.return_value = True
        mock_queue.return_value = queue

        response = client.delete("/api/connectivity/queue/1/action/123")

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        queue.cancel_action.assert_called_with(123, account_id=1)

    @patch("app.api.connectivity.get_action_queue")
    def test_cancel_action_not_found(self, mock_queue, client):
        """Test cancelling non-existent action."""
        queue = MagicMock()
        queue.cancel_action.return_value = False
        mock_queue.return_value = queue

        response = client.delete("/api/connectivity/queue/1/action/999")

        assert response.status_code == 404
        data = response.get_json()
        assert data["success"] is False


class TestProcessQueueEndpoint:
    """Tests for POST /api/connectivity/queue/process endpoint."""

    @patch("app.api.connectivity.emit_queue_processed")
    @patch("app.api.connectivity.process_all_pending_actions")
    @patch("app.api.connectivity.get_action_queue")
    @patch("app.api.connectivity.get_connectivity_service")
    def test_process_queue_success(
        self, mock_service, mock_queue, mock_process, mock_emit, client
    ):
        """Test successful queue processing."""
        service = MagicMock()
        service.is_online = True
        mock_service.return_value = service

        queue = MagicMock()
        queue.get_pending_count.return_value = 5
        mock_queue.return_value = queue

        mock_process.return_value = {
            1: ProcessResult(total=3, completed=2, failed=1, errors=["Error 1"]),
            2: ProcessResult(total=2, completed=2, failed=0, errors=[]),
        }

        response = client.post("/api/connectivity/queue/process")

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["summary"]["total"] == 5
        assert data["summary"]["completed"] == 4
        assert data["summary"]["failed"] == 1
        mock_emit.assert_called_once_with(total=5, completed=4, failed=1)

    @patch("app.api.connectivity.get_action_queue")
    @patch("app.api.connectivity.get_connectivity_service")
    def test_process_queue_offline_rejected(self, mock_service, mock_queue, client):
        """Test that processing is rejected when offline."""
        service = MagicMock()
        service.is_online = False
        mock_service.return_value = service

        response = client.post("/api/connectivity/queue/process")

        assert response.status_code == 503
        data = response.get_json()
        assert data["success"] is False
        assert "offline" in data["error"]

    @patch("app.api.connectivity.get_action_queue")
    @patch("app.api.connectivity.get_connectivity_service")
    def test_process_queue_empty(self, mock_service, mock_queue, client):
        """Test processing empty queue."""
        service = MagicMock()
        service.is_online = True
        mock_service.return_value = service

        queue = MagicMock()
        queue.get_pending_count.return_value = 0
        mock_queue.return_value = queue

        response = client.post("/api/connectivity/queue/process")

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert "No pending actions" in data["message"]
