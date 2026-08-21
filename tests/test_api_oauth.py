# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour l'API REST OAuth (Story 1.2).

Couvre:
- GET /api/oauth/config
- GET /api/oauth/gmail/callback
- POST /api/oauth/session/store
- GET /api/oauth/session/<state>/poll
- POST /api/oauth/gmail/complete
- POST /api/oauth/<id>/disconnect
"""

import json
import time
import pytest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from app.api.app import create_app


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
        mock.return_value = manager
        yield manager


@pytest.fixture
def oauth_env_vars(monkeypatch):
    """Configure les variables d'environnement OAuth Gmail."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost:5050/api/oauth/gmail/callback")
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:1420")
    # Module-level constants read at import time — setenv n'a pas d'effet
    monkeypatch.setattr("app.api.oauth.GOOGLE_CLIENT_ID", "test-client-id.apps.googleusercontent.com")
    monkeypatch.setattr("app.api.oauth.GOOGLE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setattr("app.api.oauth.GOOGLE_REDIRECT_URI", "http://localhost:5050/api/oauth/gmail/callback")
    monkeypatch.setattr("app.api.oauth.FRONTEND_URL", "http://localhost:1420")


@pytest.fixture
def outlook_env_vars(monkeypatch):
    """Configure les variables d'environnement OAuth Outlook."""
    monkeypatch.setenv("MICROSOFT_CLIENT_ID", "test-microsoft-client-id")
    monkeypatch.setenv("MICROSOFT_CLIENT_SECRET", "test-microsoft-client-secret")
    monkeypatch.setenv("MICROSOFT_REDIRECT_URI", "http://localhost:5050/api/oauth/outlook/callback")
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:1420")
    monkeypatch.setattr("app.api.oauth.MICROSOFT_CLIENT_ID", "test-microsoft-client-id")
    monkeypatch.setattr("app.api.oauth.MICROSOFT_CLIENT_SECRET", "test-microsoft-client-secret")
    monkeypatch.setattr("app.api.oauth.MICROSOFT_REDIRECT_URI", "http://localhost:5050/api/oauth/outlook/callback")
    monkeypatch.setattr("app.api.oauth.FRONTEND_URL", "http://localhost:1420")


# ============================================================================
# Tests GET /api/oauth/config
# ============================================================================

class TestOAuthConfig:
    """Tests pour GET /api/oauth/config."""

    def test_get_config_success(self, client, oauth_env_vars):
        """Retourne la configuration OAuth Gmail."""
        response = client.get("/api/oauth/config")

        assert response.status_code == 200
        data = response.get_json()
        # Legacy fields (backwards compatibility)
        assert "client_id" in data
        assert "redirect_uri" in data
        assert "configured" in data
        assert data["configured"] is True
        # New Gmail nested config
        assert "gmail" in data
        assert data["gmail"]["configured"] is True

    def test_get_config_outlook(self, client, monkeypatch):
        """Retourne la configuration OAuth Outlook."""
        # Patch les variables au niveau du module oauth
        monkeypatch.setattr("app.api.oauth.MICROSOFT_CLIENT_ID", "test-microsoft-client-id")
        monkeypatch.setattr("app.api.oauth.MICROSOFT_CLIENT_SECRET", "test-microsoft-secret")

        response = client.get("/api/oauth/config")

        assert response.status_code == 200
        data = response.get_json()
        assert "outlook" in data
        assert data["outlook"]["configured"] is True
        assert data["outlook"]["client_id"] == "test-microsoft-client-id"

    def test_get_config_not_configured(self, client, monkeypatch):
        """Retourne configured=False si variables manquantes."""
        # Patch les variables au niveau du module oauth
        monkeypatch.setattr("app.api.oauth.GOOGLE_CLIENT_ID", "")
        monkeypatch.setattr("app.api.oauth.GOOGLE_CLIENT_SECRET", "")
        monkeypatch.setattr("app.api.oauth.MICROSOFT_CLIENT_ID", "")
        monkeypatch.setattr("app.api.oauth.MICROSOFT_CLIENT_SECRET", "")

        response = client.get("/api/oauth/config")

        assert response.status_code == 200
        data = response.get_json()
        assert data["configured"] is False
        assert data["gmail"]["configured"] is False
        assert data["outlook"]["configured"] is False


# ============================================================================
# Tests GET /api/oauth/gmail/callback
# ============================================================================

class TestGmailCallback:
    """Tests pour GET /api/oauth/gmail/callback."""

    def test_callback_with_code(self, client, oauth_env_vars):
        """Redirige vers le frontend avec le code."""
        response = client.get(
            "/api/oauth/gmail/callback?code=auth_code_123&state=state_abc"
        )

        assert response.status_code == 302
        assert "localhost:1420" in response.location
        assert "provider=gmail" in response.location
        assert "code=auth_code_123" in response.location
        assert "state=state_abc" in response.location

    def test_callback_with_error(self, client, oauth_env_vars):
        """Redirige vers le frontend avec l'erreur."""
        response = client.get(
            "/api/oauth/gmail/callback?error=access_denied&error_description=User%20denied"
        )

        assert response.status_code == 302
        assert "provider=gmail" in response.location
        assert "error=access_denied" in response.location
        # urllib.parse.urlencode encode l'espace en '+' (form-urlencoded standard) ;
        # %20 et + sont sémantiquement équivalents en query string.
        assert "error_description=User+denied" in response.location

    def test_callback_without_params(self, client, oauth_env_vars):
        """Redirige vers le frontend sans paramètres."""
        response = client.get("/api/oauth/gmail/callback")

        assert response.status_code == 302
        assert "localhost:1420" in response.location
        assert "provider=gmail" in response.location

    @patch("app.api.oauth.store_tokens_server", return_value=True)
    @patch("app.api.oauth.get_account_manager")
    @patch("app.api.oauth.requests.get")
    @patch("app.api.oauth.requests.post")
    def test_callback_redirects_error_when_db_upsert_fails(
        self, mock_post, mock_get, mock_mgr, mock_store, client, oauth_env_vars
    ):
        """Silent-failure fix (issue #320).

        Si la synchro DB SQLite échoue pendant le callback Gmail, le user
        ne doit PAS être redirigé avec ?success=true — sinon le compte
        n'existera jamais en base, le sync service ne le verra pas, et
        l'utilisateur pensera être connecté alors qu'aucun email n'arrivera.
        """
        import time as _time
        from app.api.oauth import _pending_code_verifiers, _code_verifier_lock

        state = "state_db_fail_001"
        with _code_verifier_lock:
            _pending_code_verifiers[state] = {
                "code_verifier": "v_xyz",
                "timestamp": _time.time(),
            }

        # Token exchange OK
        mock_post.return_value = MagicMock(
            ok=True,
            json=MagicMock(return_value={
                "access_token": "at_token",
                "refresh_token": "rt_token",
                "expires_in": 3600,
            }),
        )
        # Userinfo OK
        mock_get.return_value = MagicMock(
            ok=True,
            json=MagicMock(return_value={
                "email": "new-user@gmail.com",
                "name": "New User",
            }),
        )
        # Account manager benigne
        manager = MagicMock()
        manager.get_account.return_value = None
        manager.current_account_id = None
        mock_mgr.return_value = manager

        # Simuler la panne DB : get_db_session raise
        with patch(
            "app.db.database.get_db_session",
            side_effect=RuntimeError("Simulated DB down"),
        ):
            response = client.get(
                f"/api/oauth/gmail/callback?code=auth_code_x&state={state}"
            )

        assert response.status_code == 302
        assert "success=true" not in response.location, (
            f"Silent-failure régression : le callback a redirigé success=true malgré "
            f"l'échec DB. URL reçue : {response.location}"
        )
        assert "error=db_sync_failed" in response.location
        assert "provider=gmail" in response.location

    @patch("app.api.oauth.store_tokens_server", return_value=True)
    @patch("app.api.oauth.get_account_manager")
    @patch("app.api.oauth.requests.get")
    @patch("app.api.oauth.requests.post")
    def test_callback_retries_transient_sqlite_lock(
        self, mock_post, mock_get, mock_mgr, mock_store, client, oauth_env_vars
    ):
        """A short SQLite writer lock must not strand the user at db_sync_failed."""
        import time as _time
        from app.api.oauth import _pending_code_verifiers, _code_verifier_lock

        state = "state_db_lock_retry"
        with _code_verifier_lock:
            _pending_code_verifiers[state] = {
                "code_verifier": "v_xyz",
                "timestamp": _time.time(),
            }

        mock_post.return_value = MagicMock(
            ok=True,
            json=MagicMock(return_value={
                "access_token": "at_token",
                "refresh_token": "rt_token",
                "expires_in": 3600,
            }),
        )
        mock_get.return_value = MagicMock(
            ok=True,
            json=MagicMock(return_value={
                "email": "locked-user@gmail.com",
                "name": "Locked User",
            }),
        )
        manager = MagicMock()
        manager.get_account.return_value = None
        manager.current_account_id = None
        mock_mgr.return_value = manager

        locked_session = MagicMock()
        locked_session.commit.side_effect = RuntimeError("database is locked")
        ok_session = MagicMock()

        @contextmanager
        def _locked_cm():
            yield locked_session

        @contextmanager
        def _ok_cm():
            yield ok_session

        with patch("app.db.database.get_db_session", side_effect=[_locked_cm(), _ok_cm()]), \
             patch("app.db.repositories.account_repository.AccountRepository") as repo_cls, \
             patch("app.utils.signature.fetch_and_store_signature"), \
             patch("app.api.oauth._sleep_before_db_sync_retry") as sleep_mock:
            repo_cls.return_value.get_by_email.return_value = MagicMock()
            response = client.get(
                f"/api/oauth/gmail/callback?code=auth_code_x&state={state}"
            )

        assert response.status_code == 302
        assert "success=true" in response.location
        assert "error=db_sync_failed" not in response.location
        sleep_mock.assert_called_once_with(1.0)
        # Retry loop ran exactly twice: attempt 1 committed → locked, attempt 2
        # committed → ok. Assert on the two sessions' commits, NOT on
        # repo_cls.call_count — the signature-fetch step's api_usage_probe also
        # resolves the account via AccountRepository, so a global construction
        # count is >2 and unrelated to the retry behaviour under test.
        locked_session.commit.assert_called_once()
        ok_session.commit.assert_called_once()

    @patch("app.api.oauth.store_tokens_server", return_value=True)
    @patch("app.api.oauth.get_account_manager")
    @patch("app.api.oauth.requests.get")
    @patch("app.api.oauth.requests.post")
    def test_mobile_callback_redirects_to_app_after_server_side_exchange(
        self, mock_post, mock_get, mock_mgr, mock_store, client, oauth_env_vars
    ):
        """Mobile OAuth must return to the native app after the backend stores the session."""
        from app.api import oauth as oauth_mod

        state = "mobile_state_001"
        with oauth_mod._code_verifier_lock:
            oauth_mod._pending_code_verifiers[state] = {
                "code_verifier": "mobile_verifier",
                "client_type": "mobile",
                "timestamp": time.time(),
            }

        mock_post.return_value = MagicMock(
            ok=True,
            json=MagicMock(return_value={
                "access_token": "at_token",
                "refresh_token": "rt_token",
                "expires_in": 3600,
            }),
        )
        mock_get.return_value = MagicMock(
            ok=True,
            json=MagicMock(return_value={
                "email": "mobile-user@gmail.com",
                "name": "Mobile User",
            }),
        )
        manager = MagicMock()
        manager.get_account.return_value = None
        manager.current_account_id = None
        mock_mgr.return_value = manager

        fake_session = MagicMock()
        fake_session.query.return_value.filter_by.return_value.first.return_value = MagicMock(
            signature_user_modified=True
        )

        @contextmanager
        def _db_cm():
            yield fake_session

        with patch("app.db.database.get_db_session", return_value=_db_cm()), \
             patch("app.db.repositories.account_repository.AccountRepository") as repo_cls, \
             patch.object(oauth_mod, "_save_verifiers_to_file"):
            repo_cls.return_value.get_by_email.return_value = MagicMock(user_id=1694432691)
            response = client.get(
                f"/api/oauth/gmail/callback?code=auth_code_x&state={state}"
            )

        assert response.status_code == 302
        assert response.location.startswith("agentys://oauth-complete?")
        assert "success=true" in response.location
        assert f"state={state}" in response.location
        assert "mobile-user%40gmail.com" not in response.location
        assert "at_token" not in response.location
        with oauth_mod._pending_oauth_lock:
            assert oauth_mod._pending_oauth_sessions[state]["email"] == "mobile-user@gmail.com"
            oauth_mod._pending_oauth_sessions.pop(state, None)


# ============================================================================
# Tests GET /api/oauth/outlook/callback
# ============================================================================

class TestOutlookCallback:
    """Tests pour GET /api/oauth/outlook/callback."""

    def test_callback_with_code(self, client, outlook_env_vars):
        """Redirige vers le frontend avec le code."""
        response = client.get(
            "/api/oauth/outlook/callback?code=outlook_code_123&state=state_xyz"
        )

        assert response.status_code == 302
        assert "localhost:1420" in response.location
        assert "provider=outlook" in response.location
        assert "code=outlook_code_123" in response.location
        assert "state=state_xyz" in response.location

    def test_callback_with_error(self, client, outlook_env_vars):
        """Redirige vers le frontend avec l'erreur."""
        response = client.get(
            "/api/oauth/outlook/callback?error=access_denied&error_description=User%20denied%20consent"
        )

        assert response.status_code == 302
        assert "provider=outlook" in response.location
        assert "error=access_denied" in response.location
        assert "error_description=User%20denied%20consent" in response.location

    def test_callback_without_params(self, client, outlook_env_vars):
        """Redirige vers le frontend sans paramètres."""
        response = client.get("/api/oauth/outlook/callback")

        assert response.status_code == 302
        assert "localhost:1420" in response.location
        assert "provider=outlook" in response.location

    def test_callback_recovers_verifier_from_disk_when_memory_misses(
        self, client, outlook_env_vars, tmp_path, monkeypatch
    ):
        """Multi-worker safety regression (2026-04-25, M365 corporate fix).

        Symptom : un user M365 pro tombait sur "Malformed auth code." parce que
        le worker gunicorn qui servait /pkce/store n'était pas celui qui recevait
        le callback. Le verifier était bien sur disque (volume Railway persistant)
        mais invisible dans la dict en mémoire du worker du callback. Le code
        retombait sur le redirect-to-frontend qui pouvait ensuite échouer côté
        Microsoft (token déjà consommé, encodage perdu, etc.).

        Ce test simule le scénario : on écrit le verifier sur disque sans toucher
        à la mémoire, puis on hit le callback. Le lookup-with-disk-fallback doit
        réussir et l'échange Microsoft doit être tenté server-side (pas de
        redirect-to-frontend).
        """
        from app.api import oauth as oauth_mod

        state = "state_multi_worker_001"

        # Simulate worker A having written the verifier to disk while worker B
        # (this process) has an empty in-memory dict.
        pkce_file = tmp_path / "pkce_verifiers.json"
        pkce_file.write_text(
            json.dumps({state: {"code_verifier": "v_disk_only", "timestamp": time.time()}})
        )
        monkeypatch.setattr(oauth_mod, "_PKCE_FILE", str(pkce_file))
        # Wipe in-memory state so the lookup must hit disk to succeed.
        with oauth_mod._code_verifier_lock:
            oauth_mod._pending_code_verifiers.clear()

        with patch("app.api.oauth.requests.post") as mock_post, \
             patch("app.api.oauth.requests.get") as mock_get, \
             patch("app.api.oauth.get_account_manager") as mock_mgr, \
             patch("app.api.oauth.store_tokens_server", return_value=True):
            mock_post.return_value = MagicMock(
                ok=True,
                json=MagicMock(return_value={
                    "access_token": "at",
                    "refresh_token": "rt",
                    "expires_in": 3600,
                }),
            )
            mock_get.return_value = MagicMock(
                ok=True,
                json=MagicMock(return_value={
                    "mail": "pro@m365corp.com",
                    "displayName": "Pro User",
                }),
            )
            manager = MagicMock()
            manager.get_account.return_value = None
            manager.current_account_id = None
            mock_mgr.return_value = manager

            response = client.get(
                f"/api/oauth/outlook/callback?code=long_m365_auth_code&state={state}"
            )

        # Verifier was found on disk → server-side exchange ran → no fallback redirect.
        assert response.status_code == 302
        assert "code=long_m365_auth_code" not in response.location, (
            f"Régression multi-worker : le callback est tombé sur le fallback "
            f"redirect-to-frontend au lieu d'utiliser le verifier sur disque. "
            f"URL = {response.location}"
        )
        # Token exchange was actually attempted with Microsoft. The callback now
        # also runs best-effort signature sync, which can fire token-refresh
        # POSTs — 2026-06-02 #4 made Outlook signature import functional instead
        # of a silent no-op (OutlookAdapter is now built via account_id, so it
        # loads the stored tokens and hits Graph). So assert on the FIRST post
        # (the authorization-code exchange) rather than the total call count.
        assert mock_post.call_count >= 1
        exchange_call = mock_post.call_args_list[0]
        assert exchange_call[1]["data"]["code"] == "long_m365_auth_code"
        assert exchange_call[1]["data"]["code_verifier"] == "v_disk_only"

    def test_complete_strips_whitespace_from_code(
        self, client, outlook_env_vars
    ):
        """Defensive strip : un code OAuth avec whitespace de bord (corp proxy
        peut injecter \\r\\n) ne doit pas être envoyé tel quel à Microsoft."""
        with patch("app.api.oauth.requests.post") as mock_post, \
             patch("app.api.oauth.requests.get") as mock_get, \
             patch("app.api.oauth.get_account_manager") as mock_mgr, \
             patch("app.api.oauth.store_tokens_server", return_value=True):
            mock_post.return_value = MagicMock(
                ok=True,
                json=MagicMock(return_value={
                    "access_token": "at", "refresh_token": "rt", "expires_in": 3600,
                }),
            )
            mock_get.return_value = MagicMock(
                ok=True,
                json=MagicMock(return_value={"mail": "u@m365.com"}),
            )
            manager = MagicMock()
            manager.get_account.return_value = None
            manager.current_account_id = None
            mock_mgr.return_value = manager

            response = client.post(
                "/api/oauth/outlook/complete",
                data=json.dumps({
                    "code": "  trimmed_code\r\n",
                    "state": "  state_x  ",
                    "code_verifier": "  v_yz  ",
                    "redirect_uri": "  http://localhost:5050/api/oauth/outlook/callback  ",
                }),
                content_type="application/json",
            )

            assert response.status_code == 200
            sent = mock_post.call_args[1]["data"]
            assert sent["code"] == "trimmed_code"
            assert sent["code_verifier"] == "v_yz"
            assert sent["redirect_uri"] == "http://localhost:5050/api/oauth/outlook/callback"


# ============================================================================
# Tests POST /api/oauth/session/store
# ============================================================================

class TestStoreSession:
    """Tests pour POST /api/oauth/session/store."""

    def test_store_session_success(self, client):
        """Stocke une session OAuth avec succès."""
        response = client.post(
            "/api/oauth/session/store",
            data=json.dumps({
                "state": "test_state_123",
                "tokens": {
                    "access_token": "ya29.test",
                    "refresh_token": "1//test",
                    "expires_in": 3600,
                },
                "email": "test@gmail.com",
            }),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True

    def test_store_session_missing_state(self, client):
        """Retourne 400 si state manquant."""
        response = client.post(
            "/api/oauth/session/store",
            data=json.dumps({"tokens": {}}),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "state" in response.get_json()["error"].lower()

    def test_store_session_no_json(self, client):
        """Retourne 415 si pas de Content-Type JSON."""
        response = client.post("/api/oauth/session/store")

        # Flask retourne 415 UNSUPPORTED MEDIA TYPE sans Content-Type
        assert response.status_code in (400, 415)

    def test_store_session_with_error(self, client):
        """Stocke une session avec erreur."""
        response = client.post(
            "/api/oauth/session/store",
            data=json.dumps({
                "state": "test_state_error",
                "error": "access_denied",
            }),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True


# ============================================================================
# Tests GET /api/oauth/session/<state>/poll
# ============================================================================

class TestPollSession:
    """Tests pour GET /api/oauth/session/<state>/poll."""

    def test_poll_session_not_found(self, client):
        """Retourne 200 avec status=pending si session non trouvée (pas 404, pour éviter les erreurs console)."""
        response = client.get("/api/oauth/session/unknown_state/poll")

        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "pending"

    def test_poll_session_success(self, client):
        """Retourne les tokens après stockage."""
        # D'abord stocker une session
        client.post(
            "/api/oauth/session/store",
            data=json.dumps({
                "state": "poll_test_state",
                "tokens": {
                    "access_token": "ya29.poll_test",
                    "refresh_token": "1//poll_test",
                    "expires_in": 3600,
                },
                "email": "poll@gmail.com",
            }),
            content_type="application/json",
        )

        # Puis récupérer la session
        response = client.get("/api/oauth/session/poll_test_state/poll")

        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "success"
        assert data["email"] == "poll@gmail.com"
        # FIX AUTH-001 (audit P0): le polling endpoint ne retourne plus
        # `tokens` (raw OAuth access/refresh) mais un JWT signé via la clé
        # `token`. La session de test n'a pas de jwt → token=None mais la
        # clé doit exister.
        assert "token" in data

    def test_poll_session_one_time_use(self, client):
        """La session est supprimée après récupération."""
        # Stocker une session
        client.post(
            "/api/oauth/session/store",
            data=json.dumps({
                "state": "one_time_state",
                "tokens": {"access_token": "test"},
                "email": "test@gmail.com",
            }),
            content_type="application/json",
        )

        # Première récupération réussit
        response1 = client.get("/api/oauth/session/one_time_state/poll")
        assert response1.status_code == 200

        # Deuxième récupération retourne pending (session supprimée)
        response2 = client.get("/api/oauth/session/one_time_state/poll")
        assert response2.status_code == 200
        assert response2.get_json()["status"] == "pending"

    def test_poll_session_with_error(self, client):
        """Retourne l'erreur si session en erreur."""
        # Stocker une session avec erreur
        client.post(
            "/api/oauth/session/store",
            data=json.dumps({
                "state": "error_state",
                "error": "access_denied",
            }),
            content_type="application/json",
        )

        response = client.get("/api/oauth/session/error_state/poll")

        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "error"
        assert data["error"] == "access_denied"


# ============================================================================
# Tests POST /api/oauth/gmail/complete
# ============================================================================

class TestCompleteOAuth:
    """Tests pour POST /api/oauth/gmail/complete (échange code → token)."""

    def _mock_gmail_exchange(self, mock_account_manager):
        """Configure les mocks pour un échange Gmail réussi."""
        mock_account_manager.get_account.return_value = None
        mock_account_manager.current_account_id = None
        return {
            "token_response": MagicMock(
                ok=True,
                json=MagicMock(return_value={
                    "access_token": "ya29.test-access",
                    "refresh_token": "1//test-refresh",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                }),
            ),
            "userinfo_response": MagicMock(
                ok=True,
                json=MagicMock(return_value={
                    "email": "test@gmail.com",
                    "name": "Test User",
                }),
            ),
        }

    @patch("app.db.database.get_db_session")
    @patch("app.api.oauth.store_tokens_server", return_value=True)
    @patch("app.api.oauth.requests.get")
    @patch("app.api.oauth.requests.post")
    def test_complete_gmail_success(
        self, mock_post, mock_get, mock_store, mock_db, client, mock_account_manager
    ):
        """Flow complet : code + verifier → token exchange → userinfo → 200."""
        mocks = self._mock_gmail_exchange(mock_account_manager)
        mock_post.return_value = mocks["token_response"]
        mock_get.return_value = mocks["userinfo_response"]

        response = client.post(
            "/api/oauth/gmail/complete",
            data=json.dumps({
                "code": "auth_code_123",
                "state": "state_abc",
                "code_verifier": "verifier_xyz",
            }),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["email"] == "test@gmail.com"
        assert "account_id" in data
        # B-03 : le happy path expose db_synced=true.
        assert data["db_synced"] is True
        mock_post.assert_called_once()
        mock_store.assert_called_once()

    @patch("app.db.database.get_db_session")
    @patch("app.api.oauth.store_tokens_server", return_value=True)
    @patch("app.api.oauth.requests.get")
    @patch("app.api.oauth.requests.post")
    def test_complete_gmail_db_sync_failure_sets_db_synced_false(
        self, mock_post, mock_get, mock_store, mock_db, client, mock_account_manager
    ):
        """B-03 (famille #320, audit 2026-06-11) : un échec de sync DB ne doit
        plus être avalé — le flow reste un succès (JWT émis) mais la réponse ET
        la session de polling portent db_synced=false."""
        from app.api import oauth as oauth_module

        mocks = self._mock_gmail_exchange(mock_account_manager)
        mock_post.return_value = mocks["token_response"]
        mock_get.return_value = mocks["userinfo_response"]
        mock_db.side_effect = RuntimeError("database is locked")

        try:
            response = client.post(
                "/api/oauth/gmail/complete",
                data=json.dumps({
                    "code": "auth_code_123",
                    "state": "state_db_fail",
                    "code_verifier": "verifier_xyz",
                }),
                content_type="application/json",
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data["success"] is True  # le flow JWT n'est pas cassé
            assert data["token"]
            assert data["db_synced"] is False
            # La session de polling porte aussi le flag.
            session = oauth_module._pending_oauth_sessions.get("state_db_fail")
            assert session is not None
            assert session["db_synced"] is False
        finally:
            oauth_module._pending_oauth_sessions.pop("state_db_fail", None)

    def test_complete_gmail_missing_code(self, client):
        """Retourne 400 si code manquant."""
        response = client.post(
            "/api/oauth/gmail/complete",
            data=json.dumps({
                "state": "state_abc",
                "code_verifier": "verifier_xyz",
            }),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "code" in response.get_json()["error"].lower()

    def test_complete_gmail_missing_verifier(self, client):
        """Retourne 400 si code_verifier manquant (et pas dans le backend store)."""
        response = client.post(
            "/api/oauth/gmail/complete",
            data=json.dumps({
                "code": "auth_code_123",
                "state": "state_abc",
            }),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "code_verifier" in response.get_json()["error"].lower()

    @patch("app.api.oauth.store_tokens_server", return_value=True)
    @patch("app.api.oauth.requests.post")
    def test_complete_gmail_token_exchange_failure(
        self, mock_post, mock_store, client
    ):
        """Retourne 400 si l'échange de tokens échoue."""
        mock_post.return_value = MagicMock(
            ok=False,
            json=MagicMock(return_value={
                "error": "invalid_grant",
                "error_description": "Code has expired",
            }),
        )

        response = client.post(
            "/api/oauth/gmail/complete",
            data=json.dumps({
                "code": "expired_code",
                "state": "state_abc",
                "code_verifier": "verifier_xyz",
            }),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "error" in response.get_json()

    def test_complete_gmail_no_json(self, client):
        """Retourne 400/415 si pas de Content-Type JSON."""
        response = client.post("/api/oauth/gmail/complete")

        assert response.status_code in (400, 415)


# ============================================================================
# Tests POST /api/oauth/outlook/complete
# ============================================================================

class TestCompleteOutlookOAuth:
    """Tests pour POST /api/oauth/outlook/complete (échange code → token)."""

    def _mock_outlook_exchange(self, mock_account_manager):
        """Configure les mocks pour un échange Outlook réussi."""
        mock_account_manager.get_account.return_value = None
        mock_account_manager.current_account_id = None
        return {
            "token_response": MagicMock(
                ok=True,
                json=MagicMock(return_value={
                    "access_token": "eyJ0eXAi.test-access",
                    "refresh_token": "M.test-refresh",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                }),
            ),
            "userinfo_response": MagicMock(
                ok=True,
                json=MagicMock(return_value={
                    "mail": "test@outlook.com",
                    "displayName": "Test User",
                    "userPrincipalName": "test@outlook.com",
                }),
            ),
        }

    @patch("app.db.database.get_db_session")
    @patch("app.api.oauth.store_tokens_server", return_value=True)
    @patch("app.api.oauth.requests.get")
    @patch("app.api.oauth.requests.post")
    def test_complete_outlook_success(
        self, mock_post, mock_get, mock_store, mock_db, client, mock_account_manager
    ):
        """Flow complet : code + verifier → token exchange → userinfo → 200."""
        mocks = self._mock_outlook_exchange(mock_account_manager)
        mock_post.return_value = mocks["token_response"]
        mock_get.return_value = mocks["userinfo_response"]

        response = client.post(
            "/api/oauth/outlook/complete",
            data=json.dumps({
                "code": "outlook_code_123",
                "state": "state_xyz",
                "code_verifier": "verifier_abc",
            }),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["email"] == "test@outlook.com"
        assert "account_id" in data
        # B-03 : le happy path expose db_synced=true.
        assert data["db_synced"] is True
        mock_post.assert_called_once()
        mock_store.assert_called_once()

    @patch("app.db.database.get_db_session")
    @patch("app.api.oauth.store_tokens_server", return_value=True)
    @patch("app.api.oauth.requests.get")
    @patch("app.api.oauth.requests.post")
    def test_complete_outlook_db_sync_failure_sets_db_synced_false(
        self, mock_post, mock_get, mock_store, mock_db, client, mock_account_manager
    ):
        """B-03 : même garantie que gmail/complete — échec de sync DB propagé
        via db_synced=false dans la réponse et la session de polling."""
        from app.api import oauth as oauth_module

        mocks = self._mock_outlook_exchange(mock_account_manager)
        mock_post.return_value = mocks["token_response"]
        mock_get.return_value = mocks["userinfo_response"]
        mock_db.side_effect = RuntimeError("database is locked")

        try:
            response = client.post(
                "/api/oauth/outlook/complete",
                data=json.dumps({
                    "code": "outlook_code_123",
                    "state": "state_db_fail_ms",
                    "code_verifier": "verifier_abc",
                }),
                content_type="application/json",
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data["success"] is True
            assert data["token"]
            assert data["db_synced"] is False
            session = oauth_module._pending_oauth_sessions.get("state_db_fail_ms")
            assert session is not None
            assert session["db_synced"] is False
        finally:
            oauth_module._pending_oauth_sessions.pop("state_db_fail_ms", None)

    @patch("app.db.database.get_db_session")
    @patch("app.api.oauth.store_tokens_server", return_value=True)
    @patch("app.api.oauth.requests.get")
    @patch("app.api.oauth.requests.post")
    def test_complete_outlook_oid_divergence_still_succeeds(
        self, mock_post, mock_get, mock_store, mock_db, client, mock_account_manager
    ):
        """Regression (2026-05-20): /complete must NOT 400 when the id_token's
        `oid` differs from Graph `/me`'s `id`.

        This reproduces the exact production lockout: Microsoft authenticated
        the user and both the token exchange and the userinfo fetch succeeded,
        but the old nOAuth guard hard-rejected the oid/userinfo divergence with
        `{"error":"identity_invalid","reason":"oid_userinfo_mismatch"}`. That
        divergence is legitimate for several Microsoft account types, so it is
        now logged (not fatal) and sign-in completes with 200.
        """
        import base64
        import json as _json
        self._mock_outlook_exchange(mock_account_manager)

        # id_token carries oid=alice-oid; Graph /me returns a DIFFERENT id.
        claims = {"oid": "alice-oid", "tid": "tenant-x", "email": "test@outlook.com"}
        payload_b64 = base64.urlsafe_b64encode(
            _json.dumps(claims).encode()
        ).rstrip(b"=").decode()
        fake_id_token = f"eyJhbGciOiJIUzI1NiJ9.{payload_b64}.sig"

        mock_post.return_value = MagicMock(
            ok=True,
            json=MagicMock(return_value={
                "access_token": "eyJ0eXAi.test-access",
                "refresh_token": "M.test-refresh",
                "id_token": fake_id_token,
                "expires_in": 3600,
                "token_type": "Bearer",
            }),
        )
        mock_get.return_value = MagicMock(
            ok=True,
            json=MagicMock(return_value={
                "id": "graph-different-id",  # ≠ id_token oid → old guard 400'd
                "mail": "test@outlook.com",
                "displayName": "Test User",
                "userPrincipalName": "test@outlook.com",
            }),
        )

        response = client.post(
            "/api/oauth/outlook/complete",
            data=json.dumps({
                "code": "outlook_code_123",
                "state": "state_xyz",
                "code_verifier": "verifier_abc",
            }),
            content_type="application/json",
        )

        assert response.status_code == 200, response.get_data(as_text=True)
        data = response.get_json()
        assert data["success"] is True
        assert data["email"] == "test@outlook.com"

    def test_complete_outlook_missing_code(self, client):
        """Retourne 400 si code manquant."""
        response = client.post(
            "/api/oauth/outlook/complete",
            data=json.dumps({
                "state": "state_xyz",
                "code_verifier": "verifier_abc",
            }),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "code" in response.get_json()["error"].lower()

    def test_complete_outlook_missing_verifier(self, client):
        """Retourne 400 si code_verifier manquant."""
        response = client.post(
            "/api/oauth/outlook/complete",
            data=json.dumps({
                "code": "outlook_code_123",
                "state": "state_xyz",
            }),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "code_verifier" in response.get_json()["error"].lower()

    @patch("app.api.oauth.store_tokens_server", return_value=True)
    @patch("app.api.oauth.requests.post")
    def test_complete_outlook_token_exchange_failure(
        self, mock_post, mock_store, client
    ):
        """Retourne 400 si l'échange de tokens échoue."""
        mock_post.return_value = MagicMock(
            ok=False,
            json=MagicMock(return_value={
                "error": "invalid_grant",
                "error_description": "Code has expired",
            }),
        )

        response = client.post(
            "/api/oauth/outlook/complete",
            data=json.dumps({
                "code": "expired_code",
                "state": "state_xyz",
                "code_verifier": "verifier_abc",
            }),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "error" in response.get_json()

    @patch("app.api.oauth._capture_oauth_identity_rejection")
    @patch("app.api._auth_helpers.is_production", return_value=True)
    @patch("app.api.oauth.requests.get")
    @patch("app.api.oauth.requests.post")
    def test_complete_outlook_identity_invalid_is_captured(
        self, mock_post, mock_get, _mock_is_production, mock_capture, client
    ):
        """Capture dans Sentry les rejets d'identité OAuth gérés."""
        mock_post.return_value = MagicMock(
            ok=True,
            json=MagicMock(return_value={
                "access_token": "eyJ0eXAi.test-access",
                "refresh_token": "M.test-refresh",
                "expires_in": 3600,
                "token_type": "Bearer",
            }),
        )
        mock_get.return_value = MagicMock(
            ok=True,
            json=MagicMock(return_value={
                "id": "azure-user-id",
                "mail": "test@outlook.com",
                "displayName": "Test User",
                "userPrincipalName": "test@outlook.com",
            }),
        )

        response = client.post(
            "/api/oauth/outlook/complete",
            data=json.dumps({
                "code": "outlook_code_123",
                "state": "state_xyz",
                "code_verifier": "verifier_abc",
            }),
            content_type="application/json",
        )

        assert response.status_code == 400
        body = response.get_json()
        assert body["error"] == "identity_invalid"
        # #557 follow-up: the JSON `reason` MUST be the normalized key (same
        # set as Sentry's `oauth.identity_reject_reason` tag), not the raw
        # French rejection text. The SPA maps this key to a user-facing
        # message (`Your Agentys app is out of date…` for id_token_absent).
        # Mocks above omit `id_token`, so this fixture triggers id_token_absent.
        assert body["reason"] == "id_token_absent"
        mock_capture.assert_called_once()
        assert mock_capture.call_args.kwargs["provider"] == "outlook"
        assert mock_capture.call_args.kwargs["flow"] == "complete"
        assert "id_token" in mock_capture.call_args.kwargs["reason"]

    @patch("app.api.oauth._capture_oauth_identity_rejection")
    @patch("app.api._auth_helpers.is_production", return_value=True)
    @patch("app.api.oauth.requests.get")
    @patch("app.api.oauth.requests.post")
    def test_outlook_callback_redirect_includes_reason_key(
        self, mock_post, mock_get, _mock_is_production, _mock_capture, client, monkeypatch
    ):
        """Le GET /outlook/callback redirige avec `&reason=<key>` pour que
        le SPA puisse humaniser l'identity_invalid sans devoir contacter le
        backend pour le détail (#557 follow-up).
        """
        monkeypatch.setattr("app.api.oauth.FRONTEND_URL", "http://localhost:1420")
        monkeypatch.setattr("app.api.oauth.MICROSOFT_CLIENT_ID", "test-microsoft-client-id")
        monkeypatch.setattr("app.api.oauth.MICROSOFT_CLIENT_SECRET", "test-microsoft-secret")
        monkeypatch.setattr(
            "app.api.oauth.MICROSOFT_REDIRECT_URI",
            "http://localhost:5050/api/oauth/outlook/callback",
        )

        # Seed _pending_code_verifiers so the callback path can resolve our
        # state (normally written by /pkce/store during the auth-URL build).
        from app.api import oauth as oauth_module
        with oauth_module._code_verifier_lock:
            oauth_module._pending_code_verifiers["state_redirect_xyz"] = {
                "code_verifier": "verifier_abc",
                "timestamp": time.time(),
            }

        # Token response omits id_token → triggers id_token_absent in prod.
        mock_post.return_value = MagicMock(
            ok=True,
            json=MagicMock(return_value={
                "access_token": "eyJ0eXAi.test-access",
                "refresh_token": "M.test-refresh",
                "expires_in": 3600,
                "token_type": "Bearer",
            }),
        )
        mock_get.return_value = MagicMock(
            ok=True,
            json=MagicMock(return_value={
                "id": "azure-user-id",
                "mail": "test@outlook.com",
                "userPrincipalName": "test@outlook.com",
            }),
        )

        response = client.get(
            "/api/oauth/outlook/callback?code=abc&state=state_redirect_xyz"
        )

        # 302 with reason in the redirect URL so the SPA can humanize.
        assert response.status_code == 302
        location = response.headers.get("Location", "")
        assert "error=identity_invalid" in location
        assert "reason=id_token_absent" in location

    def test_complete_outlook_no_json(self, client):
        """Retourne 400/415 si pas de Content-Type JSON."""
        response = client.post("/api/oauth/outlook/complete")

        assert response.status_code in (400, 415)


# ============================================================================
# Tests POST /api/oauth/<id>/disconnect
# ============================================================================

class TestDisconnectAccount:
    """Tests pour POST /api/oauth/<id>/disconnect."""

    def test_disconnect_success(self, client, mock_account_manager):
        """Déconnecte un compte avec succès."""
        mock_account = MagicMock()
        mock_account.id = "acc_to_disconnect"
        mock_account_manager.get_account.return_value = mock_account

        response = client.post("/api/oauth/acc_to_disconnect/disconnect")

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        mock_account_manager.update_account_status.assert_called_once()

    def test_disconnect_not_found(self, client, mock_account_manager):
        """Retourne 404 si compte non trouvé."""
        mock_account_manager.get_account.return_value = None

        response = client.post("/api/oauth/unknown_acc/disconnect")

        assert response.status_code == 404
        assert "not found" in response.get_json()["error"].lower()


# ============================================================================
# Tests Session Expiration
# ============================================================================

class TestSessionExpiration:
    """Tests pour l'expiration des sessions OAuth."""

    def test_session_cleanup_expired(self, client, monkeypatch):
        """Les sessions expirées sont nettoyées."""
        # Créer une session avec timestamp ancien
        from app.api import oauth

        with oauth._pending_oauth_lock:
            oauth._pending_oauth_sessions["expired_state"] = {
                "tokens": {"access_token": "old"},
                "email": "old@gmail.com",
                "timestamp": time.time() - 400,  # Plus de 5 minutes
            }

        # Stocker une nouvelle session déclenche le nettoyage
        client.post(
            "/api/oauth/session/store",
            data=json.dumps({
                "state": "new_state",
                "tokens": {"access_token": "new"},
            }),
            content_type="application/json",
        )

        # L'ancienne session ne devrait plus être accessible (returns pending, not the old data)
        response = client.get("/api/oauth/session/expired_state/poll")
        assert response.status_code == 200
        assert response.get_json()["status"] == "pending"


# ============================================================================
# Tests _save_tokens_to_file (silent-failure fix, issue #318)
# ============================================================================

class TestSaveTokensToFile:
    """Regression gate : `_save_tokens_to_file` doit propager les I/O errors
    au lieu de les avaler silencieusement — sinon le caller ne peut pas
    signaler à l'utilisateur que ses tokens ne sont pas persistés.
    """

    def test_save_tokens_raises_on_write_error(self, monkeypatch):
        """Issue #318 : si l'écriture disque échoue, on doit lever (pas avaler)."""
        from app.api import oauth

        def boom():
            raise PermissionError("Read-only filesystem")

        monkeypatch.setattr(oauth, "_ensure_data_dir", boom)

        with pytest.raises(PermissionError):
            oauth._save_tokens_to_file()

    def test_store_tokens_server_returns_false_when_persistence_fails(self, monkeypatch):
        """Corollaire : quand `_save_tokens_to_file` lève, `store_tokens_server`
        renvoie False — ce qui permet au callback de rediriger vers une page
        d'erreur plutôt que vers un faux success.
        """
        from app.api import oauth

        def boom():
            raise OSError("Disk full")

        monkeypatch.setattr(oauth, "_ensure_data_dir", boom)

        result = oauth.store_tokens_server(
            "acc_persistence_test",
            "gmail",
            {"access_token": "at", "refresh_token": "rt", "expires_in": 3600},
            "user@gmail.com",
        )
        assert result is False

    def test_save_tokens_uses_atomic_write(self, monkeypatch, tmp_path):
        """Issue #318 : écriture atomique via tempfile + os.replace.

        Garantit qu'un crash au milieu de l'écriture ne laisse jamais un
        fichier _TOKENS_FILE partiellement écrit / corrompu sur disque.
        """
        from app.api import oauth

        tokens_file = tmp_path / "tokens.json"
        monkeypatch.setattr(oauth, "_TOKENS_FILE", str(tokens_file))
        monkeypatch.setattr(oauth, "_ensure_data_dir", lambda: None)
        # Content test
        with oauth._server_tokens_lock:
            oauth._server_tokens.clear()
            oauth._server_tokens["acc_atomic"] = {
                "encrypted_data": "fake",
                "provider": "gmail",
                "email": "atomic@gmail.com",
            }

        oauth._save_tokens_to_file()

        # Le fichier final existe et contient les tokens
        assert tokens_file.exists()
        data = json.loads(tokens_file.read_text())
        assert "acc_atomic" in data
        # Aucun fichier .tmp orphelin
        leftover_tmp = list(tmp_path.glob("*.tmp*"))
        assert not leftover_tmp, f"Tmp files leaked: {leftover_tmp}"
