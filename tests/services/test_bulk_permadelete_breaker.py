# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Reproduction tests for the auto permanent-delete failure cluster
(audit 2026-06-23).

Each test maps to a numbered bug from the adversarial pass:

- #1  worker cascade-fails an insufficient-scope `delete_forever` job in a
      single provider call instead of firing one 403 per item (the storm).
- #2  the scheduler has a circuit breaker so it stops re-enqueuing a doomed
      `delete_forever` job daily, and the worker persists the flag that
      drives it (self-healing on a later success).
- #4  `run_tick_once` actually calls `vacuum_old_terminal_jobs`.
- #6  enumeration logs when it truncates at `ENUMERATION_LIMIT`.
- #11 the per-account spacing is interruptible and beats per account.

Isolation contract (cf. memory `pytest_live_bulkjob_leak`): these tests
use the in-memory `session`/`sample_account` fixtures and NEVER call
`enqueue_job`/`init_worker`, which would push real jobs into the live
encrypted desktop DB.
"""
from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.db.models.bulk_job import (
    ITEM_STATE_FAILED,
    JOB_SOURCE_AUTO_DELETION,
    JOB_STATUS_FAILED,
    JOB_TYPE_DELETE_FOREVER,
)
from app.interfaces.email_provider import InsufficientScopeError
from app.services.bulk_jobs import scheduler as sched
from app.services.bulk_jobs import worker as w
from app.services.bulk_jobs.repository import BulkJobRepository, NewBulkJob
from app.services.bulk_jobs.worker import _classify_provider_error


# ── #1 — classifier flags scope errors fatal-for-job ───────────────────
def test_insufficient_scope_is_fatal_for_job() -> None:
    outcome = _classify_provider_error(
        InsufficientScopeError(
            "messages.delete needs full scope",
            required_scope="https://mail.google.com/",
        )
    )
    assert outcome.fatal_for_job is True
    # Still NOT auth_failed — reconnecting wouldn't change requested scopes.
    assert outcome.auth_failed is False
    assert outcome.transient is False


# ── #1 + #2 + #3 + #8 — cascade end-to-end on a real repo ──────────────
def test_scope_failure_cascades_without_storm(
    session, sample_account, monkeypatch
) -> None:
    repo = BulkJobRepository(session)
    job_id = repo.create_job(
        NewBulkJob(
            user_id=None,
            account_id=sample_account.id,
            job_type=JOB_TYPE_DELETE_FOREVER,
            target_msg_ids=["a", "b", "c"],
            source=JOB_SOURCE_AUTO_DELETION,
            params={"reason": "trash_30d"},
        )
    )
    session.commit()

    claimed = repo.claim_next_pending_for_account(sample_account.id)
    session.commit()
    assert claimed is not None

    provider = MagicMock()
    provider.permanently_delete.side_effect = InsufficientScopeError(
        "messages.delete needs full scope",
        required_scope="https://mail.google.com/",
    )

    queue = w._AccountQueue(account_id=sample_account.id, worker=MagicMock())
    queue._ensure_provider = MagicMock(return_value=provider)
    bucket = MagicMock()
    bucket.acquire.return_value = True
    queue._ensure_bucket = MagicMock(return_value=bucket)

    avail_calls: list[tuple[int, bool]] = []
    monkeypatch.setattr(
        w,
        "_set_permanent_delete_availability",
        lambda aid, *, available: avail_calls.append((aid, available)),
    )

    queue._process_claimed(repo, session, claimed)
    session.commit()

    # #1: ONE provider call total — the 2 siblings cascade-failed in SQL,
    # they were never dispatched. (Pre-fix: 3 calls = 3 separate 403s.)
    assert provider.permanently_delete.call_count == 1
    # All three items end failed.
    failed = repo.list_items(job_id, state=ITEM_STATE_FAILED, limit=100)
    assert len(failed) == 3
    snap = repo.get_job(job_id)
    # #8: the reason is surfaced on the parent job, not buried in item rows.
    assert snap["error_summary"] and "scope" in snap["error_summary"].lower()
    # #3: failures + zero successes ⇒ FAILED (red), never COMPLETED (green).
    assert snap["status"] == JOB_STATUS_FAILED
    # #2: the scheduler breaker flag was persisted for this account.
    assert (sample_account.id, False) in avail_calls


# ── #2 — worker persistence helper: set / clear / idempotent ───────────
def test_set_permanent_delete_availability(monkeypatch) -> None:
    store: dict = {"overrides": {}, "saves": 0}

    def _load(aid):
        return dict(store["overrides"])

    def _save(ov, aid):
        store["overrides"] = dict(ov)
        store["saves"] += 1
        return True

    monkeypatch.setattr(
        "app.api.settings._load_account_settings_overrides", _load
    )
    monkeypatch.setattr("app.api.settings._save_account_settings", _save)

    w._set_permanent_delete_availability(7, available=False)
    assert store["overrides"].get("_permanent_delete_unavailable") is True
    assert store["saves"] == 1
    # Idempotent: a second "unavailable" doesn't re-write.
    w._set_permanent_delete_availability(7, available=False)
    assert store["saves"] == 1
    # Self-heal: a later success clears the flag.
    w._set_permanent_delete_availability(7, available=True)
    assert "_permanent_delete_unavailable" not in store["overrides"]
    assert store["saves"] == 2
    # Idempotent clear.
    w._set_permanent_delete_availability(7, available=True)
    assert store["saves"] == 2
    # Guard: a non-positive account id is a no-op (never poison a store).
    w._set_permanent_delete_availability(0, available=False)
    assert store["saves"] == 2


# ── #2 / #5 — scheduler gate reads the breaker flag ────────────────────
def test_permanent_delete_gate() -> None:
    assert sched._permanent_delete_available({}) is True
    assert sched._permanent_delete_available({"auto_empty_trash_30d": True}) is True
    assert (
        sched._permanent_delete_available({"_permanent_delete_unavailable": True})
        is False
    )


# ── #6 — enumeration warns when it truncates at the cap ────────────────
def test_enumeration_logs_when_capped(monkeypatch, caplog) -> None:
    monkeypatch.setattr(
        "app.api.routes_helpers._resolve_folder_for_provider",
        lambda provider, kind: "TRASH",
    )
    # Provider returns a full page (= the cap) of recent messages — none are
    # eligible (recent), but the truncation warning fires regardless.
    msgs = [
        SimpleNamespace(id=f"m{i}", date="2099-01-01T00:00:00Z")
        for i in range(sched.ENUMERATION_LIMIT)
    ]
    provider = MagicMock()
    provider.get_messages.return_value = msgs

    with caplog.at_level(logging.WARNING, logger="app.services.bulk_jobs.scheduler"):
        out = sched._enumerate_old_in_folder(provider, "trash", 30)

    assert out == []  # all too recent
    assert "hit cap" in caplog.text


def test_enumeration_no_warning_below_cap(monkeypatch, caplog) -> None:
    monkeypatch.setattr(
        "app.api.routes_helpers._resolve_folder_for_provider",
        lambda provider, kind: "TRASH",
    )
    provider = MagicMock()
    provider.get_messages.return_value = [
        SimpleNamespace(id="m1", date="2099-01-01T00:00:00Z")
    ]
    with caplog.at_level(logging.WARNING, logger="app.services.bulk_jobs.scheduler"):
        sched._enumerate_old_in_folder(provider, "trash", 30)
    assert "hit cap" not in caplog.text


# ── #4 — the daily tick prunes old terminal jobs ───────────────────────
def _patch_tick_db(monkeypatch, session, accounts):
    @contextmanager
    def _fake_db():
        yield session

    monkeypatch.setattr("app.db.database.get_db_session", _fake_db)

    class _AcctRepo:
        def __init__(self, _s):
            pass

        def get_active_accounts(self):
            return accounts

    monkeypatch.setattr(
        "app.db.repositories.account_repository.AccountRepository", _AcctRepo
    )


def test_run_tick_runs_vacuum(session, monkeypatch) -> None:
    _patch_tick_db(monkeypatch, session, accounts=[])
    calls: list[int] = []
    monkeypatch.setattr(
        BulkJobRepository,
        "vacuum_old_terminal_jobs",
        lambda self, older_than_days=30: (calls.append(older_than_days) or 0),
    )
    sched.run_tick_once()
    assert calls == [30]


# ── #11 — per-account spacing is interruptible + heartbeats ────────────
def test_run_tick_interruptible_and_heartbeats(session, monkeypatch) -> None:
    accounts = [
        SimpleNamespace(id=i, email=f"a{i}@x.com", user_id=None)
        for i in (1, 2, 3)
    ]
    _patch_tick_db(monkeypatch, session, accounts=accounts)

    processed: list[int] = []
    monkeypatch.setattr(
        sched, "_process_account", lambda row, stats: processed.append(row.id)
    )
    beats: list[str] = []
    monkeypatch.setattr(
        "app.services.scheduler_heartbeat.record_heartbeat",
        lambda *a, **k: beats.append(k.get("status", "ok")),
    )
    monkeypatch.setattr(
        BulkJobRepository,
        "vacuum_old_terminal_jobs",
        lambda self, older_than_days=30: 0,
    )

    ev = threading.Event()
    ev.set()  # already stopped → must break after account #1, not sleep 30s

    sched.run_tick_once(stop_event=ev)

    # Interruptible: only the first account ran; the wait() saw the set
    # event and broke instead of blocking on a bare time.sleep(30).
    assert processed == [1]
    # Daemon mode beats per account so a long tick isn't flagged dead.
    assert beats and beats[0] == "ok"
