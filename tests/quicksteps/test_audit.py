# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Audit log — end-to-end roundtrip with the real ``QuickStepAuditLog`` table.

Engine unit tests in ``test_engine.py`` stub the audit writer (see the
``conftest.py`` autouse fixture). This module deliberately bypasses that
stub by calling ``record_execution`` directly with a real session, so we
exercise the actual ORM path that production hits.
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest
from sqlalchemy.orm import sessionmaker

from app.quicksteps.audit import record_execution
from app.quicksteps.engine import ActionStatus, ExecutionReport
from app.db.models.quick_step_audit_log import QuickStepAuditLog


@pytest.fixture
def db_session(engine):
    SessionLocal = sessionmaker(bind=engine, autoflush=False)

    @contextmanager
    def fake_session_cm():
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    with patch("app.db.database.get_db_session", fake_session_cm):
        yield SessionLocal()


def _report(success: bool = True, error: str | None = None, replay: bool = False) -> ExecutionReport:
    return ExecutionReport(
        success=success,
        step_id="step-1",
        email_id="e-1",
        executed=2,
        actions=[
            ActionStatus(type="archive", ok=True),
            ActionStatus(type="mark_read", ok=success, error=error),
        ],
        error=error,
        idempotent_replay=replay,
    )


class TestRecordExecution:
    def test_writes_one_row_per_call(self, db_session, sample_account):
        record_execution(
            account_id=sample_account.id,
            step={"id": "step-1", "name": "Triage"},
            email_id="e-1",
            report=_report(),
            source="manual",
        )
        rows = db_session.query(QuickStepAuditLog).all()
        assert len(rows) == 1
        row = rows[0]
        assert row.account_id == sample_account.id
        assert row.step_id == "step-1"
        assert row.step_name == "Triage"
        assert row.email_id == "e-1"
        assert row.source == "manual"
        assert row.success is True
        assert row.executed == 2
        assert row.error is None
        assert row.replay is False
        assert "archive" in (row.actions_json or "")

    def test_failure_path_records_error(self, db_session, sample_account):
        record_execution(
            account_id=sample_account.id,
            step={"id": "step-2", "name": "Boom"},
            email_id="e-2",
            report=_report(success=False, error="provider_unavailable: x"),
            source="auto",
        )
        row = db_session.query(QuickStepAuditLog).one()
        assert row.success is False
        assert row.error == "provider_unavailable: x"
        assert row.source == "auto"

    def test_replay_flagged_on_audit_row(self, db_session, sample_account):
        record_execution(
            account_id=sample_account.id,
            step={"id": "step-3", "name": "Replay"},
            email_id="e-3",
            report=_report(replay=True),
        )
        row = db_session.query(QuickStepAuditLog).one()
        assert row.replay is True

    def test_unknown_source_falls_back_to_manual(self, db_session, sample_account):
        record_execution(
            account_id=sample_account.id,
            step={"id": "step-4", "name": "X"},
            email_id="e-4",
            report=_report(),
            source="cron-something-bogus",
        )
        row = db_session.query(QuickStepAuditLog).one()
        assert row.source == "manual"

    def test_invalid_account_id_is_no_op(self, db_session):
        record_execution(
            account_id=0,
            step={"id": "step-5"},
            email_id="e-5",
            report=_report(),
        )
        assert db_session.query(QuickStepAuditLog).count() == 0

    def test_oversized_strings_are_truncated(self, db_session, sample_account):
        long_id = "x" * 200  # step_id column is String(64)
        long_email = "y" * 400
        record_execution(
            account_id=sample_account.id,
            step={"id": long_id, "name": "n" * 500},
            email_id=long_email,
            report=_report(),
        )
        row = db_session.query(QuickStepAuditLog).one()
        assert len(row.step_id) == 64
        assert len(row.step_name or "") == 255
        assert len(row.email_id) == 255
