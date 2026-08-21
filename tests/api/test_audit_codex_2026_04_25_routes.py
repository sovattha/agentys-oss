# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Regression tests for the 2026-04-25 Codex audit — app/api/ scope.

Each test maps to a finding in the audit sub-reports:
- tasks/audit-codex-2026-04-25/01-backend-security.md
- tasks/audit-codex-2026-04-25/02-account-isolation.md
- tasks/audit-codex-2026-04-25/04-stability.md
- tasks/audit-codex-2026-04-25/05-secrets-crypto.md

Tests are grouped by severity (Critical / High / Medium) and tagged with the
sub-report finding id so a future reviewer can trace a test back to the
exploit it prevents.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

@pytest.fixture
def app_client():
    """Lazy create_app — avoids polluting module-import order with sentry."""
    from app.api.app import create_app
    app = create_app({"TESTING": True})
    with app.test_client() as client:
        yield app, client


# -----------------------------------------------------------------------------
# CRITICAL — P0-1: SECRET_KEY guard rejects weak defaults
# -----------------------------------------------------------------------------

class TestP01OAuthSecretGuard:
    """Sub-report 05 F-CRIT-2 — _validate_prod_oauth_secret hardening."""

    def test_rejects_literal_dev_default_in_prod(self):
        from app.api.oauth import _validate_prod_oauth_secret
        with pytest.raises(RuntimeError, match="placeholder default"):
            _validate_prod_oauth_secret("agentys-dev-secret-change-in-prod", is_prod=True)

    def test_rejects_short_secret_in_prod(self):
        from app.api.oauth import _validate_prod_oauth_secret
        # Use a string that is too short BUT not in WEAK_DEFAULT_SECRETS so we
        # exercise the length branch.
        with pytest.raises(RuntimeError, match=">= 32 chars"):
            _validate_prod_oauth_secret("Aa1!Aa1!Aa1!", is_prod=True)

    def test_rejects_empty_secret_in_prod(self):
        from app.api.oauth import _validate_prod_oauth_secret
        with pytest.raises(RuntimeError, match="must be set"):
            _validate_prod_oauth_secret("", is_prod=True)

    def test_rejects_agentys_dev_prefix_in_prod(self):
        from app.api.oauth import _validate_prod_oauth_secret
        with pytest.raises(RuntimeError, match="placeholder default"):
            _validate_prod_oauth_secret("agentys-dev-anything-32-chars-long", is_prod=True)

    def test_rejects_known_weak_word_in_prod(self):
        from app.api.oauth import _validate_prod_oauth_secret
        with pytest.raises(RuntimeError, match="placeholder default"):
            _validate_prod_oauth_secret("change-me", is_prod=True)

    def test_accepts_strong_secret_in_prod(self):
        from app.api.oauth import _validate_prod_oauth_secret
        # Should not raise.
        _validate_prod_oauth_secret(
            "uYE2qVzn8YN3wG7mJ4l5k1c4Yz0KQ5jh1Hwh4xkrL7Y=" * 2,
            is_prod=True,
        )

    def test_dev_env_skips_guard(self):
        """In non-prod, the guard is a no-op even with the literal default."""
        from app.api.oauth import _validate_prod_oauth_secret
        _validate_prod_oauth_secret("agentys-dev-secret-change-in-prod", is_prod=False)


# -----------------------------------------------------------------------------
# CRITICAL — P0-2: OAuth disconnect ownership check
# -----------------------------------------------------------------------------

class TestP02OAuthDisconnectOwnership:
    """Sub-report 02 C-1 — disconnect_account previously had no _check_token_ownership."""

    def test_disconnect_blocks_cross_user(self, app_client, monkeypatch):
        app, client = app_client
        # Stub get_tokens_server so the route believes a token exists.
        from app.api import oauth as oauth_mod
        monkeypatch.setattr(
            oauth_mod,
            "get_tokens_server",
            lambda aid: {"email": "victim@example.com", "provider": "gmail"},
        )

        # Attacker JWT — different email than the token owner.
        from app.api.auth import _create_jwt
        attacker_jwt = _create_jwt(user_id=42, email="attacker@evil.com")

        resp = client.post(
            "/api/oauth/abc123def4567890/disconnect",
            headers={"Authorization": f"Bearer {attacker_jwt}"},
        )
        assert resp.status_code in (401, 404)
        # Importantly, NOT 200 — the previous bug accepted the request and
        # wiped the victim's tokens.

    def test_disconnect_allows_owner(self, app_client, monkeypatch):
        app, client = app_client
        from app.api import oauth as oauth_mod
        monkeypatch.setattr(
            oauth_mod,
            "get_tokens_server",
            lambda aid: {"email": "owner@example.com", "provider": "gmail"},
        )
        # Stub the destructive ops to return success without touching disk
        # or AccountManager.
        monkeypatch.setattr(oauth_mod, "delete_tokens_server", lambda aid: True)
        fake_manager = MagicMock()
        fake_manager.get_account.return_value = MagicMock(email="owner@example.com")
        fake_manager.update_account_status.return_value = True
        monkeypatch.setattr(oauth_mod, "get_account_manager", lambda: fake_manager)

        from app.api.auth import _create_jwt
        owner_jwt = _create_jwt(user_id=1, email="owner@example.com")

        resp = client.post(
            "/api/oauth/abc123def4567890/disconnect",
            headers={"Authorization": f"Bearer {owner_jwt}"},
        )
        # 200 (disconnect proceeds) is the expected happy path.
        assert resp.status_code == 200


# -----------------------------------------------------------------------------
# CRITICAL — P0-5 / CRIT-Stab-1: webhooks SSRF + daemon thread
# -----------------------------------------------------------------------------

class TestP05WebhooksSSRF:
    """Sub-report 01 CRIT-01 + sub-report 04 CRIT-1.

    The audit removed the `webhooks` blueprint entirely rather than patching
    it (zero callers, SSRF chain via outbound-fetch /test). These tests now
    pin the deletion: the module must stay gone, and the routes must 404.
    """

    def test_webhooks_module_removed(self):
        with pytest.raises(ModuleNotFoundError):
            import app.api.webhooks  # noqa: F401

    def test_webhooks_blueprint_routes_404(self, app_client):
        _, client = app_client
        for path in ("/webhooks/", "/webhooks/test"):
            resp = client.get(path)
            assert resp.status_code == 404, f"{path} should 404 (blueprint deleted), got {resp.status_code}"


# -----------------------------------------------------------------------------
# CRITICAL — CRIT-Iso-4: pending_draft.account_id None bypass
# -----------------------------------------------------------------------------

class TestCritIso4DraftAccountIdNoneBypass:
    """Sub-report 02 C-4 — strict comparison rejects unscoped drafts."""

    def test_helper_rejects_none_account_id(self):
        from app.api.routes_pending import _draft_belongs_to_account
        draft = MagicMock()
        draft.account_id = None
        assert _draft_belongs_to_account(draft, "1") is False

    def test_helper_rejects_empty_string_account_id(self):
        from app.api.routes_pending import _draft_belongs_to_account
        draft = MagicMock()
        draft.account_id = ""
        assert _draft_belongs_to_account(draft, "1") is False

    def test_helper_rejects_mismatched_account_id(self):
        from app.api.routes_pending import _draft_belongs_to_account
        draft = MagicMock()
        draft.account_id = 2
        assert _draft_belongs_to_account(draft, "1") is False

    def test_helper_accepts_matched_account_id(self):
        from app.api.routes_pending import _draft_belongs_to_account
        draft = MagicMock()
        draft.account_id = 1
        assert _draft_belongs_to_account(draft, "1") is True


# -----------------------------------------------------------------------------
# HIGH — HIGH-Backend-1: realtime_edit ownership
# -----------------------------------------------------------------------------

class TestHighBackend1RealtimeEditOwnership:
    """Sub-report 01 HIGH-01 — sessions accessible only by their owner."""

    def test_get_session_blocks_cross_user(self, app_client):
        app, client = app_client

        # Fake a stored session owned by user A.
        from app.api import realtime_edit as rte_mod
        fake_session = MagicMock()
        fake_session.session_id = "sess-1"
        fake_session.user_id = "alice@example.com"
        fake_session.current_text = "private text"
        fake_session.is_active = True
        from datetime import datetime
        fake_session.created_at = datetime(2026, 1, 1)
        fake_session.version = 1

        fake_use_case = MagicMock()
        fake_use_case.execute.return_value = fake_session
        fake_container = MagicMock()
        fake_container.get_edit_session_use_case.return_value = fake_use_case

        with patch.object(rte_mod, "_get_container", return_value=fake_container):
            from app.api.auth import _create_jwt
            bob_jwt = _create_jwt(user_id=2, email="bob@example.com")
            resp = client.get(
                "/api/realtime-edit/sessions/sess-1",
                headers={"Authorization": f"Bearer {bob_jwt}"},
            )
            assert resp.status_code == 404  # not 200 — content stays hidden

    def test_start_session_uses_jwt_email_not_body_user_id(self, app_client):
        app, client = app_client
        from app.api import realtime_edit as rte_mod
        from datetime import datetime

        fake_session = MagicMock()
        fake_session.session_id = "sess-2"
        fake_session.user_id = "alice@example.com"
        fake_session.current_text = ""
        fake_session.is_active = True
        fake_session.created_at = datetime(2026, 1, 1)

        fake_use_case = MagicMock()
        fake_use_case.execute.return_value = fake_session
        fake_container = MagicMock()
        fake_container.get_start_edit_session_use_case.return_value = fake_use_case

        with patch.object(rte_mod, "_get_container", return_value=fake_container):
            from app.api.auth import _create_jwt
            alice_jwt = _create_jwt(user_id=1, email="alice@example.com")
            resp = client.post(
                "/api/realtime-edit/sessions",
                headers={"Authorization": f"Bearer {alice_jwt}"},
                json={"user_id": "spoofed@evil.com", "initial_text": ""},
            )
            assert resp.status_code in (200, 201)
            # The use case MUST have been called with the JWT email, not the body.
            call = fake_use_case.execute.call_args
            assert call.kwargs["user_id"] == "alice@example.com"


# -----------------------------------------------------------------------------
# HIGH — HIGH-Backend-2: connectivity queue ownership
# -----------------------------------------------------------------------------

class TestHighBackend2ConnectivityQueueOwnership:
    """Sub-report 01 HIGH-02 — /api/connectivity/queue/<account_id>."""

    def test_queue_get_blocks_cross_user(self, app_client, monkeypatch):
        app, client = app_client

        # Stub: account_id=1 belongs to user 999; caller's JWT has user_id=2.
        fake_account = MagicMock()
        fake_account.user_id = 999
        fake_repo = MagicMock()
        fake_repo.get_by_id.return_value = fake_account

        # Patch the AccountRepository where _user_owns_account uses it.
        from contextlib import contextmanager
        @contextmanager
        def fake_session():
            yield MagicMock()
        monkeypatch.setattr("app.db.database.get_db_session", fake_session)
        monkeypatch.setattr(
            "app.db.repositories.account_repository.AccountRepository",
            lambda session: fake_repo,
        )

        from app.api.auth import _create_jwt
        attacker_jwt = _create_jwt(user_id=2, email="attacker@evil.com")
        resp = client.get(
            "/api/connectivity/queue/1",
            headers={"Authorization": f"Bearer {attacker_jwt}"},
        )
        assert resp.status_code == 404


# -----------------------------------------------------------------------------
# HIGH — HIGH-Backend-3: EmailTemplate per-user scoping
# -----------------------------------------------------------------------------

class TestHighBackend3EmailTemplateOwner:
    """Sub-report 01 HIGH-03 — owner_email scoping at route layer."""

    def test_owner_email_field_exists(self):
        from app.domain.entities.email_template import EmailTemplate
        t = EmailTemplate(
            id="abc", name="Test", category="OTHER", template_body="body",
            owner_email="alice@example.com",
        )
        assert t.owner_email == "alice@example.com"

    def test_sanitize_strips_owner_email_from_input(self):
        from app.api.email_templates import sanitize_template_data
        out = sanitize_template_data({
            "name": "X", "owner_email": "spoofed@evil.com",
            "template_body": "body", "category": "OTHER",
        })
        assert "owner_email" not in out  # client cannot inject owner


# -----------------------------------------------------------------------------
# HIGH — HIGH-Backend-4: ProxyFix + dev-login prod block
# -----------------------------------------------------------------------------

class TestHighBackend4ProxyFixAndDevLogin:
    """Sub-report 01 HIGH-04 + MED-01."""

    def test_proxyfix_attached_to_app(self, app_client):
        from werkzeug.middleware.proxy_fix import ProxyFix
        app, _ = app_client
        # ProxyFix wraps wsgi_app — verify by class name.
        assert isinstance(app.wsgi_app, ProxyFix)

    def test_dev_login_has_prod_disable_branch(self):
        """Verify the env-based block is present in dev_login source.

        Reloading the module would re-evaluate the module-level JWT_SECRET
        guard with FLASK_ENV=production, which trips its own RuntimeError
        (correctly, but for a different finding). Source-level inspection
        is the correct unit-level check here.
        """
        import inspect
        from app.api import auth as auth_mod
        src = inspect.getsource(auth_mod.dev_login)
        assert "DISABLE_DEV_LOGIN_IN_PROD" in src
        assert "_is_production_env" in src

    def test_is_production_helper_honors_railway_environment_name(self, monkeypatch):
        from app.api._auth_helpers import is_production
        for var in ("FLASK_ENV", "ENVIRONMENT", "RAILWAY_ENVIRONMENT", "RAILWAY_ENVIRONMENT_NAME"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
        assert is_production() is True


# -----------------------------------------------------------------------------
# HIGH — HIGH-05 Sentry DSN default, Swagger gate
# -----------------------------------------------------------------------------

class TestHigh05SentryDSN:
    """Sub-report 05 F-HIGH-1 — no hardcoded DSN default."""

    def test_no_hardcoded_sentry_dsn_default(self):
        import inspect
        from app.api import app as app_mod
        src = inspect.getsource(app_mod)
        # The previous default contained the org-specific URL prefix.
        assert "8027b6cb411074fca590fe5ccc821f9d" not in src


# -----------------------------------------------------------------------------
# MEDIUM — MED-04/07: header injection + display spoofing
# -----------------------------------------------------------------------------

class TestMedHeaderInjection:
    """Sub-report 01 MED-04 / MED-07 — CRLF + display-name guard."""

    def test_send_email_rejects_crlf_subject(self, app_client, monkeypatch):
        app, client = app_client
        # Bypass _get_authenticated_provider by stubbing it at the import site.
        with patch("app.api.routes_emails._get_authenticated_provider"):
            resp = client.post(
                "/api/emails/send-new",
                json={
                    "to": "victim@target.com",
                    "subject": "Hello\r\nBcc: shadow@evil.com",
                    "body": "test",
                },
            )
            assert resp.status_code == 400
            data = resp.get_json() or {}
            assert "invalid" in (data.get("error", "").lower())

    def test_send_email_rejects_brackets_in_from_name(self, app_client):
        app, client = app_client
        with patch("app.api.routes_emails._get_authenticated_provider"):
            resp = client.post(
                "/api/emails/send-new",
                json={
                    "to": "victim@target.com",
                    "subject": "Hello",
                    "body": "test",
                    "from_name": "Anthropic Support <support@anthropic.com>",
                },
            )
            assert resp.status_code == 400


# -----------------------------------------------------------------------------
# LOW — CORS wildcard guard
# -----------------------------------------------------------------------------

class TestCorsWildcardGuard:
    """Sub-report 01 LOW-04."""

    def test_create_app_refuses_wildcard_origin(self, monkeypatch):
        monkeypatch.setenv("API_CORS_ORIGINS", "*,https://app.agentys.io")
        from app.api.app import create_app
        with pytest.raises(RuntimeError, match=r"\*"):
            create_app()
