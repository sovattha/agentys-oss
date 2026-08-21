# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Regression tests for bugs found during the 2026-03-22 deep audit.

These tests guard against 7 regressions:
  1. Auto-reply background thread must receive account_id (not resolve via Flask g)
  2. Provider pool health check must reuse stored sock reference
  3. Mobile theme radius values must not regress
  4. Route mock paths: routes_emails owns email endpoints (not routes.py)
  5. Mark-read returns 200 + provider_synced when provider returns False
  6. Create-draft uses _get_authenticated_provider (not LegacyModuleLoader)
  7. _get_cached_email_response is in routes_emails (not routes.py)

pytest tests/test_regression_audit_2026_03.py -v
"""

import inspect
import re
import threading
from unittest.mock import MagicMock, Mock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def app():
    from app.api.app import create_app
    app = create_app(config={"TESTING": True})
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


# ===========================================================================
# 1. Auto-reply background thread receives account_id
# ===========================================================================

class TestAutoReplyAccountId:
    """BUG: _send_auto_replies_bg used _resolve_account_id_cached() inside a
    background thread where Flask request context (g.auth_user) is unavailable.
    In multi-user mode this caused wrong user signatures.

    FIX: account_id is now passed as parameter from the caller (inside request context).
    """

    def test_send_auto_replies_bg_accepts_account_id_param(self):
        """_send_auto_replies_bg must accept account_id as third parameter."""
        from app.api.routes_emails import _send_auto_replies_bg

        sig = inspect.signature(_send_auto_replies_bg)
        params = list(sig.parameters.keys())

        assert "account_id" in params, (
            "_send_auto_replies_bg must accept account_id parameter "
            "(resolved by caller inside request context, not inside background thread)"
        )

    def test_send_auto_replies_bg_does_not_call_resolve_cached(self):
        """The function body must NOT call _resolve_account_id_cached()."""
        from app.api.routes_emails import _send_auto_replies_bg

        source = inspect.getsource(_send_auto_replies_bg)
        assert "_resolve_account_id_cached()" not in source, (
            "_send_auto_replies_bg must not call _resolve_account_id_cached() — "
            "it runs in a background thread without Flask request context. "
            "account_id must be passed as parameter."
        )

    def test_call_sites_pass_account_id(self):
        """Every list_emails call site must pass account_id to _send_auto_replies_bg."""
        import app.api.routes_emails as mod

        source = inspect.getsource(mod)
        # Find all submit_background calls with _send_auto_replies_bg
        pattern = r"submit_background\(_send_auto_replies_bg,\s*[^)]+\)"
        calls = re.findall(pattern, source)

        assert len(calls) >= 1, (
            f"Expected at least 1 call site for _send_auto_replies_bg, found {len(calls)}"
        )
        for c in calls:
            assert "account_id" in c, (
                f"Call site must pass account_id: {c}"
            )


# ===========================================================================
# 2. Provider pool health check reuses stored sock reference
# ===========================================================================

class TestProviderPoolSocketReuse:
    """BUG: Health check called conn.socket() twice — once to store timeout,
    once to restore it. The second call could return a different socket or fail.

    FIX: Store sock = conn.socket() once, reuse in finally block.
    """

    def test_health_check_reuses_sock_in_finally(self):
        """The finally block must use the stored sock variable, not call conn.socket() again."""
        from app.providers.provider_pool import ProviderPool

        source = inspect.getsource(ProviderPool._is_healthy)

        # The finally block should contain sock.settimeout, NOT conn.socket().settimeout
        finally_blocks = source.split("finally:")
        assert len(finally_blocks) >= 2, "Expected at least one finally block in _is_healthy"

        # The inner finally block (restoring timeout) should use sock, not conn.socket()
        restore_block = finally_blocks[1]  # first finally after the SELECT try
        assert "conn.socket()" not in restore_block, (
            "finally block must NOT call conn.socket() again — "
            "it must reuse the stored 'sock' variable"
        )
        assert "sock.settimeout" in restore_block or "sock is not None" in restore_block, (
            "finally block must reference the stored 'sock' variable"
        )

    def test_health_check_stores_sock_before_timeout(self):
        """sock must be assigned before settimeout is called."""
        from app.providers.provider_pool import ProviderPool

        source = inspect.getsource(ProviderPool._is_healthy)
        # sock = None must appear before sock = conn.socket()
        assert "sock = None" in source, "sock must be initialized to None for safety"
        assert "sock = conn.socket()" in source, "sock must be assigned from conn.socket()"

    def test_health_check_restores_timeout_on_healthy_connection(self):
        """Integration: health check restores original timeout after success."""
        from app.providers.provider_pool import ProviderPool

        pool = ProviderPool(check_health=True)

        mock_sock = Mock()
        mock_sock.gettimeout.return_value = 30.0

        mock_conn = Mock()
        mock_conn.socket.return_value = mock_sock
        mock_conn.select.return_value = ("OK", [b"1"])

        mock_provider = Mock()
        mock_provider._connection = mock_conn
        mock_provider._connection_lock = threading.Lock()
        mock_provider.folder = "INBOX"

        result = pool._is_healthy(mock_provider)

        assert result is True
        # sock.settimeout should be called twice: once for health check timeout, once to restore
        assert mock_sock.settimeout.call_count == 2
        # Last call should restore original timeout (30.0)
        mock_sock.settimeout.assert_called_with(30.0)
        # conn.socket() should be called only ONCE (stored in sock variable)
        mock_conn.socket.assert_called_once()


# ===========================================================================
# 3. Mobile theme radius values
# ===========================================================================

class TestMobileThemeRadius:
    """BUG: theme.radius values were halved (md:12→8, lg:16→10) in working copy,
    causing DraftCard border-radius to shrink from 16px to 8px.

    FIX: Restored to md:12, lg:16, xl:24.
    """

    def test_theme_radius_values_not_regressed(self):
        """Mobile theme radius values must match design spec."""
        import re

        with open("agentys-mobile/src/theme.ts", "r", encoding="utf-8") as f:
            content = f.read()

        # Extract radius block
        radius_match = re.search(r"radius:\s*\{([^}]+)\}", content)
        assert radius_match, "Could not find radius block in theme.ts"

        radius_block = radius_match.group(1)

        # Parse values
        values = {}
        for m in re.finditer(r"(\w+):\s*(\d+)", radius_block):
            values[m.group(1)] = int(m.group(2))

        # Assert minimum values (design spec)
        assert values.get("md", 0) >= 12, f"radius.md must be >= 12, got {values.get('md')}"
        assert values.get("lg", 0) >= 16, f"radius.lg must be >= 16, got {values.get('lg')}"
        assert values.get("xl", 0) >= 24, f"radius.xl must be >= 24, got {values.get('xl')}"

    def test_draftcard_uses_theme_radius(self):
        """DraftCard must reference theme.radius (not hardcoded small values).

        Skipped : le composant `DraftCard.tsx` a été refactoré / consolidé
        dans un autre composant lors d'un cleanup mobile (cf. git log
        agentys-mobile/). La vérification statique theme.radius est
        toujours pertinente sur les composants restants ; l'invariant
        général est protégé par le test `test_radius_tokens_meet_minimum`
        ci-dessus qui valide les tokens du thème.
        """
        import os
        path = "agentys-mobile/src/components/DraftCard.tsx"
        if not os.path.exists(path):
            pytest.skip("DraftCard.tsx removed during mobile refactor")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "theme.radius" in content, (
            "DraftCard must use theme.radius for borderRadius (not hardcoded values)"
        )


# ===========================================================================
# 4. Route mock paths: routes_emails owns email endpoints
# ===========================================================================

class TestRouteMockPaths:
    """BUG: After refactoring routes.py → routes_emails.py + routes_helpers.py,
    test mock paths targeting app.api.routes.* missed the actual code.

    FIX: Mocks must target app.api.routes_emails.* for email endpoints.
    """

    def test_get_cached_email_response_is_in_routes_emails(self):
        """_get_cached_email_response must be importable from routes_emails."""
        from app.api.routes_emails import _get_cached_email_response
        assert callable(_get_cached_email_response)

    def test_get_authenticated_provider_is_in_routes_emails(self):
        """_get_authenticated_provider must be importable from routes_emails."""
        from app.api.routes_emails import _get_authenticated_provider
        assert callable(_get_authenticated_provider)

    def test_get_email_by_id_is_in_routes_emails(self):
        """_get_email_by_id must be importable from routes_emails."""
        from app.api.routes_emails import _get_email_by_id
        assert callable(_get_email_by_id)

    def test_resolve_account_id_cached_is_in_routes_emails(self):
        """_resolve_account_id_cached must be importable from routes_emails."""
        from app.api.routes_emails import _resolve_account_id_cached
        assert callable(_resolve_account_id_cached)


class TestGetEmailMissingSentCompose:
    """Regression: missing sent compose placeholders must return 404, not 500."""

    def test_missing_sent_compose_id_returns_404(self, client):
        provider = MagicMock()
        provider.get_message_by_id.return_value = None

        session = MagicMock()
        session.__enter__.return_value = session
        session.__exit__.return_value = False

        repo = MagicMock()
        repo.get_by_email_id.return_value = None
        repo.exists_by_email_id.return_value = False

        account = MagicMock()
        account.id = "acc-1"
        account.email = "me@example.com"

        with patch("app.api.routes_emails._rh.require_owned_account_id", return_value=1), \
             patch("app.api.routes_emails._get_account_config_for_db_account_id", return_value=account), \
             patch("app.api.routes_emails._get_cached_email_detail", return_value=None), \
             patch("app.api.routes_emails._rh.get_db_session", return_value=session), \
             patch("app.api.routes_emails._rh.EmailRepository", return_value=repo), \
             patch("app.api.routes_emails._find_email_in_list_cache", return_value=None), \
             patch("app.api.routes_emails._find_sent_email_in_list_cache", return_value=None), \
             patch("app.providers.factory.get_pooled_provider", return_value=provider):
            response = client.get("/api/emails/sent:compose-1779215553")

        assert response.status_code == 404


class TestReplyActionEmailLookup:
    """Reply/send actions must not force a full provider body fetch."""

    def test_reply_action_uses_bodyless_sqlite_cache_first(self):
        from app.api import routes_emails

        provider = MagicMock()
        cached_email = MagicMock(id="19e4526202ffe7a5")

        with patch("app.api.routes_helpers._get_email_from_cache", return_value=cached_email) as mock_cache, \
             patch("app.api.routes_emails._get_email_by_id") as mock_get_email:
            result = routes_emails._get_email_for_reply_action(
                provider,
                "19e4526202ffe7a5",
                13,
            )

        assert result is cached_email
        mock_cache.assert_called_once_with(
            "19e4526202ffe7a5",
            account_id=13,
            allow_bodyless=True,
        )
        mock_get_email.assert_not_called()


# ===========================================================================
# 5. Mark-read returns 200 with provider_synced field
# ===========================================================================

class TestMarkReadProviderSynced:
    """BUG: Test expected 500 when provider.mark_as_read returns False,
    but the route was redesigned to return 200 with provider_synced: false
    (local cache updated, provider sync reported separately).
    """

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_mark_read_returns_200_when_provider_returns_false(
        self, mock_get_provider, mock_get_email, client
    ):
        """mark_as_read returning False should still yield 200 with provider_synced=False."""
        mock_email = Mock()
        mock_email.id = "test-email-id"
        mock_get_email.return_value = mock_email

        mock_provider = Mock()
        mock_provider.mark_as_read.return_value = False
        mock_get_provider.return_value = mock_provider

        response = client.patch(
            "/api/emails/test-email-id/read",
            json={"is_read": True}
        )
        data = response.get_json()

        assert response.status_code == 200, (
            "Route must return 200 even when provider sync fails "
            "(local cache is updated, provider_synced reports sync status)"
        )
        assert data["success"] is True
        assert data["provider_synced"] is False

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_mark_read_returns_provider_synced_true_on_success(
        self, mock_get_provider, mock_get_email, client
    ):
        """mark_as_read returning True should yield provider_synced=True."""
        mock_email = Mock()
        mock_email.id = "test-email-id"
        mock_get_email.return_value = mock_email

        mock_provider = Mock()
        mock_provider.mark_as_read.return_value = True
        mock_get_provider.return_value = mock_provider

        response = client.patch(
            "/api/emails/test-email-id/read",
            json={"is_read": True}
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["provider_synced"] is True


# ===========================================================================
# 6. Create-draft uses _get_authenticated_provider (not LegacyModuleLoader)
# ===========================================================================

class TestCreateDraftProviderPath:
    """BUG: Tests mocked LegacyModuleLoader.email_provider but the route
    calls _get_authenticated_provider() + _get_email_by_id().

    FIX: Route verified to use _get_authenticated_provider.
    """

    def test_create_draft_route_uses_get_authenticated_provider(self):
        """create_draft_from_content must call _get_authenticated_provider, not LegacyModuleLoader."""
        from app.api.routes_emails import create_draft_from_content

        source = inspect.getsource(create_draft_from_content)
        assert "_get_authenticated_provider()" in source, (
            "create_draft must use _get_authenticated_provider()"
        )
        assert "LegacyModuleLoader" not in source, (
            "create_draft must NOT use LegacyModuleLoader"
        )

    def test_mark_read_route_uses_get_authenticated_provider(self):
        """update_email_read_status must call _get_authenticated_provider."""
        from app.api.routes_emails import update_email_read_status

        source = inspect.getsource(update_email_read_status)
        assert "_get_authenticated_provider()" in source
        assert "LegacyModuleLoader" not in source

    @patch("app.api.routes_emails._resolve_account_id_cached", return_value=1)
    @patch("app.api.routes_helpers._resolve_account_id_cached", return_value=1)
    @patch("app.utils.signature.append_signature", side_effect=lambda body, **kw: body)
    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_create_draft_e2e_with_correct_mocks(
        self, mock_get_provider, mock_get_email, mock_sig,
        mock_resolve1, mock_resolve2, client
    ):
        """End-to-end: create draft with correct mock targets returns 201."""
        mock_email = Mock()
        mock_email.id = "test-email-123"
        mock_email.sender = "alice@example.com"
        mock_email.thread_id = None
        mock_email.conversation_id = None

        mock_provider = Mock()
        mock_provider.create_draft.return_value = "draft-abc"
        mock_provider.PROVIDER_NAME = "gmail"
        mock_get_provider.return_value = mock_provider
        mock_get_email.return_value = mock_email

        response = client.post(
            "/api/emails/test-email-123/draft",
            json={"subject": "Re: Test", "body": "Hello"},
        )
        data = response.get_json()

        assert response.status_code == 201
        assert data["success"] is True
        assert data["email_id"] == "test-email-123"

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_mark_read_e2e_with_correct_mocks(
        self, mock_get_provider, mock_get_email, client
    ):
        """End-to-end: mark read with correct mock targets returns 200."""
        mock_email = Mock()
        mock_email.id = "test-email-456"
        mock_get_email.return_value = mock_email

        mock_provider = Mock()
        mock_provider.mark_as_read.return_value = True
        mock_get_provider.return_value = mock_provider

        response = client.patch(
            "/api/emails/test-email-456/read",
            json={"is_read": True},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["success"] is True
        assert data["is_read"] is True


# ===========================================================================
# 7. _get_cached_email_response mock path
# ===========================================================================

class TestCachedEmailResponseMockPath:
    """BUG: Tests patched app.api.routes._get_cached_email_response but the function
    is imported into routes_emails.py from routes_helpers.py. Patching at routes.py
    missed the actual call site.
    """

    @patch("app.api.routes_emails._get_cached_email_response")
    @patch("app.api.routes_emails._get_current_account_for_user")
    @patch("app.api.routes_emails._rh._resolve_account_id_for_email", return_value=1)
    def test_list_emails_uses_cache_from_routes_emails(
        self, mock_resolve, mock_current, mock_cache, client
    ):
        """GET /api/emails must be interceptable by patching routes_emails._get_cached_email_response."""
        # En CI, _get_current_account_for_user retourne None → route short-circuit
        # (count=0). On force un account factice pour que la route aille jusqu'au cache.
        mock_account = MagicMock()
        mock_account.email = "test@example.com"
        mock_account.id = "test-account-1"
        mock_current.return_value = mock_account

        mock_cache.return_value = {
            "count": 1,
            "offset": 0,
            "has_more": False,
            "filter": "all",
            "source": "test",
            "emails": [
                {
                    "id": "regression-test-001",
                    "sender": "test@example.com",
                    "sender_name": "Test",
                    "subject": "Regression check",
                    "received_at": "2026-03-22T10:00:00Z",
                    "is_read": False,
                    "body": "",
                    "labels": [],
                }
            ],
        }

        response = client.get("/api/emails")
        data = response.get_json()

        assert response.status_code == 200
        assert data["count"] == 1
        assert data["emails"][0]["id"] == "regression-test-001"
        mock_cache.assert_called_once()
