# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Migration 044 : ``data/batch_queue.db`` (SQLite annexe) → DB principale.

La suite historique (test_batch_queue / test_c5_batch_routing /
test_scheduler_heartbeat_wireups::TestBatchWorkerHeartbeat) sert de
caractérisation et passe inchangée sur les nouveaux internals SQLAlchemy
(seam ``db_path`` + ``_get_conn()`` SQL brut préservés). Ce fichier couvre
ce qui est PROPRE à la migration :
- import one-shot du fichier legacy (2 tables, lignes par PK, schéma
  pré-``account_id`` toléré, parking ``.imported``, idempotence où la DB
  gagne sur un rejeu, DB illisible sans crash) ;
- le store par défaut écrit dans la DB PRINCIPALE (plus de side-file) et
  son constructeur reste paresseux (contrat TestBatchWorkerHeartbeat).
"""

import sqlite3
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.batch_queue as bq_module
from app.batch_queue import BatchQueue
from app.db.models import Base
from app.db.models.batch_queue import ActiveBatchRow, BatchQueueItemRow


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
    legacy_path = tmp_path / "batch_queue.db"
    monkeypatch.setattr(bq_module, "_legacy_db_path", lambda: str(legacy_path))
    monkeypatch.setattr(bq_module, "_legacy_import_done", False)
    yield {"cm": _cm, "legacy": legacy_path}
    engine.dispose()


def _seed_legacy_db(path, *, with_account_id_column=True):
    """Crée un batch_queue.db au schéma historique (2 tables, 3+2 lignes)."""
    conn = sqlite3.connect(str(path))
    account_col = "account_id  TEXT DEFAULT ''," if with_account_id_column else ""
    conn.executescript(f"""
        CREATE TABLE batch_queue (
            id          TEXT PRIMARY KEY,
            email_id    TEXT NOT NULL,
            {account_col}
            tier        TEXT NOT NULL,
            model       TEXT NOT NULL,
            system_prompt TEXT NOT NULL,
            user_prompt TEXT NOT NULL,
            max_tokens  INTEGER NOT NULL DEFAULT 512,
            temperature REAL DEFAULT 0.5,
            metadata    TEXT,
            status      TEXT NOT NULL DEFAULT 'pending',
            batch_id    TEXT,
            result_draft TEXT,
            error       TEXT,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            created_at  TEXT NOT NULL,
            submitted_at TEXT,
            completed_at TEXT
        );

        CREATE TABLE active_batches (
            batch_id    TEXT PRIMARY KEY,
            request_count INTEGER NOT NULL,
            submitted_at TEXT NOT NULL,
            status      TEXT NOT NULL DEFAULT 'in_progress'
        );
    """)
    if with_account_id_column:
        conn.execute(
            """INSERT INTO batch_queue
               (id, email_id, account_id, tier, model, system_prompt, user_prompt,
                max_tokens, temperature, metadata, status, created_at)
               VALUES ('legacy-pending', 'email-1', '42', 'standard', 'haiku',
                       'sys', 'usr', 1024, 0.7,
                       '{"sender": "a@b.c", "subject": "S"}',
                       'pending', '2026-06-10T09:00:00')""",
        )
        conn.execute(
            """INSERT INTO batch_queue
               (id, email_id, account_id, tier, model, system_prompt, user_prompt,
                status, batch_id, result_draft, input_tokens, output_tokens,
                created_at, submitted_at, completed_at)
               VALUES ('legacy-done', 'email-2', '', 'complex', 'haiku',
                       'sys', 'usr', 'completed', 'msgbatch_1', 'Bonjour…',
                       120, 80, '2026-06-09T22:00:00', '2026-06-09T22:05:00',
                       '2026-06-09T23:00:00')""",
        )
        conn.execute(
            """INSERT INTO batch_queue
               (id, email_id, account_id, tier, model, system_prompt, user_prompt,
                status, batch_id, created_at, submitted_at)
               VALUES ('legacy-inflight', 'email-3', '42', 'standard', 'haiku',
                       'sys', 'usr', 'submitted', 'msgbatch_2',
                       '2026-06-11T01:00:00', '2026-06-11T01:10:00')""",
        )
    else:
        conn.execute(
            """INSERT INTO batch_queue
               (id, email_id, tier, model, system_prompt, user_prompt,
                status, created_at)
               VALUES ('legacy-pending', 'email-1', 'standard', 'haiku',
                       'sys', 'usr', 'pending', '2026-06-10T09:00:00')""",
        )
    conn.execute(
        """INSERT INTO active_batches (batch_id, request_count, submitted_at, status)
           VALUES ('msgbatch_1', 5, '2026-06-09T22:05:00', 'ended')""",
    )
    conn.execute(
        """INSERT INTO active_batches (batch_id, request_count, submitted_at, status)
           VALUES ('msgbatch_2', 1, '2026-06-11T01:10:00', 'in_progress')""",
    )
    conn.commit()
    conn.close()


class TestLegacyImport:
    def test_imports_rows_and_parks_file(self, main_db):
        _seed_legacy_db(main_db["legacy"])
        queue = BatchQueue()  # store par défaut → DB principale

        # Contrat dict(sqlite3.Row) : toutes les colonnes, types préservés,
        # metadata = JSON brut (string), account_id = TEXT sentinelle.
        item = queue.get_by_email_id("email-1", account_id="42")
        assert item is not None
        assert item["id"] == "legacy-pending"
        assert item["account_id"] == "42"
        assert item["max_tokens"] == 1024
        assert item["temperature"] == 0.7
        assert item["metadata"] == '{"sender": "a@b.c", "subject": "S"}'
        assert item["created_at"] == "2026-06-10T09:00:00"

        done = queue.get_items_for_batch("msgbatch_1")
        assert len(done) == 1
        assert done[0]["status"] == "completed"
        assert done[0]["result_draft"] == "Bonjour…"
        assert done[0]["input_tokens"] == 120
        assert done[0]["account_id"] == ""  # sentinelle legacy mono-compte

        # active_batches : seul le in_progress ressort de get_active_batches
        active = queue.get_active_batches()
        assert [b["batch_id"] for b in active] == ["msgbatch_2"]
        assert active[0]["request_count"] == 1

        # Fichier parqué
        assert not main_db["legacy"].exists()
        assert main_db["legacy"].with_suffix(".db.imported").exists()

    def test_pre_account_id_schema_tolerated(self, main_db):
        """Un legacy antérieur à l'ALTER ``account_id`` s'importe (défaut '')."""
        _seed_legacy_db(main_db["legacy"], with_account_id_column=False)
        queue = BatchQueue()
        item = queue.get_by_email_id("email-1")
        assert item is not None
        assert item["account_id"] == ""

    def test_import_idempotent_db_wins_over_replay(self, main_db):
        _seed_legacy_db(main_db["legacy"])
        queue = BatchQueue()
        queue.mark_failed("legacy-pending", "boom")  # mutation en DB
        queue.mark_batch_ended("msgbatch_2")

        # Rejeu : un vieux backup du fichier réapparaît + « restart » process
        import os
        os.replace(
            str(main_db["legacy"]) + ".imported", str(main_db["legacy"])
        )
        bq_module._legacy_import_done = False
        replayed = BatchQueue()
        assert replayed.get_by_email_id("email-1") is None  # failed, pas ré-importé
        assert replayed.get_active_batches() == []  # ended, pas ressuscité
        with main_db["cm"]() as s:
            assert s.query(BatchQueueItemRow).count() == 3
            assert s.query(ActiveBatchRow).count() == 2
            assert s.get(BatchQueueItemRow, "legacy-pending").status == "failed"

    def test_unreadable_legacy_does_not_break_store(self, main_db):
        main_db["legacy"].write_text("pas une base sqlite", encoding="utf-8")
        queue = BatchQueue()
        item_id = queue.enqueue("e1", "standard", "haiku", "sys", "usr")
        assert queue.get_by_email_id("e1")["id"] == item_id  # le store vit sa vie
        assert main_db["legacy"].exists()  # fichier laissé pour diagnostic

    def test_missing_active_batches_table_tolerated(self, main_db):
        """Très vieux fichier sans ``active_batches`` : items importés quand même."""
        conn = sqlite3.connect(str(main_db["legacy"]))
        conn.executescript("""
            CREATE TABLE batch_queue (
                id TEXT PRIMARY KEY, email_id TEXT NOT NULL, tier TEXT NOT NULL,
                model TEXT NOT NULL, system_prompt TEXT NOT NULL,
                user_prompt TEXT NOT NULL, max_tokens INTEGER NOT NULL DEFAULT 512,
                temperature REAL DEFAULT 0.5, metadata TEXT,
                status TEXT NOT NULL DEFAULT 'pending', batch_id TEXT,
                result_draft TEXT, error TEXT, input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0, created_at TEXT NOT NULL,
                submitted_at TEXT, completed_at TEXT
            );
            INSERT INTO batch_queue (id, email_id, tier, model, system_prompt,
                user_prompt, status, created_at)
            VALUES ('old-1', 'email-old', 't', 'm', 's', 'u', 'pending',
                    '2026-06-01T08:00:00');
        """)
        conn.commit()
        conn.close()

        queue = BatchQueue()
        assert queue.get_by_email_id("email-old") is not None
        assert not main_db["legacy"].exists()


class TestDefaultStoreOnMainDb:
    def test_enqueue_lands_in_main_db(self, main_db):
        queue = BatchQueue()
        item_id = queue.enqueue(
            "e1", "standard", "haiku", "sys", "usr",
            metadata={"sender": "x@y.z"}, account_id="7",
        )
        with main_db["cm"]() as s:
            row = s.get(BatchQueueItemRow, item_id)
            assert row is not None
            assert row.account_id == "7"
            assert row.metadata_json == '{"sender": "x@y.z"}'

    def test_constructor_is_lazy_without_db_path(self, main_db, monkeypatch):
        """Contrat TestBatchWorkerHeartbeat : ``BatchQueue()`` ne touche ni la
        DB principale ni l'import legacy avant le premier usage."""
        def _boom():
            raise AssertionError("import legacy déclenché par __init__")

        monkeypatch.setattr(bq_module, "_ensure_legacy_import", _boom)
        queue = BatchQueue()  # ne doit PAS lever
        monkeypatch.setattr(bq_module, "_ensure_legacy_import", lambda: None)
        assert queue.pending_count() == 0  # premier usage seulement

    def test_mark_submitted_single_commit_upserts_active_batch(self, main_db):
        """L'upsert historique INSERT OR REPLACE (→ merge) reste rejouable."""
        queue = BatchQueue()
        i1 = queue.enqueue("e1", "t", "m", "s", "u")
        i2 = queue.enqueue("e2", "t", "m", "s", "u")
        queue.mark_submitted([i1], "b1")
        queue.mark_submitted([i2], "b1")  # re-soumission même batch_id
        active = queue.get_active_batches()
        assert len(active) == 1  # remplacé, pas dupliqué
        assert active[0]["request_count"] == 1
        assert queue.pending_count() == 0
