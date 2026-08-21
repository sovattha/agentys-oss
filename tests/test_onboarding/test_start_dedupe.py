# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Regression tests for OnboardingManager.start() dedupe.

Before this fix, the frontend firing 4 POSTs /api/onboarding/start in
rapid succession would spawn 4 parallel orchestrators (4× LLM cost,
racing file writes). These tests lock in the contract:

- Concurrent ``start()`` calls for the SAME account → 1 row created,
  N-1 calls return the same id with ``already_running: True``.
- Sequential ``start()`` after a previous run ``completed`` / ``failed``
  → a NEW row is created (retry works).
- Different accounts → independent (no cross-contamination).
"""

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models.base import Base
from app.db.models.onboarding_result import OnboardingResult
from app.db.repositories.onboarding_repository import OnboardingRepository
from app.onboarding import manager as manager_mod
from app.onboarding.manager import OnboardingManager


@pytest.fixture(autouse=True)
def _clean_heartbeats():
    manager_mod._LAST_HEARTBEAT.clear()
    yield
    manager_mod._LAST_HEARTBEAT.clear()


@pytest.fixture
def session_factory():
    """In-memory SQLite session factory with the onboarding_results table.

    Uses ``StaticPool`` + ``check_same_thread=False`` so the in-memory
    database is shared across test threads — otherwise each thread would
    get its own empty copy and the concurrency test couldn't observe the
    dedupe behaviour we're trying to lock in.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
        echo=False,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    yield Session
    engine.dispose()


@pytest.fixture
def manager(session_factory, monkeypatch):
    """OnboardingManager wired to an in-memory DB with the analysis thread
    targets neutered to no-ops.

    NOTE: we can't patch ``threading.Thread`` globally because the
    ``ThreadPoolExecutor`` used by the concurrency test itself relies on
    real threads. Instead we stub out the two target methods that a real
    thread would invoke (``_run_analysis`` / ``_wait_for_sync_then_run``)
    — the thread still starts, runs nothing, and exits cleanly.
    """
    mgr = OnboardingManager(session_factory=session_factory)
    monkeypatch.setattr(mgr, "_count_account_emails", lambda acc_id: 500)
    monkeypatch.setattr(mgr, "_run_analysis", lambda *a, **k: None)
    monkeypatch.setattr(mgr, "_wait_for_sync_then_run", lambda *a, **k: None)

    def _run_without_usage_context(*args, fn, **_kwargs):
        fn(*args)

    monkeypatch.setattr(mgr, "_run_with_usage_context", _run_without_usage_context)
    return mgr


class TestStartDedupe:
    """Core dedupe contract."""

    def test_single_start_creates_one_row(self, manager, session_factory):
        r = manager.start(account_id=1, user_email="a@x.com")
        assert r["already_running"] is False
        with session_factory() as s:
            rows = s.query(OnboardingResult).filter_by(account_id=1).all()
            assert len(rows) == 1
            assert rows[0].status == "pending"

    def test_second_call_while_pending_returns_same_id(self, manager, session_factory):
        r1 = manager.start(account_id=1, user_email="a@x.com")
        r2 = manager.start(account_id=1, user_email="a@x.com")
        assert r2["already_running"] is True
        assert r2["onboarding_id"] == r1["onboarding_id"]
        with session_factory() as s:
            assert s.query(OnboardingResult).filter_by(account_id=1).count() == 1

    def test_four_concurrent_calls_create_one_row(self, manager, session_factory):
        """The exact bug we fixed: 4 parallel POSTs in 2 seconds."""
        results = []
        barrier = threading.Barrier(4)

        def _fire():
            barrier.wait()  # release all 4 threads at the same instant
            return manager.start(account_id=1, user_email="a@x.com")

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(_fire) for _ in range(4)]
            for f in as_completed(futures):
                results.append(f.result())

        # Exactly one row created
        with session_factory() as s:
            rows = s.query(OnboardingResult).filter_by(account_id=1).all()
            assert len(rows) == 1, f"expected 1 row, got {len(rows)}"
            created_id = rows[0].id

        # Exactly one call got already_running=False; the other 3 got True
        fresh = [r for r in results if r["already_running"] is False]
        reused = [r for r in results if r["already_running"] is True]
        assert len(fresh) == 1
        assert len(reused) == 3
        # All 4 responses point to the same onboarding_id
        assert {r["onboarding_id"] for r in results} == {created_id}


class TestRetryAfterTerminalStatus:
    """A terminal status (completed/failed/partial) must NOT block a retry."""

    def _create_row_with_status(self, session_factory, account_id, status):
        with session_factory() as s:
            row = OnboardingResult(account_id=account_id, status=status)
            s.add(row)
            s.commit()
            return row.id

    def test_retry_after_completed_spawns_new_row(self, manager, session_factory):
        old_id = self._create_row_with_status(session_factory, 1, "completed")
        r = manager.start(account_id=1, user_email="a@x.com")
        assert r["already_running"] is False
        assert r["onboarding_id"] != old_id

    def test_retry_after_failed_spawns_new_row(self, manager, session_factory):
        self._create_row_with_status(session_factory, 1, "failed")
        r = manager.start(account_id=1, user_email="a@x.com")
        assert r["already_running"] is False

    def test_retry_after_partial_spawns_new_row(self, manager, session_factory):
        self._create_row_with_status(session_factory, 1, "partial")
        r = manager.start(account_id=1, user_email="a@x.com")
        assert r["already_running"] is False

    def test_retry_replaces_old_active_row_without_heartbeat(self, manager, session_factory):
        created_at = datetime.now(timezone.utc) - timedelta(seconds=90)
        with session_factory() as s:
            old = OnboardingResult(
                account_id=1,
                status="waiting_for_sync",
                created_at=created_at.replace(tzinfo=None),
            )
            s.add(old)
            s.commit()
            old_id = old.id

        manager_mod._LAST_HEARTBEAT.pop(old_id, None)

        r = manager.start(account_id=1, user_email="a@x.com")

        assert r["already_running"] is False
        assert r["onboarding_id"] != old_id
        with session_factory() as s:
            old_row = s.query(OnboardingResult).filter_by(id=old_id).one()
            new_row = s.query(OnboardingResult).filter_by(id=r["onboarding_id"]).one()
            assert old_row.status == "failed"
            assert new_row.status == "pending"

    def test_recent_active_row_without_heartbeat_is_preserved(self, manager, session_factory):
        created_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        with session_factory() as s:
            row = OnboardingResult(
                account_id=1,
                status="waiting_for_sync",
                created_at=created_at.replace(tzinfo=None),
            )
            s.add(row)
            s.commit()
            row_id = row.id

        manager_mod._LAST_HEARTBEAT.pop(row_id, None)

        r = manager.start(account_id=1, user_email="a@x.com")

        assert r["already_running"] is True
        assert r["onboarding_id"] == row_id
        with session_factory() as s:
            assert s.query(OnboardingResult).filter_by(account_id=1).count() == 1


class TestRunAnalysisTransactionLifecycle:
    """Regression guard for provider fetches inside _run_analysis."""

    def test_sent_cache_provider_fetch_starts_outside_read_transaction(
        self, session_factory, monkeypatch
    ):
        with session_factory() as s:
            row = OnboardingResult(account_id=1, status="pending")
            s.add(row)
            s.commit()
            onboarding_id = row.id

        mgr = OnboardingManager(session_factory=session_factory)
        observed_transactions = []

        def fake_populate_sent_cache(account_id, user_email, session):
            observed_transactions.append(session.in_transaction())
            return {"stored": 0, "attempted": True, "failed": True, "via": None}

        class StopAfterPopulateLoader:
            def __init__(self, *_args, **_kwargs):
                pass

            def load(self, **_kwargs):
                raise RuntimeError("stop after sent-cache transaction check")

        monkeypatch.setattr(mgr, "_populate_sent_cache", fake_populate_sent_cache)
        monkeypatch.setattr(manager_mod, "RepositoryLoader", StopAfterPopulateLoader)

        mgr._run_analysis(onboarding_id, 1, "a@x.com")

        assert observed_transactions == [False]


class TestCrossAccountIsolation:
    """Dedupe is strictly per-account."""

    def test_different_accounts_both_create_rows(self, manager, session_factory):
        r1 = manager.start(account_id=1, user_email="a@x.com")
        r2 = manager.start(account_id=2, user_email="b@y.com")
        assert r1["already_running"] is False
        assert r2["already_running"] is False
        assert r1["onboarding_id"] != r2["onboarding_id"]
        with session_factory() as s:
            assert s.query(OnboardingResult).count() == 2


class TestRepositoryFindActive:
    """The underlying DB query."""

    def test_find_active_returns_none_when_empty(self, session_factory):
        with session_factory() as s:
            repo = OnboardingRepository(s)
            assert repo.find_active(1) is None

    def test_find_active_ignores_completed(self, session_factory):
        with session_factory() as s:
            s.add(OnboardingResult(account_id=1, status="completed"))
            s.commit()
            repo = OnboardingRepository(s)
            assert repo.find_active(1) is None

    def test_find_active_returns_pending(self, session_factory):
        with session_factory() as s:
            s.add(OnboardingResult(account_id=1, status="pending"))
            s.commit()
            repo = OnboardingRepository(s)
            result = repo.find_active(1)
            assert result is not None
            assert result.status == "pending"

    def test_find_active_picks_most_recent(self, session_factory):
        """When multiple active rows exist (shouldn't happen after the fix,
        but defensive), the most recent wins."""
        with session_factory() as s:
            s.add(OnboardingResult(account_id=1, status="pending"))
            s.add(OnboardingResult(account_id=1, status="running"))
            s.commit()
            repo = OnboardingRepository(s)
            result = repo.find_active(1)
            assert result is not None
            # Most recent = 'running' (inserted second)
            assert result.status == "running"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
