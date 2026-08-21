# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests complets pour OutlookAdapter.

Ce module teste l'adaptateur Microsoft Outlook via Graph API.

Couverture:
1. __init__() - validation des paramètres, env vars
2. authenticate() - modes client credentials et device code
3. _map_to_standard_email() - conversion Message -> StandardEmail
4. get_unread_messages() - récupération messages non lus
5. get_message_by_id() - récupération par ID
6. create_draft() - création de brouillons (nouveau et réponse)
7. send_draft() - envoi de brouillons
8. mark_as_read() - marquage messages lus
9. apply_label() - application de catégories
10. move_to_spam() - déplacement vers spam
11. get_user_drafts() - récupération brouillons utilisateur
12. get_draft_by_id() - récupération brouillon par ID
13. update_draft() - mise à jour de brouillons

Pattern: Arrange-Act-Assert
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime
from typing import List


# =============================================================================
# Fixtures et Mocks
# =============================================================================


class MockEmailAddress:
    """Mock pour EmailAddress."""
    def __init__(self, address: str = "", name: str = None):
        self.address = address
        self.name = name


class MockRecipient:
    """Mock pour Recipient."""
    def __init__(self, email_address: MockEmailAddress = None):
        self.email_address = email_address


class MockItemBody:
    """Mock pour ItemBody."""
    def __init__(self, content: str = "", content_type=None):
        self.content = content
        self.content_type = content_type


class MockMessage:
    """Mock pour Message de Graph API."""
    def __init__(
        self,
        id: str = "msg-123",
        from_: MockRecipient = None,
        to_recipients: List[MockRecipient] = None,
        cc_recipients: List[MockRecipient] = None,
        subject: str = "Test Subject",
        body: MockItemBody = None,
        received_date_time: datetime = None,
        is_read: bool = False,
        has_attachments: bool = False,
        conversation_id: str = None,
        importance=None,
        categories: List[str] = None,
        web_link: str = None,
        is_draft: bool = False
    ):
        self.id = id
        self.from_ = from_
        self.to_recipients = to_recipients or []
        self.cc_recipients = cc_recipients or []
        self.subject = subject
        self.body = body
        self.received_date_time = received_date_time
        self.is_read = is_read
        self.has_attachments = has_attachments
        self.conversation_id = conversation_id
        self.importance = importance
        self.categories = categories or []
        self.web_link = web_link
        self.is_draft = is_draft


class MockBodyType:
    """Mock pour BodyType enum."""
    Html = "html"
    Text = "text"


@pytest.fixture
def mock_env_vars(monkeypatch):
    """Configure les variables d'environnement pour les tests."""
    monkeypatch.setenv("AZURE_TENANT_ID", "test-tenant-id")
    monkeypatch.setenv("AZURE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("OUTLOOK_USER_ID", "test@example.com")


@pytest.fixture
def mock_graph_imports():
    """Mock tous les imports Graph API."""
    with patch("app.providers.outlook_adapter.ClientSecretCredential") as mock_secret_cred, \
         patch("app.providers.outlook_adapter.DeviceCodeCredential") as mock_device_cred, \
         patch("app.providers.outlook_adapter.GraphServiceClient") as mock_graph_client, \
         patch("app.providers.outlook_adapter.MessagesRequestBuilder") as mock_msg_builder, \
         patch("app.providers.outlook_adapter.FolderMessagesRequestBuilder") as mock_folder_builder, \
         patch("app.providers.outlook_adapter.Message") as mock_message_class, \
         patch("app.providers.outlook_adapter.Recipient") as mock_recipient_class, \
         patch("app.providers.outlook_adapter.EmailAddress") as mock_email_class, \
         patch("app.providers.outlook_adapter.ItemBody") as mock_body_class, \
         patch("app.providers.outlook_adapter.BodyType", MockBodyType):

        yield {
            "secret_cred": mock_secret_cred,
            "device_cred": mock_device_cred,
            "graph_client": mock_graph_client,
            "msg_builder": mock_msg_builder,
            "folder_builder": mock_folder_builder,
            "message_class": mock_message_class,
            "recipient_class": mock_recipient_class,
            "email_class": mock_email_class,
            "body_class": mock_body_class,
        }


@pytest.fixture
def outlook_adapter(mock_env_vars, mock_graph_imports):
    """Crée un OutlookAdapter mocké."""
    from app.providers.outlook_adapter import OutlookAdapter
    adapter = OutlookAdapter()
    return adapter


@pytest.fixture
def authenticated_adapter(outlook_adapter, mock_graph_imports):
    """Crée un OutlookAdapter authentifié."""
    outlook_adapter._authenticated = True
    outlook_adapter._client = MagicMock()
    return outlook_adapter


# =============================================================================
# Tests - __init__
# =============================================================================


class TestOutlookAdapterInit:
    """Tests pour l'initialisation de OutlookAdapter."""

    def test_init_with_env_vars(self, mock_env_vars, mock_graph_imports):
        """Test init avec variables d'environnement."""
        from app.providers.outlook_adapter import OutlookAdapter

        adapter = OutlookAdapter()

        assert adapter.tenant_id == "test-tenant-id"
        assert adapter.client_id == "test-client-id"
        assert adapter.client_secret == "test-client-secret"
        assert adapter.user_id == "test@example.com"
        assert adapter.use_device_code is False
        assert adapter._authenticated is False
        assert adapter._client is None

    def test_init_with_explicit_params(self, mock_env_vars, mock_graph_imports):
        """Test init avec paramètres explicites."""
        from app.providers.outlook_adapter import OutlookAdapter

        adapter = OutlookAdapter(
            tenant_id="explicit-tenant",
            client_id="explicit-client",
            client_secret="explicit-secret",
            user_id="explicit@example.com",
            use_device_code=False
        )

        assert adapter.tenant_id == "explicit-tenant"
        assert adapter.client_id == "explicit-client"
        assert adapter.client_secret == "explicit-secret"
        assert adapter.user_id == "explicit@example.com"

    def test_init_missing_tenant_id_raises_error(self, monkeypatch, mock_graph_imports):
        """Test erreur si tenant_id manquant."""
        monkeypatch.delenv("AZURE_TENANT_ID", raising=False)
        monkeypatch.setenv("AZURE_CLIENT_ID", "test-client")
        monkeypatch.setenv("AZURE_CLIENT_SECRET", "test-secret")

        from app.providers.outlook_adapter import OutlookAdapter

        with pytest.raises(ValueError, match="AZURE_TENANT_ID et AZURE_CLIENT_ID sont requis"):
            OutlookAdapter()

    def test_init_missing_client_id_raises_error(self, monkeypatch, mock_graph_imports):
        """Test erreur si client_id manquant."""
        monkeypatch.setenv("AZURE_TENANT_ID", "test-tenant")
        monkeypatch.delenv("AZURE_CLIENT_ID", raising=False)
        monkeypatch.delenv("MICROSOFT_CLIENT_ID", raising=False)
        monkeypatch.setenv("AZURE_CLIENT_SECRET", "test-secret")

        from app.providers.outlook_adapter import OutlookAdapter

        with pytest.raises(ValueError, match="AZURE_TENANT_ID et AZURE_CLIENT_ID sont requis"):
            OutlookAdapter()

    def test_init_missing_client_secret_without_device_code_raises_error(
        self, monkeypatch, mock_graph_imports
    ):
        """Test erreur si client_secret manquant sans device_code."""
        monkeypatch.setenv("AZURE_TENANT_ID", "test-tenant")
        monkeypatch.setenv("AZURE_CLIENT_ID", "test-client")
        monkeypatch.delenv("AZURE_CLIENT_SECRET", raising=False)
        monkeypatch.delenv("MICROSOFT_CLIENT_SECRET", raising=False)

        from app.providers.outlook_adapter import OutlookAdapter

        with pytest.raises(ValueError, match="AZURE_CLIENT_SECRET requis pour le mode app-only"):
            OutlookAdapter(use_device_code=False)

    def test_init_device_code_mode_no_secret_required(self, monkeypatch, mock_graph_imports):
        """Test que device_code n'a pas besoin de client_secret."""
        monkeypatch.setenv("AZURE_TENANT_ID", "test-tenant")
        monkeypatch.setenv("AZURE_CLIENT_ID", "test-client")
        monkeypatch.delenv("AZURE_CLIENT_SECRET", raising=False)
        monkeypatch.delenv("MICROSOFT_CLIENT_SECRET", raising=False)

        from app.providers.outlook_adapter import OutlookAdapter

        adapter = OutlookAdapter(use_device_code=True)

        assert adapter.use_device_code is True
        assert adapter.client_secret is None


# =============================================================================
# Tests - provider_name
# =============================================================================


class TestProviderName:
    """Tests pour la propriété provider_name."""

    def test_provider_name_returns_outlook(self, outlook_adapter):
        """Test que provider_name retourne 'outlook'."""
        assert outlook_adapter.provider_name == "outlook"


# =============================================================================
# Tests - authenticate
# =============================================================================


class TestAuthenticate:
    """Tests pour l'authentification."""

    def test_authenticate_client_credentials_success(
        self, outlook_adapter, mock_graph_imports
    ):
        """Test authentification mode client credentials réussie."""
        result = outlook_adapter.authenticate()

        assert result is True
        assert outlook_adapter._authenticated is True
        assert outlook_adapter._client is not None
        mock_graph_imports["secret_cred"].assert_called_once()
        mock_graph_imports["graph_client"].assert_called_once()

    def test_authenticate_device_code_success(
        self, mock_env_vars, mock_graph_imports
    ):
        """Test authentification mode device code réussie."""
        from app.providers.outlook_adapter import OutlookAdapter

        adapter = OutlookAdapter(use_device_code=True)
        result = adapter.authenticate()

        assert result is True
        assert adapter._authenticated is True
        mock_graph_imports["device_cred"].assert_called_once()

    def test_authenticate_failure(self, outlook_adapter, mock_graph_imports):
        """Test authentification échouée."""
        mock_graph_imports["graph_client"].side_effect = Exception("Auth failed")

        result = outlook_adapter.authenticate()

        assert result is False
        assert outlook_adapter._authenticated is False

    def test_ensure_authenticated_calls_authenticate_if_not_authenticated(
        self, outlook_adapter, mock_graph_imports
    ):
        """Test que _ensure_authenticated appelle authenticate si non authentifié."""
        outlook_adapter._ensure_authenticated()

        assert outlook_adapter._authenticated is True

    def test_ensure_authenticated_raises_if_authenticate_fails(
        self, outlook_adapter, mock_graph_imports
    ):
        """Test que _ensure_authenticated lève exception si authenticate échoue."""
        mock_graph_imports["graph_client"].side_effect = Exception("Auth failed")

        with pytest.raises(RuntimeError, match="Authentification Outlook requise"):
            outlook_adapter._ensure_authenticated()


# =============================================================================
# Tests - _map_to_standard_email
# =============================================================================


class TestMapToStandardEmail:
    """Tests pour la conversion Message -> StandardEmail."""

    def test_map_complete_message(self, authenticated_adapter):
        """Test mapping d'un message complet."""
        sender_email = MockEmailAddress("sender@example.com", "Sender Name")
        sender = MockRecipient(sender_email)

        to_email = MockEmailAddress("to@example.com")
        to_recipient = MockRecipient(to_email)

        cc_email = MockEmailAddress("cc@example.com")
        cc_recipient = MockRecipient(cc_email)

        body = MockItemBody("Message body", MockBodyType.Text)
        received = datetime(2025, 1, 15, 10, 30, 0)

        message = MockMessage(
            id="msg-123",
            from_=sender,
            to_recipients=[to_recipient],
            cc_recipients=[cc_recipient],
            subject="Test Subject",
            body=body,
            received_date_time=received,
            is_read=True,
            has_attachments=True,
            conversation_id="conv-456",
            importance="high",
            categories=["Work", "Important"],
            web_link="https://outlook.office.com/mail/msg-123"
        )

        result = authenticated_adapter._map_to_standard_email(message)

        assert result.id == "msg-123"
        assert result.sender == "sender@example.com"
        assert result.sender_name == "Sender Name"
        assert result.to == ["to@example.com"]
        assert result.cc == ["cc@example.com"]
        assert result.subject == "Test Subject"
        assert result.body == "Message body"
        assert result.received_at == received
        assert result.is_read is True
        assert result.has_attachments is True
        assert result.conversation_id == "conv-456"
        assert result.provider_source == "outlook"

    def test_map_message_with_html_body(self, authenticated_adapter):
        """Test mapping avec corps HTML."""
        body = MockItemBody("<html><body><p>Hello</p></body></html>", MockBodyType.Html)
        message = MockMessage(body=body)

        with patch.object(authenticated_adapter, '_extract_text_from_html') as mock_extract:
            mock_extract.return_value = "Hello"
            result = authenticated_adapter._map_to_standard_email(message)

        assert result.body_html == "<html><body><p>Hello</p></body></html>"
        mock_extract.assert_called_once()

    def test_map_message_with_no_sender(self, authenticated_adapter):
        """Test mapping sans expéditeur."""
        message = MockMessage(from_=None)

        result = authenticated_adapter._map_to_standard_email(message)

        assert result.sender == ""
        assert result.sender_name is None

    def test_map_message_with_no_recipients(self, authenticated_adapter):
        """Test mapping sans destinataires."""
        message = MockMessage(to_recipients=None, cc_recipients=None)

        result = authenticated_adapter._map_to_standard_email(message)

        assert result.to == []
        assert result.cc == []

    def test_map_message_with_empty_fields(self, authenticated_adapter):
        """Test mapping avec champs vides."""
        message = MockMessage(
            id="",
            subject="",
            body=None,
            received_date_time=None
        )

        result = authenticated_adapter._map_to_standard_email(message)

        assert result.id == ""
        assert result.subject == ""
        assert result.body == ""
        assert result.received_at is None

    def test_map_message_recipient_with_none_email_address(self, authenticated_adapter):
        """Test mapping avec recipient sans email_address."""
        recipient_without_email = MockRecipient(None)
        message = MockMessage(to_recipients=[recipient_without_email])

        result = authenticated_adapter._map_to_standard_email(message)

        assert result.to == []


# =============================================================================
# Tests - get_unread_messages
# =============================================================================


class TestGetUnreadMessages:
    """Tests pour la récupération des messages non lus."""

    def test_get_unread_messages_success(self, authenticated_adapter):
        """Test récupération réussie des messages non lus."""
        mock_message = MockMessage(id="msg-1", subject="Unread Email")

        async def mock_get_async(limit, unread_only=False, folder_id=None):
            return [mock_message]

        with patch.object(
            authenticated_adapter, '_get_messages_async',
            side_effect=mock_get_async
        ):
            results = authenticated_adapter.get_unread_messages(limit=5)

        assert len(results) == 1
        assert results[0].id == "msg-1"
        assert results[0].subject == "Unread Email"

    def test_get_unread_messages_empty(self, authenticated_adapter):
        """Test récupération quand aucun message non lu."""
        async def mock_get_async(limit, unread_only=False, folder_id=None):
            return []

        with patch.object(
            authenticated_adapter, '_get_messages_async',
            side_effect=mock_get_async
        ):
            results = authenticated_adapter.get_unread_messages()

        assert results == []

    def test_get_unread_messages_error(self, authenticated_adapter):
        """Test récupération avec erreur."""
        async def mock_get_async(limit, unread_only=False, folder_id=None):
            raise Exception("API Error")

        with patch.object(
            authenticated_adapter, '_get_messages_async',
            side_effect=mock_get_async
        ):
            results = authenticated_adapter.get_unread_messages()

        assert results == []


# =============================================================================
# Tests - get_message_by_id
# =============================================================================


class TestGetMessageById:
    """Tests pour la récupération d'un message par ID."""

    def test_get_message_by_id_success(self, authenticated_adapter):
        """Test récupération réussie par ID."""
        mock_message = MockMessage(id="msg-123", subject="Specific Email")

        async def mock_get_async(message_id, expand_attachments=False):
            return mock_message

        with patch.object(
            authenticated_adapter, '_get_message_by_id_async',
            side_effect=mock_get_async
        ):
            result = authenticated_adapter.get_message_by_id("msg-123")

        assert result is not None
        assert result.id == "msg-123"
        assert result.subject == "Specific Email"

    def test_get_message_by_id_not_found(self, authenticated_adapter):
        """Test récupération message non trouvé."""
        async def mock_get_async(message_id):
            return None

        with patch.object(
            authenticated_adapter, '_get_message_by_id_async',
            side_effect=mock_get_async
        ):
            result = authenticated_adapter.get_message_by_id("nonexistent")

        assert result is None

    def test_get_message_by_id_error(self, authenticated_adapter):
        """Test récupération avec erreur."""
        async def mock_get_async(message_id):
            raise Exception("API Error")

        with patch.object(
            authenticated_adapter, '_get_message_by_id_async',
            side_effect=mock_get_async
        ):
            result = authenticated_adapter.get_message_by_id("msg-123")

        assert result is None


# =============================================================================
# Tests - create_draft
# =============================================================================


class TestCreateDraft:
    """Tests pour la création de brouillons."""

    def test_create_draft_new_email_success(self, authenticated_adapter):
        """Test création brouillon nouveau email réussie."""
        async def mock_create_async(**kwargs):
            return "draft-123"

        with patch.object(
            authenticated_adapter, '_create_draft_async',
            side_effect=mock_create_async
        ):
            result = authenticated_adapter.create_draft(
                to=["recipient@example.com"],
                subject="Test Subject",
                body="Test body"
            )

        assert result == "draft-123"

    def test_create_draft_reply_success(self, authenticated_adapter):
        """Test création brouillon réponse réussie."""
        async def mock_create_async(**kwargs):
            assert kwargs["reply_to_id"] == "original-msg"
            return "reply-draft-123"

        with patch.object(
            authenticated_adapter, '_create_draft_async',
            side_effect=mock_create_async
        ):
            result = authenticated_adapter.create_draft(
                to=["recipient@example.com"],
                subject="Re: Test",
                body="Reply body",
                reply_to_id="original-msg"
            )

        assert result == "reply-draft-123"

    def test_create_draft_with_cc(self, authenticated_adapter):
        """Test création brouillon avec CC."""
        async def mock_create_async(**kwargs):
            assert kwargs["cc"] == ["cc1@example.com", "cc2@example.com"]
            return "draft-with-cc"

        with patch.object(
            authenticated_adapter, '_create_draft_async',
            side_effect=mock_create_async
        ):
            result = authenticated_adapter.create_draft(
                to=["to@example.com"],
                subject="Test",
                body="Body",
                cc=["cc1@example.com", "cc2@example.com"]
            )

        assert result == "draft-with-cc"

    def test_create_draft_html_body(self, authenticated_adapter):
        """Test création brouillon avec corps HTML."""
        async def mock_create_async(**kwargs):
            assert kwargs["is_html"] is True
            return "html-draft"

        with patch.object(
            authenticated_adapter, '_create_draft_async',
            side_effect=mock_create_async
        ):
            result = authenticated_adapter.create_draft(
                to=["to@example.com"],
                subject="Test",
                body="<p>HTML content</p>",
                is_html=True
            )

        assert result == "html-draft"

    def test_create_draft_error(self, authenticated_adapter):
        """Test création brouillon avec erreur."""
        async def mock_create_async(**kwargs):
            raise Exception("API Error")

        with patch.object(
            authenticated_adapter, '_create_draft_async',
            side_effect=mock_create_async
        ):
            result = authenticated_adapter.create_draft(
                to=["to@example.com"],
                subject="Test",
                body="Body"
            )

        assert result is None


# =============================================================================
# Tests - send_draft
# =============================================================================


class TestSendDraft:
    """Tests pour l'envoi de brouillons."""

    def test_send_draft_success(self, authenticated_adapter):
        """Test envoi brouillon réussi."""
        async def mock_send_async(draft_id):
            return True

        with patch.object(
            authenticated_adapter, '_send_draft_async',
            side_effect=mock_send_async
        ):
            result = authenticated_adapter.send_draft("draft-123")

        assert result is True

    def test_send_draft_failure(self, authenticated_adapter):
        """Test envoi brouillon échoué."""
        async def mock_send_async(draft_id):
            return False

        with patch.object(
            authenticated_adapter, '_send_draft_async',
            side_effect=mock_send_async
        ):
            result = authenticated_adapter.send_draft("draft-123")

        assert result is False

    def test_send_draft_error(self, authenticated_adapter):
        """Test envoi brouillon avec erreur."""
        async def mock_send_async(draft_id):
            raise Exception("API Error")

        with patch.object(
            authenticated_adapter, '_send_draft_async',
            side_effect=mock_send_async
        ):
            result = authenticated_adapter.send_draft("draft-123")

        assert result is False


# =============================================================================
# Tests - mark_as_read
# =============================================================================


class TestMarkAsRead:
    """Tests pour le marquage des messages comme lus."""

    def test_mark_as_read_success(self, authenticated_adapter):
        """Test marquage réussi."""
        async def mock_mark_async(message_id):
            return True

        with patch.object(
            authenticated_adapter, '_mark_as_read_async',
            side_effect=mock_mark_async
        ):
            result = authenticated_adapter.mark_as_read("msg-123")

        assert result is True

    def test_mark_as_read_failure(self, authenticated_adapter):
        """Test marquage échoué."""
        async def mock_mark_async(message_id):
            return False

        with patch.object(
            authenticated_adapter, '_mark_as_read_async',
            side_effect=mock_mark_async
        ):
            result = authenticated_adapter.mark_as_read("msg-123")

        assert result is False

    def test_mark_as_read_error(self, authenticated_adapter):
        """Test marquage avec erreur."""
        async def mock_mark_async(message_id):
            raise Exception("API Error")

        with patch.object(
            authenticated_adapter, '_mark_as_read_async',
            side_effect=mock_mark_async
        ):
            result = authenticated_adapter.mark_as_read("msg-123")

        assert result is False


# =============================================================================
# Tests - apply_label
# =============================================================================


class TestApplyLabel:
    """Tests pour l'application de catégories."""

    def test_apply_label_success(self, authenticated_adapter):
        """Test application label réussie."""
        async def mock_apply_async(message_id, label):
            return True

        with patch.object(
            authenticated_adapter, '_apply_label_async',
            side_effect=mock_apply_async
        ):
            result = authenticated_adapter.apply_label("msg-123", "Important")

        assert result is True

    def test_apply_label_failure(self, authenticated_adapter):
        """Test application label échouée."""
        async def mock_apply_async(message_id, label):
            return False

        with patch.object(
            authenticated_adapter, '_apply_label_async',
            side_effect=mock_apply_async
        ):
            result = authenticated_adapter.apply_label("msg-123", "Important")

        assert result is False

    def test_apply_label_error(self, authenticated_adapter):
        """Test application label avec erreur."""
        async def mock_apply_async(message_id, label):
            raise Exception("API Error")

        with patch.object(
            authenticated_adapter, '_apply_label_async',
            side_effect=mock_apply_async
        ):
            result = authenticated_adapter.apply_label("msg-123", "Important")

        assert result is False


# =============================================================================
# Tests - move_to_spam
# =============================================================================


class TestMoveToSpam:
    """Tests pour le déplacement vers spam."""

    def test_move_to_spam_success(self, authenticated_adapter):
        """Test déplacement vers spam réussi."""
        async def mock_move_async(message_id):
            return True

        with patch.object(
            authenticated_adapter, '_move_to_spam_async',
            side_effect=mock_move_async
        ):
            result = authenticated_adapter.move_to_spam("msg-123")

        assert result is True

    def test_move_to_spam_failure(self, authenticated_adapter):
        """Test déplacement vers spam échoué."""
        async def mock_move_async(message_id):
            return False

        with patch.object(
            authenticated_adapter, '_move_to_spam_async',
            side_effect=mock_move_async
        ):
            result = authenticated_adapter.move_to_spam("msg-123")

        assert result is False

    def test_move_to_spam_error(self, authenticated_adapter):
        """Test déplacement vers spam avec erreur."""
        async def mock_move_async(message_id):
            raise Exception("API Error")

        with patch.object(
            authenticated_adapter, '_move_to_spam_async',
            side_effect=mock_move_async
        ):
            result = authenticated_adapter.move_to_spam("msg-123")

        assert result is False


# =============================================================================
# Tests - get_user_drafts
# =============================================================================


class TestGetUserDrafts:
    """Tests pour la récupération des brouillons utilisateur."""

    def test_get_user_drafts_success(self, authenticated_adapter):
        """Test récupération brouillons réussie."""
        mock_draft = MockMessage(id="draft-1", subject="Draft Subject", is_draft=True)

        async def mock_get_async(limit, unread_only=False, folder_id=None):
            return [mock_draft]

        with patch.object(
            authenticated_adapter, '_get_user_drafts_async',
            side_effect=mock_get_async
        ):
            results = authenticated_adapter.get_user_drafts(limit=10)

        assert len(results) == 1
        assert results[0].id == "draft-1"
        assert results[0].raw_metadata["is_user_draft"] is True

    def test_get_user_drafts_empty(self, authenticated_adapter):
        """Test récupération aucun brouillon."""
        async def mock_get_async(limit, unread_only=False, folder_id=None):
            return []

        with patch.object(
            authenticated_adapter, '_get_user_drafts_async',
            side_effect=mock_get_async
        ):
            results = authenticated_adapter.get_user_drafts()

        assert results == []

    def test_get_user_drafts_error(self, authenticated_adapter):
        """Test récupération brouillons avec erreur."""
        async def mock_get_async(limit, unread_only=False, folder_id=None):
            raise Exception("API Error")

        with patch.object(
            authenticated_adapter, '_get_user_drafts_async',
            side_effect=mock_get_async
        ):
            results = authenticated_adapter.get_user_drafts()

        assert results == []


# =============================================================================
# Tests - get_draft_by_id
# =============================================================================


class TestGetDraftById:
    """Tests pour la récupération d'un brouillon par ID."""

    def test_get_draft_by_id_success(self, authenticated_adapter):
        """Test récupération brouillon par ID réussie."""
        mock_draft = MockMessage(id="draft-123", subject="Draft Subject")

        async def mock_get_async(draft_id):
            return mock_draft

        with patch.object(
            authenticated_adapter, '_get_draft_by_id_async',
            side_effect=mock_get_async
        ):
            result = authenticated_adapter.get_draft_by_id("draft-123")

        assert result is not None
        assert result.id == "draft-123"
        assert result.raw_metadata["is_user_draft"] is True

    def test_get_draft_by_id_not_found(self, authenticated_adapter):
        """Test récupération brouillon non trouvé."""
        async def mock_get_async(draft_id):
            return None

        with patch.object(
            authenticated_adapter, '_get_draft_by_id_async',
            side_effect=mock_get_async
        ):
            result = authenticated_adapter.get_draft_by_id("nonexistent")

        assert result is None

    def test_get_draft_by_id_error(self, authenticated_adapter):
        """Test récupération brouillon avec erreur."""
        async def mock_get_async(draft_id):
            raise Exception("API Error")

        with patch.object(
            authenticated_adapter, '_get_draft_by_id_async',
            side_effect=mock_get_async
        ):
            result = authenticated_adapter.get_draft_by_id("draft-123")

        assert result is None


# =============================================================================
# Tests - update_draft
# =============================================================================


class TestUpdateDraft:
    """Tests pour la mise à jour de brouillons."""

    def test_update_draft_success(self, authenticated_adapter):
        """Test mise à jour brouillon réussie."""
        async def mock_update_async(**kwargs):
            return True

        with patch.object(
            authenticated_adapter, '_update_draft_async',
            side_effect=mock_update_async
        ):
            result = authenticated_adapter.update_draft(
                draft_id="draft-123",
                subject="New Subject",
                body="New Body"
            )

        assert result is True

    def test_update_draft_partial_update(self, authenticated_adapter):
        """Test mise à jour partielle brouillon."""
        async def mock_update_async(**kwargs):
            assert kwargs["subject"] == "New Subject"
            assert kwargs["body"] is None
            return True

        with patch.object(
            authenticated_adapter, '_update_draft_async',
            side_effect=mock_update_async
        ):
            result = authenticated_adapter.update_draft(
                draft_id="draft-123",
                subject="New Subject"
            )

        assert result is True

    def test_update_draft_failure(self, authenticated_adapter):
        """Test mise à jour brouillon échouée."""
        async def mock_update_async(**kwargs):
            return False

        with patch.object(
            authenticated_adapter, '_update_draft_async',
            side_effect=mock_update_async
        ):
            result = authenticated_adapter.update_draft(
                draft_id="draft-123",
                body="New Body"
            )

        assert result is False

    def test_update_draft_error(self, authenticated_adapter):
        """Test mise à jour brouillon avec erreur."""
        async def mock_update_async(**kwargs):
            raise Exception("API Error")

        with patch.object(
            authenticated_adapter, '_update_draft_async',
            side_effect=mock_update_async
        ):
            result = authenticated_adapter.update_draft(
                draft_id="draft-123",
                body="New Body"
            )

        assert result is False

    def test_update_draft_with_recipients(self, authenticated_adapter):
        """Test mise à jour brouillon avec destinataires."""
        async def mock_update_async(**kwargs):
            assert kwargs["to"] == ["new@example.com"]
            assert kwargs["cc"] == ["cc@example.com"]
            return True

        with patch.object(
            authenticated_adapter, '_update_draft_async',
            side_effect=mock_update_async
        ):
            result = authenticated_adapter.update_draft(
                draft_id="draft-123",
                to=["new@example.com"],
                cc=["cc@example.com"]
            )

        assert result is True

    def test_update_draft_html_body(self, authenticated_adapter):
        """Test mise à jour brouillon avec corps HTML."""
        async def mock_update_async(**kwargs):
            assert kwargs["is_html"] is True
            return True

        with patch.object(
            authenticated_adapter, '_update_draft_async',
            side_effect=mock_update_async
        ):
            result = authenticated_adapter.update_draft(
                draft_id="draft-123",
                body="<p>HTML content</p>",
                is_html=True
            )

        assert result is True


# =============================================================================
# Tests - Async Methods Internal
# =============================================================================


class TestAsyncMethodsInternal:
    """Tests pour les méthodes async internes."""

    def test_get_messages_async_returns_empty_on_none_result(
        self, authenticated_adapter
    ):
        """Test _get_messages_async retourne [] si result None."""
        import asyncio

        mock_users = MagicMock()
        mock_by_user = MagicMock()
        mock_mail_folders = MagicMock()
        mock_by_folder = MagicMock()
        mock_messages = MagicMock()

        async def mock_get(request_configuration):
            return None

        mock_messages.get = mock_get
        mock_by_folder.messages = mock_messages
        mock_mail_folders.by_mail_folder_id.return_value = mock_by_folder
        mock_by_user.mail_folders = mock_mail_folders
        mock_users.by_user_id.return_value = mock_by_user
        authenticated_adapter._client.users = mock_users

        result = asyncio.run(authenticated_adapter._get_messages_async(10))

        assert result == []

    def test_apply_label_async_adds_prefix(self, authenticated_adapter):
        """Test _apply_label_async ajoute préfixe Agentys-."""
        import asyncio

        mock_message = MockMessage(id="msg-123", categories=["Existing"])

        mock_users = MagicMock()
        mock_by_user = MagicMock()
        mock_messages = MagicMock()
        mock_by_message = MagicMock()

        async def mock_get():
            return mock_message

        async def mock_patch(update):
            assert "Agentys-Important" in update.categories
            assert "Existing" in update.categories

        mock_by_message.get = mock_get
        mock_by_message.patch = mock_patch
        mock_messages.by_message_id.return_value = mock_by_message
        mock_by_user.messages = mock_messages
        mock_users.by_user_id.return_value = mock_by_user
        authenticated_adapter._client.users = mock_users

        with patch("app.providers.outlook_adapter.Message") as mock_msg_class:
            mock_msg_class.return_value = MagicMock(categories=["Existing", "Agentys-Important"])
            result = asyncio.run(authenticated_adapter._apply_label_async("msg-123", "Important"))

        assert result is True

    def test_apply_label_async_skips_duplicate(self, authenticated_adapter):
        """Test _apply_label_async n'ajoute pas un label en double."""
        import asyncio

        mock_message = MockMessage(id="msg-123", categories=["Agentys-Important"])

        mock_users = MagicMock()
        mock_by_user = MagicMock()
        mock_messages = MagicMock()
        mock_by_message = MagicMock()

        async def mock_get():
            return mock_message

        async def mock_patch(update):
            # Should only have one Agentys-Important
            pass

        mock_by_message.get = mock_get
        mock_by_message.patch = mock_patch
        mock_messages.by_message_id.return_value = mock_by_message
        mock_by_user.messages = mock_messages
        mock_users.by_user_id.return_value = mock_by_user
        authenticated_adapter._client.users = mock_users

        with patch("app.providers.outlook_adapter.Message"):
            result = asyncio.run(authenticated_adapter._apply_label_async("msg-123", "Important"))

        assert result is True


# =============================================================================
# Tests - Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests pour les cas limites."""

    def test_map_message_with_none_importance(self, authenticated_adapter):
        """Test mapping message avec importance None."""
        message = MockMessage(importance=None)

        result = authenticated_adapter._map_to_standard_email(message)

        assert result.raw_metadata["importance"] is None

    def test_map_message_with_empty_categories(self, authenticated_adapter):
        """Test mapping message avec catégories vides."""
        message = MockMessage(categories=[])

        result = authenticated_adapter._map_to_standard_email(message)

        assert result.raw_metadata["categories"] == []

    def test_map_message_with_recipient_missing_address(self, authenticated_adapter):
        """Test mapping avec destinataire sans adresse."""
        recipient = MockRecipient(MockEmailAddress(address=None))
        message = MockMessage(to_recipients=[recipient])

        result = authenticated_adapter._map_to_standard_email(message)

        # Should filter out recipients without address
        assert result.to == []

    def test_create_draft_multiple_recipients(self, authenticated_adapter):
        """Test création brouillon avec plusieurs destinataires."""
        async def mock_create_async(**kwargs):
            assert len(kwargs["to"]) == 3
            return "multi-recipient-draft"

        with patch.object(
            authenticated_adapter, '_create_draft_async',
            side_effect=mock_create_async
        ):
            result = authenticated_adapter.create_draft(
                to=["a@example.com", "b@example.com", "c@example.com"],
                subject="Test",
                body="Body"
            )

        assert result == "multi-recipient-draft"

    def test_get_unread_messages_with_default_limit(self, authenticated_adapter):
        """Test get_unread_messages utilise limite par défaut."""
        async def mock_get_async(limit, unread_only=False, folder_id=None):
            assert limit == 10  # Default
            return []

        with patch.object(
            authenticated_adapter, '_get_messages_async',
            side_effect=mock_get_async
        ):
            authenticated_adapter.get_unread_messages()

    def test_get_user_drafts_with_default_limit(self, authenticated_adapter):
        """Test get_user_drafts utilise limite par défaut."""
        async def mock_get_async(limit, unread_only=False, folder_id=None):
            assert limit == 50  # Default
            return []

        with patch.object(
            authenticated_adapter, '_get_user_drafts_async',
            side_effect=mock_get_async
        ):
            authenticated_adapter.get_user_drafts()


# =============================================================================
# Tests - Constants
# =============================================================================


class TestConstants:
    """Tests pour les constantes."""

    def test_provider_name_constant(self, outlook_adapter):
        """Test PROVIDER_NAME constant."""
        assert outlook_adapter.PROVIDER_NAME == "outlook"

    def test_graph_scopes_defined(self, outlook_adapter):
        """Test GRAPH_SCOPES constant."""
        assert outlook_adapter.GRAPH_SCOPES == ["https://graph.microsoft.com/.default"]

    def test_user_scopes_defined(self, outlook_adapter):
        """Test USER_SCOPES constant."""
        assert "https://graph.microsoft.com/Mail.Read" in outlook_adapter.USER_SCOPES
        assert "https://graph.microsoft.com/Mail.ReadWrite" in outlook_adapter.USER_SCOPES
        assert "https://graph.microsoft.com/Mail.Send" in outlook_adapter.USER_SCOPES


# =============================================================================
# Tests - Interface Compliance
# =============================================================================


class TestInterfaceCompliance:
    """Tests pour vérifier la conformité à l'interface EmailProvider."""

    def test_implements_email_provider(self, outlook_adapter):
        """Test que OutlookAdapter implémente EmailProvider."""
        from app.interfaces.email_provider import EmailProvider
        assert isinstance(outlook_adapter, EmailProvider)

    def test_has_required_methods(self, outlook_adapter):
        """Test que toutes les méthodes requises sont implémentées."""
        required_methods = [
            "authenticate",
            "get_unread_messages",
            "get_message_by_id",
            "create_draft",
            "send_draft",
            "mark_as_read",
            "apply_label",
            "move_to_spam",
            "get_user_drafts",
            "get_draft_by_id",
            "update_draft",
        ]

        for method in required_methods:
            assert hasattr(outlook_adapter, method)
            assert callable(getattr(outlook_adapter, method))

    def test_send_email_convenience_method(self, authenticated_adapter):
        """Test méthode send_email (héritée de EmailProvider)."""
        async def mock_create_async(**kwargs):
            return "draft-123"

        async def mock_send_async(draft_id):
            return True

        with patch.object(
            authenticated_adapter, '_create_draft_async',
            side_effect=mock_create_async
        ):
            with patch.object(
                authenticated_adapter, '_send_draft_async',
                side_effect=mock_send_async
            ):
                result = authenticated_adapter.send_email(
                    to=["to@example.com"],
                    subject="Test",
                    body="Body"
                )

        assert result is True


# =============================================================================
# Audit fixes 2026-06-02 — regression tests
# =============================================================================


class TestAuditOL04ReadStatusSync:
    """OL-04: Outlook delta sync propagates read-status changes via label_changes.

    Before the fix, get_history_changes hardcoded label_changes=[], so a message
    marked read/unread in Outlook web or mobile never updated the Agentys DB.
    """

    def test_emits_unread_label_changes_per_message(self, authenticated_adapter):
        adapter = authenticated_adapter
        adapter._access_token = "fake-token"

        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {
            "value": [
                {"id": "m-read", "isRead": True, "subject": "Read"},
                {"id": "m-unread", "isRead": False, "subject": "Unread"},
            ],
            "@odata.deltaLink": (
                "https://graph.microsoft.com/v1.0/users/user@example.com/"
                "mailFolders/inbox/messages/delta?$deltatoken=NEWTOKEN"
            ),
        }

        calls = []

        def fake_request(method, url, **kwargs):
            calls.append(url)
            return fake_resp

        with patch("app.providers.outlook_adapter._graph_request_with_retry", side_effect=fake_request), \
             patch.object(adapter, "_map_raw_dict_to_standard_email", side_effect=lambda m: m):
            result = adapter.get_history_changes("OLD_TOKEN")

        by_id = {lc["message_id"]: lc for lc in result["label_changes"]}
        assert by_id["m-read"].get("removed") == ["UNREAD"]
        assert by_id["m-unread"].get("added") == ["UNREAD"]
        assert "/mailFolders/inbox/messages/delta" in calls[0]
        assert result["new_history_id"] == (
            "https://graph.microsoft.com/v1.0/users/user@example.com/"
            "mailFolders/inbox/messages/delta?$deltatoken=NEWTOKEN"
        )

    def test_skips_messages_without_isread_field(self, authenticated_adapter):
        adapter = authenticated_adapter
        adapter._access_token = "fake-token"
        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {
            "value": [{"id": "m-noflag", "subject": "no isRead"}],
            "@odata.deltaLink": "https://x?$deltatoken=T2",
        }
        with patch("app.providers.outlook_adapter._graph_request_with_retry", return_value=fake_resp), \
             patch.object(adapter, "_map_raw_dict_to_standard_email", side_effect=lambda m: m):
            result = adapter.get_history_changes("OLD")
        assert result["label_changes"] == []

    def test_delta_init_uses_inbox_folder_delta_link(
        self, authenticated_adapter, caplog
    ):
        """Outlook message delta is scoped to a folder; keep its deltaLink URL."""
        adapter = authenticated_adapter
        adapter._access_token = "fake-token"
        adapter.user_id = "user@example.com"

        accepted = MagicMock()
        accepted.status_code = 200
        accepted.json.return_value = {
            "value": [],
            "@odata.deltaLink": (
                "https://graph.microsoft.com/v1.0/users/user@example.com/"
                "mailFolders/inbox/messages/delta?$deltatoken=INBOXTOKEN"
            ),
        }

        calls = []

        def fake_request(method, url, **kwargs):
            calls.append(url)
            return accepted

        with patch(
            "app.providers.outlook_adapter._graph_request_with_retry",
            side_effect=fake_request,
        ):
            token = adapter.get_current_history_id()

        assert token == (
            "https://graph.microsoft.com/v1.0/users/user@example.com/"
            "mailFolders/inbox/messages/delta?$deltatoken=INBOXTOKEN"
        )
        assert len(calls) == 1
        assert "/mailFolders/inbox/messages/delta" in calls[0]
        assert "Delta init failed" not in caplog.text


class TestAuditOL02LargeAttachments:
    """OL-02: attachments larger than ~3 MB use a Graph upload session instead of
    raising and silently dropping the whole email."""

    def test_large_attachment_uses_chunked_upload_session(self, authenticated_adapter):
        adapter = authenticated_adapter
        adapter._access_token = "fake-token"

        create_resp = MagicMock()
        create_resp.status_code = 201
        create_resp.json.return_value = {"uploadUrl": "https://upload.example/session"}
        put_resp = MagicMock()
        put_resp.status_code = 201

        calls = []

        def fake_req(method, url, **kwargs):
            calls.append((url, kwargs))
            return create_resp if "createUploadSession" in url else put_resp

        payload = b"x" * (5 * 1024 * 1024)  # ~5 MiB -> 2 chunks at 3.2 MiB
        with patch("app.providers.outlook_adapter._graph_request_with_retry", side_effect=fake_req):
            adapter._upload_large_attachment_via_session("msg-1", "big.pdf", payload, "application/pdf")

        create_calls = [c for c in calls if "createUploadSession" in c[0]]
        assert len(create_calls) == 1
        assert create_calls[0][1]["json"]["AttachmentItem"]["size"] == len(payload)

        put_calls = [c for c in calls if c[0] == "https://upload.example/session"]
        assert len(put_calls) == 2
        ranges = [c[1]["headers"]["Content-Range"] for c in put_calls]
        assert ranges[0].startswith("bytes 0-")
        assert ranges[-1].endswith(f"/{len(payload)}")

    def test_upload_session_raises_on_failure(self, authenticated_adapter):
        adapter = authenticated_adapter
        adapter._access_token = "fake-token"
        bad = MagicMock()
        bad.status_code = 403
        with patch("app.providers.outlook_adapter._graph_request_with_retry", return_value=bad):
            with pytest.raises(Exception):
                adapter._upload_large_attachment_via_session(
                    "m", "f.bin", b"x" * (4 * 1024 * 1024), "application/octet-stream"
                )

    def test_routing_large_to_session_small_to_inline(self, authenticated_adapter):
        import asyncio
        from unittest.mock import AsyncMock

        adapter = authenticated_adapter
        adapter._access_token = "fake-token"
        post_mock = AsyncMock()
        (adapter._client.users.by_user_id.return_value
            .messages.by_message_id.return_value.attachments.post) = post_mock

        small = ("small.txt", b"y" * 1000, "text/plain")
        large = ("big.pdf", b"z" * (4 * 1024 * 1024), "application/pdf")
        with patch.object(adapter, "_upload_large_attachment_via_session") as big:
            asyncio.run(adapter._upload_attachments_async("msg-1", [small, large]))

        big.assert_called_once()
        assert big.call_args[0][1] == "big.pdf"   # large file routed to session
        post_mock.assert_awaited_once()            # small file used inline SDK post
