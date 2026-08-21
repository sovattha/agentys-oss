# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Audit fix C-2 (issue #522) — `scheduled_emails_bp` n'avait aucun auth guard.

Bug: le blueprint `scheduled_emails_bp` n'était pas dans `_guarded_blueprints`
et tombait sur le compte singleton via `_get_current_account_for_user()`
quand le caller n'avait pas de JWT. Conséquence: un attaquant non
authentifié distant pouvait :

- POST   /api/emails/schedule         → enqueuer un email sortant sous
                                        l'identité du singleton
- GET    /api/emails/scheduled        → lister les sends programmés
- DELETE /api/emails/scheduled/<id>   → annuler des sends
- PATCH  /api/emails/scheduled/<id>   → hijack `to`/`subject`/`body`

Fix:
  1) `scheduled_emails_bp` ajouté à `_guarded_blueprints` dans
     `app/api/app.py:524` — toute route exige Bearer JWT (ou loopback).
  2) Defense-in-depth : `_get_current_account_for_user()` retourne `None`
     en contexte requête non-loopback sans JWT (au lieu de `singleton`).

Run: `pytest tests/audit_fixes/test_c_02_scheduled_emails_unauth.py -v`
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

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


@pytest.fixture
def store(tmp_path):
    """Store SQLite isolé par test, injecté comme default global."""
    from app.services.scheduled_email_store import (
        ScheduledEmailStore,
        reset_default_store,
    )
    s = ScheduledEmailStore(db_path=str(tmp_path / "sched.db"))
    reset_default_store(s)
    yield s
    reset_default_store(None)


def _future_iso(hours: int = 2) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


REMOTE_ATTACKER = {"REMOTE_ADDR": "203.0.113.10"}


# --------------------------------------------------------------------------- #
# Reproduction: unauthenticated remote caller hits all 4 routes — must 401
# --------------------------------------------------------------------------- #


def test_post_schedule_remote_no_auth_must_be_rejected(client, store):
    """C-2: anonymous remote caller MUST NOT enqueue an outbound send."""
    resp = client.post(
        "/api/emails/schedule",
        json={
            "to": "victim@example.com",
            "subject": "phish",
            "body": "click here",
            "send_at": _future_iso(),
        },
        environ_base=REMOTE_ATTACKER,
    )
    assert resp.status_code == 401, (
        f"C-2 leak: anonymous remote enqueue returned {resp.status_code} "
        f"with body {resp.get_data(as_text=True)[:200]}"
    )
    # Side-effect check: scan the per-test store across plausible account IDs
    # — the pre-fix bug would have inserted a row under the singleton's id.
    for probe_id in (1, 7, 42, 99):
        rows = store.list_by_account(account_id=probe_id, statuses=("pending",))
        assert rows == [], f"C-2 side-effect: a row landed under account_id={probe_id}"


def test_get_scheduled_remote_no_auth_must_be_rejected(client):
    resp = client.get(
        "/api/emails/scheduled",
        environ_base=REMOTE_ATTACKER,
    )
    assert resp.status_code == 401, (
        f"C-2 leak: anonymous remote list returned {resp.status_code}"
    )
    body = resp.get_data(as_text=True)
    # The pre-fix bug returned `{"items": [...], "count": N}` with the
    # singleton's pending sends. Be paranoid.
    assert '"items"' not in body


def test_delete_scheduled_remote_no_auth_must_be_rejected(client):
    resp = client.delete(
        "/api/emails/scheduled/some-id-123",
        environ_base=REMOTE_ATTACKER,
    )
    assert resp.status_code == 401


def test_patch_scheduled_remote_no_auth_must_be_rejected(client):
    resp = client.patch(
        "/api/emails/scheduled/some-id-123",
        json={"subject": "hijacked"},
        environ_base=REMOTE_ATTACKER,
    )
    assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# Defense-in-depth: even if the auth guard is bypassed (regression in a
# future refactor), `_get_current_account_for_user()` must NOT return the
# singleton in a non-loopback request without JWT.
# --------------------------------------------------------------------------- #


def test_get_current_account_for_user_non_loopback_no_jwt_returns_none(app):
    """ISO C-2 piste 2: defense-in-depth on the helper itself."""
    from app.api.routes_helpers import _get_current_account_for_user

    sentinel_singleton = Mock(id="singleton-account", email="singleton@example.com")

    with app.test_request_context(
        "/api/emails/scheduled",
        environ_base={"REMOTE_ADDR": "203.0.113.10"},
    ), patch(
        "app.multi_accounts.get_current_account",
        return_value=sentinel_singleton,
    ):
        result = _get_current_account_for_user()

    assert result is None, (
        "Defense-in-depth broken: a non-loopback request without JWT still "
        "exposes the singleton account."
    )


def test_get_current_account_for_user_loopback_still_returns_singleton(app):
    """Regression: the Tauri desktop path (loopback) must keep working."""
    from app.api.routes_helpers import _get_current_account_for_user

    sentinel_singleton = Mock(id="singleton-account", email="singleton@example.com")

    with app.test_request_context(
        "/api/emails/scheduled",
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    ), patch(
        "app.multi_accounts.get_current_account",
        return_value=sentinel_singleton,
    ):
        result = _get_current_account_for_user()

    assert result is sentinel_singleton


# --------------------------------------------------------------------------- #
# Sanity: legitimate flows still work (JWT and loopback)
# --------------------------------------------------------------------------- #


def test_post_schedule_with_valid_jwt_succeeds(client, store):
    """Regression: a properly authenticated user can still schedule sends."""
    fake_account = Mock()
    fake_account.id = "alice-account"
    fake_account.email = "alice@example.com"

    with patch(
        "app.api.auth._decode_jwt",
        return_value={"sub": 1, "email": "alice@example.com"},
    ), patch(
        "app.api.scheduled_emails._get_current_account_for_user",
        return_value=fake_account,
    ), patch(
        "app.api.scheduled_emails._resolve_account_id_cached",
        return_value=42,
    ):
        resp = client.post(
            "/api/emails/schedule",
            json={
                "to": "bob@example.com",
                "subject": "hello",
                "body": "hi bob",
                "send_at": _future_iso(),
            },
            headers={"Authorization": "Bearer stub-token"},
            environ_base=REMOTE_ATTACKER,
        )

    assert resp.status_code == 201, (
        f"Authenticated POST unexpectedly rejected: {resp.status_code} "
        f"{resp.get_data(as_text=True)[:200]}"
    )


def test_post_schedule_loopback_no_jwt_succeeds(client, store):
    """Regression: Tauri desktop (loopback, no JWT) still works."""
    fake_account = Mock()
    fake_account.id = "tauri-singleton"
    fake_account.email = "user@local"

    with patch(
        "app.api.scheduled_emails._get_current_account_for_user",
        return_value=fake_account,
    ), patch(
        "app.api.scheduled_emails._resolve_account_id_cached",
        return_value=7,
    ):
        resp = client.post(
            "/api/emails/schedule",
            json={
                "to": "bob@example.com",
                "subject": "hello",
                "body": "hi bob",
                "send_at": _future_iso(),
            },
            # test_client defaults REMOTE_ADDR to 127.0.0.1 — explicit for clarity
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )

    assert resp.status_code == 201, (
        f"Loopback POST unexpectedly rejected: {resp.status_code} "
        f"{resp.get_data(as_text=True)[:200]}"
    )
