# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Audit 2026-05-29 — the -1 "no account" sentinel poisons JSON file stores.

``_resolve_account_id_for_user()`` returns ``-1`` (``_NO_ACCOUNT_SENTINEL``)
for any JWT user who has not yet linked a mailbox (pre-OAuth onboarding). That
sentinel is SQL-safe (no row has id -1) but the JSON file stores
``contact_groups.json`` and ``reminders.json`` PERSIST rows tagged ``-1`` and
match them with ``==``, so every pre-OAuth tenant pooled into one shared
read/write/delete bucket.

Fix: reject non-positive callers (HTTP 401/404 / empty list) unless loopback
(Tauri desktop), mirroring routes_contacts F-02/F-05.

Run: pytest tests/audit_fixes/test_isolation_2026_05_29_file_store_sentinel.py -v
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytest.importorskip("flask_cors")

REMOTE = {"REMOTE_ADDR": "203.0.113.10"}
LOOPBACK = {"REMOTE_ADDR": "127.0.0.1"}
AUTH = {"Authorization": "Bearer tok"}
JWT = {"sub": "1", "email": "preoauth@example.com"}


@pytest.fixture
def client():
    from app.api.app import create_app
    app = create_app(config={"TESTING": True})
    app.config["TESTING"] = True
    return app.test_client()


# --------------------------------------------------------------------------- #
# Contact groups
#
# Post-migration 039 le store est la table SQLAlchemy ``contact_groups`` (plus
# de _load_groups/_save_groups). Les tests 401 prouvent que la garde
# court-circuite AVANT tout accès DB ; les tests de scope montent une SQLite
# mémoire seedée et rebindent ``app.db.database.get_db_session``.
# --------------------------------------------------------------------------- #

def _contact_groups_db(monkeypatch, tmp_path, rows):
    from contextlib import contextmanager

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    import app.api.contact_groups as cg
    from app.db.models import Base
    from app.db.repositories.contact_group_repository import ContactGroupRepository

    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False)
    with SessionLocal() as s:
        for grp in rows:
            s.add(ContactGroupRepository.row_from_legacy_dict(grp, grp["id"]))
        s.commit()

    @contextmanager
    def _cm():
        s = SessionLocal()
        try:
            yield s
        finally:
            s.close()

    monkeypatch.setattr("app.db.database.get_db_session", _cm)
    monkeypatch.setattr(cg, "GROUPS_FILE", str(tmp_path / "contact_groups.json"))
    monkeypatch.setattr(cg, "_legacy_import_done", True)


def test_contact_groups_list_rejects_preoauth_sentinel(client, monkeypatch, tmp_path):
    """A pre-OAuth (account_id == -1) web caller must NOT receive the shared
    -1 bucket — 401 instead of leaking another tenant's groups."""
    _contact_groups_db(monkeypatch, tmp_path, [
        {"id": "grp_x", "name": "Board", "account_id": -1,
         "members": [{"name": "X", "email": "board@acme.com"}]},
    ])
    with patch("app.api.auth._decode_jwt", return_value=JWT), \
         patch("app.api.contact_groups._resolve_account_id_for_user", return_value=-1):
        resp = client.get("/api/contact-groups", headers=AUTH, environ_base=REMOTE)
    assert resp.status_code == 401


def test_contact_groups_create_rejects_preoauth_sentinel(client):
    with patch("app.api.auth._decode_jwt", return_value=JWT), \
         patch("app.api.contact_groups._resolve_account_id_for_user", return_value=-1), \
         patch("app.db.database.get_db_session") as db:
        resp = client.post(
            "/api/contact-groups",
            headers=AUTH, environ_base=REMOTE,
            json={"name": "Spy", "members": [{"name": "a", "email": "a@b.com"}]},
        )
    assert resp.status_code == 401
    db.assert_not_called()  # never persists a -1 record


def test_contact_groups_delete_rejects_preoauth_sentinel(client):
    with patch("app.api.auth._decode_jwt", return_value=JWT), \
         patch("app.api.contact_groups._resolve_account_id_for_user", return_value=-1), \
         patch("app.db.database.get_db_session") as db:
        resp = client.delete("/api/contact-groups/grp_x", headers=AUTH, environ_base=REMOTE)
    assert resp.status_code == 401
    db.assert_not_called()


def test_contact_groups_positive_account_sees_only_own(client, monkeypatch, tmp_path):
    _contact_groups_db(monkeypatch, tmp_path, [
        {"id": "g5", "name": "Mine", "account_id": 5, "members": [], "use_count": 0},
        {"id": "g99", "name": "Theirs", "account_id": 99, "members": [], "use_count": 0},
    ])
    with patch("app.api.auth._decode_jwt", return_value=JWT), \
         patch("app.api.contact_groups._resolve_account_id_for_user", return_value=5):
        resp = client.get("/api/contact-groups", headers=AUTH, environ_base=REMOTE)
    assert resp.status_code == 200
    names = [g["name"] for g in resp.get_json()["groups"]]
    assert names == ["Mine"]
    assert "Theirs" not in names


def test_contact_groups_loopback_preoauth_allowed(client, monkeypatch, tmp_path):
    """Tauri desktop (loopback) with no positive id is trusted — single user."""
    _contact_groups_db(monkeypatch, tmp_path, [
        {"id": "gl", "name": "Local", "account_id": -1, "members": [], "use_count": 0},
    ])
    with patch("app.api.contact_groups._resolve_account_id_for_user", return_value=-1):
        resp = client.get("/api/contact-groups", environ_base=LOOPBACK)
    assert resp.status_code == 200
    assert [g["name"] for g in resp.get_json()["groups"]] == ["Local"]


# --------------------------------------------------------------------------- #
# Reminders
# --------------------------------------------------------------------------- #

def test_reminders_list_empty_for_preoauth_sentinel(client):
    """A -1 caller must see NO reminders (not the shared -1 bucket)."""
    others = [{"id": "r1", "account_id": -1, "subject": "Call investor", "type": "reminder"}]
    with patch("app.api.auth._decode_jwt", return_value=JWT), \
         patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=-1), \
         patch("app.api.auth._is_loopback", return_value=False), \
         patch("app.services.reminder_service._read", return_value=others):
        resp = client.get("/api/reminders", headers=AUTH, environ_base=REMOTE)
    assert resp.status_code == 200
    assert resp.get_json()["reminders"] == []


def test_reminders_create_rejected_for_preoauth_sentinel(client):
    with patch("app.api.auth._decode_jwt", return_value=JWT), \
         patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=-1), \
         patch("app.api.auth._is_loopback", return_value=False), \
         patch("app.services.reminder_service.add_reminder") as add:
        resp = client.post(
            "/api/reminders",
            headers=AUTH, environ_base=REMOTE,
            json={"email_id": "e1", "reminder_date": "2026-06-01T09:00:00"},
        )
    assert resp.status_code == 401
    add.assert_not_called()


def test_reminders_delete_rejected_for_preoauth_sentinel(client):
    with patch("app.api.auth._decode_jwt", return_value=JWT), \
         patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=-1), \
         patch("app.api.auth._is_loopback", return_value=False), \
         patch("app.services.reminder_service.dismiss_reminder") as dismiss:
        resp = client.delete("/api/reminders/r1", headers=AUTH, environ_base=REMOTE)
    assert resp.status_code == 404
    dismiss.assert_not_called()
