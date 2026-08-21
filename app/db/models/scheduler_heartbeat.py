# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Heartbeat row for background schedulers.

Issue #577 item 4. The 5 schedulers (learning, recap, scheduled_email,
batch_worker, bulk_jobs) silently swallow exceptions in their loop —
when a thread dies, the app keeps responding 200 but the scheduled
work is lost, and the user only finds out when an expected follow-up
never goes out.

Each scheduler stamps this row at the start of its tick. The
``/api/_internal/scheduler-health`` endpoint flags a row as stale
when ``now - last_run_at > expected_interval_seconds``. The sentinel
in nightly.yml polls daily and opens an auto-sentinelle issue.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class SchedulerHeartbeat(Base):
    """Latest heartbeat for each background scheduler.

    Primary key is the scheduler name (string) — the scheduler
    identifies itself, no auto-increment id needed. UPSERT semantics
    via ``session.merge`` in :func:`app.services.scheduler_heartbeat
    .record_heartbeat`.
    """

    __tablename__ = "scheduler_heartbeats"

    # Scheduler identifier, e.g. "scheduled_email_scheduler". Stable
    # across restarts; the scheduler that picks this name owns the row.
    name: Mapped[str] = mapped_column(String(128), primary_key=True)

    # Wall-clock UTC at the start of the most recent tick.
    last_run_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # "ok" | "error" | "warmup" — free string so future Phase B can add
    # statuses without schema migration. The endpoint surfaces this as-is.
    last_status: Mapped[str] = mapped_column(String(32), nullable=False)

    # Tolerance window. Caller passes the scheduler's own
    # check_interval × 2 (or larger) so a single missed tick doesn't
    # alert. Stored in seconds for unambiguous arithmetic in the
    # staleness check.
    expected_interval_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<SchedulerHeartbeat(name='{self.name}', "
            f"last_run_at={self.last_run_at!r}, "
            f"last_status='{self.last_status}', "
            f"expected_interval_seconds={self.expected_interval_seconds})>"
        )
