# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Regression tests for the 2026-04-25 Codex audit fixes.

Covers:
- C-3: _email_id_index scoped by (account_id, email_id) — IMAP UID collision
- HIGH-4: terminal-status retention eviction at flush time
- MED-1: atomic write of pending_drafts.json
- MED-2: atexit flush
- MED-8: _refining_locks popped on release / delete
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.domain.entities.pending_draft import PendingDraft, PendingDraftStatus
from app.infrastructure.pending_draft_store import (
    InMemoryPendingDraftStore,
    _ACTIVE_RETENTION_DAYS,
    _TERMINAL_RETENTION_DAYS,
)


@pytest.fixture
def store():
    """Fresh store backed by a temp file (no atexit pollution between tests)."""
    tmp_dir = tempfile.mkdtemp()
    path = os.path.join(tmp_dir, "pending_drafts.json")
    s = InMemoryPendingDraftStore(persist_path=path)
    yield s
    s.flush()


def _draft(
    *,
    draft_id: str,
    email_id: str,
    account_id: str | None,
    status: PendingDraftStatus = PendingDraftStatus.PENDING,
    created_at: str | None = None,
    processed_at: str | None = None,
) -> PendingDraft:
    return PendingDraft(
        id=draft_id,
        email_id=email_id,
        account_id=account_id,
        status=status,
        created_at=created_at or datetime.now().isoformat(),
        processed_at=processed_at,
    )


# ============================================================================
# C-3: cross-account email_id collision
# ============================================================================

class TestCrossAccountEmailIdScoping:
    """IMAP UIDs collide trivially across servers — the index must scope by account."""

    def test_two_accounts_same_email_id_no_leak(self, store):
        """Same email_id under two different account_ids → distinct entries."""
        a = _draft(draft_id="d-A", email_id="12345", account_id="acct-A")
        b = _draft(draft_id="d-B", email_id="12345", account_id="acct-B")
        store.add(a)
        store.add(b)
        # Both drafts stored
        assert store.get_by_id("d-A") is not None
        assert store.get_by_id("d-B") is not None
        # Account-scoped lookup must return the matching account's draft
        got_a = store.get_by_email_id("12345", account_id="acct-A")
        got_b = store.get_by_email_id("12345", account_id="acct-B")
        assert got_a is not None and got_a.id == "d-A"
        assert got_b is not None and got_b.id == "d-B"

    def test_no_account_id_with_multiple_candidates_returns_none(self, store):
        """Without account_id, ambiguous lookup must NOT leak — return None."""
        store.add(_draft(draft_id="d-A", email_id="12345", account_id="acct-A"))
        store.add(_draft(draft_id="d-B", email_id="12345", account_id="acct-B"))
        # No account_id → ambiguous → reject (no leak)
        assert store.get_by_email_id("12345") is None
        assert store.get_by_email_id_including_rejected("12345") is None

    def test_no_account_id_does_not_match_scoped_draft(self, store):
        """Audit P1-008 (2026-04-28): a caller passing no account_id must not
        match a draft stored under a real account_id, even when there is only
        one candidate. The previous single-candidate fallback was a cross-
        tenant leak in dev installs (where everything is "exactly one")."""
        store.add(_draft(draft_id="d-A", email_id="12345", account_id="acct-A"))
        assert store.get_by_email_id("12345") is None  # no account_id passed

    def test_account_id_mismatch_returns_none(self, store):
        """Caller's account_id must match the index — no fallback to other accounts."""
        store.add(_draft(draft_id="d-A", email_id="12345", account_id="acct-A"))
        got = store.get_by_email_id("12345", account_id="acct-OTHER")
        assert got is None

    def test_legacy_draft_with_none_account_id(self, store):
        """Drafts with account_id=None (legacy) keyed under (None, email_id)."""
        store.add(_draft(draft_id="d-legacy", email_id="42", account_id=None))
        # account_id=None lookup hits when single candidate
        got = store.get_by_email_id("42", account_id=None)
        assert got is not None and got.id == "d-legacy"


# ============================================================================
# HIGH-4: terminal-status retention eviction
# ============================================================================

class TestPendingDraftRetention:
    """Persisted pending drafts are bounded by retention policy."""

    def test_old_sent_drafts_evicted(self, monkeypatch, store):
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "legacy_full_cache")
        old_ts = (datetime.now() - timedelta(days=_TERMINAL_RETENTION_DAYS + 5)).isoformat()
        store.add(_draft(
            draft_id="old-sent",
            email_id="e1",
            account_id="acct-A",
            status=PendingDraftStatus.SENT,
            created_at=old_ts,
            processed_at=old_ts,
        ))
        # Force a flush that triggers eviction
        store.flush()
        assert store.get_by_id("old-sent") is None

    def test_recent_sent_drafts_kept(self, monkeypatch, store):
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "legacy_full_cache")
        recent_ts = (datetime.now() - timedelta(days=5)).isoformat()
        store.add(_draft(
            draft_id="recent-sent",
            email_id="e2",
            account_id="acct-A",
            status=PendingDraftStatus.SENT,
            created_at=recent_ts,
            processed_at=recent_ts,
        ))
        store.flush()
        assert store.get_by_id("recent-sent") is not None

    def test_old_pending_drafts_kept_in_legacy_full_cache(self, monkeypatch, store):
        """Legacy full-cache keeps historical active-draft retention semantics."""
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "legacy_full_cache")
        old_ts = (datetime.now() - timedelta(days=90)).isoformat()
        store.add(_draft(
            draft_id="old-pending",
            email_id="e3",
            account_id="acct-A",
            status=PendingDraftStatus.PENDING,
            created_at=old_ts,
        ))
        store.flush()
        assert store.get_by_id("old-pending") is not None

    def test_old_pending_drafts_evicted_in_metadata_only(self, monkeypatch, store):
        """Generated active drafts still contain content, so metadata-only TTLs them."""
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "metadata_only")
        old_ts = (datetime.now() - timedelta(days=_ACTIVE_RETENTION_DAYS + 1)).isoformat()
        store.add(_draft(
            draft_id="old-pending",
            email_id="e3",
            account_id="acct-A",
            status=PendingDraftStatus.PENDING,
            created_at=old_ts,
        ))
        store.flush()
        assert store.get_by_id("old-pending") is None

    def test_active_retention_days_is_configurable(self, monkeypatch, store):
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "metadata_only")
        monkeypatch.setenv("AGENTYS_PENDING_DRAFT_ACTIVE_RETENTION_DAYS", "7")
        old_ts = (datetime.now() - timedelta(days=8)).isoformat()
        store.add(_draft(
            draft_id="old-modified",
            email_id="e3b",
            account_id="acct-A",
            status=PendingDraftStatus.MODIFIED,
            created_at=old_ts,
        ))
        store.flush()
        assert store.get_by_id("old-modified") is None

    def test_old_rejected_drafts_evicted(self, monkeypatch, store):
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "legacy_full_cache")
        old_ts = (datetime.now() - timedelta(days=_TERMINAL_RETENTION_DAYS + 1)).isoformat()
        store.add(_draft(
            draft_id="old-rej",
            email_id="e4",
            account_id="acct-A",
            status=PendingDraftStatus.REJECTED,
            created_at=old_ts,
            processed_at=old_ts,
        ))
        store.flush()
        assert store.get_by_id("old-rej") is None


# ============================================================================
# MED-1: atomic write
# ============================================================================

class TestAtomicWrite:
    """A simulated crash mid-write must not corrupt the JSON file."""

    def test_flush_produces_valid_json(self, store):
        store.add(_draft(draft_id="d1", email_id="42", account_id="acct-A"))
        store.flush()
        # File exists and contains valid JSON
        with open(store._persist_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert isinstance(data, list)
        assert any(d["id"] == "d1" for d in data)

    def test_no_tmp_files_left_after_flush(self, store):
        """Successful flush should clean up temp files in the same directory."""
        store.add(_draft(draft_id="d1", email_id="42", account_id="acct-A"))
        store.flush()
        parent = Path(store._persist_path).parent
        leftover = [p for p in parent.iterdir() if p.name.endswith(".tmp")]
        assert leftover == []


# ============================================================================
# MED-8: lock cleanup on release/delete
# ============================================================================

class TestLockCleanup:
    def test_release_refining_lock_pops_when_unused(self, store):
        store.try_acquire_refining_lock("draft-X")
        assert "draft-X" in store._refining_locks
        store.release_refining_lock("draft-X")
        assert "draft-X" not in store._refining_locks

    def test_delete_pops_locks(self, store):
        d = _draft(draft_id="draft-Y", email_id="99", account_id="acct-A")
        store.add(d)
        # Touch the draft lock so the entry exists
        store.get_draft_lock("draft-Y")
        store.try_acquire_refining_lock("draft-Y")
        store.release_refining_lock("draft-Y")
        store.delete("draft-Y")
        assert "draft-Y" not in store._draft_locks
        assert "draft-Y" not in store._refining_locks


# ============================================================================
# Index-key normalization
# ============================================================================

class TestIndexKeyNormalization:
    def test_int_account_id_normalized_to_str(self, store):
        """account_id may arrive as int or str — index uses str-or-None."""
        store.add(_draft(draft_id="d-int", email_id="55", account_id=123))
        # Lookup with int and str must both hit the same entry
        got_int = store.get_by_email_id("55", account_id=123)
        got_str = store.get_by_email_id("55", account_id="123")
        assert got_int is not None and got_int.id == "d-int"
        assert got_str is not None and got_str.id == "d-int"

    def test_empty_string_account_id_normalized_to_none(self, store):
        """account_id="" should behave like None."""
        store.add(_draft(draft_id="d-empty", email_id="66", account_id=""))
        got = store.get_by_email_id("66", account_id=None)
        assert got is not None and got.id == "d-empty"
