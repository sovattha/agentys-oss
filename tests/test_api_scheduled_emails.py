# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests pour les endpoints REST de schedule send.

Endpoints:
- POST   /api/emails/schedule
- GET    /api/emails/scheduled
- DELETE /api/emails/scheduled/<id>
- PATCH  /api/emails/scheduled/<id>
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest


@pytest.fixture()
def app():
    from app.api.app import create_app

    app = create_app(config={"TESTING": True})
    app.config["TESTING"] = True
    return app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def store(tmp_path):
    """Store SQLite isole par test, injecte comme default global."""
    from app.services.scheduled_email_store import (
        ScheduledEmailStore,
        reset_default_store,
    )

    s = ScheduledEmailStore(db_path=str(tmp_path / "sched.db"))
    reset_default_store(s)
    yield s
    reset_default_store(None)


@pytest.fixture(autouse=True)
def _mock_account():
    mock = Mock()
    mock.id = "test-account"
    mock.email = "test@example.com"
    with patch(
        "app.api.scheduled_emails._get_current_account_for_user",
        return_value=mock,
    ), patch(
        "app.api.scheduled_emails._resolve_account_id_cached",
        return_value=42,
    ):
        yield mock


# ── POST /api/emails/schedule ──────────────────────────────────────────────


class TestScheduleNewEmail:
    def test_schedule_new_email_success(self, client, store):
        send_at = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        resp = client.post(
            "/api/emails/schedule",
            json={
                "to": "alice@example.com",
                "subject": "Bonjour",
                "body": "Salut Alice",
                "send_at": send_at,
            },
        )
        assert resp.status_code == 201, resp.get_data(as_text=True)
        data = resp.get_json()
        assert data["scheduled_id"]
        assert data["status"] == "pending"

        row = store.get_by_id(data["scheduled_id"])
        assert row is not None
        assert row["account_id"] == 42
        assert row["payload"]["to"] == ["alice@example.com"]
        assert row["payload"]["subject"] == "Bonjour"

    def test_schedule_reply_with_metadata(self, client, store):
        send_at = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
        resp = client.post(
            "/api/emails/schedule",
            json={
                "to": "alice@example.com",
                "subject": "Re: hello",
                "body": "Reponse",
                "send_at": send_at,
                "reply_to_id": "msg-orig-123",
                "thread_id": "thread-9",
            },
        )
        assert resp.status_code == 201, resp.get_data(as_text=True)
        sched_id = resp.get_json()["scheduled_id"]
        row = store.get_by_id(sched_id)
        assert row["payload"]["reply_to_id"] == "msg-orig-123"
        assert row["payload"]["thread_id"] == "thread-9"

    def test_schedule_rejects_past_send_at(self, client):
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        resp = client.post(
            "/api/emails/schedule",
            json={"to": "a@example.com", "subject": "x", "body": "y", "send_at": past},
        )
        assert resp.status_code == 400
        assert "send_at" in resp.get_json().get("error", "").lower()

    def test_schedule_rejects_missing_recipient(self, client):
        send_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        resp = client.post(
            "/api/emails/schedule",
            json={"to": "", "subject": "x", "body": "y", "send_at": send_at},
        )
        assert resp.status_code == 400

    def test_schedule_rejects_invalid_send_at(self, client):
        resp = client.post(
            "/api/emails/schedule",
            json={
                "to": "a@example.com",
                "subject": "x",
                "body": "y",
                "send_at": "pas-une-date",
            },
        )
        assert resp.status_code == 400

    def test_schedule_emits_websocket_event(self, client, store):
        send_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        with patch("app.api.scheduled_emails.emit_email_scheduled") as ws_mock:
            resp = client.post(
                "/api/emails/schedule",
                json={
                    "to": "a@example.com",
                    "subject": "x",
                    "body": "y",
                    "send_at": send_at,
                },
            )
        assert resp.status_code == 201
        ws_mock.assert_called_once()
        kw = ws_mock.call_args.kwargs
        assert kw.get("account_id") == 42


# ── GET /api/emails/scheduled ──────────────────────────────────────────────


class TestListScheduled:
    def test_list_returns_pending_for_account(self, client, store):
        send_at = datetime.now(timezone.utc) + timedelta(hours=1)
        sid_a = store.insert(
            account_id=42,
            payload={"to": ["a@x.com"], "subject": "A", "body": "x"},
            send_at=send_at,
        )
        store.insert(
            account_id=99,  # autre compte
            payload={"to": ["b@x.com"], "subject": "B", "body": "x"},
            send_at=send_at,
        )

        resp = client.get("/api/emails/scheduled")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "items" in data
        ids = {it["id"] for it in data["items"]}
        assert sid_a in ids
        assert len(data["items"]) == 1

    def test_list_includes_count(self, client, store):
        send_at = datetime.now(timezone.utc) + timedelta(hours=1)
        for i in range(3):
            store.insert(
                account_id=42,
                payload={"to": [f"a{i}@x.com"], "subject": str(i), "body": "x"},
                send_at=send_at,
            )
        resp = client.get("/api/emails/scheduled")
        data = resp.get_json()
        assert data["count"] == 3


# ── DELETE /api/emails/scheduled/<id> ──────────────────────────────────────


class TestCancelScheduled:
    def test_cancel_existing_pending(self, client, store):
        sid = store.insert(
            account_id=42,
            payload={"to": ["a@x.com"], "subject": "x", "body": "x"},
            send_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        with patch("app.api.scheduled_emails.emit_email_schedule_canceled") as ws_mock:
            resp = client.delete(f"/api/emails/scheduled/{sid}")
        assert resp.status_code == 200
        assert store.get_by_id(sid)["status"] == "cancelled"
        ws_mock.assert_called_once()

    def test_cancel_unknown_returns_404(self, client, store):
        resp = client.delete("/api/emails/scheduled/ghost")
        assert resp.status_code == 404

    def test_cancel_other_account_forbidden(self, client, store):
        sid = store.insert(
            account_id=99,
            payload={"to": ["a@x.com"], "subject": "x", "body": "x"},
            send_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        resp = client.delete(f"/api/emails/scheduled/{sid}")
        assert resp.status_code in (403, 404)
        # Le row de l'autre compte doit rester intact
        assert store.get_by_id(sid)["status"] == "pending"


# ── PATCH /api/emails/scheduled/<id> ───────────────────────────────────────


class TestPatchScheduled:
    def test_patch_send_at_updates_row(self, client, store):
        sid = store.insert(
            account_id=42,
            payload={"to": ["a@x.com"], "subject": "x", "body": "x"},
            send_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        new_at = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        with patch("app.api.scheduled_emails.emit_email_schedule_updated") as ws_mock:
            resp = client.patch(
                f"/api/emails/scheduled/{sid}",
                json={"send_at": new_at},
            )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        ws_mock.assert_called_once()

        row = store.get_by_id(sid)
        rsend = row["send_at"]
        if rsend.tzinfo is None:
            rsend = rsend.replace(tzinfo=timezone.utc)
        diff = (rsend - datetime.fromisoformat(new_at)).total_seconds()
        assert abs(diff) < 2

    def test_patch_payload_updates_subject_and_body(self, client, store):
        sid = store.insert(
            account_id=42,
            payload={"to": ["a@x.com"], "subject": "old", "body": "old"},
            send_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        resp = client.patch(
            f"/api/emails/scheduled/{sid}",
            json={"subject": "nouveau", "body": "corps mis a jour"},
        )
        assert resp.status_code == 200
        row = store.get_by_id(sid)
        assert row["payload"]["subject"] == "nouveau"
        assert row["payload"]["body"] == "corps mis a jour"

    def test_patch_rejects_past_send_at(self, client, store):
        sid = store.insert(
            account_id=42,
            payload={"to": ["a@x.com"], "subject": "x", "body": "x"},
            send_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        resp = client.patch(f"/api/emails/scheduled/{sid}", json={"send_at": past})
        assert resp.status_code == 400

    def test_patch_other_account_forbidden(self, client, store):
        sid = store.insert(
            account_id=99,
            payload={"to": ["a@x.com"], "subject": "x", "body": "x"},
            send_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        new_at = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        resp = client.patch(
            f"/api/emails/scheduled/{sid}", json={"send_at": new_at}
        )
        assert resp.status_code in (403, 404)


# ── POST /api/emails/scheduled/<id>/send-now ───────────────────────────────


class TestSendScheduledNow:
    def test_send_now_dispatches_via_scheduler(self, client, store):
        sid = store.insert(
            account_id=42,
            payload={"to": ["a@x.com"], "subject": "x", "body": "x"},
            send_at=datetime.now(timezone.utc) + timedelta(hours=2),
        )

        def fake_dispatch(sched_id, account_id):
            # The real scheduler claims the row and marks it sent — emulate
            # that here so the endpoint's post-dispatch refetch sees "sent".
            store.claim_for_send(sched_id)
            store.mark_sent(sched_id, message_id="msg-now")
            return True, None

        with patch(
            "app.services.scheduled_email_scheduler.get_default_scheduler"
        ) as get_scheduler_mock:
            scheduler = Mock()
            scheduler.dispatch_now.side_effect = fake_dispatch
            get_scheduler_mock.return_value = scheduler
            resp = client.post(f"/api/emails/scheduled/{sid}/send-now")

        assert resp.status_code == 200, resp.get_data(as_text=True)
        scheduler.dispatch_now.assert_called_once_with(sid, account_id=42)
        assert store.get_by_id(sid)["status"] == "sent"

    def test_send_now_returns_502_on_dispatch_failure(self, client, store):
        sid = store.insert(
            account_id=42,
            payload={"to": ["a@x.com"], "subject": "x", "body": "x"},
            send_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        with patch(
            "app.services.scheduled_email_scheduler.get_default_scheduler"
        ) as get_scheduler_mock:
            scheduler = Mock()
            scheduler.dispatch_now.return_value = (False, "provider down")
            get_scheduler_mock.return_value = scheduler
            resp = client.post(f"/api/emails/scheduled/{sid}/send-now")

        assert resp.status_code == 502
        assert "provider down" in resp.get_json()["error"]

    def test_send_now_unknown_returns_404(self, client):
        resp = client.post("/api/emails/scheduled/ghost/send-now")
        assert resp.status_code == 404

    def test_send_now_rejects_non_pending(self, client, store):
        sid = store.insert(
            account_id=42,
            payload={"to": ["a@x.com"], "subject": "x", "body": "x"},
            send_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        store.cancel(sid)
        resp = client.post(f"/api/emails/scheduled/{sid}/send-now")
        assert resp.status_code == 409

    def test_send_now_other_account_forbidden(self, client, store):
        sid = store.insert(
            account_id=99,
            payload={"to": ["a@x.com"], "subject": "x", "body": "x"},
            send_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        resp = client.post(f"/api/emails/scheduled/{sid}/send-now")
        assert resp.status_code in (403, 404)
        # The other account's row must remain pending, untouched.
        assert store.get_by_id(sid)["status"] == "pending"
