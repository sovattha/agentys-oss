# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests for the deadline-driven Quick Step actions.

``create_reminder`` and ``create_calendar_event`` both fire from a
``firesOn="received"`` rule (typically gated by ``has_deadline_detected``)
and schedule a reminder / calendar event ``days_before`` the deadline the
ingest pipeline stamped on the email (``emails.deadline_at``), with a
fallback to a live ``extract_deadline`` pass when the column is empty.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.quicksteps import schema


def _new_id() -> str:
    return str(uuid.uuid4())


def _step(action: dict, **overrides) -> dict:
    base = {"id": _new_id(), "name": "Deadline rule", "actions": [action]}
    base.update(overrides)
    return base


# --------------------------------------------------------------------------- #
# Schema validation
# --------------------------------------------------------------------------- #

class TestRegistryWiring:
    def test_both_actions_dispatch_via_registry(self):
        from app.quicksteps.registry import (
            ACTION_HANDLERS,
            handle_create_calendar_event,
            handle_create_reminder,
        )

        assert ACTION_HANDLERS["create_reminder"] is handle_create_reminder
        assert ACTION_HANDLERS["create_calendar_event"] is handle_create_calendar_event


class TestCreateReminderSchema:
    def test_accepts_with_days_before(self):
        cleaned = schema.validate_quick_step(
            _step({"type": "create_reminder", "payload": {"days_before": 2}})
        )
        assert cleaned["actions"][0]["type"] == "create_reminder"
        assert cleaned["actions"][0]["payload"]["days_before"] == 2

    def test_defaults_days_before_when_omitted(self):
        cleaned = schema.validate_quick_step(
            _step({"type": "create_reminder", "payload": {}})
        )
        assert cleaned["actions"][0]["payload"]["days_before"] == 2

    def test_allows_zero_days_before(self):
        cleaned = schema.validate_quick_step(
            _step({"type": "create_reminder", "payload": {"days_before": 0}})
        )
        assert cleaned["actions"][0]["payload"]["days_before"] == 0

    def test_rejects_negative_days_before(self):
        with pytest.raises(schema.ValidationError, match="days_before"):
            schema.validate_quick_step(
                _step({"type": "create_reminder", "payload": {"days_before": -1}})
            )

    def test_rejects_oversized_days_before(self):
        with pytest.raises(schema.ValidationError, match="days_before"):
            schema.validate_quick_step(
                _step({"type": "create_reminder", "payload": {"days_before": 999}})
            )

    def test_rejects_non_integer_days_before(self):
        with pytest.raises(schema.ValidationError, match="days_before"):
            schema.validate_quick_step(
                _step({"type": "create_reminder", "payload": {"days_before": "soon"}})
            )

    def test_rejected_on_sent_flow(self):
        # received-side action: pairing it with firesOn="sent" must fail the
        # cross-flow guard (only create_snoozed_followup_draft + mark_with_emoji
        # are sent-safe).
        with pytest.raises(schema.ValidationError):
            schema.validate_quick_step(
                _step(
                    {"type": "create_reminder", "payload": {"days_before": 2}},
                    firesOn="sent",
                )
            )


class TestCreateCalendarEventSchema:
    def test_accepts_with_days_before_and_duration(self):
        cleaned = schema.validate_quick_step(
            _step({
                "type": "create_calendar_event",
                "payload": {"days_before": 3, "duration_minutes": 45},
            })
        )
        payload = cleaned["actions"][0]["payload"]
        assert payload["days_before"] == 3
        assert payload["duration_minutes"] == 45

    def test_defaults_duration_when_omitted(self):
        cleaned = schema.validate_quick_step(
            _step({"type": "create_calendar_event", "payload": {"days_before": 1}})
        )
        assert cleaned["actions"][0]["payload"]["duration_minutes"] == 30

    def test_rejects_zero_duration(self):
        with pytest.raises(schema.ValidationError, match="duration_minutes"):
            schema.validate_quick_step(
                _step({
                    "type": "create_calendar_event",
                    "payload": {"days_before": 1, "duration_minutes": 0},
                })
            )

    def test_rejects_oversized_duration(self):
        with pytest.raises(schema.ValidationError, match="duration_minutes"):
            schema.validate_quick_step(
                _step({
                    "type": "create_calendar_event",
                    "payload": {"days_before": 1, "duration_minutes": 5000},
                })
            )

    def test_rejected_on_sent_flow(self):
        with pytest.raises(schema.ValidationError):
            schema.validate_quick_step(
                _step(
                    {"type": "create_calendar_event", "payload": {"days_before": 2}},
                    firesOn="sent",
                )
            )


# --------------------------------------------------------------------------- #
# Handler fixtures
# --------------------------------------------------------------------------- #

from dataclasses import dataclass  # noqa: E402

from app.quicksteps.types import ExecutionContext  # noqa: E402


@dataclass
class _FakeEmail:
    subject: str = "Invoice #42"
    body: str = ""
    body_html: str = ""
    body_text: str = ""
    deadline_at: object = None  # datetime | None — column on the SQL Email row
    id: str = "msg-1"


def _ctx(email, *, account_id: int = 1, account_email: str = "user@example.com") -> ExecutionContext:
    return ExecutionContext(
        provider=object(),
        account_id=account_id,
        account_email=account_email,
        account_display_name="User",
        email=email,
        email_id="msg-1",
        raw_id="msg-1",
        template_vars={},
    )


def _patch_add_reminder(monkeypatch) -> list[dict]:
    """Capture add_reminder(...) calls; returns the list they're recorded in."""
    calls: list[dict] = []
    from app.services import reminder_service

    def _fake_add_reminder(*, email_id, subject, reminder_date_iso, account_id=None, reminder_type="snooze"):
        calls.append({
            "email_id": email_id,
            "subject": subject,
            "reminder_date_iso": reminder_date_iso,
            "account_id": account_id,
            "reminder_type": reminder_type,
        })
        return "rem-123"

    monkeypatch.setattr(reminder_service, "add_reminder", _fake_add_reminder)
    return calls


# --------------------------------------------------------------------------- #
# create_reminder handler
# --------------------------------------------------------------------------- #

class TestCreateReminderHandler:
    def test_schedules_reminder_days_before_deadline(self, monkeypatch):
        from app.quicksteps.handlers.deadline_actions import handle_create_reminder

        deadline = datetime.now(timezone.utc) + timedelta(days=30)
        calls = _patch_add_reminder(monkeypatch)
        result = handle_create_reminder(
            _ctx(_FakeEmail(deadline_at=deadline)), {"days_before": 2}
        )
        assert result.ok is True
        assert len(calls) == 1
        assert calls[0]["reminder_type"] == "deadline"
        assert calls[0]["email_id"] == "msg-1"
        assert calls[0]["account_id"] == 1
        fired = datetime.fromisoformat(calls[0]["reminder_date_iso"])
        # 2 days before the deadline (± a few seconds of wall-clock drift)
        assert abs((fired - (deadline - timedelta(days=2))).total_seconds()) < 5

    def test_falls_back_to_extract_when_no_deadline_at(self, monkeypatch):
        from app.quicksteps.handlers.deadline_actions import handle_create_reminder

        calls = _patch_add_reminder(monkeypatch)
        email = _FakeEmail(deadline_at=None, body="Please pay. Payment due March 15, 2099.")
        result = handle_create_reminder(_ctx(email), {"days_before": 0})
        assert result.ok is True
        assert len(calls) == 1
        fired = datetime.fromisoformat(calls[0]["reminder_date_iso"])
        assert fired.year == 2099 and fired.month == 3

    def test_no_deadline_returns_error_and_no_reminder(self, monkeypatch):
        from app.quicksteps.handlers.deadline_actions import handle_create_reminder

        calls = _patch_add_reminder(monkeypatch)
        result = handle_create_reminder(_ctx(_FakeEmail(deadline_at=None, body="hi")), {"days_before": 2})
        assert result.ok is False
        assert result.error == "no_deadline_detected"
        assert calls == []

    def test_clamps_past_fire_time_to_now(self, monkeypatch):
        from app.quicksteps.handlers.deadline_actions import handle_create_reminder

        # Deadline tomorrow, asked to remind 7 days before → fire time is in
        # the past; must clamp to ~now so the reminder still surfaces.
        deadline = datetime.now(timezone.utc) + timedelta(days=1)
        calls = _patch_add_reminder(monkeypatch)
        result = handle_create_reminder(_ctx(_FakeEmail(deadline_at=deadline)), {"days_before": 7})
        assert result.ok is True
        fired = datetime.fromisoformat(calls[0]["reminder_date_iso"])
        now = datetime.now(timezone.utc)
        assert fired >= now - timedelta(seconds=5)

    def test_skips_past_deadline(self, monkeypatch):
        # Adversarial review F6: a deadline already in the past must not fire
        # a reminder immediately on a stale date.
        from app.quicksteps.handlers.deadline_actions import handle_create_reminder

        calls = _patch_add_reminder(monkeypatch)
        past = datetime.now(timezone.utc) - timedelta(days=3)
        result = handle_create_reminder(_ctx(_FakeEmail(deadline_at=past)), {"days_before": 2})
        assert result.ok is False
        assert result.error == "deadline_in_past"
        assert calls == []


# --------------------------------------------------------------------------- #
# create_calendar_event handler
# --------------------------------------------------------------------------- #

class _FakeCal:
    def __init__(self):
        self.events: list = []

    def create_event(self, event, calendar_id: str = "primary"):
        self.events.append(event)
        return {"event_id": "evt-1", "meet_link": None}


def _patch_calendar(monkeypatch, cal=None):
    """Wire a fake calendar provider through the rsvp-style resolution path."""
    from app import multi_accounts
    from app.providers import calendar_factory

    class _Cfg:
        id = "abc-hex"

    class _Mgr:
        def get_account_by_email(self, _email):
            return _Cfg()

    fake = cal if cal is not None else _FakeCal()
    monkeypatch.setattr(multi_accounts, "get_account_manager", lambda: _Mgr())
    monkeypatch.setattr(calendar_factory, "create_calendar_provider", lambda _id: fake)
    return fake


class TestCreateCalendarEventHandler:
    def test_creates_event_days_before_deadline(self, monkeypatch):
        from app.quicksteps.handlers.deadline_actions import handle_create_calendar_event

        deadline = datetime.now(timezone.utc) + timedelta(days=30)
        cal = _patch_calendar(monkeypatch)
        result = handle_create_calendar_event(
            _ctx(_FakeEmail(deadline_at=deadline)),
            {"days_before": 3, "duration_minutes": 45},
        )
        assert result.ok is True
        assert result.artifact["event_id"] == "evt-1"
        assert len(cal.events) == 1
        ev = cal.events[0]
        assert abs((ev.start - (deadline - timedelta(days=3))).total_seconds()) < 5
        assert int((ev.end - ev.start).total_seconds() / 60) == 45

    def test_unresolved_account_returns_error(self, monkeypatch):
        from app.quicksteps.handlers.deadline_actions import handle_create_calendar_event

        deadline = datetime.now(timezone.utc) + timedelta(days=30)
        result = handle_create_calendar_event(
            _ctx(_FakeEmail(deadline_at=deadline), account_email=""),
            {"days_before": 2, "duration_minutes": 30},
        )
        assert result.ok is False
        assert result.error == "calendar_account_unresolved"

    def test_no_deadline_returns_error(self, monkeypatch):
        from app.quicksteps.handlers.deadline_actions import handle_create_calendar_event

        cal = _patch_calendar(monkeypatch)
        result = handle_create_calendar_event(
            _ctx(_FakeEmail(deadline_at=None, body="no date here")),
            {"days_before": 2, "duration_minutes": 30},
        )
        assert result.ok is False
        assert result.error == "no_deadline_detected"
        assert cal.events == []

    def test_skips_past_deadline(self, monkeypatch):
        # Adversarial review F6.
        from app.quicksteps.handlers.deadline_actions import handle_create_calendar_event

        cal = _patch_calendar(monkeypatch)
        past = datetime.now(timezone.utc) - timedelta(days=3)
        result = handle_create_calendar_event(
            _ctx(_FakeEmail(deadline_at=past)),
            {"days_before": 2, "duration_minutes": 30},
        )
        assert result.ok is False
        assert result.error == "deadline_in_past"
        assert cal.events == []

    def test_title_capped_for_long_subject(self, monkeypatch):
        # Adversarial review F7: the attacker-controlled subject must not blow
        # past a sane title length on the calendar event.
        from app.quicksteps.handlers.deadline_actions import handle_create_calendar_event

        cal = _patch_calendar(monkeypatch)
        deadline = datetime.now(timezone.utc) + timedelta(days=10)
        result = handle_create_calendar_event(
            _ctx(_FakeEmail(deadline_at=deadline, subject="X" * 300)),
            {"days_before": 1, "duration_minutes": 30},
        )
        assert result.ok is True
        assert len(cal.events[0].title) <= 140
        assert cal.events[0].title.startswith("⏰ ")


# --------------------------------------------------------------------------- #
# Deadline resolution — SQL column path (layer 2)
# --------------------------------------------------------------------------- #

from contextlib import contextmanager  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db.models.email import Email  # noqa: E402


@pytest.fixture
def db_session(engine):
    """Patch get_db_session onto the in-memory test engine so the handler's
    SQL deadline lookup (layer 2) is isolated from the on-disk DB."""
    SessionLocal = sessionmaker(bind=engine, autoflush=False)

    @contextmanager
    def fake_session_cm():
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.db.database.get_db_session", fake_session_cm)
        yield SessionLocal()


class TestDeadlineResolutionFromSql:
    def test_reads_deadline_from_sql_when_attribute_absent(self, db_session, sample_account, monkeypatch):
        # ctx.email carries no usable deadline_at, but the ingest pipeline
        # stamped emails.deadline_at — _resolve_deadline_at layer 2 must read
        # it (keyed on the provider email_id, not the int PK).
        deadline = datetime.now(timezone.utc) + timedelta(days=20)
        db_session.add(Email(
            email_id="msg-sql",
            account_id=sample_account.id,
            thread_id="t1",
            sender="x@y.com",
            subject="Invoice",
            date=datetime.utcnow(),
            deadline_at=deadline.replace(tzinfo=None),
        ))
        db_session.commit()

        calls = _patch_add_reminder(monkeypatch)
        ctx = ExecutionContext(
            provider=object(),
            account_id=sample_account.id,
            account_email="me@x.com",
            account_display_name="Me",
            email=_FakeEmail(deadline_at=None, body="no inline date"),
            email_id="msg-sql",
            raw_id="msg-sql",
            template_vars={},
        )
        from app.quicksteps.handlers.deadline_actions import handle_create_reminder
        result = handle_create_reminder(ctx, {"days_before": 1})

        assert result.ok is True
        fired = datetime.fromisoformat(calls[0]["reminder_date_iso"])
        assert abs((fired - (deadline - timedelta(days=1))).total_seconds()) < 5
