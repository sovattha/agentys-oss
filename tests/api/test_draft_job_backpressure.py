# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest


@pytest.fixture
def client():
    from app.api.app import create_app

    app = create_app(config={"TESTING": True})
    return app.test_client()


def _mock_container():
    store = Mock()
    store.get_by_email_id.return_value = None
    container = Mock()
    container.get_pending_draft_store.return_value = store
    return container


def test_process_email_returns_retry_after_when_draft_queue_is_full(client):
    from app.api import routes_emails

    provider = Mock()
    full = SimpleNamespace(
        status="full",
        task_id="task-full",
        queue_depth=200,
        queue_max=200,
        active_workers=16,
        active_for_account=4,
        retry_after_seconds=12,
        enqueued=False,
        duplicate=False,
        full=True,
    )

    with patch("app.api.routes_emails._validate_email_id", return_value=True), \
         patch("app.api.routes_emails._rate_limited", return_value=(True, 0)), \
         patch("app.api.routes_emails._resolve_account_id_cached", return_value=1), \
         patch("app.api.routes_emails._get_authenticated_provider", return_value=provider), \
         patch("app.api.routes_emails._get_current_account_for_user", return_value=None), \
         patch.object(routes_emails._rh, "_get_container", return_value=_mock_container()), \
         patch("app.infrastructure.draft_job_queue.enqueue_draft_job", return_value=full), \
         patch("app.api.routes_emails._detach_provider_from_request") as detach:
        response = client.post(
            "/api/emails/email-queue-full/process",
            json={
                "force": True,
                "cached_email": {
                    "sender": "client@example.com",
                    "sender_name": "Client",
                    "to": ["agentys@example.com"],
                    "cc": [],
                    "subject": "Question",
                    "body": "Bonjour, pouvez-vous confirmer ?",
                    "body_text": "Bonjour, pouvez-vous confirmer ?",
                    "body_html": "",
                    "conversation_id": "thread-queue-full",
                },
            },
        )

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "12"
    assert response.get_json()["status"] == "busy"
    assert response.get_json()["queue_status"] == "full"
    assert response.get_json()["reason"] == "full"
    assert response.get_json()["queue_depth"] == 200
    assert response.get_json()["active_for_account"] == 4
    detach.assert_not_called()


def test_process_email_backpressure_response_includes_rejection_reason(client):
    from app.api import routes_emails

    provider = Mock()
    full = SimpleNamespace(
        status="full",
        task_id="task-full",
        queue_depth=0,
        queue_max=1000,
        active_workers=2,
        active_for_account=1,
        retry_after_seconds=3,
        backend="redis",
        rejection_reason="redis_lock_timeout",
        enqueued=False,
        duplicate=False,
        full=True,
    )

    with patch("app.api.routes_emails._validate_email_id", return_value=True), \
         patch("app.api.routes_emails._rate_limited", return_value=(True, 0)), \
         patch("app.api.routes_emails._resolve_account_id_cached", return_value=1), \
         patch("app.api.routes_emails._get_authenticated_provider", return_value=provider), \
         patch("app.api.routes_emails._get_current_account_for_user", return_value=None), \
         patch.object(routes_emails._rh, "_get_container", return_value=_mock_container()), \
         patch("app.infrastructure.draft_job_queue.enqueue_draft_job", return_value=full):
        response = client.post(
            "/api/emails/email-lock-timeout/process",
            json={"force": True},
        )

    assert response.status_code == 429
    data = response.get_json()
    assert data["queue_status"] == "full"
    assert data["reason"] == "redis_lock_timeout"
    assert data["backend"] == "redis"
    assert data["queue_depth"] == 0


def test_process_email_duplicate_job_returns_existing_task(client):
    from app.api import routes_emails

    duplicate = SimpleNamespace(
        status="duplicate",
        task_id="task-existing",
        queue_depth=8,
        queue_max=200,
        active_workers=4,
        active_for_account=1,
        retry_after_seconds=0,
        enqueued=False,
        duplicate=True,
        full=False,
    )

    with patch("app.api.routes_emails._validate_email_id", return_value=True), \
         patch("app.api.routes_emails._rate_limited", return_value=(True, 0)), \
         patch("app.api.routes_emails._resolve_account_id_cached", return_value=1), \
         patch("app.api.routes_emails._get_authenticated_provider", return_value=Mock()), \
         patch("app.api.routes_emails._get_current_account_for_user", return_value=None), \
         patch.object(routes_emails._rh, "_get_container", return_value=_mock_container()), \
         patch("app.infrastructure.draft_job_queue.enqueue_draft_job", return_value=duplicate), \
         patch("app.api.routes_emails._detach_provider_from_request") as detach:
        response = client.post(
            "/api/emails/email-duplicate/process",
            json={"force": True},
        )

    assert response.status_code == 202
    data = response.get_json()
    assert data["task_id"] == "task-existing"
    assert data["queue_status"] == "duplicate"
    assert data["status_url"] == "/api/draft-jobs/task-existing"
    detach.assert_not_called()


def test_draft_job_status_endpoint_returns_shared_redis_status(client):
    shared_status = {
        "status": "completed",
        "ready": True,
        "queue_wait_ms": 120,
        "run_ms": 430,
    }

    with patch("app.infrastructure.draft_job_queue.get_draft_job_status", return_value=shared_status):
        response = client.get("/api/draft-jobs/task-123456")

    assert response.status_code == 200
    data = response.get_json()
    assert data["task_id"] == "task-123456"
    assert data["status"] == "completed"
    assert data["ready"] is True
    assert data["queue_wait_ms"] == 120
    assert data["run_ms"] == 430


def test_draft_job_status_endpoint_returns_unknown_for_missing_job(client):
    with patch("app.infrastructure.draft_job_queue.get_draft_job_status", return_value=None):
        response = client.get("/api/draft-jobs/task-unknown")

    assert response.status_code == 404
    assert response.get_json() == {
        "task_id": "task-unknown",
        "status": "unknown",
        "ready": False,
    }


def test_process_email_load_mode_uses_header_account_for_queue(client, monkeypatch):
    from app.api import routes_emails

    monkeypatch.setenv("AGENTYS_LOAD_TEST_MODE", "true")
    monkeypatch.setenv("AGENTYS_MOCK_LLM", "true")
    monkeypatch.setenv("AGENTYS_MOCK_EMAIL_PROVIDER", "true")
    captured = {}
    submission = SimpleNamespace(
        status="duplicate",
        task_id="task-load-account",
        queue_depth=8,
        queue_max=200,
        active_workers=4,
        active_for_account=1,
        retry_after_seconds=0,
        enqueued=False,
        duplicate=True,
        full=False,
    )

    def fake_enqueue_draft_job(**kwargs):
        captured.update(kwargs)
        return submission

    with patch("app.api.routes_emails._validate_email_id", return_value=True), \
         patch("app.api.routes_emails._rate_limited", return_value=(True, 0)), \
         patch("app.api.routes_emails._resolve_account_id_cached", return_value=-1), \
         patch("app.api.routes_emails._get_authenticated_provider", return_value=Mock()), \
         patch("app.api.routes_emails._get_current_account_for_user", return_value=None), \
         patch.object(routes_emails._rh, "_get_container", return_value=_mock_container()), \
         patch("app.infrastructure.draft_job_queue.enqueue_draft_job", side_effect=fake_enqueue_draft_job), \
         patch("app.api.routes_emails._detach_provider_from_request"):
        response = client.post(
            "/api/emails/email-load-account/process",
            headers={"X-Account-Id": "7"},
            json={"force": True},
        )

    assert response.status_code == 202
    assert captured["account_id"] == 7
    assert captured["key"] == "7:email-load-account"


def test_process_email_redis_queue_passes_serializable_payload_and_keeps_provider_scoped(client):
    from app.api import routes_emails

    provider = Mock()
    captured = {}
    submission = SimpleNamespace(
        status="enqueued",
        task_id="task-redis",
        queue_depth=1,
        queue_max=1000,
        active_workers=0,
        active_for_account=1,
        retry_after_seconds=0,
        enqueued=True,
        duplicate=False,
        full=False,
        backend="redis",
    )

    def fake_enqueue_draft_job(**kwargs):
        captured.update(kwargs)
        return submission

    account = SimpleNamespace(id="acct-hash-1", email="user@example.com", user_id=42)
    with patch("app.api.routes_emails._validate_email_id", return_value=True), \
         patch("app.api.routes_emails._rate_limited", return_value=(True, 0)), \
         patch("app.api.routes_emails._resolve_account_id_cached", return_value=9), \
         patch("app.api.routes_emails._get_authenticated_provider", return_value=provider), \
         patch("app.api.routes_emails._get_current_account_for_user", return_value=account), \
         patch.object(routes_emails._rh, "_get_container", return_value=_mock_container()), \
         patch("app.infrastructure.draft_job_queue.draft_queue_backend", return_value="redis"), \
         patch("app.infrastructure.draft_job_queue.enqueue_draft_job", side_effect=fake_enqueue_draft_job), \
         patch("app.api.routes_emails._detach_provider_from_request") as detach:
        response = client.post(
            "/api/emails/email-redis/process",
            json={
                "force": True,
                "cached_email": {
                    "sender": "client@example.com",
                    "sender_name": "Client",
                    "to": ["agentys@example.com"],
                    "cc": [],
                    "subject": "Question",
                    "body": "Bonjour, pouvez-vous confirmer ?",
                    "body_text": "Bonjour, pouvez-vous confirmer ?",
                    "body_html": "",
                    "conversation_id": "thread-redis",
                },
            },
        )

    assert response.status_code == 202
    assert captured["payload"]["email_id"] == "email-redis"
    assert captured["payload"]["account_id"] == 9
    assert captured["payload"]["account_hash"] == "acct-hash-1"
    assert captured["payload"]["user_email"] == "user@example.com"
    assert captured["payload"]["user_id"] == 42
    assert captured["payload"]["cached_email"]["subject"] == "Question"
    detach.assert_not_called()
