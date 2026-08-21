# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""L2 tests for `BulkJobRepository`.

Use the project's `session` fixture (tempfile SQLite, all tables created
via Base.metadata.create_all in tests/db/conftest.py) to exercise the
race-free claim, retry semantics, and recovery paths.

These tests intentionally do NOT exercise the full `UPDATE … RETURNING`
of the worker hot path on SQLCipher — the upstream `tests/db/conftest`
fixture uses plain SQLite. SQLCipher and SQLite share the same SQL
grammar, so behavior is preserved; the SQLCipher-specific concern
(`PRAGMA key`) is covered elsewhere (`tests/db/test_encryption.py`).
"""
from __future__ import annotations

import time

import pytest

from app.db.models import Account
from app.db.models.bulk_job import (
    JOB_SOURCE_MANUAL,
    JOB_STATUS_CANCELLED,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    JOB_STATUS_PAUSED,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    JOB_TYPE_ARCHIVE,
)
from app.services.bulk_jobs.repository import (
    BulkJobRepository,
    NewBulkJob,
)


# ── fixtures ───────────────────────────────────────────────────────────
@pytest.fixture
def repo(session) -> BulkJobRepository:
    return BulkJobRepository(session)


@pytest.fixture
def account_b(session) -> Account:
    """A second sample account so we can test cross-account isolation."""
    a = Account(
        email="second@example.com",
        provider="outlook",
        display_name="Second User",
        is_active=True,
    )
    session.add(a)
    session.commit()
    return a


def _archive_job(account_id: int, n: int, *, user_id: int | None = 1) -> NewBulkJob:
    return NewBulkJob(
        user_id=user_id,
        account_id=account_id,
        job_type=JOB_TYPE_ARCHIVE,
        target_msg_ids=[f"msg{i:04d}" for i in range(n)],
        source=JOB_SOURCE_MANUAL,
    )


# ── creation ───────────────────────────────────────────────────────────
def test_create_job_persists_job_and_items(
    session, repo, sample_account
) -> None:
    job_id = repo.create_job(_archive_job(sample_account.id, 5))
    session.commit()

    job = repo.get_job(job_id)
    assert job is not None
    assert job["status"] == JOB_STATUS_QUEUED
    assert job["target_total"] == 5
    assert job["account_id"] == sample_account.id
    assert job["user_id"] == 1
    assert job["job_type"] == JOB_TYPE_ARCHIVE

    items = repo.list_items(job_id, state="pending", limit=100)
    assert len(items) == 5
    assert {i["provider_msg_id"] for i in items} == {f"msg{i:04d}" for i in range(5)}


def test_create_job_dedups_target_ids(
    session, repo, sample_account
) -> None:
    """Duplicates within a single job are silently de-duped — the same
    message isn't worth processing twice in a row, and it would also
    waste an item-row slot."""
    spec = NewBulkJob(
        user_id=1,
        account_id=sample_account.id,
        job_type=JOB_TYPE_ARCHIVE,
        target_msg_ids=["dup", "dup", "dup", "other"],
    )
    job_id = repo.create_job(spec)
    session.commit()
    items = repo.list_items(job_id, state="pending", limit=100)
    assert len(items) == 2
    assert repo.get_job(job_id)["target_total"] == 2


def test_create_job_rejects_empty_target(repo, sample_account) -> None:
    with pytest.raises(ValueError):
        repo.create_job(_archive_job(sample_account.id, 0))


def test_create_job_rejects_unknown_type(repo, sample_account) -> None:
    spec = NewBulkJob(
        user_id=1,
        account_id=sample_account.id,
        job_type="not_a_real_op",
        target_msg_ids=["m1"],
    )
    with pytest.raises(ValueError):
        repo.create_job(spec)


# ── claim_next_pending_for_account ─────────────────────────────────────
def test_claim_promotes_queued_job_to_running(
    session, repo, sample_account
) -> None:
    job_id = repo.create_job(_archive_job(sample_account.id, 2))
    session.commit()
    assert repo.get_job_status(job_id) == JOB_STATUS_QUEUED

    claimed = repo.claim_next_pending_for_account(sample_account.id)
    session.commit()

    assert claimed is not None
    assert claimed.account_id == sample_account.id
    assert claimed.attempts == 0
    assert repo.get_job_status(job_id) == JOB_STATUS_RUNNING


def test_claim_returns_none_when_no_pending(repo, sample_account) -> None:
    assert repo.claim_next_pending_for_account(sample_account.id) is None


def test_claim_is_fifo_within_a_job(session, repo, sample_account) -> None:
    repo.create_job(_archive_job(sample_account.id, 3))
    session.commit()
    seen: list[str] = []
    for _ in range(3):
        c = repo.claim_next_pending_for_account(sample_account.id)
        session.commit()
        assert c is not None
        seen.append(c.provider_msg_id)
    assert seen == ["msg0000", "msg0001", "msg0002"]


def test_claim_is_fifo_across_jobs_for_same_account(
    session, repo, sample_account
) -> None:
    """Older job's items drain first."""
    j1 = repo.create_job(_archive_job(sample_account.id, 1))
    session.commit()
    # Tiny sleep so created_at differs lexicographically.
    time.sleep(0.001)
    repo.create_job(_archive_job(sample_account.id, 1))
    session.commit()

    first = repo.claim_next_pending_for_account(sample_account.id)
    session.commit()
    assert first is not None
    assert first.job_id == j1


def test_claim_isolates_accounts(
    session, repo, sample_account, account_b
) -> None:
    """Two accounts, two jobs — claiming for A must not touch B."""
    job_a = repo.create_job(_archive_job(sample_account.id, 1))
    job_b = repo.create_job(_archive_job(account_b.id, 1))
    session.commit()

    a = repo.claim_next_pending_for_account(sample_account.id)
    session.commit()
    assert a is not None and a.job_id == job_a

    b = repo.claim_next_pending_for_account(account_b.id)
    session.commit()
    assert b is not None and b.job_id == job_b


def test_claim_does_not_double_pop_same_item(
    session, repo, sample_account
) -> None:
    """The atomic UPDATE … RETURNING must hand the same row to only one caller."""
    repo.create_job(_archive_job(sample_account.id, 3))
    session.commit()

    a = repo.claim_next_pending_for_account(sample_account.id)
    b = repo.claim_next_pending_for_account(sample_account.id)
    c = repo.claim_next_pending_for_account(sample_account.id)
    d = repo.claim_next_pending_for_account(sample_account.id)
    session.commit()

    ids = {x.item_id for x in (a, b, c) if x}
    assert len(ids) == 3
    assert d is None


# ── reporting + finalize ───────────────────────────────────────────────
def test_mark_succeeded_bumps_counter(
    session, repo, sample_account
) -> None:
    job_id = repo.create_job(_archive_job(sample_account.id, 2))
    session.commit()
    c = repo.claim_next_pending_for_account(sample_account.id)
    session.commit()
    assert c is not None

    repo.mark_item_succeeded(c.item_id, c.job_id)
    session.commit()
    assert repo.get_job(job_id)["succeeded_count"] == 1


def test_finalize_completes_when_drained(
    session, repo, sample_account
) -> None:
    job_id = repo.create_job(_archive_job(sample_account.id, 2))
    session.commit()
    for _ in range(2):
        c = repo.claim_next_pending_for_account(sample_account.id)
        session.commit()
        repo.mark_item_succeeded(c.item_id, c.job_id)
        session.commit()

    new_status = repo.finalize_job_if_drained(job_id)
    session.commit()
    assert new_status == JOB_STATUS_COMPLETED
    assert repo.get_job(job_id)["completed_at"] is not None


def test_finalize_fails_when_every_item_failed(
    session, repo, sample_account
) -> None:
    job_id = repo.create_job(_archive_job(sample_account.id, 2))
    session.commit()
    for _ in range(2):
        c = repo.claim_next_pending_for_account(sample_account.id)
        session.commit()
        repo.mark_item_failed(c.item_id, c.job_id, "boom")
        session.commit()
    assert repo.finalize_job_if_drained(job_id) == JOB_STATUS_FAILED


def test_finalize_idempotent_on_terminal_job(
    session, repo, sample_account
) -> None:
    """Calling finalize on an already-terminal job stays a no-op."""
    job_id = repo.create_job(_archive_job(sample_account.id, 1))
    session.commit()
    c = repo.claim_next_pending_for_account(sample_account.id)
    session.commit()
    repo.mark_item_succeeded(c.item_id, c.job_id)
    session.commit()

    first = repo.finalize_job_if_drained(job_id)
    session.commit()
    second = repo.finalize_job_if_drained(job_id)
    session.commit()
    assert first == JOB_STATUS_COMPLETED
    assert second == JOB_STATUS_COMPLETED  # already terminal


# ── pause / cancel / retry ─────────────────────────────────────────────
def test_pause_then_resume(session, repo, sample_account) -> None:
    job_id = repo.create_job(_archive_job(sample_account.id, 1))
    session.commit()
    # Pause from queued is allowed.
    assert repo.request_pause(job_id) is True
    session.commit()
    assert repo.get_job_status(job_id) == JOB_STATUS_PAUSED
    assert repo.request_resume(job_id) is True
    session.commit()
    assert repo.get_job_status(job_id) == JOB_STATUS_QUEUED


def test_pause_rejects_terminal(session, repo, sample_account) -> None:
    job_id = repo.create_job(_archive_job(sample_account.id, 1))
    session.commit()
    c = repo.claim_next_pending_for_account(sample_account.id)
    session.commit()
    repo.mark_item_succeeded(c.item_id, c.job_id)
    repo.finalize_job_if_drained(job_id)
    session.commit()
    assert repo.request_pause(job_id) is False


def test_cancel_skips_remaining_pending_items(
    session, repo, sample_account
) -> None:
    job_id = repo.create_job(_archive_job(sample_account.id, 5))
    session.commit()

    # Process one item to running state.
    c = repo.claim_next_pending_for_account(sample_account.id)
    session.commit()
    repo.mark_item_succeeded(c.item_id, c.job_id)
    session.commit()

    assert repo.request_cancel(job_id) is True
    session.commit()
    snap = repo.get_job(job_id)
    assert snap["status"] == JOB_STATUS_CANCELLED
    assert snap["succeeded_count"] == 1
    # The 4 still-pending items must have moved to skipped.
    assert snap["skipped_count"] == 4
    assert (
        len(repo.list_items(job_id, state="pending", limit=100)) == 0
    )


def test_retry_failed_requeues_only_failed_items(
    session, repo, sample_account
) -> None:
    job_id = repo.create_job(_archive_job(sample_account.id, 3))
    session.commit()

    # Fail two, succeed one.
    claims = []
    for _ in range(3):
        c = repo.claim_next_pending_for_account(sample_account.id)
        session.commit()
        claims.append(c)
    repo.mark_item_failed(claims[0].item_id, job_id, "x")
    repo.mark_item_failed(claims[1].item_id, job_id, "y")
    repo.mark_item_succeeded(claims[2].item_id, job_id)
    session.commit()
    repo.finalize_job_if_drained(job_id)
    session.commit()

    requeued = repo.retry_failed(job_id)
    session.commit()

    assert requeued == 2
    snap = repo.get_job(job_id)
    assert snap["status"] == JOB_STATUS_QUEUED
    assert snap["failed_count"] == 0
    assert snap["completed_at"] is None
    assert len(repo.list_items(job_id, state="pending", limit=100)) == 2


# ── recovery / vacuum ──────────────────────────────────────────────────
def test_recover_orphaned_in_progress_resets_state(
    session, repo, sample_account
) -> None:
    """Items left `in_progress` after a worker crash are reclaimable."""
    repo.create_job(_archive_job(sample_account.id, 2))
    session.commit()
    c = repo.claim_next_pending_for_account(sample_account.id)
    session.commit()
    assert c is not None

    # Simulate crash mid-process — we never call mark_*. Item is in_progress.
    moved = repo.recover_orphaned_in_progress()
    session.commit()
    assert moved == 1
    # Re-claim should pick it up again.
    again = repo.claim_next_pending_for_account(sample_account.id)
    session.commit()
    assert again is not None and again.item_id == c.item_id


def test_fail_remaining_pending(session, repo, sample_account) -> None:
    job_id = repo.create_job(_archive_job(sample_account.id, 3))
    session.commit()
    flipped = repo.fail_remaining_pending(job_id, "auth dead")
    session.commit()
    assert flipped == 3
    snap = repo.get_job(job_id)
    assert snap["failed_count"] == 3
    assert snap["error_summary"] == "auth dead"


def test_vacuum_old_terminal_jobs(session, repo, sample_account) -> None:
    """Jobs older than `older_than_days` and terminal are deleted."""
    job_id = repo.create_job(_archive_job(sample_account.id, 1))
    session.commit()
    c = repo.claim_next_pending_for_account(sample_account.id)
    session.commit()
    repo.mark_item_succeeded(c.item_id, c.job_id)
    repo.finalize_job_if_drained(job_id)
    session.commit()

    # Backdate completed_at to 60 days ago to trigger the vacuum.
    from sqlalchemy import text
    session.execute(
        text(
            "UPDATE bulk_jobs SET completed_at = :ts, "
            "created_at = :ts WHERE id = :id"
        ),
        {"ts": "2025-01-01T00:00:00Z", "id": job_id},
    )
    session.commit()

    deleted = repo.vacuum_old_terminal_jobs(older_than_days=30)
    session.commit()
    assert deleted == 1
    assert repo.get_job(job_id) is None


# ── HTTP-side queries ──────────────────────────────────────────────────
def test_list_jobs_for_user_filters_by_user(
    session, repo, sample_account
) -> None:
    repo.create_job(_archive_job(sample_account.id, 1, user_id=1))
    repo.create_job(_archive_job(sample_account.id, 1, user_id=2))
    session.commit()
    user_1_jobs = repo.list_jobs_for_user(user_id=1)
    user_2_jobs = repo.list_jobs_for_user(user_id=2)
    loopback_jobs = repo.list_jobs_for_user(user_id=None)

    assert len(user_1_jobs) == 1 and user_1_jobs[0]["user_id"] == 1
    assert len(user_2_jobs) == 1 and user_2_jobs[0]["user_id"] == 2
    # Loopback (None) sees both.
    assert len(loopback_jobs) == 2


def test_get_job_returns_parsed_params(
    session, repo, sample_account
) -> None:
    spec = NewBulkJob(
        user_id=1,
        account_id=sample_account.id,
        job_type=JOB_TYPE_ARCHIVE,
        target_msg_ids=["m"],
        params={"label": "Important"},
    )
    job_id = repo.create_job(spec)
    session.commit()
    snap = repo.get_job(job_id)
    assert snap["params"] == {"label": "Important"}


# ── audit 2026-06-23: permanent-delete failure cluster ─────────────────
def test_finalize_fails_when_failures_and_skips_but_no_success(
    session, repo, sample_account
) -> None:
    """Bug #3: a doomed job where items 403-fail and 404-skip but NOTHING
    succeeds must be FAILED (red), not COMPLETED (green). The old rule
    (`failed_count == target_total`) marked this COMPLETED — silent
    failure."""
    job_id = repo.create_job(_archive_job(sample_account.id, 2))
    session.commit()
    c1 = repo.claim_next_pending_for_account(sample_account.id)
    session.commit()
    repo.mark_item_failed(c1.item_id, job_id, "403")
    session.commit()
    c2 = repo.claim_next_pending_for_account(sample_account.id)
    session.commit()
    repo.mark_item_skipped(c2.item_id, job_id, "404")
    session.commit()
    assert repo.finalize_job_if_drained(job_id) == JOB_STATUS_FAILED


def test_finalize_completes_on_partial_success(
    session, repo, sample_account
) -> None:
    """A run with at least one real success stays a partial COMPLETED so
    the user can retry just the failures."""
    job_id = repo.create_job(_archive_job(sample_account.id, 2))
    session.commit()
    c1 = repo.claim_next_pending_for_account(sample_account.id)
    session.commit()
    repo.mark_item_succeeded(c1.item_id, job_id)
    session.commit()
    c2 = repo.claim_next_pending_for_account(sample_account.id)
    session.commit()
    repo.mark_item_failed(c2.item_id, job_id, "x")
    session.commit()
    assert repo.finalize_job_if_drained(job_id) == JOB_STATUS_COMPLETED


def test_finalize_completes_when_all_skipped(
    session, repo, sample_account
) -> None:
    """Everything 404-skipped (already gone) is a clean COMPLETED, not a
    FAILED — there was nothing left to do."""
    job_id = repo.create_job(_archive_job(sample_account.id, 2))
    session.commit()
    for _ in range(2):
        c = repo.claim_next_pending_for_account(sample_account.id)
        session.commit()
        repo.mark_item_skipped(c.item_id, job_id, "404")
        session.commit()
    assert repo.finalize_job_if_drained(job_id) == JOB_STATUS_COMPLETED


def test_fail_remaining_stamps_error_summary_with_no_pending_siblings(
    session, repo, sample_account
) -> None:
    """Bug #8: on a single-item job the current item is already failed by
    the caller, so fail_remaining_pending flips 0 siblings — but it must
    still stamp error_summary so the UI shows *why* the job died."""
    job_id = repo.create_job(_archive_job(sample_account.id, 1))
    session.commit()
    c = repo.claim_next_pending_for_account(sample_account.id)
    session.commit()
    repo.mark_item_failed(c.item_id, job_id, "insufficient OAuth scope")
    session.commit()

    flipped = repo.fail_remaining_pending(
        job_id, "insufficient OAuth scope: messages.delete"
    )
    session.commit()
    assert flipped == 0
    assert repo.get_job(job_id)["error_summary"].startswith(
        "insufficient OAuth scope"
    )


def test_requeue_without_bump_does_not_spend_retry_budget(
    session, repo, sample_account
) -> None:
    """Bug #9: a throttle/pause requeue must not increment attempts, else a
    rate-limited item burns its retry budget before any real error."""
    repo.create_job(_archive_job(sample_account.id, 1))
    session.commit()
    c = repo.claim_next_pending_for_account(sample_account.id)
    session.commit()

    # Default behaviour still bumps (a real transient error).
    a1 = repo.requeue_item_for_retry(c.item_id, "boom")
    session.commit()
    assert a1 == 1

    c2 = repo.claim_next_pending_for_account(sample_account.id)
    session.commit()
    a2 = repo.requeue_item_for_retry(
        c2.item_id, "rate limited", bump_attempts=False
    )
    session.commit()
    assert a2 == 1  # unchanged — the throttle didn't cost a retry


def test_retry_failed_clears_stale_error_summary(
    session, repo, sample_account
) -> None:
    """Bug #10: retrying a job must clear the old error_summary, else a
    later-successful retry still shows the prior failure reason."""
    job_id = repo.create_job(_archive_job(sample_account.id, 1))
    session.commit()
    c = repo.claim_next_pending_for_account(sample_account.id)
    session.commit()
    repo.mark_item_failed(c.item_id, job_id, "boom")
    session.commit()
    repo.fail_remaining_pending(job_id, "structural failure")
    session.commit()
    assert repo.get_job(job_id)["error_summary"] is not None
    repo.finalize_job_if_drained(job_id)
    session.commit()

    repo.retry_failed(job_id)
    session.commit()
    assert repo.get_job(job_id)["error_summary"] is None


def test_delete_job_removes_terminal_job(
    session, repo, sample_account
) -> None:
    """Bug #7 (backend): a terminal job can be dismissed (deleted)."""
    job_id = repo.create_job(_archive_job(sample_account.id, 1))
    session.commit()
    repo.request_cancel(job_id)  # → cancelled (terminal)
    session.commit()
    assert repo.delete_job(job_id) is True
    assert repo.get_job(job_id) is None


def test_delete_job_refuses_active_job(
    session, repo, sample_account
) -> None:
    """Never orphan in-flight work: an active job can't be dismissed."""
    job_id = repo.create_job(_archive_job(sample_account.id, 1))
    session.commit()
    assert repo.delete_job(job_id) is False
    assert repo.get_job(job_id) is not None
