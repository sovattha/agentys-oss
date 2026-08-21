# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Heartbeat helper for background schedulers — issue #577 item 4.

Each scheduler calls :func:`record_heartbeat` at the START of its
loop body. The endpoint :func:`/api/_internal/scheduler-health`
queries :func:`get_stale_heartbeats` to detect a thread that has
silently died (no more beats > expected_interval_seconds).

Wired schedulers (Phase A + Phase B, issue #577 item 4):

* ``scheduled_email_scheduler`` — :mod:`app.services.scheduled_email_scheduler`
* ``recap_scheduler`` — :mod:`app.services.recap_scheduler`
* ``bulk_jobs_scheduler`` — :mod:`app.services.bulk_jobs.scheduler`
* ``batch_worker`` — :mod:`app.batch_queue`
* ``learning_refresh_scheduler`` — :mod:`app.learning_refresh`

Thread-safety: SQLAlchemy session per call (short-lived). UPSERT via
``session.merge`` so concurrent ticks of the same scheduler don't
duplicate rows.

CRITICAL contract: :func:`record_heartbeat` MUST NOT raise. The
heartbeat exists to detect crashes — if it crashes the scheduler,
it becomes the very thing it was meant to detect. Any exception is
swallowed and logged at warning.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List

from app.db.database import get_db_session

logger = logging.getLogger(__name__)


def record_heartbeat(
    name: str,
    *,
    status: str = "ok",
    expected_interval_seconds: int,
) -> None:
    """Stamp a heartbeat for ``name``. Idempotent UPSERT.

    Args:
        name: Stable scheduler identifier (e.g.
            ``"scheduled_email_scheduler"``). Becomes the row primary
            key.
        status: ``"ok"`` (default), ``"error"``, or any free-form
            label. Surfaced as-is by the health endpoint.
        expected_interval_seconds: Tolerance window. Pass the
            scheduler's own ``check_interval × 2`` so a single missed
            tick does not alert.

    Never raises — DB unavailability, schema mismatch, every error is
    logged and swallowed.
    """
    try:
        from app.db.models.scheduler_heartbeat import SchedulerHeartbeat

        with get_db_session() as session:
            row = SchedulerHeartbeat(
                name=name,
                last_run_at=datetime.now(timezone.utc),
                last_status=status,
                expected_interval_seconds=int(expected_interval_seconds),
            )
            session.merge(row)
    except Exception as exc:
        logger.warning(
            "scheduler_heartbeat: record failed for %s (%s) — swallowed "
            "to keep the scheduler running",
            name,
            type(exc).__name__,
        )


def get_all_heartbeats() -> List["SchedulerHeartbeat"]:  # noqa: F821
    """Snapshot every heartbeat row. Empty list when the table is
    fresh (e.g. brand-new deploy with no scheduler having beaten yet).
    """
    from app.db.models.scheduler_heartbeat import SchedulerHeartbeat

    with get_db_session() as session:
        rows = session.query(SchedulerHeartbeat).all()
        # Detach so the caller can read attributes after the session
        # closes — the endpoint uses these post-iteration.
        for row in rows:
            session.expunge(row)
        return rows


def is_stale(row: "SchedulerHeartbeat", now: datetime | None = None) -> bool:  # noqa: F821
    """True iff this heartbeat is older than its declared interval.

    ``last_run_at`` is stored naive UTC by SQLite. We add tzinfo on
    read for arithmetic against an aware ``now``.
    """
    now = now or datetime.now(timezone.utc)
    last_run = row.last_run_at
    if last_run.tzinfo is None:
        last_run = last_run.replace(tzinfo=timezone.utc)
    elapsed = (now - last_run).total_seconds()
    return elapsed > row.expected_interval_seconds


def get_stale_heartbeats() -> List["SchedulerHeartbeat"]:  # noqa: F821
    """Subset of :func:`get_all_heartbeats` that breach their interval."""
    now = datetime.now(timezone.utc)
    return [row for row in get_all_heartbeats() if is_stale(row, now)]
