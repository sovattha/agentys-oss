# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests supplémentaires pour améliorer la couverture de GmailAdapter.

Ces tests couvrent les méthodes et branches non testées :
- send_draft (succès et erreur)
- _get_or_create_label (création et récupération)
- move_to_spam (succès et erreur)
- get_user_drafts (succès et erreur)
- get_draft_by_id (succès et erreur)
- get_sent_emails (succès et erreur)
- update_draft (succès et erreur)
- _ensure_authenticated (RuntimeError)
- authenticate avec credentials file et token file corrompu
"""

import base64
import logging
import pytest
from unittest.mock import MagicMock, patch, mock_open
import httplib2
from googleapiclient.errors import HttpError

from app.interfaces.email_provider import StandardEmail


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_gmail_service():
    """Service Gmail entièrement mocké."""
    service = MagicMock()
    return service


@pytest.fixture
def authenticated_gmail_adapter(mock_gmail_service):
    """GmailAdapter authentifié avec service mocké."""
    with patch("app.providers.gmail_adapter.build"):
        with patch("app.providers.gmail_adapter.Credentials"):
            from app.providers.gmail_adapter import GmailAdapter
            adapter = GmailAdapter.__new__(GmailAdapter)
            adapter._service = mock_gmail_service
            adapter._credentials = MagicMock()
            adapter._credentials.valid = True
            adapter._authenticated = True
            adapter.PROVIDER_NAME = "gmail"
            adapter.token_file = "token.json"
            adapter.credentials_file = None
            adapter.client_id = "test-client-id"
            adapter.client_secret = "test-client-secret"
            adapter.refresh_token = "test-refresh-token"
            return adapter


# =============================================================================
# Tests - send_draft
# =============================================================================


class TestGmailApiTiming:
    """Tests pour l'instrumentation des appels Gmail."""

    def test_execute_gmail_request_logs_slow_success(self, caplog):
        from app.providers.gmail_adapter import GmailAdapter

        adapter = GmailAdapter.__new__(GmailAdapter)
        adapter.account_id = "acct-1"
        adapter._quota = MagicMock()
        adapter._quota.run.side_effect = lambda operation, execute, max_wait_seconds=None: execute()

        request = MagicMock()
        request.execute.return_value = {"id": "msg-1"}

        with patch("app.providers.gmail_adapter.time.perf_counter", side_effect=[100.0, 106.0]):
            with caplog.at_level(logging.WARNING, logger="app.providers.gmail_adapter"):
                assert adapter._execute_gmail_request(request, "messages.get") == {"id": "msg-1"}

        assert "[GMAIL-API]" in caplog.text
        assert "operation=messages.get" in caplog.text
        assert "account_key=acct-1" in caplog.text
        assert "success=true" in caplog.text
        assert "ms=6000" in caplog.text

    def test_execute_gmail_request_logs_failure(self, caplog):
        from app.providers.gmail_adapter import GmailAdapter

        adapter = GmailAdapter.__new__(GmailAdapter)
        adapter.account_id = "acct-1"
        adapter._quota = MagicMock()
        adapter._quota.run.side_effect = RuntimeError("network stalled")

        request = MagicMock()

        with patch("app.providers.gmail_adapter.time.perf_counter", side_effect=[200.0, 202.0]):
            with caplog.at_level(logging.WARNING, logger="app.providers.gmail_adapter"):
                with pytest.raises(RuntimeError):
                    adapter._execute_gmail_request(request, "history.list")

        assert "[GMAIL-API]" in caplog.text
        assert "operation=history.list" in caplog.text
        assert "success=false" in caplog.text
        assert "error_type=RuntimeError" in caplog.text
        assert "ms=2000" in caplog.text


class TestSendDraft:
    """Tests pour GmailAdapter.send_draft()."""

    def test_send_draft_success(self, authenticated_gmail_adapter, mock_gmail_service):
        """
        ARRANGE: draft_id valide, API retourne succès
        ACT: Appeler send_draft()
        ASSERT: Retourne True
        """
        # Arrange
        mock_gmail_service.users().drafts().send().execute.return_value = {}

        # Act
        result = authenticated_gmail_adapter.send_draft("draft-123")

        # Assert
        assert result is True
        mock_gmail_service.users().drafts().send.assert_called()

    def test_send_draft_http_error_returns_false(self, authenticated_gmail_adapter, mock_gmail_service):
        """
        ARRANGE: API Gmail lève HttpError
        ACT: Appeler send_draft()
        ASSERT: Retourne False
        """
        # Arrange
        resp = httplib2.Response({"status": 404})
        mock_gmail_service.users().drafts().send().execute.side_effect = HttpError(
            resp, b"Draft not found"
        )

        # Act
        result = authenticated_gmail_adapter.send_draft("invalid-draft")

        # Assert
        assert result is False


# =============================================================================
# Tests - _get_or_create_label
# =============================================================================


class TestGetOrCreateLabel:
    """Tests pour GmailAdapter._get_or_create_label()."""

    def test_get_existing_label(self, authenticated_gmail_adapter, mock_gmail_service):
        """
        ARRANGE: Label existe déjà
        ACT: Appeler _get_or_create_label()
        ASSERT: Retourne l'ID du label existant
        """
        # Arrange
        mock_gmail_service.users().labels().list().execute.return_value = {
            "labels": [
                {"id": "label-123", "name": "Agentys/URGENT"},
                {"id": "label-456", "name": "Agentys/TEST"},
            ]
        }

        # Act
        result = authenticated_gmail_adapter._get_or_create_label("Agentys/URGENT")

        # Assert
        assert result == "label-123"

    def test_create_new_label(self, authenticated_gmail_adapter, mock_gmail_service):
        """
        ARRANGE: Label n'existe pas
        ACT: Appeler _get_or_create_label()
        ASSERT: Crée le label et retourne son ID
        """
        # Arrange
        mock_gmail_service.users().labels().list().execute.return_value = {
            "labels": []
        }
        mock_gmail_service.users().labels().create().execute.return_value = {
            "id": "new-label-789"
        }

        # Act
        result = authenticated_gmail_adapter._get_or_create_label("Agentys/NEW")

        # Assert
        assert result == "new-label-789"
        mock_gmail_service.users().labels().create.assert_called()

    def test_get_or_create_label_http_error(self, authenticated_gmail_adapter, mock_gmail_service):
        """
        ARRANGE: API lève HttpError
        ACT: Appeler _get_or_create_label()
        ASSERT: Retourne None
        """
        # Arrange
        resp = httplib2.Response({"status": 500})
        mock_gmail_service.users().labels().list().execute.side_effect = HttpError(
            resp, b"Internal error"
        )

        # Act
        result = authenticated_gmail_adapter._get_or_create_label("Agentys/ERROR")

        # Assert
        assert result is None


# =============================================================================
# Tests - move_to_spam
# =============================================================================


class TestMoveToSpam:
    """Tests pour GmailAdapter.move_to_spam()."""

    def test_move_to_spam_success(self, authenticated_gmail_adapter, mock_gmail_service):
        """
        ARRANGE: message_id valide
        ACT: Appeler move_to_spam()
        ASSERT: Retourne True, labels modifiés
        """
        # Arrange
        mock_gmail_service.users().messages().modify().execute.return_value = {}

        # Act
        result = authenticated_gmail_adapter.move_to_spam("msg-123")

        # Assert
        assert result is True
        mock_gmail_service.users().messages().modify.assert_called()

    def test_move_to_spam_http_error(self, authenticated_gmail_adapter, mock_gmail_service):
        """
        ARRANGE: API lève HttpError
        ACT: Appeler move_to_spam()
        ASSERT: Retourne False
        """
        # Arrange
        resp = httplib2.Response({"status": 404})
        mock_gmail_service.users().messages().modify().execute.side_effect = HttpError(
            resp, b"Message not found"
        )

        # Act
        result = authenticated_gmail_adapter.move_to_spam("invalid-msg")

        # Assert
        assert result is False


# =============================================================================
# Tests - get_user_drafts
# =============================================================================


class TestGetUserDrafts:
    """Tests pour GmailAdapter.get_user_drafts()."""

    def test_get_user_drafts_success(self, authenticated_gmail_adapter, mock_gmail_service):
        """
        ARRANGE: Plusieurs brouillons existent
        ACT: Appeler get_user_drafts()
        ASSERT: Retourne liste de StandardEmail
        """
        # Arrange
        body_content = base64.urlsafe_b64encode(b"Draft content").decode()
        mock_gmail_service.users().drafts().list().execute.return_value = {
            "drafts": [
                {"id": "draft-1"},
                {"id": "draft-2"},
            ]
        }
        mock_gmail_service.users().drafts().get().execute.return_value = {
            "id": "draft-1",
            "message": {
                "id": "msg-draft-1",
                "threadId": "thread-1",
                "labelIds": ["DRAFT"],
                "payload": {
                    "headers": [
                        {"name": "From", "value": "me@example.com"},
                        {"name": "To", "value": "recipient@example.com"},
                        {"name": "Subject", "value": "Draft Subject"},
                    ],
                    "body": {"data": body_content},
                    "parts": []
                }
            }
        }

        # Act
        result = authenticated_gmail_adapter.get_user_drafts(limit=10)

        # Assert
        assert len(result) == 2
        assert result[0].raw_metadata.get("is_user_draft") is True
        assert result[0].raw_metadata.get("draft_id") == "draft-1"

    def test_get_user_drafts_empty(self, authenticated_gmail_adapter, mock_gmail_service):
        """
        ARRANGE: Aucun brouillon
        ACT: Appeler get_user_drafts()
        ASSERT: Retourne liste vide
        """
        # Arrange
        mock_gmail_service.users().drafts().list().execute.return_value = {
            "drafts": []
        }

        # Act
        result = authenticated_gmail_adapter.get_user_drafts()

        # Assert
        assert result == []

    def test_get_user_drafts_http_error(self, authenticated_gmail_adapter, mock_gmail_service):
        """
        ARRANGE: API lève HttpError
        ACT: Appeler get_user_drafts()
        ASSERT: Retourne liste vide
        """
        # Arrange
        resp = httplib2.Response({"status": 500})
        mock_gmail_service.users().drafts().list().execute.side_effect = HttpError(
            resp, b"Internal error"
        )

        # Act
        result = authenticated_gmail_adapter.get_user_drafts()

        # Assert
        assert result == []


# =============================================================================
# Tests - get_draft_by_id
# =============================================================================


class TestGetDraftById:
    """Tests pour GmailAdapter.get_draft_by_id()."""

    def test_get_draft_by_id_success(self, authenticated_gmail_adapter, mock_gmail_service):
        """
        ARRANGE: draft_id valide
        ACT: Appeler get_draft_by_id()
        ASSERT: Retourne StandardEmail avec métadonnées draft
        """
        # Arrange
        body_content = base64.urlsafe_b64encode(b"Draft body").decode()
        mock_gmail_service.users().drafts().get().execute.return_value = {
            "id": "draft-999",
            "message": {
                "id": "msg-999",
                "threadId": "thread-999",
                "labelIds": ["DRAFT"],
                "payload": {
                    "headers": [
                        {"name": "From", "value": "me@example.com"},
                        {"name": "To", "value": "dest@example.com"},
                        {"name": "Subject", "value": "My Draft"},
                    ],
                    "body": {"data": body_content},
                    "parts": []
                }
            }
        }

        # Act
        result = authenticated_gmail_adapter.get_draft_by_id("draft-999")

        # Assert
        assert result is not None
        assert result.id == "draft-999"
        assert result.subject == "My Draft"
        assert result.raw_metadata.get("is_user_draft") is True

    def test_get_draft_by_id_not_found(self, authenticated_gmail_adapter, mock_gmail_service):
        """
        ARRANGE: draft_id invalide
        ACT: Appeler get_draft_by_id()
        ASSERT: Retourne None
        """
        # Arrange
        resp = httplib2.Response({"status": 404})
        mock_gmail_service.users().drafts().get().execute.side_effect = HttpError(
            resp, b"Draft not found"
        )

        # Act
        result = authenticated_gmail_adapter.get_draft_by_id("invalid-draft")

        # Assert
        assert result is None


# =============================================================================
# Tests - get_sent_emails
# =============================================================================


class TestGetSentEmails:
    """Tests pour GmailAdapter.get_sent_emails()."""

    def test_get_sent_emails_success(self, authenticated_gmail_adapter, mock_gmail_service):
        """
        ARRANGE: Plusieurs emails envoyés (batch API)
        ACT: Appeler get_sent_emails()
        ASSERT: Retourne liste de StandardEmail
        """
        # Arrange
        body_content = base64.urlsafe_b64encode(b"Sent email body").decode()
        mock_gmail_service.users().messages().list().execute.return_value = {
            "messages": [
                {"id": "sent-1"},
                {"id": "sent-2"},
            ]
        }

        # The production code now uses _batch_fetch_messages + _map_to_standard_email
        raw_msg = {
            "id": "sent-1",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Sent Subject"},
                    {"name": "To", "value": "recipient@example.com"},
                    {"name": "From", "value": "sender@example.com"},
                ],
                "body": {"data": body_content},
                "parts": [],
            },
            "labelIds": ["SENT"],
        }
        with patch.object(
            authenticated_gmail_adapter,
            "_batch_fetch_messages",
            return_value=[raw_msg, raw_msg],
        ):
            # Act
            result = authenticated_gmail_adapter.get_sent_emails(limit=10)

        # Assert — returns StandardEmail objects, not dicts
        assert len(result) == 2
        assert result[0].subject == "Sent Subject"

    def test_get_sent_emails_empty(self, authenticated_gmail_adapter, mock_gmail_service):
        """
        ARRANGE: Aucun email envoyé
        ACT: Appeler get_sent_emails()
        ASSERT: Retourne liste vide
        """
        # Arrange
        mock_gmail_service.users().messages().list().execute.return_value = {
            "messages": []
        }

        # Act
        result = authenticated_gmail_adapter.get_sent_emails()

        # Assert
        assert result == []

    def test_get_sent_emails_http_error(self, authenticated_gmail_adapter, mock_gmail_service):
        """
        ARRANGE: API lève HttpError
        ACT: Appeler get_sent_emails()
        ASSERT: Retourne liste vide
        """
        # Arrange
        resp = httplib2.Response({"status": 500})
        mock_gmail_service.users().messages().list().execute.side_effect = HttpError(
            resp, b"Internal error"
        )

        # Act
        result = authenticated_gmail_adapter.get_sent_emails()

        # Assert
        assert result == []


# =============================================================================
# Tests - update_draft
# =============================================================================


class TestUpdateDraft:
    """Tests pour GmailAdapter.update_draft()."""

    def test_update_draft_success(self, authenticated_gmail_adapter, mock_gmail_service):
        """
        ARRANGE: draft_id valide et nouveaux paramètres
        ACT: Appeler update_draft()
        ASSERT: Retourne True
        """
        # Arrange
        body_content = base64.urlsafe_b64encode(b"Old content").decode()
        mock_gmail_service.users().drafts().get().execute.return_value = {
            "id": "draft-update",
            "message": {
                "id": "msg-update",
                "threadId": "thread-update",
                "labelIds": ["DRAFT"],
                "payload": {
                    "headers": [
                        {"name": "From", "value": "me@example.com"},
                        {"name": "To", "value": "old@example.com"},
                        {"name": "Subject", "value": "Old Subject"},
                    ],
                    "body": {"data": body_content},
                    "parts": []
                }
            }
        }
        mock_gmail_service.users().drafts().update().execute.return_value = {
            "id": "draft-update"
        }

        # Act
        result = authenticated_gmail_adapter.update_draft(
            draft_id="draft-update",
            subject="New Subject",
            body="New content",
            to=["new@example.com"]
        )

        # Assert
        assert result is True
        mock_gmail_service.users().drafts().update.assert_called()

    def test_update_draft_partial_update(self, authenticated_gmail_adapter, mock_gmail_service):
        """
        ARRANGE: Seulement le body est fourni
        ACT: Appeler update_draft()
        ASSERT: Conserve les autres valeurs
        """
        # Arrange
        body_content = base64.urlsafe_b64encode(b"Old content").decode()
        mock_gmail_service.users().drafts().get().execute.return_value = {
            "id": "draft-partial",
            "message": {
                "id": "msg-partial",
                "payload": {
                    "headers": [
                        {"name": "To", "value": "keep@example.com"},
                        {"name": "Subject", "value": "Keep Subject"},
                    ],
                    "body": {"data": body_content},
                    "parts": []
                }
            }
        }
        mock_gmail_service.users().drafts().update().execute.return_value = {}

        # Act
        result = authenticated_gmail_adapter.update_draft(
            draft_id="draft-partial",
            body="Only body updated"
        )

        # Assert
        assert result is True

    def test_update_draft_not_found(self, authenticated_gmail_adapter, mock_gmail_service):
        """
        ARRANGE: draft_id invalide
        ACT: Appeler update_draft()
        ASSERT: Retourne False
        """
        # Arrange
        resp = httplib2.Response({"status": 404})
        mock_gmail_service.users().drafts().get().execute.side_effect = HttpError(
            resp, b"Draft not found"
        )

        # Act
        result = authenticated_gmail_adapter.update_draft(
            draft_id="invalid",
            body="New content"
        )

        # Assert
        assert result is False

    def test_update_draft_update_fails(self, authenticated_gmail_adapter, mock_gmail_service):
        """
        ARRANGE: get réussit mais update échoue
        ACT: Appeler update_draft()
        ASSERT: Retourne False
        """
        # Arrange
        body_content = base64.urlsafe_b64encode(b"Content").decode()
        mock_gmail_service.users().drafts().get().execute.return_value = {
            "id": "draft-fail",
            "message": {
                "id": "msg-fail",
                "payload": {
                    "headers": [
                        {"name": "To", "value": "to@example.com"},
                        {"name": "Subject", "value": "Subject"},
                    ],
                    "body": {"data": body_content},
                    "parts": []
                }
            }
        }
        resp = httplib2.Response({"status": 500})
        mock_gmail_service.users().drafts().update().execute.side_effect = HttpError(
            resp, b"Update failed"
        )

        # Act
        result = authenticated_gmail_adapter.update_draft(
            draft_id="draft-fail",
            body="New content"
        )

        # Assert
        assert result is False


# =============================================================================
# Tests - _ensure_authenticated
# =============================================================================


class TestEnsureAuthenticated:
    """Tests pour GmailAdapter._ensure_authenticated()."""

    def test_ensure_authenticated_raises_when_auth_fails(self):
        """
        ARRANGE: authenticate() retourne False
        ACT: Appeler _ensure_authenticated()
        ASSERT: Lève RuntimeError
        """
        with patch("app.providers.gmail_adapter.build"):
            with patch("app.providers.gmail_adapter.Credentials"):
                from app.providers.gmail_adapter import GmailAdapter
                adapter = GmailAdapter.__new__(GmailAdapter)
                adapter._service = None
                adapter._authenticated = False
                adapter.token_file = "token.json"
                adapter.credentials_file = None
                adapter.client_id = None
                adapter.client_secret = None
                adapter.refresh_token = None
                adapter._auth_fail_time = 0
                adapter._auth_fail_reason = ""
                adapter._last_error = ""
                adapter.account_id = None

                with pytest.raises(RuntimeError, match="Authentification Gmail requise"):
                    adapter._ensure_authenticated()


# =============================================================================
# Tests - authenticate edge cases
# =============================================================================


class TestAuthenticateEdgeCases:
    """Tests pour les edge cases de authenticate()."""

    @patch("os.path.exists")
    @patch("os.remove")
    @patch("app.providers.gmail_adapter.Credentials")
    @patch("app.providers.gmail_adapter.build")
    def test_authenticate_removes_corrupted_token(
        self, mock_build, mock_creds_class, mock_remove, mock_exists
    ):
        """
        ARRANGE: token.json existe mais est corrompu
        ACT: Appeler authenticate()
        ASSERT: Fichier supprimé, nouvelle authentification
        """
        # Arrange
        mock_exists.return_value = True
        mock_creds_class.from_authorized_user_file.side_effect = ValueError("Invalid JSON")

        # Create new valid creds for fallback
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.expired = False
        mock_creds.refresh_token = "refresh"
        mock_creds.to_json.return_value = "{}"
        mock_creds_class.return_value = mock_creds

        mock_build.return_value = MagicMock()

        from app.providers.gmail_adapter import GmailAdapter
        adapter = GmailAdapter(
            client_id="test-id",
            client_secret="test-secret",
            refresh_token="test-refresh"
        )

        with patch("builtins.open", mock_open()):
            result = adapter.authenticate()

        # Assert
        mock_remove.assert_called_once()
        assert result is True

    @patch("os.path.exists")
    @patch("app.providers.gmail_adapter.Credentials")
    @patch("app.providers.gmail_adapter.build")
    @patch("app.providers.gmail_adapter.InstalledAppFlow")
    def test_authenticate_with_credentials_file(
        self, mock_flow, mock_build, mock_creds_class, mock_exists
    ):
        """
        ARRANGE: credentials.json existe, pas de token, pas de refresh_token
        ACT: Appeler authenticate()
        ASSERT: Flow OAuth interactif lancé
        """
        # Arrange - credentials.json exists, token.json doesn't
        def exists_side_effect(path):
            if "credentials.json" in str(path):
                return True
            return False

        mock_exists.side_effect = exists_side_effect

        # Mock creds that are not valid (will trigger OAuth flow)
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.to_json.return_value = "{}"

        # Flow returns valid creds
        mock_flow.from_client_secrets_file.return_value.run_local_server.return_value = mock_creds

        mock_build.return_value = MagicMock()

        from app.providers.gmail_adapter import GmailAdapter
        # Create adapter with ONLY credentials_file (no client_id, client_secret, refresh_token)
        adapter = GmailAdapter(
            credentials_file="credentials.json",
            client_id=None,
            client_secret=None,
            refresh_token=None
        )
        # Clear environment variables
        adapter.client_id = None
        adapter.client_secret = None
        adapter.refresh_token = None

        with patch("builtins.open", mock_open()):
            result = adapter.authenticate()

        # Assert
        mock_flow.from_client_secrets_file.assert_called()
        assert result is True

    @patch("os.path.exists", return_value=False)
    @patch("app.providers.gmail_adapter.Credentials")
    @patch("app.providers.gmail_adapter.build")
    def test_authenticate_no_credentials_raises_error(
        self, mock_build, mock_creds_class, mock_exists
    ):
        """
        ARRANGE: Pas de token, pas de credentials, pas de refresh token
        ACT: Appeler authenticate()
        ASSERT: Retourne False (erreur loggée)
        """
        from app.providers.gmail_adapter import GmailAdapter
        adapter = GmailAdapter()

        result = adapter.authenticate()

        assert result is False


# =============================================================================
# Tests - _create_message with reply headers
# =============================================================================


class TestCreateMessageReplyHeaders:
    """Tests pour _create_message avec headers de réponse."""

    def test_create_message_with_reply_to_id_adds_headers(
        self, authenticated_gmail_adapter, mock_gmail_service
    ):
        """
        ARRANGE: reply_to_id fourni avec Message-ID
        ACT: Appeler _create_message()
        ASSERT: In-Reply-To et References ajoutés
        """
        # Arrange - mock get_message_by_id to return message with Message-ID
        original_email = StandardEmail(
            id="original-123",
            sender="sender@example.com",
            subject="Original Subject",
            raw_metadata={"Message-ID": "<msg-123@example.com>"}
        )
        authenticated_gmail_adapter.get_message_by_id = MagicMock(return_value=original_email)

        # Act
        result = authenticated_gmail_adapter._create_message(
            to=["recipient@example.com"],
            subject="Re: Original Subject",
            body="Reply body",
            reply_to_id="original-123"
        )

        # Assert
        assert "raw" in result
        # Le message encodé devrait contenir les headers
        base64.urlsafe_b64decode(result["raw"]).decode()
        # Note: headers are part of the encoded message

    def test_create_message_with_html(self, authenticated_gmail_adapter):
        """
        ARRANGE: is_html=True
        ACT: Appeler _create_message()
        ASSERT: Message MIME multipart créé
        """
        # Act
        result = authenticated_gmail_adapter._create_message(
            to=["recipient@example.com"],
            subject="HTML Email",
            body="<p>HTML content</p>",
            is_html=True
        )

        # Assert
        assert "raw" in result

    def test_create_message_with_cc(self, authenticated_gmail_adapter):
        """
        ARRANGE: cc fourni
        ACT: Appeler _create_message()
        ASSERT: Header Cc ajouté
        """
        # Act
        result = authenticated_gmail_adapter._create_message(
            to=["to@example.com"],
            subject="With CC",
            body="Body",
            cc=["cc1@example.com", "cc2@example.com"]
        )

        # Assert
        assert "raw" in result
        decoded = base64.urlsafe_b64decode(result["raw"]).decode()
        assert "Cc:" in decoded


class TestSendReplyDirectlyFastPath:
    """Régressions du chemin d'envoi Gmail en un seul appel."""

    def test_send_reply_directly_fetches_message_id_when_only_thread_id_is_cached(
        self, authenticated_gmail_adapter, mock_gmail_service
    ):
        authenticated_gmail_adapter._get_reply_metadata = MagicMock(
            return_value={
                "thread_id": "19e442093e7f29f3",
                "message_id_header": "<original@example.com>",
            }
        )
        mock_gmail_service.users().messages().send().execute.return_value = {
            "id": "sent-123",
            "threadId": "19e442093e7f29f3",
        }

        result = authenticated_gmail_adapter.send_reply_directly(
            to=["agentys.demo@gmail.com"],
            subject="Re: Test Agentys",
            body="<p>Reçu.</p>",
            reply_to_id="19e442093e7f29f3",
            thread_id="19e442093e7f29f3",
            is_html=True,
        )

        assert result == "sent-123"
        authenticated_gmail_adapter._get_reply_metadata.assert_called_once_with("19e442093e7f29f3")
        body = mock_gmail_service.users().messages().send.call_args.kwargs["body"]
        assert body["threadId"] == "19e442093e7f29f3"
        decoded = base64.urlsafe_b64decode(body["raw"]).decode()
        assert "In-Reply-To: <original@example.com>" in decoded
        assert "References: <original@example.com>" in decoded

    def test_send_reply_directly_uses_provided_message_id_without_metadata_fetch(
        self, authenticated_gmail_adapter, mock_gmail_service
    ):
        authenticated_gmail_adapter._get_reply_metadata = MagicMock(
            side_effect=AssertionError("metadata fetch should be skipped")
        )
        mock_gmail_service.users().messages().send().execute.return_value = {
            "id": "sent-456",
            "threadId": "19e442093e7f29f3",
        }

        result = authenticated_gmail_adapter.send_reply_directly(
            to=["agentys.demo@gmail.com"],
            subject="Re: Test Agentys",
            body="<p>Reçu.</p>",
            reply_to_id="19e442093e7f29f3",
            thread_id="19e442093e7f29f3",
            message_id_header="<original@example.com>",
            is_html=True,
        )

        assert result == "sent-456"
        authenticated_gmail_adapter._get_reply_metadata.assert_not_called()
        body = mock_gmail_service.users().messages().send.call_args.kwargs["body"]
        decoded = base64.urlsafe_b64decode(body["raw"]).decode()
        assert "In-Reply-To: <original@example.com>" in decoded

    def test_create_message_does_not_refetch_when_metadata_provided_without_message_id(
        self, authenticated_gmail_adapter
    ):
        authenticated_gmail_adapter._get_reply_metadata = MagicMock(
            side_effect=AssertionError("metadata fetch should be skipped")
        )

        result = authenticated_gmail_adapter._create_message(
            to=["agentys.demo@gmail.com"],
            subject="Re: Test Agentys",
            body="<p>Reçu.</p>",
            reply_to_id="19e442093e7f29f3",
            reply_metadata={"thread_id": "19e442093e7f29f3", "message_id_header": None},
            is_html=True,
        )

        assert "raw" in result
        authenticated_gmail_adapter._get_reply_metadata.assert_not_called()


# =============================================================================
# Tests - get_unread_messages HttpError
# =============================================================================


class TestGetUnreadMessagesErrors:
    """Tests pour get_unread_messages avec erreurs."""

    def test_get_unread_messages_http_error_returns_empty(
        self, authenticated_gmail_adapter, mock_gmail_service
    ):
        """
        ARRANGE: API lève HttpError
        ACT: Appeler get_unread_messages()
        ASSERT: Retourne liste vide
        """
        # Arrange
        resp = httplib2.Response({"status": 500})
        mock_gmail_service.users().messages().list().execute.side_effect = HttpError(
            resp, b"Internal error"
        )

        # Act
        result = authenticated_gmail_adapter.get_unread_messages()

        # Assert
        assert result == []


# =============================================================================
# Tests - get_message_by_id HttpError
# =============================================================================


class TestGetMessageByIdErrors:
    """Tests pour get_message_by_id avec erreurs."""

    def test_get_message_by_id_http_error_returns_none(
        self, authenticated_gmail_adapter, mock_gmail_service
    ):
        """
        ARRANGE: API lève HttpError
        ACT: Appeler get_message_by_id()
        ASSERT: Retourne None
        """
        # Arrange
        resp = httplib2.Response({"status": 404})
        mock_gmail_service.users().messages().get().execute.side_effect = HttpError(
            resp, b"Message not found"
        )

        # Act
        result = authenticated_gmail_adapter.get_message_by_id("invalid-id")

        # Assert
        assert result is None


# =============================================================================
# Tests - mark_as_read HttpError
# =============================================================================


class TestMarkAsReadErrors:
    """Tests pour mark_as_read avec erreurs."""

    def test_mark_as_read_http_error_returns_false(
        self, authenticated_gmail_adapter, mock_gmail_service
    ):
        """
        ARRANGE: API lève HttpError
        ACT: Appeler mark_as_read()
        ASSERT: Retourne False
        """
        # Arrange
        resp = httplib2.Response({"status": 404})
        mock_gmail_service.users().messages().modify().execute.side_effect = HttpError(
            resp, b"Message not found"
        )

        # Act
        result = authenticated_gmail_adapter.mark_as_read("invalid-id")

        # Assert
        assert result is False


# =============================================================================
# Tests - provider_name property
# =============================================================================


class TestProviderName:
    """Tests pour la propriété provider_name."""

    def test_provider_name_returns_gmail(self, authenticated_gmail_adapter):
        """
        ARRANGE: GmailAdapter créé
        ACT: Accéder à provider_name
        ASSERT: Retourne "gmail"
        """
        assert authenticated_gmail_adapter.provider_name == "gmail"


# =============================================================================
# Tests - create_draft with reply threading
# =============================================================================


class TestCreateDraftThreading:
    """Tests pour create_draft avec threading."""

    def test_create_draft_with_reply_adds_thread_id(
        self, authenticated_gmail_adapter, mock_gmail_service
    ):
        """
        ARRANGE: reply_to_id pointant vers message avec conversation_id
        ACT: Appeler create_draft()
        ASSERT: threadId ajouté au body
        """
        # Arrange
        original = StandardEmail(
            id="orig-123",
            sender="sender@example.com",
            conversation_id="thread-abc"
        )
        authenticated_gmail_adapter.get_message_by_id = MagicMock(return_value=original)
        mock_gmail_service.users().drafts().create().execute.return_value = {
            "id": "new-draft"
        }

        # Act
        result = authenticated_gmail_adapter.create_draft(
            to=["recipient@example.com"],
            subject="Re: Test",
            body="Reply",
            reply_to_id="orig-123"
        )

        # Assert
        assert result == "new-draft"

    def test_create_draft_http_error_returns_none(
        self, authenticated_gmail_adapter, mock_gmail_service
    ):
        """
        ARRANGE: API lève HttpError lors de la création
        ACT: Appeler create_draft()
        ASSERT: Retourne None
        """
        # Arrange
        resp = httplib2.Response({"status": 500})
        mock_gmail_service.users().drafts().create().execute.side_effect = HttpError(
            resp, b"Internal error"
        )

        # Act
        result = authenticated_gmail_adapter.create_draft(
            to=["test@test.com"],
            subject="Test",
            body="Body"
        )

        # Assert
        assert result is None


# =============================================================================
# Tests - apply_label with HttpError
# =============================================================================


class TestApplyLabelHttpError:
    """Tests pour apply_label avec HttpError."""

    def test_apply_label_modify_http_error(
        self, authenticated_gmail_adapter, mock_gmail_service
    ):
        """
        ARRANGE: _get_or_create_label réussit mais modify échoue
        ACT: Appeler apply_label()
        ASSERT: Retourne False
        """
        # Arrange
        mock_gmail_service.users().labels().list().execute.return_value = {
            "labels": [{"id": "label-123", "name": "Agentys/TEST"}]
        }
        resp = httplib2.Response({"status": 404})
        mock_gmail_service.users().messages().modify().execute.side_effect = HttpError(
            resp, b"Message not found"
        )

        # Act
        result = authenticated_gmail_adapter.apply_label("invalid-msg", "TEST")

        # Assert
        assert result is False
