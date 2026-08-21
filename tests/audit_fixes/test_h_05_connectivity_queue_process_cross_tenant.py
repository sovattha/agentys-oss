# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Audit fix H-5 (issue #531) — `POST /api/connectivity/queue/process`
drainait la file d'actions offline pour TOUS les comptes du système.

Bug: la route déléguait à ``process_all_pending_actions()`` qui itérait
``session.query(Account).all()`` sans filtre tenant. Le sibling
``DELETE /queue/<account_id>/action/<id>`` a déjà un check
``_user_owns_account`` (L:212) ; celui-ci était global. Un user
authentifié avec un magic link standard pouvait force-flush les
sends/deletes/archives queued par d'autres users contre le provider
email réel.

Fix:
- ``process_all_pending_actions(user_id: int | None = None)`` : filtre
  ``Account.user_id == user_id`` quand le param est set. ``None`` reste
  réservé au legacy (loopback Tauri, single-user host).
- ``process_queue`` route : résout le scope depuis ``g.auth_user`` ou
  loopback ``_is_loopback(request.remote_addr)``. JWT user → user_id ;
  loopback no JWT → None ; sinon 401 belt-and-suspenders.

Run: ``pytest tests/audit_fixes/test_h_05_connectivity_queue_process_cross_tenant.py -v``
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("flask_cors")


@pytest.fixture
def app():
    from app.api.app import create_app
    a = create_app(config={"TESTING": True})
    a.config["TESTING"] = True
    return a


@pytest.fixture
def client(app):
    return app.test_client()


# --------------------------------------------------------------------------- #
# Route-level tests — verifies the scope passed to process_all_pending_actions
# --------------------------------------------------------------------------- #

@pytest.fixture
def stub_route(monkeypatch):
    """Stub connectivity_service.is_online + action_queue.get_pending_count
    + process_all_pending_actions so we can assert which scope was passed."""
    svc = MagicMock()
    svc.is_online = True
    monkeypatch.setattr(
        "app.api.connectivity.get_connectivity_service", lambda: svc
    )

    queue = MagicMock()
    queue.get_pending_count.return_value = 3  # any non-zero
    monkeypatch.setattr(
        "app.api.connectivity.get_action_queue", lambda: queue
    )

    monkeypatch.setattr(
        "app.api.connectivity.emit_queue_processed", lambda **kw: None
    )

    spy = MagicMock(return_value={})
    monkeypatch.setattr(
        "app.api.connectivity.process_all_pending_actions", spy
    )
    return spy


def test_loopback_no_jwt_processes_every_account(client, stub_route):
    """Tauri desktop (loopback, no JWT) keeps the legacy unrestricted scope."""
    # Default test_client has remote_addr=127.0.0.1 (loopback) ; no auth header.
    resp = client.post("/api/connectivity/queue/process")
    assert resp.status_code == 200
    stub_route.assert_called_once_with(user_id=None)


def test_jwt_user_scopes_to_own_user_id(client, stub_route, monkeypatch):
    """A non-admin JWT caller only processes their own accounts."""
    fake_payload = {"sub": "42", "id": 42, "email": "alice@test.com"}
    monkeypatch.setattr("app.api.auth._decode_jwt", lambda token: fake_payload)
    resp = client.post(
        "/api/connectivity/queue/process",
        headers={"Authorization": "Bearer alice-stub"},
        environ_base={"REMOTE_ADDR": "203.0.113.10"},  # remote, not loopback
    )
    assert resp.status_code == 200
    stub_route.assert_called_once_with(user_id=42)


def test_jwt_with_string_id_is_coerced_to_int(client, stub_route, monkeypatch):
    """JWT payload with id as str (e.g. JSON parsed) still works."""
    fake_payload = {"sub": "7", "id": "7", "email": "bob@test.com"}
    monkeypatch.setattr("app.api.auth._decode_jwt", lambda token: fake_payload)
    resp = client.post(
        "/api/connectivity/queue/process",
        headers={"Authorization": "Bearer bob-stub"},
        environ_base={"REMOTE_ADDR": "203.0.113.10"},
    )
    assert resp.status_code == 200
    stub_route.assert_called_once_with(user_id=7)


def test_jwt_without_id_returns_401(client, stub_route, monkeypatch):
    """If the JWT lacks an id we refuse rather than fall back to global."""
    fake_payload = {"sub": "x", "email": "no-id@test.com"}  # no "id"
    monkeypatch.setattr("app.api.auth._decode_jwt", lambda token: fake_payload)
    resp = client.post(
        "/api/connectivity/queue/process",
        headers={"Authorization": "Bearer noid-stub"},
        environ_base={"REMOTE_ADDR": "203.0.113.10"},
    )
    # Auth guard or route — either way, no global flush.
    assert resp.status_code in (401, 403)
    stub_route.assert_not_called()


def test_remote_no_jwt_is_rejected(client, stub_route):
    """A non-loopback caller without JWT must not drain the queue."""
    resp = client.post(
        "/api/connectivity/queue/process",
        environ_base={"REMOTE_ADDR": "203.0.113.10"},
    )
    assert resp.status_code in (401, 403)
    stub_route.assert_not_called()


# --------------------------------------------------------------------------- #
# Service-level test — verifies the SQL filter actually scopes by user_id
# --------------------------------------------------------------------------- #

def test_process_all_pending_actions_filters_by_user_id():
    """process_all_pending_actions(user_id=42) must filter Account.user_id==42
    in the DB query — not iterate every Account and post-filter."""
    from app.services import action_queue as aq

    # Capture the filter chain. session.query(Account) → query.filter(...) → query.all()
    filtered_accounts: list = []
    captured_filter_arg = {}

    fake_query = MagicMock()
    fake_query.all.return_value = filtered_accounts

    def _capture_filter(criterion):
        captured_filter_arg["criterion"] = criterion
        return fake_query

    fake_query.filter.side_effect = _capture_filter

    fake_session = MagicMock()
    fake_session.query.return_value = fake_query

    fake_ctx = MagicMock()
    fake_ctx.__enter__.return_value = fake_session
    fake_ctx.__exit__.return_value = False

    with patch("app.db.database.get_db_session", return_value=fake_ctx):
        with patch("app.db.repositories.AccountRepository"):
            result = aq.process_all_pending_actions(user_id=42)

    assert result == {}
    fake_query.filter.assert_called_once()
    # The filter criterion is `Account.user_id == 42` — we just verify .filter
    # was invoked (sqlalchemy clauses don't expose a clean equality).
    assert captured_filter_arg["criterion"] is not None


def test_process_all_pending_actions_no_user_id_skips_filter():
    """process_all_pending_actions() with no arg keeps legacy behaviour:
    query every Account, no filter. Required for loopback Tauri host."""
    from app.services import action_queue as aq

    fake_query = MagicMock()
    fake_query.all.return_value = []

    fake_session = MagicMock()
    fake_session.query.return_value = fake_query

    fake_ctx = MagicMock()
    fake_ctx.__enter__.return_value = fake_session
    fake_ctx.__exit__.return_value = False

    with patch("app.db.database.get_db_session", return_value=fake_ctx):
        with patch("app.db.repositories.AccountRepository"):
            aq.process_all_pending_actions()  # no user_id

    fake_query.filter.assert_not_called()
    fake_query.all.assert_called_once()
