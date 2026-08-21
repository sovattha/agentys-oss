# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Migration 039 : ``data/contact_groups.json`` → table ``contact_groups``.

Prouve les trois propriétés de la migration de persistance :
1. **Contrat intact** — CRUD complet via l'API avec les mêmes shapes/erreurs
   que le store JSON historique (tri use_count desc puis nom, 404 par compte,
   400 doublon de nom insensible à la casse).
2. **Isolation par compte** — un tenant ne voit/modifie/supprime JAMAIS les
   groupes d'un autre (la classe de bugs « -1 sentinel » de l'audit
   2026-05-29 reste fermée côté DB).
3. **Import legacy one-shot sans perte** — le JSON existant est importé au
   premier accès (orphelins -1 compris), le fichier est parqué en
   ``.imported``, l'opération est idempotente par PK, et un JSON corrompu ne
   casse pas l'API ni ne détruit le fichier.
"""

import json
import os
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
from app.db.models.contact_group import ContactGroupRow


@pytest.fixture
def db(tmp_path, monkeypatch):
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
    legacy_path = str(tmp_path / "contact_groups.json")
    monkeypatch.setattr(cg, "GROUPS_FILE", legacy_path)
    monkeypatch.setattr(cg, "_legacy_import_done", False)
    yield {"cm": _cm, "legacy_path": legacy_path, "SessionLocal": SessionLocal}
    engine.dispose()


@pytest.fixture
def app_client(db):
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(contact_groups_bp)
    return app.test_client()


def _as_account(account_id: int):
    return patch(
        "app.api.contact_groups._resolve_account_id_for_user",
        return_value=account_id,
    )


def _create(client, name, *, emails=("a@b.c",), **extra):
    payload = {
        "name": name,
        "members": [{"name": "M", "email": e} for e in emails],
        **extra,
    }
    return client.post(
        "/api/contact-groups",
        data=json.dumps(payload),
        content_type="application/json",
    )


class TestCrudContract:
    """Le contrat de l'API est identique au store JSON historique."""

    def test_create_then_get_roundtrip(self, app_client):
        with _as_account(1):
            resp = _create(app_client, "Équipe", emails=("x@y.z",), emoji="👥")
            assert resp.status_code == 201
            created = resp.get_json()["group"]
            assert created["id"].startswith("grp_")
            assert created["account_id"] == 1
            assert created["use_count"] == 0
            assert created["members"] == [{"name": "M", "email": "x@y.z"}]
            assert created["created_at"]  # isoformat string

            got = app_client.get(f"/api/contact-groups/{created['id']}")
            assert got.status_code == 200
            assert got.get_json()["group"] == created

    def test_duplicate_name_same_account_rejected_case_insensitive(self, app_client):
        with _as_account(1):
            assert _create(app_client, "Board").status_code == 201
            resp = _create(app_client, "bOaRd")
            assert resp.status_code == 400
            assert "already exists" in resp.get_json()["error"]

    def test_same_name_other_account_allowed(self, app_client):
        with _as_account(1):
            assert _create(app_client, "Board").status_code == 201
        with _as_account(2):
            assert _create(app_client, "Board").status_code == 201

    def test_list_sorted_by_use_count_then_name(self, app_client):
        with _as_account(1):
            gid_b = _create(app_client, "Bravo").get_json()["group"]["id"]
            _create(app_client, "Alpha")
            _create(app_client, "Charlie")
            # Bravo gagne 2 utilisations → premier malgré l'ordre alpha
            app_client.post(f"/api/contact-groups/{gid_b}/use")
            app_client.post(f"/api/contact-groups/{gid_b}/use")

            resp = app_client.get("/api/contact-groups")
            body = resp.get_json()
            assert body["total"] == 3
            assert [g["name"] for g in body["groups"]] == ["Bravo", "Alpha", "Charlie"]
            assert body["groups"][0]["use_count"] == 2

    def test_update_and_delete(self, app_client):
        with _as_account(1):
            gid = _create(app_client, "Old").get_json()["group"]["id"]
            resp = app_client.put(
                f"/api/contact-groups/{gid}",
                data=json.dumps({
                    "name": "New",
                    "members": [{"name": "Z", "email": "z@z.z"}],
                    "virtual_meeting": True,
                }),
                content_type="application/json",
            )
            assert resp.status_code == 200
            g = resp.get_json()["group"]
            assert g["name"] == "New"
            assert g["virtual_meeting"] is True
            assert g["members"] == [{"name": "Z", "email": "z@z.z"}]

            assert app_client.delete(f"/api/contact-groups/{gid}").status_code == 200
            assert app_client.get(f"/api/contact-groups/{gid}").status_code == 404

    def test_use_endpoint_404_on_unknown(self, app_client):
        with _as_account(1):
            assert app_client.post("/api/contact-groups/grp_nope/use").status_code == 404


class TestAccountIsolation:
    """Un tenant ne touche jamais les groupes d'un autre."""

    def test_list_is_scoped(self, app_client):
        with _as_account(1):
            _create(app_client, "Mine")
        with _as_account(2):
            body = app_client.get("/api/contact-groups").get_json()
            assert body["total"] == 0
            assert body["groups"] == []

    def test_cross_account_get_update_delete_use_are_404(self, app_client):
        with _as_account(1):
            gid = _create(app_client, "Secret").get_json()["group"]["id"]
        with _as_account(2):
            assert app_client.get(f"/api/contact-groups/{gid}").status_code == 404
            assert app_client.put(
                f"/api/contact-groups/{gid}",
                data=json.dumps({"name": "Hacked"}),
                content_type="application/json",
            ).status_code == 404
            assert app_client.delete(f"/api/contact-groups/{gid}").status_code == 404
            assert app_client.post(f"/api/contact-groups/{gid}/use").status_code == 404
        # Et le groupe est intact pour son propriétaire
        with _as_account(1):
            got = app_client.get(f"/api/contact-groups/{gid}")
            assert got.status_code == 200
            assert got.get_json()["group"]["name"] == "Secret"


class TestLegacyJsonImport:
    """Import one-shot du store JSON historique, sans perte ni doublon."""

    LEGACY = [
        {
            "id": "grp_legacy00001",
            "name": "Clients VIP",
            "emoji": "⭐",
            "description": None,
            "label_name": "vip",
            "members": [{"name": "K", "email": "k@client.com"}],
            "created_at": "2026-01-15T10:00:00",
            "updated_at": "2026-02-01T09:30:00",
            "use_count": 7,
            "account_id": 1,
            "virtual_meeting": True,
        },
        # Pré-isolation : pas d'account_id ni de virtual_meeting (défauts
        # historiques de _load_groups : -1 / False), timestamp illisible.
        {
            "id": "grp_orphan00001",
            "name": "Orphan",
            "members": [],
            "created_at": "not-a-date",
            "updated_at": None,
            "use_count": 0,
        },
    ]

    def _seed_legacy(self, db, payload=None):
        with open(db["legacy_path"], "w", encoding="utf-8") as f:
            if isinstance(payload, str):
                f.write(payload)
            else:
                json.dump(payload if payload is not None else self.LEGACY, f)

    def test_first_access_imports_and_parks_file(self, app_client, db):
        self._seed_legacy(db)
        with _as_account(1):
            body = app_client.get("/api/contact-groups").get_json()
        # Le groupe du compte 1 est servi depuis la DB, fidèlement
        assert body["total"] == 1
        g = body["groups"][0]
        assert g["id"] == "grp_legacy00001"
        assert g["use_count"] == 7
        assert g["virtual_meeting"] is True
        assert g["members"] == [{"name": "K", "email": "k@client.com"}]
        assert g["created_at"].startswith("2026-01-15T10:00:00")
        # L'orphelin -1 est importé mais invisible pour un compte positif
        with db["cm"]() as s:
            orphan = s.get(ContactGroupRow, "grp_orphan00001")
            assert orphan is not None
            assert orphan.account_id == -1
            assert orphan.virtual_meeting is False
        # Le fichier est parqué (backup) — plus de double source de vérité
        assert not os.path.exists(db["legacy_path"])
        assert os.path.exists(db["legacy_path"] + ".imported")

    def test_import_is_idempotent_by_pk(self, app_client, db):
        self._seed_legacy(db)
        with _as_account(1):
            app_client.get("/api/contact-groups")
        # Simule un redémarrage process AVEC un fichier legacy restauré
        os.replace(db["legacy_path"] + ".imported", db["legacy_path"])
        cg._legacy_import_done = False
        with _as_account(1):
            body = app_client.get("/api/contact-groups").get_json()
        assert body["total"] == 1  # pas de doublon
        with db["cm"]() as s:
            assert s.query(ContactGroupRow).count() == 2

    def test_corrupt_json_does_not_break_api_nor_destroy_file(self, app_client, db):
        self._seed_legacy(db, payload="{not json")
        with _as_account(1):
            resp = app_client.get("/api/contact-groups")
        assert resp.status_code == 200
        assert resp.get_json()["total"] == 0
        # Fichier laissé en place pour diagnostic / retry au prochain process
        assert os.path.exists(db["legacy_path"])

    def test_db_groups_win_over_replayed_legacy(self, app_client, db):
        """Un groupe modifié en DB n'est pas écrasé par un rejeu du JSON."""
        self._seed_legacy(db)
        with _as_account(1):
            app_client.get("/api/contact-groups")
            app_client.put(
                "/api/contact-groups/grp_legacy00001",
                data=json.dumps({"name": "Renamed in DB"}),
                content_type="application/json",
            )
        os.replace(db["legacy_path"] + ".imported", db["legacy_path"])
        cg._legacy_import_done = False
        with _as_account(1):
            body = app_client.get("/api/contact-groups").get_json()
        assert [g["name"] for g in body["groups"]] == ["Renamed in DB"]


class TestConsumersOnDb:
    """Les consommateurs hors blueprint (purge compte, suppression de label)
    opèrent sur la table — et restent scopés par compte."""

    def test_account_purge_removes_only_that_accounts_groups(self, app_client, db):
        from app.api.accounts import _purge_contact_groups_for_account

        with _as_account(1):
            _create(app_client, "Doomed A")
            _create(app_client, "Doomed B")
        with _as_account(2):
            _create(app_client, "Survivor")

        _purge_contact_groups_for_account(1)

        with _as_account(1):
            assert app_client.get("/api/contact-groups").get_json()["total"] == 0
        with _as_account(2):
            body = app_client.get("/api/contact-groups").get_json()
            assert [g["name"] for g in body["groups"]] == ["Survivor"]

    def test_label_unlink_is_account_scoped(self, app_client, db):
        """Supprimer le label « proj » du compte 1 ne touche PAS le groupe
        homonyme du compte 2 — l'ancien parcours JSON global le faisait."""
        from app.api.labels import _clear_label_from_contact_groups

        with _as_account(1):
            gid1 = _create(app_client, "G1", label_name="proj").get_json()["group"]["id"]
        with _as_account(2):
            gid2 = _create(app_client, "G2", label_name="proj").get_json()["group"]["id"]

        cleared = _clear_label_from_contact_groups("proj", 1)
        assert cleared == 1

        with _as_account(1):
            assert app_client.get(f"/api/contact-groups/{gid1}").get_json()["group"]["label_name"] is None
        with _as_account(2):
            assert app_client.get(f"/api/contact-groups/{gid2}").get_json()["group"]["label_name"] == "proj"


class TestForwardHandlerLookup:
    """`_get_group_by_id` (consommé par quicksteps forward) lit la DB."""

    def test_lookup_returns_legacy_shaped_dict(self, app_client, db):
        with _as_account(4):
            gid = _create(app_client, "Ops", emails=("ops@corp.com",)).get_json()["group"]["id"]
        group = cg._get_group_by_id(gid)
        assert group is not None
        assert group["account_id"] == 4
        assert group["members"] == [{"name": "M", "email": "ops@corp.com"}]
        assert cg._get_group_by_id("grp_missing") is None
