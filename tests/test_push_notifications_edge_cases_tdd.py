# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests TDD pour les edge cases des notifications push.

Ces tests couvrent les cas limites non testés :
- Valeurs null/vides
- Formats invalides de tokens
- Scénarios d'erreur réseau
- Limites des valeurs

Approche TDD : Tests écrits d'abord, code corrigé si nécessaire.
"""

import pytest
from unittest.mock import Mock, patch

from app.domain.entities.push_notification import (
    DeviceToken,
    DevicePlatform,
    PushNotification,
    PushNotificationCategory,
    PushNotificationStatus,
    PushNotificationRecord,
)
from app.domain.ports.notification_port import PushNotificationResult


# ============================================================================
# TESTS - DeviceToken - Edge Cases
# ============================================================================

class TestDeviceTokenEdgeCases:
    """Tests edge cases pour DeviceToken."""

    def test_device_token_with_none_raises(self):
        """Test qu'un token None lève une erreur."""
        with pytest.raises(ValueError, match="cannot be empty"):
            DeviceToken(token=None, platform=DevicePlatform.IOS)

    def test_device_token_with_whitespace_only_raises(self):
        """Test qu'un token avec espaces seulement lève une erreur."""
        with pytest.raises(ValueError, match="cannot be empty"):
            DeviceToken(token="   ", platform=DevicePlatform.IOS)

    def test_device_token_with_empty_string_raises(self):
        """Test qu'un token vide lève une erreur."""
        with pytest.raises(ValueError, match="cannot be empty"):
            DeviceToken(token="", platform=DevicePlatform.IOS)

    def test_device_token_with_string_platform(self):
        """Test création avec platform en string."""
        device = DeviceToken(token="test_token", platform="android")
        assert device.platform == DevicePlatform.ANDROID

    def test_device_token_with_invalid_platform_raises(self):
        """Test qu'une platform invalide lève une erreur."""
        with pytest.raises(ValueError):
            DeviceToken(token="test_token", platform="windows")

    def test_device_token_with_uppercase_platform(self):
        """Test que la platform en majuscules est rejetée."""
        with pytest.raises(ValueError):
            DeviceToken(token="test_token", platform="IOS")

    def test_device_token_to_dict_with_none_values(self):
        """Test to_dict avec valeurs None."""
        device = DeviceToken(token="test_token", platform=DevicePlatform.WEB)
        data = device.to_dict()

        assert data["user_id"] is None
        assert data["device_name"] is None
        assert data["app_version"] is None
        assert data["last_used_at"] is None

    def test_device_token_from_dict_minimal(self):
        """Test from_dict avec données minimales."""
        data = {"token": "test_token", "platform": "ios"}
        device = DeviceToken.from_dict(data)

        assert device.token == "test_token"
        assert device.platform == DevicePlatform.IOS
        assert device.is_active is True

    def test_device_token_from_dict_missing_token_raises(self):
        """Test from_dict sans token lève une erreur."""
        data = {"platform": "ios"}
        with pytest.raises(KeyError):
            DeviceToken.from_dict(data)

    def test_device_token_from_dict_missing_platform_raises(self):
        """Test from_dict sans platform lève une erreur."""
        data = {"token": "test_token"}
        with pytest.raises(KeyError):
            DeviceToken.from_dict(data)

    def test_device_token_from_dict_with_invalid_date(self):
        """Test from_dict avec date invalide."""
        data = {
            "token": "test_token",
            "platform": "ios",
            "created_at": "not-a-date",
        }
        with pytest.raises(ValueError):
            DeviceToken.from_dict(data)

    def test_device_token_from_dict_with_empty_date_string(self):
        """Test from_dict avec date vide."""
        data = {
            "token": "test_token",
            "platform": "ios",
            "created_at": "",
        }
        # Une chaîne vide dans fromisoformat lève ValueError
        # Mais le code utilise `if data.get("created_at")` qui retourne False pour ""
        # Donc datetime.now() est utilisé à la place
        device = DeviceToken.from_dict(data)
        assert device.created_at is not None

    def test_device_token_with_very_long_token(self):
        """Test avec un token très long (FCM tokens peuvent être longs)."""
        long_token = "a" * 500
        device = DeviceToken(token=long_token, platform=DevicePlatform.ANDROID)
        assert len(device.token) == 500

    def test_device_token_with_special_characters(self):
        """Test avec caractères spéciaux dans le token."""
        special_token = "abc123-_:="
        device = DeviceToken(token=special_token, platform=DevicePlatform.IOS)
        assert device.token == special_token


# ============================================================================
# TESTS - PushNotification - Edge Cases
# ============================================================================

class TestPushNotificationEdgeCases:
    """Tests edge cases pour PushNotification."""

    def test_notification_with_none_title_raises(self):
        """Test qu'un title None lève une erreur."""
        with pytest.raises(ValueError, match="title cannot be empty"):
            PushNotification(title=None, body="Body")

    def test_notification_with_none_body_raises(self):
        """Test qu'un body None lève une erreur."""
        with pytest.raises(ValueError, match="body cannot be empty"):
            PushNotification(title="Title", body=None)

    def test_notification_with_whitespace_title_raises(self):
        """Test qu'un title avec espaces seulement lève une erreur."""
        with pytest.raises(ValueError, match="title cannot be empty"):
            PushNotification(title="   ", body="Body")

    def test_notification_with_whitespace_body_raises(self):
        """Test qu'un body avec espaces seulement lève une erreur."""
        with pytest.raises(ValueError, match="body cannot be empty"):
            PushNotification(title="Title", body="   ")

    def test_notification_with_string_category(self):
        """Test création avec category en string."""
        notif = PushNotification(
            title="Title",
            body="Body",
            category="error",
        )
        assert notif.category == PushNotificationCategory.ERROR

    def test_notification_with_invalid_category_raises(self):
        """Test qu'une category invalide lève une erreur."""
        with pytest.raises(ValueError):
            PushNotification(
                title="Title",
                body="Body",
                category="invalid_category",
            )

    def test_notification_with_none_data(self):
        """Test création avec data None."""
        notif = PushNotification(title="Title", body="Body", data=None)
        data = notif.to_dict()
        assert data["data"] == {}

    def test_notification_with_empty_data(self):
        """Test création avec data vide."""
        notif = PushNotification(title="Title", body="Body", data={})
        assert notif.data == {}

    def test_notification_with_nested_data(self):
        """Test création avec data imbriquées."""
        nested = {"level1": {"level2": {"key": "value"}}}
        notif = PushNotification(title="Title", body="Body", data=nested)
        assert notif.data["level1"]["level2"]["key"] == "value"

    def test_notification_to_dict_includes_all_fields(self):
        """Test que to_dict inclut tous les champs."""
        notif = PushNotification(
            title="Title",
            body="Body",
            category=PushNotificationCategory.DRAFT_CREATED,
            badge=5,
            sound=False,
            priority="high",
            ttl=3600,
            collapse_key="group_1",
            image_url="https://example.com/image.png",
        )
        data = notif.to_dict()

        assert data["title"] == "Title"
        assert data["body"] == "Body"
        assert data["category"] == "draft.created"
        assert data["badge"] == 5
        assert data["sound"] is False
        assert data["priority"] == "high"
        assert data["ttl"] == 3600
        assert data["collapse_key"] == "group_1"
        assert data["image_url"] == "https://example.com/image.png"

    def test_notification_default_values(self):
        """Test les valeurs par défaut."""
        notif = PushNotification(title="Title", body="Body")

        assert notif.category == PushNotificationCategory.INFO
        assert notif.badge is None
        assert notif.sound is True
        assert notif.priority == "normal"
        assert notif.ttl == 86400
        assert notif.collapse_key is None
        assert notif.image_url is None

    def test_notification_with_very_long_title(self):
        """Test avec un titre très long."""
        long_title = "T" * 1000
        notif = PushNotification(title=long_title, body="Body")
        assert len(notif.title) == 1000

    def test_notification_with_unicode_characters(self):
        """Test avec caractères Unicode."""
        notif = PushNotification(
            title="🔔 Notification",
            body="Message avec émojis 🎉 et caractères: àéïöü",
        )
        assert "🔔" in notif.title
        assert "🎉" in notif.body

    def test_notification_with_invalid_priority_allowed(self):
        """Test qu'une priorité invalide est acceptée (pas de validation)."""
        notif = PushNotification(
            title="Title",
            body="Body",
            priority="ultra_high",
        )
        # Pas de validation sur priority actuellement
        assert notif.priority == "ultra_high"


# ============================================================================
# TESTS - PushNotificationRecord - Edge Cases
# ============================================================================

class TestPushNotificationRecordEdgeCases:
    """Tests edge cases pour PushNotificationRecord."""

    def test_record_with_all_statuses(self):
        """Test création avec tous les statuts."""
        notif = PushNotification(title="Test", body="Body")

        for status in PushNotificationStatus:
            record = PushNotificationRecord(
                notification=notif,
                device_token="token",
                status=status,
            )
            assert record.status == status

    def test_record_with_error_message(self):
        """Test création avec message d'erreur."""
        notif = PushNotification(title="Test", body="Body")
        record = PushNotificationRecord(
            notification=notif,
            device_token="token",
            status=PushNotificationStatus.FAILED,
            error_message="Token expired",
        )

        assert record.status == PushNotificationStatus.FAILED
        assert record.error_message == "Token expired"

    def test_record_to_dict_complete(self):
        """Test to_dict avec tous les champs."""
        notif = PushNotification(title="Test", body="Body")
        record = PushNotificationRecord(
            notification=notif,
            device_token="test_token",
            status=PushNotificationStatus.SENT,
            message_id="msg_123",
            error_message=None,
        )
        data = record.to_dict()

        assert data["device_token"] == "test_token"
        assert data["status"] == "sent"
        assert data["message_id"] == "msg_123"
        assert data["error_message"] is None
        assert "notification" in data
        assert "sent_at" in data


# ============================================================================
# TESTS - DevicePlatform - Edge Cases
# ============================================================================

class TestDevicePlatformEdgeCases:
    """Tests edge cases pour DevicePlatform enum."""

    def test_all_platforms_have_lowercase_values(self):
        """Test que tous les values sont en lowercase."""
        for platform in DevicePlatform:
            assert platform.value == platform.value.lower()

    def test_platform_values(self):
        """Test les valeurs de l'enum."""
        assert DevicePlatform.IOS.value == "ios"
        assert DevicePlatform.ANDROID.value == "android"
        assert DevicePlatform.WEB.value == "web"


# ============================================================================
# TESTS - PushNotificationStatus - Edge Cases
# ============================================================================

class TestPushNotificationStatusEdgeCases:
    """Tests edge cases pour PushNotificationStatus enum."""

    def test_all_statuses(self):
        """Test tous les statuts."""
        expected = {"pending", "sent", "delivered", "failed"}
        actual = {s.value for s in PushNotificationStatus}
        assert expected == actual


# ============================================================================
# TESTS - PushNotificationCategory - Edge Cases
# ============================================================================

class TestPushNotificationCategoryEdgeCases:
    """Tests edge cases pour PushNotificationCategory enum."""

    def test_all_categories(self):
        """Test toutes les catégories."""
        expected = {
            "draft.created", "draft.failed", "followup.sent",
            "health.alert", "budget.warning", "error", "info"
        }
        actual = {c.value for c in PushNotificationCategory}
        assert expected == actual


# ============================================================================
# TESTS - PushNotificationResult - Edge Cases
# ============================================================================

class TestPushNotificationResultEdgeCases:
    """Tests edge cases pour PushNotificationResult."""

    def test_result_success(self):
        """Test résultat succès."""
        result = PushNotificationResult(
            success=True,
            message_id="msg_123",
        )
        assert result.success is True
        assert result.message_id == "msg_123"
        assert result.error_code is None
        assert result.error_message is None

    def test_result_failure_with_error_details(self):
        """Test résultat échec avec détails d'erreur."""
        result = PushNotificationResult(
            success=False,
            error_code="INVALID_TOKEN",
            error_message="The token has expired",
        )
        assert result.success is False
        assert result.error_code == "INVALID_TOKEN"
        assert result.error_message == "The token has expired"

    def test_result_failure_without_error_details(self):
        """Test résultat échec sans détails d'erreur."""
        result = PushNotificationResult(success=False)
        assert result.success is False
        assert result.error_code is None
        assert result.error_message is None


# ============================================================================
# TESTS - MockPushAdapter - Edge Cases
# ============================================================================

class TestMockPushAdapterEdgeCases:
    """Tests edge cases pour MockPushAdapter."""

    def test_mock_adapter_basic_send(self):
        """Test mock adapter envoi basique."""
        from app.adapters.push.mock_adapter import MockPushAdapter

        adapter = MockPushAdapter()
        result = adapter.send("token", "Title", "Body")

        assert result.success is True
        assert adapter.get_notifications_count() == 1

    def test_mock_adapter_clear_resets_all(self):
        """Test que clear() réinitialise tout."""
        from app.adapters.push.mock_adapter import MockPushAdapter

        adapter = MockPushAdapter()
        adapter.send("t1", "Title", "Body")
        adapter.send("t2", "Title", "Body")

        assert adapter.get_notifications_count() == 2

        adapter.clear()

        assert adapter.get_notifications_count() == 0
        assert adapter.sent_notifications == []

    def test_mock_adapter_send_batch_with_partial_failures(self):
        """Test batch avec échecs partiels."""
        from app.adapters.push.mock_adapter import MockPushAdapter

        adapter = MockPushAdapter(invalid_tokens=["bad_token"])
        results = adapter.send_batch(
            device_tokens=["good_token", "bad_token", "another_good"],
            title="Test",
            body="Body",
        )

        assert len(results) == 3
        assert results[0].success is True
        assert results[1].success is False
        assert results[2].success is True

    def test_mock_adapter_validate_empty_token(self):
        """Test validation token vide."""
        from app.adapters.push.mock_adapter import MockPushAdapter

        adapter = MockPushAdapter()
        assert adapter.validate_token("") is False
        # Le MockPushAdapter ne valide pas les espaces, juste les chaînes vides et les tokens invalides
        # Les tokens avec espaces sont techniquement "valides" pour le mock
        assert adapter.validate_token("valid_token") is True


# ============================================================================
# TESTS - FCMAdapter - Edge Cases
# ============================================================================

class TestFCMAdapterEdgeCases:
    """Tests edge cases pour FCMAdapter."""

    def test_fcm_adapter_validate_short_token(self):
        """Test validation token trop court."""
        from app.adapters.push.fcm_adapter import FCMAdapter

        adapter = FCMAdapter()
        # FCM tokens font généralement > 100 caractères
        assert adapter.validate_token("short") is False
        assert adapter.validate_token("a" * 50) is False

    def test_fcm_adapter_validate_long_token(self):
        """Test validation token de longueur correcte."""
        from app.adapters.push.fcm_adapter import FCMAdapter

        adapter = FCMAdapter()
        long_token = "a" * 150
        assert adapter.validate_token(long_token) is True

    def test_fcm_adapter_not_configured(self):
        """Test FCM non configuré."""
        from app.adapters.push.fcm_adapter import FCMAdapter

        adapter = FCMAdapter()
        # Sans credentials, devrait être non disponible
        if not adapter.is_available():
            result = adapter.send("token", "Title", "Body")
            assert result.success is False


# ============================================================================
# TESTS - ExpoAdapter - Edge Cases
# ============================================================================

class TestExpoAdapterEdgeCases:
    """Tests edge cases pour ExpoAdapter."""

    def test_expo_adapter_validate_invalid_format(self):
        """Test validation format invalide."""
        from app.adapters.push.expo_adapter import ExpoAdapter

        adapter = ExpoAdapter()
        assert adapter.validate_token("InvalidFormat") is False
        assert adapter.validate_token("ExponentPushToken") is False
        assert adapter.validate_token("ExponentPushToken[") is False

    def test_expo_adapter_validate_empty_brackets(self):
        """Test validation crochets vides."""
        from app.adapters.push.expo_adapter import ExpoAdapter

        adapter = ExpoAdapter()
        assert adapter.validate_token("ExponentPushToken[]") is False

    def test_expo_adapter_validate_valid_format(self):
        """Test validation format valide."""
        from app.adapters.push.expo_adapter import ExpoAdapter

        adapter = ExpoAdapter()
        assert adapter.validate_token("ExponentPushToken[abc123]") is True
        assert adapter.validate_token("ExponentPushToken[a-b_c.d]") is True

    @patch("requests.post")
    def test_expo_adapter_network_error(self, mock_post):
        """Test erreur réseau."""
        from app.adapters.push.expo_adapter import ExpoAdapter
        import requests

        mock_post.side_effect = requests.exceptions.ConnectionError("Network error")

        adapter = ExpoAdapter()
        result = adapter.send(
            device_token="ExponentPushToken[test123]",
            title="Test",
            body="Body",
        )

        assert result.success is False

    @patch("requests.post")
    def test_expo_adapter_timeout(self, mock_post):
        """Test timeout."""
        from app.adapters.push.expo_adapter import ExpoAdapter
        import requests

        mock_post.side_effect = requests.exceptions.Timeout("Request timed out")

        adapter = ExpoAdapter()
        result = adapter.send(
            device_token="ExponentPushToken[test123]",
            title="Test",
            body="Body",
        )

        assert result.success is False

    @patch("requests.post")
    def test_expo_adapter_invalid_json_response(self, mock_post):
        """Test réponse JSON invalide."""
        from app.adapters.push.expo_adapter import ExpoAdapter

        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_post.return_value = mock_response

        adapter = ExpoAdapter()
        result = adapter.send(
            device_token="ExponentPushToken[test123]",
            title="Test",
            body="Body",
        )

        assert result.success is False

    @patch("requests.post")
    def test_expo_adapter_http_error(self, mock_post):
        """Test erreur HTTP (5xx)."""
        from app.adapters.push.expo_adapter import ExpoAdapter

        mock_response = Mock()
        mock_response.ok = False
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_post.return_value = mock_response

        adapter = ExpoAdapter()
        result = adapter.send(
            device_token="ExponentPushToken[test123]",
            title="Test",
            body="Body",
        )

        assert result.success is False
