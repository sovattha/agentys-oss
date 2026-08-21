# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Audit 2026-05-29 (label slice) — custom-label CRUD must reject the -1 sentinel.

``_resolve_account_id_for_user()`` returns ``-1`` (``_NO_ACCOUNT_SENTINEL``) for
any caller without their own DB account (pre-OAuth JWT user, or an email with no
matching ``accounts`` row). That sentinel is SQL-safe, but ``get_label_store(-1)``
maps to the on-disk ``data/labels/-1/`` directory, so every unresolved caller
pools into ONE shared label library — read AND write.

The rules / VIP / assign / counts handlers were guarded in the 2026-05-29 fix,
but the custom-label CRUD (``GET``/``POST`` ``/api/labels`` and
``GET``/``PUT``/``DELETE`` ``/api/labels/<name>``) was missed: it still passed
``-1`` straight to the store. ``create``/``update``/``delete`` are the write side
of the bleed — one unresolved account creating "Agentys" would surface it to
every other unresolved account.

Fix: reject ``account_id <= 0`` with 401 in all five handlers, mirroring the
existing siblings (no loopback relaxation — same as ``list_rules`` /
``get_label_counts``).

Run: pytest tests/audit_fixes/test_label_crud_minus1_guard.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("flask_cors")

from app.domain.entities.email_labels import EmailLabel  # noqa: E402

REMOTE = {"REMOTE_ADDR": "203.0.113.10"}  # public IP → defeats loopback trust
AUTH = {"Authorization": "Bearer tok"}
JWT = {"sub": "1", "email": "preoauth@example.com"}


@pytest.fixture
def client():
    from app.api.app import create_app
    app = create_app(config={"TESTING": True})
    app.config["TESTING"] = True
    return app.test_client()


# --------------------------------------------------------------------------- #
# GET /api/labels  (list)
# --------------------------------------------------------------------------- #

def test_list_labels_rejects_preoauth_sentinel(client):
    """A -1 caller must 401 — never read the shared data/labels/-1/ pool."""
    leaked = [EmailLabel(name="LeakedAgentys", is_default=False)]
    with patch("app.api.auth._decode_jwt", return_value=JWT), \
         patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=-1), \
         patch("app.api.labels._get_labels_cached", return_value=leaked) as cached:
        resp = client.get("/api/labels", headers=AUTH, environ_base=REMOTE)
    assert resp.status_code == 401
    cached.assert_not_called()  # short-circuits before any store read


def test_list_labels_positive_account_ok(client):
    """Regression: a real account (id > 0) still gets its own labels."""
    labels = [EmailLabel(name="Mine", is_default=False)]
    with patch("app.api.auth._decode_jwt", return_value=JWT), \
         patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=5), \
         patch("app.api.labels._get_labels_cached", return_value=labels) as cached:
        resp = client.get("/api/labels", headers=AUTH, environ_base=REMOTE)
    assert resp.status_code == 200
    assert resp.get_json()["count"] == 1
    cached.assert_called_once_with(account_id=5)


# --------------------------------------------------------------------------- #
# POST /api/labels  (create) — the WRITE side of the bleed
# --------------------------------------------------------------------------- #

def test_create_label_rejects_and_never_writes(client):
    with patch("app.api.auth._decode_jwt", return_value=JWT), \
         patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=-1), \
         patch("app.api.labels.get_container") as gc:
        resp = client.post(
            "/api/labels", headers=AUTH, environ_base=REMOTE,
            json={"name": "Spy", "is_project": True},
        )
    assert resp.status_code == 401
    # Never resolves a store → nothing written to data/labels/-1/
    gc.return_value.get_label_store.assert_not_called()


def test_create_label_positive_account_writes_to_own_store(client):
    """Regression: id > 0 still creates the label in ITS OWN store."""
    store = MagicMock()
    store.add_label.return_value = True
    with patch("app.api.auth._decode_jwt", return_value=JWT), \
         patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=5), \
         patch("app.api.labels.get_container") as gc:
        gc.return_value.get_label_store.return_value = store
        resp = client.post(
            "/api/labels", headers=AUTH, environ_base=REMOTE,
            json={"name": "Mine"},
        )
    assert resp.status_code == 201
    gc.return_value.get_label_store.assert_called_once_with(account_id=5)
    store.add_label.assert_called_once()


# --------------------------------------------------------------------------- #
# GET / PUT / DELETE /api/labels/<name>
# --------------------------------------------------------------------------- #

def test_get_label_by_name_rejects_preoauth_sentinel(client):
    with patch("app.api.auth._decode_jwt", return_value=JWT), \
         patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=-1), \
         patch("app.api.labels.get_container") as gc:
        resp = client.get("/api/labels/Agentys", headers=AUTH, environ_base=REMOTE)
    assert resp.status_code == 401
    gc.return_value.get_label_store.assert_not_called()


def test_update_label_rejects_and_never_writes(client):
    with patch("app.api.auth._decode_jwt", return_value=JWT), \
         patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=-1), \
         patch("app.api.labels.get_container") as gc:
        resp = client.put(
            "/api/labels/Agentys", headers=AUTH, environ_base=REMOTE,
            json={"color": "#000000"},
        )
    assert resp.status_code == 401
    gc.return_value.get_label_store.assert_not_called()


def test_delete_label_rejects_and_never_writes(client):
    with patch("app.api.auth._decode_jwt", return_value=JWT), \
         patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=-1), \
         patch("app.api.labels.get_container") as gc:
        resp = client.delete("/api/labels/Agentys", headers=AUTH, environ_base=REMOTE)
    assert resp.status_code == 401
    gc.return_value.get_label_store.assert_not_called()
