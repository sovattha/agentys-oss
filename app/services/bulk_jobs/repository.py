"""Persistence layer for the bulk-action queue.

Owns *all* SQL the worker and the HTTP layer issue against `bulk_jobs`
and `bulk_job_items`. Two distinct write patterns coexist:

1. **Hot-path mutations** issued by the worker thread. These run on a
   private SQLAlchemy session per worker because a worker thread must
   not share a session with Flask request threads (`expire_on_commit=
   False` + the long-lived nature would leak stale state).
   The atomic claim uses SQLite's `UPDATE … RETURNING` (available since
   SQLite 3.35 / SQLCipher 4.5+).

2. **Cold-path queries** for HTTP routes. These reuse the regular
   `get_db_session()` context manager so they participate in normal
   per-request transaction management.

The repository never decides *what* to do with an item — that is the
worker's job. It only enforces invariants:
- counters monotonic;
- terminal jobs (`completed`/`failed`/`cancelled`) cannot be flipped
  back to `running`;
- claiming an item flips its state to `in_progress` atomically.
"""
from __future__ import annotations

import json
import logging
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.models.bulk_job import (
    ITEM_STATE_FAILED,
    ITEM_STATE_IN_PROGRESS,
    ITEM_STATE_PENDING,
    ITEM_STATE_SKIPPED,
    ITEM_STATE_SUCCEEDED,
    JOB_SOURCE_MANUAL,
    JOB_STATUS_CANCELLED,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    JOB_STATUS_PAUSED,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    JOB_STATUSES_TERMINAL,
    JOB_TYPES_KNOWN,
)

logger = logging.getLogger(__name__)


# ── ULID generation ────────────────────────────────────────────────────
# Crockford base32 alphabet. We don't need a third-party `ulid` package:
# 48 bits of millisecond timestamp + 80 bits of randomness packed as 26
# Crockford chars. Lexically sorts by creation time, opaque to clients.
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _generate_ulid() -> str:
    timestamp_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    randomness = secrets.randbits(80)
    value = (timestamp_ms << 80) | randomness
    chars: list[str] = []
    for _ in range(26):
        chars.append(_CROCKFORD[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


def _utc_now_iso() -> str:
    """ISO-8601 UTC stamp, second-precision. SQLite stores TEXT lexicographically."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── DTOs ───────────────────────────────────────────────────────────────
@dataclass
class NewBulkJob:
    """Caller-side description of a job to enqueue."""

    user_id: int | None
    account_id: int
    job_type: str
    target_msg_ids: list[str]
    source: str = JOB_SOURCE_MANUAL
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class ClaimedItem:
    """The single item the worker just took ownership of."""

    item_id: int
    job_id: str
    account_id: int
    job_type: str
    provider_msg_id: str
    attempts: int
    params: dict[str, Any]


# ── Repository ─────────────────────────────────────────────────────────
class BulkJobRepository:
    """Thin wrapper around `Session` that hides the bulk-job SQL.

    Sessions are passed in by the caller so this object stays stateless
    and trivially testable. The worker creates one persistent session
    via the global session factory; the HTTP layer uses request-scoped
    sessions through `get_db_session()`.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    # ── creation ───────────────────────────────────────────────────────
    def create_job(self, spec: NewBulkJob) -> str:
        """Insert a job + its items in a single transaction.

        Caller is responsible for `session.commit()` (or use the context
        manager). Empty `target_msg_ids` is rejected — there's no point
        creating an empty job, and the dispatcher would never finalize
        it.
        """
        if not spec.target_msg_ids:
            raise ValueError("create_job requires at least one target_msg_id")
        if spec.job_type not in JOB_TYPES_KNOWN:
            raise ValueError(
                f"unknown job_type {spec.job_type!r}; expected one of "
                f"{sorted(JOB_TYPES_KNOWN)}"
            )

        job_id = _generate_ulid()
        now = _utc_now_iso()
        # Dedup target IDs to avoid two items hitting the same message
        # within a single job. Across jobs we still allow duplicates —
        # the worker tolerates them via the 404-as-skipped rule.
        unique_ids = list(dict.fromkeys(spec.target_msg_ids))

        self._session.execute(
            text(
                """
                INSERT INTO bulk_jobs
                  (id, user_id, account_id, job_type, source, status,
                   target_total, params_json, created_at)
                VALUES
                  (:id, :user_id, :account_id, :job_type, :source, :status,
                   :target_total, :params_json, :created_at)
                """
            ),
            {
                "id": job_id,
                "user_id": spec.user_id,
                "account_id": spec.account_id,
                "job_type": spec.job_type,
                "source": spec.source,
                "status": JOB_STATUS_QUEUED,
                "target_total": len(unique_ids),
                "params_json": json.dumps(spec.params) if spec.params else None,
                "created_at": now,
            },
        )

        self._session.execute(
            text(
                """
                INSERT INTO bulk_job_items
                  (job_id, provider_msg_id, state, attempts, updated_at)
                VALUES
                  (:job_id, :provider_msg_id, :state, 0, :updated_at)
                """
            ),
            [
                {
                    "job_id": job_id,
                    "provider_msg_id": msg_id,
                    "state": ITEM_STATE_PENDING,
                    "updated_at": now,
                }
                for msg_id in unique_ids
            ],
        )
        return job_id

    # ── worker hot path ────────────────────────────────────────────────
    def claim_next_pending_for_account(
        self, account_id: int
    ) -> Optional[ClaimedItem]:
        """Atomically reserve the next pending item for `account_id`.

        FIFO ordering across all running jobs for the account: oldest
        job wins ties via `created_at`, then oldest item via `id`.
        Bumps the parent job from `queued` → `running` on its first
        claim.

        Returns None if no claimable item exists.
        """
        # First, promote any queued job that has pending work to running.
        # We do this in a separate statement so the RETURNING clause
        # below stays simple.
        now = _utc_now_iso()
        self._session.execute(
            text(
                """
                UPDATE bulk_jobs
                SET status = :running, started_at = COALESCE(started_at, :now)
                WHERE account_id = :account_id
                  AND status = :queued
                  AND id IN (
                    SELECT DISTINCT job_id FROM bulk_job_items WHERE state = :pending
                  )
                """
            ),
            {
                "running": JOB_STATUS_RUNNING,
                "queued": JOB_STATUS_QUEUED,
                "pending": ITEM_STATE_PENDING,
                "account_id": account_id,
                "now": now,
            },
        )

        # Atomic claim. UPDATE … RETURNING avoids the SELECT-then-UPDATE
        # race that would let two workers pop the same row. SQLite 3.35+.
        row = self._session.execute(
            text(
                """
                UPDATE bulk_job_items
                SET state = :in_progress, updated_at = :now
                WHERE id = (
                    SELECT i.id
                    FROM bulk_job_items i
                    JOIN bulk_jobs j ON j.id = i.job_id
                    WHERE j.account_id = :account_id
                      AND j.status = :running
                      AND i.state = :pending
                    ORDER BY j.created_at ASC, i.id ASC
                    LIMIT 1
                )
                RETURNING id, job_id, provider_msg_id, attempts
                """
            ),
            {
                "in_progress": ITEM_STATE_IN_PROGRESS,
                "pending": ITEM_STATE_PENDING,
                "running": JOB_STATUS_RUNNING,
                "account_id": account_id,
                "now": now,
            },
        ).first()

        if not row:
            return None

        # Need the parent job's type + params to build the operation.
        parent = self._session.execute(
            text(
                "SELECT job_type, params_json, account_id FROM bulk_jobs WHERE id = :id"
            ),
            {"id": row.job_id},
        ).first()
        if not parent:
            # Parent vanished mid-claim (account deleted CASCADE). Mark
            # the orphan skipped so we don't infinite-loop on it.
            self._session.execute(
                text(
                    "UPDATE bulk_job_items SET state = :skipped, "
                    "last_error = 'orphaned (parent gone)', updated_at = :now "
                    "WHERE id = :id"
                ),
                {
                    "skipped": ITEM_STATE_SKIPPED,
                    "id": row.id,
                    "now": _utc_now_iso(),
                },
            )
            return None

        params = json.loads(parent.params_json) if parent.params_json else {}
        return ClaimedItem(
            item_id=row.id,
            job_id=row.job_id,
            account_id=int(parent.account_id),
            job_type=parent.job_type,
            provider_msg_id=row.provider_msg_id,
            attempts=int(row.attempts),
            params=params,
        )

    def has_pending_for_account(self, account_id: int) -> bool:
        """Cheap predicate the dispatcher uses to know which AccountQueues
        need to wake up.
        """
        row = self._session.execute(
            text(
                """
                SELECT 1
                FROM bulk_job_items i
                JOIN bulk_jobs j ON j.id = i.job_id
                WHERE j.account_id = :account_id
                  AND j.status IN (:queued, :running)
                  AND i.state = :pending
                LIMIT 1
                """
            ),
            {
                "account_id": account_id,
                "queued": JOB_STATUS_QUEUED,
                "running": JOB_STATUS_RUNNING,
                "pending": ITEM_STATE_PENDING,
            },
        ).first()
        return row is not None

    def has_recent_job(
        self,
        *,
        account_id: int,
        job_type: str,
        source: str,
        since_iso: str,
    ) -> bool:
        """Used by the auto-deletion scheduler for idempotence.

        Returns True if a job matching `(account_id, job_type, source)`
        was created at or after `since_iso` and is *not* in a terminal
        state. Prevents the scheduler from enqueuing the same daily
        cleanup twice (e.g. on backend restart at 04:01).
        """
        row = self._session.execute(
            text(
                """
                SELECT 1
                FROM bulk_jobs
                WHERE account_id = :account_id
                  AND job_type = :job_type
                  AND source = :source
                  AND created_at >= :since
                  AND status NOT IN ('completed', 'failed', 'cancelled')
                LIMIT 1
                """
            ),
            {
                "account_id": account_id,
                "job_type": job_type,
                "source": source,
                "since": since_iso,
            },
        ).first()
        return row is not None

    def list_active_account_ids(self) -> list[int]:
        """Used by the dispatcher to decide which workers to spawn."""
        rows = self._session.execute(
            text(
                """
                SELECT DISTINCT account_id
                FROM bulk_jobs
                WHERE status IN (:queued, :running)
                """
            ),
            {"queued": JOB_STATUS_QUEUED, "running": JOB_STATUS_RUNNING},
        ).all()
        return [int(r.account_id) for r in rows]

    # ── result reporting ───────────────────────────────────────────────
    def mark_item_succeeded(self, item_id: int, job_id: str) -> None:
        now = _utc_now_iso()
        self._session.execute(
            text(
                """
                UPDATE bulk_job_items
                SET state = :succeeded, updated_at = :now, last_error = NULL
                WHERE id = :id
                """
            ),
            {"succeeded": ITEM_STATE_SUCCEEDED, "now": now, "id": item_id},
        )
        self._session.execute(
            text(
                """
                UPDATE bulk_jobs
                SET succeeded_count = succeeded_count + 1
                WHERE id = :id
                """
            ),
            {"id": job_id},
        )

    def mark_item_failed(self, item_id: int, job_id: str, error: str) -> None:
        now = _utc_now_iso()
        self._session.execute(
            text(
                """
                UPDATE bulk_job_items
                SET state = :failed, updated_at = :now, last_error = :err
                WHERE id = :id
                """
            ),
            {
                "failed": ITEM_STATE_FAILED,
                "now": now,
                "err": (error or "")[:1024],
                "id": item_id,
            },
        )
        self._session.execute(
            text(
                """
                UPDATE bulk_jobs
                SET failed_count = failed_count + 1
                WHERE id = :id
                """
            ),
            {"id": job_id},
        )

    def mark_item_skipped(self, item_id: int, job_id: str, reason: str) -> None:
        now = _utc_now_iso()
        self._session.execute(
            text(
                """
                UPDATE bulk_job_items
                SET state = :skipped, updated_at = :now, last_error = :err
                WHERE id = :id
                """
            ),
            {
                "skipped": ITEM_STATE_SKIPPED,
                "now": now,
                "err": (reason or "")[:1024],
                "id": item_id,
            },
        )
        self._session.execute(
            text(
                """
                UPDATE bulk_jobs
                SET skipped_count = skipped_count + 1
                WHERE id = :id
                """
            ),
            {"id": job_id},
        )

    def requeue_item_for_retry(
        self, item_id: int, error: str, *, bump_attempts: bool = True
    ) -> int:
        """Put an item back in pending. Returns the (possibly unchanged)
        `attempts` value so the worker can decide whether to give up.

        `bump_attempts=False` requeues *without* spending the retry budget.
        Used for non-error requeues — a mid-claim pause or a rate-limit
        throttle is not the item's fault, so counting it toward
        ITEM_MAX_ATTEMPTS would prematurely burn an item's budget and fail
        it before it ever hit a real error (bug #9).
        """
        now = _utc_now_iso()
        attempts_expr = "attempts + 1" if bump_attempts else "attempts"
        row = self._session.execute(
            text(
                f"""
                UPDATE bulk_job_items
                SET state = :pending,
                    attempts = {attempts_expr},
                    updated_at = :now,
                    last_error = :err
                WHERE id = :id
                RETURNING attempts
                """
            ),
            {
                "pending": ITEM_STATE_PENDING,
                "now": now,
                "err": (error or "")[:1024],
                "id": item_id,
            },
        ).first()
        return int(row.attempts) if row else 0

    # ── lifecycle transitions ──────────────────────────────────────────
    def get_job_status(self, job_id: str) -> Optional[str]:
        row = self._session.execute(
            text("SELECT status FROM bulk_jobs WHERE id = :id"),
            {"id": job_id},
        ).first()
        return row.status if row else None

    def finalize_job_if_drained(self, job_id: str) -> Optional[str]:
        """If no items remain pending or in_progress, mark the job
        completed/failed and stamp `completed_at`.

        Returns the final status if the job was finalized, None otherwise.
        Idempotent: a job already in a terminal state stays untouched.
        """
        snapshot = self._session.execute(
            text(
                """
                SELECT
                    j.status AS status,
                    j.target_total AS target_total,
                    j.failed_count AS failed_count,
                    j.succeeded_count AS succeeded_count,
                    COUNT(CASE WHEN i.state IN (:pending, :in_progress)
                               THEN 1 END) AS in_flight
                FROM bulk_jobs j
                LEFT JOIN bulk_job_items i ON i.job_id = j.id
                WHERE j.id = :id
                GROUP BY j.id
                """
            ),
            {
                "id": job_id,
                "pending": ITEM_STATE_PENDING,
                "in_progress": ITEM_STATE_IN_PROGRESS,
            },
        ).first()
        if not snapshot:
            return None
        if snapshot.status in JOB_STATUSES_TERMINAL:
            return snapshot.status
        if snapshot.in_flight > 0:
            return None

        # All items resolved. A job is FAILED when there were real
        # failures and *nothing* actually succeeded — this includes the
        # case the old `failed_count == target_total` rule missed: a
        # doomed scope job where 247 items 403-fail and 1 item 404-skips
        # would have shown COMPLETED (green) even though zero work landed.
        # A run with at least one success is a partial COMPLETED (the user
        # sees the failed_count and can retry). An all-skipped run (404s,
        # nothing left to do) is COMPLETED, not FAILED.
        new_status = (
            JOB_STATUS_FAILED
            if snapshot.failed_count > 0 and snapshot.succeeded_count == 0
            else JOB_STATUS_COMPLETED
        )
        self._session.execute(
            text(
                """
                UPDATE bulk_jobs
                SET status = :status, completed_at = :now
                WHERE id = :id AND status NOT IN ({terminal})
                """.format(
                    terminal=", ".join(
                        f"'{s}'" for s in sorted(JOB_STATUSES_TERMINAL)
                    )
                )
            ),
            {"status": new_status, "now": _utc_now_iso(), "id": job_id},
        )
        return new_status

    def request_pause(self, job_id: str) -> bool:
        return self._set_status_if(
            job_id, new=JOB_STATUS_PAUSED, allowed_from=(JOB_STATUS_RUNNING, JOB_STATUS_QUEUED)
        )

    def request_resume(self, job_id: str) -> bool:
        # Resume sends the job back to queued — the dispatcher picks it
        # up and promotes it to running on the next claim cycle.
        return self._set_status_if(
            job_id, new=JOB_STATUS_QUEUED, allowed_from=(JOB_STATUS_PAUSED,)
        )

    def request_cancel(self, job_id: str) -> bool:
        """Mark job cancelled and skip every remaining pending item.

        in_progress items are *not* aborted mid-flight (the worker
        thread might be in the middle of a network call); they finish
        naturally and the job stays in `cancelled` state. Counters keep
        climbing because the user still wants to know what landed.
        """
        ok = self._set_status_if(
            job_id,
            new=JOB_STATUS_CANCELLED,
            allowed_from=(JOB_STATUS_RUNNING, JOB_STATUS_QUEUED, JOB_STATUS_PAUSED),
        )
        if not ok:
            return False
        now = _utc_now_iso()
        result = self._session.execute(
            text(
                """
                UPDATE bulk_job_items
                SET state = :skipped,
                    updated_at = :now,
                    last_error = 'job cancelled'
                WHERE job_id = :id AND state = :pending
                """
            ),
            {
                "skipped": ITEM_STATE_SKIPPED,
                "pending": ITEM_STATE_PENDING,
                "id": job_id,
                "now": now,
            },
        )
        skipped = result.rowcount or 0
        if skipped:
            self._session.execute(
                text(
                    "UPDATE bulk_jobs SET skipped_count = skipped_count + :n, "
                    "completed_at = :now WHERE id = :id"
                ),
                {"n": skipped, "now": now, "id": job_id},
            )
        return True

    def fail_remaining_pending(self, job_id: str, reason: str) -> int:
        """Flip every still-pending item of `job_id` to `failed`.

        Used by the worker when a structural failure mode (auth, banned
        account) makes per-item retries pointless. `error_summary` on
        the parent job is set so the UI can show why everything died at
        once instead of spelunking through item rows.

        Returns the count of items flipped.
        """
        now = _utc_now_iso()
        truncated_reason = (reason or "")[:1024]
        result = self._session.execute(
            text(
                """
                UPDATE bulk_job_items
                SET state = :failed,
                    last_error = :reason,
                    updated_at = :now
                WHERE job_id = :id AND state = :pending
                """
            ),
            {
                "failed": ITEM_STATE_FAILED,
                "reason": truncated_reason,
                "now": now,
                "id": job_id,
                "pending": ITEM_STATE_PENDING,
            },
        )
        flipped = result.rowcount or 0
        if flipped > 0:
            self._session.execute(
                text(
                    """
                    UPDATE bulk_jobs
                    SET failed_count = failed_count + :n,
                        error_summary = :reason
                    WHERE id = :id
                    """
                ),
                {"n": flipped, "reason": truncated_reason, "id": job_id},
            )
        else:
            # No pending siblings to flip (e.g. a single-item job, or the
            # current item was already failed by the caller). Still stamp
            # error_summary so the UI shows *why* the job died instead of a
            # bare "1 failed" with no reason. (Bug #8: scope failures left
            # error_summary NULL because the only failure path was the
            # current item, not a sibling cascade.)
            self._session.execute(
                text(
                    """
                    UPDATE bulk_jobs
                    SET error_summary = :reason
                    WHERE id = :id
                    """
                ),
                {"reason": truncated_reason, "id": job_id},
            )
        return flipped

    def retry_failed(self, job_id: str) -> int:
        """Re-pending all `failed` items of `job_id`. Resets attempts to 0.

        Returns the count of requeued items. Forces the job back to
        `queued` if it was terminal.
        """
        now = _utc_now_iso()
        result = self._session.execute(
            text(
                """
                UPDATE bulk_job_items
                SET state = :pending, attempts = 0, last_error = NULL, updated_at = :now
                WHERE job_id = :id AND state = :failed
                """
            ),
            {
                "pending": ITEM_STATE_PENDING,
                "failed": ITEM_STATE_FAILED,
                "id": job_id,
                "now": now,
            },
        )
        requeued = result.rowcount or 0
        if requeued > 0:
            self._session.execute(
                text(
                    """
                    UPDATE bulk_jobs
                    SET status = :queued,
                        failed_count = MAX(0, failed_count - :n),
                        error_summary = NULL,
                        completed_at = NULL
                    WHERE id = :id
                    """
                ),
                {"queued": JOB_STATUS_QUEUED, "n": requeued, "id": job_id},
            )
        return requeued

    def delete_job(self, job_id: str) -> bool:
        """Delete a *terminal* job and its items (FK cascade).

        Used by the "dismiss" affordance so the user can clear a scary
        "248 failed" row that can't be usefully retried (e.g. a doomed
        scope job). Refuses to delete an active job — we never orphan
        in-flight work. Returns True if a row was deleted.
        """
        terminal_csv = ", ".join(f"'{s}'" for s in sorted(JOB_STATUSES_TERMINAL))
        result = self._session.execute(
            text(
                f"""
                DELETE FROM bulk_jobs
                WHERE id = :id AND status IN ({terminal_csv})
                """
            ),
            {"id": job_id},
        )
        return (result.rowcount or 0) > 0

    def _set_status_if(
        self, job_id: str, *, new: str, allowed_from: Iterable[str]
    ) -> bool:
        allowed = list(allowed_from)
        placeholders = ",".join(f":s{i}" for i in range(len(allowed)))
        params: dict[str, Any] = {"new": new, "id": job_id}
        for i, s in enumerate(allowed):
            params[f"s{i}"] = s
        result = self._session.execute(
            text(
                f"UPDATE bulk_jobs SET status = :new WHERE id = :id "
                f"AND status IN ({placeholders})"
            ),
            params,
        )
        return (result.rowcount or 0) > 0

    # ── recovery / maintenance ─────────────────────────────────────────
    def recover_orphaned_in_progress(self) -> int:
        """At boot, reset any item left in `in_progress` back to pending.

        The previous worker died mid-flight; at-least-once semantics
        make a re-attempt safe for every operation we support (404 is
        treated as `skipped` by the worker).
        """
        result = self._session.execute(
            text(
                """
                UPDATE bulk_job_items
                SET state = :pending, updated_at = :now
                WHERE state = :in_progress
                """
            ),
            {
                "pending": ITEM_STATE_PENDING,
                "in_progress": ITEM_STATE_IN_PROGRESS,
                "now": _utc_now_iso(),
            },
        )
        return result.rowcount or 0

    def vacuum_old_terminal_jobs(self, older_than_days: int = 30) -> int:
        """Delete completed/failed/cancelled jobs older than N days.

        Items cascade automatically. Returns the number of jobs deleted.
        Run weekly from a maintenance job.
        """
        if older_than_days <= 0:
            raise ValueError("older_than_days must be > 0")
        cutoff_ts = time.time() - older_than_days * 86400
        cutoff = (
            datetime.fromtimestamp(cutoff_ts, tz=timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ")
        )
        terminal_csv = ", ".join(f"'{s}'" for s in sorted(JOB_STATUSES_TERMINAL))
        result = self._session.execute(
            text(
                f"""
                DELETE FROM bulk_jobs
                WHERE status IN ({terminal_csv})
                  AND COALESCE(completed_at, created_at) < :cutoff
                """
            ),
            {"cutoff": cutoff},
        )
        return result.rowcount or 0

    # ── read-side queries (HTTP layer) ─────────────────────────────────
    def list_jobs_for_user(
        self,
        user_id: int | None,
        *,
        status: str | None = None,
        since_iso: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List jobs belonging to `user_id` (or all jobs if user_id is None,
        i.e. Tauri loopback mode).

        Tauri loopback intentionally sees every account's jobs because
        the desktop app is single-tenant. For multi-user web mode, the
        JWT user_id MUST be set and we filter on it.
        """
        clauses = ["1=1"]
        params: dict[str, Any] = {"limit": int(limit)}
        if user_id is not None:
            clauses.append("user_id = :user_id")
            params["user_id"] = user_id
        if status:
            clauses.append("status = :status")
            params["status"] = status
        if since_iso:
            clauses.append("created_at >= :since")
            params["since"] = since_iso

        rows = self._session.execute(
            text(
                f"""
                SELECT id, user_id, account_id, job_type, source, status,
                       target_total, succeeded_count, failed_count,
                       skipped_count, params_json, error_summary,
                       created_at, started_at, completed_at
                FROM bulk_jobs
                WHERE {" AND ".join(clauses)}
                ORDER BY created_at DESC
                LIMIT :limit
                """
            ),
            params,
        ).all()
        return [self._row_to_dict(r) for r in rows]

    def get_job(self, job_id: str) -> Optional[dict[str, Any]]:
        row = self._session.execute(
            text(
                """
                SELECT id, user_id, account_id, job_type, source, status,
                       target_total, succeeded_count, failed_count,
                       skipped_count, params_json, error_summary,
                       created_at, started_at, completed_at
                FROM bulk_jobs WHERE id = :id
                """
            ),
            {"id": job_id},
        ).first()
        return self._row_to_dict(row) if row else None

    def list_items(
        self,
        job_id: str,
        *,
        state: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses = ["job_id = :id"]
        params: dict[str, Any] = {"id": job_id, "limit": int(limit)}
        if state:
            clauses.append("state = :state")
            params["state"] = state
        rows = self._session.execute(
            text(
                f"""
                SELECT id, job_id, provider_msg_id, state, attempts,
                       last_error, updated_at
                FROM bulk_job_items
                WHERE {" AND ".join(clauses)}
                ORDER BY id ASC
                LIMIT :limit
                """
            ),
            params,
        ).all()
        return [
            {
                "id": r.id,
                "job_id": r.job_id,
                "provider_msg_id": r.provider_msg_id,
                "state": r.state,
                "attempts": r.attempts,
                "last_error": r.last_error,
                "updated_at": r.updated_at,
            }
            for r in rows
        ]

    @staticmethod
    def _row_to_dict(row: Any) -> dict[str, Any]:
        params: Any = None
        if row.params_json:
            try:
                params = json.loads(row.params_json)
            except json.JSONDecodeError:
                logger.warning(
                    "[bulk-jobs] job %s has corrupted params_json", row.id
                )
                params = None
        return {
            "id": row.id,
            "user_id": row.user_id,
            "account_id": row.account_id,
            "job_type": row.job_type,
            "source": row.source,
            "status": row.status,
            "target_total": row.target_total,
            "succeeded_count": row.succeeded_count,
            "failed_count": row.failed_count,
            "skipped_count": row.skipped_count,
            "params": params,
            "error_summary": row.error_summary,
            "created_at": row.created_at,
            "started_at": row.started_at,
            "completed_at": row.completed_at,
        }
