# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests E2E OAuth Outlook — couche stockage tokens + endpoints API.

Couvre :
- store_tokens_server / get_tokens_server / delete_tokens_server
- Chiffrement Fernet (access_token jamais en clair dans _server_tokens)
- Expiration et rafraîchissement de tokens via MICROSOFT_TOKEN_URL
- GET /api/oauth/tokens/<id>/status
- POST /api/oauth/tokens/<id>/refresh
- GET /api/oauth/tokens/<id>/access (auto-refresh si expiré)
- GET /api/oauth/outlook/callback — callback complet
- POST /api/oauth/<id>/disconnect

pytest tests/test_outlook_oauth_agentys.py -v
"""

import hashlib
import os
import time
from contextlib import contextmanager
from types import SimpleNamespace
import pytest
from unittest.mock import MagicMock, patch

from app.api.app import create_app
from app.api.oauth import (
    _refresh_tokens_server,
    delete_tokens_server,
    get_tokens_server,
    store_tokens_server,
)
import app.api.oauth as oauth_module


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture(autouse=True)
def clean_tokens_and_no_file_io():
    """Nettoie _server_tokens et neutralise les I/O fichiers avant chaque test."""
    with oauth_module._server_tokens_lock:
        backup = dict(oauth_module._server_tokens)
        backup_deletions = set(oauth_module._server_token_deletions)
        backup_mtime = oauth_module._server_tokens_mtime
        backup_fsize = oauth_module._server_tokens_fsize
        oauth_module._server_tokens.clear()
        oauth_module._server_token_deletions.clear()

    with patch("app.api.oauth._save_tokens_to_file"), \
         patch("app.api.oauth._load_tokens_from_file"), \
         patch("app.api.oauth._reload_tokens_if_disk_newer"):
        yield

    with oauth_module._server_tokens_lock:
        oauth_module._server_tokens.clear()
        oauth_module._server_tokens.update(backup)
        oauth_module._server_token_deletions.clear()
        oauth_module._server_token_deletions.update(backup_deletions)
        oauth_module._server_tokens_mtime = backup_mtime
        oauth_module._server_tokens_fsize = backup_fsize


@pytest.fixture
def flask_app():
    return create_app({"TESTING": True})


@pytest.fixture
def flask_client(flask_app):
    return flask_app.test_client()


@pytest.fixture
def mock_mgr():
    """Mock du gestionnaire de comptes OAuth."""
    with patch("app.api.oauth.get_account_manager") as mock:
        manager = MagicMock()
        mock.return_value = manager
        yield manager


@pytest.fixture
def sample_tokens():
    return {
        "access_token": "EwBAAl3BAAUFFpUAo7J3Ve0bjLBWZWCclRC3x5Jqr...",
        "refresh_token": "M.C3_BAY.Cq_v5....",
        "expires_in": 3600,
        "token_type": "Bearer",
        # Scopes en URI complets (nécessaires pour has_email=True dans /status)
        "scope": (
            "https://graph.microsoft.com/Mail.Read "
            "https://graph.microsoft.com/Mail.ReadWrite "
            "https://graph.microsoft.com/Mail.Send "
            "offline_access"
        ),
    }


@pytest.fixture
def account_id():
    return hashlib.sha256("outlook:user@hotmail.com".encode()).hexdigest()[:16]


@pytest.fixture
def stored_account_id(account_id, sample_tokens):
    """Stocke les tokens et retourne l'account_id ; nettoie après le test."""
    store_tokens_server(account_id, "outlook", sample_tokens, "user@hotmail.com")
    yield account_id
    delete_tokens_server(account_id)


# ============================================================================
# Tests : Stockage des tokens
# ============================================================================


class TestOutlookTokenStorage:
    def test_store_encrypts_data(self, account_id, sample_tokens):
        """store_tokens_server() chiffre l'access_token — jamais en clair dans _server_tokens."""
        store_tokens_server(account_id, "outlook", sample_tokens, "user@hotmail.com")

        with oauth_module._server_tokens_lock:
            stored = oauth_module._server_tokens.get(account_id)

        assert stored is not None
        raw_str = str(stored)
        # L'access_token en clair ne doit pas apparaître dans les données stockées
        assert sample_tokens["access_token"] not in raw_str
        # Seul encrypted_data contient les données sensibles
        assert "encrypted_data" in stored

    def test_get_decrypts_correctly(self, account_id, sample_tokens):
        """get_tokens_server() déchiffre et retourne les bonnes valeurs."""
        store_tokens_server(account_id, "outlook", sample_tokens, "user@hotmail.com")

        result = get_tokens_server(account_id)

        assert result is not None
        assert result["access_token"] == sample_tokens["access_token"]
        assert result["refresh_token"] == sample_tokens["refresh_token"]
        assert result["provider"] == "outlook"
        assert result["email"] == "user@hotmail.com"

    def test_get_returns_none_for_unknown_id(self):
        """get_tokens_server() retourne None pour un account_id inconnu."""
        result = get_tokens_server("unknownid_doesnotexist")
        assert result is None

    def test_get_falls_back_to_db_account_hash(self):
        """Worker-safe: oauth_tokens.json absent, tokens relus depuis la DB."""
        email = "nat@example.com"
        account_hash = hashlib.sha256(f"gmail:{email}".encode()).hexdigest()[:16]
        db_account = SimpleNamespace(
            email=email,
            provider="gmail",
            access_token="db-access-token",
            refresh_token="db-refresh-token",
            token_expires_at=None,
        )

        class FakeAccountRepository:
            def __init__(self, session):
                self.session = session

            def get_active_accounts(self):
                return [db_account]

        @contextmanager
        def fake_db_session():
            yield object()

        with patch("app.db.database.get_db_session", fake_db_session), \
             patch("app.db.repositories.account_repository.AccountRepository", FakeAccountRepository):
            result = get_tokens_server(account_hash)

        assert result is not None
        assert result["provider"] == "gmail"
        assert result["email"] == email
        assert result["access_token"] == "db-access-token"
        assert result["refresh_token"] == "db-refresh-token"
        assert result["expires_at"] == 1.0
        assert result["source"] == "db_account"

    def test_delete_removes_entry(self, account_id, sample_tokens):
        """delete_tokens_server() supprime les tokens — get_tokens_server retourne None."""
        store_tokens_server(account_id, "outlook", sample_tokens, "user@hotmail.com")
        assert get_tokens_server(account_id) is not None

        delete_tokens_server(account_id)

        assert get_tokens_server(account_id) is None

    def test_store_persists_to_file(self, account_id, sample_tokens):
        """store_tokens_server() appelle _save_tokens_to_file pour la persistance."""
        with patch("app.api.oauth._save_tokens_to_file") as mock_save:
            store_tokens_server(account_id, "outlook", sample_tokens, "user@hotmail.com")

        mock_save.assert_called_once()

    def test_roundtrip_preserves_all_fields(self, account_id, sample_tokens):
        """store → get préserve provider, email, expires_at et scope."""
        store_tokens_server(account_id, "outlook", sample_tokens, "user@hotmail.com")

        result = get_tokens_server(account_id)

        assert result["provider"] == "outlook"
        assert result["email"] == "user@hotmail.com"
        # expires_at doit être dans le futur (stocké comme time.time() + expires_in)
        assert result["expires_at"] > time.time()
        assert "Mail.Read" in result.get("scope", "")


# ============================================================================
# Tests : Expiration des tokens
# ============================================================================


class TestOutlookTokenExpiration:
    def test_valid_token_is_valid(self, flask_client, account_id, sample_tokens):
        """Token avec expires_at dans 1h → is_valid=True, expires_in > 0."""
        store_tokens_server(account_id, "outlook", sample_tokens, "user@hotmail.com")

        response = flask_client.get(f"/api/oauth/tokens/{account_id}/status")

        assert response.status_code == 200
        data = response.get_json()
        assert data["has_tokens"] is True
        assert data["is_valid"] is True
        assert data["expires_in"] > 0

    def test_expired_token_is_invalid(self, flask_client, account_id):
        """Token expiré depuis 1 min → is_valid=False, expires_in ≤ 0."""
        expired_tokens = {
            "access_token": "expired_token",
            "refresh_token": "some_refresh",
            "expires_in": -60,  # Expiré depuis 60s
        }
        store_tokens_server(account_id, "outlook", expired_tokens, "user@hotmail.com")

        response = flask_client.get(f"/api/oauth/tokens/{account_id}/status")

        assert response.status_code == 200
        data = response.get_json()
        assert data["has_tokens"] is True
        assert data["is_valid"] is False

    def test_status_endpoint_valid_token(self, flask_client, account_id, sample_tokens):
        """GET /api/oauth/tokens/<id>/status retourne has_tokens, is_valid, provider, has_email."""
        store_tokens_server(account_id, "outlook", sample_tokens, "user@hotmail.com")

        response = flask_client.get(f"/api/oauth/tokens/{account_id}/status")

        assert response.status_code == 200
        data = response.get_json()
        assert data["has_tokens"] is True
        assert data["is_valid"] is True
        assert data["provider"] == "outlook"
        assert data["has_email"] is True  # URI scopes complets dans sample_tokens

    def test_status_endpoint_not_found(self, flask_client):
        """GET /api/oauth/tokens/<id>/status → has_tokens=False pour id inconnu."""
        response = flask_client.get("/api/oauth/tokens/unknown_id_xyz/status")

        assert response.status_code == 200
        data = response.get_json()
        assert data["has_tokens"] is False
        assert data["is_valid"] is False


# ============================================================================
# Tests : Rafraîchissement des tokens
# ============================================================================


class TestOutlookTokenRefresh:
    def test_refresh_posts_to_microsoft_token_url(self, account_id, sample_tokens):
        """_refresh_tokens_server() appelle requests.post vers MICROSOFT_TOKEN_URL."""
        store_tokens_server(account_id, "outlook", sample_tokens, "user@hotmail.com")

        new_tokens = {
            "access_token": "new_access_token_abc",
            "refresh_token": "new_refresh_token_xyz",
            "expires_in": 3600,
        }
        with patch("requests.post") as mock_post:
            mock_post.return_value.ok = True
            mock_post.return_value.json.return_value = new_tokens

            _refresh_tokens_server(account_id)

        mock_post.assert_called_once()
        call_args = mock_post.call_args
        # URL doit être le token endpoint Microsoft
        assert "microsoftonline.com" in call_args[0][0]
        assert "grant_type" in call_args[1].get("data", {})
        assert call_args[1]["data"]["grant_type"] == "refresh_token"

    def test_refresh_updates_access_token(self, account_id, sample_tokens):
        """Après refresh, l'access_token stocké est le nouveau."""
        store_tokens_server(account_id, "outlook", sample_tokens, "user@hotmail.com")

        new_tokens = {
            "access_token": "fresh_access_token_NEW",
            "refresh_token": sample_tokens["refresh_token"],
            "expires_in": 3600,
        }
        with patch("requests.post") as mock_post:
            mock_post.return_value.ok = True
            mock_post.return_value.json.return_value = new_tokens

            result = _refresh_tokens_server(account_id)

        assert result is not None
        assert result["access_token"] == "fresh_access_token_NEW"

    def test_refresh_preserves_old_refresh_token_when_missing(self, account_id, sample_tokens):
        """Si Microsoft n'envoie pas de refresh_token, l'ancien est conservé."""
        store_tokens_server(account_id, "outlook", sample_tokens, "user@hotmail.com")

        # Réponse sans refresh_token (cas courant pour Microsoft)
        new_tokens_no_refresh = {
            "access_token": "new_access_only",
            "expires_in": 3600,
            # Pas de refresh_token
        }
        with patch("requests.post") as mock_post:
            mock_post.return_value.ok = True
            mock_post.return_value.json.return_value = new_tokens_no_refresh

            result = _refresh_tokens_server(account_id)

        assert result is not None
        assert result["refresh_token"] == sample_tokens["refresh_token"]

    def test_refresh_returns_none_on_http_400(self, account_id, sample_tokens):
        """HTTP 400 lors du refresh → _refresh_tokens_server retourne None."""
        store_tokens_server(account_id, "outlook", sample_tokens, "user@hotmail.com")

        with patch("requests.post") as mock_post:
            mock_post.return_value.ok = False
            mock_post.return_value.status_code = 400
            mock_post.return_value.json.return_value = {
                "error": "invalid_request",
                "error_description": "Bad request",
            }
            mock_post.return_value.text = '{"error": "invalid_request"}'

            result = _refresh_tokens_server(account_id)

        assert result is None

    def test_refresh_invalid_grant_emits_ws_event(self, account_id, sample_tokens):
        """error=invalid_grant → emit_token_expired(account_id, email, 'outlook') appelé."""
        store_tokens_server(account_id, "outlook", sample_tokens, "user@hotmail.com")

        with patch("requests.post") as mock_post, \
             patch("app.api.websocket.emit_token_expired") as mock_emit:
            mock_post.return_value.ok = False
            mock_post.return_value.status_code = 400
            mock_post.return_value.json.return_value = {
                "error": "invalid_grant",
                "error_description": "Refresh token has expired",
            }
            mock_post.return_value.text = '{"error": "invalid_grant"}'

            _refresh_tokens_server(account_id)

        mock_emit.assert_called_once_with(account_id, "user@hotmail.com", "outlook")

    def test_refresh_endpoint_success(self, flask_client, account_id, sample_tokens):
        """POST /api/oauth/tokens/<id>/refresh → {success: true, expires_in > 0}."""
        store_tokens_server(account_id, "outlook", sample_tokens, "user@hotmail.com")

        new_tokens = {
            "access_token": "refreshed_token",
            "refresh_token": "new_refresh",
            "expires_in": 3600,
        }
        with patch("requests.post") as mock_post:
            mock_post.return_value.ok = True
            mock_post.return_value.json.return_value = new_tokens

            response = flask_client.post(f"/api/oauth/tokens/{account_id}/refresh")

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["expires_in"] > 0

    def test_refresh_endpoint_not_found(self, flask_client):
        """POST /api/oauth/tokens/<id>/refresh → 404 pour id inconnu."""
        response = flask_client.post("/api/oauth/tokens/nonexistent_id_xyz/refresh")

        assert response.status_code == 404

    def test_access_endpoint_auto_refreshes_expired_token(
        self, flask_client, account_id
    ):
        """GET /api/oauth/tokens/<id>/access avec token expiré → refresh auto + new access_token."""
        expired_tokens = {
            "access_token": "old_expired_token",
            "refresh_token": "valid_refresh_token",
            "expires_in": -60,  # Déjà expiré
        }
        store_tokens_server(account_id, "outlook", expired_tokens, "user@hotmail.com")

        refreshed = {
            "access_token": "brand_new_token",
            "refresh_token": "still_valid_refresh",
            "expires_in": 3600,
        }
        with patch("requests.post") as mock_post:
            mock_post.return_value.ok = True
            mock_post.return_value.json.return_value = refreshed

            response = flask_client.get(f"/api/oauth/tokens/{account_id}/access")

        assert response.status_code == 200
        data = response.get_json()
        assert data["access_token"] == "brand_new_token"


# ============================================================================
# Tests : Callback OAuth Outlook
# ============================================================================


class TestOutlookOAuthCallback:
    def test_missing_code_redirects_error(self, flask_client):
        """Pas de code param → redirect vers ?provider=outlook&error=missing_code."""
        response = flask_client.get("/api/oauth/outlook/callback?state=some_state")

        assert response.status_code == 302
        assert "provider=outlook" in response.location
        assert "error=missing_code" in response.location

    def test_provider_error_param_forwarded(self, flask_client):
        """?error=access_denied → redirect qui préserve le paramètre error."""
        response = flask_client.get(
            "/api/oauth/outlook/callback"
            "?error=access_denied&error_description=User+denied+consent"
        )

        assert response.status_code == 302
        assert "provider=outlook" in response.location
        assert "error=access_denied" in response.location
        assert "error_description=User" in response.location

    def _store_code_verifier(self, state: str):
        """Stocke un code_verifier PKCE pour le callback."""
        with oauth_module._code_verifier_lock:
            oauth_module._pending_code_verifiers[state] = {
                "code_verifier": "test_code_verifier_E2E",
                "timestamp": time.time(),
            }

    def _clear_code_verifier(self, state: str):
        with oauth_module._code_verifier_lock:
            oauth_module._pending_code_verifiers.pop(state, None)

    def test_token_exchange_success_creates_account(
        self, flask_client, mock_mgr, sample_tokens
    ):
        """Callback complet → tokens échangés + account créé dans le manager."""
        state = "outlook_state_new_account"
        self._store_code_verifier(state)
        mock_mgr.get_account.return_value = None  # Nouveau compte
        mock_mgr.current_account_id = "some_existing"

        try:
            with patch("requests.post") as mock_post, \
                 patch("requests.get") as mock_get:
                mock_post.return_value.ok = True
                mock_post.return_value.json.return_value = sample_tokens
                mock_get.return_value.ok = True
                mock_get.return_value.json.return_value = {
                    "mail": "user@hotmail.com",
                    "displayName": "Test User",
                }

                response = flask_client.get(
                    f"/api/oauth/outlook/callback?code=auth_code_123&state={state}"
                )
        finally:
            self._clear_code_verifier(state)

        assert response.status_code == 302
        assert "provider=outlook" in response.location
        assert "success=true" in response.location
        mock_mgr.add_account.assert_called_once()

    def test_existing_account_updates_status_not_duplicated(
        self, flask_client, mock_mgr, sample_tokens
    ):
        """Compte existant → update_account_status appelé, add_account non appelé."""
        state = "outlook_state_existing"
        self._store_code_verifier(state)

        existing_account = MagicMock()
        existing_account.id = "existing_outlook_abc"
        mock_mgr.get_account.return_value = existing_account
        mock_mgr.current_account_id = "existing_outlook_abc"

        try:
            with patch("requests.post") as mock_post, \
                 patch("requests.get") as mock_get:
                mock_post.return_value.ok = True
                mock_post.return_value.json.return_value = sample_tokens
                mock_get.return_value.ok = True
                mock_get.return_value.json.return_value = {"mail": "user@hotmail.com"}

                response = flask_client.get(
                    f"/api/oauth/outlook/callback?code=code_existing&state={state}"
                )
        finally:
            self._clear_code_verifier(state)

        assert response.status_code == 302
        mock_mgr.update_account_status.assert_called()
        mock_mgr.add_account.assert_not_called()

    def test_token_exchange_failure_redirects(self, flask_client):
        """Échange de token échoue (HTTP 400) → redirect avec error."""
        state = "outlook_state_fail"
        self._store_code_verifier(state)

        try:
            with patch("requests.post") as mock_post:
                mock_post.return_value.ok = False
                mock_post.return_value.json.return_value = {
                    "error": "invalid_grant",
                    "error_description": "Code expired",
                }

                response = flask_client.get(
                    f"/api/oauth/outlook/callback?code=bad_code&state={state}"
                )
        finally:
            self._clear_code_verifier(state)

        assert response.status_code == 302
        assert "error" in response.location

    def test_userinfo_failure_redirects(self, flask_client, sample_tokens):
        """Tokens OK mais Graph /me retourne 401 → redirect avec error=userinfo_failed."""
        state = "outlook_state_userinfo_fail"
        self._store_code_verifier(state)

        try:
            with patch("requests.post") as mock_post, \
                 patch("requests.get") as mock_get:
                mock_post.return_value.ok = True
                mock_post.return_value.json.return_value = sample_tokens
                mock_get.return_value.ok = False
                mock_get.return_value.status_code = 401

                response = flask_client.get(
                    f"/api/oauth/outlook/callback?code=code_ok&state={state}"
                )
        finally:
            self._clear_code_verifier(state)

        assert response.status_code == 302
        assert "error=userinfo_failed" in response.location

    def test_auto_activates_when_no_current_account(
        self, flask_client, mock_mgr, sample_tokens
    ):
        """Pas de compte actif → switch_to(account_id) appelé après création."""
        state = "outlook_state_auto_activate"
        self._store_code_verifier(state)

        mock_mgr.get_account.return_value = None
        mock_mgr.current_account_id = None  # Aucun compte actif

        try:
            with patch("requests.post") as mock_post, \
                 patch("requests.get") as mock_get:
                mock_post.return_value.ok = True
                mock_post.return_value.json.return_value = sample_tokens
                mock_get.return_value.ok = True
                mock_get.return_value.json.return_value = {"mail": "new@hotmail.com"}

                flask_client.get(
                    f"/api/oauth/outlook/callback?code=auto_code&state={state}"
                )
        finally:
            self._clear_code_verifier(state)

        mock_mgr.switch_to.assert_called()

    def test_stores_tokens_server_side(self, flask_client, mock_mgr, sample_tokens):
        """Après callback réussi, get_tokens_server(account_id) retourne les tokens."""
        state = "outlook_state_store_check"
        email = "stored_check@hotmail.com"
        expected_account_id = hashlib.sha256(f"outlook:{email}".encode()).hexdigest()[:16]

        self._store_code_verifier(state)
        mock_mgr.get_account.return_value = None
        mock_mgr.current_account_id = "other"

        try:
            with patch("requests.post") as mock_post, \
                 patch("requests.get") as mock_get:
                mock_post.return_value.ok = True
                mock_post.return_value.json.return_value = sample_tokens
                mock_get.return_value.ok = True
                mock_get.return_value.json.return_value = {"mail": email}

                flask_client.get(
                    f"/api/oauth/outlook/callback?code=store_code&state={state}"
                )
        finally:
            self._clear_code_verifier(state)

        stored = get_tokens_server(expected_account_id)
        assert stored is not None
        assert stored["provider"] == "outlook"
        assert stored["email"] == email


# ============================================================================
# Tests : Déconnexion Outlook
# ============================================================================


class TestOutlookDisconnect:
    def test_disconnect_removes_tokens(self, flask_client, mock_mgr, account_id, sample_tokens):
        """POST /api/oauth/<id>/disconnect supprime les tokens côté serveur."""
        store_tokens_server(account_id, "outlook", sample_tokens, "user@hotmail.com")
        assert get_tokens_server(account_id) is not None

        existing_account = MagicMock()
        existing_account.id = account_id
        mock_mgr.get_account.return_value = existing_account

        flask_client.post(f"/api/oauth/{account_id}/disconnect")

        assert get_tokens_server(account_id) is None

    def test_disconnect_updates_account_manager(
        self, flask_client, mock_mgr, account_id, sample_tokens
    ):
        """POST /api/oauth/<id>/disconnect met à jour le statut dans le manager."""
        store_tokens_server(account_id, "outlook", sample_tokens, "user@hotmail.com")

        existing_account = MagicMock()
        existing_account.id = account_id
        mock_mgr.get_account.return_value = existing_account

        response = flask_client.post(f"/api/oauth/{account_id}/disconnect")

        assert response.status_code == 200
        mock_mgr.update_account_status.assert_called_once()

    def test_disconnect_unknown_id_returns_404(self, flask_client, mock_mgr):
        """POST /api/oauth/<id>/disconnect → 404 pour compte inconnu dans le manager."""
        mock_mgr.get_account.return_value = None  # Compte inconnu

        response = flask_client.post("/api/oauth/unknown_id_xyz/disconnect")

        assert response.status_code == 404


# ============================================================================
# Tests : E2E réel Outlook OAuth (skippés sans credentials)
# ============================================================================


MICROSOFT_CLIENT_ID = os.getenv("MICROSOFT_CLIENT_ID")
MICROSOFT_CLIENT_SECRET = os.getenv("MICROSOFT_CLIENT_SECRET")
MICROSOFT_REFRESH_TOKEN = os.getenv("MICROSOFT_REFRESH_TOKEN")

_skip_real = pytest.mark.skipif(
    not (MICROSOFT_CLIENT_ID and MICROSOFT_CLIENT_SECRET and MICROSOFT_REFRESH_TOKEN),
    reason=(
        "MICROSOFT_CLIENT_ID, MICROSOFT_CLIENT_SECRET et MICROSOFT_REFRESH_TOKEN "
        "requis pour les tests réels"
    ),
)


class TestOutlookOAuthRealE2E:
    @_skip_real
    def test_real_token_refresh(self):
        """Rafraîchissement réel via login.microsoftonline.com → new access_token."""
        import requests as req_lib

        response = req_lib.post(
            oauth_module.MICROSOFT_TOKEN_URL,
            data={
                "client_id": MICROSOFT_CLIENT_ID,
                "client_secret": MICROSOFT_CLIENT_SECRET,
                "refresh_token": MICROSOFT_REFRESH_TOKEN,
                "grant_type": "refresh_token",
                "scope": (
                    "https://graph.microsoft.com/Mail.Read "
                    "https://graph.microsoft.com/Mail.Send "
                    "offline_access"
                ),
            },
        )
        assert response.ok, f"Refresh réel échoué : {response.text[:200]}"
        data = response.json()
        assert "access_token" in data

    @_skip_real
    def test_real_token_roundtrip(self):
        """store_tokens_server + get_tokens_server avec chiffrement Fernet réel."""
        test_id = "real_test_roundtrip_id"
        tokens = {
            "access_token": "test_real_access",
            "refresh_token": MICROSOFT_REFRESH_TOKEN,
            "expires_in": 3600,
        }
        try:
            result = store_tokens_server(test_id, "outlook", tokens, "real@hotmail.com")
            assert result is True

            retrieved = get_tokens_server(test_id)
            assert retrieved is not None
            assert retrieved["access_token"] == "test_real_access"
            assert retrieved["provider"] == "outlook"
        finally:
            delete_tokens_server(test_id)

    @_skip_real
    def test_real_graph_me(self):
        """GET graph.microsoft.com/v1.0/me avec refresh réel → mail ou userPrincipalName présent."""
        import requests as req_lib

        # D'abord rafraîchir pour obtenir un access_token valide
        resp = req_lib.post(
            oauth_module.MICROSOFT_TOKEN_URL,
            data={
                "client_id": MICROSOFT_CLIENT_ID,
                "client_secret": MICROSOFT_CLIENT_SECRET,
                "refresh_token": MICROSOFT_REFRESH_TOKEN,
                "grant_type": "refresh_token",
            },
        )
        assert resp.ok
        access_token = resp.json()["access_token"]

        me_resp = req_lib.get(
            oauth_module.MICROSOFT_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert me_resp.ok
        me_data = me_resp.json()
        assert "mail" in me_data or "userPrincipalName" in me_data
