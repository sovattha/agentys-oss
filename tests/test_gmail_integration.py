# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests d'intégration pour le provider Gmail avec mock de l'API Google.
"""

import pytest
from unittest.mock import MagicMock, patch
import base64

from app.providers.gmail_adapter import GmailAdapter as GmailProvider


# ============================================================================
# FIXTURES - MOCK GMAIL API
# ============================================================================

@pytest.fixture
def mock_gmail_message():
    """Message Gmail simulé."""
    return {
        "id": "msg-123",
        "threadId": "thread-456",
        "labelIds": ["INBOX", "UNREAD"],
        "payload": {
            "headers": [
                {"name": "From", "value": "sender@example.com"},
                {"name": "To", "value": "recipient@example.com"},
                {"name": "Subject", "value": "Test Subject"},
                {"name": "Date", "value": "Mon, 15 Jan 2025 10:30:00 +0000"},
            ],
            "body": {
                "data": base64.urlsafe_b64encode(b"Test email body").decode()
            },
            "parts": []
        }
    }


@pytest.fixture
def mock_gmail_message_with_name():
    """Message Gmail avec nom d'expéditeur."""
    return {
        "id": "msg-456",
        "threadId": "thread-789",
        "labelIds": ["INBOX"],
        "payload": {
            "headers": [
                {"name": "From", "value": "Jean Dupont <jean.dupont@example.com>"},
                {"name": "To", "value": "support@company.com"},
                {"name": "Subject", "value": "Question importante"},
                {"name": "Date", "value": "Tue, 16 Jan 2025 14:00:00 +0100"},
            ],
            "body": {
                "data": base64.urlsafe_b64encode(b"Bonjour, j'ai une question.").decode()
            },
            "parts": []
        }
    }


@pytest.fixture
def mock_gmail_service(mock_gmail_message):
    """Service Gmail mocké."""
    service = MagicMock()

    # Mock users().messages().list()
    list_response = {"messages": [{"id": "msg-123"}]}
    service.users().messages().list().execute.return_value = list_response

    # Mock users().messages().get()
    service.users().messages().get().execute.return_value = mock_gmail_message

    # Mock users().messages().modify()
    service.users().messages().modify().execute.return_value = {}

    # Mock users().drafts().create()
    service.users().drafts().create().execute.return_value = {"id": "draft-001"}

    # Mock users().drafts().send()
    service.users().drafts().send().execute.return_value = {}

    return service


# ============================================================================
# TESTS - GMAIL PROVIDER
# ============================================================================

class TestGmailProviderAuthentication:
    """Tests d'authentification Gmail."""

    @patch("builtins.open", MagicMock())
    @patch("os.path.exists", return_value=False)
    @patch("app.providers.gmail_adapter.Credentials")
    @patch("app.providers.gmail_adapter.build")
    def test_authenticate_with_valid_token(self, mock_build, mock_creds_class, mock_exists):
        """Authentification réussie avec token valide."""
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.expired = False
        mock_creds.refresh_token = "refresh-token"
        mock_creds.to_json.return_value = "{}"
        mock_creds_class.return_value = mock_creds

        mock_service = MagicMock()
        mock_build.return_value = mock_service

        with patch.dict("os.environ", {
            "GOOGLE_CLIENT_ID": "client-id",
            "GOOGLE_CLIENT_SECRET": "client-secret",
            "GOOGLE_REFRESH_TOKEN": "refresh-token"
        }):
            provider = GmailProvider()
            result = provider.authenticate()

        assert result is True

    @patch("builtins.open", MagicMock())
    @patch("os.path.exists", return_value=False)
    @patch("app.providers.gmail_adapter.Credentials")
    @patch("app.providers.gmail_adapter.build")
    @patch("app.providers.gmail_adapter.Request")
    def test_authenticate_refreshes_expired_token(self, mock_request, mock_build, mock_creds_class, mock_exists):
        """Rafraîchissement du token expiré."""
        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds.refresh_token = "refresh-token"
        mock_creds.to_json.return_value = "{}"
        mock_creds_class.return_value = mock_creds

        mock_build.return_value = MagicMock()

        with patch.dict("os.environ", {
            "GOOGLE_CLIENT_ID": "client-id",
            "GOOGLE_CLIENT_SECRET": "client-secret",
            "GOOGLE_REFRESH_TOKEN": "refresh-token"
        }):
            provider = GmailProvider()
            provider.authenticate()

        mock_creds.refresh.assert_called_once()


class TestGmailProviderMessages:
    """Tests de récupération des messages."""

    @patch("builtins.open", MagicMock())
    @patch("os.path.exists", return_value=False)
    @patch("app.providers.gmail_adapter.Credentials")
    @patch("app.providers.gmail_adapter.build")
    def test_get_unread_messages(self, mock_build, mock_creds_class, mock_exists, mock_gmail_service, mock_gmail_message):
        """Récupération des messages non lus."""
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.to_json.return_value = "{}"
        mock_creds_class.return_value = mock_creds
        mock_build.return_value = mock_gmail_service

        with patch.dict("os.environ", {
            "GOOGLE_CLIENT_ID": "client-id",
            "GOOGLE_CLIENT_SECRET": "client-secret",
            "GOOGLE_REFRESH_TOKEN": "refresh-token"
        }):
            provider = GmailProvider()
            provider.authenticate()
            messages = provider.get_unread_messages(limit=10)

        assert len(messages) == 1
        assert messages[0].id == "msg-123"
        assert messages[0].sender == "sender@example.com"
        assert messages[0].subject == "Test Subject"

    @patch("builtins.open", MagicMock())
    @patch("os.path.exists", return_value=False)
    @patch("app.providers.gmail_adapter.Credentials")
    @patch("app.providers.gmail_adapter.build")
    def test_get_message_by_id(self, mock_build, mock_creds_class, mock_exists, mock_gmail_service):
        """Récupération d'un message par ID."""
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.to_json.return_value = "{}"
        mock_creds_class.return_value = mock_creds
        mock_build.return_value = mock_gmail_service

        with patch.dict("os.environ", {
            "GOOGLE_CLIENT_ID": "client-id",
            "GOOGLE_CLIENT_SECRET": "client-secret",
            "GOOGLE_REFRESH_TOKEN": "refresh-token"
        }):
            provider = GmailProvider()
            provider.authenticate()
            message = provider.get_message_by_id("msg-123")

        assert message is not None
        assert message.id == "msg-123"


class TestGmailProviderDrafts:
    """Tests de création de brouillons."""

    @patch("builtins.open", MagicMock())
    @patch("os.path.exists", return_value=False)
    @patch("app.providers.gmail_adapter.Credentials")
    @patch("app.providers.gmail_adapter.build")
    def test_create_draft(self, mock_build, mock_creds_class, mock_exists, mock_gmail_service):
        """Création d'un brouillon."""
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.to_json.return_value = "{}"
        mock_creds_class.return_value = mock_creds
        mock_build.return_value = mock_gmail_service

        with patch.dict("os.environ", {
            "GOOGLE_CLIENT_ID": "client-id",
            "GOOGLE_CLIENT_SECRET": "client-secret",
            "GOOGLE_REFRESH_TOKEN": "refresh-token"
        }):
            provider = GmailProvider()
            provider.authenticate()
            draft_id = provider.create_draft(
                to=["recipient@example.com"],
                subject="Re: Test",
                body="Merci pour votre message.",
                reply_to_id="msg-123"
            )

        assert draft_id == "draft-001"

    @patch("builtins.open", MagicMock())
    @patch("os.path.exists", return_value=False)
    @patch("app.providers.gmail_adapter.Credentials")
    @patch("app.providers.gmail_adapter.build")
    def test_create_draft_with_cc(self, mock_build, mock_creds_class, mock_exists, mock_gmail_service):
        """Création d'un brouillon avec CC."""
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.to_json.return_value = "{}"
        mock_creds_class.return_value = mock_creds
        mock_build.return_value = mock_gmail_service

        with patch.dict("os.environ", {
            "GOOGLE_CLIENT_ID": "client-id",
            "GOOGLE_CLIENT_SECRET": "client-secret",
            "GOOGLE_REFRESH_TOKEN": "refresh-token"
        }):
            provider = GmailProvider()
            provider.authenticate()
            draft_id = provider.create_draft(
                to=["recipient@example.com"],
                subject="Test",
                body="Message",
                cc=["cc@example.com"]
            )

        assert draft_id is not None


class TestGmailProviderMarkAsRead:
    """Tests de marquage comme lu."""

    @patch("builtins.open", MagicMock())
    @patch("os.path.exists", return_value=False)
    @patch("app.providers.gmail_adapter.Credentials")
    @patch("app.providers.gmail_adapter.build")
    def test_mark_as_read(self, mock_build, mock_creds_class, mock_exists, mock_gmail_service):
        """Marquage d'un message comme lu."""
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.to_json.return_value = "{}"
        mock_creds_class.return_value = mock_creds
        mock_build.return_value = mock_gmail_service

        with patch.dict("os.environ", {
            "GOOGLE_CLIENT_ID": "client-id",
            "GOOGLE_CLIENT_SECRET": "client-secret",
            "GOOGLE_REFRESH_TOKEN": "refresh-token"
        }):
            provider = GmailProvider()
            provider.authenticate()
            result = provider.mark_as_read("msg-123")

        assert result is True
        mock_gmail_service.users().messages().modify.assert_called()


# ============================================================================
# TESTS - PARSING EMAIL ADDRESS
# ============================================================================

class TestEmailAddressParsing:
    """Tests du parsing des adresses email."""

    @patch("app.providers.gmail_adapter.Credentials")
    @patch("app.providers.gmail_adapter.build")
    def test_parse_simple_email(self, mock_build, mock_creds_class):
        """Parse email simple."""
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds_class.return_value = mock_creds
        mock_build.return_value = MagicMock()

        with patch.dict("os.environ", {
            "GOOGLE_CLIENT_ID": "id",
            "GOOGLE_CLIENT_SECRET": "secret",
            "GOOGLE_REFRESH_TOKEN": "token"
        }):
            provider = GmailProvider()
            # _parse_email_address returns (email, name)
            email, name = provider._parse_email_address("test@example.com")

        assert email == "test@example.com"
        assert name is None

    @patch("app.providers.gmail_adapter.Credentials")
    @patch("app.providers.gmail_adapter.build")
    def test_parse_email_with_name(self, mock_build, mock_creds_class):
        """Parse email avec nom."""
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds_class.return_value = mock_creds
        mock_build.return_value = MagicMock()

        with patch.dict("os.environ", {
            "GOOGLE_CLIENT_ID": "id",
            "GOOGLE_CLIENT_SECRET": "secret",
            "GOOGLE_REFRESH_TOKEN": "token"
        }):
            provider = GmailProvider()
            # _parse_email_address returns (email, name)
            email, name = provider._parse_email_address("Jean Dupont <jean@example.com>")

        assert email == "jean@example.com"
        assert name == "Jean Dupont"

    @patch("app.providers.gmail_adapter.Credentials")
    @patch("app.providers.gmail_adapter.build")
    def test_parse_email_with_quoted_name(self, mock_build, mock_creds_class):
        """Parse email avec nom entre guillemets."""
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds_class.return_value = mock_creds
        mock_build.return_value = MagicMock()

        with patch.dict("os.environ", {
            "GOOGLE_CLIENT_ID": "id",
            "GOOGLE_CLIENT_SECRET": "secret",
            "GOOGLE_REFRESH_TOKEN": "token"
        }):
            provider = GmailProvider()
            # _parse_email_address returns (email, name)
            email, name = provider._parse_email_address('"Jean Dupont" <jean@example.com>')

        assert email == "jean@example.com"
        assert name == "Jean Dupont"


# ============================================================================
# TESTS - INTÉGRATION COMPLÈTE
# ============================================================================

class TestGmailFullIntegration:
    """Tests d'intégration complète du flux."""

    @patch("builtins.open", MagicMock())
    @patch("os.path.exists", return_value=False)
    @patch("app.providers.gmail_adapter.Credentials")
    @patch("app.providers.gmail_adapter.build")
    def test_full_email_processing_flow(self, mock_build, mock_creds_class, mock_exists, mock_gmail_service, mock_gmail_message):
        """Test du flux complet : récupérer, traiter, créer brouillon."""
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.to_json.return_value = "{}"
        mock_creds_class.return_value = mock_creds
        mock_build.return_value = mock_gmail_service

        with patch.dict("os.environ", {
            "GOOGLE_CLIENT_ID": "client-id",
            "GOOGLE_CLIENT_SECRET": "client-secret",
            "GOOGLE_REFRESH_TOKEN": "refresh-token"
        }):
            provider = GmailProvider()

            # 1. Authentification
            assert provider.authenticate() is True

            # 2. Récupérer messages non lus
            messages = provider.get_unread_messages(limit=5)
            assert len(messages) >= 1

            # 3. Traiter le premier message
            email = messages[0]
            assert email.sender is not None
            assert email.subject is not None

            # 4. Créer un brouillon de réponse
            draft_id = provider.create_draft(
                to=[email.sender],
                subject=f"Re: {email.subject}",
                body="Merci pour votre message. Cordialement.",
                reply_to_id=email.id
            )
            assert draft_id is not None

            # 5. Marquer comme lu
            result = provider.mark_as_read(email.id)
            assert result is True
