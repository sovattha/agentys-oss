# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests d'intégration pour le provider Outlook avec mock de Microsoft Graph API.
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime


# Skip all tests if azure module is not available
pytest.importorskip("azure.identity", reason="azure-identity not installed")


# ============================================================================
# FIXTURES - MOCK GRAPH API
# ============================================================================

@pytest.fixture
def mock_graph_message():
    """Message Graph API simulé."""
    message = MagicMock()
    message.id = "msg-outlook-123"
    message.conversation_id = "conv-456"
    message.subject = "Test Outlook Subject"
    message.is_read = False
    message.has_attachments = False
    message.received_date_time = datetime(2025, 1, 15, 10, 30, 0)
    message.importance = "normal"
    message.categories = []
    message.web_link = "https://outlook.office.com/mail/..."

    # From
    message.from_ = MagicMock()
    message.from_.email_address = MagicMock()
    message.from_.email_address.address = "sender@outlook.com"
    message.from_.email_address.name = "Outlook Sender"

    # To recipients
    to_recipient = MagicMock()
    to_recipient.email_address = MagicMock()
    to_recipient.email_address.address = "recipient@company.com"
    message.to_recipients = [to_recipient]

    # CC recipients
    message.cc_recipients = []

    # Body
    message.body = MagicMock()
    message.body.content_type = MagicMock()
    message.body.content_type.value = "text"
    message.body.content = "Test email body from Outlook"

    return message


@pytest.fixture
def mock_graph_client(mock_graph_message):
    """Client Graph API mocké."""
    client = MagicMock()

    # Mock async get messages
    messages_result = MagicMock()
    messages_result.value = [mock_graph_message]

    async def mock_get_messages(*args, **kwargs):
        return messages_result

    async def mock_get_message(*args, **kwargs):
        return mock_graph_message

    async def mock_post_message(*args, **kwargs):
        result = MagicMock()
        result.id = "draft-outlook-001"
        return result

    async def mock_patch_message(*args, **kwargs):
        return None

    async def mock_send(*args, **kwargs):
        return None

    # Configure mocks
    client.users.by_user_id().messages.get = AsyncMock(side_effect=mock_get_messages)
    client.users.by_user_id().messages.by_message_id().get = AsyncMock(side_effect=mock_get_message)
    client.users.by_user_id().messages.post = AsyncMock(side_effect=mock_post_message)
    client.users.by_user_id().messages.by_message_id().patch = AsyncMock(side_effect=mock_patch_message)
    client.users.by_user_id().messages.by_message_id().send.post = AsyncMock(side_effect=mock_send)
    client.users.by_user_id().messages.by_message_id().create_reply.post = AsyncMock(side_effect=mock_post_message)

    # _get_messages_async uses mail_folders.by_mail_folder_id("inbox").messages.get
    client.users.by_user_id().mail_folders.by_mail_folder_id().messages.get = AsyncMock(side_effect=mock_get_messages)

    return client


# ============================================================================
# TESTS - OUTLOOK ADAPTER
# ============================================================================

class TestOutlookAdapterInit:
    """Tests d'initialisation de l'adaptateur Outlook."""

    def test_init_missing_tenant_id(self):
        """Erreur si AZURE_TENANT_ID manquant."""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="AZURE_TENANT_ID"):
                from app.providers.outlook_adapter import OutlookAdapter
                OutlookAdapter()

    def test_init_missing_client_secret_app_mode(self):
        """Erreur si AZURE_CLIENT_SECRET manquant en mode app."""
        with patch.dict("os.environ", {
            "AZURE_TENANT_ID": "tenant-id",
            "AZURE_CLIENT_ID": "client-id",
        }, clear=True):
            with pytest.raises(ValueError, match="AZURE_CLIENT_SECRET"):
                from app.providers.outlook_adapter import OutlookAdapter
                OutlookAdapter()

    def test_init_device_code_no_secret_needed(self):
        """Pas besoin de secret en mode device code."""
        with patch.dict("os.environ", {
            "AZURE_TENANT_ID": "tenant-id",
            "AZURE_CLIENT_ID": "client-id",
            "OUTLOOK_USER_ID": "user@company.com",
        }, clear=True):
            from app.providers.outlook_adapter import OutlookAdapter
            # Should not raise
            adapter = OutlookAdapter(use_device_code=True)
            assert adapter.use_device_code is True


class TestOutlookAdapterAuthentication:
    """Tests d'authentification Outlook."""

    @patch("app.providers.outlook_adapter.ClientSecretCredential")
    @patch("app.providers.outlook_adapter.GraphServiceClient")
    def test_authenticate_client_credentials(self, mock_graph_client_class, mock_credential):
        """Authentification avec client credentials."""
        mock_graph_client_class.return_value = MagicMock()

        with patch.dict("os.environ", {
            "AZURE_TENANT_ID": "tenant-id",
            "AZURE_CLIENT_ID": "client-id",
            "AZURE_CLIENT_SECRET": "client-secret",
            "OUTLOOK_USER_ID": "user@company.com",
        }):
            from app.providers.outlook_adapter import OutlookAdapter
            adapter = OutlookAdapter()
            result = adapter.authenticate()

        assert result is True
        mock_credential.assert_called_once()

    @patch("app.providers.outlook_adapter.DeviceCodeCredential")
    @patch("app.providers.outlook_adapter.GraphServiceClient")
    def test_authenticate_device_code(self, mock_graph_client_class, mock_credential):
        """Authentification avec device code."""
        mock_graph_client_class.return_value = MagicMock()

        with patch.dict("os.environ", {
            "AZURE_TENANT_ID": "tenant-id",
            "AZURE_CLIENT_ID": "client-id",
            "OUTLOOK_USER_ID": "user@company.com",
        }):
            from app.providers.outlook_adapter import OutlookAdapter
            adapter = OutlookAdapter(use_device_code=True)
            result = adapter.authenticate()

        assert result is True
        mock_credential.assert_called_once()


class TestOutlookAdapterMessages:
    """Tests de récupération des messages Outlook."""

    @patch("app.providers.outlook_adapter.ClientSecretCredential")
    @patch("app.providers.outlook_adapter.GraphServiceClient")
    def test_get_unread_messages(self, mock_graph_client_class, mock_credential, mock_graph_client, mock_graph_message):
        """Récupération des messages non lus."""
        mock_graph_client_class.return_value = mock_graph_client

        with patch.dict("os.environ", {
            "AZURE_TENANT_ID": "tenant-id",
            "AZURE_CLIENT_ID": "client-id",
            "AZURE_CLIENT_SECRET": "client-secret",
            "OUTLOOK_USER_ID": "user@company.com",
        }):
            from app.providers.outlook_adapter import OutlookAdapter
            adapter = OutlookAdapter()
            adapter.authenticate()
            messages = adapter.get_unread_messages(limit=10)

        assert len(messages) == 1
        assert messages[0].id == "msg-outlook-123"
        assert messages[0].sender == "sender@outlook.com"

    @patch("app.providers.outlook_adapter.ClientSecretCredential")
    @patch("app.providers.outlook_adapter.GraphServiceClient")
    def test_get_message_by_id(self, mock_graph_client_class, mock_credential, mock_graph_client):
        """Récupération d'un message par ID."""
        mock_graph_client_class.return_value = mock_graph_client

        with patch.dict("os.environ", {
            "AZURE_TENANT_ID": "tenant-id",
            "AZURE_CLIENT_ID": "client-id",
            "AZURE_CLIENT_SECRET": "client-secret",
            "OUTLOOK_USER_ID": "user@company.com",
        }):
            from app.providers.outlook_adapter import OutlookAdapter
            adapter = OutlookAdapter()
            adapter.authenticate()
            message = adapter.get_message_by_id("msg-outlook-123")

        assert message is not None
        assert message.subject == "Test Outlook Subject"


class TestOutlookAdapterDrafts:
    """Tests de création de brouillons Outlook."""

    @patch("app.providers.outlook_adapter.ClientSecretCredential")
    @patch("app.providers.outlook_adapter.GraphServiceClient")
    def test_create_draft(self, mock_graph_client_class, mock_credential, mock_graph_client):
        """Création d'un brouillon."""
        mock_graph_client_class.return_value = mock_graph_client

        with patch.dict("os.environ", {
            "AZURE_TENANT_ID": "tenant-id",
            "AZURE_CLIENT_ID": "client-id",
            "AZURE_CLIENT_SECRET": "client-secret",
            "OUTLOOK_USER_ID": "user@company.com",
        }):
            from app.providers.outlook_adapter import OutlookAdapter
            adapter = OutlookAdapter()
            adapter.authenticate()
            draft_id = adapter.create_draft(
                to=["recipient@example.com"],
                subject="Test Draft",
                body="Draft body"
            )

        assert draft_id == "draft-outlook-001"

    @patch("app.providers.outlook_adapter.ClientSecretCredential")
    @patch("app.providers.outlook_adapter.GraphServiceClient")
    def test_create_reply_draft(self, mock_graph_client_class, mock_credential, mock_graph_client):
        """Création d'un brouillon de réponse."""
        mock_graph_client_class.return_value = mock_graph_client

        with patch.dict("os.environ", {
            "AZURE_TENANT_ID": "tenant-id",
            "AZURE_CLIENT_ID": "client-id",
            "AZURE_CLIENT_SECRET": "client-secret",
            "OUTLOOK_USER_ID": "user@company.com",
        }):
            from app.providers.outlook_adapter import OutlookAdapter
            adapter = OutlookAdapter()
            adapter.authenticate()
            draft_id = adapter.create_draft(
                to=["recipient@example.com"],
                subject="Re: Test",
                body="Reply body",
                reply_to_id="original-msg-id"
            )

        assert draft_id is not None


class TestOutlookAdapterMarkAsRead:
    """Tests de marquage comme lu Outlook."""

    @patch("app.providers.outlook_adapter.ClientSecretCredential")
    @patch("app.providers.outlook_adapter.GraphServiceClient")
    def test_mark_as_read(self, mock_graph_client_class, mock_credential, mock_graph_client):
        """Marquage d'un message comme lu."""
        mock_graph_client_class.return_value = mock_graph_client

        with patch.dict("os.environ", {
            "AZURE_TENANT_ID": "tenant-id",
            "AZURE_CLIENT_ID": "client-id",
            "AZURE_CLIENT_SECRET": "client-secret",
            "OUTLOOK_USER_ID": "user@company.com",
        }):
            from app.providers.outlook_adapter import OutlookAdapter
            adapter = OutlookAdapter()
            adapter.authenticate()
            result = adapter.mark_as_read("msg-outlook-123")

        assert result is True


# ============================================================================
# TESTS - MAPPING STANDARD EMAIL
# ============================================================================

class TestOutlookEmailMapping:
    """Tests du mapping vers StandardEmail."""

    @patch("app.providers.outlook_adapter.ClientSecretCredential")
    @patch("app.providers.outlook_adapter.GraphServiceClient")
    def test_map_to_standard_email(self, mock_graph_client_class, mock_credential, mock_graph_message):
        """Mapping correct d'un message Graph vers StandardEmail."""
        mock_graph_client_class.return_value = MagicMock()

        with patch.dict("os.environ", {
            "AZURE_TENANT_ID": "tenant-id",
            "AZURE_CLIENT_ID": "client-id",
            "AZURE_CLIENT_SECRET": "client-secret",
            "OUTLOOK_USER_ID": "user@company.com",
        }):
            from app.providers.outlook_adapter import OutlookAdapter
            adapter = OutlookAdapter()
            email = adapter._map_to_standard_email(mock_graph_message)

        assert email.id == "msg-outlook-123"
        assert email.sender == "sender@outlook.com"
        assert email.sender_name == "Outlook Sender"
        assert email.subject == "Test Outlook Subject"
        assert "recipient@company.com" in email.to
        assert email.provider_source == "outlook"
