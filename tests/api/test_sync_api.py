# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Integration tests for sync API endpoints.

Tests cover:
- GET /api/sync/status - Get sync service status
- POST /api/sync/trigger - Trigger manual sync
- GET /api/sync/history - Get sync history
"""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.api.app import create_app
from app.services.sync_service import SyncResult, SyncService, SyncStatus


@pytest.fixture
def app():
    """Create application for testing."""
    app = create_app({"TESTING": True})
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


# ==============================================================================
# GET /api/sync/status Tests
# ==============================================================================


class TestGetSyncStatus:
    """Tests for GET /api/sync/status endpoint."""

    def test_status_when_service_not_initialized(self, client):
        """Test status returns 503 when service not initialized."""
        with patch("app.api.sync.get_sync_service", return_value=None):
            response = client.get("/api/sync/status")

        assert response.status_code == 503
        data = json.loads(response.data)
        assert data["success"] is False
        assert "not initialized" in data["error"].lower()

    def test_status_when_service_running(self, client):
        """Test status returns correct data when service is running."""
        mock_service = MagicMock(spec=SyncService)
        mock_status = SyncStatus(
            is_running=True,
            is_syncing=False,
            last_sync_at=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
            next_sync_at=datetime(2024, 1, 15, 12, 2, 0, tzinfo=timezone.utc),
            sync_interval_seconds=120,
        )
        mock_service.status = mock_status

        with patch("app.api.sync.get_sync_service", return_value=mock_service):
            response = client.get("/api/sync/status")

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["success"] is True
        assert data["status"]["is_running"] is True
        assert data["status"]["is_syncing"] is False
        assert data["status"]["sync_interval_seconds"] == 120
        assert "2024-01-15" in data["status"]["last_sync_at"]

    def test_status_when_syncing(self, client):
        """Test status shows is_syncing=True during sync."""
        mock_service = MagicMock(spec=SyncService)
        mock_status = SyncStatus(
            is_running=True,
            is_syncing=True,
            sync_interval_seconds=60,
        )
        mock_service.status = mock_status

        with patch("app.api.sync.get_sync_service", return_value=mock_service):
            response = client.get("/api/sync/status")

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["status"]["is_syncing"] is True

    def test_status_with_null_timestamps(self, client):
        """Test status handles null timestamps correctly."""
        mock_service = MagicMock(spec=SyncService)
        mock_status = SyncStatus(
            is_running=False,
            is_syncing=False,
            last_sync_at=None,
            next_sync_at=None,
            sync_interval_seconds=120,
        )
        mock_service.status = mock_status

        with patch("app.api.sync.get_sync_service", return_value=mock_service):
            response = client.get("/api/sync/status")

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["status"]["last_sync_at"] is None
        assert data["status"]["next_sync_at"] is None


# ==============================================================================
# POST /api/sync/trigger Tests
# ==============================================================================


_ADMIN_HEADERS = {"Authorization": "Bearer admin-stub"}


class TestTriggerSync:
    """Tests for POST /api/sync/trigger endpoint.

    M-1 (audit, issue #535, 2026-05-05): /api/sync/trigger is now under
    `@require_admin`. The autouse fixture stubs `_decode_jwt` + `_is_admin`
    so the existing tests keep exercising the success path; the admin
    gating itself is regression-tested in
    tests/audit_fixes/test_m_01_sync_trigger_admin_only.py.
    """

    @pytest.fixture(autouse=True)
    def _stub_admin(self, monkeypatch):
        fake_payload = {"sub": "1", "email": "admin@test.com"}
        monkeypatch.setattr("app.api.auth._decode_jwt", lambda token: fake_payload)
        monkeypatch.setattr("app.api.admin._is_admin", lambda email: True)
        yield

    def test_trigger_when_service_not_initialized(self, client):
        """Test trigger returns 503 when service not initialized."""
        with patch("app.api.sync.get_sync_service", return_value=None):
            response = client.post("/api/sync/trigger", headers=_ADMIN_HEADERS)

        assert response.status_code == 503
        data = json.loads(response.data)
        assert data["success"] is False
        assert "not initialized" in data["error"].lower()

    def test_trigger_when_service_not_running(self, client):
        """Test trigger returns 503 when service not running."""
        mock_service = MagicMock(spec=SyncService)
        mock_service.is_running = False

        with patch("app.api.sync.get_sync_service", return_value=mock_service):
            response = client.post("/api/sync/trigger", headers=_ADMIN_HEADERS)

        assert response.status_code == 503
        data = json.loads(response.data)
        assert data["success"] is False
        assert "not running" in data["error"].lower()

    def test_trigger_success(self, client):
        """Test successful sync trigger."""
        mock_service = MagicMock(spec=SyncService)
        mock_service.is_running = True
        mock_service.trigger_sync.return_value = True

        with patch("app.api.sync.get_sync_service", return_value=mock_service):
            response = client.post("/api/sync/trigger", headers=_ADMIN_HEADERS)

        assert response.status_code == 202
        data = json.loads(response.data)
        assert data["success"] is True
        assert "triggered" in data["message"].lower()
        mock_service.trigger_sync.assert_called_once()

    def test_trigger_when_already_syncing(self, client):
        """Test trigger returns 409 when sync already in progress."""
        mock_service = MagicMock(spec=SyncService)
        mock_service.is_running = True
        mock_service.trigger_sync.return_value = False

        with patch("app.api.sync.get_sync_service", return_value=mock_service):
            response = client.post("/api/sync/trigger", headers=_ADMIN_HEADERS)

        assert response.status_code == 409
        data = json.loads(response.data)
        assert data["success"] is False
        assert "already in progress" in data["error"].lower()


# ==============================================================================
# GET /api/sync/history Tests
# ==============================================================================


class TestGetSyncHistory:
    """Tests for GET /api/sync/history endpoint."""

    def test_history_when_service_not_initialized(self, client):
        """Test history returns 503 when service not initialized."""
        with patch("app.api.sync.get_sync_service", return_value=None):
            response = client.get("/api/sync/history")

        assert response.status_code == 503
        data = json.loads(response.data)
        assert data["success"] is False
        assert "not initialized" in data["error"].lower()

    def test_history_empty(self, client):
        """Test history returns empty list when no syncs done."""
        mock_service = MagicMock(spec=SyncService)
        mock_status = SyncStatus(last_sync_at=None, last_results=[])
        mock_service.status = mock_status

        with patch("app.api.sync.get_sync_service", return_value=mock_service):
            response = client.get("/api/sync/history")

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["success"] is True
        assert data["history"] == []
        assert data["last_sync_at"] is None

    def test_history_with_results(self, client):
        """Test history returns sync results."""
        results = [
            SyncResult(
                account_id=1,
                account_email="test@gmail.com",
                success=True,
                new_emails_count=5,
                duration_ms=100,
            ),
            SyncResult(
                account_id=2,
                account_email="test@outlook.com",
                success=False,
                error_message="Auth failed",
                duration_ms=50,
            ),
        ]
        mock_service = MagicMock(spec=SyncService)
        mock_status = SyncStatus(
            last_sync_at=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
            last_results=results,
        )
        mock_service.status = mock_status

        with patch("app.api.sync.get_sync_service", return_value=mock_service):
            response = client.get("/api/sync/history")

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["success"] is True
        assert len(data["history"]) == 2

        # First result
        assert data["history"][0]["account_id"] == 1
        assert data["history"][0]["account_email"] == "test@gmail.com"
        assert data["history"][0]["success"] is True
        assert data["history"][0]["new_emails_count"] == 5

        # Second result
        assert data["history"][1]["account_id"] == 2
        assert data["history"][1]["success"] is False
        assert data["history"][1]["error_message"] == "Auth failed"

    def test_history_with_limit(self, client):
        """Test history respects limit parameter."""
        results = [
            SyncResult(account_id=i, account_email=f"test{i}@example.com", success=True)
            for i in range(20)
        ]
        mock_service = MagicMock(spec=SyncService)
        mock_status = SyncStatus(
            last_sync_at=datetime.now(timezone.utc),
            last_results=results,
        )
        mock_service.status = mock_status

        with patch("app.api.sync.get_sync_service", return_value=mock_service):
            response = client.get("/api/sync/history?limit=5")

        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data["history"]) == 5

    def test_history_limit_max_100(self, client):
        """Test history limit is capped at 100."""
        results = [
            SyncResult(account_id=i, account_email=f"test{i}@example.com", success=True)
            for i in range(150)
        ]
        mock_service = MagicMock(spec=SyncService)
        mock_status = SyncStatus(
            last_sync_at=datetime.now(timezone.utc),
            last_results=results,
        )
        mock_service.status = mock_status

        with patch("app.api.sync.get_sync_service", return_value=mock_service):
            response = client.get("/api/sync/history?limit=200")

        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data["history"]) == 100  # Capped at 100

    def test_history_invalid_limit_uses_default(self, client):
        """Test history uses default limit for invalid parameter."""
        results = [
            SyncResult(account_id=i, account_email=f"test{i}@example.com", success=True)
            for i in range(20)
        ]
        mock_service = MagicMock(spec=SyncService)
        mock_status = SyncStatus(
            last_sync_at=datetime.now(timezone.utc),
            last_results=results,
        )
        mock_service.status = mock_status

        with patch("app.api.sync.get_sync_service", return_value=mock_service):
            response = client.get("/api/sync/history?limit=invalid")

        assert response.status_code == 200
        data = json.loads(response.data)
        # Default limit is 10
        assert len(data["history"]) == 10


# ==============================================================================
# Edge Cases
# ==============================================================================


class TestSyncApiEdgeCases:
    """Tests for edge cases in sync API."""

    def test_status_endpoint_accepts_only_get(self, client):
        """Test status endpoint only accepts GET requests."""
        with patch("app.api.sync.get_sync_service") as mock_get:
            mock_service = MagicMock()
            mock_service.status = SyncStatus()
            mock_get.return_value = mock_service

            # POST should not be allowed
            response = client.post("/api/sync/status")
            assert response.status_code == 405

            # PUT should not be allowed
            response = client.put("/api/sync/status")
            assert response.status_code == 405

    def test_trigger_endpoint_accepts_only_post(self, client):
        """Test trigger endpoint only accepts POST requests."""
        with patch("app.api.sync.get_sync_service") as mock_get:
            mock_service = MagicMock()
            mock_service.is_running = True
            mock_service.trigger_sync.return_value = True
            mock_get.return_value = mock_service

            # GET should not be allowed
            response = client.get("/api/sync/trigger")
            assert response.status_code == 405

    def test_history_endpoint_accepts_only_get(self, client):
        """Test history endpoint only accepts GET requests."""
        with patch("app.api.sync.get_sync_service") as mock_get:
            mock_service = MagicMock()
            mock_service.status = SyncStatus()
            mock_get.return_value = mock_service

            # POST should not be allowed
            response = client.post("/api/sync/history")
            assert response.status_code == 405
