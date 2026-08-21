# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Migration 043 : ``data/scheduled_emails.db`` (SQLite annexe) → DB principale.

La suite historique (test_scheduled_email_store / _scheduler /
test_api_scheduled_emails — 64 tests) sert de caractérisation et passe
inchangée sur les nouveaux internals SQLAlchemy (seam ``db_path`` préservé).
Ce fichier couvre ce qui est PROPRE à la migration :
- import one-shot du fichier legacy (lignes par PK, schéma pré-attempts
  toléré, parking ``.imported``, idempotence, DB illisible sans crash) ;
- le store par défaut écrit dans la DB PRINCIPALE (plus de side-file) ;
- ``recover_stuck_sending(now=...)`` : sémantique stricte déterministe.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.services.scheduled_email_store as store_module
from app.db.models import Base
from app.db.models.scheduled_email import ScheduledEmailRow
from app.services.scheduled_email_store import ScheduledEmailStore


@pytest.fixture
def main_db(tmp_path, monkeypatch):
    """DB principale en mémoire + chemin legacy isolé + flag d'import reset."""
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
    legacy_path = tmp_path / "scheduled_emails.db"
    monkeypatch.setattr(store_module, "_legacy_db_path", lambda: str(legacy_path))
    monkeypatch.setattr(store_module, "_legacy_import_done", False)
    yield {"cm": _cm, "legacy": legacy_path}
    engine.dispose()


def _seed_legacy_db(path, *, with_attempts_column=True):
    """Crée un scheduled_emails.db au schéma historique avec 2 lignes."""
    conn = sqlite3.connect(str(path))
    attempts_col = ", attempts INTEGER NOT NULL DEFAULT 0" if with_attempts_column else ""
    conn.executescript(f"""
        CREATE TABLE scheduled_emails (
            id              TEXT PRIMARY KEY,
            account_id      INTEGER NOT NULL,
            payload         TEXT NOT NULL,
            send_at         TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'pending',
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL,
            sent_at         TEXT,
            sent_message_id TEXT,
            error           TEXT,
            idempotency_key TEXT{attempts_col}
        );
    """)
    base_cols = (
        "id, account_id, payload, send_at, status, created_at, updated_at, "
        "sent_at, sent_message_id, error, idempotency_key"
    )
    rows = [
        ("legacy-pending", 7, '{"to": ["a@b.c"], "subject": "S"}',
         "2026-06-20T10:00:00+00:00", "pending",
         "2026-06-12T08:00:00+00:00", "2026-06-12T08:00:00+00:00",
         None, None, None, "agentys-scheduled-legacy-pending@agentys.local"),
        ("legacy-sent", 7, '{"to": ["x@y.z"]}',
         "2026-06-01T10:00:00+00:00", "sent",
         "2026-05-30T08:00:00+00:00", "2026-06-01T10:00:05+00:00",
         "2026-06-01T10:00:05+00:00", "msg-99", None, None),
    ]
    if with_attempts_column:
        conn.executemany(
            f"INSERT INTO scheduled_emails ({base_cols}, attempts) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,1)",
            rows,
        )
    else:
        conn.executemany(
            f"INSERT INTO scheduled_emails ({base_cols}) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
    conn.commit()
    conn.close()


class TestLegacyImport:
    def test_imports_rows_and_parks_file(self, main_db):
        _seed_legacy_db(main_db["legacy"])
        store = ScheduledEmailStore()  # store par défaut → DB principale

        row = store.get_by_id("legacy-pending")
        assert row is not None
        assert row["status"] == "pending"
        assert row["payload"] == {"to": ["a@b.c"], "subject": "S"}
        assert row["attempts"] == 1
        sent = store.get_by_id("legacy-sent")
        assert sent["sent_message_id"] == "msg-99"
        # idempotency_key absent dans le legacy → dérivée de l'id (contrat)
        assert sent["idempotency_key"] == "agentys-scheduled-legacy-sent@agentys.local"
        # Fichier parqué
        assert not main_db["legacy"].exists()
        assert main_db["legacy"].with_suffix(".db.imported").exists()

    def test_pre_attempts_schema_tolerated(self, main_db):
        """Un legacy antérieur à la colonne `attempts` s'importe (défaut 0)."""
        _seed_legacy_db(main_db["legacy"], with_attempts_column=False)
        store = ScheduledEmailStore()
        assert store.get_by_id("legacy-pending")["attempts"] == 0

    def test_import_idempotent_db_wins_over_replay(self, main_db):
        _seed_legacy_db(main_db["legacy"])
        store = ScheduledEmailStore()
        assert store.cancel("legacy-pending") is True  # mutation en DB

        # Rejeu : un vieux backup du fichier réapparaît + « restart » process
        import os
        os.replace(
            str(main_db["legacy"]) + ".imported", str(main_db["legacy"])
        )
        store_module._legacy_import_done = False
        row = ScheduledEmailStore().get_by_id("legacy-pending")
        assert row["status"] == "cancelled"  # la DB gagne, pas de doublon
        with main_db["cm"]() as s:
            assert s.query(ScheduledEmailRow).count() == 2

    def test_unreadable_legacy_does_not_break_store(self, main_db):
        main_db["legacy"].write_text("pas une base sqlite", encoding="utf-8")
        store = ScheduledEmailStore()
        sid = store.insert(
            account_id=1, payload={"to": ["a@b.c"]},
            send_at=datetime.now(timezone.utc),
        )
        assert store.get_by_id(sid) is not None  # le store vit sa vie
        assert main_db["legacy"].exists()  # fichier laissé pour diagnostic


class TestDefaultStoreOnMainDb:
    def test_insert_lands_in_main_db(self, main_db):
        store = ScheduledEmailStore()
        sid = store.insert(
            account_id=3, payload={"subject": "hello"},
            send_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        with main_db["cm"]() as s:
            row = s.get(ScheduledEmailRow, sid)
            assert row is not None
            assert row.account_id == 3


class TestRecoverNowInjection:
    def test_strict_boundary_is_deterministic_with_injected_now(self, main_db):
        store = ScheduledEmailStore()
        sid = store.insert(
            account_id=1, payload={},
            send_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        assert store.claim_for_send(sid) is True
        # now == updated_at (à la granularité près) → strict `<` ne récupère pas
        claimed = store.get_by_id(sid)
        assert store.recover_stuck_sending(
            threshold_minutes=0, now=claimed["updated_at"]
        ) == 0
        # now futur → récupère, déterministe
        assert store.recover_stuck_sending(
            threshold_minutes=0,
            now=claimed["updated_at"] + timedelta(seconds=1),
        ) == 1
        assert store.get_by_id(sid)["status"] == "pending"
