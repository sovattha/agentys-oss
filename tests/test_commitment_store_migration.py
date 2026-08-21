# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Migration 045 : ``data/commitments.db`` (SQLite annexe) → DB principale.

La suite historique (tests/infrastructure/adapters/test_commitment_adapter.py
— 66 tests) sert de caractérisation et passe inchangée sur les nouveaux
internals SQLAlchemy (seams ``db_path``/no-arg → engine privé et
``_get_connection()`` préservés). Ce fichier couvre ce qui est PROPRE à la
migration :
- import one-shot du fichier legacy (lignes par PK, schéma pré-``account_id``
  toléré — le bug prod « no such column: account_id » —, parking
  ``.imported``, idempotence, DB illisible sans crash) ;
- le mode container (``use_main_db=True``) écrit dans la DB PRINCIPALE ;
- le seam historique no-arg reste un ``:memory:`` privé (déviation assumée
  vs gabarit 043) : il ne touche NI la DB principale NI le fichier legacy.

NB : la classe est chargée via ``spec_from_file_location`` comme dans la
suite de caractérisation, pour éviter les side-effects de
``app.infrastructure.__init__`` ; les monkeypatch de module visent CETTE
instance de module.
"""

import importlib.util
import sqlite3
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base
from app.db.models.commitment import CommitmentRow
from app.domain.entities.commitment import Commitment, CommitmentStatus


def _load_adapter_module():
    """Charge commitment_adapter.py sans passer par app.infrastructure.__init__."""
    spec = importlib.util.spec_from_file_location(
        "commitment_adapter_migration",
        "app/infrastructure/adapters/commitment_adapter.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


adapter_module = _load_adapter_module()
CommitmentAdapter = adapter_module.CommitmentAdapter


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
    legacy_path = tmp_path / "commitments.db"
    monkeypatch.setattr(adapter_module, "_legacy_db_path", lambda: str(legacy_path))
    monkeypatch.setattr(adapter_module, "_legacy_import_done", False)
    yield {"cm": _cm, "legacy": legacy_path}
    engine.dispose()


def _seed_legacy_db(path, *, with_account_id_column=True):
    """Crée un commitments.db au schéma historique avec 2 lignes.

    ``with_account_id_column=False`` reproduit le fichier prod réel
    (mtime fév. 2026, schéma pré-``account_id``) qui faisait échouer toute
    construction de l'ancien adapter (CREATE INDEX sur colonne absente).
    """
    conn = sqlite3.connect(str(path))
    account_col = ",\n            account_id INTEGER" if with_account_id_column else ""
    conn.executescript(f"""
        CREATE TABLE commitments (
            id TEXT PRIMARY KEY,
            email_id TEXT NOT NULL,
            description TEXT NOT NULL,
            detected_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            deadline TEXT,
            completed_at TEXT{account_col}
        );
        CREATE INDEX idx_commitments_email_id ON commitments(email_id);
        CREATE INDEX idx_commitments_status ON commitments(status);
    """)
    base_cols = (
        "id, email_id, description, detected_at, status, deadline, completed_at"
    )
    rows = [
        ("legacy-pending", "email-1", "Envoyer le rapport lundi",
         "2026-02-25T10:30:00", "pending", "2026-03-02", None),
        ("legacy-completed", "email-2", "Relancer le client",
         "2026-02-20T09:00:00", "completed", None, "2026-02-24T18:00:00"),
    ]
    if with_account_id_column:
        conn.executemany(
            f"INSERT INTO commitments ({base_cols}, account_id) "
            "VALUES (?,?,?,?,?,?,?,7)",
            rows,
        )
    else:
        conn.executemany(
            f"INSERT INTO commitments ({base_cols}) VALUES (?,?,?,?,?,?,?)",
            rows,
        )
    conn.commit()
    conn.close()


class TestLegacyImport:
    def test_imports_rows_and_parks_file(self, main_db):
        _seed_legacy_db(main_db["legacy"])
        adapter = CommitmentAdapter(use_main_db=True)  # mode container → DB principale

        row = adapter.get_by_id("legacy-pending")
        assert row is not None
        assert row.email_id == "email-1"
        assert row.description == "Envoyer le rapport lundi"
        assert row.detected_at == "2026-02-25T10:30:00"  # ISO local naïf, tel quel
        assert row.status == CommitmentStatus.PENDING
        assert row.deadline == "2026-03-02"
        assert row.account_id == 7
        done = adapter.get_by_id("legacy-completed")
        assert done.status == CommitmentStatus.COMPLETED
        assert done.completed_at == "2026-02-24T18:00:00"
        # Fichier parqué
        assert not main_db["legacy"].exists()
        assert main_db["legacy"].with_suffix(".db.imported").exists()

    def test_pre_account_id_schema_tolerated(self, main_db):
        """Le fichier prod réel (pré-account_id) s'importe sans crash.

        C'est le fix racine du cluster « no such column: account_id » :
        l'ancien _ensure_table levait OperationalError à la CONSTRUCTION.
        """
        _seed_legacy_db(main_db["legacy"], with_account_id_column=False)
        adapter = CommitmentAdapter(use_main_db=True)  # ne doit pas lever
        row = adapter.get_by_id("legacy-pending")
        assert row is not None
        assert row.account_id is None
        assert not main_db["legacy"].exists()

    def test_import_idempotent_db_wins_over_replay(self, main_db):
        _seed_legacy_db(main_db["legacy"])
        adapter = CommitmentAdapter(use_main_db=True)
        assert adapter.mark_completed("legacy-pending") is True  # mutation en DB

        # Rejeu : un vieux backup du fichier réapparaît + « restart » process
        import os
        os.replace(
            str(main_db["legacy"]) + ".imported", str(main_db["legacy"])
        )
        adapter_module._legacy_import_done = False
        row = CommitmentAdapter(use_main_db=True).get_by_id("legacy-pending")
        assert row.status == CommitmentStatus.COMPLETED  # la DB gagne, pas de doublon
        with main_db["cm"]() as s:
            assert s.query(CommitmentRow).count() == 2

    def test_unreadable_legacy_does_not_break_store(self, main_db):
        main_db["legacy"].write_text("pas une base sqlite", encoding="utf-8")
        adapter = CommitmentAdapter(use_main_db=True)
        adapter.add_commitment(Commitment(
            id="fresh-1", email_id="email-9", description="Nouveau",
            detected_at="2026-06-12T09:00:00", status=CommitmentStatus.PENDING,
        ))
        assert adapter.get_by_id("fresh-1") is not None  # le store vit sa vie
        assert main_db["legacy"].exists()  # fichier laissé pour diagnostic


class TestMainDbMode:
    def test_add_commitment_lands_in_main_db(self, main_db):
        adapter = CommitmentAdapter(use_main_db=True)
        adapter.add_commitment(Commitment(
            id="main-1", email_id="email-3", description="Suivi client",
            detected_at="2026-06-12T10:00:00", status=CommitmentStatus.PENDING,
            account_id=3,
        ))
        with main_db["cm"]() as s:
            row = s.get(CommitmentRow, "main-1")
            assert row is not None
            assert row.account_id == 3

    def test_use_main_db_excludes_db_path(self, tmp_path):
        with pytest.raises(ValueError):
            CommitmentAdapter(db_path=tmp_path / "x.db", use_main_db=True)


class TestPrivateSeamPreserved:
    def test_no_arg_stays_private_memory(self, main_db):
        """Déviation assumée vs gabarit 043 : no-arg = :memory: privé.

        Le seam historique ne touche ni la DB principale ni le legacy."""
        _seed_legacy_db(main_db["legacy"])
        adapter = CommitmentAdapter()
        adapter.add_commitment(Commitment(
            id="iso-1", email_id="e1", description="Privé",
            detected_at="2026-06-12T11:00:00", status=CommitmentStatus.PENDING,
        ))
        assert adapter.get_by_id("iso-1") is not None
        # Legacy ni lu ni parqué, DB principale vierge
        assert main_db["legacy"].exists()
        assert adapter_module._legacy_import_done is False
        with main_db["cm"]() as s:
            assert s.query(CommitmentRow).count() == 0

    def test_get_connection_refused_in_main_db_mode(self, main_db):
        adapter = CommitmentAdapter(use_main_db=True)
        with pytest.raises(RuntimeError):
            adapter._get_connection()
