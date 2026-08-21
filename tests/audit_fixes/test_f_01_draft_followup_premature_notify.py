# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""F-01 (2026-05-21) regression: check_and_notify must not pre-empt the
draft_followup wake-sweep.

Bug shape: ``reminder_service.check_and_notify`` (the always-on 60s reminder
loop) marked ``draft_followup`` reminders ``notified=True`` with no reply
check. That both surfaced the snoozed draft via ``/api/drafts`` unchecked AND
starved ``sweep_woken_draft_followups`` — it early-continues on
``notified=True``, so delete-on-reply / inbox-surface / the "Follow up" label
never fired. Blast: every account with a create_snoozed_followup_draft Quick
Step (the 2 starter follow-up rules ship enabled).

These tests drive the REAL ``reminder_service`` (isolated reminders.json)
through ``check_and_notify`` and then run the sweep against the same reminder
state — only the PendingDraft store and the provider are doubled. So they
prove end-to-end that the sweep still owns the wake transition after the 60s
loop has run. Codex audits these against the diff; the name states the finding.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional
from unittest.mock import patch

import pytest

from app.domain.entities.pending_draft import PendingDraft, PendingDraftStatus
from app.quicksteps.handlers.create_snoozed_followup_draft import (
    sweep_woken_draft_followups,
)


@pytest.fixture
def temp_reminders_file(tmp_path, monkeypatch):
    """Point reminder_service at an isolated reminders.json for the test."""
    path = tmp_path / "reminders.json"
    monkeypatch.setattr("app.services.reminder_service._REMINDERS_FILE", path)
    return path


@dataclass
class _ThreadMsg:
    sender: str


class _InMemoryStore:
    """Minimal PendingDraft store double exposing add/delete/get_by_id."""

    def __init__(self):
        self.items: dict[str, PendingDraft] = {}

    def add(self, draft: PendingDraft) -> str:
        self.items[draft.id] = draft
        return draft.id

    def delete(self, draft_id: str) -> bool:
        return self.items.pop(draft_id, None) is not None

    def get_by_id(self, draft_id: str) -> Optional[PendingDraft]:
        return self.items.get(draft_id)


class _Container:
    def __init__(self, store):
        self._store = store

    def get_pending_draft_store(self):
        return self._store


class _FakeProvider:
    """No apply_label attr → the label step no-ops cleanly (IMAP-like)."""

    def __init__(self, *, thread_messages=None):
        self._messages = thread_messages or []
        self.calls: list[str] = []

    def get_thread_messages(self, thread_id):
        self.calls.append(thread_id)
        return self._messages


def _seed_draft(store, *, draft_id="draft-f01", thread_id="thread-9"):
    draft = PendingDraft(
        id=draft_id,
        email_id=thread_id,
        email_sender="me@x.com",
        draft_subject="Re: Test",
        draft_body="follow up",
        routing_tier="followup",
        status=PendingDraftStatus.PENDING,
        account_id="42",
    )
    store.add(draft)
    return draft


def _due_draft_followup(*, draft_id: str) -> dict:
    """A draft_followup reminder whose wake date is in the past, unprocessed."""
    return {
        "id": "rem-f01",
        "email_id": draft_id,
        "subject": "Re: Test",
        "reminder_date": "2020-01-01T00:00:00+00:00",  # always in the past
        "notified": False,
        "account_id": 42,
        "type": "draft_followup",
    }


def _run_check_and_notify():
    """Fire the always-on 60s reminder loop once (no real toast)."""
    from app.services.reminder_service import check_and_notify
    with patch("app.infrastructure.notifications.notify.send"):
        check_and_notify()


def test_sweep_still_deletes_on_reply_after_check_and_notify(temp_reminders_file):
    """End-to-end F-01: after check_and_notify runs on a due draft_followup,
    the sweep must STILL detect the recipient's reply and DELETE the draft.

    Pre-fix, check_and_notify marked the reminder notified=True, so the sweep
    early-continued (deleted=0) and the stale relance draft survived + got
    surfaced unchecked.
    """
    store = _InMemoryStore()
    draft = _seed_draft(store)
    temp_reminders_file.write_text(json.dumps([_due_draft_followup(draft_id=draft.id)]))

    _run_check_and_notify()  # the 60s loop — must not pre-empt the sweep

    # Sanity: the loop left the reminder pending for the sweep to claim.
    assert json.loads(temp_reminders_file.read_text())[0]["notified"] is False

    # Recipient replied → the sweep deletes the draft + dismisses the reminder.
    provider = _FakeProvider(thread_messages=[
        _ThreadMsg(sender="me@x.com"),
        _ThreadMsg(sender="alex@acme.com"),  # the reply
    ])
    with patch(
        "app.infrastructure.container.get_container",
        return_value=_Container(store),
    ):
        counters = sweep_woken_draft_followups(
            account_id=42, account_email="me@x.com", provider=provider,
        )

    assert counters == {"checked": 1, "promoted": 0, "deleted": 1, "errors": 0}
    assert store.items == {}, "replied-to draft must be deleted, not surfaced"
    assert provider.calls == ["thread-9"]
    # dismiss_reminder removed the entry from the real reminders.json.
    assert json.loads(temp_reminders_file.read_text()) == []


def test_sweep_promotes_on_no_reply_after_check_and_notify(temp_reminders_file):
    """End-to-end F-01 (no-reply path): after check_and_notify, the sweep
    promotes the draft (flips notified=True) and surfaces it — proving the
    wake transition still happens, just owned by the sweep after its reply
    check, not the premature 60s loop.
    """
    store = _InMemoryStore()
    draft = _seed_draft(store)
    temp_reminders_file.write_text(json.dumps([_due_draft_followup(draft_id=draft.id)]))

    _run_check_and_notify()

    # Only self in the thread → no reply → promote + inbox-surface.
    provider = _FakeProvider(thread_messages=[_ThreadMsg(sender="me@x.com")])
    with patch(
        "app.infrastructure.container.get_container",
        return_value=_Container(store),
    ):
        counters = sweep_woken_draft_followups(
            account_id=42, account_email="me@x.com", provider=provider,
        )

    assert counters == {"checked": 1, "promoted": 1, "deleted": 0, "errors": 0}
    assert draft.id in store.items  # kept

    rows = json.loads(temp_reminders_file.read_text())
    # The original draft_followup reminder is now notified=True (this is what
    # surfaces the draft in /api/drafts).
    draft_followup_rows = [r for r in rows if r.get("type") == "draft_followup"]
    assert len(draft_followup_rows) == 1
    assert draft_followup_rows[0]["notified"] is True
    # An immediate-date 'followup' surface reminder was added for the inbox.
    assert any(r.get("type") == "followup" for r in rows)
