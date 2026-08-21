# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Migration 040 : snippets.json + snippet_shares.json → tables DB.

Complète la suite de caractérisation (``test_snippets_contract.py``, qui
prouve le contrat constant) avec les propriétés propres à la MIGRATION :
import legacy one-shot des DEUX fichiers (fidélité, idempotence par PK,
parking ``.imported``, corruption tolérée), purge de compte à la sémantique
historique deux-modes avec cascade des partages.
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

import app.api.snippets as snippets_module
from app.api.snippets import snippets_bp
from app.db.models import Base
from app.db.models.snippet import SnippetRow, SnippetShareRow

OWNER = "owner@example.com"
OTHER = "other@example.com"
AUTH = {"Authorization": "Bearer tok"}

LEGACY_SNIPPETS = [
    {
        "id": "snippet_legacy0001",
        "name": "Relance facture",
        "content": "Bonjour, ...",
        "subject": "Relance",
        "to": "compta@client.com",
        "cc": None,
        "bcc": None,
        "category": "finance",
        "is_private": True,
        "owner_email": OWNER,
        "account_id": 3,
        "created_at": "2026-01-10T08:00:00+00:00",
        "updated_at": "2026-02-01T09:00:00+00:00",
        "use_count": 12,
    },
    # Legacy pré-ownership : owner/account absents, champs manquants
    {"id": "snippet_legacy0002", "name": "Old school", "content": "..."},
]

LEGACY_SHARES = [
    {
        "id": "share_legacy00001",
        "snippet_id": "snippet_legacy0001",
        "shared_by": OWNER,
        "shared_with": OTHER,
        "shared_at": "2026-03-01T10:00:00+00:00",
    },
]


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
    snippets_file = tmp_path / "snippets.json"
    shares_file = tmp_path / "snippet_shares.json"
    monkeypatch.setattr(snippets_module, "SNIPPETS_FILE", str(snippets_file))
    monkeypatch.setattr(snippets_module, "SHARES_FILE", str(shares_file))
    monkeypatch.setattr(snippets_module, "_legacy_import_done", False)
    yield {"cm": _cm, "snippets": snippets_file, "shares": shares_file}
    engine.dispose()


@pytest.fixture
def client(db):
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(snippets_bp)
    return app.test_client()


def _as_user(email: str):
    return patch(
        "app.api.auth._decode_jwt",
        return_value={"sub": "u-" + email, "email": email},
    )


def _seed_legacy(db, snippets=None, shares=None):
    db["snippets"].write_text(
        json.dumps(LEGACY_SNIPPETS if snippets is None else snippets,
                   ensure_ascii=False),
        encoding="utf-8",
    )
    db["shares"].write_text(
        json.dumps(LEGACY_SHARES if shares is None else shares, ensure_ascii=False),
        encoding="utf-8",
    )


class TestLegacyImport:
    def test_first_access_imports_both_files_faithfully(self, client, db):
        _seed_legacy(db)
        with _as_user(OWNER):
            body = client.get("/api/snippets", headers=AUTH).get_json()
        names = {s["name"] for s in body["snippets"]}
        assert names == {"Relance facture", "Old school"}
        legacy = next(s for s in body["snippets"] if s["id"] == "snippet_legacy0001")
        assert legacy["use_count"] == 12
        assert legacy["to"] == "compta@client.com"
        assert legacy["created_at"] == "2026-01-10T08:00:00+00:00"
        # Le partage legacy est importé et opérationnel
        with _as_user(OTHER):
            mine = client.get("/api/snippets/shared-with-me", headers=AUTH).get_json()
        assert mine["total"] == 1
        assert mine["snippets"][0]["id"] == "snippet_legacy0001"
        assert mine["snippets"][0]["share_id"] == "share_legacy00001"
        # Les deux fichiers sont parqués
        assert not os.path.exists(db["snippets"])
        assert os.path.exists(str(db["snippets"]) + ".imported")
        assert not os.path.exists(db["shares"])
        assert os.path.exists(str(db["shares"]) + ".imported")

    def test_import_is_idempotent_by_pk(self, client, db):
        _seed_legacy(db)
        with _as_user(OWNER):
            client.get("/api/snippets", headers=AUTH)
        # Restaure les fichiers (simule un vieux backup re-déposé) + restart
        os.replace(str(db["snippets"]) + ".imported", str(db["snippets"]))
        os.replace(str(db["shares"]) + ".imported", str(db["shares"]))
        snippets_module._legacy_import_done = False
        with _as_user(OWNER):
            body = client.get("/api/snippets", headers=AUTH).get_json()
        assert body["total"] == 2  # pas de doublon
        with db["cm"]() as s:
            assert s.query(SnippetRow).count() == 2
            assert s.query(SnippetShareRow).count() == 1

    def test_corrupt_snippets_json_does_not_break_api(self, client, db):
        db["snippets"].write_text("{not json", encoding="utf-8")
        with _as_user(OWNER):
            resp = client.get("/api/snippets", headers=AUTH)
        assert resp.status_code == 200
        assert resp.get_json()["total"] == 0
        # Fichier laissé en place pour diagnostic
        assert os.path.exists(db["snippets"])


class TestAccountPurgeSemantics:
    def _seed_via_api(self, client):
        with _as_user(OWNER):
            r1 = client.post(
                "/api/snippets", headers=AUTH,
                data=json.dumps({"name": "Tagged14", "content": "x", "account_id": 14}),
                content_type="application/json",
            ).get_json()["snippet"]
            r2 = client.post(
                "/api/snippets", headers=AUTH,
                data=json.dumps({"name": "NoAccount", "content": "x"}),
                content_type="application/json",
            ).get_json()["snippet"]
            with patch("app.api.snippets.is_known_user", return_value=True):
                client.post(
                    f"/api/snippets/{r1['id']}/share", headers=AUTH,
                    data=json.dumps({"email": OTHER}),
                    content_type="application/json",
                )
        return r1, r2

    def test_other_accounts_remain_only_tagged_snippets_purged(self, client, db):
        """Mode « il reste d'autres comptes » : seuls les snippets tagués
        account_id partent — et leurs partages cascadent."""
        from app.db.repositories.snippet_repository import SnippetRepository

        r1, r2 = self._seed_via_api(client)
        with db["cm"]() as s:
            removed, shares_removed = SnippetRepository(s).purge_for_account(
                14, OWNER, owner_has_no_more_accounts=False
            )
            s.commit()
        assert (removed, shares_removed) == (1, 1)
        with db["cm"]() as s:
            assert [r.id for r in s.query(SnippetRow).all()] == [r2["id"]]
            assert s.query(SnippetShareRow).count() == 0

    def test_last_account_purges_all_owner_snippets(self, client, db):
        from app.db.repositories.snippet_repository import SnippetRepository

        self._seed_via_api(client)
        with _as_user(OTHER):
            client.post(
                "/api/snippets", headers=AUTH,
                data=json.dumps({"name": "Survivor", "content": "x"}),
                content_type="application/json",
            )
        with db["cm"]() as s:
            removed, _shares = SnippetRepository(s).purge_for_account(
                14, OWNER, owner_has_no_more_accounts=True
            )
            s.commit()
        assert removed == 2
        with db["cm"]() as s:
            remaining = [r.owner_email for r in s.query(SnippetRow).all()]
        assert remaining == [OTHER]
