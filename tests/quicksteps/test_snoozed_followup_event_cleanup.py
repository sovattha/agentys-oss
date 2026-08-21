# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Regression tests for eager cleanup of snoozed follow-up drafts."""
from __future__ import annotations

from dataclasses import dataclass

from app.api.quicksteps_scheduler import (
    _thread_has_engagement_beyond_cold_send,
    process_snoozed_draft_replies_after_sync,
)


@dataclass
class _Draft:
    id: str
    email_id: str
    account_id: str = "42"
    routing_tier: str = "followup"


class _Store:
    def __init__(self, draft: _Draft):
        self.draft = draft
        self.deleted: list[str] = []

    def get_pending(self, limit=50, account_id=None):
        return [self.draft] if str(account_id) == self.draft.account_id else []

    def get_by_email_id(self, email_id, account_id=None):
        if email_id == self.draft.email_id and str(account_id) == self.draft.account_id:
            return self.draft
        return None

    def delete(self, draft_id):
        self.deleted.append(draft_id)
        return draft_id == self.draft.id


class _Container:
    def __init__(self, store: _Store | None = None):
        self._store = store

    def get_pending_draft_store(self):
        return self._store


class _Session:
    def __enter__(self):
        return object()

    def __exit__(self, exc_type, exc, tb):
        return False


class _Repo:
    def __init__(self, rows):
        self.rows = rows

    def get_by_thread(self, thread_id, account_id):
        return self.rows


def _wire(monkeypatch, *, store: _Store, rows: list[object], dismissed: list[str]):
    monkeypatch.setattr(
        "app.infrastructure.container.get_container",
        lambda: _Container(store),
    )
    monkeypatch.setattr("app.db.database.get_db_session", lambda: _Session())
    monkeypatch.setattr(
        "app.db.repositories.email_repository.EmailRepository",
        lambda session: _Repo(rows),
    )
    monkeypatch.setattr(
        "app.services.reminder_service.list_draft_followups",
        lambda account_id=None: [{"id": "rem-1", "email_id": store.draft.id}],
    )
    monkeypatch.setattr(
        "app.services.reminder_service.dismiss_reminder",
        lambda reminder_id, account_id=None: dismissed.append(reminder_id),
    )


def test_thread_engagement_helper_is_direction_agnostic():
    assert _thread_has_engagement_beyond_cold_send([object()]) is False
    assert _thread_has_engagement_beyond_cold_send([object(), object()]) is True


def test_sync_cleanup_deletes_snoozed_followup_when_thread_has_new_activity(monkeypatch):
    draft = _Draft(id="draft-1", email_id="thread-1")
    store = _Store(draft)
    dismissed: list[str] = []
    _wire(monkeypatch, store=store, rows=[object(), object()], dismissed=dismissed)

    killed = process_snoozed_draft_replies_after_sync(42, "me@example.com")

    assert killed == 1
    assert store.deleted == ["draft-1"]
    assert dismissed == ["rem-1"]


def test_sync_cleanup_keeps_snoozed_followup_when_thread_has_only_cold_send(monkeypatch):
    draft = _Draft(id="draft-1", email_id="thread-1")
    store = _Store(draft)
    dismissed: list[str] = []
    _wire(monkeypatch, store=store, rows=[object()], dismissed=dismissed)

    killed = process_snoozed_draft_replies_after_sync(42, "me@example.com")

    assert killed == 0
    assert store.deleted == []
    assert dismissed == []
