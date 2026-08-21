# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Migration 041 : ``data/followups.json`` (dict mémoire de calendar.py) → table DB.

Propriétés prouvées :
- fidélité du store records (roundtrip exact du format historique) ;
- ``wake_snoozed`` : réveil des snoozes échus, tolérance aux dates illisibles
  (comportement historique de ``_wake_snoozed_followups``) ;
- import legacy one-shot : objet ``{id: record}``, idempotent par PK, parking
  ``.imported``, JSON corrompu → quarantaine ``.corrupt-<ts>`` (audit
  2026-05-11 P1, conservé) ;
- purge par compte (string OAuth hash) ;
- cycle de vie complet via les ROUTES calendar (create → list → complete →
  delete) sur le store DB.
"""

import json
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.services.followup_store as fu_store
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
    legacy = tmp_path / "followups.json"
    monkeypatch.setattr(fu_store, "FOLLOWUPS_FILE", str(legacy))
    monkeypatch.setattr(fu_store, "_legacy_import_done", False)
    yield {"cm": _cm, "legacy": legacy, "tmp": tmp_path}
    engine.dispose()


def _record(**overrides):
    base = {
        "email_id": "e1",
        "account_id": ACC,
        "title": "Relancer",
        "description": "desc",
        "due_date": "2026-06-20T10:00:00+00:00",
        "status": "pending",
        "created_at": "2026-06-12T08:00:00+00:00",
        "completed_at": None,
        "snoozed_until": None,
        "snooze_count": 0,
        "calendar_event_id": None,
        "sync_to_calendar": False,
        "email_subject": "Projet",
        "email_sender": "client@x.com",
        "auto_created": False,
        "ai_reason": None,
    }
    base.update(overrides)
    return base


class TestStoreRoundtrip:
    def test_save_get_roundtrip_exact(self, db):
        rec = _record(snooze_count=3, sync_to_calendar=True, ai_reason="détecté")
        fu_store.save_record("f1", rec)
        assert fu_store.get_record("f1") == rec
        assert fu_store.get_record("missing") is None

    def test_records_for_account_scoped(self, db):
        fu_store.save_record("f1", _record())
        fu_store.save_record("f2", _record(account_id=OTHER_ACC, title="Autre"))
        ids = [fid for fid, _ in fu_store.records_for_account(ACC)]
        assert ids == ["f1"]
        assert len(fu_store.all_records()) == 2

    def test_delete(self, db):
        fu_store.save_record("f1", _record())
        assert fu_store.delete_record("f1") is True
        assert fu_store.delete_record("f1") is False
        assert fu_store.get_record("f1") is None

    def test_purge_account(self, db):
        fu_store.save_record("f1", _record())
        fu_store.save_record("f2", _record(title="2"))
        fu_store.save_record("f3", _record(account_id=OTHER_ACC))
        assert fu_store.delete_all_for_account(ACC) == 2
        assert [fid for fid, _ in fu_store.all_records()] == ["f3"]


class TestWakeSnoozed:
    def test_wakes_only_elapsed_snoozes(self, db):
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        fu_store.save_record("elapsed", _record(status="snoozed", snoozed_until=past))
        fu_store.save_record("future", _record(status="snoozed", snoozed_until=future))
        fu_store.save_record("garbage", _record(status="snoozed", snoozed_until="banana"))

        assert fu_store.wake_snoozed() == 1

        assert fu_store.get_record("elapsed")["status"] == "pending"
        assert fu_store.get_record("elapsed")["snoozed_until"] is None
        assert fu_store.get_record("future")["status"] == "snoozed"
        # Tolérance historique : date illisible = laissé tel quel, pas de crash
        assert fu_store.get_record("garbage")["status"] == "snoozed"

    def test_naive_snooze_coerced_utc(self, db):
        naive_past = (datetime.now(timezone.utc) - timedelta(hours=2)).replace(tzinfo=None).isoformat()
        fu_store.save_record("naive", _record(status="snoozed", snoozed_until=naive_past))
        assert fu_store.wake_snoozed() == 1
        assert fu_store.get_record("naive")["status"] == "pending"


class TestLegacyImport:
    def test_import_object_root_faithfully_and_parks(self, db):
        db["legacy"].write_text(json.dumps({
            "fid-legacy": _record(snooze_count=2, auto_created=True),
            "fid-partial": {"account_id": ACC, "title": "Partiel"},  # record partiel
        }), encoding="utf-8")

        rec = fu_store.get_record("fid-legacy")  # 1er accès → import
        assert rec["snooze_count"] == 2
        assert rec["auto_created"] is True
        partial = fu_store.get_record("fid-partial")
        assert partial["status"] == "pending"  # défaut tolérant
        assert partial["snooze_count"] == 0
        assert not os.path.exists(db["legacy"])
        assert os.path.exists(str(db["legacy"]) + ".imported")

    def test_import_idempotent_by_pk(self, db):
        db["legacy"].write_text(json.dumps({"f1": _record()}), encoding="utf-8")
        fu_store.get_record("f1")
        os.replace(str(db["legacy"]) + ".imported", str(db["legacy"]))
        fu_store._legacy_import_done = False
        # Le record DB a été modifié entre-temps : le rejeu ne l'écrase pas
        rec = fu_store.get_record("f1")
        rec["title"] = "Modifié en DB"
        fu_store.save_record("f1", rec)
        fu_store._legacy_import_done = False
        assert fu_store.get_record("f1")["title"] == "Modifié en DB"
        assert len(fu_store.all_records()) == 1

    def test_corrupt_json_quarantined(self, db):
        db["legacy"].write_text("{not json", encoding="utf-8")
        assert fu_store.all_records() == []
        # Quarantaine historique (audit 2026-05-11 P1) : le fichier corrompu
        # est déplacé en .corrupt-<ts>, pas laissé à re-crasher chaque boot
        assert not os.path.exists(db["legacy"])
        corrupted = list(db["tmp"].glob("followups.json.corrupt-*"))
        assert len(corrupted) == 1


class TestRoutesLifecycleOnDb:
    """Cycle complet via les vues calendar (create → list → complete → delete)."""

    @pytest.fixture
    def app(self):
        from app.api.app import create_app
        return create_app({"TESTING": True})

    def test_full_lifecycle(self, app, db):
        from app.api import calendar as cal

        with patch.object(cal, "_validate_account_ownership", side_effect=lambda aid: aid), \
             patch.object(cal, "_get_current_account_id", return_value=ACC):
            # CREATE
            with app.test_request_context(
                "/api/calendar/followups", method="POST",
                json={
                    "email_id": "e9", "title": "Relancer X",
                    "due_date": "2026-06-25T09:00:00+00:00",
                    "account_id": ACC,
                },
            ):
                resp = cal.create_followup()
            assert resp[1] == 201
            fid = resp[0].get_json()["id"]

            # LIST (filtré compte + statut)
            with app.test_request_context(f"/api/calendar/followups?account_id={ACC}&status=pending"):
                body = cal.list_followups().get_json()
            assert body["count"] == 1
            assert body["followups"][0]["id"] == fid
            assert body["followups"][0]["title"] == "Relancer X"

            # PATCH action=complete
            with app.test_request_context(
                f"/api/calendar/followups/{fid}", method="PATCH",
                json={"action": "complete"},
            ):
                body = cal.update_followup(fid).get_json()
            assert body["followup"]["status"] == "completed"
            assert body["followup"]["completed_at"]

            # DELETE
            with app.test_request_context(f"/api/calendar/followups/{fid}", method="DELETE"):
                body = cal.delete_followup(fid).get_json()
            assert body["success"] is True
            assert fu_store.get_record(fid) is None
