# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests E2E pour le flow OAuth Outlook (Microsoft Graph API).

Ces tests vérifient le flow OAuth réel avec de vrais credentials.
Skippés automatiquement si les credentials ne sont pas configurés.

Pour activer ces tests:
1. Créer une application Azure AD dans Azure Portal
2. Configurer les permissions Microsoft Graph:
   - Mail.Read
   - Mail.ReadWrite
   - Mail.Send
3. Créer un secret client
4. Configurer les variables d'environnement:
   - AZURE_TENANT_ID
   - AZURE_CLIENT_ID
   - AZURE_CLIENT_SECRET
   - OUTLOOK_USER_ID

pytest tests/test_outlook_oauth_e2e.py -v
"""

import os
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

# Skip if azure module is not available
pytest.importorskip("azure.identity", reason="azure-identity not installed")
pytest.importorskip("msgraph", reason="msgraph-sdk not installed")


# ============================================================================
# SKIP CONDITIONS
# ============================================================================

def has_outlook_oauth_credentials() -> bool:
    """Vérifie si les credentials OAuth Outlook sont configurés."""
    return all([
        os.getenv("AZURE_TENANT_ID"),
        os.getenv("AZURE_CLIENT_ID"),
        os.getenv("AZURE_CLIENT_SECRET"),
        os.getenv("OUTLOOK_USER_ID"),
    ])


def has_outlook_device_code_credentials() -> bool:
    """Vérifie si les credentials pour device code flow sont configurés."""
    return all([
        os.getenv("AZURE_TENANT_ID"),
        os.getenv("AZURE_CLIENT_ID"),
        os.getenv("OUTLOOK_USER_ID"),
    ])


skip_no_oauth = pytest.mark.skipif(
    not has_outlook_oauth_credentials(),
    reason="AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, OUTLOOK_USER_ID requis"
)

skip_no_device_code = pytest.mark.skipif(
    not has_outlook_device_code_credentials(),
    reason="AZURE_TENANT_ID, AZURE_CLIENT_ID, OUTLOOK_USER_ID requis pour device code"
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_graph_message():
    """Message Graph API simulé."""
    from msgraph.generated.models.body_type import BodyType

    message = MagicMock()
    message.id = "msg-outlook-e2e-123"
    message.conversation_id = "conv-e2e-456"
    message.subject = "Test E2E Outlook Subject"
    message.is_read = False
    message.has_attachments = False
    message.received_date_time = "2025-01-15T10:30:00Z"
    message.importance = "normal"
    message.categories = []
    message.web_link = "https://outlook.office.com/mail/..."

    # From
    message.from_ = MagicMock()
    message.from_.email_address = MagicMock()
    message.from_.email_address.address = "sender@outlook.com"
    message.from_.email_address.name = "E2E Sender"

    # To recipients
    to_recipient = MagicMock()
    to_recipient.email_address = MagicMock()
    to_recipient.email_address.address = "recipient@company.com"
    message.to_recipients = [to_recipient]

    # CC recipients
    message.cc_recipients = []

    # Body
    message.body = MagicMock()
    message.body.content_type = BodyType.Text
    message.body.content = "Test email body from Outlook E2E"

    return message


@pytest.fixture
def mock_graph_client(mock_graph_message):
    """Client Graph API mocké pour E2E."""
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
        result.id = "draft-outlook-e2e-001"
        return result

    async def mock_patch_message(*args, **kwargs):
        return None

    async def mock_send(*args, **kwargs):
        return None

    async def mock_move(*args, **kwargs):
        return None

    # Configure mocks
    user_mock = MagicMock()
    client.users.by_user_id.return_value = user_mock

    user_mock.messages.get = AsyncMock(side_effect=mock_get_messages)
    user_mock.messages.post = AsyncMock(side_effect=mock_post_message)
    user_mock.messages.by_message_id.return_value.get = AsyncMock(side_effect=mock_get_message)
    user_mock.messages.by_message_id.return_value.patch = AsyncMock(side_effect=mock_patch_message)
    user_mock.messages.by_message_id.return_value.send.post = AsyncMock(side_effect=mock_send)
    user_mock.messages.by_message_id.return_value.move.post = AsyncMock(side_effect=mock_move)
    user_mock.messages.by_message_id.return_value.create_reply.post = AsyncMock(side_effect=mock_post_message)

    # Drafts folder
    drafts_result = MagicMock()
    drafts_result.value = [mock_graph_message]
    user_mock.mail_folders.by_mail_folder_id.return_value.messages.get = AsyncMock(
        return_value=drafts_result
    )

    return client


# ============================================================================
# TESTS OAUTH FLOW - AVEC MOCKS
# ============================================================================

class TestOutlookOAuthFlowMocked:
    """Tests du flow OAuth Outlook avec mocks (toujours exécutés)."""

    @patch("app.providers.outlook_adapter.ClientSecretCredential")
    @patch("app.providers.outlook_adapter.GraphServiceClient")
    def test_oauth_flow_with_client_credentials(
        self, mock_graph_client_class, mock_credential
    ):
        """Flow OAuth avec client credentials (app-only)."""
        mock_graph_client_class.return_value = MagicMock()

        with patch.dict("os.environ", {
            "AZURE_TENANT_ID": "test-tenant-id",
            "AZURE_CLIENT_ID": "test-client-id",
            "AZURE_CLIENT_SECRET": "test-client-secret",
            "OUTLOOK_USER_ID": "user@company.com",
        }):
            from app.providers.outlook_adapter import OutlookAdapter
            adapter = OutlookAdapter()
            result = adapter.authenticate()

        assert result is True
        assert adapter._authenticated is True
        mock_credential.assert_called_once_with(
            tenant_id="test-tenant-id",
            client_id="test-client-id",
            client_secret="test-client-secret"
        )

    @patch("app.providers.outlook_adapter.DeviceCodeCredential")
    @patch("app.providers.outlook_adapter.GraphServiceClient")
    def test_oauth_flow_with_device_code(
        self, mock_graph_client_class, mock_credential
    ):
        """Flow OAuth avec device code (interactif)."""
        mock_graph_client_class.return_value = MagicMock()

        with patch.dict("os.environ", {
            "AZURE_TENANT_ID": "test-tenant-id",
            "AZURE_CLIENT_ID": "test-client-id",
            "OUTLOOK_USER_ID": "user@company.com",
        }):
            from app.providers.outlook_adapter import OutlookAdapter
            adapter = OutlookAdapter(use_device_code=True)
            result = adapter.authenticate()

        assert result is True
        mock_credential.assert_called_once_with(
            tenant_id="test-tenant-id",
            client_id="test-client-id"
        )

    @patch("app.providers.outlook_adapter.ClientSecretCredential")
    @patch("app.providers.outlook_adapter.GraphServiceClient")
    def test_oauth_credentials_from_env(
        self, mock_graph_client_class, mock_credential
    ):
        """Les credentials sont lus depuis les variables d'environnement."""
        mock_graph_client_class.return_value = MagicMock()

        with patch.dict("os.environ", {
            "AZURE_TENANT_ID": "env-tenant",
            "AZURE_CLIENT_ID": "env-client",
            "AZURE_CLIENT_SECRET": "env-secret",
            "OUTLOOK_USER_ID": "env-user@company.com",
        }, clear=False):
            from app.providers.outlook_adapter import OutlookAdapter
            adapter = OutlookAdapter()
            adapter.authenticate()

        mock_credential.assert_called_once_with(
            tenant_id="env-tenant",
            client_id="env-client",
            client_secret="env-secret"
        )

    @patch("app.providers.outlook_adapter.ClientSecretCredential")
    @patch("app.providers.outlook_adapter.GraphServiceClient")
    def test_oauth_uses_correct_scopes_app_only(
        self, mock_graph_client_class, mock_credential
    ):
        """Vérifie les scopes utilisés pour app-only."""
        mock_graph_client_class.return_value = MagicMock()

        with patch.dict("os.environ", {
            "AZURE_TENANT_ID": "tenant",
            "AZURE_CLIENT_ID": "client",
            "AZURE_CLIENT_SECRET": "secret",
            "OUTLOOK_USER_ID": "user@company.com",
        }):
            from app.providers.outlook_adapter import OutlookAdapter
            adapter = OutlookAdapter()
            adapter.authenticate()

        call_args = mock_graph_client_class.call_args
        scopes = call_args.kwargs.get("scopes") or call_args[1].get("scopes")
        assert "https://graph.microsoft.com/.default" in scopes

    @patch("app.providers.outlook_adapter.DeviceCodeCredential")
    @patch("app.providers.outlook_adapter.GraphServiceClient")
    def test_oauth_uses_correct_scopes_device_code(
        self, mock_graph_client_class, mock_credential
    ):
        """Vérifie les scopes utilisés pour device code."""
        mock_graph_client_class.return_value = MagicMock()

        with patch.dict("os.environ", {
            "AZURE_TENANT_ID": "tenant",
            "AZURE_CLIENT_ID": "client",
            "OUTLOOK_USER_ID": "user@company.com",
        }):
            from app.providers.outlook_adapter import OutlookAdapter
            adapter = OutlookAdapter(use_device_code=True)
            adapter.authenticate()

        call_args = mock_graph_client_class.call_args
        scopes = call_args.kwargs.get("scopes") or call_args[1].get("scopes")
        # Device code flow uses specific mail scopes
        assert any("Mail.Read" in s for s in scopes)


# ============================================================================
# TESTS OAUTH FLOW - FULL E2E (nécessite credentials réels)
# ============================================================================

@skip_no_oauth
class TestOutlookOAuthFlowE2E:
    """
    Tests E2E du flow OAuth Outlook avec credentials réels.

    Ces tests font de vrais appels à Microsoft Graph API.
    Skippés si les credentials ne sont pas configurés.
    """

    def test_e2e_authenticate_with_real_credentials(self):
        """Authentification réelle avec OAuth client credentials."""
        from app.providers.outlook_adapter import OutlookAdapter

        adapter = OutlookAdapter()
        result = adapter.authenticate()

        assert result is True
        assert adapter._authenticated is True
        assert adapter._client is not None

    def test_e2e_get_unread_messages_structure(self):
        """Vérifie la structure des messages retournés."""
        from app.providers.outlook_adapter import OutlookAdapter

        adapter = OutlookAdapter()
        adapter.authenticate()

        messages = adapter.get_unread_messages(limit=2)

        for msg in messages:
            assert hasattr(msg, "id")
            assert hasattr(msg, "sender")
            assert hasattr(msg, "subject")
            assert hasattr(msg, "body")
            assert hasattr(msg, "is_read")
            assert msg.provider_source == "outlook"

    def test_e2e_get_user_drafts(self):
        """Récupère les brouillons de l'utilisateur."""
        from app.providers.outlook_adapter import OutlookAdapter

        adapter = OutlookAdapter()
        adapter.authenticate()

        drafts = adapter.get_user_drafts(limit=5)

        for draft in drafts:
            assert draft.raw_metadata.get("is_user_draft") is True
            assert draft.provider_source == "outlook"


# ============================================================================
# TESTS OAUTH ERROR HANDLING
# ============================================================================

class TestOutlookOAuthErrorHandling:
    """Tests de gestion des erreurs OAuth Outlook."""

    @patch("app.providers.outlook_adapter.ClientSecretCredential")
    @patch("app.providers.outlook_adapter.GraphServiceClient")
    def test_handles_invalid_tenant_id(
        self, mock_graph_client_class, mock_credential
    ):
        """Gère un tenant_id invalide."""
        mock_credential.side_effect = Exception("AADSTS90002: Tenant not found")

        with patch.dict("os.environ", {
            "AZURE_TENANT_ID": "invalid-tenant",
            "AZURE_CLIENT_ID": "client",
            "AZURE_CLIENT_SECRET": "secret",
            "OUTLOOK_USER_ID": "user@company.com",
        }):
            from app.providers.outlook_adapter import OutlookAdapter
            adapter = OutlookAdapter()
            result = adapter.authenticate()

        assert result is False
        assert adapter._authenticated is False

    @patch("app.providers.outlook_adapter.ClientSecretCredential")
    @patch("app.providers.outlook_adapter.GraphServiceClient")
    def test_handles_invalid_client_secret(
        self, mock_graph_client_class, mock_credential
    ):
        """Gère un client_secret invalide."""
        mock_credential.side_effect = Exception("AADSTS7000215: Invalid client secret")

        with patch.dict("os.environ", {
            "AZURE_TENANT_ID": "tenant",
            "AZURE_CLIENT_ID": "client",
            "AZURE_CLIENT_SECRET": "wrong-secret",
            "OUTLOOK_USER_ID": "user@company.com",
        }):
            from app.providers.outlook_adapter import OutlookAdapter
            adapter = OutlookAdapter()
            result = adapter.authenticate()

        assert result is False

    @patch("app.providers.outlook_adapter.ClientSecretCredential")
    @patch("app.providers.outlook_adapter.GraphServiceClient")
    def test_handles_network_error(
        self, mock_graph_client_class, mock_credential
    ):
        """Gère une erreur réseau."""
        mock_credential.side_effect = Exception("Connection refused")

        with patch.dict("os.environ", {
            "AZURE_TENANT_ID": "tenant",
            "AZURE_CLIENT_ID": "client",
            "AZURE_CLIENT_SECRET": "secret",
            "OUTLOOK_USER_ID": "user@company.com",
        }):
            from app.providers.outlook_adapter import OutlookAdapter
            adapter = OutlookAdapter()
            result = adapter.authenticate()

        assert result is False

    def test_handles_missing_tenant_id(self):
        """Gère l'absence de tenant_id."""
        with patch.dict("os.environ", {
            "AZURE_CLIENT_ID": "client",
            "AZURE_CLIENT_SECRET": "secret",
        }, clear=True):
            with pytest.raises(ValueError, match="AZURE_TENANT_ID"):
                from app.providers.outlook_adapter import OutlookAdapter
                OutlookAdapter()

    def test_handles_missing_client_secret_app_mode(self):
        """Gère l'absence de client_secret en mode app-only."""
        with patch.dict("os.environ", {
            "AZURE_TENANT_ID": "tenant",
            "AZURE_CLIENT_ID": "client",
        }, clear=True):
            with pytest.raises(ValueError, match="AZURE_CLIENT_SECRET"):
                from app.providers.outlook_adapter import OutlookAdapter
                OutlookAdapter()


# ============================================================================
# TESTS FULL WORKFLOW OAUTH
# ============================================================================

class TestOutlookOAuthWorkflow:
    """Tests du workflow complet OAuth (avec mocks)."""

    @patch("app.providers.outlook_adapter.ClientSecretCredential")
    @patch("app.providers.outlook_adapter.GraphServiceClient")
    def test_complete_workflow_authenticate_list_draft(
        self, mock_graph_client_class, mock_credential, mock_graph_client, mock_graph_message
    ):
        """Workflow complet: auth → list messages → create draft."""
        mock_graph_client_class.return_value = mock_graph_client

        with patch.dict("os.environ", {
            "AZURE_TENANT_ID": "tenant",
            "AZURE_CLIENT_ID": "client",
            "AZURE_CLIENT_SECRET": "secret",
            "OUTLOOK_USER_ID": "user@company.com",
        }):
            from app.providers.outlook_adapter import OutlookAdapter
            adapter = OutlookAdapter()

            # 1. Authenticate
            assert adapter.authenticate() is True

            # 2. Get unread messages
            messages = adapter.get_unread_messages(limit=5)
            assert len(messages) == 1
            assert messages[0].id == "msg-outlook-e2e-123"

            # 3. Create draft reply
            draft_id = adapter.create_draft(
                to=["sender@outlook.com"],
                subject="Re: Test E2E Outlook Subject",
                body="Thanks for your message!",
                reply_to_id="msg-outlook-e2e-123"
            )
            assert draft_id == "draft-outlook-e2e-001"

    @patch("app.providers.outlook_adapter.ClientSecretCredential")
    @patch("app.providers.outlook_adapter.GraphServiceClient")
    def test_workflow_mark_as_read_and_apply_label(
        self, mock_graph_client_class, mock_credential, mock_graph_client, mock_graph_message
    ):
        """Workflow: mark as read → apply category."""
        mock_graph_client_class.return_value = mock_graph_client

        with patch.dict("os.environ", {
            "AZURE_TENANT_ID": "tenant",
            "AZURE_CLIENT_ID": "client",
            "AZURE_CLIENT_SECRET": "secret",
            "OUTLOOK_USER_ID": "user@company.com",
        }):
            from app.providers.outlook_adapter import OutlookAdapter
            adapter = OutlookAdapter()
            adapter.authenticate()

            # Mark as read
            result = adapter.mark_as_read("msg-outlook-e2e-123")
            assert result is True

            # Apply category
            result = adapter.apply_label("msg-outlook-e2e-123", "Traité")
            assert result is True

    @patch("app.providers.outlook_adapter.ClientSecretCredential")
    @patch("app.providers.outlook_adapter.GraphServiceClient")
    def test_workflow_create_and_send_draft(
        self, mock_graph_client_class, mock_credential, mock_graph_client
    ):
        """Workflow: create draft → send draft."""
        mock_graph_client_class.return_value = mock_graph_client

        with patch.dict("os.environ", {
            "AZURE_TENANT_ID": "tenant",
            "AZURE_CLIENT_ID": "client",
            "AZURE_CLIENT_SECRET": "secret",
            "OUTLOOK_USER_ID": "user@company.com",
        }):
            from app.providers.outlook_adapter import OutlookAdapter
            adapter = OutlookAdapter()
            adapter.authenticate()

            # Create draft
            draft_id = adapter.create_draft(
                to=["recipient@example.com"],
                subject="Test Subject",
                body="Test body content"
            )
            assert draft_id is not None

            # Send draft
            result = adapter.send_draft(draft_id)
            assert result is True


# ============================================================================
# TESTS OPERATIONS SPECIFIQUES OUTLOOK
# ============================================================================

class TestOutlookSpecificOperations:
    """Tests des opérations spécifiques à Outlook."""

    @patch("app.providers.outlook_adapter.ClientSecretCredential")
    @patch("app.providers.outlook_adapter.GraphServiceClient")
    def test_move_to_spam(
        self, mock_graph_client_class, mock_credential, mock_graph_client
    ):
        """Déplace un message vers le dossier spam."""
        mock_graph_client_class.return_value = mock_graph_client

        with patch.dict("os.environ", {
            "AZURE_TENANT_ID": "tenant",
            "AZURE_CLIENT_ID": "client",
            "AZURE_CLIENT_SECRET": "secret",
            "OUTLOOK_USER_ID": "user@company.com",
        }):
            from app.providers.outlook_adapter import OutlookAdapter
            adapter = OutlookAdapter()
            adapter.authenticate()

            result = adapter.move_to_spam("msg-outlook-e2e-123")
            assert result is True

    @patch("app.providers.outlook_adapter.ClientSecretCredential")
    @patch("app.providers.outlook_adapter.GraphServiceClient")
    def test_apply_agentys_category(
        self, mock_graph_client_class, mock_credential, mock_graph_client, mock_graph_message
    ):
        """Applique une catégorie Agentys au message."""
        mock_graph_client_class.return_value = mock_graph_client

        with patch.dict("os.environ", {
            "AZURE_TENANT_ID": "tenant",
            "AZURE_CLIENT_ID": "client",
            "AZURE_CLIENT_SECRET": "secret",
            "OUTLOOK_USER_ID": "user@company.com",
        }):
            from app.providers.outlook_adapter import OutlookAdapter
            adapter = OutlookAdapter()
            adapter.authenticate()

            result = adapter.apply_label("msg-outlook-e2e-123", "Processed")
            assert result is True

    @patch("app.providers.outlook_adapter.ClientSecretCredential")
    @patch("app.providers.outlook_adapter.GraphServiceClient")
    def test_get_drafts_folder(
        self, mock_graph_client_class, mock_credential, mock_graph_client, mock_graph_message
    ):
        """Récupère les brouillons du dossier Drafts."""
        mock_graph_client_class.return_value = mock_graph_client

        with patch.dict("os.environ", {
            "AZURE_TENANT_ID": "tenant",
            "AZURE_CLIENT_ID": "client",
            "AZURE_CLIENT_SECRET": "secret",
            "OUTLOOK_USER_ID": "user@company.com",
        }):
            from app.providers.outlook_adapter import OutlookAdapter
            adapter = OutlookAdapter()
            adapter.authenticate()

            drafts = adapter.get_user_drafts(limit=10)
            assert len(drafts) >= 0

    @patch("app.providers.outlook_adapter.ClientSecretCredential")
    @patch("app.providers.outlook_adapter.GraphServiceClient")
    def test_update_draft(
        self, mock_graph_client_class, mock_credential, mock_graph_client, mock_graph_message
    ):
        """Met à jour un brouillon existant."""
        mock_graph_client_class.return_value = mock_graph_client

        with patch.dict("os.environ", {
            "AZURE_TENANT_ID": "tenant",
            "AZURE_CLIENT_ID": "client",
            "AZURE_CLIENT_SECRET": "secret",
            "OUTLOOK_USER_ID": "user@company.com",
        }):
            from app.providers.outlook_adapter import OutlookAdapter
            adapter = OutlookAdapter()
            adapter.authenticate()

            result = adapter.update_draft(
                draft_id="draft-001",
                subject="Updated Subject",
                body="Updated body content"
            )
            assert result is True


# ============================================================================
# TESTS PROVIDER NAME ET METADATA
# ============================================================================

class TestOutlookProviderMetadata:
    """Tests des métadonnées du provider."""

    @patch("app.providers.outlook_adapter.ClientSecretCredential")
    @patch("app.providers.outlook_adapter.GraphServiceClient")
    def test_provider_name(self, mock_graph_client_class, mock_credential):
        """Vérifie le nom du provider."""
        mock_graph_client_class.return_value = MagicMock()

        with patch.dict("os.environ", {
            "AZURE_TENANT_ID": "tenant",
            "AZURE_CLIENT_ID": "client",
            "AZURE_CLIENT_SECRET": "secret",
            "OUTLOOK_USER_ID": "user@company.com",
        }):
            from app.providers.outlook_adapter import OutlookAdapter
            adapter = OutlookAdapter()

        assert adapter.provider_name == "outlook"

    @patch("app.providers.outlook_adapter.ClientSecretCredential")
    @patch("app.providers.outlook_adapter.GraphServiceClient")
    def test_message_metadata_includes_outlook_specific_fields(
        self, mock_graph_client_class, mock_credential, mock_graph_message
    ):
        """Vérifie que les métadonnées Outlook sont présentes."""
        mock_graph_client_class.return_value = MagicMock()

        with patch.dict("os.environ", {
            "AZURE_TENANT_ID": "tenant",
            "AZURE_CLIENT_ID": "client",
            "AZURE_CLIENT_SECRET": "secret",
            "OUTLOOK_USER_ID": "user@company.com",
        }):
            from app.providers.outlook_adapter import OutlookAdapter
            adapter = OutlookAdapter()
            email = adapter._map_to_standard_email(mock_graph_message)

        assert email.raw_metadata is not None
        assert "importance" in email.raw_metadata
        assert "categories" in email.raw_metadata
        assert "web_link" in email.raw_metadata
