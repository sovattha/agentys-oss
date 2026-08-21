# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Audit fix C-4 (2026-04-25 isolation report) — `EmailDaemon` ran the
blocked-sender / spam / pending-draft paths through
`AccountManager.get_current_account()`, a process-global singleton.

When the daemon polls multiple accounts in sequence (or when the API
flips the singleton from a request thread while the daemon thread is
mid-poll), the wrong user's blocklist gets applied to incoming emails:
user A's blocked sender silently filters user B's mail, and the
generated `PendingDraft` rows are filed to whichever account the
singleton happens to point at.

This test locks in:
  - `EmailDaemon` accepts an `account_id` field at construction.
  - When the field is set, the blocked-sender check queries
    `manager.accounts.get(self.account_id)` instead of the singleton —
    proven by mocking `accounts.get` and `get_current_account` and
    asserting the singleton is NOT consulted.
  - When the field is None we keep the legacy singleton fallback so
    `run_daemon.py` (single-account standalone) still works.

Run: `pytest tests/audit_fixes/test_c04_daemon_account_id.py -v`
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def fake_email():
    """Minimal StandardEmail-shaped object — only the attrs the daemon reads."""
    e = MagicMock()
    e.id = "msg-123"
    e.sender = "alice@external.com"
    e.subject = "Hello"
    e.body = ""
    e.received_at = None
    return e


def _make_daemon(account_id):
    """Build an EmailDaemon with mocks plugged in so __post_init__ doesn't
    spin up real LLM clients / providers."""
    from app.daemon import EmailDaemon

    return EmailDaemon(
        account_id=account_id,
        provider=MagicMock(),
        drafter=MagicMock(),
        critic=MagicMock(),
        prioritizer=MagicMock(),
        classifier=MagicMock(),
        tracker=MagicMock(),
        processed_drafts_tracker=MagicMock(),
        learning_manager=MagicMock(),
        draft_history=MagicMock(),
    )


def test_daemon_with_explicit_account_id_skips_singleton(fake_email):
    """When `self.account_id` is set, the blocklist must be read from
    `manager.accounts.get(self.account_id)` — NOT the singleton."""
    daemon = _make_daemon(account_id="acct-A")

    fake_account = MagicMock()
    fake_account.id = "acct-A"
    fake_manager = MagicMock()
    fake_manager.accounts = {"acct-A": fake_account}
    fake_manager.is_sender_allowed.return_value = False  # block this sender

    with patch("app.multi_accounts.get_account_manager", return_value=fake_manager):
        result = daemon._clean_and_validate_email(fake_email)

    # Singleton must not be touched when an explicit account_id is bound.
    fake_manager.get_current_account.assert_not_called()
    # Blocklist applied → email skipped with reason `blocked_sender`.
    assert getattr(result, "should_skip", False) is True
    assert getattr(result, "skip_reason", None) == "blocked_sender"
    fake_manager.is_sender_allowed.assert_called_with("acct-A", fake_email.sender)


def test_daemon_without_account_id_falls_back_to_singleton(fake_email):
    """Legacy path (`run_daemon.py` single-account mode): when account_id
    is None the daemon must still call `get_current_account()` so existing
    deployments don't break."""
    daemon = _make_daemon(account_id=None)

    fake_singleton_account = MagicMock()
    fake_singleton_account.id = "legacy-acct"
    fake_manager = MagicMock()
    fake_manager.get_current_account.return_value = fake_singleton_account
    fake_manager.is_sender_allowed.return_value = True  # don't block

    with patch("app.multi_accounts.get_account_manager", return_value=fake_manager):
        daemon._clean_and_validate_email(fake_email)

    # Singleton consulted exactly because we have no explicit binding.
    fake_manager.get_current_account.assert_called()
