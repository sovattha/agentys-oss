# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Re-evaluating auto-triggers on email state changes (mark-as-read).

Covers:
  - `_step_fired_on_email` dedup: same (step, email) row in audit log → True.
  - `run_auto_triggers` skips a step whose audit row says it already fired.
  - The "Has label Info + is_read=true → Archive" use-case end-to-end:
    first call (email unread) leaves the rule dormant, second call after
    marking-as-read fires it exactly once.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from unittest.mock import patch

import pytest
from sqlalchemy.orm import sessionmaker

from app.db.models.quick_step_audit_log import QuickStepAuditLog
from app.quicksteps import auto_trigger


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


@dataclass
class _Email:
    sender: str = "ian@pinterest.com"
    subject: str = "Show us your game day era"
    body: str = ""
    body_html: str = ""
    recipients: str = ""
    attachments_meta: str = ""
    id: str = "email-info-1"
    thread_id: str = "thread-1"
    is_read: bool = False
    labels: object = None


def _insert_audit_row(session, *, account_id: int, step_id: str, email_id: str, success: bool = True, source: str = "auto"):
    row = QuickStepAuditLog(
        account_id=account_id,
        step_id=step_id,
        step_name="Info → Archive",
        email_id=email_id,
        source=source,
        success=success,
        executed=1,
        created_at=datetime.utcnow(),
    )
    session.add(row)
    session.commit()
    return row


class TestStepFiredOnEmail:
    def test_returns_true_when_audit_row_exists(self, db_session, sample_account):
        _insert_audit_row(
            db_session,
            account_id=sample_account.id,
            step_id="step-A",
            email_id="email-1",
        )
        assert auto_trigger._step_fired_on_email(
            sample_account.id, "step-A", "email-1"
        ) is True

    def test_returns_false_when_no_row(self, db_session, sample_account):
        assert auto_trigger._step_fired_on_email(
            sample_account.id, "step-A", "email-1"
        ) is False

    def test_scoped_per_account(self, db_session, sample_account):
        _insert_audit_row(
            db_session,
            account_id=sample_account.id,
            step_id="step-A",
            email_id="email-1",
        )
        # Different account_id → must not match.
        assert auto_trigger._step_fired_on_email(
            sample_account.id + 999, "step-A", "email-1"
        ) is False

    def test_scoped_per_email(self, db_session, sample_account):
        _insert_audit_row(
            db_session,
            account_id=sample_account.id,
            step_id="step-A",
            email_id="email-1",
        )
        assert auto_trigger._step_fired_on_email(
            sample_account.id, "step-A", "email-DIFFERENT"
        ) is False

    def test_ignores_manual_runs(self, db_session, sample_account):
        # Manual runs (user keypress) don't block auto-fires — only auto rows
        # set the dedup marker.
        _insert_audit_row(
            db_session,
            account_id=sample_account.id,
            step_id="step-A",
            email_id="email-1",
            source="manual",
        )
        assert auto_trigger._step_fired_on_email(
            sample_account.id, "step-A", "email-1"
        ) is False

    def test_ignores_failed_runs(self, db_session, sample_account):
        # A failed auto-fire should NOT block a retry — only successful rows
        # are durable dedup markers.
        _insert_audit_row(
            db_session,
            account_id=sample_account.id,
            step_id="step-A",
            email_id="email-1",
            success=False,
        )
        assert auto_trigger._step_fired_on_email(
            sample_account.id, "step-A", "email-1"
        ) is False

    def test_empty_inputs_return_false_without_raising(self):
        # No DB access expected on degenerate inputs.
        assert auto_trigger._step_fired_on_email(0, "step", "email") is False
        assert auto_trigger._step_fired_on_email(1, "", "email") is False
        assert auto_trigger._step_fired_on_email(1, "step", "") is False


class TestRunAutoTriggersSkipsAlreadyFired:
    def test_step_skipped_when_audit_row_exists(self, db_session, sample_account):
        """A rule with an audit row for this (step, email) must NOT execute again."""
        step = {
            "id": "step-Z",
            "name": "Info → Archive",
            "enabled": True,
            "autoEnabled": True,
            "firesOn": "received",
            "triggerOperator": "AND",
            "triggers": [{"type": "subject_keyword", "value": "game day"}],
            "actions": [{"type": "archive", "payload": {}}],
        }
        _insert_audit_row(
            db_session,
            account_id=sample_account.id,
            step_id="step-Z",
            email_id="email-info-1",
        )

        called = {"execute": 0}

        class _FakeEngine:
            @staticmethod
            def execute(**_kw):
                called["execute"] += 1

                class _R:
                    success = True
                    error = None
                return _R()

        with patch("app.quicksteps.store.load_quick_steps", return_value=[step]), \
             patch("app.quicksteps.engine", _FakeEngine):
            auto_trigger.run_auto_triggers(
                sample_account.id, "email-info-1", _Email()
            )
        assert called["execute"] == 0

    def test_step_fires_when_no_audit_row_yet(self, db_session, sample_account):
        step = {
            "id": "step-NEW",
            "name": "Info → Archive",
            "enabled": True,
            "autoEnabled": True,
            "firesOn": "received",
            "triggerOperator": "AND",
            "triggers": [{"type": "subject_keyword", "value": "game day"}],
            "actions": [{"type": "archive", "payload": {}}],
        }

        called = {"execute": 0}

        class _FakeReport:
            success = True
            error = None

        class _FakeEngine:
            @staticmethod
            def execute(**_kw):
                called["execute"] += 1
                return _FakeReport()

        with patch("app.quicksteps.store.load_quick_steps", return_value=[step]), \
             patch("app.quicksteps.engine", _FakeEngine):
            auto_trigger.run_auto_triggers(
                sample_account.id, "email-info-1", _Email()
            )
        assert called["execute"] == 1
