# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests E2E pour le flow OAuth Gmail complet.

Ces tests vérifient le flow OAuth réel avec de vrais credentials.
Skippés automatiquement si les credentials ne sont pas configurés.

Pour activer ces tests:
1. Créer un projet Google Cloud Console
2. Activer l'API Gmail
3. Créer des credentials OAuth 2.0
4. Configurer les variables d'environnement:
   - GOOGLE_CLIENT_ID
   - GOOGLE_CLIENT_SECRET
   - GOOGLE_REFRESH_TOKEN (obtenu via le premier flow OAuth)

pytest tests/test_gmail_oauth_e2e.py -v
"""

import os
import pytest
from unittest.mock import MagicMock, patch

from app.providers.gmail_adapter import GmailAdapter


# ============================================================================
# SKIP CONDITIONS
# ============================================================================

def has_gmail_oauth_credentials() -> bool:
    """Vérifie si les credentials OAuth Gmail sont configurés."""
    return all([
        os.getenv("GOOGLE_CLIENT_ID"),
        os.getenv("GOOGLE_CLIENT_SECRET"),
        os.getenv("GOOGLE_REFRESH_TOKEN"),
    ])


def has_gmail_credentials_file() -> bool:
    """Vérifie si le fichier credentials.json existe."""
    creds_file = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
    return os.path.exists(creds_file)


skip_no_oauth = pytest.mark.skipif(
    not has_gmail_oauth_credentials(),
    reason="GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN requis"
)

skip_no_credentials_file = pytest.mark.skipif(
    not has_gmail_credentials_file(),
    reason="Fichier credentials.json requis"
)


# ============================================================================
# TESTS OAUTH FLOW - AVEC MOCKS
# ============================================================================

class TestGmailOAuthFlowMocked:
    """Tests du flow OAuth Gmail avec mocks (toujours exécutés)."""

    @patch("builtins.open", MagicMock())
    @patch("os.path.exists", return_value=False)
    @patch("app.providers.gmail_adapter._build_authorized_http", return_value=None)
    @patch("app.providers.gmail_adapter.Credentials")
    @patch("app.providers.gmail_adapter.build")
    def test_oauth_flow_with_refresh_token(
        self, mock_build, mock_creds_class, mock_authed_http, mock_exists
    ):
        """Flow OAuth avec refresh token pré-existant."""
        # Setup mock credentials
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.expired = False
        mock_creds.refresh_token = "mock-refresh-token"
        mock_creds.to_json.return_value = '{"token": "mock"}'
        mock_creds_class.return_value = mock_creds

        # Setup mock service
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        # Test
        with patch.dict("os.environ", {
            "GOOGLE_CLIENT_ID": "test-client-id.apps.googleusercontent.com",
            "GOOGLE_CLIENT_SECRET": "test-client-secret",
            "GOOGLE_REFRESH_TOKEN": "1//test-refresh-token"
        }):
            adapter = GmailAdapter()
            result = adapter.authenticate()

        assert result is True
        assert adapter._authenticated is True
        # _build_authorized_http patché → None → fallback legacy build(..., credentials=creds)
        mock_build.assert_called_once_with("gmail", "v1", credentials=mock_creds)

    @patch("builtins.open", MagicMock())
    @patch("os.path.exists", return_value=False)
    @patch("app.providers.gmail_adapter.Credentials")
    @patch("app.providers.gmail_adapter.build")
    @patch("app.providers.gmail_adapter.Request")
    def test_oauth_flow_refreshes_expired_token(
        self, mock_request, mock_build, mock_creds_class, mock_exists
    ):
        """Flow OAuth rafraîchit un token expiré."""
        # Setup mock credentials - token expiré mais avec refresh_token valide
        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds.refresh_token = "mock-refresh-token"
        mock_creds.to_json.return_value = '{"token": "refreshed"}'

        # Après refresh(), le token devient valide
        def refresh_side_effect(*args):
            mock_creds.valid = True
            mock_creds.expired = False

        mock_creds.refresh.side_effect = refresh_side_effect
        mock_creds_class.return_value = mock_creds

        mock_build.return_value = MagicMock()

        # Test
        with patch.dict("os.environ", {
            "GOOGLE_CLIENT_ID": "test-client-id.apps.googleusercontent.com",
            "GOOGLE_CLIENT_SECRET": "test-client-secret",
            "GOOGLE_REFRESH_TOKEN": "1//test-refresh-token"
        }):
            adapter = GmailAdapter()
            result = adapter.authenticate()

        assert result is True
        mock_creds.refresh.assert_called_once()

    @patch("builtins.open", MagicMock())
    @patch("os.path.exists", return_value=False)
    @patch("app.providers.gmail_adapter.Credentials")
    @patch("app.providers.gmail_adapter.build")
    def test_oauth_credentials_from_env(
        self, mock_build, mock_creds_class, mock_exists
    ):
        """Les credentials sont lus depuis les variables d'environnement."""
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.refresh_token = "env-refresh"
        mock_creds.to_json.return_value = "{}"
        mock_creds_class.return_value = mock_creds
        mock_build.return_value = MagicMock()

        with patch.dict("os.environ", {
            "GOOGLE_CLIENT_ID": "env-client-id",
            "GOOGLE_CLIENT_SECRET": "env-secret",
            "GOOGLE_REFRESH_TOKEN": "env-refresh"
        }, clear=False):
            adapter = GmailAdapter()
            adapter.authenticate()

        mock_creds_class.assert_called_once()
        call_kwargs = mock_creds_class.call_args.kwargs
        assert call_kwargs["client_id"] == "env-client-id"
        assert call_kwargs["client_secret"] == "env-secret"
        assert call_kwargs["refresh_token"] == "env-refresh"

    @patch("builtins.open", MagicMock())
    @patch("os.path.exists", return_value=False)
    @patch("app.providers.gmail_adapter.Credentials")
    def test_oauth_fails_without_credentials(
        self, mock_creds_class, mock_exists
    ):
        """L'authentification échoue sans credentials."""
        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds.refresh_token = None
        mock_creds_class.return_value = mock_creds

        # Clear environment variables
        with patch.dict("os.environ", {}, clear=True):
            adapter = GmailAdapter()
            result = adapter.authenticate()

        assert result is False

    @patch("builtins.open", MagicMock())
    @patch("os.path.exists")
    @patch("app.providers.gmail_adapter.Credentials")
    @patch("app.providers.gmail_adapter.build")
    def test_oauth_uses_cached_token_file(
        self, mock_build, mock_creds_class, mock_exists
    ):
        """Utilise le token.json s'il existe."""
        mock_exists.side_effect = lambda path: path == "token.json"

        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.expired = False
        mock_creds.refresh_token = "cached-token"
        mock_creds.to_json.return_value = "{}"

        # Mock Credentials.from_authorized_user_file
        mock_creds_class.from_authorized_user_file.return_value = mock_creds
        mock_build.return_value = MagicMock()

        adapter = GmailAdapter(token_file="token.json")
        result = adapter.authenticate()

        assert result is True
        mock_creds_class.from_authorized_user_file.assert_called_once()


# ============================================================================
# TESTS OAUTH FLOW - FULL E2E (nécessite credentials réels)
# ============================================================================

@skip_no_oauth
class TestGmailOAuthFlowE2E:
    """
    Tests E2E du flow OAuth Gmail avec credentials réels.

    Ces tests font de vrais appels à l'API Google.
    Skippés si les credentials ne sont pas configurés.
    """

    def test_e2e_authenticate_with_real_credentials(self):
        """Authentification réelle avec OAuth."""
        adapter = GmailAdapter()
        result = adapter.authenticate()

        assert result is True
        assert adapter._authenticated is True
        assert adapter._service is not None

    def test_e2e_get_profile(self):
        """Récupère le profil utilisateur après authentification."""
        adapter = GmailAdapter()
        adapter.authenticate()

        # L'API Gmail retourne le profil utilisateur
        profile = adapter._service.users().getProfile(userId="me").execute()

        assert "emailAddress" in profile
        assert "@" in profile["emailAddress"]

    def test_e2e_list_labels(self):
        """Liste les labels Gmail."""
        adapter = GmailAdapter()
        adapter.authenticate()

        results = adapter._service.users().labels().list(userId="me").execute()
        labels = results.get("labels", [])

        # Gmail a toujours des labels par défaut
        assert len(labels) > 0
        label_names = [label.get("name") for label in labels]
        assert "INBOX" in label_names or any("INBOX" in str(n) for n in label_names)

    def test_e2e_get_unread_messages_structure(self):
        """Vérifie la structure des messages retournés."""
        adapter = GmailAdapter()
        adapter.authenticate()

        # Récupérer jusqu'à 2 messages (évite les gros volumes)
        messages = adapter.get_unread_messages(limit=2)

        # Peut être vide si pas de messages non lus
        for msg in messages:
            # Vérifier la structure StandardEmail
            assert hasattr(msg, "id")
            assert hasattr(msg, "sender")
            assert hasattr(msg, "subject")
            assert hasattr(msg, "body")
            assert hasattr(msg, "is_read")
            assert msg.provider_source == "gmail"

    def test_e2e_token_is_cached(self, tmp_path):
        """Le token est sauvegardé dans un fichier cache."""
        token_file = tmp_path / "token.json"

        adapter = GmailAdapter(token_file=str(token_file))
        result = adapter.authenticate()

        assert result is True
        assert token_file.exists()

        # Le fichier contient du JSON valide
        import json
        with open(token_file) as f:
            token_data = json.load(f)

        assert "token" in token_data or "refresh_token" in token_data

    def test_e2e_scopes_are_correct(self):
        """Vérifie que les scopes demandés sont corrects."""
        adapter = GmailAdapter()

        expected_scopes = [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/gmail.compose",
        ]

        for scope in expected_scopes:
            assert scope in adapter.SCOPES


# ============================================================================
# TESTS OAUTH ERROR HANDLING
# ============================================================================

class TestGmailOAuthErrorHandling:
    """Tests de gestion des erreurs OAuth."""

    @patch("builtins.open", MagicMock())
    @patch("os.path.exists", return_value=False)
    @patch("app.providers.gmail_adapter.Credentials")
    def test_handles_invalid_client_id(self, mock_creds_class, mock_exists):
        """Gère un client_id invalide."""
        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.refresh_token = "token"
        mock_creds.refresh.side_effect = Exception("invalid_client")
        mock_creds_class.return_value = mock_creds

        with patch.dict("os.environ", {
            "GOOGLE_CLIENT_ID": "invalid-client-id",
            "GOOGLE_CLIENT_SECRET": "secret",
            "GOOGLE_REFRESH_TOKEN": "token"
        }):
            adapter = GmailAdapter()
            result = adapter.authenticate()

        assert result is False

    @patch("builtins.open", MagicMock())
    @patch("os.path.exists", return_value=False)
    @patch("app.providers.gmail_adapter.Credentials")
    def test_handles_revoked_token(self, mock_creds_class, mock_exists):
        """Gère un token révoqué."""
        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.refresh_token = "revoked-token"
        mock_creds.refresh.side_effect = Exception("Token has been expired or revoked")
        mock_creds_class.return_value = mock_creds

        with patch.dict("os.environ", {
            "GOOGLE_CLIENT_ID": "client-id",
            "GOOGLE_CLIENT_SECRET": "secret",
            "GOOGLE_REFRESH_TOKEN": "revoked-token"
        }):
            adapter = GmailAdapter()
            result = adapter.authenticate()

        assert result is False

    @patch("builtins.open", MagicMock())
    @patch("os.path.exists", return_value=True)
    @patch("os.remove")
    @patch("app.providers.gmail_adapter.Credentials")
    @patch("app.providers.gmail_adapter.build")
    def test_handles_corrupted_token_file(
        self, mock_build, mock_creds_class, mock_remove, mock_exists
    ):
        """Supprime un fichier token corrompu."""
        # Premier appel: from_authorized_user_file lève une exception
        mock_creds_class.from_authorized_user_file.side_effect = Exception(
            "Corrupted token file"
        )

        # Setup pour le fallback via refresh token
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.refresh_token = "new-token"
        mock_creds.to_json.return_value = "{}"
        mock_creds_class.return_value = mock_creds
        mock_build.return_value = MagicMock()

        with patch.dict("os.environ", {
            "GOOGLE_CLIENT_ID": "client-id",
            "GOOGLE_CLIENT_SECRET": "secret",
            "GOOGLE_REFRESH_TOKEN": "refresh-token"
        }):
            adapter = GmailAdapter(token_file="token.json")
            result = adapter.authenticate()

        # Le fichier corrompu est supprimé (d'autres remove peuvent arriver
        # côté _atomic_write_text cleanup si refresh s'exécute — peu importe).
        mock_remove.assert_any_call("token.json")
        assert result is True

    @patch("builtins.open", MagicMock())
    @patch("os.path.exists", return_value=False)
    @patch("app.providers.gmail_adapter.Credentials")
    def test_handles_network_error(self, mock_creds_class, mock_exists):
        """Gère une erreur réseau lors du refresh."""
        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.refresh_token = "token"
        mock_creds.refresh.side_effect = Exception("Network error")
        mock_creds_class.return_value = mock_creds

        with patch.dict("os.environ", {
            "GOOGLE_CLIENT_ID": "client-id",
            "GOOGLE_CLIENT_SECRET": "secret",
            "GOOGLE_REFRESH_TOKEN": "token"
        }):
            adapter = GmailAdapter()
            result = adapter.authenticate()

        assert result is False
        assert adapter._authenticated is False


# ============================================================================
# TESTS FULL WORKFLOW OAUTH
# ============================================================================

class TestGmailOAuthWorkflow:
    """Tests du workflow complet OAuth (avec mocks)."""

    @patch("builtins.open", MagicMock())
    @patch("os.path.exists", return_value=False)
    @patch("app.providers.gmail_adapter.Credentials")
    @patch("app.providers.gmail_adapter.build")
    def test_complete_workflow_authenticate_list_draft(
        self, mock_build, mock_creds_class, mock_exists
    ):
        """Workflow complet: auth → list messages → create draft."""
        # Setup mocks
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.refresh_token = "token"
        mock_creds.to_json.return_value = "{}"
        mock_creds_class.return_value = mock_creds

        mock_service = MagicMock()
        mock_build.return_value = mock_service

        # Mock list messages
        mock_service.users().messages().list().execute.return_value = {
            "messages": [{"id": "msg-001"}]
        }

        # Mock get message
        import base64
        mock_service.users().messages().get().execute.return_value = {
            "id": "msg-001",
            "threadId": "thread-001",
            "labelIds": ["INBOX", "UNREAD"],
            "payload": {
                "headers": [
                    {"name": "From", "value": "test@example.com"},
                    {"name": "To", "value": "me@example.com"},
                    {"name": "Subject", "value": "Test"},
                ],
                "body": {"data": base64.urlsafe_b64encode(b"Hello").decode()},
                "parts": []
            }
        }

        # Mock create draft
        mock_service.users().drafts().create().execute.return_value = {
            "id": "draft-001"
        }

        with patch.dict("os.environ", {
            "GOOGLE_CLIENT_ID": "client-id",
            "GOOGLE_CLIENT_SECRET": "secret",
            "GOOGLE_REFRESH_TOKEN": "token"
        }):
            adapter = GmailAdapter()

            # 1. Authenticate
            assert adapter.authenticate() is True

            # 2. Get unread messages
            messages = adapter.get_unread_messages(limit=5)
            assert len(messages) == 1
            assert messages[0].id == "msg-001"

            # 3. Create draft reply
            draft_id = adapter.create_draft(
                to=["test@example.com"],
                subject="Re: Test",
                body="Thanks for your message!",
                reply_to_id="msg-001"
            )
            assert draft_id == "draft-001"

            # 4. Verify calls
            mock_service.users().messages().list.assert_called()
            mock_service.users().drafts().create.assert_called()
