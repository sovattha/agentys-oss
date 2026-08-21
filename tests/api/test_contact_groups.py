# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour POST/PUT /api/contact-groups — champs optionnels en JSON null.

Régression : le frontend envoie `label_name: null` quand aucun projet
n'est sélectionné dans le formulaire "New group". Le backend faisait
`data.get("label_name", "").strip()` qui crash sur None en AttributeError,
renvoyant 500 "Internal server error" visible dans la modale.

Post-migration 039 (JSON → table ``contact_groups``) : le store est
SQLAlchemy ; les fixtures montent une DB SQLite en mémoire et rebindent
``app.db.database.get_db_session``. Le contrat de réponse est inchangé —
ces tests le prouvent en tournant tels quels sur le nouveau backend.
"""

import json
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.api.contact_groups as cg
from app.api.contact_groups import contact_groups_bp
from app.db.models import Base


@pytest.fixture
def db_session_cm(tmp_path, monkeypatch):
    """DB SQLite mémoire + rebind de get_db_session + import legacy neutralisé."""
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False)

    @contextmanager
    def _cm():
        s = SessionLocal()
        try:
            yield s
        finally:
            s.close()

    monkeypatch.setattr("app.db.database.get_db_session", _cm)
    monkeypatch.setattr(cg, "GROUPS_FILE", str(tmp_path / "contact_groups.json"))
    monkeypatch.setattr(cg, "_legacy_import_done", False)
    yield _cm
    engine.dispose()


@pytest.fixture
def client(db_session_cm):
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(contact_groups_bp)
    with patch("app.api.contact_groups._resolve_account_id_for_user", return_value=1):
        yield app.test_client()


class TestCreateGroupOptionalNullFields:
    """Le frontend peut envoyer label_name/emoji/description=null (JSON null).
    Le backend doit normaliser None → "" avant .strip() sinon 500."""

    def test_label_name_null_creates_group(self, client):
        resp = client.post(
            "/api/contact-groups",
            data=json.dumps({
                "name": "agentys",
                "members": [{"name": "Alex", "email": "alex@example.com"}],
                "label_name": None,  # le cas qui crashait
                "virtual_meeting": True,
            }),
            content_type="application/json",
        )
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["group"]["name"] == "agentys"
        assert body["group"]["label_name"] is None
        assert body["group"]["virtual_meeting"] is True

    def test_all_optional_fields_null(self, client):
        resp = client.post(
            "/api/contact-groups",
            data=json.dumps({
                "name": "g1",
                "members": [{"name": "X", "email": "x@y.z"}],
                "emoji": None,
                "description": None,
                "label_name": None,
            }),
            content_type="application/json",
        )
        assert resp.status_code == 201
        g = resp.get_json()["group"]
        assert g["emoji"] is None
        assert g["description"] is None
        assert g["label_name"] is None

    def test_member_name_null(self, client):
        """Le nom d'un membre peut être null (contact typé à la main)."""
        resp = client.post(
            "/api/contact-groups",
            data=json.dumps({
                "name": "g2",
                "members": [{"name": None, "email": "noname@example.com"}],
            }),
            content_type="application/json",
        )
        assert resp.status_code == 201
        members = resp.get_json()["group"]["members"]
        assert members[0]["name"] == ""
        assert members[0]["email"] == "noname@example.com"


class TestUpdateGroupOptionalNullFields:
    """Même contrat pour PUT /api/contact-groups/<id>."""

    def test_update_label_name_null(self, client):
        # seed a group
        resp = client.post(
            "/api/contact-groups",
            data=json.dumps({
                "name": "seed",
                "members": [{"name": "A", "email": "a@b.c"}],
                "label_name": "proj-x",
            }),
            content_type="application/json",
        )
        gid = resp.get_json()["group"]["id"]

        # clear label via null
        resp = client.put(
            f"/api/contact-groups/{gid}",
            data=json.dumps({"label_name": None}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.get_json()["group"]["label_name"] is None

    def test_update_name_null_is_rejected(self, client):
        """name=null doit être rejeté avec 400, pas 500."""
        resp = client.post(
            "/api/contact-groups",
            data=json.dumps({
                "name": "seed2",
                "members": [{"name": "A", "email": "a@b.c"}],
            }),
            content_type="application/json",
        )
        gid = resp.get_json()["group"]["id"]

        resp = client.put(
            f"/api/contact-groups/{gid}",
            data=json.dumps({"name": None}),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "empty" in resp.get_json()["error"].lower()
