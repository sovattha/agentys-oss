# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Audit fix ISO-01 — `GET /api/oauth/tokens/<account_id>/access` is unauthenticated.

Bug: oauth_bp is excluded from `apply_auth_guard` in `app/api/app.py:300`.
The `get_access_token`, `refresh_account_tokens`, and `get_token_status`
endpoints call `get_tokens_server(account_id)` and return the raw OAuth
access_token / refresh status without any caller identity check.

Attack: an unauthenticated remote attacker who guesses or leaks any
account_id can fetch a live Gmail/Outlook access_token and read the
mailbox.

Fix: require auth (Bearer JWT or loopback) on these endpoints, and check
that the JWT email matches the email stored alongside the OAuth tokens.

Run: `pytest tests/audit_fixes/test_iso_01_oauth_access_token_unauthenticated.py -v`
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest

pytest.importorskip("flask_cors")


@pytest.fixture
def app():
    from app.api.app import create_app
    app = create_app(config={"TESTING": True})
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@contextmanager
def _stub_oauth_storage(account_id: str, email: str):
    """Pretend the server has stored tokens for `account_id` belonging to `email`.

    We patch `get_tokens_server` directly so we don't have to muck with
    encryption / file persistence. `_refresh_tokens_server` is patched as a
    no-op that returns the same payload (refresh path).
    """
    fake_token_data = {
        "provider": "gmail",
        "email": email,
        "access_token": "ya29.SECRET-VICTIM-TOKEN",
        "refresh_token": "1//SECRET-REFRESH",
        "expires_at": 9999999999,  # far future, no refresh needed
        "token_type": "Bearer",
        "scope": "https://www.googleapis.com/auth/gmail.readonly",
    }
    with patch(
        "app.api.oauth.get_tokens_server",
        side_effect=lambda aid: fake_token_data if aid == account_id else None,
    ), patch(
        "app.api.oauth._refresh_tokens_server",
        side_effect=lambda aid: fake_token_data if aid == account_id else None,
    ):
        yield


def _stub_jwt(user_id: int, email: str):
    """Make `_decode_jwt` return a fake payload for any token."""
    return patch(
        "app.api.auth._decode_jwt",
        return_value={"sub": user_id, "email": email},
    )


# --------------------------------------------------------------------------- #
# Reproduction: unauthenticated remote caller exfiltrates an access_token
# --------------------------------------------------------------------------- #


def test_get_access_token_remote_no_auth_must_be_rejected(app, client):
    """ISO-01: A remote unauthenticated caller MUST NOT receive the token.

    Before the fix: 200 OK with the access_token. After: 401 Unauthorized.
    """
    with _stub_oauth_storage("victim_account_hash", "victim@example.com"):
        resp = client.get(
            "/api/oauth/tokens/victim_account_hash/access",
            environ_base={"REMOTE_ADDR": "203.0.113.10"},
        )

    # Must NOT return the token to an unauthenticated remote caller.
    assert resp.status_code in (401, 403), (
        f"ISO-01 leak: unauthenticated remote caller got {resp.status_code} "
        f"with body {resp.get_data(as_text=True)[:200]}"
    )
    body = resp.get_data(as_text=True)
    assert "ya29.SECRET-VICTIM-TOKEN" not in body
    assert "access_token" not in resp.get_json(silent=True) or {}


def test_get_token_status_remote_no_auth_must_be_rejected(app, client):
    """ISO-01: token status is also sensitive — leaks email + scopes."""
    with _stub_oauth_storage("victim_account_hash", "victim@example.com"):
        resp = client.get(
            "/api/oauth/tokens/victim_account_hash/status",
            environ_base={"REMOTE_ADDR": "203.0.113.10"},
        )

    assert resp.status_code in (401, 403)
    body = resp.get_data(as_text=True)
    assert "victim@example.com" not in body


def test_refresh_tokens_remote_no_auth_must_be_rejected(app, client):
    """ISO-01: forcing a refresh on someone else's account is also forbidden."""
    with _stub_oauth_storage("victim_account_hash", "victim@example.com"):
        resp = client.post(
            "/api/oauth/tokens/victim_account_hash/refresh",
            environ_base={"REMOTE_ADDR": "203.0.113.10"},
        )

    assert resp.status_code in (401, 403)


# --------------------------------------------------------------------------- #
# Cross-user attack: authenticated user A asks for user B's tokens
# --------------------------------------------------------------------------- #


def test_get_access_token_cross_user_must_be_rejected(app, client):
    """ISO-01: even an authenticated JWT caller cannot fetch another user's
    OAuth access_token. The handler must check that
    `stored.email == g.auth_user.email`.
    """
    with _stub_oauth_storage("victim_account_hash", "victim@example.com"), \
         _stub_jwt(user_id=999, email="attacker@example.com"):
        resp = client.get(
            "/api/oauth/tokens/victim_account_hash/access",
            headers={"Authorization": "Bearer stub-token"},
            environ_base={"REMOTE_ADDR": "203.0.113.10"},
        )

    assert resp.status_code in (401, 403, 404), (
        f"ISO-01 cross-user leak: attacker received {resp.status_code} "
        f"with body {resp.get_data(as_text=True)[:200]}"
    )
    body = resp.get_data(as_text=True)
    assert "ya29.SECRET-VICTIM-TOKEN" not in body


# --------------------------------------------------------------------------- #
# Sanity: same-user (matching JWT email) MUST still work
# --------------------------------------------------------------------------- #


def test_get_access_token_same_user_succeeds(app, client):
    """Regression: legitimate caller — JWT email matches stored token email —
    still receives the access_token."""
    with _stub_oauth_storage("alice_hash", "alice@example.com"), \
         _stub_jwt(user_id=1, email="alice@example.com"):
        resp = client.get(
            "/api/oauth/tokens/alice_hash/access",
            headers={"Authorization": "Bearer stub-token"},
            environ_base={"REMOTE_ADDR": "203.0.113.10"},
        )

    assert resp.status_code == 200, (
        f"Same-user lookup unexpectedly failed: {resp.status_code} "
        f"{resp.get_data(as_text=True)[:200]}"
    )
    payload = resp.get_json()
    assert payload.get("access_token") == "ya29.SECRET-VICTIM-TOKEN"


def test_get_access_token_loopback_no_jwt_succeeds(app, client):
    """Regression: Tauri desktop loopback (no JWT) still works as before.
    The auth guard accepts loopback callers, and the ownership check is
    intentionally relaxed in this mode (single-user host).
    """
    with _stub_oauth_storage("local_hash", "local@example.com"):
        resp = client.get(
            "/api/oauth/tokens/local_hash/access",
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )

    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload.get("access_token") == "ya29.SECRET-VICTIM-TOKEN"
