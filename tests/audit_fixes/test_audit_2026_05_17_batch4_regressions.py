"""Regression tests for audit batch4 fixes (2026-05-17).

Each test reproduces the exact bug shape Pass 1/Pass 2 identified, then
asserts the fix's user-visible behaviour. Codex audits these against the
diff, so the names are explicit about WHICH finding they cover.
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest


# ============================================================================
# F-02 — reminder_service: gate _mark_notified on sent=True + retry budget
# ============================================================================

@pytest.fixture
def temp_reminders_file(tmp_path, monkeypatch):
    """Point reminder_service at an isolated reminders.json for the test."""
    path = tmp_path / "reminders.json"
    monkeypatch.setattr(
        "app.services.reminder_service._REMINDERS_FILE",
        path,
    )
    return path


def _due_reminder(rid: str = "test-id-1", subject: str = "Test reminder") -> dict[str, Any]:
    """A reminder due 1 day in the past, not yet notified."""
    return {
        "id": rid,
        "email_id": "email-abc",
        "subject": subject,
        "reminder_date": "2020-01-01T00:00:00+00:00",  # always in the past
        "notified": False,
        "account_id": 42,
        "type": "snooze",
    }


def test_f02_mark_notified_skipped_when_notify_returns_false(temp_reminders_file):
    """F-02 core: notifier returning False (vs raising) must NOT mark notified.

    Before batch4, the code did `notify.send(...); _mark_notified(...)` with
    no inspection of the return value. All 4 platform notifiers return False
    on failure (FileNotFoundError on subprocess, etc.), so the user lost the
    reminder forever. The fix captures the bool and gates _mark_notified.
    """
    temp_reminders_file.write_text(json.dumps([_due_reminder()]))

    with patch(
        "app.infrastructure.notifications.notify.send",
        return_value=False,
    ):
        from app.services.reminder_service import check_and_notify
        check_and_notify()

    data = json.loads(temp_reminders_file.read_text())
    assert data[0]["notified"] is False, (
        "Reminder must remain pending so the next scheduler tick can retry — "
        "the False return is exactly the failure mode B-05's comment claimed "
        "to handle, but its implementation only caught raises."
    )
    assert data[0]["notify_attempts"] == 1, (
        "Each False return increments notify_attempts so the quarantine "
        "budget can bound retries (see test_f02_quarantine_after_max_attempts)."
    )


def test_f02_mark_notified_set_when_notify_returns_true(temp_reminders_file):
    """F-02 happy path: successful send marks notified, doesn't increment attempts."""
    temp_reminders_file.write_text(json.dumps([_due_reminder()]))

    with patch(
        "app.infrastructure.notifications.notify.send",
        return_value=True,
    ):
        from app.services.reminder_service import check_and_notify
        check_and_notify()

    data = json.loads(temp_reminders_file.read_text())
    assert data[0]["notified"] is True
    # notify_attempts may be absent (never written) on the happy path
    assert data[0].get("notify_attempts", 0) == 0


def test_f02_mark_notified_skipped_when_notify_raises(temp_reminders_file):
    """F-02 raise path: an exception inside notify.send still defers + counts."""
    temp_reminders_file.write_text(json.dumps([_due_reminder()]))

    with patch(
        "app.infrastructure.notifications.notify.send",
        side_effect=RuntimeError("toast layer crashed"),
    ):
        from app.services.reminder_service import check_and_notify
        check_and_notify()

    data = json.loads(temp_reminders_file.read_text())
    assert data[0]["notified"] is False
    assert data[0]["notify_attempts"] == 1


def test_f02_quarantine_after_max_attempts(temp_reminders_file):
    """F-02 retry budget: after _MAX_NOTIFY_ATTEMPTS failures, mark notified.

    Without this guard, a permanently-broken notifier loop logs a warning
    every 60s forever (the P1-002 retry-storm finding the audit merged into
    F-02). The 5-attempt cap is a noise/recovery trade-off; the entry is
    released so it doesn't re-fire, and an ERROR log signals ops.
    """
    from app.services.reminder_service import _MAX_NOTIFY_ATTEMPTS

    # Reminder already at one-below cap so the next failure trips quarantine.
    r = _due_reminder()
    r["notify_attempts"] = _MAX_NOTIFY_ATTEMPTS - 1
    temp_reminders_file.write_text(json.dumps([r]))

    with patch(
        "app.infrastructure.notifications.notify.send",
        return_value=False,
    ):
        from app.services.reminder_service import check_and_notify
        check_and_notify()

    data = json.loads(temp_reminders_file.read_text())
    assert data[0]["notified"] is True, (
        f"After {_MAX_NOTIFY_ATTEMPTS} failures, the entry must be quarantined "
        "(marked notified) to break the infinite-retry loop."
    )
    assert data[0]["notify_attempts"] == _MAX_NOTIFY_ATTEMPTS


def test_draft_followup_not_toasted_and_left_for_wake_sweep(temp_reminders_file):
    """draft_followup must not toast (F-02) and must NOT be marked notified
    by check_and_notify (F-01, 2026-05-21).

    F-02: draft_followup entries don't trigger a desktop toast — their wake
    surface is the drafts list, so they must never reach notify.send.

    F-01: the wake-time sweep (sweep_woken_draft_followups) is the SOLE owner
    of the notified flip — it does a get_thread_messages reply check, then
    deletes the draft (recipient replied) or marks notified to surface it (no
    reply). The earlier code marked draft_followup notified HERE, which both
    surfaced the draft with no reply check AND starved the sweep (it
    early-continues on notified=True). check_and_notify must leave it pending.
    """
    r = _due_reminder(rid="draft-id-1")
    r["type"] = "draft_followup"
    temp_reminders_file.write_text(json.dumps([r]))

    # No notify mock needed — draft_followup must not reach notify.send.
    with patch("app.infrastructure.notifications.notify.send") as send_mock:
        from app.services.reminder_service import check_and_notify
        check_and_notify()
        send_mock.assert_not_called()

    data = json.loads(temp_reminders_file.read_text())
    assert data[0]["notified"] is False, (
        "F-01: check_and_notify must NOT mark draft_followup notified — the "
        "wake-sweep owns that flip after its reply check. Marking it here "
        "surfaced the draft unchecked and starved the sweep."
    )
