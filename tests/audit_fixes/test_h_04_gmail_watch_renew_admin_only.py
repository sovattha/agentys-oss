# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Audit fix H-4 (issue #530) — `/api/gmail/watch/renew-due` sans gate admin.

Bug : `POST /api/gmail/watch/renew-due` (`app/api/gmail_push.py:350`) était
auth-gated par le blueprint guard mais sans `@require_admin` ni token
d'observabilité. L'endpoint itère TOUS les comptes Gmail dont la watch
expire dans 24h et re-issue `start_watch()` contre le topic Pub/Sub du
serveur — un endpoint cron par construction. Tout user authentifié pouvait
le déclencher → dépenses Pub/Sub dupliquées + drain du quota Gmail
`users.watch()` (50/jour côté Google, partagé par projet GCP).

Les sibling endpoints `start_gmail_watch` et `stop_gmail_watch` ont déjà
`_account_is_owned_by_caller`, mais ce check est inapplicable à un cron
qui itère tous les comptes — `@require_admin` est la garde naturelle,
cohérente avec `/push/broadcast` (#523) et `/api/sync/trigger` (#535).

Le workflow `.github/workflows/gmail-watch-renew.yml` utilise le token
interne `OBSERVABILITY_TOKEN`, comme les autres sentinelles L3. Les appels
humains restent possibles via JWT admin.

Run: `pytest tests/audit_fixes/test_h_04_gmail_watch_renew_admin_only.py -v`
"""

from __future__ import annotations

import inspect
from unittest.mock import patch

import pytest

pytest.importorskip("flask_cors")


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture
def client():
    from app.api.app import create_app
    app = create_app(config={"TESTING": True})
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


REMOTE_ATTACKER = {"REMOTE_ADDR": "203.0.113.10"}


# --------------------------------------------------------------------------- #
# Reproduction: a non-admin authenticated user MUST NOT trigger renewal.
# --------------------------------------------------------------------------- #


def test_renew_due_non_admin_jwt_must_be_rejected(client):
    """A magic-link JWT for a normal user MUST be 403, not 200."""
    fake_payload = {"sub": "42", "email": "victim@example.com"}

    with patch("app.api.auth._decode_jwt", return_value=fake_payload), \
         patch("app.api.admin._is_admin", return_value=False), \
         patch("app.providers.gmail_adapter.GmailAdapter") as mock_adapter:
        resp = client.post(
            "/api/gmail/watch/renew-due",
            headers={"Authorization": "Bearer normal-user-jwt"},
            environ_base=REMOTE_ATTACKER,
        )

    assert resp.status_code == 403, (
        f"H-4 leak: non-admin authenticated user got {resp.status_code} "
        f"with body {resp.get_data(as_text=True)[:200]}"
    )
    # No Gmail API call — the gate must abort before any provider work.
    mock_adapter.assert_not_called()


def test_renew_due_no_jwt_remote_must_be_rejected(client):
    """Anonymous remote caller is also rejected."""
    with patch("app.providers.gmail_adapter.GmailAdapter") as mock_adapter:
        resp = client.post(
            "/api/gmail/watch/renew-due",
            environ_base=REMOTE_ATTACKER,
        )
    # Either the blueprint auth guard returns 401 first, or @require_auth
    # inside @require_admin returns 401 — both acceptable, neither must be 200.
    assert resp.status_code in (401, 403)
    mock_adapter.assert_not_called()


def test_renew_due_loopback_no_jwt_must_be_rejected(client):
    """Tauri loopback callers are NOT exempt from @require_admin: this is a
    cron op, no Tauri user should ever hit it. Without a Bearer the
    @require_auth wrapper inside @require_admin rejects."""
    with patch("app.providers.gmail_adapter.GmailAdapter") as mock_adapter:
        resp = client.post(
            "/api/gmail/watch/renew-due",
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )
    assert resp.status_code == 401
    mock_adapter.assert_not_called()


# --------------------------------------------------------------------------- #
# Sanity: legitimate admin (the GitHub Actions cron) still works.
# --------------------------------------------------------------------------- #


def test_renew_due_admin_jwt_passes_gate(client, monkeypatch):
    """An admin JWT must clear the gate and reach the renewal logic.

    The renewal then short-circuits because GMAIL_PUSH_TOPIC isn't set in
    tests — but it must reach that branch, not the 403 from the gate. We
    assert the response is 200/400 (renewal logic responses), not 403.
    """
    fake_payload = {"sub": "1", "email": "admin@test.com"}
    monkeypatch.delenv("GMAIL_PUSH_TOPIC", raising=False)

    with patch("app.api.auth._decode_jwt", return_value=fake_payload), \
         patch("app.api.admin._is_admin", return_value=True):
        resp = client.post(
            "/api/gmail/watch/renew-due",
            headers={"Authorization": "Bearer admin-jwt"},
            environ_base=REMOTE_ATTACKER,
        )

    # No topic env → 400 from the renewal logic, NOT 403 from the gate.
    assert resp.status_code != 403, (
        f"Admin unexpectedly rejected by the gate: {resp.get_data(as_text=True)[:200]}"
    )


def test_renew_due_observability_token_passes_cron_gate(client, monkeypatch):
    """The GitHub Actions cron uses OBSERVABILITY_TOKEN, not a human admin JWT.

    A signed service JWT is still sent to clear the global API auth guard.
    """
    monkeypatch.setenv("OBSERVABILITY_TOKEN", "obs-secret")
    monkeypatch.delenv("GMAIL_PUSH_TOPIC", raising=False)

    fake_payload = {"sub": "0", "email": "gmail-watch-renew@agentys.internal"}
    with patch("app.api.auth._decode_jwt", return_value=fake_payload):
        resp = client.post(
            "/api/gmail/watch/renew-due",
            headers={
                "Authorization": "Bearer service-jwt",
                "X-Observability-Token": "obs-secret",
            },
            environ_base=REMOTE_ATTACKER,
        )

    # No topic env -> renewal logic response, not auth gate response.
    assert resp.status_code == 400
    assert "GMAIL_PUSH_TOPIC" in resp.get_data(as_text=True)


def test_renew_due_async_cron_returns_accepted(client, monkeypatch):
    """GitHub Actions queues renewal work instead of holding a 5-minute HTTP request."""
    monkeypatch.setenv("OBSERVABILITY_TOKEN", "obs-secret")

    fake_payload = {"sub": "0", "email": "gmail-watch-renew@agentys.internal"}
    with patch("app.api.auth._decode_jwt", return_value=fake_payload), \
         patch("app.api.gmail_push._start_renew_due_watches_background") as start_bg:
        resp = client.post(
            "/api/gmail/watch/renew-due?async=1",
            headers={
                "Authorization": "Bearer service-jwt",
                "X-Observability-Token": "obs-secret",
            },
            environ_base=REMOTE_ATTACKER,
        )

    assert resp.status_code == 202
    assert resp.get_json() == {"status": "queued"}
    start_bg.assert_called_once_with()


# --------------------------------------------------------------------------- #
# Static check: the decorator is actually present on the view function.
# Mirror of test_c_03_push_broadcast_admin_only.
# --------------------------------------------------------------------------- #


def test_renew_due_source_has_cron_gate_decorator():
    """Source-level sanity check: prevents a future refactor from silently
    removing the decorator. functools.wraps makes runtime introspection
    unreliable (qualnames are copied), so we grep the source."""
    from app.api import gmail_push

    src = inspect.getsource(gmail_push)
    idx = src.find("def renew_due_watches(")
    assert idx > 0, "renew_due_watches not found in source"
    # Look backwards 400 chars — enough to span the decorator stack.
    preamble = src[max(0, idx - 400) : idx]
    assert "@_require_admin_or_observability_token" in preamble, (
        "@_require_admin_or_observability_token missing immediately above renew_due_watches — "
        "the H-4 fix has been regressed.\nPreamble:\n" + preamble
    )
