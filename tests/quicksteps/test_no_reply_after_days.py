# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""`no_reply_after_days` trigger condition — SQL-backed (table ``emails``).

Matches when the thread's most recent sent email is older than N days with
no inbound reply after it. Replaces the legacy FollowupTracker cross-check
(removed 2026-05) with a direct, account-scoped query on the emails table —
same shape as ``thread_has_user_reply``.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy.orm import sessionmaker

from app.db.models.email import Email
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
    id: str = "msg-current"
    thread_id: str = "thread-A"
    sender: str = ""
    subject: str = ""
    body: str = ""
    body_html: str = ""
    recipients: str = ""
    attachments_meta: str = ""
    is_read: bool = False
    labels: object = None


def _insert(session, *, account_id, thread_id, is_sent, days_ago, email_id, sender="me@example.com"):
    session.add(Email(
        email_id=email_id,
        account_id=account_id,
        thread_id=thread_id,
        sender=sender,
        subject="Re: ..." if is_sent else "Question",
        date=datetime.utcnow() - timedelta(days=days_ago),
        is_sent=is_sent,
    ))
    session.commit()


def _match(account_id, *, thread_id="thread-A", value="3", negate=False):
    cond = {"type": "no_reply_after_days", "value": value}
    if negate:
        cond["negate"] = True
    return auto_trigger._match_condition(
        cond,
        _Email(thread_id=thread_id),
        account_id=account_id,
        email_id="msg-current",
    )


class TestNoReplyAfterDays:
    def test_matches_when_sent_older_than_n_days_with_no_reply(self, db_session, sample_account):
        _insert(db_session, account_id=sample_account.id, thread_id="thread-A",
                is_sent=True, days_ago=10, email_id="sent-1")
        assert _match(sample_account.id) is True

    def test_no_match_when_sent_is_recent(self, db_session, sample_account):
        _insert(db_session, account_id=sample_account.id, thread_id="thread-A",
                is_sent=True, days_ago=1, email_id="sent-1")
        assert _match(sample_account.id) is False

    def test_no_match_when_inbound_reply_arrived_after_sent(self, db_session, sample_account):
        _insert(db_session, account_id=sample_account.id, thread_id="thread-A",
                is_sent=True, days_ago=10, email_id="sent-1")
        _insert(db_session, account_id=sample_account.id, thread_id="thread-A",
                is_sent=False, days_ago=2, email_id="in-1", sender="ext@partner.com")
        assert _match(sample_account.id) is False

    def test_no_match_when_no_sent_email_in_thread(self, db_session, sample_account):
        _insert(db_session, account_id=sample_account.id, thread_id="thread-A",
                is_sent=False, days_ago=10, email_id="in-1", sender="ext@partner.com")
        assert _match(sample_account.id) is False

    def test_account_scoped(self, db_session, sample_account, sample_account_outlook):
        # An old unanswered sent email in ANOTHER account's thread must not
        # trip the matcher for this account.
        _insert(db_session, account_id=sample_account_outlook.id, thread_id="thread-A",
                is_sent=True, days_ago=10, email_id="sent-1")
        assert _match(sample_account.id) is False

    def test_account_id_zero_returns_false(self, db_session, sample_account):
        _insert(db_session, account_id=sample_account.id, thread_id="thread-A",
                is_sent=True, days_ago=10, email_id="sent-1")
        assert _match(0) is False

    def test_negate_flips_result(self, db_session, sample_account):
        _insert(db_session, account_id=sample_account.id, thread_id="thread-A",
                is_sent=True, days_ago=10, email_id="sent-1")
        # raw_match=True → negate → False.
        assert _match(sample_account.id, negate=True) is False
