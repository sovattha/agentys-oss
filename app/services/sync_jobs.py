# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Provider sync job queue.

This module keeps Gmail/Outlook/IMAP work out of read-only HTTP endpoints.
Jobs are persisted so the web app can scale past a single request thread and
so repeated refreshes coalesce per account/folder.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
import uuid
import zlib
from datetime import datetime, timedelta, timezone
from typing import Any, cast

from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError

from app.db.database import get_db_session
from app.db.models.account import Account
from app.db.models.provider_quota_window import ProviderQuotaWindow
from app.db.models.sync_job import (
    SYNC_JOB_ACTIVE_STATUSES,
    SYNC_JOB_STATUS_COMPLETED,
    SYNC_JOB_STATUS_FAILED,
    SYNC_JOB_STATUS_QUEUED,
    SYNC_JOB_STATUS_RETRY_WAITING,
    SYNC_JOB_STATUS_RUNNING,
    SyncJob,
)
from app.infrastructure.thread_pool import submit_background

logger = logging.getLogger(__name__)
_INBOX_SYNC_LIMIT = 100
_SECONDARY_SYNC_LIMIT = 50
_STALE_SYNC_JOB_SECONDS = 15 * 60
_SYNC_JOB_LEASE_SECONDS_ENV = "AGENTYS_SYNC_JOB_LEASE_SECONDS"
_DEFAULT_LEASE_SECONDS = 120
_MAX_ATTEMPTS = 3
_RETRY_BACKOFF_BASE_SECONDS = 30
_RETRY_BACKOFF_MAX_SECONDS = 5 * 60
_DISPATCH_CONCURRENCY_ENV = "AGENTYS_SYNC_JOB_DISPATCH_CONCURRENCY"
_DEFAULT_DISPATCH_CONCURRENCY = 4
_GMAIL_PROJECT_UNITS_PER_MINUTE_ENV = "AGENTYS_GMAIL_PROJECT_UNITS_PER_MINUTE"
_GMAIL_ACCOUNT_UNITS_PER_MINUTE_ENV = "AGENTYS_GMAIL_ACCOUNT_UNITS_PER_MINUTE"
_GMAIL_QUOTA_SHARDS_ENV = "AGENTYS_GMAIL_QUOTA_SHARDS"
_DEFAULT_GMAIL_PROJECT_UNITS_PER_MINUTE = 1_200_000
_DEFAULT_GMAIL_ACCOUNT_UNITS_PER_MINUTE = 6_000
_DEFAULT_GMAIL_QUOTA_SHARDS = 32
_GMAIL_QUOTA_WINDOW_SECONDS = 60
_GMAIL_QUOTA_RETENTION_SECONDS = 10 * 60
_GMAIL_QUOTA_RETRY_SECONDS = 15
_SYNC_JOB_ADVISORY_NAMESPACE = "agentys.sync_jobs"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_utc() -> datetime:
    # SQLAlchemy DateTime columns in this schema are timezone-naive.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _coerce_utc(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None

    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def _datetime_to_json(value: Any) -> str | None:
    parsed = _coerce_utc(value)
    return parsed.isoformat() if parsed is not None else None


def _signed_crc32(value: str) -> int:
    key = zlib.crc32(value.encode("utf-8"))
    return key - 2**32 if key >= 2**31 else key


def _lock_sync_job_scope(session: Any, account_id: int, folder: str) -> None:
    bind = session.get_bind()
    if getattr(bind.dialect, "name", "") != "postgresql":
        return

    session.execute(
        text("SELECT pg_advisory_xact_lock(:namespace_key, :scope_key)"),
        {
            "namespace_key": _signed_crc32(_SYNC_JOB_ADVISORY_NAMESPACE),
            "scope_key": _signed_crc32(f"{account_id}:{folder}"),
        },
    )


def _make_lease_owner() -> str:
    return (
        f"{socket.gethostname()}:{os.getpid()}:"
        f"{threading.get_ident()}:{uuid.uuid4().hex[:8]}"
    )


def _lease_expired(job: SyncJob, now: datetime) -> bool:
    started_at = _coerce_utc(job.started_at)
    if started_at is not None:
        age_seconds = (now - started_at).total_seconds()
        if age_seconds >= _lease_seconds():
            return True

    expires_at = _coerce_utc(job.lease_expires_at)
    return expires_at is not None and expires_at <= now


def _backoff_elapsed(job: SyncJob, now: datetime) -> bool:
    backoff_until = _coerce_utc(job.backoff_until)
    return backoff_until is None or backoff_until <= now


def _next_backoff_until(attempt_count: int, now: datetime) -> datetime:
    exponent = max(0, attempt_count - 1)
    delay_seconds = min(
        _RETRY_BACKOFF_BASE_SECONDS * (2 ** exponent),
        _RETRY_BACKOFF_MAX_SECONDS,
    )
    return now + timedelta(seconds=delay_seconds)


def _max_dispatch_concurrency() -> int:
    raw = os.getenv(_DISPATCH_CONCURRENCY_ENV, str(_DEFAULT_DISPATCH_CONCURRENCY))
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        logger.warning(
            "Invalid %s=%r; using %s",
            _DISPATCH_CONCURRENCY_ENV,
            raw,
            _DEFAULT_DISPATCH_CONCURRENCY,
        )
        return _DEFAULT_DISPATCH_CONCURRENCY


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        logger.warning("Invalid %s=%r; using %s", name, raw, default)
        return default


def _lease_seconds() -> int:
    return _env_int(_SYNC_JOB_LEASE_SECONDS_ENV, _DEFAULT_LEASE_SECONDS)


def _gmail_project_units_per_minute() -> int:
    return _env_int(
        _GMAIL_PROJECT_UNITS_PER_MINUTE_ENV,
        _DEFAULT_GMAIL_PROJECT_UNITS_PER_MINUTE,
    )


def _gmail_account_units_per_minute() -> int:
    return _env_int(
        _GMAIL_ACCOUNT_UNITS_PER_MINUTE_ENV,
        _DEFAULT_GMAIL_ACCOUNT_UNITS_PER_MINUTE,
    )


def _gmail_quota_shards() -> int:
    return _env_int(_GMAIL_QUOTA_SHARDS_ENV, _DEFAULT_GMAIL_QUOTA_SHARDS)


def _estimate_sync_job_provider_units(job: SyncJob, provider: str) -> int:
    if provider.lower() != "gmail":
        return 0
    requested_limit = max(1, int(job.requested_limit or 1))
    return 5 + (requested_limit * 20)


def _account_provider(session: Any, account_id: int) -> str:
    account = session.get(Account, account_id)
    return str(getattr(account, "provider", "") or "")


def _quota_window_start(now: datetime) -> datetime:
    normalized = _coerce_utc(now) or _now_utc()
    timestamp = int(normalized.replace(tzinfo=timezone.utc).timestamp())
    window_start = timestamp - (timestamp % _GMAIL_QUOTA_WINDOW_SECONDS)
    return datetime.fromtimestamp(window_start, timezone.utc).replace(tzinfo=None)


def _gmail_project_scope_key(account_id: int) -> str:
    shard_count = _gmail_quota_shards()
    return f"project:{account_id % shard_count}"


def _gmail_project_shard_limit() -> int:
    project_limit = _gmail_project_units_per_minute()
    return max(1, project_limit // _gmail_quota_shards())


def _prune_old_gmail_quota_windows(session: Any, now: datetime) -> None:
    cutoff = now - timedelta(seconds=_GMAIL_QUOTA_RETENTION_SECONDS)
    session.execute(
        delete(ProviderQuotaWindow).where(
            ProviderQuotaWindow.provider == "gmail",
            ProviderQuotaWindow.window_start < cutoff,
        )
    )


def _locked_quota_window(
    session: Any,
    *,
    provider: str,
    quota_scope: str,
    scope_key: str,
    window_start: datetime,
) -> ProviderQuotaWindow:
    query = (
        select(ProviderQuotaWindow)
        .where(
            ProviderQuotaWindow.provider == provider,
            ProviderQuotaWindow.quota_scope == quota_scope,
            ProviderQuotaWindow.scope_key == scope_key,
            ProviderQuotaWindow.window_start == window_start,
        )
        .with_for_update()
    )
    window = session.scalars(query).one_or_none()
    if window is not None:
        return cast(ProviderQuotaWindow, window)

    try:
        with session.begin_nested():
            window = ProviderQuotaWindow(
                provider=provider,
                quota_scope=quota_scope,
                scope_key=scope_key,
                window_start=window_start,
                units_reserved=0,
            )
            session.add(window)
            session.flush()
        return window
    except IntegrityError:
        return cast(ProviderQuotaWindow, session.scalars(query).one())


def _reserve_gmail_quota(
    session: Any,
    *,
    account_id: int,
    units: int,
    now: datetime,
) -> bool:
    if units <= 0:
        return True
    window_start = _quota_window_start(now)
    _prune_old_gmail_quota_windows(session, now)

    project_limit = _gmail_project_shard_limit()
    account_limit = _gmail_account_units_per_minute()
    charge = max(1, units)

    project_window = _locked_quota_window(
        session,
        provider="gmail",
        quota_scope="project",
        scope_key=_gmail_project_scope_key(account_id),
        window_start=window_start,
    )
    if project_window.units_reserved + charge > project_limit:
        return False

    account_window = _locked_quota_window(
        session,
        provider="gmail",
        quota_scope="account",
        scope_key=str(account_id),
        window_start=window_start,
    )
    if account_window.units_reserved + charge > account_limit:
        return False

    project_window.units_reserved += charge
    account_window.units_reserved += charge
    return True


def _defer_sync_job_for_gmail_quota(job: SyncJob, now: datetime, units: int) -> None:
    job.status = SYNC_JOB_STATUS_RETRY_WAITING
    job.backoff_until = now + timedelta(seconds=_GMAIL_QUOTA_RETRY_SECONDS)
    job.last_error_code = "gmail_quota_budget"
    job.error_summary = "Gmail quota budget exhausted; retry scheduled"
    job.provider_units_estimate = units


def _reset_gmail_quota_for_tests() -> None:
    return None


def _active_running_job_count(session: Any, now: datetime) -> int:
    running_jobs = session.scalars(
        select(SyncJob).where(SyncJob.status == SYNC_JOB_STATUS_RUNNING)
    ).all()
    active = 0
    for job in running_jobs:
        if job.lease_owner:
            if not _lease_expired(job, now):
                active += 1
            continue
        if _stale_job_age_seconds(job, now) is None:
            active += 1
    return active


def _claim_sync_job_for_worker(job: SyncJob, now: datetime) -> tuple[str, str]:
    lease_owner = _make_lease_owner()
    if job.status == SYNC_JOB_STATUS_RETRY_WAITING:
        job.backoff_until = None
        job.error_summary = "Retry backoff elapsed; job claimed"
    elif job.status == SYNC_JOB_STATUS_RUNNING:
        job.error_summary = "Expired sync job lease reclaimed by dispatcher"

    job.status = SYNC_JOB_STATUS_RUNNING
    job.started_at = _now_iso()
    job.lease_owner = lease_owner
    job.lease_expires_at = now + timedelta(seconds=_lease_seconds())
    job.attempt_count += 1
    return job.id, lease_owner


def _ready_sync_job_candidates(session: Any, now: datetime, limit: int) -> list[SyncJob]:
    candidates: list[SyncJob] = []
    queued_jobs = session.scalars(
        select(SyncJob)
        .where(SyncJob.status == SYNC_JOB_STATUS_QUEUED)
        .order_by(SyncJob.created_at.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()
    candidates.extend(queued_jobs)

    remaining = limit - len(candidates)
    if remaining > 0:
        retry_jobs = session.scalars(
            select(SyncJob)
            .where(SyncJob.status == SYNC_JOB_STATUS_RETRY_WAITING)
            .where(
                (SyncJob.backoff_until.is_(None))
                | (SyncJob.backoff_until <= now)
            )
            .order_by(SyncJob.created_at.asc())
            .limit(remaining)
            .with_for_update(skip_locked=True)
        ).all()
        candidates.extend(retry_jobs)

    remaining = limit - len(candidates)
    if remaining > 0:
        expired_running_jobs = session.scalars(
            select(SyncJob)
            .where(SyncJob.status == SYNC_JOB_STATUS_RUNNING)
            .where(SyncJob.lease_owner.is_not(None))
            .where(SyncJob.lease_expires_at <= now)
            .order_by(SyncJob.created_at.asc())
            .limit(remaining)
            .with_for_update(skip_locked=True)
        ).all()
        candidates.extend(expired_running_jobs)

    return candidates


def _dispatch_ready_sync_jobs() -> list[str]:
    """Claim ready jobs up to the global cap and submit only those workers."""
    claimed: list[tuple[str, str]] = []
    with get_db_session() as session:
        now = _now_utc()
        available_slots = _max_dispatch_concurrency() - _active_running_job_count(session, now)
        if available_slots <= 0:
            return []

        for job in _ready_sync_job_candidates(session, now, available_slots):
            provider = _account_provider(session, job.account_id)
            units = _estimate_sync_job_provider_units(job, provider)
            if not _reserve_gmail_quota(
                session,
                account_id=job.account_id,
                units=units,
                now=now,
            ):
                _defer_sync_job_for_gmail_quota(job, now, units)
                continue
            job.provider_units_estimate = units
            claimed.append(_claim_sync_job_for_worker(job, now))
        session.flush()

    for job_id, lease_owner in claimed:
        submit_background(_run_sync_job, job_id, lease_owner)  # type: ignore[no-untyped-call]
    return [job_id for job_id, _ in claimed]


def _stale_job_age_seconds(job: SyncJob, now: datetime) -> int | None:
    anchor = _coerce_utc(job.started_at) or _coerce_utc(job.created_at)
    if anchor is None:
        return None
    age = int((now - anchor).total_seconds())
    if age < _STALE_SYNC_JOB_SECONDS:
        return None
    return age


def _job_to_dict(job: SyncJob, *, coalesced: bool = False) -> dict[str, Any]:
    return {
        "id": job.id,
        "account_id": job.account_id,
        "folder": job.folder,
        "status": job.status,
        "source": job.source,
        "requested_limit": job.requested_limit,
        "unread_only": job.unread_only,
        "coalesced": coalesced,
        "coalesced_count": job.coalesced_count,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "error_summary": job.error_summary,
        "lease_expires_at": _datetime_to_json(job.lease_expires_at),
        "attempt_count": job.attempt_count,
        "backoff_until": _datetime_to_json(job.backoff_until),
        "last_error_code": job.last_error_code,
        "provider_units_estimate": job.provider_units_estimate,
    }


def enqueue_sync_job(
    *,
    account_id: int,
    folder: str = "inbox",
    limit: int = 50,
    unread_only: bool = False,
    user_id: int | None = None,
    source: str = "manual",
) -> dict[str, Any]:
    """Create or coalesce a provider sync job.

    At most one active job per ``(account_id, folder)`` is allowed. This turns
    a burst of refresh clicks or stale-read revalidations into a single provider
    sync, which protects shared Railway capacity and Gmail quotas.
    """
    if account_id <= 0:
        raise ValueError("account_id must be a positive DB id")

    normalized_folder = (folder or "inbox").lower()
    requested_limit = max(1, int(limit or 50))
    cap = _INBOX_SYNC_LIMIT if normalized_folder == "inbox" else _SECONDARY_SYNC_LIMIT
    safe_limit = min(requested_limit, cap)

    should_dispatch = False
    job_dict: dict[str, Any] = {}
    with get_db_session() as session:
        _lock_sync_job_scope(session, account_id, normalized_folder)
        existing = session.scalars(
            select(SyncJob)
            .where(
                SyncJob.account_id == account_id,
                SyncJob.folder == normalized_folder,
                SyncJob.status.in_(SYNC_JOB_ACTIVE_STATUSES),
            )
            .order_by(SyncJob.created_at.desc())
            .limit(1)
            .with_for_update()
        ).first()
        if existing:
            now = _now_utc()
            existing.coalesced_count += 1
            existing.requested_limit = max(existing.requested_limit, safe_limit)
            existing.unread_only = existing.unread_only and bool(unread_only)

            if existing.status == SYNC_JOB_STATUS_RETRY_WAITING:
                if _backoff_elapsed(existing, now):
                    existing.status = SYNC_JOB_STATUS_QUEUED
                    existing.backoff_until = None
                    existing.error_summary = "Retry backoff elapsed; job requeued"
                    should_dispatch = True
                session.flush()
                job_dict = _job_to_dict(existing, coalesced=True)
            elif (
                existing.status == SYNC_JOB_STATUS_RUNNING
                and existing.lease_owner
                and _lease_expired(existing, now)
            ):
                existing.status = SYNC_JOB_STATUS_QUEUED
                existing.lease_owner = None
                existing.lease_expires_at = None
                existing.error_summary = "Expired sync job lease reclaimed; job requeued"
                should_dispatch = True
                session.flush()
                job_dict = _job_to_dict(existing, coalesced=True)
                logger.warning(
                    "Reclaimed expired sync job lease %s for account=%s folder=%s",
                    existing.id,
                    account_id,
                    normalized_folder,
                )
            elif (
                not existing.lease_owner
                and (stale_age := _stale_job_age_seconds(existing, now)) is not None
            ):
                existing.status = SYNC_JOB_STATUS_FAILED
                existing.completed_at = _now_iso()
                existing.error_summary = (
                    f"Stale sync job reclaimed after {stale_age}s; "
                    "replacement job enqueued"
                )
                session.flush()
                logger.warning(
                    "Reclaimed stale sync job %s for account=%s folder=%s age=%ss",
                    existing.id,
                    account_id,
                    normalized_folder,
                    stale_age,
                )
                job_dict = {}
            else:
                should_dispatch = existing.status == SYNC_JOB_STATUS_QUEUED
                session.flush()
                job_dict = _job_to_dict(existing, coalesced=True)

            if job_dict and not should_dispatch:
                return job_dict

        if not job_dict:
            job = SyncJob(
                id=uuid.uuid4().hex,
                user_id=user_id,
                account_id=account_id,
                folder=normalized_folder,
                status=SYNC_JOB_STATUS_QUEUED,
                source=source,
                requested_limit=safe_limit,
                unread_only=bool(unread_only),
            )
            session.add(job)
            session.flush()
            job_dict = _job_to_dict(job, coalesced=False)
            should_dispatch = True

    if should_dispatch:
        _dispatch_ready_sync_jobs()
        try:
            from app.api.websocket import emit_sync_progress

            emit_sync_progress(account_id, "queued")
        except Exception as exc:
            logger.debug("sync job queued WS emit failed: %s", exc)
    return job_dict


def _run_sync_job(job_id: str, lease_owner: str | None = None) -> None:
    """Run one queued sync job in the shared background pool."""
    job_snapshot: dict[str, Any] | None = None
    worker_lease_owner = lease_owner or _make_lease_owner()
    with get_db_session() as session:
        job = session.scalars(
            select(SyncJob)
            .where(SyncJob.id == job_id)
            .limit(1)
            .with_for_update()
        ).first()
        if not job:
            logger.warning("sync job %s disappeared before execution", job_id)
            return
        now = _now_utc()
        if lease_owner is not None:
            if (
                job.status != SYNC_JOB_STATUS_RUNNING
                or job.lease_owner != lease_owner
                or _lease_expired(job, now)
            ):
                logger.info("sync job %s no longer owns lease %s", job_id, lease_owner)
                return
        else:
            if job.status == SYNC_JOB_STATUS_RETRY_WAITING and not _backoff_elapsed(job, now):
                logger.info("sync job %s is still in retry backoff", job_id)
                return
            if job.status not in SYNC_JOB_ACTIVE_STATUSES:
                logger.info("sync job %s is no longer active (status=%s)", job_id, job.status)
                return
            if (
                job.status == SYNC_JOB_STATUS_RUNNING
                and job.lease_owner
                and not _lease_expired(job, now)
            ):
                logger.info("sync job %s already has an active lease", job_id)
                return
            _claim_sync_job_for_worker(job, now)
            worker_lease_owner = job.lease_owner or worker_lease_owner
        session.flush()
        job_snapshot = _job_to_dict(job)

    account_id = int(job_snapshot["account_id"])
    job_t0 = time.perf_counter()
    try:
        from app.api import routes_helpers as _rh
        from app.api.routes_emails import _sync_emails_to_cache
        from app.api.websocket import emit_sync_progress, emit_to_account

        emit_sync_progress(account_id, "syncing")
        oauth_account_id = _rh._resolve_oauth_account_id_for_db_account(account_id)
        if not oauth_account_id:
            # Secondary folders have no other sync path: surface the terminal
            # failure to the list route or it reports syncing forever.
            _rh.record_folder_sync_outcome(
                account_id, str(job_snapshot["folder"]), ok=False,
            )
            raise RuntimeError("No OAuth account configured for sync job")

        folder = str(job_snapshot["folder"])
        requested_limit = int(job_snapshot["requested_limit"])
        logger.info(
            "[SYNC-JOB] start job_id=%s account_id=%s folder=%s source=%s "
            "limit=%s coalesced_count=%s attempt=%s",
            job_id,
            account_id,
            folder,
            job_snapshot.get("source"),
            requested_limit,
            job_snapshot.get("coalesced_count"),
            job_snapshot.get("attempt_count"),
        )
        # Capture row count so the ``sync_complete`` WS payload is truthful.
        # Audit 2026-05-17: the prior code hardcoded ``new_emails: 0`` here,
        # which made the FE skeleton stuck for the full 12 s cold-start
        # fallback whenever Spam/Trash/Archived were opened for the first
        # time (FE handler only refreshes when ``new_emails > 0``).
        synced_count = 0
        if folder == "sent":
            synced_count = _rh._refresh_sent_cache_bg(
                account_id, oauth_account_id, requested_limit,
            ) or 0
        elif folder in {"trash", "spam", "archived"}:
            synced_count = _rh._refresh_folder_cache_bg(
                folder, account_id, oauth_account_id, requested_limit,
            ) or 0
        else:
            synced_count = _sync_emails_to_cache(
                account_id,
                requested_limit,
                bool(job_snapshot["unread_only"]),
                oauth_account_id,
                folder,
            ) or 0

        lease_intact = True
        with get_db_session() as session:
            job = session.scalars(
                select(SyncJob)
                .where(SyncJob.id == job_id)
                .limit(1)
                .with_for_update()
            ).first()
            if job:
                if job.lease_owner != worker_lease_owner:
                    # Audit F-05 (2026-05-17 deep-audit): the previous
                    # ``return`` here skipped the user-facing terminal
                    # WS events (emit_sync_progress + sync_complete),
                    # leaving the FE activity monitor stuck in
                    # "syncing" until — and unless — the reclaimer
                    # worker eventually fires its own terminal. On a
                    # double-failure that never came. The DB state
                    # update is the only thing we MUST skip when we
                    # no longer own the lease; the WS emit is
                    # idempotent on the FE (sync_complete just
                    # triggers an inbox refresh) and clears the user's
                    # spinner regardless.
                    logger.warning(
                        "sync job %s completed after losing its lease; skipping DB state update but emitting terminal WS",
                        job_id,
                    )
                    lease_intact = False
                else:
                    job.status = SYNC_JOB_STATUS_COMPLETED
                    job.completed_at = _now_iso()
                    job.lease_owner = None
                    job.lease_expires_at = None
                    job.backoff_until = None
                    job.last_error_code = None
                    session.flush()

        emit_sync_progress(account_id, "success")
        emit_to_account(
            "sync_complete",
            {
                "new_emails": int(synced_count),
                "duration_ms": 0,
                "accounts": [{"account_id": account_id, "folder": folder}],
                "job_id": job_id,
                "folder": folder,
                "lease_reclaimed": not lease_intact,
            },
            account_id,
        )
        logger.info(
            "[SYNC-JOB] complete job_id=%s account_id=%s folder=%s source=%s "
            "synced=%s lease_intact=%s ms=%s",
            job_id,
            account_id,
            folder,
            job_snapshot.get("source"),
            int(synced_count),
            lease_intact,
            int((time.perf_counter() - job_t0) * 1000),
        )
    except Exception as exc:
        logger.warning("sync job %s failed: %s", job_id, exc)
        with get_db_session() as session:
            job = session.scalars(
                select(SyncJob)
                .where(SyncJob.id == job_id)
                .limit(1)
                .with_for_update()
            ).first()
            if job:
                if job.lease_owner != worker_lease_owner:
                    # Audit F-05 (2026-05-17 deep-audit): the previous
                    # ``return`` here skipped the WS error emit at the
                    # bottom of the except block, leaving the FE
                    # spinner stuck "syncing" forever when both the
                    # original worker AND the reclaimer failed. Skip
                    # only the DB update; always emit a terminal WS.
                    logger.warning(
                        "sync job %s failed after losing its lease; skipping DB state update but emitting terminal WS",
                        job_id,
                    )
                else:
                    error_code = type(exc).__name__[:64]
                    job.lease_owner = None
                    job.lease_expires_at = None
                    job.error_summary = str(exc)[:1000]
                    job.last_error_code = error_code
                    if job.attempt_count < _MAX_ATTEMPTS:
                        job.status = SYNC_JOB_STATUS_RETRY_WAITING
                        job.backoff_until = _next_backoff_until(job.attempt_count, _now_utc())
                        job.completed_at = None
                    else:
                        job.status = SYNC_JOB_STATUS_FAILED
                        job.completed_at = _now_iso()
                        job.backoff_until = None
                    session.flush()
        try:
            from app.api.websocket import emit_sync_error

            emit_sync_error(account_id, str(exc)[:300])
        except Exception as emit_exc:
            logger.debug("sync job error WS emit failed: %s", emit_exc)
    finally:
        try:
            _dispatch_ready_sync_jobs()
        except Exception as dispatch_exc:
            # B-04 (audit 2026-06-11): a swallowed dispatch failure stalls every
            # queued/retry_waiting job until the next external event — warn.
            logger.warning("sync job follow-up dispatch failed: %s", dispatch_exc)


# ── Periodic dispatch ticker (B-04, audit 2026-06-11) ───────────────────────
# Dispatch used to be purely event-driven (enqueue + worker completion), so a
# job parked in retry_waiting / quota-defer was never re-dispatched on a quiet
# system once its backoff_until elapsed. This daemon thread sweeps the ready
# candidates on a fixed interval (pattern GmailWatchScheduler: daemon thread +
# stop event, started once from run_api.py at boot).

_TICKER_INTERVAL_SECONDS = 60

_ticker_lock = threading.Lock()
_ticker_thread: threading.Thread | None = None
_ticker_stop = threading.Event()


def _run_sync_job_ticker(interval_seconds: float) -> None:
    # Wait first: the initial delay lets boot (DB init, migrations) finish
    # before the first sweep.
    while not _ticker_stop.wait(timeout=interval_seconds):
        try:
            _dispatch_ready_sync_jobs()
        except Exception as exc:
            # DB not ready / transient failure: skip this tick, retry later.
            logger.warning("sync job ticker dispatch failed: %s", exc)


def start_sync_job_ticker(interval_seconds: float = _TICKER_INTERVAL_SECONDS) -> None:
    """Start the periodic dispatch sweep. Idempotent — one thread per process."""
    global _ticker_thread
    with _ticker_lock:
        if _ticker_thread is not None and _ticker_thread.is_alive():
            return
        _ticker_stop.clear()
        _ticker_thread = threading.Thread(
            target=_run_sync_job_ticker,
            args=(interval_seconds,),
            daemon=True,
            name="SyncJobTicker",
        )
        _ticker_thread.start()
    logger.info("sync job ticker started (interval %ss)", interval_seconds)


def stop_sync_job_ticker() -> None:
    global _ticker_thread
    with _ticker_lock:
        _ticker_stop.set()
        if _ticker_thread is not None:
            _ticker_thread.join(timeout=5)
            _ticker_thread = None
