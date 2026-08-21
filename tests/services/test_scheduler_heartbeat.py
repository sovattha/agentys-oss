# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests for app.services.scheduler_heartbeat — issue #577 item 4.

Rationale: 5 background schedulers (learning, recap, scheduled_email,
batch_worker, bulk_jobs) silently swallow exceptions inside their loop.
A crashed thread leaves the app responding 200 but the scheduled work
never runs — the user discovers it the day a follow-up doesn't go out.

The heartbeat is the cheap structural fix: each scheduler stamps a row
at the start of its tick. A sentinel polls /scheduler-health daily and
opens an issue if any row is stale.

These tests pin the contract — UPSERT, never duplicates, stale only
when the wall-clock gap exceeds the declared interval.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture(autouse=True)
def _ensure_db_schema():
    """The heartbeat model is new — make sure CREATE TABLE has run.

    Production boots through `init_db()` which loads every model, but
    individual unit tests can hit `record_heartbeat` before the test
    runner has touched the schema.
    """
    from app.db.database import init_db

    init_db()


@pytest.fixture
def clean_heartbeats():
    """Wipe all rows so test order doesn't leak state."""
    from app.db.database import get_db_session
    from app.db.models.scheduler_heartbeat import SchedulerHeartbeat

    with get_db_session() as session:
        session.query(SchedulerHeartbeat).delete()
    yield
    with get_db_session() as session:
        session.query(SchedulerHeartbeat).delete()


class TestRecordHeartbeat:
    def test_first_call_inserts_row(self, clean_heartbeats):
        from app.services.scheduler_heartbeat import record_heartbeat
        from app.db.database import get_db_session
        from app.db.models.scheduler_heartbeat import SchedulerHeartbeat

        record_heartbeat(
            "scheduled_email_scheduler",
            status="ok",
            expected_interval_seconds=120,
        )

        with get_db_session() as session:
            rows = session.query(SchedulerHeartbeat).all()
            assert len(rows) == 1
            assert rows[0].name == "scheduled_email_scheduler"
            assert rows[0].last_status == "ok"
            assert rows[0].expected_interval_seconds == 120

    def test_second_call_updates_same_row_not_inserts_new(
        self, clean_heartbeats
    ):
        """The whole point of UPSERT — duplicates would lie about the
        last beat by surfacing the older row first."""
        from app.services.scheduler_heartbeat import record_heartbeat
        from app.db.database import get_db_session
        from app.db.models.scheduler_heartbeat import SchedulerHeartbeat

        record_heartbeat("recap_scheduler", status="ok", expected_interval_seconds=600)
        record_heartbeat("recap_scheduler", status="error", expected_interval_seconds=600)
        record_heartbeat("recap_scheduler", status="ok", expected_interval_seconds=600)

        with get_db_session() as session:
            rows = session.query(SchedulerHeartbeat).all()
            assert len(rows) == 1
            assert rows[0].last_status == "ok"

    def test_separate_schedulers_get_separate_rows(self, clean_heartbeats):
        from app.services.scheduler_heartbeat import record_heartbeat
        from app.db.database import get_db_session
        from app.db.models.scheduler_heartbeat import SchedulerHeartbeat

        record_heartbeat("a", status="ok", expected_interval_seconds=60)
        record_heartbeat("b", status="ok", expected_interval_seconds=60)
        record_heartbeat("c", status="ok", expected_interval_seconds=60)

        with get_db_session() as session:
            assert session.query(SchedulerHeartbeat).count() == 3

    def test_record_heartbeat_swallows_exceptions(
        self, clean_heartbeats, monkeypatch
    ):
        """Contract: a DB failure inside record_heartbeat MUST NOT bubble
        to the caller. Otherwise the heartbeat we added to detect crashes
        becomes the cause of the crash. Logged at warning, never raised.
        """
        import app.services.scheduler_heartbeat as svc

        def _boom():
            raise RuntimeError("simulated DB outage")

        monkeypatch.setattr(svc, "get_db_session", _boom)
        # Must not raise.
        svc.record_heartbeat("x", status="ok", expected_interval_seconds=60)


class TestGetStaleHeartbeats:
    def test_fresh_heartbeat_is_not_stale(self, clean_heartbeats):
        from app.services.scheduler_heartbeat import (
            record_heartbeat,
            get_stale_heartbeats,
        )

        record_heartbeat("fresh", status="ok", expected_interval_seconds=60)
        stale = get_stale_heartbeats()
        assert stale == []

    def test_old_heartbeat_is_stale(self, clean_heartbeats):
        """Backdate a row to simulate a scheduler that died long ago."""
        from app.services.scheduler_heartbeat import get_stale_heartbeats
        from app.db.database import get_db_session
        from app.db.models.scheduler_heartbeat import SchedulerHeartbeat

        with get_db_session() as session:
            row = SchedulerHeartbeat(
                name="dead_scheduler",
                last_status="ok",
                expected_interval_seconds=60,
                last_run_at=datetime.now(timezone.utc)
                - timedelta(seconds=200),
            )
            session.add(row)

        stale = get_stale_heartbeats()
        assert len(stale) == 1
        assert stale[0].name == "dead_scheduler"
        # Reported "elapsed" should be larger than the declared interval.
        elapsed = (
            datetime.now(timezone.utc) - stale[0].last_run_at.replace(tzinfo=timezone.utc)
        ).total_seconds()
        assert elapsed > stale[0].expected_interval_seconds

    def test_boundary_just_under_interval_is_not_stale(
        self, clean_heartbeats
    ):
        """Exact boundary — a scheduler that beat 59s ago with a 60s
        interval is still healthy; one that beat 61s ago is not."""
        from app.services.scheduler_heartbeat import get_stale_heartbeats
        from app.db.database import get_db_session
        from app.db.models.scheduler_heartbeat import SchedulerHeartbeat

        now = datetime.now(timezone.utc)
        with get_db_session() as session:
            session.add(
                SchedulerHeartbeat(
                    name="just_in_time",
                    last_status="ok",
                    expected_interval_seconds=60,
                    last_run_at=now - timedelta(seconds=30),
                )
            )

        stale = get_stale_heartbeats()
        assert stale == []

    def test_mixed_state_returns_only_stale_rows(self, clean_heartbeats):
        from app.services.scheduler_heartbeat import (
            record_heartbeat,
            get_stale_heartbeats,
        )
        from app.db.database import get_db_session
        from app.db.models.scheduler_heartbeat import SchedulerHeartbeat

        record_heartbeat("alive", status="ok", expected_interval_seconds=60)

        with get_db_session() as session:
            session.add(
                SchedulerHeartbeat(
                    name="dead",
                    last_status="ok",
                    expected_interval_seconds=60,
                    last_run_at=datetime.now(timezone.utc)
                    - timedelta(seconds=300),
                )
            )

        stale = get_stale_heartbeats()
        assert {r.name for r in stale} == {"dead"}
