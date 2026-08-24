# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests pour le store SQLite des emails programmés (schedule send).

Le store persiste les payloads d'envois différés (heure cible >> 15s du undo-send).
Pattern : SQLite thread-local connection, idempotent _init_db(), CRUD complet.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest


@pytest.fixture()
def store(tmp_path):
    from app.services.scheduled_email_store import ScheduledEmailStore

    db_path = str(tmp_path / "scheduled.db")
    return ScheduledEmailStore(db_path=db_path)


def _payload(**overrides):
    base = {
        "to": ["alice@example.com"],
        "subject": "Hello",
        "body": "Bonjour Alice",
        "cc": [],
        "bcc": [],
        "is_html": False,
        "reply_to_id": None,
        "thread_id": None,
        "attachments": [],
        "skip_signature": False,
        "signature_html": "",
        "ai_assisted": False,
        "from_name": None,
    }
    base.update(overrides)
    return base


# ── insertion + lecture ─────────────────────────────────────────────────────


def test_insert_and_get_by_id(store):
    send_at = datetime(2026, 5, 1, 8, 0, tzinfo=timezone.utc)
    sched_id = store.insert(account_id=42, payload=_payload(), send_at=send_at)

    assert isinstance(sched_id, str) and len(sched_id) > 8

    row = store.get_by_id(sched_id)
    assert row is not None
    assert row["account_id"] == 42
    assert row["status"] == "pending"
    assert row["payload"]["to"] == ["alice@example.com"]
    assert row["payload"]["subject"] == "Hello"
    assert row["idempotency_key"] == f"agentys-scheduled-{sched_id}@agentys.local"
    # send_at est sérialisé en ISO ; round-trip doit conserver l'instant
    assert row["send_at"].replace(tzinfo=timezone.utc) == send_at or row["send_at"] == send_at


def test_get_by_id_unknown_returns_none(store):
    assert store.get_by_id("ghost") is None


# ── crash recovery ──────────────────────────────────────────────────────────


def test_recover_stuck_sending_requeues_and_warns(store, monkeypatch):
    """Regression (chaos audit 2026-06-02, V6/D4): a row crashed in 'sending'
    is requeued to 'pending' so it isn't silently lost — but because it may have
    been DELIVERED before the crash (mark_sent runs only after the provider
    accepts), the requeue is a possible DUPLICATE send and must be surfaced
    (WARNING naming the ids) for sentinel_stuck_schedule, not done silently."""
    from app.services import scheduled_email_store

    send_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    sched_id = store.insert(account_id=7, payload=_payload(), send_at=send_at)
    assert store.claim_for_send(sched_id) is True  # pending -> sending

    warning = Mock()
    monkeypatch.setattr(scheduled_email_store.logger, "warning", warning)
    # negative threshold => threshold instant is in the future, so the
    # just-claimed 'sending' row reliably qualifies as stuck (no sleep).
    recovered = store.recover_stuck_sending(threshold_minutes=-1)

    assert recovered == 1
    row = store.get_by_id(sched_id)
    assert row is not None and row["status"] == "pending"  # requeued for next tick
    # the possible-duplicate requeue is surfaced, not silent
    warning.assert_called_once()
    log_message = warning.call_args.args[0] % warning.call_args.args[1:]
    assert sched_id in log_message
    assert "duplicate" in log_message.lower()


def test_recover_stuck_sending_noop_when_nothing_stuck(store, caplog):
    """No 'sending' rows => no requeue, no warning."""
    import logging

    store.insert(account_id=7, payload=_payload(),
                 send_at=datetime.now(timezone.utc) + timedelta(hours=1))
    with caplog.at_level(logging.WARNING):
        recovered = store.recover_stuck_sending(threshold_minutes=10)
    assert recovered == 0
    assert "requeueing" not in caplog.text.lower()


# ── listing ─────────────────────────────────────────────────────────────────


def test_list_by_account_returns_pending_only_by_default(store):
    send_at = datetime.now(timezone.utc) + timedelta(hours=1)
    a = store.insert(account_id=1, payload=_payload(), send_at=send_at)
    b = store.insert(account_id=1, payload=_payload(subject="B"), send_at=send_at)
    store.mark_sent(b, message_id="msg-x")
    store.insert(account_id=2, payload=_payload(subject="C"), send_at=send_at)

    rows = store.list_by_account(account_id=1)
    assert {r["id"] for r in rows} == {a}
    assert rows[0]["payload"]["subject"] == "Hello"


def test_list_by_account_with_status_filter(store):
    send_at = datetime.now(timezone.utc) + timedelta(hours=1)
    a = store.insert(account_id=1, payload=_payload(), send_at=send_at)
    b = store.insert(account_id=1, payload=_payload(subject="B"), send_at=send_at)
    store.mark_sent(b, message_id="msg-x")

    rows = store.list_by_account(account_id=1, statuses=("pending", "sent"))
    assert {r["id"] for r in rows} == {a, b}


def test_list_due_returns_pending_past_send_at(store):
    now = datetime.now(timezone.utc)
    past = store.insert(account_id=1, payload=_payload(subject="past"), send_at=now - timedelta(minutes=5))
    future = store.insert(account_id=1, payload=_payload(subject="future"), send_at=now + timedelta(hours=1))
    cancelled = store.insert(account_id=1, payload=_payload(subject="cancelled"), send_at=now - timedelta(minutes=10))
    store.cancel(cancelled)
    sent = store.insert(account_id=1, payload=_payload(subject="sent"), send_at=now - timedelta(minutes=10))
    store.mark_sent(sent, message_id="msg-z")

    due_ids = {r["id"] for r in store.list_due(now=now)}
    assert past in due_ids
    assert future not in due_ids
    assert cancelled not in due_ids
    assert sent not in due_ids


# ── transitions de status ──────────────────────────────────────────────────


def test_cancel_marks_status(store):
    sid = store.insert(
        account_id=1,
        payload=_payload(),
        send_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    assert store.cancel(sid) is True
    row = store.get_by_id(sid)
    assert row["status"] == "cancelled"


def test_cancel_already_sent_returns_false(store):
    sid = store.insert(
        account_id=1,
        payload=_payload(),
        send_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    store.mark_sent(sid, message_id="msg-1")
    assert store.cancel(sid) is False


def test_mark_sent_records_message_id(store):
    sid = store.insert(
        account_id=1,
        payload=_payload(),
        send_at=datetime.now(timezone.utc),
    )
    store.mark_sent(sid, message_id="m-42")
    row = store.get_by_id(sid)
    assert row["status"] == "sent"
    assert row["sent_message_id"] == "m-42"
    assert row["sent_at"] is not None


def test_mark_failed_records_error(store):
    sid = store.insert(
        account_id=1,
        payload=_payload(),
        send_at=datetime.now(timezone.utc),
    )
    store.mark_failed(sid, error="SMTP refused")
    row = store.get_by_id(sid)
    assert row["status"] == "failed"
    assert "SMTP refused" in row["error"]


def test_update_send_at_only_when_pending(store):
    sid = store.insert(
        account_id=1,
        payload=_payload(),
        send_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    new_dt = datetime.now(timezone.utc) + timedelta(days=2)
    assert store.update_send_at(sid, new_send_at=new_dt) is True
    row = store.get_by_id(sid)
    rsend = row["send_at"] if row["send_at"].tzinfo else row["send_at"].replace(tzinfo=timezone.utc)
    assert abs((rsend - new_dt).total_seconds()) < 1

    # Une fois envoyé, l'update doit refuser
    store.mark_sent(sid, message_id="m-1")
    assert store.update_send_at(sid, new_send_at=datetime.now(timezone.utc)) is False


def test_count_pending_by_account(store):
    send_at = datetime.now(timezone.utc) + timedelta(hours=1)
    store.insert(account_id=1, payload=_payload(), send_at=send_at)
    store.insert(account_id=1, payload=_payload(), send_at=send_at)
    store.insert(account_id=2, payload=_payload(), send_at=send_at)
    cancelled = store.insert(account_id=1, payload=_payload(), send_at=send_at)
    store.cancel(cancelled)

    assert store.count_pending(account_id=1) == 2
    assert store.count_pending(account_id=2) == 1
    assert store.count_pending(account_id=3) == 0


# ── isolation par compte ───────────────────────────────────────────────────


def test_get_by_id_can_filter_by_account(store):
    """Anti cross-tenant : un autre compte ne doit jamais voir/toucher le row."""
    sid = store.insert(
        account_id=1,
        payload=_payload(),
        send_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    assert store.get_by_id(sid, account_id=1) is not None
    assert store.get_by_id(sid, account_id=2) is None


def test_cancel_with_account_filter_rejects_other_tenant(store):
    sid = store.insert(
        account_id=1,
        payload=_payload(),
        send_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    assert store.cancel(sid, account_id=2) is False
    assert store.get_by_id(sid)["status"] == "pending"
    assert store.cancel(sid, account_id=1) is True


def test_delete_by_account_removes_all_statuses_for_account(store):
    send_at = datetime.now(timezone.utc) + timedelta(hours=1)
    pending = store.insert(account_id=1, payload=_payload(subject="pending"), send_at=send_at)
    sent = store.insert(account_id=1, payload=_payload(subject="sent"), send_at=send_at)
    other = store.insert(account_id=2, payload=_payload(subject="other"), send_at=send_at)
    store.mark_sent(sent, message_id="msg-1")

    assert store.delete_by_account(1) == 2

    assert store.get_by_id(pending) is None
    assert store.get_by_id(sent) is None
    assert store.get_by_id(other) is not None


def test_payload_with_reply_metadata_is_preserved(store):
    payload = _payload(
        reply_to_id="msg-orig-123",
        thread_id="thread-9",
        subject="Re: Hello",
    )
    sid = store.insert(
        account_id=1,
        payload=payload,
        send_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    row = store.get_by_id(sid)
    assert row["payload"]["reply_to_id"] == "msg-orig-123"
    assert row["payload"]["thread_id"] == "thread-9"
    assert row["payload"]["subject"] == "Re: Hello"
