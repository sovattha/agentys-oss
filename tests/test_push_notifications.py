# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour les notifications push mobiles.

Ces tests couvrent :
- Les entités de domaine (DeviceToken, PushNotification)
- Le port NotificationPort
- Les adapters (Mock, FCM, Expo)
- Le use case SendPushNotificationUseCase
- L'API REST pour les devices
- L'intégration avec NotificationManager
"""

import pytest
import json
from unittest.mock import Mock, patch

# Domain entities
from app.domain.entities import (
    DeviceToken,
    DevicePlatform,
    PushNotification,
    PushNotificationCategory,
    PushNotificationStatus,
    PushNotificationRecord,
)

# Domain ports
from app.domain.ports import (
    PushNotificationResult,
)

# Adapters
from app.adapters.push import MockPushAdapter, FCMAdapter, ExpoAdapter

# Application use case
from app.application import SendPushNotificationUseCase


# ============================================================================
# TESTS - DOMAIN ENTITIES
# ============================================================================

class TestDeviceToken:
    """Tests pour l'entité DeviceToken."""

    def test_create_device_token(self):
        """Test création d'un DeviceToken valide."""
        device = DeviceToken(
            token="test_token_123",
            platform=DevicePlatform.IOS,
            user_id="user_1",
            device_name="iPhone de Jean",
        )

        assert device.token == "test_token_123"
        assert device.platform == DevicePlatform.IOS
        assert device.user_id == "user_1"
        assert device.device_name == "iPhone de Jean"
        assert device.is_active is True
        assert device.created_at is not None

    def test_create_device_token_with_string_platform(self):
        """Test création avec plateforme en string."""
        device = DeviceToken(
            token="test_token",
            platform="android",
        )
        assert device.platform == DevicePlatform.ANDROID

    def test_device_token_empty_raises(self):
        """Test qu'un token vide lève une erreur."""
        with pytest.raises(ValueError, match="cannot be empty"):
            DeviceToken(token="", platform=DevicePlatform.IOS)

    def test_device_token_to_dict(self):
        """Test sérialisation en dictionnaire."""
        device = DeviceToken(
            token="test_token",
            platform=DevicePlatform.ANDROID,
            user_id="user_1",
        )
        data = device.to_dict()

        assert data["token"] == "test_token"
        assert data["platform"] == "android"
        assert data["user_id"] == "user_1"
        assert data["is_active"] is True

    def test_device_token_from_dict(self):
        """Test désérialisation depuis dictionnaire."""
        data = {
            "token": "test_token",
            "platform": "ios",
            "user_id": "user_1",
            "device_name": "Test Device",
            "created_at": "2024-01-01T12:00:00",
            "is_active": True,
        }
        device = DeviceToken.from_dict(data)

        assert device.token == "test_token"
        assert device.platform == DevicePlatform.IOS
        assert device.user_id == "user_1"


class TestPushNotification:
    """Tests pour l'entité PushNotification."""

    def test_create_push_notification(self):
        """Test création d'une PushNotification valide."""
        notif = PushNotification(
            title="Test Title",
            body="Test body message",
            category=PushNotificationCategory.DRAFT_CREATED,
            data={"key": "value"},
        )

        assert notif.title == "Test Title"
        assert notif.body == "Test body message"
        assert notif.category == PushNotificationCategory.DRAFT_CREATED
        assert notif.data == {"key": "value"}
        assert notif.priority == "normal"

    def test_push_notification_empty_title_raises(self):
        """Test qu'un titre vide lève une erreur."""
        with pytest.raises(ValueError, match="title cannot be empty"):
            PushNotification(title="", body="Body")

    def test_push_notification_empty_body_raises(self):
        """Test qu'un corps vide lève une erreur."""
        with pytest.raises(ValueError, match="body cannot be empty"):
            PushNotification(title="Title", body="")

    def test_push_notification_to_dict(self):
        """Test sérialisation en dictionnaire."""
        notif = PushNotification(
            title="Title",
            body="Body",
            category=PushNotificationCategory.ERROR,
            priority="high",
        )
        data = notif.to_dict()

        assert data["title"] == "Title"
        assert data["body"] == "Body"
        assert data["category"] == "error"
        assert data["priority"] == "high"


class TestPushNotificationRecord:
    """Tests pour l'entité PushNotificationRecord."""

    def test_create_record(self):
        """Test création d'un enregistrement."""
        notif = PushNotification(title="Test", body="Body")
        record = PushNotificationRecord(
            notification=notif,
            device_token="test_token",
            status=PushNotificationStatus.SENT,
            message_id="msg_123",
        )

        assert record.notification == notif
        assert record.device_token == "test_token"
        assert record.status == PushNotificationStatus.SENT
        assert record.message_id == "msg_123"

    def test_record_to_dict(self):
        """Test sérialisation d'un enregistrement."""
        notif = PushNotification(title="Test", body="Body")
        record = PushNotificationRecord(
            notification=notif,
            device_token="test_token",
            status=PushNotificationStatus.FAILED,
            error_message="Token expired",
        )
        data = record.to_dict()

        assert data["device_token"] == "test_token"
        assert data["status"] == "failed"
        assert data["error_message"] == "Token expired"


# ============================================================================
# TESTS - MOCK ADAPTER
# ============================================================================

class TestMockPushAdapter:
    """Tests pour le MockPushAdapter."""

    def test_mock_adapter_properties(self):
        """Test des propriétés de base."""
        adapter = MockPushAdapter()

        assert adapter.name == "mock"
        assert adapter.is_available() is True

    def test_send_success(self):
        """Test envoi réussi."""
        adapter = MockPushAdapter()
        result = adapter.send(
            device_token="test_token",
            title="Test",
            body="Body",
        )

        assert result.success is True
        assert result.message_id is not None
        assert len(adapter.sent_notifications) == 1

    def test_send_failure_mode(self):
        """Test mode échec."""
        adapter = MockPushAdapter(should_fail=True, failure_error="Test error")
        result = adapter.send(
            device_token="test_token",
            title="Test",
            body="Body",
        )

        assert result.success is False
        assert result.error_code == "MOCK_FAILURE"
        assert result.error_message == "Test error"

    def test_send_invalid_token(self):
        """Test token invalide."""
        adapter = MockPushAdapter(invalid_tokens=["bad_token"])
        result = adapter.send(
            device_token="bad_token",
            title="Test",
            body="Body",
        )

        assert result.success is False
        assert result.error_code == "INVALID_TOKEN"

    def test_send_batch(self):
        """Test envoi batch."""
        adapter = MockPushAdapter()
        results = adapter.send_batch(
            device_tokens=["token1", "token2", "token3"],
            title="Batch Test",
            body="Body",
        )

        assert len(results) == 3
        assert all(r.success for r in results)
        assert adapter.get_notifications_count() == 3

    def test_validate_token(self):
        """Test validation de token."""
        adapter = MockPushAdapter(invalid_tokens=["invalid"])

        assert adapter.validate_token("valid_token") is True
        assert adapter.validate_token("invalid") is False
        assert adapter.validate_token("") is False

    def test_clear_notifications(self):
        """Test effacement des notifications."""
        adapter = MockPushAdapter()
        adapter.send("token", "Title", "Body")
        assert adapter.get_notifications_count() == 1

        adapter.clear()
        assert adapter.get_notifications_count() == 0

    def test_get_notifications_for_token(self):
        """Test récupération par token."""
        adapter = MockPushAdapter()
        adapter.send("token_a", "Title A", "Body A")
        adapter.send("token_b", "Title B", "Body B")
        adapter.send("token_a", "Title C", "Body C")

        notifs = adapter.get_notifications_for_token("token_a")
        assert len(notifs) == 2


# ============================================================================
# TESTS - FCM ADAPTER
# ============================================================================

class TestFCMAdapter:
    """Tests pour le FCMAdapter."""

    def test_fcm_adapter_properties(self):
        """Test des propriétés de base."""
        adapter = FCMAdapter()

        assert adapter.name == "fcm"

    def test_fcm_not_configured(self):
        """Test FCM non configuré."""
        adapter = FCMAdapter()

        # Sans configuration, devrait être non disponible
        if not adapter.is_available():
            result = adapter.send("token", "Title", "Body")
            assert result.success is False
            assert result.error_code == "NOT_CONFIGURED"

    def test_validate_token_format(self):
        """Test validation format token FCM."""
        adapter = FCMAdapter()

        # Token valide (long, alphanumerique)
        valid_token = "c" * 150
        assert adapter.validate_token(valid_token) is True

        # Token trop court
        assert adapter.validate_token("short") is False

        # Token vide
        assert adapter.validate_token("") is False


# ============================================================================
# TESTS - EXPO ADAPTER
# ============================================================================

class TestExpoAdapter:
    """Tests pour le ExpoAdapter."""

    def test_expo_adapter_properties(self):
        """Test des propriétés de base."""
        adapter = ExpoAdapter()

        assert adapter.name == "expo"
        assert adapter.is_available() is True  # Toujours disponible

    def test_validate_expo_token(self):
        """Test validation format token Expo."""
        adapter = ExpoAdapter()

        # Format ExponentPushToken[xxx]
        assert adapter.validate_token("ExponentPushToken[abc123]") is True
        assert adapter.validate_token("ExponentPushToken[]") is False
        assert adapter.validate_token("InvalidToken") is False
        assert adapter.validate_token("") is False

    @patch("requests.post")
    def test_send_success(self, mock_post):
        """Test envoi réussi via Expo."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "data": {"status": "ok", "id": "receipt_123"}
        }
        mock_post.return_value = mock_response

        adapter = ExpoAdapter()
        result = adapter.send(
            device_token="ExponentPushToken[test123]",
            title="Test",
            body="Body",
        )

        assert result.success is True
        assert result.message_id == "receipt_123"

    @patch("requests.post")
    def test_send_failure(self, mock_post):
        """Test échec via Expo."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "data": {
                "status": "error",
                "message": "Device not registered",
                "details": {"error": "DeviceNotRegistered"},
            }
        }
        mock_post.return_value = mock_response

        adapter = ExpoAdapter()
        result = adapter.send(
            device_token="ExponentPushToken[test123]",
            title="Test",
            body="Body",
        )

        assert result.success is False
        assert result.error_code == "DeviceNotRegistered"


# ============================================================================
# TESTS - USE CASE
# ============================================================================

class TestSendPushNotificationUseCase:
    """Tests pour le use case SendPushNotificationUseCase."""

    @pytest.fixture
    def mock_adapter(self):
        """Fixture adapter mock."""
        return MockPushAdapter()

    @pytest.fixture
    def use_case(self, mock_adapter):
        """Fixture use case avec mock adapter."""
        return SendPushNotificationUseCase(notification_adapter=mock_adapter)

    def test_execute_single(self, use_case, mock_adapter):
        """Test envoi simple."""
        result = use_case.execute(
            device_token="token_123",
            title="Test",
            body="Body",
            category=PushNotificationCategory.INFO,
        )

        assert result.success is True
        assert mock_adapter.get_notifications_count() == 1

    def test_execute_batch(self, use_case, mock_adapter):
        """Test envoi batch."""
        results = use_case.execute_batch(
            device_tokens=["t1", "t2", "t3"],
            title="Batch",
            body="Body",
        )

        assert len(results) == 3
        assert all(r.success for r in results)

    def test_notify_draft_created(self, use_case, mock_adapter):
        """Test notification brouillon créé."""
        results = use_case.notify_draft_created(
            device_tokens=["token1"],
            recipient="john@example.com",
            subject="Meeting tomorrow",
            draft_id="draft_123",
            priority_score=85,
        )

        assert len(results) == 1
        assert results[0].success is True

        # Vérifier les données
        notif = mock_adapter.sent_notifications[0]
        assert notif.data["type"] == "draft_created"
        assert notif.data["recipient"] == "john@example.com"

    def test_notify_followup_sent(self, use_case, mock_adapter):
        """Test notification relance envoyée."""
        results = use_case.notify_followup_sent(
            device_tokens=["token1"],
            recipient="jane@example.com",
            days_since=5,
        )

        assert len(results) == 1
        notif = mock_adapter.sent_notifications[0]
        assert notif.data["type"] == "followup_sent"
        assert notif.data["days_since"] == 5

    def test_notify_error(self, use_case, mock_adapter):
        """Test notification erreur."""
        results = use_case.notify_error(
            device_tokens=["token1"],
            error_message="Connection failed",
            context={"component": "gmail"},
        )

        assert len(results) == 1
        notif = mock_adapter.sent_notifications[0]
        assert notif.data["type"] == "error"

    def test_notify_budget_warning(self, use_case, mock_adapter):
        """Test notification alerte budget."""
        results = use_case.notify_budget_warning(
            device_tokens=["token1"],
            current_spend=45.0,
            budget_limit=50.0,
        )

        assert len(results) == 1
        notif = mock_adapter.sent_notifications[0]
        assert notif.data["type"] == "budget_warning"
        assert notif.data["percent_used"] == 90.0

    def test_get_stats(self, use_case):
        """Test statistiques."""
        use_case.execute("t1", "Title 1", "Body", category=PushNotificationCategory.INFO)
        use_case.execute("t2", "Title 2", "Body", category=PushNotificationCategory.ERROR)

        stats = use_case.get_stats()

        assert stats["total"] == 2
        assert stats["sent"] == 2
        assert stats["failed"] == 0
        assert stats["success_rate"] == 100.0

    def test_get_records(self, use_case):
        """Test récupération historique."""
        use_case.execute("t1", "Title 1", "Body")
        use_case.execute("t2", "Title 2", "Body")

        records = use_case.get_records(limit=10)

        assert len(records) == 2


# ============================================================================
# TESTS - API ROUTES
# ============================================================================

class TestPushNotificationsAPI:
    """Tests pour l'API REST des push notifications."""

    @pytest.fixture
    def client(self):
        """Fixture client de test Flask."""
        pytest.importorskip("flask_cors", reason="flask_cors required for API tests")
        from app.api.app import create_app

        app = create_app({"TESTING": True})
        with app.test_client() as client:
            yield client

    @pytest.fixture
    def temp_devices_file(self, tmp_path):
        """Fixture fichier temporaire pour les devices."""
        devices_file = tmp_path / "push_devices.json"
        devices_file.write_text(json.dumps({"devices": []}))
        return devices_file

    def test_list_devices_empty(self, client):
        """Test liste devices vide."""
        with patch("app.api.push_notifications._get_device_store") as mock_store:
            mock_store.return_value.get_all.return_value = []

            response = client.get("/push/devices")
            assert response.status_code == 200

            data = response.get_json()
            assert data["count"] == 0

    def test_register_device(self, client):
        """Test enregistrement d'un device."""
        with patch("app.api.push_notifications._get_device_store") as mock_store:
            mock_device = DeviceToken(
                token="test_token_123",
                platform=DevicePlatform.IOS,
            )
            mock_store.return_value.register.return_value = mock_device

            response = client.post(
                "/push/devices",
                json={
                    "token": "test_token_123",
                    "platform": "ios",
                    "device_name": "Test iPhone",
                },
            )

            assert response.status_code == 201
            data = response.get_json()
            assert data["success"] is True

    def test_register_device_missing_token(self, client):
        """Test enregistrement sans token."""
        response = client.post(
            "/push/devices",
            json={"platform": "ios"},
        )

        assert response.status_code == 400
        data = response.get_json()
        assert "token is required" in data["error"]

    def test_register_device_invalid_platform(self, client):
        """Test enregistrement avec plateforme invalide."""
        response = client.post(
            "/push/devices",
            json={"token": "test", "platform": "windows"},
        )

        assert response.status_code == 400

    def test_send_notification(self, client):
        """Test envoi notification."""
        with patch("app.api.push_notifications._get_push_notification_service") as mock_service:
            mock_result = PushNotificationResult(
                success=True,
                message_id="msg_123",
            )
            mock_service.return_value.send_to_token.return_value = mock_result

            response = client.post(
                "/push/send",
                json={
                    "token": "test_token",
                    "title": "Test",
                    "body": "Test body",
                },
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data["success"] is True
            assert data["message_id"] == "msg_123"

    def test_send_notification_batch(self, client):
        """Test envoi batch."""
        with patch("app.api.push_notifications._get_push_notification_service") as mock_service:
            mock_results = [
                PushNotificationResult(success=True, message_id="msg_1"),
                PushNotificationResult(success=True, message_id="msg_2"),
                PushNotificationResult(success=False, error_message="Failed"),
            ]
            mock_service.return_value.send_to_tokens.return_value = mock_results

            response = client.post(
                "/push/send",
                json={
                    "tokens": ["t1", "t2", "t3"],
                    "title": "Batch",
                    "body": "Body",
                },
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data["total"] == 3
            assert data["success"] == 2
            assert data["failed"] == 1

    def test_broadcast(self, client, monkeypatch):
        """Test broadcast à tous les devices.

        C-3 (issue #523, 2026-05-05): /push/broadcast est désormais admin-only
        — on stub _decode_jwt + _is_admin et on envoie un Bearer dummy."""
        fake_payload = {"sub": "1", "email": "admin@test.com"}
        monkeypatch.setattr("app.api.auth._decode_jwt", lambda token: fake_payload)
        monkeypatch.setattr("app.api.admin._is_admin", lambda email: True)

        with patch("app.api.push_notifications._get_push_notification_service") as mock_service:
            mock_results = [
                PushNotificationResult(success=True),
                PushNotificationResult(success=True),
            ]
            mock_service.return_value.broadcast.return_value = mock_results

            response = client.post(
                "/push/broadcast",
                json={
                    "title": "Broadcast",
                    "body": "Message to all",
                },
                headers={"Authorization": "Bearer admin-stub"},
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data["total_devices"] == 2
            assert data["success"] == 2

    def test_push_stats(self, client, monkeypatch):
        """Test statistiques.

        Audit 2026-05-29: /push/stats is now admin-only (was leaking the whole
        device inventory + global notification volume to any caller). Mirrors
        the /push/broadcast admin gate (C-3)."""
        fake_payload = {"sub": "1", "email": "admin@test.com"}
        monkeypatch.setattr("app.api.auth._decode_jwt", lambda token: fake_payload)

        # Non-admin caller is rejected.
        monkeypatch.setattr("app.api.admin._is_admin", lambda email: False)
        denied = client.get("/push/stats", headers={"Authorization": "Bearer user"})
        assert denied.status_code == 403

        # Admin caller gets the stats.
        monkeypatch.setattr("app.api.admin._is_admin", lambda email: True)
        with patch("app.api.push_notifications._get_push_notification_service") as mock_service:
            with patch("app.api.push_notifications._get_device_store") as mock_store:
                with patch("app.api.push_notifications._get_push_adapter") as mock_adapter:
                    mock_service.return_value.get_stats.return_value = {
                        "total": 10,
                        "sent": 8,
                        "failed": 2,
                    }
                    mock_store.return_value.get_all.return_value = []
                    mock_adapter.return_value.name = "mock"

                    response = client.get(
                        "/push/stats", headers={"Authorization": "Bearer admin"}
                    )

                    assert response.status_code == 200
                    data = response.get_json()
                    assert data["notifications"]["total"] == 10

    def test_push_history(self, client, monkeypatch):
        """Test historique.

        Audit 2026-05-29: /push/history is now admin-only (was leaking every
        tenant's notification titles + bodies to any caller)."""
        fake_payload = {"sub": "1", "email": "admin@test.com"}
        monkeypatch.setattr("app.api.auth._decode_jwt", lambda token: fake_payload)

        # Non-admin caller is rejected.
        monkeypatch.setattr("app.api.admin._is_admin", lambda email: False)
        denied = client.get("/push/history", headers={"Authorization": "Bearer user"})
        assert denied.status_code == 403

        # Admin caller gets the history.
        monkeypatch.setattr("app.api.admin._is_admin", lambda email: True)
        with patch("app.api.push_notifications._get_push_notification_service") as mock_service:
            mock_service.return_value.get_records.return_value = []

            response = client.get(
                "/push/history", headers={"Authorization": "Bearer admin"}
            )

            assert response.status_code == 200
            data = response.get_json()
            assert "history" in data


# ============================================================================
# TESTS - DEVICE TOKEN STORE (JsonFileDeviceStore)
# ============================================================================

class TestDeviceTokenStore:
    """Tests pour le JsonFileDeviceStore (infrastructure)."""

    @pytest.fixture
    def temp_store(self, tmp_path):
        """Fixture store temporaire."""
        from app.infrastructure.device_store import JsonFileDeviceStore

        filepath = tmp_path / "devices.json"
        return JsonFileDeviceStore(filepath=filepath)

    def test_register_device(self, temp_store):
        """Test enregistrement."""
        device = temp_store.register(
            token="test_token",
            platform="ios",
            user_id="user_1",
        )

        assert device.token == "test_token"
        assert device.platform == DevicePlatform.IOS
        assert device.user_id == "user_1"

    def test_get_device(self, temp_store):
        """Test récupération."""
        temp_store.register("test_token", "android")

        device = temp_store.get("test_token")
        assert device is not None
        assert device.platform == DevicePlatform.ANDROID

    def test_unregister_device(self, temp_store):
        """Test désinscription."""
        temp_store.register("test_token", "ios")

        result = temp_store.unregister("test_token")
        assert result is True

        device = temp_store.get("test_token")
        assert device is None

    def test_get_all_devices(self, temp_store):
        """Test liste tous les devices."""
        temp_store.register("t1", "ios", user_id="u1")
        temp_store.register("t2", "android", user_id="u2")
        temp_store.register("t3", "ios", user_id="u1")

        all_devices = temp_store.get_all()
        assert len(all_devices) == 3

        user_devices = temp_store.get_all(user_id="u1")
        assert len(user_devices) == 2

    def test_get_tokens(self, temp_store):
        """Test récupération tokens uniquement."""
        temp_store.register("t1", "ios")
        temp_store.register("t2", "android")

        tokens = temp_store.get_tokens()
        assert set(tokens) == {"t1", "t2"}

    def test_deactivate_device(self, temp_store):
        """Test désactivation."""
        temp_store.register("test_token", "ios")

        result = temp_store.deactivate("test_token")
        assert result is True

        # Le device existe mais n'apparaît plus dans get_all
        device = temp_store.get("test_token")
        assert device is not None
        assert device.is_active is False

        active_devices = temp_store.get_all()
        assert len(active_devices) == 0

    def test_persistence(self, tmp_path):
        """Test persistance entre instances."""
        from app.infrastructure.device_store import JsonFileDeviceStore

        filepath = tmp_path / "devices.json"

        # Première instance
        store1 = JsonFileDeviceStore(filepath=filepath)
        store1.register("token_1", "ios")
        store1.register("token_2", "android")

        # Deuxième instance (recharge depuis le fichier)
        store2 = JsonFileDeviceStore(filepath=filepath)
        devices = store2.get_all()

        assert len(devices) == 2


# ============================================================================
# TESTS - PUSH NOTIFICATION SERVICE
# ============================================================================

class TestPushNotificationService:
    """Tests pour le PushNotificationService."""

    @pytest.fixture
    def temp_store(self, tmp_path):
        """Fixture store temporaire."""
        from app.infrastructure.device_store import JsonFileDeviceStore
        return JsonFileDeviceStore(filepath=tmp_path / "devices.json")

    @pytest.fixture
    def mock_adapter(self):
        """Fixture mock adapter."""
        return MockPushAdapter()

    @pytest.fixture
    def service(self, temp_store, mock_adapter):
        """Fixture service avec mock adapter."""
        from app.application import PushNotificationService
        return PushNotificationService(
            device_store=temp_store,
            notification_adapter=mock_adapter,
        )

    def test_notify_all_draft_created(self, service, temp_store, mock_adapter):
        """Test notification brouillon à tous les devices."""
        temp_store.register("token1", "ios")
        temp_store.register("token2", "android")

        count = service.notify_all_draft_created(
            recipient="john@example.com",
            subject="Meeting tomorrow",
            draft_id="draft_123",
            priority_score=85,
        )

        assert count == 2
        assert mock_adapter.get_notifications_count() == 2

    def test_notify_all_followup_sent(self, service, temp_store, mock_adapter):
        """Test notification relance à tous les devices."""
        temp_store.register("token1", "ios")

        count = service.notify_all_followup_sent(
            recipient="jane@example.com",
            days_since=5,
        )

        assert count == 1

    def test_notify_all_error(self, service, temp_store, mock_adapter):
        """Test notification erreur à tous les devices."""
        temp_store.register("token1", "ios")

        count = service.notify_all_error(
            error_message="Connection failed",
            context={"component": "gmail"},
        )

        assert count == 1

    def test_broadcast(self, service, temp_store, mock_adapter):
        """Test broadcast."""
        temp_store.register("token1", "ios")
        temp_store.register("token2", "android")

        results = service.broadcast(
            title="Broadcast",
            body="Message to all",
        )

        assert len(results) == 2
        assert all(r.success for r in results)

    def test_no_devices(self, service, mock_adapter):
        """Test avec aucun device."""
        count = service.notify_all_draft_created(
            recipient="john@example.com",
            subject="Test",
            draft_id="123",
        )

        assert count == 0
        assert mock_adapter.get_notifications_count() == 0


# ============================================================================
# TESTS - INTÉGRATION NOTIFICATION MANAGER
# ============================================================================

class TestNotificationManagerIntegration:
    """Tests d'intégration avec le NotificationManager existant."""

    def test_draft_created_with_push(self):
        """Test notification brouillon avec push."""
        from app.infrastructure.notifications import NotificationManager, NotificationConfig

        config = NotificationConfig(
            enabled=False,  # Désactiver desktop pour le test
            push_enabled=True,
        )
        manager = NotificationManager(config=config)

        with patch.object(manager, "_send_push_draft_created") as mock_push:
            manager.draft_created(
                recipient="john@example.com",
                subject="Test subject",
                priority=85,
                draft_id="draft_123",
            )

            mock_push.assert_called_once_with(
                "john@example.com",
                "Test subject",
                "draft_123",
                85,
            )

    def test_followup_created_with_push(self):
        """Test notification relance avec push."""
        from app.infrastructure.notifications import NotificationManager, NotificationConfig

        config = NotificationConfig(enabled=False, push_enabled=True)
        manager = NotificationManager(config=config)

        with patch.object(manager, "_send_push_followup") as mock_push:
            manager.followup_created(
                recipient="jane@example.com",
                days=5,
            )

            mock_push.assert_called_once_with("jane@example.com", 5)

    def test_error_with_push(self):
        """Test notification erreur avec push."""
        from app.infrastructure.notifications import NotificationManager, NotificationConfig

        config = NotificationConfig(enabled=False, push_enabled=True)
        manager = NotificationManager(config=config)

        with patch.object(manager, "_send_push_error") as mock_push:
            manager.error("Test error", context={"component": "gmail"})

            mock_push.assert_called_once_with("Test error", {"component": "gmail"})

    def test_push_disabled(self):
        """Test push désactivé."""
        from app.infrastructure.notifications import NotificationManager, NotificationConfig

        config = NotificationConfig(enabled=False, push_enabled=False)
        manager = NotificationManager(config=config)

        with patch.object(manager, "_send_push_draft_created") as mock_push:
            manager.draft_created(
                recipient="john@example.com",
                subject="Test",
                draft_id="123",
            )

            mock_push.assert_not_called()
