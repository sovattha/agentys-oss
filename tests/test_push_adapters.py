# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour les adapters push (Expo, FCM, Mock).

pytest tests/test_push_adapters.py -v
"""

from unittest.mock import patch, MagicMock, mock_open
import json
import os

from app.adapters.push.expo_adapter import ExpoAdapter, ExpoConfig
from app.adapters.push.fcm_adapter import FCMAdapter, FCMConfig
from app.adapters.push.mock_adapter import MockPushAdapter, MockNotificationRecord
from app.domain.ports.notification_port import (
    NotificationPort,
    NotificationPriority,
    PushNotificationResult,
)


# =============================================================================
# ExpoConfig Tests
# =============================================================================


class TestExpoConfig:
    """Tests pour ExpoConfig."""

    def test_config_default_values(self):
        """ExpoConfig a des valeurs par défaut None."""
        config = ExpoConfig()
        assert config.access_token is None

    def test_config_with_access_token(self):
        """ExpoConfig accepte un access_token."""
        config = ExpoConfig(access_token="test_token")
        assert config.access_token == "test_token"

    def test_config_from_env_with_token(self):
        """ExpoConfig.from_env charge le token depuis l'environnement."""
        with patch.dict(os.environ, {"EXPO_ACCESS_TOKEN": "env_token"}):
            config = ExpoConfig.from_env()
            assert config.access_token == "env_token"

    def test_config_from_env_without_token(self):
        """ExpoConfig.from_env retourne None si pas de token."""
        with patch.dict(os.environ, {}, clear=True):
            # S'assurer que la variable n'existe pas
            os.environ.pop("EXPO_ACCESS_TOKEN", None)
            config = ExpoConfig.from_env()
            assert config.access_token is None


# =============================================================================
# ExpoAdapter Tests
# =============================================================================


class TestExpoAdapter:
    """Tests pour ExpoAdapter."""

    def test_adapter_implements_notification_port(self):
        """ExpoAdapter implémente NotificationPort."""
        adapter = ExpoAdapter()
        assert isinstance(adapter, NotificationPort)

    def test_adapter_name(self):
        """ExpoAdapter a le nom 'expo'."""
        adapter = ExpoAdapter()
        assert adapter.name == "expo"

    def test_adapter_is_always_available(self):
        """ExpoAdapter est toujours disponible."""
        adapter = ExpoAdapter()
        assert adapter.is_available() is True

    def test_adapter_uses_provided_config(self):
        """ExpoAdapter utilise la config fournie."""
        config = ExpoConfig(access_token="custom_token")
        adapter = ExpoAdapter(config=config)
        assert adapter.config.access_token == "custom_token"

    def test_adapter_loads_config_from_env(self):
        """ExpoAdapter charge la config depuis l'env si non fournie."""
        with patch.dict(os.environ, {"EXPO_ACCESS_TOKEN": "env_token"}):
            adapter = ExpoAdapter()
            assert adapter.config.access_token == "env_token"


class TestExpoAdapterValidateToken:
    """Tests pour ExpoAdapter.validate_token."""

    def test_validate_token_valid_format(self):
        """validate_token accepte le format ExponentPushToken[xxx]."""
        adapter = ExpoAdapter()
        assert adapter.validate_token("ExponentPushToken[abc123]") is True

    def test_validate_token_empty(self):
        """validate_token rejette les tokens vides."""
        adapter = ExpoAdapter()
        assert adapter.validate_token("") is False

    def test_validate_token_none(self):
        """validate_token rejette None."""
        adapter = ExpoAdapter()
        assert adapter.validate_token(None) is False

    def test_validate_token_empty_brackets(self):
        """validate_token rejette ExponentPushToken[]."""
        adapter = ExpoAdapter()
        assert adapter.validate_token("ExponentPushToken[]") is False

    def test_validate_token_alternative_format(self):
        """validate_token accepte les anciens tokens longs."""
        adapter = ExpoAdapter()
        long_token = "a" * 25
        assert adapter.validate_token(long_token) is True

    def test_validate_token_short_token_rejected(self):
        """validate_token rejette les tokens trop courts."""
        adapter = ExpoAdapter()
        assert adapter.validate_token("short") is False


class TestExpoAdapterSend:
    """Tests pour ExpoAdapter.send."""

    def test_send_invalid_token_returns_error(self):
        """send avec token invalide retourne une erreur."""
        adapter = ExpoAdapter()
        result = adapter.send(
            device_token="invalid",
            title="Test",
            body="Test body",
        )
        assert result.success is False
        assert result.error_code == "INVALID_TOKEN"

    @patch("requests.post")
    def test_send_success(self, mock_post):
        """send réussit avec un token valide."""
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "data": {"status": "ok", "id": "msg_123"}
        }
        mock_post.return_value = mock_response

        adapter = ExpoAdapter()
        result = adapter.send(
            device_token="ExponentPushToken[abc123]",
            title="Test",
            body="Test body",
        )

        assert result.success is True
        assert result.message_id == "msg_123"

    @patch("requests.post")
    def test_send_with_data(self, mock_post):
        """send inclut les données personnalisées."""
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {"data": {"status": "ok", "id": "123"}}
        mock_post.return_value = mock_response

        adapter = ExpoAdapter()
        adapter.send(
            device_token="ExponentPushToken[abc123]",
            title="Test",
            body="Test body",
            data={"email_id": "123"},
        )

        call_args = mock_post.call_args
        sent_message = call_args.kwargs.get("json") or call_args[1].get("json")
        assert sent_message["data"] == {"email_id": "123"}

    @patch("requests.post")
    def test_send_with_high_priority(self, mock_post):
        """send avec priorité haute utilise 'high'."""
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {"data": {"status": "ok", "id": "123"}}
        mock_post.return_value = mock_response

        adapter = ExpoAdapter()
        adapter.send(
            device_token="ExponentPushToken[abc123]",
            title="Test",
            body="Test body",
            priority=NotificationPriority.HIGH,
        )

        call_args = mock_post.call_args
        sent_message = call_args.kwargs.get("json") or call_args[1].get("json")
        assert sent_message["priority"] == "high"

    @patch("requests.post")
    def test_send_with_access_token(self, mock_post):
        """send inclut le token d'accès dans les headers."""
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {"data": {"status": "ok", "id": "123"}}
        mock_post.return_value = mock_response

        config = ExpoConfig(access_token="my_token")
        adapter = ExpoAdapter(config=config)
        adapter.send(
            device_token="ExponentPushToken[abc123]",
            title="Test",
            body="Test body",
        )

        call_args = mock_post.call_args
        headers = call_args.kwargs.get("headers") or call_args[1].get("headers")
        assert headers["Authorization"] == "Bearer my_token"

    @patch("requests.post")
    def test_send_ticket_error(self, mock_post):
        """send gère les erreurs de ticket."""
        mock_response = MagicMock()
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
            device_token="ExponentPushToken[abc123]",
            title="Test",
            body="Test body",
        )

        assert result.success is False
        assert result.error_code == "DeviceNotRegistered"
        assert "Device not registered" in result.error_message

    @patch("requests.post")
    def test_send_http_error(self, mock_post):
        """send gère les erreurs HTTP."""
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_post.return_value = mock_response

        adapter = ExpoAdapter()
        result = adapter.send(
            device_token="ExponentPushToken[abc123]",
            title="Test",
            body="Test body",
        )

        assert result.success is False
        assert result.error_code == "HTTP_500"

    @patch("requests.post")
    def test_send_exception(self, mock_post):
        """send gère les exceptions."""
        mock_post.side_effect = Exception("Network error")

        adapter = ExpoAdapter()
        result = adapter.send(
            device_token="ExponentPushToken[abc123]",
            title="Test",
            body="Test body",
        )

        assert result.success is False
        assert result.error_code == "SEND_ERROR"
        assert "Network error" in result.error_message


class TestExpoAdapterSendBatch:
    """Tests pour ExpoAdapter.send_batch."""

    def test_send_batch_empty_list(self):
        """send_batch avec liste vide retourne liste vide."""
        adapter = ExpoAdapter()
        results = adapter.send_batch([], "Test", "Body")
        assert results == []

    def test_send_batch_invalid_tokens(self):
        """send_batch avec tokens invalides retourne des erreurs."""
        adapter = ExpoAdapter()
        results = adapter.send_batch(["short", "bad"], "Test", "Body")
        assert len(results) == 2
        assert all(r.success is False for r in results)
        assert all(r.error_code == "INVALID_TOKEN" for r in results)

    @patch("requests.post")
    def test_send_batch_success(self, mock_post):
        """send_batch réussit avec des tokens valides."""
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "data": [
                {"status": "ok", "id": "msg_1"},
                {"status": "ok", "id": "msg_2"},
            ]
        }
        mock_post.return_value = mock_response

        adapter = ExpoAdapter()
        results = adapter.send_batch(
            ["ExponentPushToken[a]", "ExponentPushToken[b]"],
            "Test",
            "Body",
        )

        assert len(results) == 2
        assert all(r.success is True for r in results)

    @patch("requests.post")
    def test_send_batch_mixed_valid_invalid(self, mock_post):
        """send_batch gère le mix de tokens valides/invalides."""
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "data": [{"status": "ok", "id": "msg_1"}]
        }
        mock_post.return_value = mock_response

        adapter = ExpoAdapter()
        results = adapter.send_batch(
            ["ExponentPushToken[valid]", "invalid"],
            "Test",
            "Body",
        )

        assert len(results) == 2
        # Premier résultat invalide (dans l'ordre de traitement)
        assert results[0].success is False  # invalid token
        assert results[1].success is True   # valid token

    @patch("requests.post")
    def test_send_batch_http_error(self, mock_post):
        """send_batch gère les erreurs HTTP pour tout le batch."""
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status_code = 500
        mock_response.text = "Server Error"
        mock_post.return_value = mock_response

        adapter = ExpoAdapter()
        results = adapter.send_batch(
            ["ExponentPushToken[a]", "ExponentPushToken[b]"],
            "Test",
            "Body",
        )

        assert len(results) == 2
        assert all(r.success is False for r in results)
        assert all(r.error_code == "HTTP_500" for r in results)


class TestExpoAdapterGetPushReceipts:
    """Tests pour ExpoAdapter.get_push_receipts."""

    def test_get_push_receipts_empty_list(self):
        """get_push_receipts avec liste vide retourne liste vide."""
        adapter = ExpoAdapter()
        receipts = adapter.get_push_receipts([])
        assert receipts == []

    @patch("requests.post")
    def test_get_push_receipts_success(self, mock_post):
        """get_push_receipts récupère les receipts."""
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "data": {
                "id_1": {"status": "ok"},
                "id_2": {"status": "error", "message": "Failed"},
            }
        }
        mock_post.return_value = mock_response

        adapter = ExpoAdapter()
        receipts = adapter.get_push_receipts(["id_1", "id_2"])

        assert receipts == {
            "id_1": {"status": "ok"},
            "id_2": {"status": "error", "message": "Failed"},
        }

    @patch("requests.post")
    def test_get_push_receipts_error(self, mock_post):
        """get_push_receipts gère les erreurs."""
        mock_post.side_effect = Exception("Network error")

        adapter = ExpoAdapter()
        receipts = adapter.get_push_receipts(["id_1"])

        assert receipts == []


# =============================================================================
# FCMConfig Tests
# =============================================================================


class TestFCMConfig:
    """Tests pour FCMConfig."""

    def test_config_default_values(self):
        """FCMConfig a des valeurs par défaut None."""
        config = FCMConfig()
        assert config.credentials_path is None
        assert config.project_id is None
        assert config.private_key is None
        assert config.client_email is None

    def test_config_with_values(self):
        """FCMConfig accepte des valeurs."""
        config = FCMConfig(
            credentials_path="/path/to/creds.json",
            project_id="my-project",
            private_key="key",
            client_email="email@test.com",
        )
        assert config.credentials_path == "/path/to/creds.json"
        assert config.project_id == "my-project"

    def test_config_from_env(self):
        """FCMConfig.from_env charge depuis l'environnement."""
        env = {
            "FIREBASE_CREDENTIALS_PATH": "/creds.json",
            "FIREBASE_PROJECT_ID": "proj",
            "FIREBASE_PRIVATE_KEY": "key",
            "FIREBASE_CLIENT_EMAIL": "email",
        }
        with patch.dict(os.environ, env):
            config = FCMConfig.from_env()
            assert config.credentials_path == "/creds.json"
            assert config.project_id == "proj"


# =============================================================================
# FCMAdapter Tests
# =============================================================================


class TestFCMAdapter:
    """Tests pour FCMAdapter."""

    def test_adapter_implements_notification_port(self):
        """FCMAdapter implémente NotificationPort."""
        adapter = FCMAdapter()
        assert isinstance(adapter, NotificationPort)

    def test_adapter_name(self):
        """FCMAdapter a le nom 'fcm'."""
        adapter = FCMAdapter()
        assert adapter.name == "fcm"

    def test_adapter_not_available_without_config(self):
        """FCMAdapter n'est pas disponible sans config."""
        config = FCMConfig()
        adapter = FCMAdapter(config=config)
        assert adapter.is_available() is False

    def test_adapter_available_with_credentials_path(self):
        """FCMAdapter est disponible avec credentials_path."""
        config = FCMConfig(credentials_path="/path/to/creds.json")
        adapter = FCMAdapter(config=config)

        with patch("os.path.exists", return_value=True):
            assert adapter.is_available() is True

    def test_adapter_available_with_env_credentials(self):
        """FCMAdapter est disponible avec credentials en env."""
        config = FCMConfig(
            project_id="proj",
            private_key="key",
            client_email="email",
        )
        adapter = FCMAdapter(config=config)
        assert adapter.is_available() is True


class TestFCMAdapterValidateToken:
    """Tests pour FCMAdapter.validate_token."""

    def test_validate_token_empty(self):
        """validate_token rejette les tokens vides."""
        adapter = FCMAdapter()
        assert adapter.validate_token("") is False

    def test_validate_token_none(self):
        """validate_token rejette None."""
        adapter = FCMAdapter()
        assert adapter.validate_token(None) is False

    def test_validate_token_too_short(self):
        """validate_token rejette les tokens trop courts."""
        adapter = FCMAdapter()
        assert adapter.validate_token("a" * 99) is False

    def test_validate_token_too_long(self):
        """validate_token rejette les tokens trop longs."""
        adapter = FCMAdapter()
        assert adapter.validate_token("a" * 201) is False

    def test_validate_token_valid_length(self):
        """validate_token accepte les tokens de bonne longueur."""
        adapter = FCMAdapter()
        token = "a" * 150
        assert adapter.validate_token(token) is True

    def test_validate_token_invalid_characters(self):
        """validate_token rejette les caractères invalides."""
        adapter = FCMAdapter()
        token = "a" * 100 + "!@#" + "a" * 50
        assert adapter.validate_token(token) is False


class TestFCMAdapterGetCredentials:
    """Tests pour FCMAdapter._get_credentials."""

    def test_get_credentials_from_file(self):
        """_get_credentials charge depuis un fichier."""
        creds_data = {
            "type": "service_account",
            "project_id": "my-project",
        }
        config = FCMConfig(credentials_path="/path/to/creds.json")
        adapter = FCMAdapter(config=config)

        with patch("os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=json.dumps(creds_data))):
                creds = adapter._get_credentials()
                assert creds["project_id"] == "my-project"

    def test_get_credentials_from_env(self):
        """_get_credentials construit depuis les variables d'env."""
        config = FCMConfig(
            project_id="proj",
            private_key="key\\nwith\\nnewlines",
            client_email="email@test.com",
        )
        adapter = FCMAdapter(config=config)

        creds = adapter._get_credentials()
        assert creds["project_id"] == "proj"
        assert "\n" in creds["private_key"]

    def test_get_credentials_none(self):
        """_get_credentials retourne None sans config."""
        config = FCMConfig()
        adapter = FCMAdapter(config=config)
        assert adapter._get_credentials() is None


class TestFCMAdapterSend:
    """Tests pour FCMAdapter.send."""

    def test_send_not_available(self):
        """send retourne erreur si non disponible."""
        config = FCMConfig()
        adapter = FCMAdapter(config=config)

        result = adapter.send("token", "Title", "Body")

        assert result.success is False
        assert result.error_code == "NOT_CONFIGURED"

    def test_send_auth_failed(self):
        """send retourne erreur si auth échoue."""
        config = FCMConfig(
            project_id="proj",
            private_key="key",
            client_email="email",
        )
        adapter = FCMAdapter(config=config)

        with patch.object(adapter, "_get_access_token", return_value=None):
            result = adapter.send("token", "Title", "Body")

        assert result.success is False
        assert result.error_code == "AUTH_FAILED"

    @patch("requests.post")
    def test_send_success(self, mock_post):
        """send réussit avec une réponse OK."""
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {"name": "projects/p/messages/msg_123"}
        mock_post.return_value = mock_response

        config = FCMConfig(
            project_id="proj",
            private_key="key",
            client_email="email",
        )
        adapter = FCMAdapter(config=config)

        with patch.object(adapter, "_get_access_token", return_value="access_token"):
            with patch.object(adapter, "_get_credentials", return_value={"project_id": "proj"}):
                result = adapter.send(
                    "a" * 150,
                    "Title",
                    "Body",
                )

        assert result.success is True
        assert result.message_id == "msg_123"

    @patch("requests.post")
    def test_send_with_data(self, mock_post):
        """send inclut les données personnalisées."""
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {"name": "projects/p/messages/123"}
        mock_post.return_value = mock_response

        config = FCMConfig(
            project_id="proj",
            private_key="key",
            client_email="email",
        )
        adapter = FCMAdapter(config=config)

        with patch.object(adapter, "_get_access_token", return_value="token"):
            with patch.object(adapter, "_get_credentials", return_value={"project_id": "proj"}):
                adapter.send(
                    "a" * 150,
                    "Title",
                    "Body",
                    data={"email_id": 123},
                )

        call_args = mock_post.call_args
        sent_message = call_args.kwargs.get("json") or call_args[1].get("json")
        assert sent_message["message"]["data"] == {"email_id": "123"}

    @patch("requests.post")
    def test_send_http_error(self, mock_post):
        """send gère les erreurs HTTP."""
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.json.return_value = {
            "error": {"status": "INVALID_ARGUMENT", "message": "Bad request"}
        }
        mock_response.text = "Error"
        mock_post.return_value = mock_response

        config = FCMConfig(
            project_id="proj",
            private_key="key",
            client_email="email",
        )
        adapter = FCMAdapter(config=config)

        with patch.object(adapter, "_get_access_token", return_value="token"):
            with patch.object(adapter, "_get_credentials", return_value={"project_id": "proj"}):
                result = adapter.send("a" * 150, "Title", "Body")

        assert result.success is False
        assert result.error_code == "INVALID_ARGUMENT"


class TestFCMAdapterSendBatch:
    """Tests pour FCMAdapter.send_batch."""

    def test_send_batch_calls_send_for_each(self):
        """send_batch appelle send pour chaque token."""
        adapter = FCMAdapter()

        with patch.object(adapter, "send") as mock_send:
            mock_send.return_value = PushNotificationResult(success=True)
            results = adapter.send_batch(
                ["token1", "token2"],
                "Title",
                "Body",
            )

        assert len(results) == 2
        assert mock_send.call_count == 2


# =============================================================================
# MockPushAdapter Tests
# =============================================================================


class TestMockPushAdapter:
    """Tests pour MockPushAdapter."""

    def test_adapter_implements_notification_port(self):
        """MockPushAdapter implémente NotificationPort."""
        adapter = MockPushAdapter()
        assert isinstance(adapter, NotificationPort)

    def test_adapter_name(self):
        """MockPushAdapter a le nom 'mock'."""
        adapter = MockPushAdapter()
        assert adapter.name == "mock"

    def test_adapter_is_always_available(self):
        """MockPushAdapter est toujours disponible."""
        adapter = MockPushAdapter()
        assert adapter.is_available() is True

    def test_adapter_default_success(self):
        """MockPushAdapter réussit par défaut."""
        adapter = MockPushAdapter()
        result = adapter.send("token", "Title", "Body")
        assert result.success is True

    def test_adapter_configurable_failure(self):
        """MockPushAdapter peut être configuré pour échouer."""
        adapter = MockPushAdapter(should_fail=True, failure_error="Custom error")
        result = adapter.send("token", "Title", "Body")
        assert result.success is False
        assert result.error_code == "MOCK_FAILURE"
        assert result.error_message == "Custom error"


class TestMockPushAdapterSend:
    """Tests pour MockPushAdapter.send."""

    def test_send_records_notification(self):
        """send enregistre la notification."""
        adapter = MockPushAdapter()
        adapter.send("token123", "Title", "Body", data={"key": "value"})

        assert len(adapter.sent_notifications) == 1
        record = adapter.sent_notifications[0]
        assert record.device_token == "token123"
        assert record.title == "Title"
        assert record.body == "Body"
        assert record.data == {"key": "value"}

    def test_send_generates_message_id(self):
        """send génère un message_id."""
        adapter = MockPushAdapter()
        result = adapter.send("token", "Title", "Body")
        assert result.message_id is not None

    def test_send_with_priority(self):
        """send enregistre la priorité."""
        adapter = MockPushAdapter()
        adapter.send(
            "token",
            "Title",
            "Body",
            priority=NotificationPriority.HIGH,
        )

        record = adapter.sent_notifications[0]
        assert record.priority == NotificationPriority.HIGH

    def test_send_invalid_token(self):
        """send échoue pour les tokens invalides."""
        adapter = MockPushAdapter(invalid_tokens=["bad_token"])
        result = adapter.send("bad_token", "Title", "Body")

        assert result.success is False
        assert result.error_code == "INVALID_TOKEN"
        assert len(adapter.sent_notifications) == 0


class TestMockPushAdapterSendBatch:
    """Tests pour MockPushAdapter.send_batch."""

    def test_send_batch_records_all(self):
        """send_batch enregistre toutes les notifications."""
        adapter = MockPushAdapter()
        results = adapter.send_batch(
            ["token1", "token2", "token3"],
            "Title",
            "Body",
        )

        assert len(results) == 3
        assert all(r.success is True for r in results)
        assert len(adapter.sent_notifications) == 3

    def test_send_batch_mixed(self):
        """send_batch gère le mix valide/invalide."""
        adapter = MockPushAdapter(invalid_tokens=["bad"])
        results = adapter.send_batch(
            ["good1", "bad", "good2"],
            "Title",
            "Body",
        )

        assert len(results) == 3
        assert results[0].success is True
        assert results[1].success is False
        assert results[2].success is True
        assert len(adapter.sent_notifications) == 2


class TestMockPushAdapterValidateToken:
    """Tests pour MockPushAdapter.validate_token."""

    def test_validate_token_empty(self):
        """validate_token rejette les tokens vides."""
        adapter = MockPushAdapter()
        assert adapter.validate_token("") is False

    def test_validate_token_none(self):
        """validate_token rejette None."""
        adapter = MockPushAdapter()
        assert adapter.validate_token(None) is False

    def test_validate_token_valid(self):
        """validate_token accepte les tokens valides."""
        adapter = MockPushAdapter()
        assert adapter.validate_token("any_token") is True

    def test_validate_token_invalid_list(self):
        """validate_token rejette les tokens dans la liste."""
        adapter = MockPushAdapter(invalid_tokens=["bad1", "bad2"])
        assert adapter.validate_token("bad1") is False
        assert adapter.validate_token("good") is True


class TestMockPushAdapterUtilities:
    """Tests pour les méthodes utilitaires de MockPushAdapter."""

    def test_clear(self):
        """clear efface toutes les notifications."""
        adapter = MockPushAdapter()
        adapter.send("token1", "Title", "Body")
        adapter.send("token2", "Title", "Body")
        assert len(adapter.sent_notifications) == 2

        adapter.clear()
        assert len(adapter.sent_notifications) == 0

    def test_get_notifications_for_token(self):
        """get_notifications_for_token filtre par token."""
        adapter = MockPushAdapter()
        adapter.send("token1", "Title1", "Body1")
        adapter.send("token2", "Title2", "Body2")
        adapter.send("token1", "Title3", "Body3")

        token1_notifs = adapter.get_notifications_for_token("token1")
        assert len(token1_notifs) == 2
        assert all(n.device_token == "token1" for n in token1_notifs)

    def test_get_notifications_count(self):
        """get_notifications_count retourne le bon nombre."""
        adapter = MockPushAdapter()
        assert adapter.get_notifications_count() == 0

        adapter.send("token", "Title", "Body")
        assert adapter.get_notifications_count() == 1

    def test_set_should_fail(self):
        """set_should_fail configure l'état d'échec."""
        adapter = MockPushAdapter()
        result1 = adapter.send("token", "Title", "Body")
        assert result1.success is True

        adapter.set_should_fail(True, "Forced error")
        result2 = adapter.send("token", "Title", "Body")
        assert result2.success is False
        assert result2.error_message == "Forced error"

        adapter.set_should_fail(False)
        result3 = adapter.send("token", "Title", "Body")
        assert result3.success is True

    def test_add_invalid_token(self):
        """add_invalid_token ajoute un token invalide."""
        adapter = MockPushAdapter()
        assert adapter.validate_token("token") is True

        adapter.add_invalid_token("token")
        assert adapter.validate_token("token") is False

    def test_add_invalid_token_idempotent(self):
        """add_invalid_token est idempotent."""
        adapter = MockPushAdapter()
        adapter.add_invalid_token("token")
        adapter.add_invalid_token("token")
        assert len(adapter.invalid_tokens) == 1

    def test_remove_invalid_token(self):
        """remove_invalid_token retire un token invalide."""
        adapter = MockPushAdapter(invalid_tokens=["token"])
        assert adapter.validate_token("token") is False

        adapter.remove_invalid_token("token")
        assert adapter.validate_token("token") is True

    def test_remove_invalid_token_not_present(self):
        """remove_invalid_token ne fait rien si token absent."""
        adapter = MockPushAdapter()
        adapter.remove_invalid_token("not_present")
        assert len(adapter.invalid_tokens) == 0


class TestMockNotificationRecord:
    """Tests pour MockNotificationRecord."""

    def test_record_has_all_fields(self):
        """MockNotificationRecord a tous les champs."""
        record = MockNotificationRecord(
            device_token="token",
            title="Title",
            body="Body",
            data={"key": "value"},
            priority=NotificationPriority.HIGH,
        )
        assert record.device_token == "token"
        assert record.title == "Title"
        assert record.body == "Body"
        assert record.data == {"key": "value"}
        assert record.priority == NotificationPriority.HIGH
        assert record.sent_at is not None
        assert record.message_id is not None

    def test_record_defaults(self):
        """MockNotificationRecord a des valeurs par défaut."""
        record = MockNotificationRecord(
            device_token="token",
            title="Title",
            body="Body",
            data=None,
            priority=NotificationPriority.NORMAL,
        )
        assert record.data is None
        assert record.priority == NotificationPriority.NORMAL


# =============================================================================
# Integration Tests
# =============================================================================


class TestPushAdaptersInteroperability:
    """Tests d'interopérabilité entre les adapters."""

    def test_all_adapters_have_same_interface(self):
        """Tous les adapters ont la même interface."""
        adapters = [
            ExpoAdapter(),
            FCMAdapter(),
            MockPushAdapter(),
        ]

        for adapter in adapters:
            assert hasattr(adapter, "name")
            assert hasattr(adapter, "is_available")
            assert hasattr(adapter, "send")
            assert hasattr(adapter, "send_batch")
            assert hasattr(adapter, "validate_token")

    def test_all_adapters_return_same_result_type(self):
        """Tous les adapters retournent PushNotificationResult."""
        mock_adapter = MockPushAdapter()
        result = mock_adapter.send("token", "Title", "Body")
        assert isinstance(result, PushNotificationResult)

        # Expo avec token invalide
        expo_adapter = ExpoAdapter()
        result = expo_adapter.send("invalid", "Title", "Body")
        assert isinstance(result, PushNotificationResult)

        # FCM non configuré
        fcm_adapter = FCMAdapter()
        result = fcm_adapter.send("token", "Title", "Body")
        assert isinstance(result, PushNotificationResult)
