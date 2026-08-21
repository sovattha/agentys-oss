# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""L2 tests for `BulkJobRepository.has_recent_job` and the auto-deletion
scheduler's idempotence guard.

The scheduler's enumeration paths talk to a live email provider, so we
don't try to integration-test the full daily tick here. Instead we
verify the load-bearing guard — `has_recent_job` — that prevents the
cron from enqueuing duplicate jobs across a backend restart or two
ticks colliding. That's the part codex flagged in §12 of the plan
("idempotence du scheduler").
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.db.models.bulk_job import (
    JOB_SOURCE_AUTO_DELETION,
    JOB_SOURCE_MANUAL,
    JOB_TYPE_DELETE_FOREVER,
)
from app.services.bulk_jobs.repository import (
    BulkJobRepository,
    NewBulkJob,
)


def _utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def repo(session) -> BulkJobRepository:
    return BulkJobRepository(session)


def _scheduler_job(account_id: int) -> NewBulkJob:
    return NewBulkJob(
        user_id=None,
        account_id=account_id,
        job_type=JOB_TYPE_DELETE_FOREVER,
        target_msg_ids=[f"trash{i}" for i in range(3)],
        source=JOB_SOURCE_AUTO_DELETION,
        params={"reason": "trash_30d"},
    )


def test_has_recent_job_detects_active_match(
    session, repo, sample_account
) -> None:
    """A queued auto-deletion job blocks a same-day re-enqueue."""
    repo.create_job(_scheduler_job(sample_account.id))
    session.commit()

    today = _utc_iso(datetime.now(timezone.utc).replace(hour=0, minute=0, second=0))
    assert repo.has_recent_job(
        account_id=sample_account.id,
        job_type=JOB_TYPE_DELETE_FOREVER,
        source=JOB_SOURCE_AUTO_DELETION,
        since_iso=today,
    ) is True


def test_has_recent_job_ignores_terminal_match(
    session, repo, sample_account
) -> None:
    """Yesterday's completed job must not block today's enqueue."""
    job_id = repo.create_job(_scheduler_job(sample_account.id))
    session.commit()
    # Drain it.
    c = repo.claim_next_pending_for_account(sample_account.id)
    session.commit()
    repo.mark_item_succeeded(c.item_id, c.job_id)
    session.commit()

    # Drain the remaining items.
    while True:
        item = repo.claim_next_pending_for_account(sample_account.id)
        if item is None:
            break
        repo.mark_item_succeeded(item.item_id, item.job_id)
    session.commit()
    repo.finalize_job_if_drained(job_id)
    session.commit()

    today = _utc_iso(datetime.now(timezone.utc))
    # Already-completed → not counted as "recent active".
    assert repo.has_recent_job(
        account_id=sample_account.id,
        job_type=JOB_TYPE_DELETE_FOREVER,
        source=JOB_SOURCE_AUTO_DELETION,
        since_iso=today,
    ) is False


def test_has_recent_job_filters_by_source(session, repo, sample_account) -> None:
    """A *manual* archive job in flight must not block an *auto-deletion*
    delete-forever enqueue (different source)."""
    spec = NewBulkJob(
        user_id=1,
        account_id=sample_account.id,
        job_type=JOB_TYPE_DELETE_FOREVER,
        target_msg_ids=["m1"],
        source=JOB_SOURCE_MANUAL,
    )
    repo.create_job(spec)
    session.commit()

    today = _utc_iso(datetime.now(timezone.utc).replace(hour=0, minute=0, second=0))
    assert repo.has_recent_job(
        account_id=sample_account.id,
        job_type=JOB_TYPE_DELETE_FOREVER,
        source=JOB_SOURCE_AUTO_DELETION,
        since_iso=today,
    ) is False


def test_has_recent_job_filters_by_account(
    session, repo, sample_account
) -> None:
    """Another account's auto-deletion job doesn't gate ours."""
    repo.create_job(_scheduler_job(sample_account.id))
    session.commit()

    today = _utc_iso(datetime.now(timezone.utc).replace(hour=0, minute=0, second=0))
    assert repo.has_recent_job(
        account_id=999,
        job_type=JOB_TYPE_DELETE_FOREVER,
        source=JOB_SOURCE_AUTO_DELETION,
        since_iso=today,
    ) is False


def test_has_recent_job_respects_since_window(
    session, repo, sample_account
) -> None:
    """A job older than `since_iso` doesn't count even if still active.

    This protects the cron from the case where a long-running job from
    yesterday's tick is still running at 04:00 — we'd want to enqueue
    today's tick anyway and let the worker drain both sequentially.
    The scheduler currently anchors `since_iso` at today's midnight,
    so this test pins that behavior.
    """
    job_id = repo.create_job(_scheduler_job(sample_account.id))
    session.commit()

    # Backdate the row to two days ago.
    from sqlalchemy import text
    two_days_ago = _utc_iso(datetime.now(timezone.utc) - timedelta(days=2))
    session.execute(
        text("UPDATE bulk_jobs SET created_at = :ts WHERE id = :id"),
        {"ts": two_days_ago, "id": job_id},
    )
    session.commit()

    today = _utc_iso(datetime.now(timezone.utc).replace(hour=0, minute=0, second=0))
    assert repo.has_recent_job(
        account_id=sample_account.id,
        job_type=JOB_TYPE_DELETE_FOREVER,
        source=JOB_SOURCE_AUTO_DELETION,
        since_iso=today,
    ) is False
