# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Integration tests for /api/bulk-jobs/* HTTP routes.

We avoid spinning up the full `create_app()` (encrypted DB engine,
schedulers, sync service) and instead build a minimal Flask app with
only the bulk-jobs blueprint mounted. The test session is injected by
patching `app.db.database.get_db_session` so the routes hit the same
tempfile DB as the repository tests.

Coverage focus:
  - `_ownership_violation` returns 404 (never 403, never the resource)
    when JWT user_id mismatches the job's user_id.
  - Tauri loopback (`get_auth_user_id() is None`) sees every job.
  - Status flips return the *new* job snapshot in one round-trip.
  - retry-failed bumps the count and re-queues failed items only.
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest
from flask import Flask

from app.db.models.bulk_job import (
    JOB_SOURCE_MANUAL,
    JOB_TYPE_ARCHIVE,
)
from app.services.bulk_jobs.repository import BulkJobRepository, NewBulkJob


# ── Fixtures ───────────────────────────────────────────────────────────
@pytest.fixture
def app(session, sample_account, monkeypatch):
    """Minimal Flask app with the bulk-jobs blueprint mounted.

    We import `routes_bulk_jobs` so its `@api_bp.route` decorators run,
    then attach `api_bp` to a fresh Flask app. The bulk-jobs handlers
    use `get_db_session()` from `app.db.database` — we monkeypatch that
    to yield the test session so writes from the route end up in the
    same tempfile DB the fixtures have already populated.
    """
    from app.api.routes_helpers import api_bp
    from app.api import routes_bulk_jobs  # noqa: F401 — registers routes

    @contextmanager
    def _fake_db_session():
        # Match `get_db_session`'s commit-on-success/rollback-on-error
        # semantics so the route's commits actually persist.
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise

    monkeypatch.setattr(
        "app.db.database.get_db_session", _fake_db_session
    )
    monkeypatch.setattr(
        "app.api.routes_bulk_jobs.get_db_session", _fake_db_session
    )

    app = Flask(__name__)
    app.config["TESTING"] = True
    # api_bp is already registered with /api prefix in production via
    # create_app; mirror that here.
    app.register_blueprint(api_bp, url_prefix="/api")
    yield app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def job_owned_by_user_1(session, sample_account) -> str:
    repo = BulkJobRepository(session)
    job_id = repo.create_job(
        NewBulkJob(
            user_id=1,
            account_id=sample_account.id,
            job_type=JOB_TYPE_ARCHIVE,
            target_msg_ids=["m1", "m2", "m3"],
            source=JOB_SOURCE_MANUAL,
        )
    )
    session.commit()
    return job_id


@pytest.fixture
def job_owned_by_user_2(session, sample_account) -> str:
    repo = BulkJobRepository(session)
    job_id = repo.create_job(
        NewBulkJob(
            user_id=2,
            account_id=sample_account.id,
            job_type=JOB_TYPE_ARCHIVE,
            target_msg_ids=["x1"],
            source=JOB_SOURCE_MANUAL,
        )
    )
    session.commit()
    return job_id


# ── Authentication helpers ─────────────────────────────────────────────
def _as_user(uid: int | None):
    """Return a context manager that pins `get_auth_user_id` to `uid`."""
    return patch(
        "app.api.routes_bulk_jobs.get_auth_user_id",
        return_value=uid,
    )


# ── GET /api/bulk-jobs ─────────────────────────────────────────────────
def test_list_filters_by_user_id(client, job_owned_by_user_1, job_owned_by_user_2):
    with _as_user(1):
        resp = client.get("/api/bulk-jobs")
    assert resp.status_code == 200
    body = resp.get_json()
    ids = {j["id"] for j in body["jobs"]}
    assert job_owned_by_user_1 in ids
    assert job_owned_by_user_2 not in ids


def test_list_in_loopback_sees_every_job(client, job_owned_by_user_1, job_owned_by_user_2):
    """Tauri desktop (`get_auth_user_id()` returns None) is single-tenant."""
    with _as_user(None):
        resp = client.get("/api/bulk-jobs")
    assert resp.status_code == 200
    body = resp.get_json()
    ids = {j["id"] for j in body["jobs"]}
    assert {job_owned_by_user_1, job_owned_by_user_2}.issubset(ids)


def test_list_rejects_invalid_status_filter(client):
    with _as_user(1):
        resp = client.get("/api/bulk-jobs?status=banana")
    assert resp.status_code == 400


def test_list_clamps_limit_to_max(client, sample_account, session):
    """Bogus huge `limit` is clamped, not 500-ed."""
    with _as_user(1):
        resp = client.get("/api/bulk-jobs?limit=99999")
    assert resp.status_code == 200


# ── GET /api/bulk-jobs/<id> ────────────────────────────────────────────
def test_get_returns_job(client, job_owned_by_user_1):
    with _as_user(1):
        resp = client.get(f"/api/bulk-jobs/{job_owned_by_user_1}")
    assert resp.status_code == 200
    assert resp.get_json()["job"]["id"] == job_owned_by_user_1


def test_get_404_when_not_owned(client, job_owned_by_user_2):
    """Cross-tenant access returns 404 (never 403, never the resource)."""
    with _as_user(1):
        resp = client.get(f"/api/bulk-jobs/{job_owned_by_user_2}")
    assert resp.status_code == 404


def test_get_404_when_missing(client):
    with _as_user(1):
        resp = client.get("/api/bulk-jobs/01ARZ3NDEKTSV4RRFFQ69G5FAVNOTREAL")
    assert resp.status_code == 404


# ── Status flips ───────────────────────────────────────────────────────
def test_pause_returns_paused_snapshot(client, job_owned_by_user_1):
    with _as_user(1):
        resp = client.post(f"/api/bulk-jobs/{job_owned_by_user_1}/pause")
    assert resp.status_code == 200
    assert resp.get_json()["job"]["status"] == "paused"


def test_pause_then_resume(client, job_owned_by_user_1):
    with _as_user(1):
        client.post(f"/api/bulk-jobs/{job_owned_by_user_1}/pause")
        resp = client.post(f"/api/bulk-jobs/{job_owned_by_user_1}/resume")
    assert resp.status_code == 200
    assert resp.get_json()["job"]["status"] == "queued"


def test_pause_409_when_already_paused(client, job_owned_by_user_1):
    with _as_user(1):
        client.post(f"/api/bulk-jobs/{job_owned_by_user_1}/pause")
        resp = client.post(f"/api/bulk-jobs/{job_owned_by_user_1}/pause")
    assert resp.status_code == 409


def test_cancel_marks_pending_items_as_skipped(
    client, session, job_owned_by_user_1
):
    with _as_user(1):
        resp = client.post(f"/api/bulk-jobs/{job_owned_by_user_1}/cancel")
    assert resp.status_code == 200
    job = resp.get_json()["job"]
    assert job["status"] == "cancelled"
    assert job["skipped_count"] == 3


def test_cancel_404_when_not_owned(client, job_owned_by_user_2):
    with _as_user(1):
        resp = client.post(f"/api/bulk-jobs/{job_owned_by_user_2}/cancel")
    assert resp.status_code == 404


# ── retry-failed ───────────────────────────────────────────────────────
def test_retry_failed_requeues_failed_items(
    client, session, sample_account
):
    """Setup: a job with 2 failed items and 1 succeeded. POST retry-failed
    should re-pending the 2 failures and reset job to queued."""
    repo = BulkJobRepository(session)
    job_id = repo.create_job(
        NewBulkJob(
            user_id=1,
            account_id=sample_account.id,
            job_type=JOB_TYPE_ARCHIVE,
            target_msg_ids=["a", "b", "c"],
            source=JOB_SOURCE_MANUAL,
        )
    )
    session.commit()
    # Drain into terminal state (2 failed, 1 succeeded).
    claimed = []
    for _ in range(3):
        c = repo.claim_next_pending_for_account(sample_account.id)
        session.commit()
        claimed.append(c)
    repo.mark_item_failed(claimed[0].item_id, job_id, "x")
    repo.mark_item_failed(claimed[1].item_id, job_id, "y")
    repo.mark_item_succeeded(claimed[2].item_id, job_id)
    session.commit()
    repo.finalize_job_if_drained(job_id)
    session.commit()

    with _as_user(1):
        resp = client.post(f"/api/bulk-jobs/{job_id}/retry-failed")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["requeued"] == 2
    assert body["job"]["status"] == "queued"
    assert body["job"]["failed_count"] == 0


# ── /items drilldown ───────────────────────────────────────────────────
def test_list_items_default_state_is_failed(
    client, session, sample_account
):
    repo = BulkJobRepository(session)
    job_id = repo.create_job(
        NewBulkJob(
            user_id=1,
            account_id=sample_account.id,
            job_type=JOB_TYPE_ARCHIVE,
            target_msg_ids=["a", "b"],
            source=JOB_SOURCE_MANUAL,
        )
    )
    session.commit()
    c = repo.claim_next_pending_for_account(sample_account.id)
    session.commit()
    repo.mark_item_failed(c.item_id, job_id, "boom")
    session.commit()

    with _as_user(1):
        resp = client.get(f"/api/bulk-jobs/{job_id}/items")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["state"] == "failed"
    assert len(body["items"]) == 1
    assert body["items"][0]["last_error"] == "boom"


def test_list_items_404_when_not_owned(client, job_owned_by_user_2):
    with _as_user(1):
        resp = client.get(f"/api/bulk-jobs/{job_owned_by_user_2}/items")
    assert resp.status_code == 404


# ── DELETE /api/bulk-jobs/<id> (dismiss) — audit 2026-06-23 #7 ──────────
def test_delete_terminal_job_dismisses_it(client, session, sample_account):
    repo = BulkJobRepository(session)
    job_id = repo.create_job(
        NewBulkJob(
            user_id=1,
            account_id=sample_account.id,
            job_type=JOB_TYPE_ARCHIVE,
            target_msg_ids=["m1"],
            source=JOB_SOURCE_MANUAL,
        )
    )
    session.commit()
    repo.request_cancel(job_id)  # → cancelled (terminal)
    session.commit()

    with _as_user(1):
        resp = client.delete(f"/api/bulk-jobs/{job_id}")
    assert resp.status_code == 200
    assert resp.get_json()["deleted"] is True
    assert repo.get_job(job_id) is None


def test_delete_active_job_409(client, job_owned_by_user_1):
    """A still-active job can't be dismissed (would orphan in-flight work)."""
    with _as_user(1):
        resp = client.delete(f"/api/bulk-jobs/{job_owned_by_user_1}")
    assert resp.status_code == 409


def test_delete_404_when_not_owned(client, job_owned_by_user_2):
    """Cross-tenant returns 404 (before any active-state check)."""
    with _as_user(1):
        resp = client.delete(f"/api/bulk-jobs/{job_owned_by_user_2}")
    assert resp.status_code == 404


def test_delete_404_when_missing(client):
    with _as_user(1):
        resp = client.delete("/api/bulk-jobs/01ARZ3NDEKTSV4RRFFQ69G5FAVNOTREAL")
    assert resp.status_code == 404
