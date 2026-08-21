"""Regression tests for `_compute_thread_counts` in routes_emails.

Ensures the inbox/sent/trash list endpoints return accurate thread_count
values (not always 1, as the previous implementation did).
"""

from datetime import datetime, timedelta

from app.api.routes_emails import _compute_thread_counts
from app.db.models import Email


def test_returns_empty_for_no_thread_ids(session, sample_account):
    assert _compute_thread_counts(session, sample_account.id, []) == {}
    assert _compute_thread_counts(session, sample_account.id, [None, None]) == {}


def test_counts_messages_per_thread(session, sample_account):
    base = datetime.utcnow()
    # Thread A: 6 messages. Thread B: 2 messages. Standalone: 1 null thread.
    rows = []
    for i in range(6):
        rows.append(Email(
            email_id=f"a_{i}", thread_id="thread_A", account_id=sample_account.id,
            subject="A", sender="x@y.z", date=base - timedelta(minutes=i),
        ))
    for i in range(2):
        rows.append(Email(
            email_id=f"b_{i}", thread_id="thread_B", account_id=sample_account.id,
            subject="B", sender="x@y.z", date=base - timedelta(minutes=i),
        ))
    rows.append(Email(
        email_id="solo", thread_id=None, account_id=sample_account.id,
        subject="solo", sender="x@y.z", date=base,
    ))
    session.add_all(rows)
    session.commit()

    result = _compute_thread_counts(
        session, sample_account.id, ["thread_A", "thread_B", None]
    )
    assert result == {"thread_A": 6, "thread_B": 2}


def test_scoped_to_account(session, sample_account, sample_account_outlook):
    """Thread counts must not leak across accounts."""
    base = datetime.utcnow()
    # Same thread_id used in two different accounts — should be counted separately.
    for i in range(3):
        session.add(Email(
            email_id=f"gmail_{i}", thread_id="shared_id",
            account_id=sample_account.id,
            subject="G", sender="x@y.z", date=base - timedelta(minutes=i),
        ))
    for i in range(5):
        session.add(Email(
            email_id=f"ol_{i}", thread_id="shared_id",
            account_id=sample_account_outlook.id,
            subject="O", sender="x@y.z", date=base - timedelta(minutes=i),
        ))
    session.commit()

    gmail_counts = _compute_thread_counts(session, sample_account.id, ["shared_id"])
    outlook_counts = _compute_thread_counts(session, sample_account_outlook.id, ["shared_id"])
    assert gmail_counts == {"shared_id": 3}
    assert outlook_counts == {"shared_id": 5}


def test_dedup_thread_ids_in_input(session, sample_account):
    """Passing the same thread_id multiple times doesn't inflate the count."""
    base = datetime.utcnow()
    for i in range(4):
        session.add(Email(
            email_id=f"d_{i}", thread_id="thread_D", account_id=sample_account.id,
            subject="D", sender="x@y.z", date=base - timedelta(minutes=i),
        ))
    session.commit()

    result = _compute_thread_counts(
        session, sample_account.id, ["thread_D"] * 10
    )
    assert result == {"thread_D": 4}
