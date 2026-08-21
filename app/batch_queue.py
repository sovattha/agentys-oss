"""
Batch Queue — DB-backed queue + background worker for off-hours batch processing.

During configured sleep/off-hours, daemon-generated drafts are queued and submitted
to the Anthropic Message Batches API at 50% discount. A background worker submits
micro-batches and polls for results.

Schedule logic:
  - Active hours (configurable, default 07:00-20:00 weekdays): real-time API
  - Off hours + weekends: batch API at 50% discount
  - Activity override: if user was active in last N minutes, use real-time

Migration 044 (chantier « web tier stateless ») : la base annexe
``data/batch_queue.db`` cesse d'exister — les tables ``batch_queue`` et
``active_batches`` vivent dans la DB principale. L'API publique de
``BatchQueue`` est STRICTEMENT inchangée (enqueue/get_pending/
get_oldest_pending_age_sec/mark_submitted/mark_completed/mark_failed/
get_active_batches/mark_batch_ended/get_items_for_batch/get_by_email_id/
get_stale_items/pending_count/cleanup_old/delete_by_account) — les
consommateurs (BatchWorker, smart_routing, privacy_retention, run_api) ne
changent pas. ``mark_submitted`` reste transactionnel (N updates + upsert
``active_batches`` dans UN SEUL commit) ; l'upsert historique
``INSERT OR REPLACE`` devient ``session.merge`` (portable Postgres).

Seam de test conservé : ``BatchQueue(db_path=...)`` monte un engine
SQLAlchemy PRIVÉ sur ce fichier (schéma créé via l'ORM) — la suite de
tests historique passe inchangée, y compris ses accès SQL BRUTS via
``_get_conn()`` (connexion sqlite3 sur le MÊME fichier, visibilité croisée
garantie par des sessions fraîches à chaque appel). Sans ``db_path``, le
store utilise la DB principale via ``get_db_session`` (paresseusement — le
constructeur ne touche RIEN) et importe une fois les lignes du legacy
``batch_queue.db`` s'il existe (idempotent par PK, fichier parqué en
``.imported``).

NB timestamps : ``datetime.now().isoformat()`` LOCAL-NAÏF, comme
l'historique (divergence volontaire vs la migration 043 qui est UTC) —
les comparaisons lexicographiques du store en dépendent.
"""

import json
import logging
import os
import signal
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import create_engine, delete, func, or_, select, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models.batch_queue import ActiveBatchRow, BatchQueueItemRow

logger = logging.getLogger(__name__)

# Thread-local storage for SQLite connections
_local = threading.local()

# Global last-activity timestamp (updated by API requests)
_last_user_activity: float = 0.0
_activity_lock = threading.Lock()


def touch_user_activity():
    """Record that the user is currently active (called from API routes)."""
    global _last_user_activity
    with _activity_lock:
        _last_user_activity = time.time()


def get_last_user_activity() -> float:
    """Get timestamp of last user activity."""
    with _activity_lock:
        return _last_user_activity


# ============================================================================
# SCHEDULE CHECKER
# ============================================================================

def is_batch_window(now: Optional[datetime] = None) -> bool:
    """
    Check if current time is within the batch processing window (off-hours).

    Returns True if we should use batch API instead of real-time.
    Considers: time window, weekend flag, and user activity override.

    Reads user-configurable schedule from settings.json (UI-editable),
    falling back to config.py defaults (env vars).
    """
    # Load user settings (UI-configurable), fallback to config.py
    try:
        from app.api.settings import load_settings
        settings = load_settings()
        batch_enabled = settings.get("batch_enabled", True)
        BATCH_ACTIVE_HOURS_START = settings.get("batch_active_hours_start", "07:00")
        BATCH_ACTIVE_HOURS_END = settings.get("batch_active_hours_end", "20:00")
        BATCH_WEEKEND_ALL_DAY = settings.get("batch_weekend_all_day", True)
        BATCH_ACTIVITY_TIMEOUT_MIN = settings.get("batch_activity_timeout_min", 15)
    except Exception:
        from app.config import (
            BATCH_API_ENABLED as batch_enabled,
            BATCH_ACTIVE_HOURS_START,
            BATCH_ACTIVE_HOURS_END,
            BATCH_WEEKEND_ALL_DAY,
            BATCH_ACTIVITY_TIMEOUT_MIN,
        )

    if not batch_enabled:
        return False

    if now is None:
        now = datetime.now()

    # Activity override: if user was active recently, use real-time
    last_active = get_last_user_activity()
    if last_active > 0:
        minutes_since_active = (time.time() - last_active) / 60
        if minutes_since_active < BATCH_ACTIVITY_TIMEOUT_MIN:
            return False  # User is active, use real-time

    # Weekend: batch all day (if enabled)
    is_weekend = now.weekday() >= 5  # Saturday=5, Sunday=6
    if is_weekend and BATCH_WEEKEND_ALL_DAY:
        return True

    # Parse active hours
    try:
        start_h, start_m = map(int, BATCH_ACTIVE_HOURS_START.split(":"))
        end_h, end_m = map(int, BATCH_ACTIVE_HOURS_END.split(":"))
    except (ValueError, AttributeError):
        logger.warning("Invalid BATCH_ACTIVE_HOURS format, defaulting to 07:00-20:00")
        start_h, start_m = 7, 0
        end_h, end_m = 20, 0

    current_minutes = now.hour * 60 + now.minute
    start_minutes = start_h * 60 + start_m
    end_minutes = end_h * 60 + end_m

    # Active hours check (handles overnight ranges like 22:00-06:00)
    if start_minutes <= end_minutes:
        # Normal range: e.g., 07:00-20:00
        is_active_hours = start_minutes <= current_minutes < end_minutes
    else:
        # Overnight range: e.g., 22:00-06:00 → active from 22:00 to 06:00
        is_active_hours = current_minutes >= start_minutes or current_minutes < end_minutes

    # Batch window = NOT active hours
    return not is_active_hours


# ============================================================================
# DB QUEUE (DB principale via SQLAlchemy — migration 044)
# ============================================================================

# Status values batch_queue ('expired' n'est jamais écrit, mais cleanup_old
# le filtre depuis toujours — conservé tel quel).
_PENDING = "pending"
_SUBMITTED = "submitted"
_COMPLETED = "completed"
_FAILED = "failed"
_EXPIRED = "expired"
# Status values active_batches.
_IN_PROGRESS = "in_progress"
_ENDED = "ended"

_legacy_import_done = False
_legacy_import_lock = threading.Lock()


def _legacy_db_path() -> str:
    from app.config import DATA_DIR
    return str(DATA_DIR / "batch_queue.db")


def _ensure_legacy_import() -> None:
    """Import one-shot du legacy ``batch_queue.db`` vers la DB principale.

    Idempotent par PK (``batch_queue.id`` et ``active_batches.batch_id``) ;
    le fichier est parqué en ``.imported`` après commit (les fichiers
    WAL/SHM résiduels sont sans effet : plus aucune connexion). Un fichier
    illisible est loggé et laissé en place ; DB indisponible → retry au
    prochain accès. Même contrat que les migrations 039-043.

    Tolère un fichier antérieur à l'ALTER in-code ``account_id`` (colonne
    absente → sentinelle ``''``) et un fichier sans table ``active_batches``.
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
                item_rows = legacy.execute("SELECT * FROM batch_queue").fetchall()
                try:
                    batch_rows = legacy.execute(
                        "SELECT * FROM active_batches"
                    ).fetchall()
                except sqlite3.Error:
                    batch_rows = []  # très vieux fichier sans la table
            finally:
                legacy.close()
        except sqlite3.Error as e:
            logger.error(
                "batch_queue: legacy DB illisible (%s), import différé: %s",
                path, e,
            )
            _legacy_import_done = True
            return

        imported = 0
        try:
            from app.db.database import get_db_session
            with get_db_session() as session:
                for row in item_rows:
                    item_id = str(row["id"])
                    if session.get(BatchQueueItemRow, item_id) is not None:
                        continue
                    keys = row.keys()
                    account_id = (
                        row["account_id"] if "account_id" in keys else ""
                    ) or ""
                    session.add(BatchQueueItemRow(
                        id=item_id,
                        email_id=row["email_id"] or "",
                        account_id=str(account_id),
                        tier=row["tier"] or "",
                        model=row["model"] or "",
                        system_prompt=row["system_prompt"] or "",
                        user_prompt=row["user_prompt"] or "",
                        max_tokens=int(row["max_tokens"] or 512),
                        temperature=(
                            float(row["temperature"])
                            if row["temperature"] is not None else None
                        ),
                        metadata_json=row["metadata"],
                        status=row["status"] or _PENDING,
                        batch_id=row["batch_id"],
                        result_draft=row["result_draft"],
                        error=row["error"],
                        input_tokens=int(row["input_tokens"] or 0),
                        output_tokens=int(row["output_tokens"] or 0),
                        created_at=row["created_at"] or "",
                        submitted_at=row["submitted_at"],
                        completed_at=row["completed_at"],
                    ))
                    imported += 1
                for row in batch_rows:
                    bid = str(row["batch_id"])
                    if session.get(ActiveBatchRow, bid) is not None:
                        continue
                    session.add(ActiveBatchRow(
                        batch_id=bid,
                        request_count=int(row["request_count"] or 0),
                        submitted_at=row["submitted_at"] or "",
                        status=row["status"] or _IN_PROGRESS,
                    ))
                    imported += 1
                session.commit()
        except Exception as e:
            logger.error("batch_queue: import legacy échoué: %s", e)
            return

        try:
            os.replace(path, path + ".imported")
        except OSError as e:
            logger.warning(
                "batch_queue: impossible de parquer la DB importée: %s", e
            )
        _legacy_import_done = True
        if imported:
            logger.info("batch_queue: %d lignes legacy importées", imported)


def _item_to_dict(row: Optional[BatchQueueItemRow]) -> Optional[dict]:
    """Reproduit EXACTEMENT ``dict(sqlite3.Row)`` du store historique :
    toutes les colonnes, mêmes clés (``metadata`` = JSON brut TEXT, jamais
    parsé — les consommateurs font ``json.loads(item["metadata"])``),
    mêmes types (timestamps TEXT, temperature float, tokens int)."""
    if row is None:
        return None
    return {
        "id": row.id,
        "email_id": row.email_id,
        "account_id": row.account_id,
        "tier": row.tier,
        "model": row.model,
        "system_prompt": row.system_prompt,
        "user_prompt": row.user_prompt,
        "max_tokens": row.max_tokens,
        "temperature": row.temperature,
        "metadata": row.metadata_json,
        "status": row.status,
        "batch_id": row.batch_id,
        "result_draft": row.result_draft,
        "error": row.error,
        "input_tokens": row.input_tokens,
        "output_tokens": row.output_tokens,
        "created_at": row.created_at,
        "submitted_at": row.submitted_at,
        "completed_at": row.completed_at,
    }


def _batch_to_dict(row: ActiveBatchRow) -> dict:
    return {
        "batch_id": row.batch_id,
        "request_count": row.request_count,
        "submitted_at": row.submitted_at,
        "status": row.status,
    }


class BatchQueue:
    """DB-backed queue for batch processing requests (API historique inchangée)."""

    def __init__(self, db_path: Optional[str] = None):
        """``db_path`` (seam de test) : engine SQLAlchemy privé sur ce fichier.

        Sans ``db_path`` : DB principale (+ import legacy one-shot), le tout
        PARESSEUSEMENT — le constructeur ne touche ni la DB ni le disque
        (``BatchWorker()`` est instancié dans des tests sans isolation
        DATA_DIR ; l'ancien ``_init_db()`` dans ``__init__`` créait un
        fichier au passage)."""
        self._db_path = db_path
        self._private_engine = None
        if db_path is not None:
            self._private_engine = create_engine(
                f"sqlite:///{db_path}",
                poolclass=StaticPool,
                connect_args={"check_same_thread": False},
            )
            BatchQueueItemRow.metadata.create_all(
                bind=self._private_engine,
                tables=[BatchQueueItemRow.__table__, ActiveBatchRow.__table__],
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

    def _get_conn(self) -> sqlite3.Connection:
        """Seam de test historique : connexion sqlite3 BRUTE sur le fichier
        du seam ``db_path`` — la suite de caractérisation backdate des
        timestamps et compte des lignes en SQL brut dessus. Visibilité
        croisée avec l'engine privé garantie : les sessions SQLAlchemy sont
        fraîches à chaque appel et committées.

        La connexion reste thread-locale MODULE-GLOBALE (``_local.batch_conn``,
        clé = thread, pas l'instance) — contrat historique, la fixture de
        test la ferme/cleare entre les tests.

        En mode défaut (DB principale), il n'y a plus de fichier annexe.
        """
        if self._db_path is None:
            raise RuntimeError(
                "BatchQueue._get_conn() n'existe qu'en mode db_path (seam de "
                "test) — le store par défaut vit dans la DB principale "
                "(migration 044)."
            )
        if not hasattr(_local, "batch_conn") or _local.batch_conn is None:
            _local.batch_conn = sqlite3.connect(self._db_path, timeout=10)
            _local.batch_conn.row_factory = sqlite3.Row
            _local.batch_conn.execute("PRAGMA journal_mode=WAL")
            _local.batch_conn.execute("PRAGMA busy_timeout=5000")
        return _local.batch_conn

    def enqueue(
        self,
        email_id: str,
        tier: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 512,
        temperature: float = 0.5,
        metadata: Optional[dict] = None,
        account_id: str = "",
    ) -> str:
        """
        Add a draft request to the batch queue.

        Returns:
            Queue item ID.
        """
        item_id = str(uuid.uuid4())
        with self._session() as session:
            session.add(BatchQueueItemRow(
                id=item_id,
                email_id=email_id,
                account_id=account_id,
                tier=tier,
                model=model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                metadata_json=json.dumps(metadata) if metadata else None,
                status=_PENDING,
                created_at=datetime.now().isoformat(),
            ))
            session.commit()
        logger.info(f"Batch queue: enqueued {email_id} ({tier}) -> {item_id[:8]}")
        return item_id

    def get_pending(self, limit: int = 50, account_id: str = "") -> list[dict]:
        """Get pending items ready for batch submission."""
        stmt = select(BatchQueueItemRow).where(BatchQueueItemRow.status == _PENDING)
        if account_id:
            stmt = stmt.where(or_(
                BatchQueueItemRow.account_id == account_id,
                BatchQueueItemRow.account_id == "",
            ))
        stmt = stmt.order_by(BatchQueueItemRow.created_at.asc()).limit(limit)
        with self._session() as session:
            rows = session.execute(stmt).scalars()
            return [_item_to_dict(r) for r in rows]

    def get_oldest_pending_age_sec(self) -> float:
        """Get age in seconds of the oldest pending item, or 0 if none."""
        with self._session() as session:
            created_at = session.execute(
                select(BatchQueueItemRow.created_at)
                .where(BatchQueueItemRow.status == _PENDING)
                .order_by(BatchQueueItemRow.created_at.asc())
                .limit(1)
            ).scalar()
        if not created_at:
            return 0.0
        try:
            created = datetime.fromisoformat(created_at)
            return (datetime.now() - created).total_seconds()
        except (ValueError, TypeError):
            return 0.0

    def mark_submitted(self, item_ids: list[str], batch_id: str):
        """Mark items as submitted with their batch ID.

        Atomicité historique préservée : les updates des items ET l'upsert
        ``active_batches`` (ex-``INSERT OR REPLACE`` → ``session.merge``)
        partent dans UN SEUL commit.
        """
        now = datetime.now().isoformat()
        with self._session() as session:
            session.execute(
                update(BatchQueueItemRow)
                .where(BatchQueueItemRow.id.in_(item_ids))
                .values(status=_SUBMITTED, batch_id=batch_id, submitted_at=now)
            )
            session.merge(ActiveBatchRow(
                batch_id=batch_id,
                request_count=len(item_ids),
                submitted_at=now,
                status=_IN_PROGRESS,
            ))
            session.commit()

    def mark_completed(
        self,
        item_id: str,
        draft: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ):
        """Mark an item as completed with its result."""
        with self._session() as session:
            session.execute(
                update(BatchQueueItemRow)
                .where(BatchQueueItemRow.id == item_id)
                .values(
                    status=_COMPLETED,
                    result_draft=draft,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    completed_at=datetime.now().isoformat(),
                )
            )
            session.commit()

    def mark_failed(self, item_id: str, error: str):
        """Mark an item as failed."""
        with self._session() as session:
            session.execute(
                update(BatchQueueItemRow)
                .where(BatchQueueItemRow.id == item_id)
                .values(
                    status=_FAILED,
                    error=error,
                    completed_at=datetime.now().isoformat(),
                )
            )
            session.commit()

    def get_active_batches(self) -> list[dict]:
        """Get all in-progress batches."""
        with self._session() as session:
            rows = session.execute(
                select(ActiveBatchRow).where(ActiveBatchRow.status == _IN_PROGRESS)
            ).scalars()
            return [_batch_to_dict(r) for r in rows]

    def mark_batch_ended(self, batch_id: str):
        """Mark a batch as ended."""
        with self._session() as session:
            session.execute(
                update(ActiveBatchRow)
                .where(ActiveBatchRow.batch_id == batch_id)
                .values(status=_ENDED)
            )
            session.commit()

    def get_items_for_batch(self, batch_id: str) -> list[dict]:
        """Get all queue items associated with a batch."""
        with self._session() as session:
            rows = session.execute(
                select(BatchQueueItemRow).where(
                    BatchQueueItemRow.batch_id == batch_id
                )
            ).scalars()
            return [_item_to_dict(r) for r in rows]

    def get_by_email_id(self, email_id: str, account_id: str = "") -> Optional[dict]:
        """Check if an email already has a pending/submitted queue item."""
        stmt = select(BatchQueueItemRow).where(
            BatchQueueItemRow.email_id == email_id,
            BatchQueueItemRow.status.in_((_PENDING, _SUBMITTED)),
        )
        if account_id:
            stmt = stmt.where(or_(
                BatchQueueItemRow.account_id == account_id,
                BatchQueueItemRow.account_id == "",
            ))
        with self._session() as session:
            row = session.execute(stmt.limit(1)).scalar_one_or_none()
            return _item_to_dict(row)

    def get_stale_items(self, timeout_minutes: int = 30) -> list[dict]:
        """Get items that have been submitted but not completed within timeout."""
        cutoff = (datetime.now() - timedelta(minutes=timeout_minutes)).isoformat()
        with self._session() as session:
            rows = session.execute(
                select(BatchQueueItemRow).where(
                    BatchQueueItemRow.status == _SUBMITTED,
                    BatchQueueItemRow.submitted_at < cutoff,
                )
            ).scalars()
            return [_item_to_dict(r) for r in rows]

    def pending_count(self) -> int:
        """Count pending items."""
        with self._session() as session:
            count = session.execute(
                select(func.count())
                .select_from(BatchQueueItemRow)
                .where(BatchQueueItemRow.status == _PENDING)
            ).scalar()
            return int(count or 0)

    def cleanup_old(self, days: int = 7):
        """Remove completed/failed items older than N days."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with self._session() as session:
            session.execute(
                delete(BatchQueueItemRow).where(
                    BatchQueueItemRow.status.in_((_COMPLETED, _FAILED, _EXPIRED)),
                    BatchQueueItemRow.completed_at < cutoff,
                )
            )
            session.execute(
                delete(ActiveBatchRow).where(
                    ActiveBatchRow.status == _ENDED,
                    ActiveBatchRow.submitted_at < cutoff,
                )
            )
            session.commit()

    def delete_by_account(self, account_id: str | int) -> int:
        """Delete all queued batch rows for one account."""
        with self._session() as session:
            res = session.execute(
                delete(BatchQueueItemRow).where(
                    BatchQueueItemRow.account_id == str(account_id)
                )
            )
            session.commit()
            return res.rowcount


# ============================================================================
# BATCH WORKER (background thread)
# ============================================================================

class BatchWorker:
    """
    Background worker that submits micro-batches and polls for results.

    Lifecycle:
      1. Check pending queue size / age
      2. If threshold met → submit micro-batch
      3. Poll active batches for completion
      4. Process completed results → save PendingDrafts + emit WebSocket
      5. Handle stale items (fallback timeout)
      6. Periodic cleanup of old records
    """

    def __init__(self):
        self._queue = BatchQueue()
        self._adapter = None  # Lazy init
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._loop_count = 0

    @property
    def adapter(self):
        if self._adapter is None:
            from app.adapters.llm.claude_batch_adapter import ClaudeBatchAdapter
            self._adapter = ClaudeBatchAdapter()
        return self._adapter

    @property
    def queue(self) -> BatchQueue:
        return self._queue

    def start(self):
        """Start the background worker thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("BatchWorker already running")
            return

        self._stop_event.clear()
        self._install_signal_handlers()
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="batch-worker",
        )
        self._thread.start()
        logger.info("BatchWorker started")

    def _install_signal_handlers(self) -> None:
        """Audit MED-4 (2026-04-25): Railway envoie SIGTERM (pas
        KeyboardInterrupt) avant SIGKILL après ~30 s de grace. Sans handler,
        ``stop()`` n'est jamais appelé et un micro-batch en vol peut
        s'interleave avec le redéploy → soumissions Anthropic dupliquées.

        ``signal.signal`` ne fonctionne que dans le main thread ; si on est
        appelé hors main thread (cas tests), on swallow silencieusement.
        """
        if threading.current_thread() is not threading.main_thread():
            return
        try:
            prev = signal.getsignal(signal.SIGTERM)

            def _handler(signum, frame):
                logger.info("BatchWorker: SIGTERM received, stopping cleanly")
                self.stop()
                if callable(prev) and prev not in (signal.SIG_DFL, signal.SIG_IGN):
                    try:
                        prev(signum, frame)
                    except Exception:
                        pass

            signal.signal(signal.SIGTERM, _handler)
        except (ValueError, OSError):
            # ValueError si pas main thread, OSError sur certaines plateformes
            pass

    def stop(self):
        """Stop the background worker."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("BatchWorker stopped")

    def _run_loop(self):
        """Main worker loop.

        Audit cron-robustness (2026-04-25): un sleep exponentiel (1 → 2 → 4 →
        max 30 s) après une exception consécutive empêche un thrash CPU si
        ``_tick`` lève sur chaque itération (SQLite locked, Anthropic 429,
        etc.). Le compteur se réinitialise dès qu'un tick passe.
        """
        from app.config import BATCH_WORKER_POLL_SEC
        from app.services.scheduler_heartbeat import record_heartbeat

        consecutive_failures = 0
        backoff_max = 30
        # Issue #577 item 4 Phase B — the backoff path can stretch a tick
        # interval up to backoff_max=30s, so the tolerance is 2× the
        # worst case rather than 2× the nominal poll. Otherwise a single
        # 30s backoff would trip the sentinel.
        _heartbeat_interval = (BATCH_WORKER_POLL_SEC + backoff_max) * 2

        while not self._stop_event.is_set():
            record_heartbeat(
                "batch_worker",
                status="ok",
                expected_interval_seconds=_heartbeat_interval,
            )
            try:
                self._tick()
                consecutive_failures = 0
            except Exception as e:
                logger.error(f"BatchWorker tick error: {e}", exc_info=True)
                record_heartbeat(
                    "batch_worker",
                    status="error",
                    expected_interval_seconds=_heartbeat_interval,
                )
                consecutive_failures += 1
                penalty = min(backoff_max, 1 << min(consecutive_failures - 1, 5))
                if self._stop_event.wait(timeout=penalty):
                    break
                continue

            self._stop_event.wait(timeout=BATCH_WORKER_POLL_SEC)

    def _tick(self):
        """Single worker iteration."""
        from app.config import (
            BATCH_QUEUE_MIN_SIZE,
            BATCH_QUEUE_MAX_SIZE,
            BATCH_QUEUE_MAX_AGE_SEC,
            BATCH_FALLBACK_TIMEOUT_MIN,
        )

        self._loop_count += 1

        # Step 1: Check if we should submit a micro-batch
        pending_count = self._queue.pending_count()
        oldest_age = self._queue.get_oldest_pending_age_sec()

        should_submit = (
            pending_count >= BATCH_QUEUE_MIN_SIZE
            or (pending_count > 0 and oldest_age > BATCH_QUEUE_MAX_AGE_SEC)
        )

        if should_submit:
            self._submit_micro_batch(limit=BATCH_QUEUE_MAX_SIZE)

        # Step 2: Poll active batches
        active_batches = self._queue.get_active_batches()
        for batch_info in active_batches:
            self._poll_batch(batch_info["batch_id"])

        # Step 3: Handle stale items (every 10th tick)
        if self._loop_count % 10 == 0:
            stale = self._queue.get_stale_items(BATCH_FALLBACK_TIMEOUT_MIN)
            for item in stale:
                logger.warning(
                    f"Batch item {item['id'][:8]} stale ({item['email_id']}), "
                    f"marking as failed for real-time fallback"
                )
                self._queue.mark_failed(item["id"], "Batch timeout - stale")
                self._fallback_realtime(item)

        # Step 4: Cleanup old records (every 100th tick, ~50 min)
        if self._loop_count % 100 == 0:
            self._queue.cleanup_old(days=7)

    def _submit_micro_batch(self, limit: int = 50):
        """Submit a micro-batch of pending items."""
        from app.adapters.llm.claude_batch_adapter import BatchRequest

        pending = self._queue.get_pending(limit=limit)
        if not pending:
            return

        requests = []
        item_ids = []

        for item in pending:
            requests.append(BatchRequest(
                custom_id=item["id"],
                model=item["model"],
                system_prompt=item["system_prompt"],
                user_prompt=item["user_prompt"],
                max_tokens=item["max_tokens"],
                temperature=item.get("temperature", 0.5),
            ))
            item_ids.append(item["id"])

        batch_id = self.adapter.submit_batch(requests)
        if batch_id:
            self._queue.mark_submitted(item_ids, batch_id)
            logger.info(f"Micro-batch submitted: {batch_id} ({len(requests)} items)")
        else:
            logger.error("Micro-batch submission failed, items remain pending")

    def _poll_batch(self, batch_id: str):
        """Poll a batch and process results if ended."""
        status = self.adapter.get_batch_status(batch_id)
        if not status:
            return

        if status["status"] != "ended":
            return

        # Batch ended — retrieve and process results
        results = self.adapter.get_batch_results(batch_id)
        items = self._queue.get_items_for_batch(batch_id)
        items_by_id = {item["id"]: item for item in items}

        for result in results:
            item = items_by_id.get(result.custom_id)
            if not item:
                continue

            if result.status == "succeeded" and result.content:
                self._queue.mark_completed(
                    result.custom_id,
                    result.content,
                    result.input_tokens,
                    result.output_tokens,
                )
                self._save_draft(item, result.content)

                # Track token usage
                self._track_tokens(
                    item["model"],
                    result.input_tokens,
                    result.output_tokens,
                )
            else:
                error = result.error or result.status
                self._queue.mark_failed(result.custom_id, error)
                logger.warning(
                    f"Batch item {result.custom_id[:8]} failed: {error}"
                )
                # Try real-time fallback for failed items
                self._fallback_realtime(item)

        self._queue.mark_batch_ended(batch_id)
        logger.info(
            f"Batch {batch_id} processed: "
            f"{sum(1 for r in results if r.status == 'succeeded')} succeeded, "
            f"{sum(1 for r in results if r.status != 'succeeded')} failed"
        )

    def _save_draft(self, item: dict, draft_text: str):
        """Save a batch-generated draft as a PendingDraft."""
        try:
            metadata = json.loads(item["metadata"]) if item.get("metadata") else {}
            email_id = item["email_id"]
            sender = metadata.get("sender", "")
            subject = metadata.get("subject", "")
            body = metadata.get("body", "")

            from app.infrastructure.container import get_container
            from app.domain.entities.pending_draft import PendingDraft

            container = get_container()
            pending_store = container.get_pending_draft_store()

            # Check if draft already exists, INCLUDING rejected drafts.
            # DP-03 fix (2026-04-24): match daemon behaviour — preserve user's
            # rejection instead of silently regenerating on the next batch tick.
            from app.domain.entities.pending_draft import PendingDraftStatus as _PDStatus_bq2
            existing = pending_store.get_by_email_id_including_rejected(email_id)
            if existing:
                if existing.status == _PDStatus_bq2.REJECTED:
                    logger.info(
                        f"[BATCH] Skipping save for {email_id}: draft was rejected by user"
                    )
                else:
                    logger.info(
                        f"Draft already exists for {email_id}, skipping batch result"
                    )
                return

            reply_subject = subject or "(sans sujet)"
            if not reply_subject.lower().startswith("re:"):
                reply_subject = f"Re: {reply_subject}"

            # H-4 fix (2026-04-25 audit): the worker thread runs without
            # any request context, so AccountManager.get_current_account()
            # returns whoever activated last on the API — definitely NOT
            # the user who enqueued this batch item. Read account_id from
            # the queued row instead, which was captured at enqueue time
            # in the request context. Empty string means legacy / boot
            # path (single-account install) and is treated as None.
            _queued_aid = (item.get("account_id") or "").strip()
            _batch_account_id = _queued_aid if _queued_aid else None

            pending_draft = PendingDraft(
                email_id=email_id,
                email_sender=sender,
                email_sender_name=(
                    sender.split("<")[0].strip() if "<" in sender else sender
                ),
                email_subject=subject,
                email_body=body,
                email_received_at=None,
                draft_subject=reply_subject,
                draft_body=draft_text,
                draft_v1=draft_text,
                critique=f"Batch API ({item['tier']})",
                classification="action",
                priority=70,
                confidence=0.80,
                account_id=_batch_account_id,
            )

            draft_id = pending_store.add(pending_draft)
            logger.info(f"Batch draft saved for {email_id}: {draft_id[:8]}")

            # Emit WebSocket event (scoped to account)
            self._emit_draft_ready(email_id, draft_id, draft_text, reply_subject, sender, _batch_account_id)

        except Exception as e:
            logger.error(f"Failed to save batch draft for {item['email_id']}: {e}")

    def _emit_draft_ready(
        self, email_id: str, draft_id: str, draft_body: str,
        subject: str, sender: str, account_id: str | None = None,
    ):
        """Emit WebSocket event for batch-generated draft (scoped to account)."""
        try:
            from app.api.websocket import emit_to_account
            emit_to_account(
                "daemon_event",
                {
                    "type": "draft_ready",
                    "email_id": email_id,
                    "timestamp": datetime.now().isoformat(),
                    "payload": {
                        "pending_draft_id": draft_id,
                        "draft_content": draft_body,
                        "subject": subject,
                        "sender": sender,
                        "source": "batch",
                    },
                },
                int(account_id) if account_id else None,
            )
        except Exception:
            pass  # Non-critical

    def _track_tokens(self, model: str, input_tokens: int, output_tokens: int):
        """Track batch token usage for cost monitoring."""
        try:
            from app.infrastructure.container import get_container
            container = get_container()
            container.token_usage.add(input_tokens, output_tokens, model)
        except Exception:
            pass

    def _fallback_realtime(self, item: dict):
        """Attempt real-time draft generation as fallback for failed batch items."""
        try:
            metadata = json.loads(item["metadata"]) if item.get("metadata") else {}
            email_id = item["email_id"]
            sender = metadata.get("sender", "")
            subject = metadata.get("subject", "")
            body = metadata.get("body", "")

            from app.infrastructure.container import get_container
            container = get_container()

            # Check if draft already exists, INCLUDING rejected drafts.
            # DP-03 fix (2026-04-24): the previous `get_by_email_id` excluded
            # REJECTED — so a relabel/batch retry would silently override a
            # user's rejection. The daemon path uses
            # `get_by_email_id_including_rejected` for this exact reason; we
            # now match that behaviour. Short-circuit on REJECTED so the user's
            # rejection is preserved.
            pending_store = container.get_pending_draft_store()
            from app.domain.entities.pending_draft import PendingDraftStatus as _PDStatus_bq
            existing = pending_store.get_by_email_id_including_rejected(email_id)
            if existing:
                if existing.status == _PDStatus_bq.REJECTED:
                    logger.info(
                        f"[BATCH] Skipping fallback for {email_id}: draft was rejected by user"
                    )
                return

            # Use SmartRouter in real-time mode
            from app.smart_routing import SmartRouter
            router = SmartRouter()

            email_content = f"De: {sender}\nSujet: {subject or ''}\n\n{body or ''}"
            result = router.route(
                email_content=email_content,
                sender=sender,
                subject=subject or "",
                body=body or "",
                label="Action",
                force=True,
                thread_depth=0,
            )

            if result.draft:
                self._save_draft(
                    {**item, "tier": "fallback"},
                    result.draft,
                )
                logger.info(f"Fallback real-time draft generated for {email_id}")

        except Exception as e:
            logger.error(f"Fallback real-time draft failed for {item.get('email_id')}: {e}")


# ============================================================================
# SINGLETON
# ============================================================================

_worker: Optional[BatchWorker] = None


def get_batch_worker() -> BatchWorker:
    """Get the global BatchWorker singleton."""
    global _worker
    if _worker is None:
        _worker = BatchWorker()
    return _worker


def get_batch_queue() -> BatchQueue:
    """Get the BatchQueue from the global worker."""
    return get_batch_worker().queue
