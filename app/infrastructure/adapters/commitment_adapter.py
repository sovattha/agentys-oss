# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Adapter de suivi des engagements — table ``commitments`` de la DB principale.

Migration 045 (chantier « web tier stateless », gabarit 043) : la base
annexe ``data/commitments.db`` cesse d'exister. L'API publique de la classe
est STRICTEMENT inchangée (add_commitment/get_pending/get_by_email/
get_overdue/mark_completed/mark_cancelled/get_by_id/get_all +
``delete_by_account`` hors port, découvert par duck-typing dans
``privacy_retention``) — les consommateurs (daemon, purge compte) ne
changent pas. ``add_commitment`` reste un upsert par PK (``session.merge``
≡ ``INSERT OR REPLACE`` historique) et les timestamps restent en ISO
**local naïf** (``datetime.now().isoformat()``) — contrat caractérisé.

Seams de test conservés (DÉVIATION assumée vs gabarit 043 : ici no-arg ≠ DB
principale) :
- ``CommitmentAdapter()`` (sans argument) → engine SQLAlchemy PRIVÉ en
  mémoire, isolé par instance ;
- ``CommitmentAdapter(db_path=...)`` → engine privé sur ce fichier ;
- ``_get_connection()`` → la connexion sqlite3 brute partagée par l'engine
  privé (la suite historique exécute du SQL dessus) ;
- le mode DB principale est demandé EXPLICITEMENT par le container via
  ``use_main_db=True`` (+ import one-shot du legacy ``commitments.db``,
  idempotent par PK, fichier parqué en ``.imported``).

Le verrou S-05 (RLock sur connexion sqlite3 partagée) disparaît : en mode
DB principale chaque appel obtient sa session via ``get_db_session`` ; en
mode privé l'engine ``StaticPool`` REND la même connexion à toutes les
sessions mais NE sérialise PAS les accès concurrents (pas de verrou) —
suffisant pour les suites de tests, séquentielles ; un usage multi-thread
du mode privé n'est pas supporté (le mode prod = DB principale, sessions
indépendantes).

Fix racine du cluster « no such column: account_id » : l'ancien
``_ensure_table`` exécutait ``CREATE INDEX … (account_id)`` sur la table
legacy pré-``account_id`` AVANT le self-heal ALTER — toute construction de
l'adapter échouait. Le schéma vit désormais dans alembic (045) et l'import
legacy tolère la colonne absente (``row.keys()``).
"""

import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from sqlalchemy import create_engine, delete, select, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models.commitment import CommitmentRow
from app.domain.entities.commitment import Commitment, CommitmentStatus
from app.domain.ports.commitment_port import CommitmentTrackerPort

logger = logging.getLogger(__name__)

_legacy_import_done = False
_legacy_import_lock = threading.Lock()


def _legacy_db_path() -> str:
    from app.config import DATA_DIR
    return str(DATA_DIR / "commitments.db")


def _ensure_legacy_import() -> None:
    """Import one-shot du legacy ``commitments.db`` vers la DB principale.

    Idempotent par PK ; le fichier est parqué en ``.imported`` après commit.
    Le schéma legacy pré-``account_id`` (cause du cluster de 38 erreurs
    locales) est toléré via ``row.keys()``. Un fichier illisible est loggé
    et laissé en place ; DB indisponible → retry au prochain accès. Même
    contrat que les migrations 039-043.
    """
    global _legacy_import_done
    if _legacy_import_done:
        return
    with _legacy_import_lock:
        if _legacy_import_done:
            return
        path = _legacy_db_path()
        if not os.path.exists(path):
            _legacy_import_done = True
            return
        try:
            legacy = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
            legacy.row_factory = sqlite3.Row
            try:
                rows = legacy.execute("SELECT * FROM commitments").fetchall()
            finally:
                legacy.close()
        except sqlite3.Error as e:
            logger.error(
                "commitments: legacy DB illisible (%s), import abandonné: %s",
                path, e,
            )
            _legacy_import_done = True
            return

        imported = 0
        try:
            from app.db.database import get_db_session
            with get_db_session() as session:
                for row in rows:
                    commitment_id = str(row["id"])
                    if session.get(CommitmentRow, commitment_id) is not None:
                        continue
                    keys = row.keys()
                    session.add(CommitmentRow(
                        id=commitment_id,
                        email_id=row["email_id"],
                        description=row["description"],
                        detected_at=row["detected_at"],
                        status=row["status"] or "pending",
                        deadline=row["deadline"],
                        completed_at=row["completed_at"],
                        account_id=(
                            row["account_id"] if "account_id" in keys else None
                        ),
                    ))
                    imported += 1
                session.commit()
        except Exception as e:
            logger.error("commitments: import legacy échoué: %s", e)
            return

        try:
            os.replace(path, path + ".imported")
        except OSError as e:
            logger.warning(
                "commitments: impossible de parquer la DB importée: %s", e
            )
        _legacy_import_done = True
        if imported:
            logger.info("commitments: %d lignes legacy importées", imported)


class CommitmentAdapter(CommitmentTrackerPort):
    """Adapter CommitmentTrackerPort sur la DB principale (ou engine privé)."""

    def __init__(self, db_path: Path = None, *, use_main_db: bool = False):
        """
        Initialise l'adapter.

        Args:
            db_path: Seam de test — engine SQLAlchemy privé sur ce fichier.
                Si None (et pas ``use_main_db``), engine privé en mémoire,
                isolé par instance (contrat historique ``:memory:``).
            use_main_db: Mode production (container) — DB principale via
                ``get_db_session`` + import one-shot du legacy.
        """
        self._private_engine = None
        if use_main_db:
            if db_path is not None:
                raise ValueError(
                    "use_main_db=True est exclusif de db_path (seam de test)"
                )
            return
        # Mode privé : UNE connexion sqlite3 partagée (comme le legacy) que
        # l'engine StaticPool réutilise pour toutes les sessions — elle reste
        # exposée telle quelle par _get_connection() (seam historique).
        self._raw_connection = sqlite3.connect(
            str(db_path) if db_path else ":memory:",
            check_same_thread=False,
        )
        self._raw_connection.row_factory = sqlite3.Row
        self._private_engine = create_engine(
            "sqlite://",
            creator=lambda: self._raw_connection,
            poolclass=StaticPool,
        )
        CommitmentRow.metadata.create_all(
            bind=self._private_engine,
            tables=[CommitmentRow.__table__],
        )
        self._private_sessionmaker = sessionmaker(
            bind=self._private_engine, autoflush=False
        )

    def _get_connection(self) -> sqlite3.Connection:
        """Seam de test historique : la connexion sqlite3 brute de l'engine privé."""
        if self._private_engine is None:
            raise RuntimeError(
                "_get_connection() est un seam de test du mode privé ; "
                "en mode DB principale, passer par get_db_session"
            )
        return self._raw_connection

    @contextmanager
    def _session(self):
        if self._private_engine is not None:
            s = self._private_sessionmaker()
            try:
                yield s
            finally:
                s.close()
        else:
            _ensure_legacy_import()
            from app.db.database import get_db_session
            with get_db_session() as s:
                yield s

    def _row_to_commitment(self, row: CommitmentRow) -> Commitment:
        """Convertit une ligne ORM en entite Commitment."""
        return Commitment(
            id=row.id,
            email_id=row.email_id,
            description=row.description,
            detected_at=row.detected_at,
            status=CommitmentStatus(row.status),
            deadline=row.deadline,
            completed_at=row.completed_at,
            account_id=row.account_id,
        )

    # =========================================================================
    # Gestion des engagements
    # =========================================================================

    def add_commitment(self, commitment: Commitment) -> None:
        """Ajoute un engagement pour suivi (upsert par PK, comme l'historique
        INSERT OR REPLACE)."""
        with self._session() as session:
            session.merge(CommitmentRow(
                id=commitment.id,
                email_id=commitment.email_id,
                description=commitment.description,
                detected_at=commitment.detected_at,
                status=commitment.status.value,
                deadline=commitment.deadline,
                completed_at=commitment.completed_at,
                account_id=commitment.account_id,
            ))
            session.commit()

    def get_pending(self) -> List[Commitment]:
        """Recupere les engagements en attente."""
        return self._list_by_status(CommitmentStatus.PENDING)

    def get_by_email(self, email_id: str) -> List[Commitment]:
        """Recupere les engagements associes a un email."""
        with self._session() as session:
            rows = session.execute(
                select(CommitmentRow).where(CommitmentRow.email_id == email_id)
            ).scalars()
            return [self._row_to_commitment(row) for row in rows]

    def get_overdue(self) -> List[Commitment]:
        """Recupere les engagements en retard."""
        return self._list_by_status(CommitmentStatus.OVERDUE)

    # =========================================================================
    # Actions
    # =========================================================================

    def mark_completed(self, commitment_id: str) -> bool:
        """Marque un engagement comme complete."""
        with self._session() as session:
            res = session.execute(
                update(CommitmentRow)
                .where(CommitmentRow.id == commitment_id)
                .values(
                    status=CommitmentStatus.COMPLETED.value,
                    completed_at=datetime.now().isoformat(),
                )
            )
            session.commit()
            return res.rowcount > 0

    def mark_cancelled(self, commitment_id: str) -> bool:
        """Marque un engagement comme annule."""
        with self._session() as session:
            res = session.execute(
                update(CommitmentRow)
                .where(CommitmentRow.id == commitment_id)
                .values(status=CommitmentStatus.CANCELLED.value)
            )
            session.commit()
            return res.rowcount > 0

    # =========================================================================
    # Requetes
    # =========================================================================

    def get_by_id(self, commitment_id: str) -> Optional[Commitment]:
        """Recupere un engagement par son ID."""
        with self._session() as session:
            row = session.get(CommitmentRow, commitment_id)
            return self._row_to_commitment(row) if row else None

    def get_all(self) -> List[Commitment]:
        """Recupere tous les engagements."""
        with self._session() as session:
            rows = session.execute(select(CommitmentRow)).scalars()
            return [self._row_to_commitment(row) for row in rows]

    def delete_by_account(self, account_id: int) -> int:
        """Supprime les engagements associés à un compte."""
        with self._session() as session:
            res = session.execute(
                delete(CommitmentRow).where(
                    CommitmentRow.account_id == int(account_id)
                )
            )
            session.commit()
            return res.rowcount

    # =========================================================================
    # Internes
    # =========================================================================

    def _list_by_status(self, status: CommitmentStatus) -> List[Commitment]:
        with self._session() as session:
            rows = session.execute(
                select(CommitmentRow).where(CommitmentRow.status == status.value)
            ).scalars()
            return [self._row_to_commitment(row) for row in rows]
