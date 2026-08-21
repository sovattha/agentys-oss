# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Migration 042 : ``data/calendar_suggestions.json`` → table DB.

Mêmes propriétés que les migrations sœurs (039/040/041) : roundtrip exact
des records, import legacy one-shot (objet racine, idempotent par PK,
parking ``.imported``, corruption → quarantaine), purge par compte (trou
RGPD comblé — rien ne purgeait les suggestions d'un compte supprimé), et
cycle de vie via les routes (add → list → accept/reject).
"""

import json
import os
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.services.calendar_suggestion_store as sugg_store
from app.db.models import Base

ACC = "acc_hash_a"
OTHER_ACC = "acc_hash_b"


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
    legacy = tmp_path / "calendar_suggestions.json"
    monkeypatch.setattr(sugg_store, "SUGGESTIONS_FILE", str(legacy))
    monkeypatch.setattr(sugg_store, "_legacy_import_done", False)
    # accept_suggestion crée un followup → neutralise aussi son store legacy
    import app.services.followup_store as fu_store
    monkeypatch.setattr(fu_store, "FOLLOWUPS_FILE", str(tmp_path / "followups.json"))
    monkeypatch.setattr(fu_store, "_legacy_import_done", False)
    yield {"cm": _cm, "legacy": legacy, "tmp": tmp_path}
    engine.dispose()


def _record(**overrides):
    base = {
        "email_id": "e1",
        "account_id": ACC,
        "description": "Envoyer le devis vendredi",
        "deadline": "2026-06-20",
        "status": "pending",
        "created_at": "2026-06-12T08:00:00+00:00",
        "email_subject": "Devis",
        "email_sender": "client@x.com",
        "draft_body_preview": "Bonjour…",
    }
    base.update(overrides)
    return base


class TestStoreRoundtrip:
    def test_save_get_roundtrip_exact(self, db):
        rec = _record()
        sugg_store.save_record("s1", rec)
        assert sugg_store.get_record("s1") == rec
        assert sugg_store.get_record("missing") is None

    def test_purge_account_scoped(self, db):
        sugg_store.save_record("s1", _record())
        sugg_store.save_record("s2", _record(account_id=OTHER_ACC))
        assert sugg_store.delete_all_for_account(ACC) == 1
        assert [sid for sid, _ in sugg_store.all_records()] == ["s2"]


class TestLegacyImport:
    def test_import_parks_and_is_idempotent(self, db):
        db["legacy"].write_text(json.dumps({"s1": _record()}), encoding="utf-8")
        assert sugg_store.get_record("s1")["description"] == "Envoyer le devis vendredi"
        assert os.path.exists(str(db["legacy"]) + ".imported")
        # Rejeu : la DB gagne
        rec = sugg_store.get_record("s1")
        rec["description"] = "Modifié en DB"
        sugg_store.save_record("s1", rec)
        os.replace(str(db["legacy"]) + ".imported", str(db["legacy"]))
        sugg_store._legacy_import_done = False
        assert sugg_store.get_record("s1")["description"] == "Modifié en DB"
        assert len(sugg_store.all_records()) == 1

    def test_corrupt_json_quarantined(self, db):
        db["legacy"].write_text("{not json", encoding="utf-8")
        assert sugg_store.all_records() == []
        assert not os.path.exists(db["legacy"])
        assert list(db["tmp"].glob("calendar_suggestions.json.corrupt-*"))


class TestRoutesLifecycleOnDb:
    @pytest.fixture
    def app(self):
        from app.api.app import create_app
        return create_app({"TESTING": True})

    def test_add_list_accept_reject(self, app, db):
        from app.api import calendar as cal

        with patch.object(cal, "_validate_account_ownership", side_effect=lambda aid: aid):
            sid1 = cal.add_suggestion(
                email_id="e1", account_id=ACC, description="Relancer A",
                draft_body="x" * 300,
            )
            sid2 = cal.add_suggestion(
                email_id="e2", account_id=ACC, description="Relancer B",
            )
            # draft_body tronqué à 200 (contrat historique)
            assert len(sugg_store.get_record(sid1)["draft_body_preview"]) == 200

            with app.test_request_context("/api/calendar/suggestions?status=pending"):
                body = cal.list_suggestions().get_json()
            assert body["count"] == 2

            with app.test_request_context(
                f"/api/calendar/suggestions/{sid1}/accept", method="POST", json={},
            ):
                resp = cal.accept_suggestion(sid1)
            assert resp.get_json()["success"] is True
            assert sugg_store.get_record(sid1)["status"] == "accepted"
            # Le followup créé depuis la suggestion existe en DB
            from app.services import followup_store
            fid = resp.get_json()["followup_id"]
            assert followup_store.get_record(fid)["auto_created"] is True

            with app.test_request_context(
                f"/api/calendar/suggestions/{sid2}/reject", method="POST", json={},
            ):
                resp = cal.reject_suggestion(sid2)
            assert resp.get_json()["success"] is True
            assert sugg_store.get_record(sid2)["status"] == "rejected"

            # Double-accept refusé (contrat historique)
            with app.test_request_context(
                f"/api/calendar/suggestions/{sid1}/accept", method="POST", json={},
            ):
                resp = cal.accept_suggestion(sid1)
            assert resp[1] == 400
