# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests for Push Notifications API endpoints (app/api/push_notifications.py).

Coverage goal: 0% -> 100%
Tested endpoints:
- GET /push/devices (list_devices)
- POST /push/devices (register_device)
- DELETE /push/devices/<token> (unregister_device)
- POST /push/send (send_notification)
- POST /push/broadcast (broadcast_notification)
- GET /push/stats (push_stats)
- GET /push/history (push_history)

Also tests:
- Helper functions: mask_token, parse_category
"""
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock

from app.api.app import create_app
from app.api.push_notifications import mask_token, parse_category
from app.domain.entities import (
    DeviceToken,
    DevicePlatform,
    PushNotification,
    PushNotificationCategory,
    PushNotificationRecord,
    PushNotificationStatus,
)
from app.domain.ports import PushNotificationResult


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def client():
    """Create test client."""
    app = create_app({"TESTING": True})
    with app.test_client() as client:
        yield client


@pytest.fixture
def mock_device_store():
    """Mock the device store."""
    with patch("app.api.push_notifications._get_device_store") as mock_getter:
        store = MagicMock()
        store.get_all.return_value = []
        mock_getter.return_value = store
        yield store


@pytest.fixture
def mock_push_adapter():
    """Mock the push adapter."""
    with patch("app.api.push_notifications._get_push_adapter") as mock_getter:
        adapter = MagicMock()
        adapter.name = "mock"
        mock_getter.return_value = adapter
        yield adapter


@pytest.fixture
def mock_push_service():
    """Mock the push notification service."""
    with patch("app.api.push_notifications._get_push_notification_service") as mock_getter:
        service = MagicMock()
        service.get_stats.return_value = {"sent": 0, "failed": 0}
        service.get_records.return_value = []
        mock_getter.return_value = service
        yield service


@pytest.fixture
def sample_device():
    """Create a sample device token."""
    return DeviceToken(
        token="expo_token_1234567890abcdef",
        platform=DevicePlatform.IOS,
        user_id="user-123",
        device_name="iPhone de Test",
        app_version="1.0.0",
        created_at=datetime(2026, 1, 16, 10, 0, 0),
        last_used_at=datetime(2026, 1, 16, 12, 0, 0),
        is_active=True,
    )


@pytest.fixture
def sample_notification():
    """Create a sample push notification."""
    return PushNotification(
        title="Test Title",
        body="Test body message",
        category=PushNotificationCategory.INFO,
    )


@pytest.fixture
def sample_notification_record(sample_notification):
    """Create a sample notification record."""
    return PushNotificationRecord(
        notification=sample_notification,
        device_token="expo_token_1234567890abcdef",
        status=PushNotificationStatus.SENT,
        message_id="msg-123",
        sent_at=datetime(2026, 1, 16, 12, 0, 0),
        error_message=None,
    )


# ============================================================================
# HELPER FUNCTION TESTS
# ============================================================================


class TestMaskToken:
    """Tests for mask_token helper function."""

    def test_mask_long_token(self):
        """Should mask token longer than visible_chars."""
        token = "expo_token_1234567890abcdefghijklmnop"
        result = mask_token(token)
        assert result == "expo_token_123456789..."
        assert len(result) == 23  # 20 visible + "..."

    def test_mask_short_token(self):
        """Should not mask token shorter than visible_chars."""
        token = "short_token"
        result = mask_token(token)
        assert result == "short_token"

    def test_mask_exact_length_token(self):
        """Should not mask token exactly at visible_chars."""
        token = "12345678901234567890"  # exactly 20 chars
        result = mask_token(token)
        assert result == "12345678901234567890"

    def test_mask_custom_visible_chars(self):
        """Should respect custom visible_chars parameter."""
        token = "my_long_token_value"
        result = mask_token(token, visible_chars=5)
        assert result == "my_lo..."

    def test_mask_empty_token(self):
        """Should handle empty token gracefully."""
        result = mask_token("")
        assert result == ""

    def test_mask_very_short_token(self):
        """Should not mask very short tokens."""
        result = mask_token("abc")
        assert result == "abc"


class TestParseCategory:
    """Tests for parse_category helper function."""

    def test_parse_valid_category(self):
        """Should parse valid category strings."""
        assert parse_category("draft.created") == PushNotificationCategory.DRAFT_CREATED
        assert parse_category("draft.failed") == PushNotificationCategory.DRAFT_FAILED
        assert parse_category("followup.sent") == PushNotificationCategory.FOLLOWUP_SENT
        assert parse_category("health.alert") == PushNotificationCategory.HEALTH_ALERT
        assert parse_category("budget.warning") == PushNotificationCategory.BUDGET_WARNING
        assert parse_category("error") == PushNotificationCategory.ERROR
        assert parse_category("info") == PushNotificationCategory.INFO

    def test_parse_invalid_category_returns_info(self):
        """Should return INFO for invalid categories."""
        assert parse_category("invalid") == PushNotificationCategory.INFO
        assert parse_category("unknown.category") == PushNotificationCategory.INFO
        assert parse_category("") == PushNotificationCategory.INFO

    def test_parse_case_sensitive(self):
        """Categories are case-sensitive."""
        # Valid lowercase
        assert parse_category("info") == PushNotificationCategory.INFO
        # Invalid uppercase falls back to INFO
        assert parse_category("INFO") == PushNotificationCategory.INFO


# ============================================================================
# LIST DEVICES ENDPOINT TESTS
# ============================================================================


class TestListDevicesEndpoint:
    """Tests for GET /push/devices endpoint."""

    def test_list_devices_empty(self, client, mock_device_store):
        """Should return empty list when no devices registered."""
        mock_device_store.get_all.return_value = []

        response = client.get("/push/devices")

        assert response.status_code == 200
        data = response.get_json()
        assert data["count"] == 0
        assert data["devices"] == []

    def test_list_devices_with_data(self, client, mock_device_store, sample_device):
        """Should return list of devices."""
        mock_device_store.get_all.return_value = [sample_device]

        response = client.get("/push/devices")

        assert response.status_code == 200
        data = response.get_json()
        assert data["count"] == 1
        assert len(data["devices"]) == 1
        device = data["devices"][0]
        assert device["platform"] == "ios"
        assert device["user_id"] == "user-123"
        assert device["device_name"] == "iPhone de Test"
        assert device["is_active"] is True

    def test_list_devices_token_masked(self, client, mock_device_store, sample_device):
        """Should mask device tokens in response."""
        mock_device_store.get_all.return_value = [sample_device]

        response = client.get("/push/devices")

        data = response.get_json()
        # Token should be masked (20 chars + "...")
        assert "..." in data["devices"][0]["token"]

    def test_list_devices_filter_by_user_id(self, client, mock_device_store, sample_device):
        """Should filter devices by user_id query param."""
        mock_device_store.get_all.return_value = [sample_device]

        response = client.get("/push/devices?user_id=user-123")

        assert response.status_code == 200
        mock_device_store.get_all.assert_called_once_with("user-123")

    def test_list_devices_no_filter(self, client, mock_device_store):
        """Should list all devices when no filter provided."""
        mock_device_store.get_all.return_value = []

        response = client.get("/push/devices")

        assert response.status_code == 200
        mock_device_store.get_all.assert_called_once_with(None)

    def test_list_devices_multiple(self, client, mock_device_store):
        """Should return multiple devices."""
        devices = [
            DeviceToken(token="token1_xxxxxxxxxxxx", platform=DevicePlatform.IOS, user_id="user1",
                       created_at=datetime.now()),
            DeviceToken(token="token2_xxxxxxxxxxxx", platform=DevicePlatform.ANDROID, user_id="user2",
                       created_at=datetime.now()),
        ]
        mock_device_store.get_all.return_value = devices

        response = client.get("/push/devices")

        assert response.status_code == 200
        data = response.get_json()
        assert data["count"] == 2

    def test_list_devices_without_last_used(self, client, mock_device_store):
        """Should handle device without last_used_at."""
        device = DeviceToken(
            token="token_xxxxxxxxxxxxxxxxxxxx",
            platform=DevicePlatform.ANDROID,
            created_at=datetime.now(),
            last_used_at=None,
        )
        mock_device_store.get_all.return_value = [device]

        response = client.get("/push/devices")

        assert response.status_code == 200
        data = response.get_json()
        assert data["devices"][0]["last_used_at"] is None


# ============================================================================
# REGISTER DEVICE ENDPOINT TESTS
# ============================================================================


class TestRegisterDeviceEndpoint:
    """Tests for POST /push/devices endpoint."""

    def test_register_device_success(self, client, mock_device_store, sample_device):
        """Should register a new device successfully."""
        mock_device_store.register.return_value = sample_device

        response = client.post(
            "/push/devices",
            json={
                "token": "expo_token_1234567890abcdef",
                "platform": "ios",
                "user_id": "user-123",
                "device_name": "iPhone de Test",
                "app_version": "1.0.0",
            },
            content_type="application/json",
        )

        assert response.status_code == 201
        data = response.get_json()
        assert data["success"] is True
        assert "device" in data

    def test_register_device_missing_token(self, client, mock_device_store):
        """Should return 400 when token is missing."""
        response = client.post(
            "/push/devices",
            json={"platform": "ios"},
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "token is required" in response.get_json()["error"]

    def test_register_device_missing_platform(self, client, mock_device_store):
        """Should return 400 when platform is missing."""
        response = client.post(
            "/push/devices",
            json={"token": "my_token"},
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "platform" in response.get_json()["error"]

    def test_register_device_invalid_platform(self, client, mock_device_store):
        """Should return 400 for invalid platform."""
        response = client.post(
            "/push/devices",
            json={"token": "my_token", "platform": "windows"},
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "platform" in response.get_json()["error"]

    def test_register_device_valid_platforms(self, client, mock_device_store, sample_device):
        """Should accept all valid platforms."""
        mock_device_store.register.return_value = sample_device

        for platform in ["ios", "android", "web"]:
            response = client.post(
                "/push/devices",
                json={"token": "my_token", "platform": platform},
                content_type="application/json",
            )
            assert response.status_code == 201

    def test_register_device_minimal_data(self, client, mock_device_store, sample_device):
        """Should register with minimal required data."""
        mock_device_store.register.return_value = sample_device

        response = client.post(
            "/push/devices",
            json={"token": "my_token", "platform": "android"},
            content_type="application/json",
        )

        assert response.status_code == 201

    def test_register_device_store_error(self, client, mock_device_store):
        """Should handle store ValueError."""
        mock_device_store.register.side_effect = ValueError("Token already exists")

        response = client.post(
            "/push/devices",
            json={"token": "my_token", "platform": "ios"},
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "Token already exists" in response.get_json()["error"]

    def test_register_device_empty_token(self, client, mock_device_store):
        """Should return 400 for empty token."""
        response = client.post(
            "/push/devices",
            json={"token": "", "platform": "ios"},
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_register_device_no_json(self, client, mock_device_store):
        """Should return error when no JSON body provided."""
        response = client.post("/push/devices")

        # Flask returns 415 Unsupported Media Type for missing Content-Type
        assert response.status_code in (400, 415)


# ============================================================================
# UNREGISTER DEVICE ENDPOINT TESTS
# ============================================================================


class TestUnregisterDeviceEndpoint:
    """Tests for DELETE /push/devices/<token> endpoint."""

    def test_unregister_device_success(self, client, mock_device_store):
        """Should unregister device successfully."""
        mock_device_store.unregister.return_value = True

        response = client.delete("/push/devices/my_device_token")

        assert response.status_code == 200
        assert response.get_json()["success"] is True

    def test_unregister_device_not_found(self, client, mock_device_store):
        """Should return 404 when device not found."""
        mock_device_store.unregister.return_value = False

        response = client.delete("/push/devices/nonexistent_token")

        assert response.status_code == 404
        assert "not found" in response.get_json()["error"].lower()

    def test_unregister_device_special_chars(self, client, mock_device_store):
        """Should handle tokens with URL-safe characters."""
        mock_device_store.unregister.return_value = True

        response = client.delete("/push/devices/token-with_special.chars")

        assert response.status_code == 200


# ============================================================================
# SEND NOTIFICATION ENDPOINT TESTS
# ============================================================================


class TestSendNotificationEndpoint:
    """Tests for POST /push/send endpoint."""

    def test_send_notification_single_token(self, client, mock_push_service):
        """Should send notification to single token."""
        mock_push_service.send_to_token.return_value = PushNotificationResult(
            success=True,
            message_id="msg-123",
        )

        response = client.post(
            "/push/send",
            json={
                "token": "my_token",
                "title": "Hello",
                "body": "World",
            },
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["message_id"] == "msg-123"

    def test_send_notification_multiple_tokens(self, client, mock_push_service):
        """Should send notification to multiple tokens."""
        mock_push_service.send_to_tokens.return_value = [
            PushNotificationResult(success=True, message_id="msg-1"),
            PushNotificationResult(success=False, error_message="Failed"),
        ]

        response = client.post(
            "/push/send",
            json={
                "tokens": ["token1", "token2"],
                "title": "Hello",
                "body": "World",
            },
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["total"] == 2
        assert data["success"] == 1
        assert data["failed"] == 1

    def test_send_notification_missing_tokens(self, client, mock_push_service):
        """Should return 400 when tokens missing."""
        response = client.post(
            "/push/send",
            json={"title": "Hello", "body": "World"},
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "token" in response.get_json()["error"].lower()

    def test_send_notification_missing_title(self, client, mock_push_service):
        """Should return 400 when title missing."""
        response = client.post(
            "/push/send",
            json={"token": "my_token", "body": "World"},
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "title" in response.get_json()["error"].lower()

    def test_send_notification_missing_body(self, client, mock_push_service):
        """Should return 400 when body missing."""
        response = client.post(
            "/push/send",
            json={"token": "my_token", "title": "Hello"},
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "body" in response.get_json()["error"].lower()

    def test_send_notification_with_category(self, client, mock_push_service):
        """Should pass category to service."""
        mock_push_service.send_to_token.return_value = PushNotificationResult(success=True)

        response = client.post(
            "/push/send",
            json={
                "token": "my_token",
                "title": "Hello",
                "body": "World",
                "category": "draft.created",
            },
            content_type="application/json",
        )

        assert response.status_code == 200
        call_args = mock_push_service.send_to_token.call_args
        assert call_args[1]["category"] == PushNotificationCategory.DRAFT_CREATED

    def test_send_notification_with_priority(self, client, mock_push_service):
        """Should pass priority to service."""
        mock_push_service.send_to_token.return_value = PushNotificationResult(success=True)

        response = client.post(
            "/push/send",
            json={
                "token": "my_token",
                "title": "Hello",
                "body": "World",
                "priority": "high",
            },
            content_type="application/json",
        )

        assert response.status_code == 200
        call_args = mock_push_service.send_to_token.call_args
        assert call_args[1]["priority"] == "high"

    def test_send_notification_with_extra_data(self, client, mock_push_service):
        """Should pass extra data to service."""
        mock_push_service.send_to_token.return_value = PushNotificationResult(success=True)

        response = client.post(
            "/push/send",
            json={
                "token": "my_token",
                "title": "Hello",
                "body": "World",
                "data": {"email_id": "123", "action": "view"},
            },
            content_type="application/json",
        )

        assert response.status_code == 200
        call_args = mock_push_service.send_to_token.call_args
        assert call_args[1]["data"] == {"email_id": "123", "action": "view"}

    def test_send_notification_failure(self, client, mock_push_service):
        """Should return 500 on send failure."""
        mock_push_service.send_to_token.return_value = PushNotificationResult(
            success=False,
            error_message="Network error",
        )

        response = client.post(
            "/push/send",
            json={
                "token": "my_token",
                "title": "Hello",
                "body": "World",
            },
            content_type="application/json",
        )

        assert response.status_code == 500
        data = response.get_json()
        assert data["success"] is False
        assert "Network error" in data["error"]

    def test_send_notification_tokens_as_string(self, client, mock_push_service):
        """Should handle tokens parameter as string (single token)."""
        mock_push_service.send_to_token.return_value = PushNotificationResult(success=True)

        response = client.post(
            "/push/send",
            json={
                "tokens": "single_token",  # String instead of list
                "title": "Hello",
                "body": "World",
            },
            content_type="application/json",
        )

        assert response.status_code == 200
        mock_push_service.send_to_token.assert_called_once()

    def test_send_notification_results_masked_tokens(self, client, mock_push_service):
        """Should mask tokens in multi-token response."""
        # Need 2+ tokens to trigger the multi-token path (len > 1)
        mock_push_service.send_to_tokens.return_value = [
            PushNotificationResult(success=True, message_id="msg-1"),
            PushNotificationResult(success=True, message_id="msg-2"),
        ]

        response = client.post(
            "/push/send",
            json={
                "tokens": [
                    "very_long_token_1234567890_abcdefghij",
                    "another_long_token_0987654321_zyxwvutsrq",
                ],
                "title": "Hello",
                "body": "World",
            },
            content_type="application/json",
        )

        data = response.get_json()
        # Tokens should be masked in results
        assert "..." in data["results"][0]["token"]
        assert "..." in data["results"][1]["token"]


# ============================================================================
# BROADCAST NOTIFICATION ENDPOINT TESTS
# ============================================================================


_ADMIN_HEADERS = {"Authorization": "Bearer admin-stub"}


class TestBroadcastNotificationEndpoint:
    """Tests for POST /push/broadcast endpoint.

    C-3 (audit, issue #523, 2026-05-05): /push/broadcast is now under
    @require_admin. The autouse fixture below stubs _decode_jwt and
    _is_admin so the existing tests keep exercising the success path; the
    admin-gating itself is regression-tested in
    tests/audit_fixes/test_c_03_push_broadcast_admin_only.py.
    """

    @pytest.fixture(autouse=True)
    def _stub_admin(self, monkeypatch):
        fake_payload = {"sub": "1", "email": "admin@test.com"}
        monkeypatch.setattr("app.api.auth._decode_jwt", lambda token: fake_payload)
        monkeypatch.setattr("app.api.admin._is_admin", lambda email: True)
        yield

    def test_broadcast_success(self, client, mock_push_service):
        """Should broadcast notification to all devices."""
        mock_push_service.broadcast.return_value = [
            PushNotificationResult(success=True),
            PushNotificationResult(success=True),
        ]

        response = client.post(
            "/push/broadcast",
            json={"title": "Announcement", "body": "System update"},
            content_type="application/json",
            headers=_ADMIN_HEADERS,
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["total_devices"] == 2
        assert data["success"] == 2
        assert data["failed"] == 0

    def test_broadcast_no_devices(self, client, mock_push_service):
        """Should handle broadcast when no devices registered."""
        mock_push_service.broadcast.return_value = []

        response = client.post(
            "/push/broadcast",
            json={"title": "Announcement", "body": "System update"},
            content_type="application/json",
            headers=_ADMIN_HEADERS,
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert "No devices registered" in data["message"]
        assert data["sent"] == 0

    def test_broadcast_partial_failure(self, client, mock_push_service):
        """Should report partial failures."""
        mock_push_service.broadcast.return_value = [
            PushNotificationResult(success=True),
            PushNotificationResult(success=False),
            PushNotificationResult(success=True),
        ]

        response = client.post(
            "/push/broadcast",
            json={"title": "Announcement", "body": "System update"},
            content_type="application/json",
            headers=_ADMIN_HEADERS,
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["total_devices"] == 3
        assert data["success"] == 2
        assert data["failed"] == 1

    def test_broadcast_missing_title(self, client, mock_push_service):
        """Should return 400 when title missing."""
        response = client.post(
            "/push/broadcast",
            json={"body": "System update"},
            content_type="application/json",
            headers=_ADMIN_HEADERS,
        )

        assert response.status_code == 400

    def test_broadcast_missing_body(self, client, mock_push_service):
        """Should return 400 when body missing."""
        response = client.post(
            "/push/broadcast",
            json={"title": "Announcement"},
            content_type="application/json",
            headers=_ADMIN_HEADERS,
        )

        assert response.status_code == 400

    def test_broadcast_with_user_id(self, client, mock_push_service):
        """Should filter broadcast by user_id."""
        mock_push_service.broadcast.return_value = [PushNotificationResult(success=True)]

        response = client.post(
            "/push/broadcast",
            json={
                "title": "Hello",
                "body": "Personal message",
                "user_id": "user-123",
            },
            content_type="application/json",
            headers=_ADMIN_HEADERS,
        )

        assert response.status_code == 200
        call_args = mock_push_service.broadcast.call_args
        assert call_args[1]["user_id"] == "user-123"

    def test_broadcast_with_category(self, client, mock_push_service):
        """Should pass category to service."""
        mock_push_service.broadcast.return_value = [PushNotificationResult(success=True)]

        response = client.post(
            "/push/broadcast",
            json={
                "title": "Alert",
                "body": "Budget exceeded",
                "category": "budget.warning",
            },
            content_type="application/json",
            headers=_ADMIN_HEADERS,
        )

        assert response.status_code == 200
        call_args = mock_push_service.broadcast.call_args
        assert call_args[1]["category"] == PushNotificationCategory.BUDGET_WARNING

    def test_broadcast_with_extra_data(self, client, mock_push_service):
        """Should pass extra data to service."""
        mock_push_service.broadcast.return_value = [PushNotificationResult(success=True)]

        response = client.post(
            "/push/broadcast",
            json={
                "title": "Alert",
                "body": "Message",
                "data": {"action": "refresh"},
            },
            content_type="application/json",
            headers=_ADMIN_HEADERS,
        )

        assert response.status_code == 200
        call_args = mock_push_service.broadcast.call_args
        assert call_args[1]["data"] == {"action": "refresh"}


# ============================================================================
# STATS ENDPOINT TESTS
# ============================================================================


class TestPushStatsEndpoint:
    """Tests for GET /push/stats endpoint."""

    @pytest.fixture(autouse=True)
    def _stub_admin(self, monkeypatch):
        # /push/stats is @require_admin (device-count enumeration guard, audit
        # h-03/C-3). Stub the JWT decoder + admin check so these shape tests
        # exercise the 200 path; the gating itself is regression-tested in
        # tests/audit_fixes/test_c_03_push_broadcast_admin_only.py.
        fake_payload = {"sub": "1", "email": "admin@test.com"}
        monkeypatch.setattr("app.api.auth._decode_jwt", lambda token: fake_payload)
        monkeypatch.setattr("app.api.admin._is_admin", lambda email: True)
        yield

    def test_stats_empty(self, client, mock_push_service, mock_device_store, mock_push_adapter):
        """Should return stats with no data."""
        mock_push_service.get_stats.return_value = {"sent": 0, "failed": 0}
        mock_device_store.get_all.return_value = []

        response = client.get("/push/stats", headers=_ADMIN_HEADERS)

        assert response.status_code == 200
        data = response.get_json()
        assert "notifications" in data
        assert "devices" in data
        assert data["devices"]["total"] == 0

    def test_stats_with_data(self, client, mock_push_service, mock_device_store, mock_push_adapter, sample_device):
        """Should return stats with device data."""
        mock_push_service.get_stats.return_value = {"sent": 10, "failed": 2}
        mock_device_store.get_all.return_value = [
            sample_device,
            DeviceToken(token="token2", platform=DevicePlatform.ANDROID, created_at=datetime.now()),
        ]

        response = client.get("/push/stats", headers=_ADMIN_HEADERS)

        assert response.status_code == 200
        data = response.get_json()
        assert data["notifications"]["sent"] == 10
        assert data["notifications"]["failed"] == 2
        assert data["devices"]["total"] == 2
        assert "ios" in data["devices"]["by_platform"]
        assert "android" in data["devices"]["by_platform"]

    def test_stats_provider_name(self, client, mock_push_service, mock_device_store, mock_push_adapter):
        """Should include provider name."""
        mock_push_service.get_stats.return_value = {}
        mock_device_store.get_all.return_value = []
        mock_push_adapter.name = "expo"

        response = client.get("/push/stats", headers=_ADMIN_HEADERS)

        assert response.status_code == 200
        data = response.get_json()
        assert data["provider"] == "expo"

    def test_stats_platform_breakdown(self, client, mock_push_service, mock_device_store, mock_push_adapter):
        """Should breakdown devices by platform."""
        mock_push_service.get_stats.return_value = {}
        devices = [
            DeviceToken(token="t1", platform=DevicePlatform.IOS, created_at=datetime.now()),
            DeviceToken(token="t2", platform=DevicePlatform.IOS, created_at=datetime.now()),
            DeviceToken(token="t3", platform=DevicePlatform.ANDROID, created_at=datetime.now()),
            DeviceToken(token="t4", platform=DevicePlatform.WEB, created_at=datetime.now()),
        ]
        mock_device_store.get_all.return_value = devices

        response = client.get("/push/stats", headers=_ADMIN_HEADERS)

        data = response.get_json()
        assert data["devices"]["by_platform"]["ios"] == 2
        assert data["devices"]["by_platform"]["android"] == 1
        assert data["devices"]["by_platform"]["web"] == 1


# ============================================================================
# HISTORY ENDPOINT TESTS
# ============================================================================


class TestPushHistoryEndpoint:
    """Tests for GET /push/history endpoint."""

    @pytest.fixture(autouse=True)
    def _stub_admin(self, monkeypatch):
        # /push/history is @require_admin (sent-notification history is an
        # account-spanning read, audit h-03/C-3). Stub admin auth for the 200
        # path; gating is regression-tested in test_c_03_push_broadcast_admin_only.py.
        fake_payload = {"sub": "1", "email": "admin@test.com"}
        monkeypatch.setattr("app.api.auth._decode_jwt", lambda token: fake_payload)
        monkeypatch.setattr("app.api.admin._is_admin", lambda email: True)
        yield

    def test_history_empty(self, client, mock_push_service):
        """Should return empty history."""
        mock_push_service.get_records.return_value = []

        response = client.get("/push/history", headers=_ADMIN_HEADERS)

        assert response.status_code == 200
        data = response.get_json()
        assert data["count"] == 0
        assert data["history"] == []

    def test_history_with_records(self, client, mock_push_service, sample_notification_record):
        """Should return notification history."""
        mock_push_service.get_records.return_value = [sample_notification_record]

        response = client.get("/push/history", headers=_ADMIN_HEADERS)

        assert response.status_code == 200
        data = response.get_json()
        assert data["count"] == 1
        record = data["history"][0]
        assert record["title"] == "Test Title"
        assert record["body"] == "Test body message"
        assert record["status"] == "sent"
        assert record["message_id"] == "msg-123"

    def test_history_default_limit(self, client, mock_push_service):
        """Should use default limit of 50."""
        mock_push_service.get_records.return_value = []

        response = client.get("/push/history", headers=_ADMIN_HEADERS)

        assert response.status_code == 200
        mock_push_service.get_records.assert_called_once_with(limit=50)

    def test_history_custom_limit(self, client, mock_push_service):
        """Should accept custom limit parameter."""
        mock_push_service.get_records.return_value = []

        response = client.get("/push/history?limit=10", headers=_ADMIN_HEADERS)

        assert response.status_code == 200
        mock_push_service.get_records.assert_called_once_with(limit=10)

    def test_history_token_masked(self, client, mock_push_service, sample_notification_record):
        """Should mask device tokens in history."""
        sample_notification_record.device_token = "very_long_device_token_1234567890"
        mock_push_service.get_records.return_value = [sample_notification_record]

        response = client.get("/push/history", headers=_ADMIN_HEADERS)

        data = response.get_json()
        assert "..." in data["history"][0]["device_token"]

    def test_history_with_error(self, client, mock_push_service, sample_notification):
        """Should include error messages in history."""
        failed_record = PushNotificationRecord(
            notification=sample_notification,
            device_token="token123",
            status=PushNotificationStatus.FAILED,
            error_message="Device token expired",
            sent_at=datetime.now(),
        )
        mock_push_service.get_records.return_value = [failed_record]

        response = client.get("/push/history", headers=_ADMIN_HEADERS)

        data = response.get_json()
        assert data["history"][0]["error"] == "Device token expired"
        assert data["history"][0]["status"] == "failed"


# ============================================================================
# EDGE CASES AND ERROR HANDLING TESTS
# ============================================================================


class TestPushNotificationsEdgeCases:
    """Edge cases and error handling tests."""

    @pytest.fixture(autouse=True)
    def _stub_admin_for_broadcast(self, monkeypatch):
        """C-3 (issue #523): /push/broadcast is admin-only. Stub the JWT
        decoder + admin check so the existing edge-case tests keep
        exercising the validation path. Other endpoints in this class are
        not admin-gated, so the stub is harmless to them."""
        fake_payload = {"sub": "1", "email": "admin@test.com"}
        monkeypatch.setattr("app.api.auth._decode_jwt", lambda token: fake_payload)
        monkeypatch.setattr("app.api.admin._is_admin", lambda email: True)
        yield

    def test_register_device_optional_fields(self, client, mock_device_store, sample_device):
        """Should register device with only required fields."""
        mock_device_store.register.return_value = sample_device

        response = client.post(
            "/push/devices",
            json={"token": "my_token", "platform": "ios"},
            content_type="application/json",
        )

        assert response.status_code == 201
        # Verify optional fields passed as None
        call_kwargs = mock_device_store.register.call_args[1]
        assert call_kwargs.get("user_id") is None
        assert call_kwargs.get("device_name") is None
        assert call_kwargs.get("app_version") is None

    def test_send_empty_tokens_list(self, client, mock_push_service):
        """Should return 400 for empty tokens list."""
        response = client.post(
            "/push/send",
            json={
                "tokens": [],
                "title": "Hello",
                "body": "World",
            },
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_broadcast_empty_title(self, client, mock_push_service):
        """Should return 400 for empty title."""
        response = client.post(
            "/push/broadcast",
            json={"title": "", "body": "Content"},
            content_type="application/json",
            headers=_ADMIN_HEADERS,
        )

        assert response.status_code == 400

    def test_broadcast_empty_body(self, client, mock_push_service):
        """Should return 400 for empty body."""
        response = client.post(
            "/push/broadcast",
            json={"title": "Title", "body": ""},
            content_type="application/json",
            headers=_ADMIN_HEADERS,
        )

        assert response.status_code == 400

    def test_default_category_on_invalid(self, client, mock_push_service):
        """Should use INFO category for invalid category values."""
        mock_push_service.send_to_token.return_value = PushNotificationResult(success=True)

        response = client.post(
            "/push/send",
            json={
                "token": "my_token",
                "title": "Hello",
                "body": "World",
                "category": "invalid.category",
            },
            content_type="application/json",
        )

        assert response.status_code == 200
        call_args = mock_push_service.send_to_token.call_args
        assert call_args[1]["category"] == PushNotificationCategory.INFO

    def test_default_priority(self, client, mock_push_service):
        """Should use default priority when not specified."""
        mock_push_service.send_to_token.return_value = PushNotificationResult(success=True)

        response = client.post(
            "/push/send",
            json={
                "token": "my_token",
                "title": "Hello",
                "body": "World",
            },
            content_type="application/json",
        )

        assert response.status_code == 200
        call_args = mock_push_service.send_to_token.call_args
        assert call_args[1]["priority"] == "normal"

    def test_empty_extra_data_default(self, client, mock_push_service):
        """Should use empty dict for data when not specified."""
        mock_push_service.send_to_token.return_value = PushNotificationResult(success=True)

        response = client.post(
            "/push/send",
            json={
                "token": "my_token",
                "title": "Hello",
                "body": "World",
            },
            content_type="application/json",
        )

        assert response.status_code == 200
        call_args = mock_push_service.send_to_token.call_args
        assert call_args[1]["data"] == {}


# ============================================================================
# INTEGRATION TESTS (with all mocks combined)
# ============================================================================


class TestPushNotificationsIntegration:
    """Integration tests with combined mocks."""

    @pytest.fixture(autouse=True)
    def _stub_admin(self, monkeypatch):
        # The flow test reads /push/stats + /push/history (both @require_admin).
        # Stub admin auth; per-user /push/devices calls send no header and keep
        # using the loopback bypass, so this is inert for them.
        fake_payload = {"sub": "1", "email": "admin@test.com"}
        monkeypatch.setattr("app.api.auth._decode_jwt", lambda token: fake_payload)
        monkeypatch.setattr("app.api.admin._is_admin", lambda email: True)
        yield

    def test_full_device_lifecycle(self, client, mock_device_store, sample_device):
        """Test complete device registration and unregistration lifecycle."""
        # Register
        mock_device_store.register.return_value = sample_device
        reg_response = client.post(
            "/push/devices",
            json={"token": "my_token", "platform": "ios"},
            content_type="application/json",
        )
        assert reg_response.status_code == 201

        # List
        mock_device_store.get_all.return_value = [sample_device]
        list_response = client.get("/push/devices")
        assert list_response.status_code == 200
        assert list_response.get_json()["count"] == 1

        # Unregister
        mock_device_store.unregister.return_value = True
        unreg_response = client.delete("/push/devices/my_token")
        assert unreg_response.status_code == 200

    def test_notification_flow(self, client, mock_push_service, mock_device_store, mock_push_adapter, sample_notification_record):
        """Test complete notification send and history flow."""
        # Send notification
        mock_push_service.send_to_token.return_value = PushNotificationResult(
            success=True, message_id="msg-123"
        )
        send_response = client.post(
            "/push/send",
            json={"token": "my_token", "title": "Test", "body": "Message"},
            content_type="application/json",
        )
        assert send_response.status_code == 200

        # Check history
        mock_push_service.get_records.return_value = [sample_notification_record]
        history_response = client.get("/push/history", headers=_ADMIN_HEADERS)
        assert history_response.status_code == 200
        assert history_response.get_json()["count"] >= 1

        # Check stats
        mock_push_service.get_stats.return_value = {"sent": 1, "failed": 0}
        mock_device_store.get_all.return_value = []
        stats_response = client.get("/push/stats", headers=_ADMIN_HEADERS)
        assert stats_response.status_code == 200
        assert stats_response.get_json()["notifications"]["sent"] == 1
