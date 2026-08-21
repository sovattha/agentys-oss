# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Audit fix B-06 (2026-06-11 backend-silent report) — wrong-severity.

`EmailDaemon._clean_and_validate_email` logged two production-affecting
failures at DEBUG level (invisible in prod):
  - the blocked-sender check failing (broken blocklist store) — blocked
    senders keep being processed with zero signal;
  - the auto-move-to-spam provider call failing — the learned-spam email
    stays in the inbox silently.

Both are promoted to WARNING. These tests lock in the new level.

Run: `pytest tests/audit_fixes/test_b06_daemon_blocklist_warning.py -v`
"""

from __future__ import annotations

import logging
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
    """Build an EmailDaemon with mocks plugged in (pattern test_c04)."""
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
        # Injecté pour ne pas toucher la DB commitments locale (schéma de
        # l'env de dev divergent — même cause que l'échec actuel de test_c04).
        commitment_use_case=MagicMock(),
    )


def test_blocked_sender_check_failure_logs_warning(fake_email, caplog):
    """Store de blocklist cassé → le check est sauté, mais on doit le VOIR :
    WARNING, plus DEBUG."""
    daemon = _make_daemon(account_id="acct-A")

    with patch(
        "app.multi_accounts.get_account_manager",
        side_effect=RuntimeError("blocklist store corrupted"),
    ), caplog.at_level(logging.WARNING, logger="app.daemon"):
        daemon._clean_and_validate_email(fake_email)

    blocked_warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING
        and "Failed to check blocked sender" in r.getMessage()
    ]
    assert blocked_warnings, (
        "the blocked-sender check failure must surface at WARNING level"
    )


def test_auto_move_spam_failure_logs_warning(fake_email, caplog):
    """Expéditeur appris comme spam mais move_to_spam lève → l'email reste en
    inbox : doit logger un WARNING (l'email est quand même skippé)."""
    daemon = _make_daemon(account_id="acct-A")
    daemon.provider.move_to_spam.side_effect = RuntimeError("provider down")

    fake_account = MagicMock()
    fake_account.id = "acct-A"
    fake_account.spammed_senders = ["alice@external.com"]
    fake_account.spammed_domains = []
    fake_manager = MagicMock()
    fake_manager.accounts = {"acct-A": fake_account}
    fake_manager.is_sender_allowed.return_value = True  # pas bloqué

    with patch(
        "app.multi_accounts.get_account_manager", return_value=fake_manager
    ), caplog.at_level(logging.WARNING, logger="app.daemon"):
        result = daemon._clean_and_validate_email(fake_email)

    # Le verdict spam tient toujours (skip), seul le move a échoué.
    assert getattr(result, "should_skip", False) is True
    assert getattr(result, "skip_reason", None) == "spammed_sender"

    spam_warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING
        and "Failed to auto-move to spam" in r.getMessage()
    ]
    assert spam_warnings, (
        "the auto-move-to-spam failure must surface at WARNING level"
    )
