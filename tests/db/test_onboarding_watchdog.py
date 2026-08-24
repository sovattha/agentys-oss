# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Test for OnboardingManager.cleanup_stale_onboardings (watchdog).

Companion to ``test_onboarding_recovery.py`` (boot-time recovery). The
watchdog runs while the process is alive and catches workers that died
between two heartbeats — typically a ``database is locked`` mid-commit
that killed the thread before it could flip the row's status itself.
"""

import time
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import OnboardingResult
from app.onboarding import manager as manager_mod
from app.onboarding.manager import OnboardingManager


@pytest.fixture
def manager(engine):
    from sqlalchemy.orm import sessionmaker
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    return OnboardingManager(session_factory=factory)


@pytest.fixture(autouse=True)
def _clean_heartbeats():
    """Each test starts with an empty module-level heartbeat dict."""
    manager_mod._LAST_HEARTBEAT.clear()
    yield
    manager_mod._LAST_HEARTBEAT.clear()


def _create_onboarding(session, account_id: int, status: str, age_seconds: float = 0.0) -> OnboardingResult:
    """Create a row whose created_at is shifted ``age_seconds`` into the past."""
    created_at = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    # SQLite stores naive datetimes — match the convention.
    row = OnboardingResult(
        account_id=account_id,
        status=status,
        created_at=created_at.replace(tzinfo=None),
    )
    session.add(row)
    session.commit()
    return row


class TestCleanupStaleOnboardings:
    def test_no_heartbeat_past_grace_is_flipped(self, manager, session, sample_account):
        """A row with no heartbeat and age past grace = dead worker."""
        row = _create_onboarding(session, sample_account.id, "waiting_for_sync", age_seconds=120)
        flipped = manager.cleanup_stale_onboardings(stale_seconds=600, grace_seconds=60)
        assert flipped == [row.id]
        session.expire_all()
        refreshed = session.query(OnboardingResult).filter_by(id=row.id).one()
        assert refreshed.status == "failed"
        assert "bloqu" in (refreshed.error_message or "").lower()

    def test_no_heartbeat_within_grace_is_preserved(self, manager, session, sample_account):
        """Fresh row in grace window: worker may not have bumped yet."""
        row = _create_onboarding(session, sample_account.id, "waiting_for_sync", age_seconds=10)
        flipped = manager.cleanup_stale_onboardings(stale_seconds=600, grace_seconds=60)
        assert flipped == []
        session.expire_all()
        refreshed = session.query(OnboardingResult).filter_by(id=row.id).one()
        assert refreshed.status == "waiting_for_sync"

    def test_recent_heartbeat_is_preserved(self, manager, session, sample_account):
        """Worker heartbeating normally: don't touch."""
        row = _create_onboarding(session, sample_account.id, "running", age_seconds=300)
        manager_mod._LAST_HEARTBEAT[row.id] = time.monotonic()
        flipped = manager.cleanup_stale_onboardings(stale_seconds=600, grace_seconds=60)
        assert flipped == []
        session.expire_all()
        refreshed = session.query(OnboardingResult).filter_by(id=row.id).one()
        assert refreshed.status == "running"

    def test_stale_heartbeat_is_flipped(self, manager, session, sample_account):
        """Worker bumped once but has been silent for > stale_seconds."""
        row = _create_onboarding(session, sample_account.id, "running", age_seconds=900)
        # Simulate a heartbeat 700s ago — past the 600s threshold.
        manager_mod._LAST_HEARTBEAT[row.id] = time.monotonic() - 700
        flipped = manager.cleanup_stale_onboardings(stale_seconds=600, grace_seconds=60)
        assert flipped == [row.id]
        session.expire_all()
        refreshed = session.query(OnboardingResult).filter_by(id=row.id).one()
        assert refreshed.status == "failed"

    def test_completed_row_is_untouched(self, manager, session, sample_account):
        row = _create_onboarding(session, sample_account.id, "completed", age_seconds=3600)
        flipped = manager.cleanup_stale_onboardings(stale_seconds=600, grace_seconds=60)
        assert flipped == []
        session.expire_all()
        refreshed = session.query(OnboardingResult).filter_by(id=row.id).one()
        assert refreshed.status == "completed"

    def test_flip_clears_heartbeat(self, manager, session, sample_account):
        """Flipping must drop the in-memory heartbeat to avoid unbounded growth."""
        row = _create_onboarding(session, sample_account.id, "running", age_seconds=900)
        manager_mod._LAST_HEARTBEAT[row.id] = time.monotonic() - 700
        manager.cleanup_stale_onboardings(stale_seconds=600, grace_seconds=60)
        assert row.id not in manager_mod._LAST_HEARTBEAT

    def test_no_active_rows_returns_empty(self, manager):
        flipped = manager.cleanup_stale_onboardings()
        assert flipped == []

    def test_emits_learning_completed_for_each_flip(self, manager, session, sample_account):
        """Frontend needs a WS event so the spinner exits without polling."""
        events: list[tuple[str, dict]] = []
        manager.emit_event = lambda name, data: events.append((name, data))
        row = _create_onboarding(session, sample_account.id, "waiting_for_sync", age_seconds=120)
        manager.cleanup_stale_onboardings(stale_seconds=600, grace_seconds=60)
        completed_events = [e for e in events if e[0] == "onboarding:learning_completed"]
        assert len(completed_events) == 1
        _, payload = completed_events[0]
        assert payload["onboarding_id"] == row.id
        assert payload["status"] == "failed"
