# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""`thread_has_user_reply` trigger condition + post-reply re-eval hook.

Covers the "auto-archive after reply" workflow:
  - The matcher returns True iff there is a sent email in the SQL `emails`
    table for (account_id, thread_id) dated AFTER the evaluated email —
    i.e. the user actually replied to it. A sent message that merely
    precedes the inbound email (the user started the thread) must NOT
    match, otherwise every reply to user-initiated outreach is archived
    on arrival (bug 2026-06-11, seeded rule "Archive after reply").
  - The matcher is account-scoped (no cross-tenant leaks).
  - The negate flag inverts the result.
  - `run_auto_triggers_async` is a thin wrapper around `run_auto_triggers`
    that hands the call to a daemon thread without blocking the caller.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
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


# Reference instants — the SQL `emails.date` column is naive-UTC by
# convention (app/utils/dates.py), so fixtures use fixed naive datetimes.
_T0 = datetime(2026, 6, 10, 12, 0, 0)   # user's initial outbound send
_T1 = datetime(2026, 6, 11, 8, 31, 0)   # inbound reply arrives
_T2 = datetime(2026, 6, 11, 9, 0, 0)    # user replies to the inbound


@dataclass
class _Email:
    id: str = "msg-inbox"
    thread_id: str = "thread-A"
    sender: str = "ext@partner.com"
    subject: str = ""
    body: str = ""
    body_html: str = ""
    recipients: str = ""
    attachments_meta: str = ""
    is_read: bool = False
    labels: object = None
    date: datetime | None = field(default_factory=lambda: _T1)


def _insert_sent_email(
    session,
    *,
    account_id: int,
    thread_id: str,
    email_id: str = "reply-1",
    date: datetime | None = None,
) -> None:
    """Insert a sent email row that the matcher should pick up."""
    session.add(Email(
        email_id=email_id,
        account_id=account_id,
        thread_id=thread_id,
        sender="me@example.com",
        subject="Re: ...",
        date=date if date is not None else _T2,
        is_sent=True,
    ))
    session.commit()


class TestThreadHasUserReplyMatcher:
    def test_returns_false_when_no_sent_email_in_thread(self, db_session, sample_account):
        result = auto_trigger._match_condition(
            {"type": "thread_has_user_reply", "value": "true"},
            _Email(thread_id="thread-A"),
            account_id=sample_account.id,
            email_id="msg-inbox",
        )
        assert result is False

    def test_returns_true_when_sent_email_exists_in_thread(self, db_session, sample_account):
        _insert_sent_email(db_session, account_id=sample_account.id, thread_id="thread-A")
        result = auto_trigger._match_condition(
            {"type": "thread_has_user_reply", "value": "true"},
            _Email(thread_id="thread-A"),
            account_id=sample_account.id,
            email_id="msg-inbox",
        )
        assert result is True

    def test_false_value_inverts_match(self, db_session, sample_account):
        # value="false" matches when there is NO sent email — useful for "I
        # haven't replied yet" rules that want to fire before any send.
        result = auto_trigger._match_condition(
            {"type": "thread_has_user_reply", "value": "false"},
            _Email(thread_id="thread-A"),
            account_id=sample_account.id,
            email_id="msg-inbox",
        )
        assert result is True

    def test_account_scoped(self, db_session, sample_account, sample_account_outlook):
        # A sent email from a different account in the same thread_id must
        # NOT trip the matcher — Gmail thread IDs are global-ish but the rule
        # has to be tenant-safe in case of any future collision.
        _insert_sent_email(
            db_session,
            account_id=sample_account_outlook.id,
            thread_id="thread-A",
        )
        result = auto_trigger._match_condition(
            {"type": "thread_has_user_reply", "value": "true"},
            _Email(thread_id="thread-A"),
            account_id=sample_account.id,
            email_id="msg-inbox",
        )
        assert result is False

    def test_negate_flips_result(self, db_session, sample_account):
        _insert_sent_email(db_session, account_id=sample_account.id, thread_id="thread-A")
        result = auto_trigger._match_condition(
            {"type": "thread_has_user_reply", "value": "true", "negate": True},
            _Email(thread_id="thread-A"),
            account_id=sample_account.id,
            email_id="msg-inbox",
        )
        # SQL has a sent email → raw_match=True → negate=True → False.
        assert result is False

    def test_empty_thread_id_returns_false(self, db_session, sample_account):
        # Defensive: emails without a thread_id (rare provider edge case) must
        # not accidentally match the empty-string thread.
        _insert_sent_email(db_session, account_id=sample_account.id, thread_id="thread-A")
        result = auto_trigger._match_condition(
            {"type": "thread_has_user_reply", "value": "true"},
            _Email(thread_id=""),
            account_id=sample_account.id,
            email_id="msg-inbox",
        )
        assert result is False

    def test_matches_on_conversation_id_for_standard_email_shape(
        self, db_session, sample_account,
    ):
        # Regression (2026-05-13): production failure where the rule never
        # fired. Provider-loaded inbox emails are ``StandardEmail`` instances
        # which expose ``conversation_id``, not ``thread_id`` — the matcher
        # must fall back to ``conversation_id`` so the SQL lookup actually
        # runs and the rule trips after a reply lands.
        @dataclass
        class _StandardEmailLike:
            id: str = "msg-inbox"
            conversation_id: str = "thread-A"
            sender: str = "ext@partner.com"
            subject: str = ""
            date: datetime | None = field(default_factory=lambda: _T1)

        _insert_sent_email(db_session, account_id=sample_account.id, thread_id="thread-A")
        result = auto_trigger._match_condition(
            {"type": "thread_has_user_reply", "value": "true"},
            _StandardEmailLike(),
            account_id=sample_account.id,
            email_id="msg-inbox",
        )
        assert result is True

    def test_account_id_zero_returns_false(self, db_session, sample_account):
        # account_id<=0 means the daemon couldn't resolve ownership; skip the
        # SQL query rather than reading without a tenant filter.
        _insert_sent_email(db_session, account_id=sample_account.id, thread_id="thread-A")
        result = auto_trigger._match_condition(
            {"type": "thread_has_user_reply", "value": "true"},
            _Email(thread_id="thread-A"),
            account_id=0,
            email_id="msg-inbox",
        )
        assert result is False


class TestThreadHasUserReplyOrdering:
    """The sent message must POSTDATE the evaluated email (bug 2026-06-11).

    "Archive after reply" means "the user replied to THIS message" — a sent
    email that merely exists earlier in the thread (user-initiated outreach)
    must not count as a reply to a message that arrived later.
    """

    def test_fresh_inbound_reply_to_user_initiated_thread_does_not_match(
        self, db_session, sample_account,
    ):
        # User sends first (_T0), contact replies (_T1). On arrival of the
        # inbound reply there is no user message AFTER it → no match, the
        # reply must stay in the inbox.
        _insert_sent_email(
            db_session, account_id=sample_account.id, thread_id="thread-A", date=_T0,
        )
        result = auto_trigger._match_condition(
            {"type": "thread_has_user_reply", "value": "true"},
            _Email(thread_id="thread-A", date=_T1),
            account_id=sample_account.id,
            email_id="msg-inbox",
        )
        assert result is False

    def test_post_reply_reeval_matches_original_email(self, db_session, sample_account):
        # Inbound arrives (_T1), user replies (_T2). The post-reply re-eval
        # re-runs the matcher on the original inbox email → match.
        _insert_sent_email(
            db_session, account_id=sample_account.id, thread_id="thread-A", date=_T2,
        )
        result = auto_trigger._match_condition(
            {"type": "thread_has_user_reply", "value": "true"},
            _Email(thread_id="thread-A", date=_T1),
            account_id=sample_account.id,
            email_id="msg-inbox",
        )
        assert result is True

    def test_newer_inbound_after_user_reply_does_not_match(
        self, db_session, sample_account,
    ):
        # User replied at _T2, then the contact answered again (after _T2).
        # That newer inbound needs attention → no match on its arrival.
        _insert_sent_email(
            db_session, account_id=sample_account.id, thread_id="thread-A", date=_T2,
        )
        newer_inbound = datetime(2026, 6, 11, 10, 0, 0)
        result = auto_trigger._match_condition(
            {"type": "thread_has_user_reply", "value": "true"},
            _Email(thread_id="thread-A", date=newer_inbound),
            account_id=sample_account.id,
            email_id="msg-inbox-2",
        )
        assert result is False

    def test_missing_date_fails_closed(self, db_session, sample_account):
        # Without the evaluated email's date the order is unknowable — fail
        # closed (no match) rather than archive a message that may be unread.
        _insert_sent_email(
            db_session, account_id=sample_account.id, thread_id="thread-A", date=_T2,
        )
        result = auto_trigger._match_condition(
            {"type": "thread_has_user_reply", "value": "true"},
            _Email(thread_id="thread-A", date=None),
            account_id=sample_account.id,
            email_id="msg-inbox",
        )
        assert result is False

    def test_aware_date_normalized_to_utc_before_comparison(
        self, db_session, sample_account,
    ):
        # The snapshot hands the matcher an AWARE datetime while the SQL
        # column is naive-UTC. Inbound wall-clock 10:00+02:00 = 08:00 UTC;
        # the user's reply at 09:00 UTC postdates it → must match. A naive
        # comparison (10:00 > 09:00) would wrongly conclude "no reply yet".
        _insert_sent_email(
            db_session, account_id=sample_account.id, thread_id="thread-A",
            date=datetime(2026, 6, 11, 9, 0, 0),
        )
        aware_inbound = datetime(
            2026, 6, 11, 10, 0, 0, tzinfo=timezone(timedelta(hours=2)),
        )
        result = auto_trigger._match_condition(
            {"type": "thread_has_user_reply", "value": "true"},
            _Email(thread_id="thread-A", date=aware_inbound),
            account_id=sample_account.id,
            email_id="msg-inbox",
        )
        assert result is True


class TestRunAutoTriggersAsync:
    def test_short_circuits_on_bad_inputs(self):
        # Defensive: degenerate inputs must not spawn a thread.
        captured: list[tuple] = []

        with patch("app.quicksteps.auto_trigger.run_auto_triggers", lambda *a, **kw: captured.append(("called",))):
            auto_trigger.run_auto_triggers_async(0, "email-1", _Email())
            auto_trigger.run_auto_triggers_async(1, "", _Email())
            auto_trigger.run_auto_triggers_async(1, "email-1", None)
        assert captured == []

    def test_forwards_to_run_auto_triggers(self):
        # Happy path: account_id+email_id+email_obj all present → worker
        # eventually calls run_auto_triggers. We use a threading.Event so the
        # assertion doesn't race the daemon thread.
        import threading
        done = threading.Event()
        seen: dict = {}

        def fake_run(account_id, email_id, email):
            seen["account_id"] = account_id
            seen["email_id"] = email_id
            seen["email"] = email
            done.set()

        with patch("app.quicksteps.auto_trigger.run_auto_triggers", fake_run):
            auto_trigger.run_auto_triggers_async(42, "msg-1", _Email(id="msg-1"))
        assert done.wait(timeout=2.0), "worker thread did not fire run_auto_triggers within 2s"
        assert seen["account_id"] == 42
        assert seen["email_id"] == "msg-1"
