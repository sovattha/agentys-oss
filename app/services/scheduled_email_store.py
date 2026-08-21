# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Store du schedule-send — table ``scheduled_emails`` de la DB principale.

Migration 043 (chantier « web tier stateless ») : la base annexe
``data/scheduled_emails.db`` cesse d'exister. L'API publique de la classe
est STRICTEMENT inchangée (insert/cancel/update_send_at/update_payload/
claim_for_send/revert_claim/recover_stuck_sending/mark_sent/mark_failed/
get_by_id/list_by_account/list_due/count_pending/delete_by_account) — les
consommateurs (scheduler, routes, quicksteps, purge compte, rétention) ne
changent pas. Les transitions atomiques (claim, cancel…) restent des
``UPDATE … WHERE status=?`` à rowcount, portables SQLite/Postgres.

Seam de test conservé : ``ScheduledEmailStore(db_path=...)`` monte un
engine SQLAlchemy PRIVÉ sur ce fichier (schéma créé via l'ORM) — la suite
de tests historique passe inchangée. Sans ``db_path``, le store utilise la
DB principale via ``get_db_session`` et importe une fois les lignes du
legacy ``scheduled_emails.db`` s'il existe (idempotent par PK, fichier
parqué en ``.imported``).

Fix racine du flip-flop de tests (granularité d'horloge Windows ~15 ms +
``<`` strict) : ``recover_stuck_sending`` accepte un ``now`` injectable —
plus aucun ``time.sleep`` nécessaire dans les tests.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models.scheduled_email import ScheduledEmailRow

logger = logging.getLogger(__name__)

# Status values — keep in sync with frontend ScheduledEmailDTO.status.
_PENDING = "pending"
_SENDING = "sending"
_SENT = "sent"
_FAILED = "failed"
_CANCELLED = "cancelled"

_legacy_import_done = False
_legacy_import_lock = threading.Lock()


def _idempotency_key_for(sched_id: str) -> str:
    return f"agentys-scheduled-{sched_id}@agentys.local"


def _to_iso(dt: datetime) -> str:
    """Serialise un datetime en ISO UTC. Naive -> on assume UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _from_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _legacy_db_path() -> str:
    from app.config import DATA_DIR
    return str(DATA_DIR / "scheduled_emails.db")


def _ensure_legacy_import() -> None:
    """Import one-shot du legacy ``scheduled_emails.db`` vers la DB principale.

    Idempotent par PK ; le fichier est parqué en ``.imported`` après commit
    (les fichiers WAL/SHM résiduels sont sans effet : plus aucune connexion).
    Un fichier illisible est loggé et laissé en place ; DB indisponible →
    retry au prochain accès. Même contrat que les migrations 039-042.
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
                rows = legacy.execute("SELECT * FROM scheduled_emails").fetchall()
            finally:
                legacy.close()
        except sqlite3.Error as e:
            logger.error(
                "scheduled_emails: legacy DB illisible (%s), import différé: %s",
                path, e,
            )
            _legacy_import_done = True
            return

        imported = 0
        try:
            from app.db.database import get_db_session
            with get_db_session() as session:
                for row in rows:
                    sched_id = str(row["id"])
                    if session.get(ScheduledEmailRow, sched_id) is not None:
                        continue
                    keys = row.keys()
                    session.add(ScheduledEmailRow(
                        id=sched_id,
                        account_id=int(row["account_id"]),
                        payload=row["payload"] or "{}",
                        send_at=row["send_at"] or "",
                        status=row["status"] or _PENDING,
                        created_at=row["created_at"] or "",
                        updated_at=row["updated_at"] or "",
                        sent_at=row["sent_at"],
                        sent_message_id=row["sent_message_id"],
                        error=row["error"],
                        idempotency_key=(
                            row["idempotency_key"] if "idempotency_key" in keys else None
                        ) or _idempotency_key_for(sched_id),
                        attempts=int(row["attempts"] or 0) if "attempts" in keys else 0,
                    ))
                    imported += 1
                session.commit()
        except Exception as e:
            logger.error("scheduled_emails: import legacy échoué: %s", e)
            return

        try:
            os.replace(path, path + ".imported")
        except OSError as e:
            logger.warning(
                "scheduled_emails: impossible de parquer la DB importée: %s", e
            )
        _legacy_import_done = True
        if imported:
            logger.info("scheduled_emails: %d lignes legacy importées", imported)


class ScheduledEmailStore:
    def __init__(self, db_path: Optional[str] = None):
        """``db_path`` (seam de test) : engine SQLAlchemy privé sur ce fichier.

        Sans ``db_path`` : DB principale (+ import legacy one-shot)."""
        self._private_engine = None
        if db_path is not None:
            self._private_engine = create_engine(
                f"sqlite:///{db_path}",
                poolclass=StaticPool,
                connect_args={"check_same_thread": False},
            )
            ScheduledEmailRow.metadata.create_all(
                bind=self._private_engine,
                tables=[ScheduledEmailRow.__table__],
            )
            self._private_sessionmaker = sessionmaker(
                bind=self._private_engine, autoflush=False
            )

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

    # ── Mutations ────────────────────────────────────────────────────────

    def insert(self, *, account_id: int, payload: dict, send_at: datetime) -> str:
        sched_id = uuid.uuid4().hex
        now_iso = _to_iso(datetime.now(timezone.utc))
        with self._session() as session:
            session.add(ScheduledEmailRow(
                id=sched_id,
                account_id=int(account_id),
                payload=json.dumps(payload, ensure_ascii=False),
                send_at=_to_iso(send_at),
                status=_PENDING,
                created_at=now_iso,
                updated_at=now_iso,
                idempotency_key=_idempotency_key_for(sched_id),
                attempts=0,
            ))
            session.commit()
        logger.info(
            "ScheduledEmailStore: inserted %s for account=%s send_at=%s",
            sched_id[:8], account_id, _to_iso(send_at),
        )
        return sched_id

    def cancel(self, sched_id: str, *, account_id: Optional[int] = None) -> bool:
        """Atomic cancel — returns True iff a pending row was transitioned."""
        stmt = (
            update(ScheduledEmailRow)
            .where(ScheduledEmailRow.id == sched_id, ScheduledEmailRow.status == _PENDING)
            .values(status=_CANCELLED, updated_at=_to_iso(datetime.now(timezone.utc)))
        )
        if account_id is not None:
            stmt = stmt.where(ScheduledEmailRow.account_id == int(account_id))
        with self._session() as session:
            res = session.execute(stmt)
            session.commit()
            return res.rowcount > 0

    def update_send_at(
        self,
        sched_id: str,
        *,
        new_send_at: datetime,
        account_id: Optional[int] = None,
    ) -> bool:
        stmt = (
            update(ScheduledEmailRow)
            .where(ScheduledEmailRow.id == sched_id, ScheduledEmailRow.status == _PENDING)
            .values(
                send_at=_to_iso(new_send_at),
                updated_at=_to_iso(datetime.now(timezone.utc)),
            )
        )
        if account_id is not None:
            stmt = stmt.where(ScheduledEmailRow.account_id == int(account_id))
        with self._session() as session:
            res = session.execute(stmt)
            session.commit()
            return res.rowcount > 0

    def update_payload(
        self,
        sched_id: str,
        *,
        new_payload: dict,
        account_id: Optional[int] = None,
    ) -> bool:
        stmt = (
            update(ScheduledEmailRow)
            .where(ScheduledEmailRow.id == sched_id, ScheduledEmailRow.status == _PENDING)
            .values(
                payload=json.dumps(new_payload, ensure_ascii=False),
                updated_at=_to_iso(datetime.now(timezone.utc)),
            )
        )
        if account_id is not None:
            stmt = stmt.where(ScheduledEmailRow.account_id == int(account_id))
        with self._session() as session:
            res = session.execute(stmt)
            session.commit()
            return res.rowcount > 0

    def claim_for_send(self, sched_id: str) -> bool:
        """Atomically transition pending → sending.

        Prevents double-delivery when two processes (or two ticks) see the
        same row in `list_due()`. Only the first claimant gets True; the
        scheduler must abort if False.
        """
        with self._session() as session:
            res = session.execute(
                update(ScheduledEmailRow)
                .where(
                    ScheduledEmailRow.id == sched_id,
                    ScheduledEmailRow.status == _PENDING,
                )
                .values(
                    status=_SENDING,
                    updated_at=_to_iso(datetime.now(timezone.utc)),
                    attempts=ScheduledEmailRow.attempts + 1,
                )
            )
            session.commit()
            return res.rowcount > 0

    def revert_claim(self, sched_id: str) -> None:
        """Roll a `sending` row back to pending if the dispatch failed
        before we got a definitive sent/failed verdict (e.g. provider
        couldn't be loaded). The next tick will retry."""
        with self._session() as session:
            session.execute(
                update(ScheduledEmailRow)
                .where(
                    ScheduledEmailRow.id == sched_id,
                    ScheduledEmailRow.status == _SENDING,
                )
                .values(status=_PENDING, updated_at=_to_iso(datetime.now(timezone.utc)))
            )
            session.commit()

    def recover_stuck_sending(
        self,
        *,
        threshold_minutes: int = 10,
        now: Optional[datetime] = None,
    ) -> int:
        """FIX EMAIL-003 (audit P1): rows left in 'sending' across a process
        restart are invisible to list_due() (which filters status='pending')
        and would never be retried — the scheduled message becomes silently
        lost. Reset rows older than `threshold_minutes` back to 'pending' so
        the next tick picks them up. Called once at scheduler startup.

        ``now`` est injectable pour les tests : la comparaison historique
        ``updated_at < now - threshold`` est STRICTE, et la granularité
        d'horloge Windows (~15 ms) rendait ``threshold_minutes=0`` flaky
        (deux now() consécutifs peuvent être égaux). Les tests passent un
        ``now`` futur déterministe au lieu d'un time.sleep.

        Returns the number of rows recovered.
        """
        now = now or datetime.now(timezone.utc)
        threshold_iso = _to_iso(now - timedelta(minutes=threshold_minutes))
        with self._session() as session:
            stuck = list(session.execute(
                select(ScheduledEmailRow.id).where(
                    ScheduledEmailRow.status == _SENDING,
                    ScheduledEmailRow.updated_at < threshold_iso,
                )
            ).scalars())
            # A row stuck in 'sending' may have been DELIVERED before the crash
            # (mark_sent runs only AFTER the provider accepts the message), so
            # requeueing it risks a DUPLICATE send. We still requeue — a silently
            # lost scheduled email is worse than a rare logged duplicate, and the
            # proper fix is reconciliation against the provider Sent folder — but we
            # SELECT + WARN first so the event is visible to sentinel_stuck_schedule
            # instead of silent (chaos audit 2026-06-02, V6/D4).
            if stuck:
                logger.warning(
                    "recover_stuck_sending requeueing %d scheduled email(s) stuck in "
                    "'sending' — possible DUPLICATE send if already delivered before "
                    "the crash; reconcile against the provider Sent folder. ids=%s",
                    len(stuck), stuck,
                )
            res = session.execute(
                update(ScheduledEmailRow)
                .where(
                    ScheduledEmailRow.status == _SENDING,
                    ScheduledEmailRow.updated_at < threshold_iso,
                )
                .values(
                    status=_PENDING,
                    updated_at=_to_iso(datetime.now(timezone.utc)),
                )
            )
            session.commit()
            return res.rowcount

    def mark_sent(self, sched_id: str, *, message_id: str) -> None:
        now_iso = _to_iso(datetime.now(timezone.utc))
        with self._session() as session:
            session.execute(
                update(ScheduledEmailRow)
                .where(ScheduledEmailRow.id == sched_id)
                .values(
                    status=_SENT,
                    sent_at=now_iso,
                    sent_message_id=message_id,
                    updated_at=now_iso,
                )
            )
            session.commit()

    def mark_failed(self, sched_id: str, *, error: str) -> None:
        now_iso = _to_iso(datetime.now(timezone.utc))
        with self._session() as session:
            session.execute(
                update(ScheduledEmailRow)
                .where(ScheduledEmailRow.id == sched_id)
                .values(status=_FAILED, error=error[:500], updated_at=now_iso)
            )
            session.commit()

    # ── Lectures ─────────────────────────────────────────────────────────

    def get_by_id(
        self,
        sched_id: str,
        *,
        account_id: Optional[int] = None,
    ) -> Optional[dict]:
        with self._session() as session:
            row = session.get(ScheduledEmailRow, sched_id)
            if row is not None and account_id is not None and row.account_id != int(account_id):
                row = None
            return _row_to_dict(row)

    def list_by_account(
        self,
        *,
        account_id: int,
        statuses: Iterable[str] = (_PENDING,),
        limit: int = 200,
    ) -> list[dict]:
        statuses = tuple(statuses) or (_PENDING,)
        with self._session() as session:
            rows = session.execute(
                select(ScheduledEmailRow)
                .where(
                    ScheduledEmailRow.account_id == int(account_id),
                    ScheduledEmailRow.status.in_(statuses),
                )
                .order_by(ScheduledEmailRow.send_at.asc())
                .limit(int(limit))
            ).scalars()
            return [_row_to_dict(r) for r in rows]

    def list_due(self, *, now: Optional[datetime] = None, limit: int = 50) -> list[dict]:
        now = now or datetime.now(timezone.utc)
        with self._session() as session:
            rows = session.execute(
                select(ScheduledEmailRow)
                .where(
                    ScheduledEmailRow.status == _PENDING,
                    ScheduledEmailRow.send_at <= _to_iso(now),
                )
                .order_by(ScheduledEmailRow.send_at.asc())
                .limit(int(limit))
            ).scalars()
            return [_row_to_dict(r) for r in rows]

    def count_pending(self, *, account_id: int) -> int:
        with self._session() as session:
            rows = session.execute(
                select(ScheduledEmailRow.id).where(
                    ScheduledEmailRow.account_id == int(account_id),
                    ScheduledEmailRow.status == _PENDING,
                )
            ).scalars()
            return len(list(rows))

    def delete_by_account(self, account_id: int) -> int:
        """Delete every scheduled-send row for one account, regardless of status."""
        with self._session() as session:
            rows = list(session.execute(
                select(ScheduledEmailRow).where(
                    ScheduledEmailRow.account_id == int(account_id)
                )
            ).scalars())
            for row in rows:
                session.delete(row)
            if rows:
                session.commit()
            return len(rows)


# ── helpers ────────────────────────────────────────────────────────────────


def _row_to_dict(row: Optional[ScheduledEmailRow]) -> Optional[dict]:
    if row is None:
        return None
    try:
        payload = json.loads(row.payload)
    except (TypeError, ValueError):
        payload = {}
    return {
        "id": row.id,
        "account_id": row.account_id,
        "payload": payload,
        "send_at": _from_iso(row.send_at),
        "status": row.status,
        "created_at": _from_iso(row.created_at),
        "updated_at": _from_iso(row.updated_at),
        "sent_at": _from_iso(row.sent_at),
        "sent_message_id": row.sent_message_id,
        "error": row.error,
        "idempotency_key": row.idempotency_key or _idempotency_key_for(row.id),
        "attempts": int(row.attempts or 0),
    }


# ── Singleton ──────────────────────────────────────────────────────────────


_default_store: Optional[ScheduledEmailStore] = None
_default_store_lock = threading.Lock()


def get_default_store() -> ScheduledEmailStore:
    """Renvoie le store par defaut (DB principale)."""
    global _default_store
    with _default_store_lock:
        if _default_store is None:
            _default_store = ScheduledEmailStore()
        return _default_store


def reset_default_store(store: Optional[ScheduledEmailStore] = None) -> None:
    """Helper test : remplace ou efface le store par defaut."""
    global _default_store
    with _default_store_lock:
        _default_store = store
