# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Suite de CARACTÉRISATION du contrat /api/snippets (11 endpoints).

Écrite AVANT la migration de persistance JSON → DB (chantier « sources de
vérité », même recette que contact_groups / migration 039) : cette suite
épingle le contrat observable du backend actuel — shapes de réponse, codes
d'erreur (`error_code`), règles d'accès (owner par email, legacy unowned
visible par tous, partages), tri, sémantique du filtre account_id — et DOIT
passer à l'identique avant et après la migration.

Particularités du contrat épinglées ici (à préserver) :
- ``owner_email = None`` (snippet legacy) ⇒ visible/éditable par TOUT
  utilisateur authentifié (``_is_owner`` retourne True pour tous).
- ``account_id = None`` ⇒ visible quel que soit le filtre ``?account_id=``.
- Unicité du nom insensible à la casse, dans le périmètre du propriétaire.
- Suppression d'un snippet ⇒ cascade de ses partages.
- Timestamps ISO 8601 timezone-aware (UTC, suffixe +00:00).
"""

import json
from unittest.mock import patch

import pytest
from flask import Flask

import app.api.snippets as snippets_module
from app.api.snippets import snippets_bp

OWNER = "owner@example.com"
OTHER = "other@example.com"


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Stockage isolé : fichiers legacy tmp + DB SQLite mémoire rebindée.

    La suite a d'abord tourné GREEN sur le backend JSON (pré-migration 040,
    le rebind DB était alors inerte) ; elle tourne désormais sur le backend
    DB avec import legacy actif — même contrat, prouvé par la même suite.
    Le test `test_legacy_unowned_visible_to_everyone` écrit dans le fichier
    legacy APRÈS un premier accès API : on reset le flag d'import pour que
    le rejeu paresseux l'absorbe (équivalent d'un restart process).
    """
    from contextlib import contextmanager

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.db.models import Base

    snippets_file = tmp_path / "snippets.json"
    shares_file = tmp_path / "snippet_shares.json"
    monkeypatch.setattr(snippets_module, "SNIPPETS_FILE", str(snippets_file))
    monkeypatch.setattr(snippets_module, "SHARES_FILE", str(shares_file))
    monkeypatch.setattr(snippets_module, "_legacy_import_done", False)

    engine = create_engine(
        "sqlite://", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
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
    yield {"snippets": snippets_file, "shares": shares_file}
    engine.dispose()


@pytest.fixture
def client(store):
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(snippets_bp)
    return app.test_client()


def _as_user(email: str):
    """Authentifie les appels comme `email` (JWT mocké)."""
    return patch(
        "app.api.auth._decode_jwt",
        return_value={"sub": "u-" + email, "email": email},
    )


AUTH = {"Authorization": "Bearer tok"}


def _create(client, name, *, content="Hello", **extra):
    return client.post(
        "/api/snippets",
        headers=AUTH,
        data=json.dumps({"name": name, "content": content, **extra}),
        content_type="application/json",
    )


class TestAuthGate:
    def test_unauthenticated_is_401(self, client):
        resp = client.get("/api/snippets")
        assert resp.status_code == 401
        assert resp.get_json()["error_code"] == "NOT_AUTHENTICATED"


class TestListScoping:
    def test_own_and_legacy_visible_others_hidden(self, client):
        with _as_user(OWNER):
            _create(client, "Mine")
        with _as_user(OTHER):
            _create(client, "Theirs")
        # Snippet legacy sans owner : visible par tous (contrat historique)
        with _as_user(OWNER):
            resp = client.get("/api/snippets", headers=AUTH)
            names = [s["name"] for s in resp.get_json()["snippets"]]
        assert "Mine" in names
        assert "Theirs" not in names

    def test_legacy_unowned_visible_to_everyone(self, client, store):
        # Seed le store legacy AVANT tout accès API : snippet sans owner_email
        # ni account_id (pré-isolation). Contrat historique : visible par tous.
        store["snippets"].write_text(json.dumps([{
            "id": "snippet_legacy00001", "name": "Legacy", "content": "Old",
            "subject": None, "to": None, "cc": None, "bcc": None,
            "category": None, "is_private": True,
            "created_at": "2025-01-01T00:00:00+00:00",
            "updated_at": "2025-01-01T00:00:00+00:00", "use_count": 0,
        }], ensure_ascii=False), encoding="utf-8")
        with _as_user(OWNER):
            _create(client, "Mine")
        for user in (OWNER, OTHER):
            with _as_user(user):
                names = [s["name"] for s in
                         client.get("/api/snippets", headers=AUTH).get_json()["snippets"]]
            assert "Legacy" in names, f"legacy doit être visible pour {user}"

    def test_account_id_filter_semantics(self, client):
        with _as_user(OWNER):
            _create(client, "AccountOne", account_id=1)
            _create(client, "AccountTwo", account_id=2)
            _create(client, "NoAccount")  # account_id None → visible partout

            all_names = [s["name"] for s in
                         client.get("/api/snippets", headers=AUTH).get_json()["snippets"]]
            acc1_names = [s["name"] for s in
                          client.get("/api/snippets?account_id=1", headers=AUTH).get_json()["snippets"]]
        assert sorted(all_names) == ["AccountOne", "AccountTwo", "NoAccount"]
        assert sorted(acc1_names) == ["AccountOne", "NoAccount"]

    def test_sorted_by_use_count_then_name(self, client):
        with _as_user(OWNER):
            sid = _create(client, "Bravo").get_json()["snippet"]["id"]
            _create(client, "Alpha")
            client.post(f"/api/snippets/{sid}/use", headers=AUTH)
            names = [s["name"] for s in
                     client.get("/api/snippets", headers=AUTH).get_json()["snippets"]]
        assert names == ["Bravo", "Alpha"]


class TestCrudContract:
    def test_create_shape_and_defaults(self, client):
        with _as_user(OWNER):
            resp = _create(client, "Sig", content="Best regards", subject="Re: hello",
                           category="signature")
        assert resp.status_code == 201
        s = resp.get_json()["snippet"]
        assert s["id"].startswith("snippet_")
        assert s["owner_email"] == OWNER
        assert s["is_private"] is True
        assert s["use_count"] == 0
        assert s["account_id"] is None
        assert s["subject"] == "Re: hello"
        assert "+00:00" in s["created_at"]  # ISO aware UTC (contrat historique)

    def test_create_validations(self, client):
        with _as_user(OWNER):
            assert _create(client, "", content="x").status_code == 400
            assert _create(client, "NoContent", content="").status_code == 400
            _create(client, "Dup")
            resp = _create(client, "dUp")
        assert resp.status_code == 400
        assert "already exists" in resp.get_json()["error"]

    def test_same_name_allowed_for_other_user(self, client):
        with _as_user(OWNER):
            assert _create(client, "Shared name").status_code == 201
        with _as_user(OTHER):
            assert _create(client, "Shared name").status_code == 201

    def test_get_owner_ok_other_403_unknown_404(self, client):
        with _as_user(OWNER):
            sid = _create(client, "Private").get_json()["snippet"]["id"]
            assert client.get(f"/api/snippets/{sid}", headers=AUTH).status_code == 200
            assert client.get("/api/snippets/snippet_nope", headers=AUTH).status_code == 404
        with _as_user(OTHER):
            resp = client.get(f"/api/snippets/{sid}", headers=AUTH)
        assert resp.status_code == 403
        assert resp.get_json()["error_code"] == "ACCESS_DENIED"

    def test_update_owner_only(self, client):
        with _as_user(OWNER):
            sid = _create(client, "Editable").get_json()["snippet"]["id"]
        with _as_user(OTHER):
            resp = client.put(
                f"/api/snippets/{sid}", headers=AUTH,
                data=json.dumps({"name": "Hacked"}),
                content_type="application/json",
            )
            assert resp.status_code == 403
        with _as_user(OWNER):
            resp = client.put(
                f"/api/snippets/{sid}", headers=AUTH,
                data=json.dumps({"name": "Renamed", "content": "New body"}),
                content_type="application/json",
            )
            assert resp.status_code == 200
            assert resp.get_json()["snippet"]["name"] == "Renamed"
            # contenu vide refusé
            resp = client.put(
                f"/api/snippets/{sid}", headers=AUTH,
                data=json.dumps({"content": "  "}),
                content_type="application/json",
            )
            assert resp.status_code == 400

    def test_delete_owner_only_and_use_increments(self, client):
        with _as_user(OWNER):
            sid = _create(client, "Doomed").get_json()["snippet"]["id"]
            resp = client.post(f"/api/snippets/{sid}/use", headers=AUTH)
            assert resp.get_json()["snippet"]["use_count"] == 1
        with _as_user(OTHER):
            assert client.delete(f"/api/snippets/{sid}", headers=AUTH).status_code == 403
        with _as_user(OWNER):
            assert client.delete(f"/api/snippets/{sid}", headers=AUTH).status_code == 200
            assert client.get(f"/api/snippets/{sid}", headers=AUTH).status_code == 404


class TestSharing:
    def _share(self, client, sid, target=OTHER):
        return client.post(
            f"/api/snippets/{sid}/share", headers=AUTH,
            data=json.dumps({"email": target}),
            content_type="application/json",
        )

    def test_share_flow_and_shared_with_me(self, client):
        with _as_user(OWNER):
            sid = _create(client, "Team sig").get_json()["snippet"]["id"]
            with patch("app.api.snippets.is_known_user", return_value=True):
                resp = self._share(client, sid)
            assert resp.status_code == 201
            share = resp.get_json()["share"]
            assert share["shared_by"] == OWNER
            assert share["shared_with"] == OTHER

            shares = client.get(f"/api/snippets/{sid}/shares", headers=AUTH).get_json()
            assert shares["total"] == 1
            assert shares["shares"][0]["email"] == OTHER

        with _as_user(OTHER):
            mine = client.get("/api/snippets/shared-with-me", headers=AUTH).get_json()
            assert mine["total"] == 1
            assert mine["snippets"][0]["id"] == sid
            assert mine["snippets"][0]["shared_by"] == OWNER
            # accès lecture via partage
            assert client.get(f"/api/snippets/{sid}", headers=AUTH).status_code == 200

    def test_share_validations(self, client):
        with _as_user(OWNER):
            sid = _create(client, "S").get_json()["snippet"]["id"]
            assert self._share(client, sid, target="notanemail").status_code == 400
            resp = self._share(client, sid, target=OWNER)
            assert resp.status_code == 400
            assert resp.get_json()["error_code"] == "SNIPPET_CANNOT_SHARE_WITH_SELF"
            with patch("app.api.snippets.is_known_user", return_value=False):
                resp = self._share(client, sid)
            assert resp.status_code == 404
            assert resp.get_json()["error_code"] == "SNIPPET_EMAIL_NOT_USER"
            with patch("app.api.snippets.is_known_user", return_value=True):
                assert self._share(client, sid).status_code == 201
                resp = self._share(client, sid)
            assert resp.status_code == 400
            assert resp.get_json()["error_code"] == "SNIPPET_ALREADY_SHARED"

    def test_non_owner_cannot_share_or_list_shares(self, client):
        with _as_user(OWNER):
            sid = _create(client, "Locked").get_json()["snippet"]["id"]
        with _as_user(OTHER):
            with patch("app.api.snippets.is_known_user", return_value=True):
                assert self._share(client, sid, target="x@y.z").status_code == 403
            assert client.get(f"/api/snippets/{sid}/shares", headers=AUTH).status_code == 403

    def test_unshare(self, client):
        with _as_user(OWNER):
            sid = _create(client, "U").get_json()["snippet"]["id"]
            with patch("app.api.snippets.is_known_user", return_value=True):
                self._share(client, sid)
            assert client.delete(
                f"/api/snippets/{sid}/share", headers=AUTH).status_code == 400
            assert client.delete(
                f"/api/snippets/{sid}/share?email={OTHER}", headers=AUTH).status_code == 200
            resp = client.delete(
                f"/api/snippets/{sid}/share?email={OTHER}", headers=AUTH)
            assert resp.status_code == 404
        with _as_user(OTHER):
            assert client.get(
                "/api/snippets/shared-with-me", headers=AUTH).get_json()["total"] == 0

    def test_delete_cascades_shares(self, client):
        with _as_user(OWNER):
            sid = _create(client, "Cascade").get_json()["snippet"]["id"]
            with patch("app.api.snippets.is_known_user", return_value=True):
                self._share(client, sid)
            client.delete(f"/api/snippets/{sid}", headers=AUTH)
        with _as_user(OTHER):
            assert client.get(
                "/api/snippets/shared-with-me", headers=AUTH).get_json()["total"] == 0


class TestDuplicate:
    def test_shared_user_can_duplicate_with_copy_naming(self, client):
        with _as_user(OWNER):
            sid = _create(client, "Modèle").get_json()["snippet"]["id"]
            with patch("app.api.snippets.is_known_user", return_value=True):
                client.post(
                    f"/api/snippets/{sid}/share", headers=AUTH,
                    data=json.dumps({"email": OTHER}),
                    content_type="application/json",
                )
        with _as_user(OTHER):
            # NB contrat : duplicate exige un content-type JSON (415 sinon)
            r1 = client.post(f"/api/snippets/{sid}/duplicate", headers=AUTH,
                             data="{}", content_type="application/json")
            assert r1.status_code == 201
            assert r1.get_json()["snippet"]["name"] == "Modèle (copie)"
            assert r1.get_json()["snippet"]["owner_email"] == OTHER
            assert r1.get_json()["snippet"]["is_private"] is True
            r2 = client.post(f"/api/snippets/{sid}/duplicate", headers=AUTH,
                             data="{}", content_type="application/json")
            assert r2.get_json()["snippet"]["name"] == "Modèle (copie 2)"

    def test_non_shared_user_cannot_duplicate(self, client):
        with _as_user(OWNER):
            sid = _create(client, "Sécret").get_json()["snippet"]["id"]
        with _as_user(OTHER):
            assert client.post(
                f"/api/snippets/{sid}/duplicate", headers=AUTH,
                data="{}", content_type="application/json").status_code == 403
