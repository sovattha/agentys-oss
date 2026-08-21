# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Regression test: ``_EmailSnapshot.of`` must read `deadline_at` and
`emoji_marker_json` from the SQL Email row when the caller hands us a
provider-style object that doesn't expose those fields.

Reason this matters — the daemon classifier loop calls
``run_auto_triggers(..., email=<StandardEmail>)``. Provider StandardEmails
carry sender / subject / body but **not** the columns stamped by
ingest-time scanners (``deadline_at`` set by deadline_extractor, and
``emoji_marker_json`` stamped by mark_with_emoji). Without a SQL backfill
in ``_EmailSnapshot.of``, conditions like ``has_deadline_detected=true``
silently never match — exactly the production symptom this guards against.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from app.quicksteps import auto_trigger


@dataclass
class _ProviderEmail:
    """Mimics a provider StandardEmail — no deadline_at / emoji_marker_json."""
    id: str = "msg-deadline-1"
    sender: str = "billing@stripe.com"
    subject: str = "Facture"
    body: str = ""
    body_html: str = ""
    recipients: str = ""
    attachments_meta: str = ""
    thread_id: str = ""
    is_read: bool = False
    date: datetime | None = None


class _FakeSqlRow:
    """Stand-in for the SQLA Email row returned by EmailRepository."""
    def __init__(self, deadline_at=None, emoji_marker_json=""):
        self.deadline_at = deadline_at
        self.emoji_marker_json = emoji_marker_json


def _patch_repo(monkeypatch, sql_row):
    """Make ``EmailRepository.get_by_email_id`` return our fake row.

    Patches at the module path the snapshot helper imports from, not the
    original symbol — same trick the existing auto_trigger tests use.
    """
    class _FakeSession:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    class _FakeRepo:
        def __init__(self, session): pass
        def get_by_email_id(self, email_id, account_id=None):
            return sql_row

    # The snapshot does `from app.db.database import get_db_session` and
    # `from app.db.repositories.email_repository import EmailRepository`
    # inside the function — we patch the source modules so the lazy
    # imports resolve to our fakes.
    import app.db.database as _db
    import app.db.repositories.email_repository as _er
    monkeypatch.setattr(_db, "get_db_session", lambda: _FakeSession())
    monkeypatch.setattr(_er, "EmailRepository", _FakeRepo)


class TestSnapshotSqlBackfill:
    def test_deadline_backfilled_for_provider_email(self, monkeypatch):
        deadline = datetime(2026, 5, 31, 17, 0, tzinfo=timezone.utc)
        _patch_repo(monkeypatch, _FakeSqlRow(deadline_at=deadline))

        snap = auto_trigger._EmailSnapshot.of(_ProviderEmail(), account_id=42)

        assert snap.deadline_at == deadline, (
            "Provider object had no deadline_at attr; snapshot must hit SQL "
            "and read the column the deadline_extractor stamped at ingest."
        )

    def test_emoji_marker_backfilled_for_provider_email(self, monkeypatch):
        marker_json = '{"emoji": "⏰", "include_deadline": true}'
        _patch_repo(monkeypatch, _FakeSqlRow(emoji_marker_json=marker_json))

        snap = auto_trigger._EmailSnapshot.of(_ProviderEmail(), account_id=42)

        assert snap.emoji_marker_json == marker_json, (
            "Provider object had no emoji_marker_json attr; snapshot must "
            "hit SQL so chained rules using has_emoji_marker can fire."
        )

    def test_has_deadline_detected_matches_via_backfill(self, monkeypatch):
        """End-to-end: trigger condition matches when the SQL row has the
        date, even though the provider object passed in didn't expose it.
        """
        deadline = datetime(2026, 5, 31, 17, 0, tzinfo=timezone.utc)
        _patch_repo(monkeypatch, _FakeSqlRow(deadline_at=deadline))

        snap = auto_trigger._EmailSnapshot.of(_ProviderEmail(), account_id=42)
        match = auto_trigger._match_condition(
            {"type": "has_deadline_detected", "value": "true"},
            snap,
            account_id=42,
            email_id="msg-deadline-1",
        )
        assert match is True

    def test_no_account_id_skips_backfill(self, monkeypatch):
        """If we don't know which account to query, do NOT run the
        backfill — cross-account lookups would be unsafe AND we'd just
        return the wrong row."""
        repo_calls = {"n": 0}

        class _Repo:
            def __init__(self, session): pass
            def get_by_email_id(self, email_id, account_id=None):
                repo_calls["n"] += 1
                return _FakeSqlRow(deadline_at=datetime(2099, 1, 1, tzinfo=timezone.utc))

        import app.db.repositories.email_repository as _er
        monkeypatch.setattr(_er, "EmailRepository", _Repo)

        snap = auto_trigger._EmailSnapshot.of(_ProviderEmail(), account_id=0)
        assert snap.deadline_at is None
        assert repo_calls["n"] == 0, "account_id=0 must skip the backfill query"

    def test_sql_row_caller_short_circuits(self, monkeypatch):
        """When the caller already passed a row with deadline_at AND marker
        set, the snapshot must NOT call the EmailRepository again — backfill
        is gated on at-least-one missing column."""
        repo_calls = {"n": 0}

        class _Repo:
            def __init__(self, session): pass
            def get_by_email_id(self, email_id, account_id=None):
                repo_calls["n"] += 1
                return _FakeSqlRow()

        import app.db.repositories.email_repository as _er
        monkeypatch.setattr(_er, "EmailRepository", _Repo)

        @dataclass
        class _RowLike:
            id: str = "msg-1"
            sender: str = ""
            subject: str = ""
            body: str = ""
            body_html: str = ""
            recipients: str = ""
            attachments_meta: str = ""
            thread_id: str = ""
            is_read: bool = False
            date: datetime | None = None
            deadline_at: datetime | None = datetime(2026, 6, 1, tzinfo=timezone.utc)
            emoji_marker_json: str = '{"emoji": "⏰"}'

        snap = auto_trigger._EmailSnapshot.of(_RowLike(), account_id=42)
        assert snap.deadline_at == datetime(2026, 6, 1, tzinfo=timezone.utc)
        assert snap.emoji_marker_json == '{"emoji": "⏰"}'
        assert repo_calls["n"] == 0, (
            "Both fields already populated on the email object → no backfill query"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ============================================================================
# Regression: handle_mark_with_emoji must NOT trigger a SQL row DELETE
# ============================================================================
# 2026-05-14: the handler previously called evict_caches(email_id, raw_id)
# without a `folder=...` arg. That helper's no-folder branch schedules a
# background SQLite DELETE of the row — which wiped the marker the handler
# had just stamped. Audit log said `success: True`, but the column came
# back NULL on the next read. This test pins the contract: invalidating
# caches must NOT call repo.delete_by_email_id.

class TestMarkWithEmojiDoesNotDeleteRow:
    def test_handler_does_not_schedule_sqlite_delete(self, monkeypatch):
        """The handler stamps emoji_marker_json + invalidates in-memory
        caches. It must NOT route through _evict_email_from_all_caches
        (which deletes the row when called without move_to_folder)."""
        delete_calls = {"n": 0}

        # Capture any attempt to delete the row.
        import app.db.repositories.email_repository as _er
        original_repo = _er.EmailRepository

        class _Repo(original_repo):
            def delete_by_email_id(self, email_id, account_id=None):
                delete_calls["n"] += 1
                return super().delete_by_email_id(email_id, account_id=account_id)

        monkeypatch.setattr(_er, "EmailRepository", _Repo)

        # Stub out the SQL write so we don't need a real DB — we're only
        # testing that the handler's eviction path doesn't fan out to the
        # SQLite delete.
        class _FakeRow:
            emoji_marker_json = None

        class _FakeSession:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def commit(self): pass

        class _FakeRepoForWrite:
            def __init__(self, _s): pass
            def get_by_email_id(self, eid, account_id=None):
                return _FakeRow()

        # Patch the handler's import target. The handler does
        # `from app.api.routes_helpers import get_db_session` and
        # `from app.db.repositories.email_repository import EmailRepository`
        # inside the function — patch the source modules.
        import app.api.routes_helpers as _rh
        import app.db.repositories.email_repository as _er2
        monkeypatch.setattr(_rh, "get_db_session", lambda: _FakeSession())
        monkeypatch.setattr(_er2, "EmailRepository", _FakeRepoForWrite)

        # Stub the websocket emit so the test doesn't try to broadcast.
        import app.api.websocket as _ws
        monkeypatch.setattr(_ws, "emit_email_updated", lambda *a, **kw: None)

        # Stub the cache invalidation helpers to no-ops — we don't need
        # to assert their internals here, just that nothing routes to a
        # row delete.
        monkeypatch.setattr(_rh, "_invalidate_folder_cache", lambda: None)
        monkeypatch.setattr(_rh, "_invalidate_label_batch_cache", lambda: None)
        monkeypatch.setattr(_rh, "_email_detail_cache", {})
        import threading
        monkeypatch.setattr(_rh, "_email_detail_cache_lock", threading.Lock())

        from app.quicksteps.handlers.mark_with_emoji import handle_mark_with_emoji
        from app.quicksteps.types import ExecutionContext

        ctx = ExecutionContext(
            provider=None, account_id=42,
            account_email="user@x.com", account_display_name="",
            email=None, email_id="msg-stamped", raw_id="msg-stamped",
        )
        result = handle_mark_with_emoji(ctx, {"emoji": "⏰", "include_deadline": True})

        assert result.ok is True, f"handler should succeed: {result.error}"
        assert delete_calls["n"] == 0, (
            "Regression: handler triggered a row DELETE after stamping the "
            "marker. The previous bug went through evict_caches → "
            "_evict_email_from_all_caches → repo.delete_by_email_id, "
            "wiping the row the handler had just written to. Use the "
            "narrow in-memory cache invalidation path instead."
        )
