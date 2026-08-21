# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests E2E complets du flow OAuth.

Couvre le cycle de vie complet :
- POST /api/oauth/outlook/complete (SPA flow)
- GET /api/oauth/outlook/callback (server-side flow)
- POST /api/oauth/gmail/complete (SPA flow)
- GET /api/oauth/tokens/<id>/status
- POST /api/oauth/tokens/<id>/refresh
- POST /api/oauth/pkce/store + consommation
- POST /api/oauth/<id>/disconnect
"""

import json
import time
import hashlib
import pytest
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse
from requests.exceptions import SSLError


from app.api.app import create_app


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def app():
    """Crée une instance de l'application Flask pour les tests."""
    app = create_app({"TESTING": True})
    return app


@pytest.fixture
def client(app):
    """Crée un client de test."""
    return app.test_client()


@pytest.fixture
def mock_account_manager():
    """Mock du gestionnaire de comptes pour OAuth."""
    with patch("app.api.oauth.get_account_manager") as mock:
        manager = MagicMock()
        manager.current_account_id = None
        mock.return_value = manager
        yield manager


@pytest.fixture
def outlook_env(monkeypatch):
    """Configure les variables d'environnement Outlook au niveau du module."""
    monkeypatch.setattr("app.api.oauth.MICROSOFT_CLIENT_ID", "test-ms-client-id")
    monkeypatch.setattr("app.api.oauth.MICROSOFT_CLIENT_SECRET", "test-ms-secret")
    monkeypatch.setattr(
        "app.api.oauth.MICROSOFT_REDIRECT_URI",
        "http://localhost:5050/api/oauth/outlook/callback",
    )
    monkeypatch.setattr("app.api.oauth.FRONTEND_URL", "http://localhost:1420")


@pytest.fixture
def gmail_env(monkeypatch):
    """Configure les variables d'environnement Gmail au niveau du module."""
    monkeypatch.setattr(
        "app.api.oauth.GOOGLE_CLIENT_ID",
        "test-google-id.apps.googleusercontent.com",
    )
    monkeypatch.setattr("app.api.oauth.GOOGLE_CLIENT_SECRET", "test-google-secret")
    monkeypatch.setattr(
        "app.api.oauth.GOOGLE_REDIRECT_URI",
        "http://localhost:5050/api/oauth/gmail/callback",
    )
    monkeypatch.setattr("app.api.oauth.FRONTEND_URL", "http://localhost:1420")


# =============================================================================
# Helpers
# =============================================================================


def _make_token_response(access="access_tok", refresh="refresh_tok"):
    """Crée un mock de réponse token exchange réussi."""
    return MagicMock(
        ok=True,
        json=MagicMock(return_value={
            "access_token": access,
            "refresh_token": refresh,
            "expires_in": 3600,
            "token_type": "Bearer",
        }),
    )


def _make_token_error(error="invalid_grant", description="Code has expired"):
    """Crée un mock de réponse token exchange échoué."""
    return MagicMock(
        ok=False,
        json=MagicMock(return_value={
            "error": error,
            "error_description": description,
        }),
    )


def _make_gmail_userinfo(email="test@gmail.com", name="Test User"):
    return MagicMock(
        ok=True,
        json=MagicMock(return_value={"email": email, "name": name}),
    )


def _make_outlook_userinfo(email="test@outlook.com", name="Test User"):
    return MagicMock(
        ok=True,
        json=MagicMock(return_value={
            "mail": email,
            "displayName": name,
            "userPrincipalName": email,
        }),
    )


def _make_userinfo_error():
    return MagicMock(ok=False, json=MagicMock(return_value={}))


# =============================================================================
# Classe 1 : TestOutlookCompleteFlowE2E
# =============================================================================


class TestOutlookCompleteFlowE2E:
    """Tests E2E pour POST /api/oauth/outlook/complete."""

    @patch("app.db.database.get_db_session")
    @patch("app.api.oauth.store_tokens_server", return_value=True)
    @patch("app.api.oauth.requests.get")
    @patch("app.api.oauth.requests.post")
    def test_full_flow_success(
        self, mock_post, mock_get, mock_store, mock_db,
        client, mock_account_manager,
    ):
        """PKCE + code → tokens → userinfo → account creation → 200."""
        mock_account_manager.get_account.return_value = None
        mock_post.return_value = _make_token_response()
        mock_get.return_value = _make_outlook_userinfo()

        response = client.post(
            "/api/oauth/outlook/complete",
            data=json.dumps({
                "code": "ms_code_123",
                "state": "state_e2e",
                "code_verifier": "verifier_e2e",
            }),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["email"] == "test@outlook.com"
        assert "account_id" in data
        mock_store.assert_called_once()
        mock_account_manager.add_account.assert_called_once()

    @patch("app.db.database.get_db_session")
    @patch("app.api.oauth.store_tokens_server", return_value=True)
    @patch("app.api.oauth.requests.get")
    @patch("app.api.oauth.requests.post")
    def test_backend_verifier_fallback(
        self, mock_post, mock_get, mock_store, mock_db,
        client, mock_account_manager,
    ):
        """Pas de code_verifier dans le body, mais stocké via /pkce/store."""
        # Stocker le verifier côté backend
        client.post(
            "/api/oauth/pkce/store",
            data=json.dumps({
                "state": "state_fallback",
                "code_verifier": "backend_verifier",
            }),
            content_type="application/json",
        )

        mock_post.return_value = _make_token_response()
        mock_get.return_value = _make_outlook_userinfo()

        # Envoyer sans code_verifier dans le body
        response = client.post(
            "/api/oauth/outlook/complete",
            data=json.dumps({
                "code": "ms_code_fallback",
                "state": "state_fallback",
            }),
            content_type="application/json",
        )

        assert response.status_code == 200
        assert response.get_json()["success"] is True

    @patch("app.api.oauth.requests.post")
    def test_token_exchange_failure(self, mock_post, client):
        """Microsoft retourne invalid_grant → 400.

        F-05 (regression audit, 2026-04-29): we no longer echo the
        upstream `error_description` to the client (attacker-controllable
        fragments). The response body now contains the OAuth error code
        from a fixed allowlist plus a retry-id for support correlation.
        """
        mock_post.return_value = _make_token_error()

        response = client.post(
            "/api/oauth/outlook/complete",
            data=json.dumps({
                "code": "bad_code",
                "state": "state_err",
                "code_verifier": "verifier_err",
            }),
            content_type="application/json",
        )

        assert response.status_code == 400
        body = response.get_json()
        # F-05: safe code from allowlist, plus retry_id for support correlation.
        assert body["error"] == "invalid_grant"
        assert "retry_id" in body and len(body["retry_id"]) >= 6

    @patch("app.api.oauth.requests.get")
    @patch("app.api.oauth.requests.post")
    def test_userinfo_failure(self, mock_post, mock_get, client):
        """Token exchange OK, userinfo échoue → 400."""
        mock_post.return_value = _make_token_response()
        mock_get.return_value = _make_userinfo_error()

        response = client.post(
            "/api/oauth/outlook/complete",
            data=json.dumps({
                "code": "code_ok",
                "state": "state_ui",
                "code_verifier": "verifier_ui",
            }),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "userinfo" in response.get_json()["error"].lower()

    @patch("app.db.database.get_db_session")
    @patch("app.api.oauth.store_tokens_server", return_value=False)
    @patch("app.api.oauth.requests.get")
    @patch("app.api.oauth.requests.post")
    def test_storage_failure(
        self, mock_post, mock_get, mock_store, mock_db, client, mock_account_manager,
    ):
        """store_tokens_server retourne False → 500."""
        mock_post.return_value = _make_token_response()
        mock_get.return_value = _make_outlook_userinfo()

        response = client.post(
            "/api/oauth/outlook/complete",
            data=json.dumps({
                "code": "code_store",
                "state": "state_store",
                "code_verifier": "verifier_store",
            }),
            content_type="application/json",
        )

        assert response.status_code == 500
        assert "storage" in response.get_json()["error"].lower()

    @patch("app.db.database.get_db_session")
    @patch("app.api.oauth.store_tokens_server", return_value=True)
    @patch("app.api.oauth.requests.get")
    @patch("app.api.oauth.requests.post")
    def test_existing_account_reconnect(
        self, mock_post, mock_get, mock_store, mock_db,
        client, mock_account_manager,
    ):
        """Account déjà dans le manager → update status (pas add_account)."""
        existing = MagicMock()
        existing.id = "existing_id"
        mock_account_manager.get_account.return_value = existing

        mock_post.return_value = _make_token_response()
        mock_get.return_value = _make_outlook_userinfo()

        response = client.post(
            "/api/oauth/outlook/complete",
            data=json.dumps({
                "code": "code_recon",
                "state": "state_recon",
                "code_verifier": "verifier_recon",
            }),
            content_type="application/json",
        )

        assert response.status_code == 200
        assert response.get_json()["success"] is True
        mock_account_manager.update_account_status.assert_called_once()
        mock_account_manager.add_account.assert_not_called()


# =============================================================================
# Classe 2 : TestOutlookCallbackFlowE2E
# =============================================================================


class TestOutlookCallbackFlowE2E:
    """Tests E2E pour GET /api/oauth/outlook/callback."""

    @patch("app.db.database.get_db_session")
    @patch("app.api.oauth.store_tokens_server", return_value=True)
    @patch("app.api.oauth.requests.get")
    @patch("app.api.oauth.requests.post")
    def test_callback_full_flow_redirect_success(
        self, mock_post, mock_get, mock_store, mock_db,
        client, mock_account_manager, outlook_env,
    ):
        """Stocke PKCE → callback avec code+state → redirect avec success=true."""
        # Stocker le verifier
        client.post(
            "/api/oauth/pkce/store",
            data=json.dumps({
                "state": "cb_state_ok",
                "code_verifier": "cb_verifier_ok",
            }),
            content_type="application/json",
        )

        mock_post.return_value = _make_token_response()
        mock_get.return_value = _make_outlook_userinfo("user@outlook.com")

        response = client.get(
            "/api/oauth/outlook/callback?code=ms_code_cb&state=cb_state_ok"
        )

        assert response.status_code == 302
        assert "success=true" in response.location
        query = parse_qs(urlparse(response.location).query)
        assert query["email"] == ["user@outlook.com"]

    def test_callback_no_verifier_redirects_to_frontend(
        self, client, outlook_env,
    ):
        """Pas de verifier stocké → redirect avec code+state (fallback frontend)."""
        response = client.get(
            "/api/oauth/outlook/callback?code=ms_code_nv&state=state_nv"
        )

        assert response.status_code == 302
        assert "code=" in response.location
        assert "state=" in response.location
        # Pas de success=true car l'échange n'a pas eu lieu
        assert "success=true" not in response.location

    @patch("app.api.oauth.requests.post")
    def test_callback_token_exchange_failure(
        self, mock_post, client, outlook_env,
    ):
        """Token exchange échoue → redirect avec error."""
        # Stocker le verifier
        client.post(
            "/api/oauth/pkce/store",
            data=json.dumps({
                "state": "cb_state_fail",
                "code_verifier": "cb_verifier_fail",
            }),
            content_type="application/json",
        )

        mock_post.return_value = _make_token_error()

        response = client.get(
            "/api/oauth/outlook/callback?code=bad_code&state=cb_state_fail"
        )

        assert response.status_code == 302
        assert "error=" in response.location

    @patch("app.api.oauth.requests.post")
    def test_callback_token_exchange_network_error_falls_back_to_frontend(
        self, mock_post, client, outlook_env,
    ):
        """Network/TLS failure during callback should not strand the OAuth flow."""
        client.post(
            "/api/oauth/pkce/store",
            data=json.dumps({
                "state": "cb_state_network",
                "code_verifier": "cb_verifier_network",
            }),
            content_type="application/json",
        )
        mock_post.side_effect = SSLError("unexpected eof")

        response = client.get(
            "/api/oauth/outlook/callback?code=ms_code_network&state=cb_state_network"
        )

        assert response.status_code == 302
        assert "provider=outlook" in response.location
        assert "code=ms_code_network" in response.location
        assert "auth_redirect_uri=" in response.location
        assert "server_error" not in response.location

    def test_callback_error_from_microsoft(self, client, outlook_env):
        """Microsoft envoie ?error=access_denied → redirect avec erreur."""
        response = client.get(
            "/api/oauth/outlook/callback?error=access_denied"
            "&error_description=User%20denied%20consent"
        )

        assert response.status_code == 302
        assert "error=access_denied" in response.location
        assert "error_description=" in response.location

    def test_callback_missing_code(self, client, outlook_env):
        """Pas de code ni d'erreur → redirect avec error=missing_code."""
        response = client.get("/api/oauth/outlook/callback")

        assert response.status_code == 302
        assert "error=missing_code" in response.location


class TestGmailCallbackFlowE2E:
    """Tests E2E pour GET /api/oauth/gmail/callback."""

    @patch("app.api.oauth.requests.post")
    def test_callback_token_exchange_network_error_falls_back_to_frontend(
        self, mock_post, client, gmail_env,
    ):
        """Google token endpoint TLS resets should use the existing SPA fallback."""
        client.post(
            "/api/oauth/pkce/store",
            data=json.dumps({
                "state": "gmail_state_network",
                "code_verifier": "gmail_verifier_network",
            }),
            content_type="application/json",
        )
        mock_post.side_effect = SSLError("unexpected eof")

        response = client.get(
            "/api/oauth/gmail/callback?code=google_code_network&state=gmail_state_network"
        )

        assert response.status_code == 302
        assert "provider=gmail" in response.location
        assert "code=google_code_network" in response.location
        assert "auth_redirect_uri=" in response.location
        assert "server_error" not in response.location


# =============================================================================
# Classe 3 : TestGmailCompleteFlowE2E
# =============================================================================


class TestGmailCompleteFlowE2E:
    """Tests E2E pour POST /api/oauth/gmail/complete."""

    @patch("app.db.database.get_db_session")
    @patch("app.api.oauth.store_tokens_server", return_value=True)
    @patch("app.api.oauth.requests.get")
    @patch("app.api.oauth.requests.post")
    def test_full_flow_success(
        self, mock_post, mock_get, mock_store, mock_db,
        client, mock_account_manager,
    ):
        """PKCE + code → tokens → userinfo → account creation → 200."""
        mock_post.return_value = _make_token_response()
        mock_get.return_value = _make_gmail_userinfo()

        response = client.post(
            "/api/oauth/gmail/complete",
            data=json.dumps({
                "code": "google_code_123",
                "state": "state_gmail",
                "code_verifier": "verifier_gmail",
            }),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["email"] == "test@gmail.com"
        assert "account_id" in data
        expected_id = hashlib.sha256(b"gmail:test@gmail.com").hexdigest()[:16]
        assert data["account_id"] == expected_id

    @patch("app.db.database.get_db_session")
    @patch("app.api.oauth.store_tokens_server", return_value=True)
    @patch("app.api.oauth.requests.get")
    @patch("app.api.oauth.requests.post")
    def test_backend_verifier_fallback(
        self, mock_post, mock_get, mock_store, mock_db,
        client, mock_account_manager,
    ):
        """Fallback sur le store backend pour le code_verifier."""
        client.post(
            "/api/oauth/pkce/store",
            data=json.dumps({
                "state": "gmail_fb_state",
                "code_verifier": "gmail_backend_verifier",
            }),
            content_type="application/json",
        )

        mock_post.return_value = _make_token_response()
        mock_get.return_value = _make_gmail_userinfo()

        response = client.post(
            "/api/oauth/gmail/complete",
            data=json.dumps({
                "code": "google_code_fb",
                "state": "gmail_fb_state",
            }),
            content_type="application/json",
        )

        assert response.status_code == 200
        assert response.get_json()["success"] is True

    @patch("app.api.oauth.requests.post")
    def test_token_exchange_failure(self, mock_post, client):
        """Google retourne invalid_grant → 400."""
        mock_post.return_value = _make_token_error()

        response = client.post(
            "/api/oauth/gmail/complete",
            data=json.dumps({
                "code": "bad_google_code",
                "state": "state_fail",
                "code_verifier": "verifier_fail",
            }),
            content_type="application/json",
        )

        assert response.status_code == 400

    @patch("app.api.oauth.requests.get")
    @patch("app.api.oauth.requests.post")
    def test_userinfo_failure(self, mock_post, mock_get, client):
        """Token OK, userinfo échoue → 400."""
        mock_post.return_value = _make_token_response()
        mock_get.return_value = _make_userinfo_error()

        response = client.post(
            "/api/oauth/gmail/complete",
            data=json.dumps({
                "code": "code_gmail_ui",
                "state": "state_ui",
                "code_verifier": "verifier_ui",
            }),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "userinfo" in response.get_json()["error"].lower()

    @patch("app.db.database.get_db_session")
    @patch("app.api.oauth.store_tokens_server", return_value=False)
    @patch("app.api.oauth.requests.get")
    @patch("app.api.oauth.requests.post")
    def test_storage_failure(
        self, mock_post, mock_get, mock_store, mock_db, client, mock_account_manager,
    ):
        """store_tokens_server retourne False → 500."""
        mock_post.return_value = _make_token_response()
        mock_get.return_value = _make_gmail_userinfo()

        response = client.post(
            "/api/oauth/gmail/complete",
            data=json.dumps({
                "code": "code_store",
                "state": "state_store",
                "code_verifier": "verifier_store",
            }),
            content_type="application/json",
        )

        assert response.status_code == 500
        assert "storage" in response.get_json()["error"].lower()

    @patch("app.db.database.get_db_session")
    @patch("app.api.oauth.store_tokens_server", return_value=True)
    @patch("app.api.oauth.requests.get")
    @patch("app.api.oauth.requests.post")
    def test_existing_account_reconnect(
        self, mock_post, mock_get, mock_store, mock_db,
        client, mock_account_manager,
    ):
        """Compte existant → update_account_status, pas add_account."""
        existing = MagicMock()
        mock_account_manager.get_account.return_value = existing

        mock_post.return_value = _make_token_response()
        mock_get.return_value = _make_gmail_userinfo()

        response = client.post(
            "/api/oauth/gmail/complete",
            data=json.dumps({
                "code": "code_recon",
                "state": "state_recon",
                "code_verifier": "verifier_recon",
            }),
            content_type="application/json",
        )

        assert response.status_code == 200
        mock_account_manager.update_account_status.assert_called_once()
        mock_account_manager.add_account.assert_not_called()

    @patch("app.db.database.get_db_session")
    @patch("app.api.oauth.store_tokens_server", return_value=True)
    @patch("app.api.oauth.requests.get")
    @patch("app.api.oauth.requests.post")
    def test_existing_gmail_reconnect_binds_web_user(
        self, mock_post, mock_get, mock_store, mock_db,
        client, mock_account_manager,
    ):
        """Reconnect OAuth doit lier le compte au user web même si un current legacy existe."""
        email = "test@gmail.com"
        expected_id = hashlib.sha256(f"gmail:{email}".encode()).hexdigest()[:16]
        expected_user_id = int(hashlib.sha256(email.lower().encode()).hexdigest()[:8], 16)
        existing = MagicMock()
        existing.user_id = None
        mock_account_manager.get_account.return_value = existing
        mock_account_manager.current_account_id = "legacy-current"
        mock_account_manager.get_current_for_user.return_value = None

        mock_post.return_value = _make_token_response()
        mock_get.return_value = _make_gmail_userinfo(email)

        response = client.post(
            "/api/oauth/gmail/complete",
            data=json.dumps({
                "code": "code_reconnect_calendar",
                "state": "state_reconnect_calendar",
                "code_verifier": "verifier_reconnect_calendar",
            }),
            content_type="application/json",
        )

        assert response.status_code == 200
        mock_account_manager.update_account_status.assert_called_once()
        mock_account_manager.update_account.assert_called_once_with(
            expected_id,
            user_id=expected_user_id,
        )
        mock_account_manager.switch_to.assert_called_once_with(
            expected_id,
            user_id=expected_user_id,
        )


# =============================================================================
# Classe 4 : TestTokenStatusAndRefreshE2E
# =============================================================================


class TestTokenStatusAndRefreshE2E:
    """Tests E2E pour token status et refresh."""

    @patch("app.api.oauth.get_tokens_server", return_value=None)
    def test_token_status_no_tokens(self, mock_tokens, client):
        """Pas de tokens → has_tokens=False."""
        response = client.get("/api/oauth/tokens/unknown_id/status")

        assert response.status_code == 200
        data = response.get_json()
        assert data["has_tokens"] is False
        assert data["is_valid"] is False

    @patch("app.api.oauth.get_tokens_server")
    def test_token_status_valid(self, mock_tokens, client):
        """Tokens valides → has_tokens=True, is_valid=True."""
        mock_tokens.return_value = {
            "access_token": "valid_token",
            "refresh_token": "refresh_tok",
            "expires_at": time.time() + 3600,
            "email": "test@outlook.com",
            "provider": "outlook",
            "scope": "",
        }

        response = client.get("/api/oauth/tokens/some_id/status")

        assert response.status_code == 200
        data = response.get_json()
        assert data["has_tokens"] is True
        assert data["is_valid"] is True
        assert data["email"] == "test@outlook.com"

    @patch("app.api.oauth.get_tokens_server", return_value=None)
    def test_token_readiness_no_tokens(self, mock_tokens, client):
        """Pas de tokens → l'app doit demander une reconnexion."""
        response = client.get("/api/oauth/tokens/unknown_id/readiness")

        assert response.status_code == 200
        data = response.get_json()
        assert data["ready"] is False
        assert data["needs_reauth"] is True
        assert data["problem"] == "no_tokens"

    @patch("app.api.oauth.get_tokens_server")
    def test_token_readiness_gmail_missing_scopes(self, mock_tokens, client):
        """Connexion partielle Gmail → permissions manquantes explicites."""
        mock_tokens.return_value = {
            "access_token": "valid_token",
            "refresh_token": "refresh_tok",
            "expires_at": time.time() + 3600,
            "email": "test@gmail.com",
            "provider": "gmail",
            "scope": "https://www.googleapis.com/auth/gmail.readonly",
        }

        response = client.get("/api/oauth/tokens/gmail_id/readiness")

        assert response.status_code == 200
        data = response.get_json()
        assert data["ready"] is False
        assert data["needs_reauth"] is True
        assert data["problem"] == "missing_scopes"
        assert "gmail.send" in data["missing_scopes"]
        assert "offline_access" not in data["missing_scopes"]

    @patch("app.api.oauth.get_tokens_server")
    def test_token_readiness_gmail_ready(self, mock_tokens, client):
        """Tous les scopes critiques Gmail → entrée autorisée."""
        mock_tokens.return_value = {
            "access_token": "valid_token",
            "refresh_token": "refresh_tok",
            "expires_at": time.time() + 3600,
            "email": "test@gmail.com",
            "provider": "gmail",
            "scope": " ".join([
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/gmail.send",
                "https://www.googleapis.com/auth/gmail.modify",
                "https://www.googleapis.com/auth/gmail.compose",
                "https://www.googleapis.com/auth/gmail.settings.basic",
                "https://www.googleapis.com/auth/userinfo.email",
            ]),
        }

        response = client.get("/api/oauth/tokens/gmail_id/readiness")

        assert response.status_code == 200
        data = response.get_json()
        assert data["ready"] is True
        assert data["needs_reauth"] is False
        assert data["missing_scopes"] == []

    @patch("app.api.oauth.get_tokens_server")
    def test_token_readiness_db_fallback_without_scope_does_not_block(self, mock_tokens, client):
        """Les comptes legacy sans scope persisté ne doivent pas être bloqués à tort."""
        mock_tokens.return_value = {
            "access_token": "valid_token",
            "refresh_token": "refresh_tok",
            "expires_at": time.time() + 3600,
            "email": "legacy@gmail.com",
            "provider": "gmail",
            "scope": "",
            "source": "db_account",
        }

        response = client.get("/api/oauth/tokens/legacy_id/readiness")

        assert response.status_code == 200
        data = response.get_json()
        assert data["ready"] is True
        assert data["scope_verified"] is False

    @patch("app.api.oauth.get_tokens_server")
    def test_token_readiness_outlook_accepts_short_scope_names(self, mock_tokens, client):
        """Microsoft peut renvoyer des scopes courts dans `scope`/`scp`."""
        mock_tokens.return_value = {
            "access_token": "valid_token",
            "refresh_token": "refresh_tok",
            "expires_at": time.time() + 3600,
            "email": "test@outlook.com",
            "provider": "outlook",
            "scope": "Mail.Read Mail.Send Mail.ReadWrite User.Read Calendars.ReadWrite People.Read Contacts.Read",
        }

        response = client.get("/api/oauth/tokens/outlook_id/readiness")

        assert response.status_code == 200
        data = response.get_json()
        assert data["ready"] is True
        assert data["missing_scopes"] == []

    @patch("app.api.oauth._refresh_tokens_server")
    @patch("app.api.oauth.get_tokens_server")
    def test_refresh_outlook_success(self, mock_get, mock_refresh, client):
        """Refresh Outlook réussi → 200."""
        mock_get.return_value = {
            "refresh_token": "old_refresh",
            "provider": "outlook",
        }
        mock_refresh.return_value = {
            "access_token": "new_access",
            "expires_at": time.time() + 3600,
        }

        response = client.post("/api/oauth/tokens/outlook_id/refresh")

        assert response.status_code == 200
        assert response.get_json()["success"] is True

    @patch("app.api.oauth._refresh_tokens_server")
    @patch("app.api.oauth.get_tokens_server")
    def test_refresh_gmail_success(self, mock_get, mock_refresh, client):
        """Refresh Gmail réussi → 200."""
        mock_get.return_value = {
            "refresh_token": "old_refresh",
            "provider": "gmail",
        }
        mock_refresh.return_value = {
            "access_token": "new_access",
            "expires_at": time.time() + 3600,
        }

        response = client.post("/api/oauth/tokens/gmail_id/refresh")

        assert response.status_code == 200
        assert response.get_json()["success"] is True

    @patch("app.api.oauth.store_tokens_server")
    @patch("app.api.oauth.requests.post")
    @patch("app.api.oauth.get_tokens_server")
    def test_refresh_preserves_scope_when_provider_omits_it(
        self,
        mock_get,
        mock_post,
        mock_store,
        client,
    ):
        """Un refresh sans scope ne doit pas casser le gate readiness."""
        old_scope = "https://www.googleapis.com/auth/gmail.readonly"
        old_token_data = {
            "refresh_token": "old_refresh",
            "provider": "gmail",
            "email": "test@gmail.com",
            "scope": old_scope,
        }
        mock_get.side_effect = [
            old_token_data,
            old_token_data,
            {
                "access_token": "new_access",
                "refresh_token": "old_refresh",
                "provider": "gmail",
                "email": "test@gmail.com",
                "scope": old_scope,
            },
        ]
        mock_post.return_value = MagicMock(
            ok=True,
            json=MagicMock(return_value={
                "access_token": "new_access",
                "expires_in": 3600,
                "token_type": "Bearer",
            }),
        )
        mock_store.return_value = True

        response = client.post("/api/oauth/tokens/gmail_id/refresh")

        assert response.status_code == 200
        stored_tokens = mock_store.call_args.args[2]
        assert stored_tokens["scope"] == old_scope

    @patch("app.api.oauth.get_tokens_server", return_value=None)
    def test_refresh_no_tokens(self, mock_tokens, client):
        """Refresh sans tokens → 404."""
        response = client.post("/api/oauth/tokens/unknown/refresh")

        assert response.status_code == 404

    @patch("app.api.oauth._refresh_tokens_server", return_value=None)
    @patch("app.api.oauth.get_tokens_server")
    def test_refresh_invalid_grant(self, mock_get, mock_refresh, client):
        """Refresh échoue (invalid_grant) → 500."""
        mock_get.return_value = {
            "refresh_token": "dead_refresh",
            "provider": "outlook",
        }

        response = client.post("/api/oauth/tokens/dead_id/refresh")

        assert response.status_code == 500
        assert "failed" in response.get_json()["error"].lower()


# =============================================================================
# Classe 5 : TestPKCEIntegration
# =============================================================================


class TestPKCEIntegration:
    """Tests d'intégration PKCE : store → consume → one-time use."""

    @patch("app.db.database.get_db_session")
    @patch("app.api.oauth.store_tokens_server", return_value=True)
    @patch("app.api.oauth.requests.get")
    @patch("app.api.oauth.requests.post")
    def test_pkce_store_and_consume(
        self, mock_post, mock_get, mock_store, mock_db,
        client, mock_account_manager, outlook_env,
    ):
        """Store → callback utilise → deuxième callback échoue (one-time use)."""
        # Store le verifier
        store_resp = client.post(
            "/api/oauth/pkce/store",
            data=json.dumps({
                "state": "pkce_state_1",
                "code_verifier": "pkce_verifier_1",
            }),
            content_type="application/json",
        )
        assert store_resp.status_code == 200

        # Premier callback consomme le verifier
        mock_post.return_value = _make_token_response()
        mock_get.return_value = _make_outlook_userinfo()

        resp1 = client.get(
            "/api/oauth/outlook/callback?code=code1&state=pkce_state_1"
        )
        assert resp1.status_code == 302
        assert "success=true" in resp1.location

        # Deuxième callback : verifier consommé → fallback frontend (code passé au frontend)
        resp2 = client.get(
            "/api/oauth/outlook/callback?code=code2&state=pkce_state_1"
        )
        assert resp2.status_code == 302
        # Le verifier a été consommé, donc redirect vers frontend avec code (pas success=true)
        assert "success=true" not in resp2.location

    def test_pkce_cleanup_expired(self, client, monkeypatch):
        """Verifier expiré est nettoyé par cleanup."""
        from app.api import oauth

        # Injecter un verifier avec timestamp ancien
        with oauth._code_verifier_lock:
            oauth._pending_code_verifiers["expired_pkce"] = {
                "code_verifier": "old_verifier",
                "timestamp": time.time() - 400,  # > 5 minutes
            }

        # Stocker un nouveau verifier déclenche le cleanup
        client.post(
            "/api/oauth/pkce/store",
            data=json.dumps({
                "state": "new_pkce",
                "code_verifier": "new_verifier",
            }),
            content_type="application/json",
        )

        # L'ancien verifier ne devrait plus être disponible
        resp = client.get("/api/oauth/pkce/expired_pkce")
        assert resp.status_code == 404


# =============================================================================
# Classe 6 : TestDisconnectFlowE2E
# =============================================================================


class TestDisconnectFlowE2E:
    """Tests E2E pour disconnect."""

    @patch("app.api.oauth.delete_tokens_server")
    def test_disconnect_deletes_tokens(
        self, mock_delete, client, mock_account_manager,
    ):
        """Disconnect supprime les tokens et met à jour le status."""
        mock_account = MagicMock()
        mock_account.id = "acc_disco"
        mock_account_manager.get_account.return_value = mock_account

        response = client.post("/api/oauth/acc_disco/disconnect")

        assert response.status_code == 200
        assert response.get_json()["success"] is True
        mock_delete.assert_called_once_with("acc_disco")

    @patch("app.api.oauth.delete_tokens_server")
    def test_disconnect_not_found(
        self, mock_delete, client, mock_account_manager,
    ):
        """Disconnect d'un compte inexistant → 404."""
        mock_account_manager.get_account.return_value = None

        response = client.post("/api/oauth/unknown_acc/disconnect")

        assert response.status_code == 404
