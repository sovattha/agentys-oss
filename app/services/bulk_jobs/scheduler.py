# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Auto-deletion scheduler — wires the 3 Settings toggles to the
bulk-action queue.

Daily tick (04:00 local by default; opt-out via env). For every active
account that opted in:

  - `auto_empty_trash_30d`  → enqueue `delete_forever` for trash items
                              older than 30 days.
  - `auto_empty_spam_30d`   → enqueue `move_to_trash` for spam items
                              older than 30 days. The 30-day cycle on
                              the trash folder finishes the job for
                              users who also enabled trash auto-empty.
  - `auto_delete_noise_30d` → enqueue `move_to_trash` for emails that
                              the local label store flagged "Noise"
                              more than 30 days ago.

Idempotence: every enqueue is gated by `BulkJobRepository.has_recent_job`
so a backend restart mid-tick (or two ticks colliding) cannot create
duplicate auto-deletion jobs for the same `(account, job_type)` pair on
the same day. The single-thread daemon loop also avoids the obvious
race entirely on a single instance — but the gate is the load-bearing
part, since multi-instance deploys are technically possible.

Keeps logic small and testable: enumeration calls into `provider.get_messages`
with a folder filter, the date filter is a Python comprehension, and the
enqueue path goes through the same `enqueue_job` as the HTTP layer.

Scope note — why three toggles, not five. An early design draft
(`tasks/plan-bulk-actions-queue.md` §5.5) sketched five auto-deletion
toggles, adding "drafts" and "newsletters". Those two are *intentionally*
not implemented — three is the deliberate, complete scope, not a
half-finished five:

  - **Drafts** are local `PendingDraft` rows, not provider messages. They
    have no `provider_msg_id`, so they cannot be items in the bulk-jobs
    queue (which is strictly `provider_msg_id -> provider op`). The manual
    `/emails/cleanup-all` route purges them synchronously instead.
  - **Newsletters** auto-deletion was never specced — there is no agreed
    detection signal — and the product decision is to not offer it. The
    "Noise" label already covers bulk low-value mail via
    `auto_delete_noise_30d`.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)


# ── Configuration knobs ────────────────────────────────────────────────
DAILY_TICK_HOUR_LOCAL = int(os.environ.get("AGENTYS_AUTO_DELETION_HOUR", "4"))
ENUMERATION_LIMIT = 500   # cap per (account, type) per tick
TRASH_RETENTION_DAYS = 30
SPAM_RETENTION_DAYS = 30
NOISE_RETENTION_DAYS = 30
# Spacing between per-account ticks. Avoids 04:00:00 thundering herd
# when many accounts are connected.
PER_ACCOUNT_DELAY_S = 30.0


@dataclass
class _TickStats:
    accounts_processed: int = 0
    jobs_enqueued: int = 0
    skipped_already_active: int = 0
    items_total: int = 0
    errors: int = 0


def _permanent_delete_available(settings: dict) -> bool:
    """Whether we should still try `delete_forever` for this account.

    Returns False once the worker has recorded that permanent delete fails
    for lack of the full Gmail OAuth scope (`_permanent_delete_unavailable`,
    set in `app.services.bulk_jobs.worker`). This is the circuit breaker the
    scheduler was missing (bug #2): without it the cron re-enqueues a job
    that 403s on every item, every day, forever. Gmail natively purges
    trash after 30 days, so the user-visible promise still holds — we just
    stop generating guaranteed-fail jobs and the 403 storm with them.
    """
    return not bool(settings.get("_permanent_delete_unavailable", False))


def _utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today_local_midnight_utc() -> str:
    """Return ISO-UTC for `today 00:00 local`. The scheduler uses this as
    the dedup window so a tick that fires at 04:00 only suppresses
    duplicates created since midnight (not since the previous tick at
    04:00 yesterday)."""
    now = datetime.now()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return _utc_iso(midnight.astimezone(timezone.utc))


def _enumerate_old_in_folder(
    provider,
    folder_kind: str,
    older_than_days: int,
) -> list[str]:
    """Return provider message IDs in `folder_kind` older than N days.

    Provider-agnostic. Falls back to an empty list on any failure (the
    cron has plenty of retries — daily — so a transient Gmail blip
    doesn't deserve an exception that kills the whole tick).
    """
    try:
        from app.api.routes_helpers import _resolve_folder_for_provider
        folder = _resolve_folder_for_provider(provider, folder_kind)
        msgs = provider.get_messages(limit=ENUMERATION_LIMIT, label_ids=[folder])
    except Exception as e:
        logger.warning(
            "[auto-deletion] enumerate %s failed: %s", folder_kind, e
        )
        return []

    # The provider cap is applied *before* the age filter below, so a
    # folder with more than ENUMERATION_LIMIT messages is only partially
    # enumerated this tick — the oldest items beyond the cap are never
    # seen. Surface that instead of silently under-cleaning (bug #6); the
    # daily cadence will chip away at the backlog over successive ticks.
    if msgs and len(msgs) >= ENUMERATION_LIMIT:
        logger.warning(
            "[auto-deletion] %s enumeration hit cap of %d; folder not fully "
            "scanned this tick (backlog drains over subsequent daily ticks)",
            folder_kind, ENUMERATION_LIMIT,
        )

    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    eligible: list[str] = []
    for m in msgs or []:
        msg_id = str(getattr(m, "id", "") or "")
        if not msg_id:
            continue
        # `received_at` / `date` are common fields; fall back to today
        # so the worst case is enqueuing a message that's *not* old
        # enough — rather than dropping a real candidate. The worker's
        # rate-limited replay across the next daily tick will eventually
        # catch it.
        ts = (
            getattr(m, "received_at", None)
            or getattr(m, "date", None)
        )
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                ts = None
        if ts is None or not isinstance(ts, datetime):
            # Unknown date → conservative skip. Keeps us from torching
            # recently-arrived spam by accident on a malformed payload.
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts <= cutoff:
            eligible.append(msg_id)
    return eligible


def _enumerate_old_noise(account_id: int, older_than_days: int) -> list[str]:
    """Return email IDs labeled "Noise" assigned more than N days ago.

    Pulls from the local label_store rather than scanning Gmail because
    the label is local-side metadata; the provider has no such concept.
    """
    try:
        from app.api.routes_helpers import _get_container

        container = _get_container()
        label_store = container.get_label_store(account_id=account_id)
        # The label store API doesn't expose "by-age" directly; we do a
        # cheap filter in Python because Noise tends to be a few hundred
        # rows. If this becomes a hotspot the right fix is a SQL view in
        # `email_labels` joined on `emails.received_at`.
        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        eligible: list[str] = []
        assignments = label_store.get_assignments(limit=ENUMERATION_LIMIT)
        if assignments and len(assignments) >= ENUMERATION_LIMIT:
            logger.warning(
                "[auto-deletion] noise enumeration hit cap of %d; not fully "
                "scanned this tick (backlog drains over subsequent ticks)",
                ENUMERATION_LIMIT,
            )
        for assignment in assignments:
            if "Noise" not in assignment.labels:
                continue
            assigned_at = getattr(assignment, "assigned_at", None)
            if not assigned_at:
                continue
            ts = assigned_at
            if isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except ValueError:
                    continue
            if not isinstance(ts, datetime):
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts <= cutoff:
                eligible.append(assignment.email_id)
        return eligible
    except Exception as e:
        logger.warning("[auto-deletion] noise enumeration failed: %s", e)
        return []


def _process_account(account_row, stats: _TickStats) -> None:
    """Apply every enabled toggle for one account."""
    from app.api.settings import load_settings
    from app.db.models.bulk_job import (
        JOB_SOURCE_AUTO_DELETION,
        JOB_TYPE_DELETE_FOREVER,
        JOB_TYPE_MOVE_TO_TRASH,
    )
    from app.db.database import get_db_session
    from app.multi_accounts import (
        create_provider_for_account,
        get_account_manager,
    )
    from app.services.bulk_jobs.repository import (
        BulkJobRepository,
        NewBulkJob,
    )
    from app.services.bulk_jobs.worker import enqueue_job

    account_id = int(account_row.id)
    settings = load_settings(account_id=account_id)

    # Cheap exit: nothing to do.
    if not any(
        settings.get(k, False)
        for k in (
            "auto_empty_trash_30d",
            "auto_empty_spam_30d",
            "auto_delete_noise_30d",
        )
    ):
        return

    # Build a provider once per account; the three toggles share it.
    try:
        mgr = get_account_manager()
        cfg = mgr.get_account_by_email(account_row.email)
        if cfg is None:
            logger.info(
                "[auto-deletion] no AccountConfig for %s, skipping",
                account_row.email,
            )
            return
        provider = create_provider_for_account(cfg)
        if not provider.authenticate():
            logger.info(
                "[auto-deletion] authenticate() failed for %s, skipping",
                account_row.email,
            )
            return
    except Exception as e:
        logger.warning(
            "[auto-deletion] provider build failed for %s: %s",
            account_row.email, e,
        )
        stats.errors += 1
        return

    today_iso = _today_local_midnight_utc()

    # Helper to enqueue with the dedup gate.
    def _maybe_enqueue(job_type: str, ids: list[str], label: str) -> None:
        if not ids:
            return
        with get_db_session() as session:
            repo = BulkJobRepository(session)
            if repo.has_recent_job(
                account_id=account_id,
                job_type=job_type,
                source=JOB_SOURCE_AUTO_DELETION,
                since_iso=today_iso,
            ):
                stats.skipped_already_active += 1
                logger.info(
                    "[auto-deletion] account %s: %s already active today, skip",
                    account_id, label,
                )
                return
        try:
            enqueue_job(
                NewBulkJob(
                    user_id=account_row.user_id,
                    account_id=account_id,
                    job_type=job_type,
                    target_msg_ids=ids,
                    source=JOB_SOURCE_AUTO_DELETION,
                    params={"reason": label},
                )
            )
            stats.jobs_enqueued += 1
            stats.items_total += len(ids)
            logger.info(
                "[auto-deletion] account %s: enqueued %s for %d items",
                account_id, label, len(ids),
            )
        except Exception as e:
            logger.warning(
                "[auto-deletion] account %s: enqueue %s failed: %s",
                account_id, label, e,
            )
            stats.errors += 1

    # ── auto_empty_trash_30d → permanent delete ────────────────────────
    if settings.get("auto_empty_trash_30d", False):
        if not _permanent_delete_available(settings):
            # Circuit breaker (bug #2): a prior tick proved this account
            # lacks the scope for permanent delete. Skip so we don't
            # re-enqueue a job that 403s on every item daily. Gmail's own
            # 30-day trash purge still empties the folder.
            logger.info(
                "[auto-deletion] account %s: permanent delete unavailable "
                "(missing OAuth scope), skipping trash_30d",
                account_id,
            )
        else:
            ids = _enumerate_old_in_folder(provider, "trash", TRASH_RETENTION_DAYS)
            _maybe_enqueue(JOB_TYPE_DELETE_FOREVER, ids, "trash_30d")

    # ── auto_empty_spam_30d → move to trash (then trash cron handles it) ─
    if settings.get("auto_empty_spam_30d", False):
        ids = _enumerate_old_in_folder(provider, "spam", SPAM_RETENTION_DAYS)
        _maybe_enqueue(JOB_TYPE_MOVE_TO_TRASH, ids, "spam_30d")

    # ── auto_delete_noise_30d → move to trash ─────────────────────────
    if settings.get("auto_delete_noise_30d", False):
        ids = _enumerate_old_noise(account_id, NOISE_RETENTION_DAYS)
        _maybe_enqueue(JOB_TYPE_MOVE_TO_TRASH, ids, "noise_30d")

    stats.accounts_processed += 1


def run_tick_once(
    *,
    only_account_id: int | None = None,
    stop_event: "threading.Event | None" = None,
) -> _TickStats:
    """Single-tick public entry point.

    Exposed so tests + ops scripts can fire a tick without waiting for
    the daemon's daily schedule. Logs a structured summary at the end.

    `stop_event`, when provided by the daemon, makes the inter-account
    spacing interruptible (clean shutdown) and enables a per-account
    heartbeat so a long multi-account tick isn't mistaken for a dead
    scheduler (bug #11: 8+ accounts × 30s blocking sleep exceeded the
    watchdog's 240s tolerance and the bare `time.sleep` ignored stop).
    """
    from app.db.database import get_db_session
    from app.db.repositories.account_repository import AccountRepository

    stats = _TickStats()
    try:
        with get_db_session() as session:
            accounts = AccountRepository(session).get_active_accounts()
            account_rows = [
                _AccountSnapshot(id=int(a.id), email=a.email, user_id=a.user_id)
                for a in accounts
            ]
    except Exception:
        logger.exception("[auto-deletion] account load failed")
        stats.errors += 1
        return stats

    if only_account_id is not None:
        account_rows = [a for a in account_rows if a.id == only_account_id]

    for i, row in enumerate(account_rows):
        # Daemon mode: beat before each account so a slow tick over many
        # accounts keeps the watchdog satisfied (bug #11).
        if stop_event is not None:
            try:
                from app.services.scheduler_heartbeat import record_heartbeat

                record_heartbeat(
                    "bulk_jobs_scheduler",
                    status="ok",
                    expected_interval_seconds=120,
                )
            except Exception:
                logger.debug("[auto-deletion] heartbeat failed", exc_info=True)
        try:
            _process_account(row, stats)
        except Exception:
            logger.exception(
                "[auto-deletion] account %s tick crashed", row.id
            )
            stats.errors += 1
        # Spread the load: don't slam every account in the same second.
        # Also gives the worker breathing room before the next chunk
        # of items piles into its FIFO queue. Interruptible under the
        # daemon so shutdown isn't blocked for up to 30s (bug #11).
        if i < len(account_rows) - 1:
            if stop_event is not None:
                if stop_event.wait(PER_ACCOUNT_DELAY_S):
                    break
            else:
                time.sleep(PER_ACCOUNT_DELAY_S)

    # Maintenance: prune old terminal jobs so the bulk_jobs table (on the
    # encrypted desktop DB) doesn't grow unbounded. This was implemented
    # but never called anywhere (bug #4); the daily tick is the natural
    # home for it.
    try:
        from app.services.bulk_jobs.repository import BulkJobRepository

        with get_db_session() as session:
            deleted = BulkJobRepository(session).vacuum_old_terminal_jobs(
                older_than_days=30
            )
        if deleted:
            logger.info(
                "[auto-deletion] vacuumed %d old terminal bulk job(s)", deleted
            )
    except Exception:
        logger.exception("[auto-deletion] vacuum failed (non-fatal)")

    logger.info(
        "[auto-deletion] tick done: accounts=%d enqueued=%d skipped=%d items=%d errors=%d",
        stats.accounts_processed,
        stats.jobs_enqueued,
        stats.skipped_already_active,
        stats.items_total,
        stats.errors,
    )
    return stats


@dataclass
class _AccountSnapshot:
    """Tiny POD so we don't drag SQLAlchemy detached instances across
    worker iterations (each `_process_account` opens its own session)."""
    id: int
    email: str
    user_id: int | None


# ── Daemon thread (runs forever, fires daily at 04:00 local) ───────────
class AutoDeletionScheduler:
    """Background thread that fires `run_tick_once` daily.

    Doesn't depend on APScheduler — Agentys already standardized on the
    plain-thread + Event idiom for its other schedulers (RecapScheduler,
    GmailWatchScheduler) and adding a third scheduling library here
    would be gratuitous. The clock-skew window is at most one minute,
    which is fine for a daily cleanup.
    """

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # Last-fire date so a slow tick can't re-fire mid-day if the
        # process happens to wake near the boundary.
        self._last_fired_date: Optional[str] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="AutoDeletionScheduler",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "[auto-deletion] started (daily %02d:00 local)",
            DAILY_TICK_HOUR_LOCAL,
        )

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        # 30s grace before the first scan so the rest of the API has
        # time to finish booting (DB engine, Socket.IO, etc.).
        if self._stop.wait(timeout=30):
            return
        while not self._stop.is_set():
            # Issue #577 item 4 Phase B — heartbeat at the START of each
            # tick. The loop polls every 60s; tolerance 2× lets a single
            # missed tick (slow DB, long account iteration) pass.
            from app.services.scheduler_heartbeat import record_heartbeat

            record_heartbeat(
                "bulk_jobs_scheduler",
                status="ok",
                expected_interval_seconds=120,
            )
            try:
                self._maybe_fire()
            except Exception:
                logger.exception("[auto-deletion] tick loop error (non-fatal)")
                record_heartbeat(
                    "bulk_jobs_scheduler",
                    status="error",
                    expected_interval_seconds=120,
                )
            # Poll every minute. Cheap, and lets the daemon converge
            # quickly if the user changes their system clock.
            if self._stop.wait(timeout=60):
                break

    def _maybe_fire(self) -> None:
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        if now.hour != DAILY_TICK_HOUR_LOCAL:
            return
        if self._last_fired_date == today_str:
            return
        self._last_fired_date = today_str
        run_tick_once(stop_event=self._stop)


_scheduler_singleton: Optional[AutoDeletionScheduler] = None
_scheduler_lock = threading.Lock()


def init_scheduler() -> AutoDeletionScheduler:
    """Idempotent boot, called from `run_api.py`."""
    global _scheduler_singleton
    with _scheduler_lock:
        if _scheduler_singleton is None:
            _scheduler_singleton = AutoDeletionScheduler()
        _scheduler_singleton.start()
        return _scheduler_singleton


def shutdown_scheduler() -> None:
    global _scheduler_singleton
    with _scheduler_lock:
        if _scheduler_singleton is None:
            return
        _scheduler_singleton.stop()
        _scheduler_singleton = None
