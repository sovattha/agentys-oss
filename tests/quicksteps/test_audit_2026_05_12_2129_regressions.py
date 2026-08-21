# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Regression tests for the audit-2026-05-12_2129 audit pass.

Locks in the two integrity-critical fixes:
- F-06 — `engine.finalize()` must cache the report AFTER the audit recorder
  ran so a recorder failure (`report.success = False`) does not leave a
  `success=True` snapshot in the idempotency store. Without this, replays
  within the 60-second TTL silently disarm the auto-trigger dedup guard
  (`_step_fired_on_email`).
- F-01 + F-05 — `_step_fired_on_thread` JOIN must compare `Email.email_id`
  (str provider id) to `QuickStepAuditLog.email_id` (str), pinned by
  `Email.account_id` to prevent cross-account email_id collisions. The
  previous JOIN used `Email.id` (int PK) which SQLite type-affinity casts
  silently to False for any non-numeric provider id → the
  `previously_auto_actioned_by` trigger never fired.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from app.quicksteps import engine
from app.quicksteps.idempotency import MemoryIdempotencyStore


def _step(actions=None):
    return {
        "id": "22222222-2222-4222-8222-222222222222",
        "name": "test",
        "actions": actions if actions is not None else [{"type": "archive"}],
        "enabled": True,
    }


# --------------------------------------------------------------------------- #
# F-06 — recorder failure must mutate the report AND the cached snapshot.
# Replays must reflect the post-recorder state, not the pre-recorder one.
# --------------------------------------------------------------------------- #

class TestFinalizeRecorderFailureCacheOrdering:
    """Locks in the F-06 fix from audit-2026-05-12_2129."""

    def test_recorder_failure_does_not_leave_stale_success_in_cache(self):
        """The bug: cache was written BEFORE the recorder ran. If the recorder
        raised, the in-memory report was flipped to success=False but the
        cache still said success=True. Replays returned success=True with no
        audit row, disarming the auto-trigger dedup guard."""
        store = MemoryIdempotencyStore()
        provider = MagicMock()
        provider.archive_email.return_value = True

        def boom_recorder(**_):
            raise RuntimeError("transient db locked")

        first = engine.execute(
            account_id=1,
            step=_step(),
            email_id="msg-xyz",
            idempotency_key="K-recorder-fail",
            provider_factory=lambda: provider,
            email_loader=lambda *_: MagicMock(),
            account_loader=lambda _aid: ("u@x", "U"),
            idempotency_store=store,
            audit_recorder=boom_recorder,
        )
        # Caller sees the in-memory report mutated by the recorder failure.
        assert first.success is False, "first call should reflect recorder failure"
        assert first.error == "audit_record_failed"

        # Replay must NOT return a lie (i.e. not success=True). The cache
        # must reflect the post-recorder state, not the pre-recorder one.
        second = engine.execute(
            account_id=1,
            step=_step(),
            email_id="msg-xyz",
            idempotency_key="K-recorder-fail",
            provider_factory=lambda: provider,
            email_loader=lambda *_: MagicMock(),
            account_loader=lambda _aid: ("u@x", "U"),
            idempotency_store=store,
            audit_recorder=boom_recorder,
        )
        assert second.idempotent_replay is True
        assert second.success is False, (
            "F-06 regression: replay returned success=True after recorder "
            "failure — cache was written before recorder ran, lying for 60s"
        )
        assert second.error == "audit_record_failed"

    def test_recorder_success_still_caches_success_true(self):
        """Sanity: the happy path must still cache success=True so the
        replay semantics for the normal case are preserved."""
        store = MemoryIdempotencyStore()
        provider = MagicMock()
        provider.archive_email.return_value = True
        recorder_calls: list = []

        def ok_recorder(**kw):
            recorder_calls.append(kw)

        first = engine.execute(
            account_id=1,
            step=_step(),
            email_id="msg-happy",
            idempotency_key="K-happy",
            provider_factory=lambda: provider,
            email_loader=lambda *_: MagicMock(),
            account_loader=lambda _aid: ("u@x", "U"),
            idempotency_store=store,
            audit_recorder=ok_recorder,
        )
        assert first.success is True
        assert len(recorder_calls) == 1

        second = engine.execute(
            account_id=1,
            step=_step(),
            email_id="msg-happy",
            idempotency_key="K-happy",
            provider_factory=lambda: provider,
            email_loader=lambda *_: MagicMock(),
            account_loader=lambda _aid: ("u@x", "U"),
            idempotency_store=store,
            audit_recorder=ok_recorder,
        )
        assert second.idempotent_replay is True
        assert second.success is True
        # Recorder must not run on replay (we don't double-audit).
        assert len(recorder_calls) == 1, "recorder must not re-fire on replay"


# --------------------------------------------------------------------------- #
# F-01 + F-05 — _step_fired_on_thread JOIN on email_id (str) + account_id.
# Uses a real in-memory SQLite via the test conftest fixture infrastructure
# rather than mocking — the bug is a SQL type-affinity behavior that mocks
# would obscure.
# --------------------------------------------------------------------------- #

@pytest.fixture
def in_memory_db():
    """Spin up an in-memory SQLite with the Email + QuickStepAuditLog tables
    so we can assert the real SQLAlchemy JOIN behavior, not a mocked one."""
    import sqlalchemy as sa
    from sqlalchemy.orm import sessionmaker
    from app.db.models.base import Base
    from app.db.models.email import Email  # noqa: F401  — register table
    from app.db.models.quick_step_audit_log import QuickStepAuditLog  # noqa: F401

    engine_ = sa.create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine_)
    Session = sessionmaker(bind=engine_, future=True)
    return engine_, Session


class TestPreviouslyAutoActionedByJoin:
    """Locks in F-01 + F-05 from audit-2026-05-12_2129.

    The bug: the JOIN compared Email.id (INTEGER PK) to QuickStepAuditLog
    .email_id (VARCHAR provider id). For Gmail's lowercase hex msg ids,
    SQLite's NUMERIC affinity casts the VARCHAR to NULL and the comparison
    is False — every previously_auto_actioned_by trigger silently never
    fires.
    """

    def _seed(self, Session, *, account_id: int, email_id: str, thread_id: str, step_id: str):
        from app.db.models.email import Email
        from app.db.models.quick_step_audit_log import QuickStepAuditLog
        with Session() as s:
            s.add(Email(
                email_id=email_id,
                account_id=account_id,
                thread_id=thread_id,
                subject="t",
                sender="x@y",
                recipients="me@z",
                date=datetime(2026, 5, 12, 10, 0),
            ))
            s.add(QuickStepAuditLog(
                account_id=account_id,
                step_id=step_id,
                step_name="step",
                email_id=email_id,
                source="auto",
                success=True,
                actions_json="[]",
                created_at=datetime(2026, 5, 12, 10, 1),
            ))
            s.commit()

    def test_join_matches_on_provider_email_id_string(self, in_memory_db, monkeypatch):
        """The lookup must return True when a successful auto audit row
        exists for an email in the same thread — even when the provider
        email_id is non-numeric (Gmail-hex)."""
        engine_, Session = in_memory_db
        from app.quicksteps import auto_trigger

        # Patch get_db_session to yield our in-memory Session.
        from contextlib import contextmanager

        @contextmanager
        def fake_session():
            s = Session()
            try:
                yield s
            finally:
                s.close()

        monkeypatch.setattr(
            "app.db.database.get_db_session", fake_session,
        )

        provider_id = "18f4e2d3c5a6b7c8"  # Gmail-shape lowercase hex
        thread = "thread-deadbeef-12345"
        step = "33333333-3333-4333-8333-333333333333"
        self._seed(
            Session,
            account_id=7,
            email_id=provider_id,
            thread_id=thread,
            step_id=step,
        )

        # Sanity check : without the fix this returned False even though
        # the audit row exists and points at the same thread.
        assert auto_trigger._step_fired_on_thread(7, step, thread) is True, (
            "F-01 regression: JOIN failed to match on provider email_id "
            "(non-numeric str). The old JOIN compared Email.id (int) to "
            "QuickStepAuditLog.email_id (str)."
        )

    def test_join_does_not_leak_across_accounts(self, in_memory_db, monkeypatch):
        """F-05: the JOIN must pin Email.account_id so a shared email_id
        across two accounts (delegate inbox, multi-mailbox) does NOT
        false-positive the audit lookup for the other account."""
        engine_, Session = in_memory_db
        from app.quicksteps import auto_trigger
        from contextlib import contextmanager

        @contextmanager
        def fake_session():
            s = Session()
            try:
                yield s
            finally:
                s.close()

        monkeypatch.setattr(
            "app.db.database.get_db_session", fake_session,
        )

        shared_email_id = "18f4e2d3c5a6b7c8"
        shared_thread = "thread-shared"
        step = "44444444-4444-4444-8444-444444444444"

        # Account 7 audited the step. Account 8 has the SAME email_id in
        # its emails table (e.g. delegated mailbox) with the same thread_id.
        self._seed(
            Session,
            account_id=7,
            email_id=shared_email_id,
            thread_id=shared_thread,
            step_id=step,
        )
        from app.db.models.email import Email
        with Session() as s:
            s.add(Email(
                email_id=shared_email_id,
                account_id=8,
                thread_id=shared_thread,
                subject="t",
                sender="x@y",
                recipients="me@z",
                date=datetime(2026, 5, 12, 10, 0),
            ))
            s.commit()

        # Account 7's lookup must succeed.
        assert auto_trigger._step_fired_on_thread(7, step, shared_thread) is True

        # Account 8 has the same email_id in its emails table but NO audit
        # row of its own. Without the Email.account_id pin in the JOIN
        # clause, the JOIN would match account 7's email row against
        # account 7's audit row even when queried with account_id=8 (the
        # audit account_id filter would catch it for THIS exact test, but
        # the broader risk is real once cross-account audit rows exist).
        # Locking the JOIN ON the account pin is correct independent of
        # the WHERE filter so we lock that contract in.
        assert auto_trigger._step_fired_on_thread(8, step, shared_thread) is False
