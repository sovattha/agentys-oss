# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Regression tests for local-only email bodies in draft generation."""

import hashlib
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest


@pytest.fixture
def app():
    from app.api.app import create_app

    app = create_app(config={"TESTING": True})
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def _cached_email_payload(**overrides):
    payload = {
        "id": "email-123",
        "sender": "alex@example.com",
        "sender_name": "Alex",
        "subject": "Question",
        "received_at": "2026-05-18T08:00:00Z",
        "body": "Local cached body",
        "body_html": "<p>Local cached body</p>",
        "body_text": "Local cached body",
        "conversation_id": "thread-123",
        "to": ["nat@example.com"],
        "cc": [],
        "source": "local_email_body_cache",
    }
    payload.update(overrides)
    return payload


def _queue_submission(status="enqueued", task_id="task-test"):
    return SimpleNamespace(
        status=status,
        task_id=task_id,
        queue_depth=0,
        queue_max=10,
        active_workers=0,
        active_for_account=0,
        retry_after_seconds=0,
        enqueued=status == "enqueued",
        duplicate=status == "duplicate",
        full=status == "full",
    )


def _immediate_enqueue_draft_job(**kwargs):
    kwargs["run"]()
    return _queue_submission(task_id=kwargs["task_id"])


def _noop_enqueue_draft_job(**kwargs):
    return _queue_submission(task_id=kwargs["task_id"])


def test_cached_process_payload_builds_standard_email(app):
    from app.api.routes_emails import _standard_email_from_cached_process_payload

    with app.app_context():
        email, error = _standard_email_from_cached_process_payload(
            "email-123",
            _cached_email_payload(),
        )

    assert error is None
    assert email.id == "email-123"
    assert email.sender == "alex@example.com"
    assert email.subject == "Question"
    assert email.body == "Local cached body"
    assert email.body_html == "<p>Local cached body</p>"
    assert email.conversation_id == "thread-123"
    assert email.provider_source == "client_cache"


def test_detail_cache_payload_builds_standard_email(app):
    from app.api.routes_emails import _standard_email_from_detail_cache

    cached = {
        "id": "email-123",
        "sender": "alex@example.com",
        "sender_name": "Alex",
        "subject": "Question",
        "received_at": "2026-05-18T08:00:00Z",
        "body": "Detail cached body",
        "body_html": "<p>Detail cached body</p>",
        "body_text": "Detail cached body",
        "conversation_id": "thread-123",
        "to": ["nat@example.com"],
        "cc": [],
    }

    with app.app_context(), \
         patch("app.api.routes_emails._get_cached_email_detail", return_value=cached):
        email = _standard_email_from_detail_cache("email-123", 1)

    assert email is not None
    assert email.id == "email-123"
    assert email.body == "Detail cached body"
    assert email.body_html == "<p>Detail cached body</p>"
    assert email.provider_source == "detail_cache"


def test_detail_cache_wait_returns_immediately_without_inflight_fetch(app):
    from app.api import routes_emails

    with app.app_context(), \
         patch("app.api.routes_emails._get_cached_email_detail", return_value=None):
        started = routes_emails._cache_time.perf_counter()
        email = routes_emails._wait_for_detail_cache_email("email-123", 1)
        duration = routes_emails._cache_time.perf_counter() - started

    assert email is None
    assert duration < 0.2


def test_process_use_case_strips_unknown_body_artifact_before_router(app, monkeypatch):
    from app.api.routes_helpers import _process_email_with_use_case
    from app.smart_routing import RoutingDecision, RoutingResult, RoutingTier

    captured = {}

    class FakeRouter:
        def route_streaming(self, **kwargs):
            captured.update(kwargs)
            return RoutingResult(
                draft="Draft body",
                decision=RoutingDecision(
                    tier=RoutingTier.STANDARD,
                    complexity_score=10,
                    reason="test",
                ),
                classification="Action",
                priority=50,
                status="generated",
            )

    email = SimpleNamespace(
        id="email-unknown",
        sender="emilie.gauthier@example.com",
        sender_name="Unknown",
        subject="Rendez-vous café mardi 15h",
        body="Unknown (empty bodies)",
        conversation_id="thread-unknown",
    )

    monkeypatch.setattr("app.config.SMART_ROUTING_ENABLED", True)
    monkeypatch.setattr("app.config.USE_CONVERSATION_HISTORY", False)

    with app.app_context(), \
         patch("app.api.routes_helpers._get_container", return_value=SimpleNamespace(llm=SimpleNamespace(name="claude"))), \
         patch("app.api.routes_helpers._fetch_thread_context", return_value=[]), \
         patch("app.api.settings.load_settings", return_value={}), \
         patch("app.smart_routing.SmartRouter", FakeRouter):
        result = _process_email_with_use_case(
            email,
            include_details=True,
            provider=Mock(),
            instructions="Réponds brièvement",
            use_streaming=True,
            _user_email="nat@example.com",
            _account_id=1,
            force=True,
        )

    assert captured["body"] == ""
    assert email.body == ""
    assert result[0] == "Draft body"


def test_cached_process_payload_rejects_oversized_body(app):
    from app.api.routes_emails import MAX_BODY_LENGTH, _standard_email_from_cached_process_payload

    with app.app_context():
        email, error = _standard_email_from_cached_process_payload(
            "email-123",
            _cached_email_payload(body="x" * (MAX_BODY_LENGTH + 1)),
        )

    assert email is None
    assert error[1] == 400


def test_process_email_draft_payload_rehydrates_cached_email(app):
    from app.api import routes_emails

    provider = Mock()
    captured = {}

    def fake_process_email_draft_job(**kwargs):
        captured.update(kwargs)

    payload = {
        "email_id": "email-worker",
        "instructions": "Réponds brièvement",
        "force_regen": True,
        "cached_email": _cached_email_payload(subject="Question worker"),
        "account_id": 12,
        "account_hash": "acct-worker",
        "user_email": "nat@example.com",
        "user_id": 34,
        "email_body_from_request": True,
    }

    with app.app_context(), \
         patch("app.api.routes_emails._create_provider_for_draft_payload", return_value=provider), \
         patch("app.api.routes_emails._process_email_draft_job", side_effect=fake_process_email_draft_job), \
         patch("app.infrastructure.cost_manager.set_usage_context", return_value=None):
        routes_emails.process_email_draft_payload(payload)

    assert captured["email_id"] == "email-worker"
    assert captured["provider"] is provider
    assert captured["cached_email"].subject == "Question worker"
    assert captured["instructions"] == "Réponds brièvement"
    assert captured["_bg_account_id"] == 12
    assert captured["_bg_user_email"] == "nat@example.com"
    assert captured["_email_body_from_request"] is True


def test_worker_provider_falls_back_to_db_account_id(app):
    from app.api import routes_emails

    provider = Mock()
    provider.authenticate.return_value = True
    manager = Mock()
    manager.get_account.return_value = None
    manager.get_account_by_email.return_value = None

    with app.app_context(), \
         patch("app.multi_accounts.get_account_manager", return_value=manager), \
         patch("app.multi_accounts.create_provider_for_account", return_value=provider) as create_provider, \
         patch("app.api.routes_emails._account_config_from_db_account_id") as from_db:
        from app.multi_accounts import AccountConfig

        account = AccountConfig(
            id="f9057edfed0d4574",
            name="Nat",
            email="nat@example.com",
            provider="gmail",
        )
        from_db.return_value = account

        resolved = routes_emails._create_provider_for_draft_payload({
            "account_id": 14,
            "account_hash": "",
            "user_email": "",
        })

    assert resolved is provider
    from_db.assert_called_once_with(14)
    create_provider.assert_called_once_with(account)


def test_db_account_id_fallback_builds_oauth_hash(app):
    from app.api import routes_emails

    db_account = SimpleNamespace(
        email="nat@example.com",
        provider="gmail",
        display_name="Nat",
        signature_html="<p>Nat</p>",
        signature_text="Nat",
        user_id=42,
    )

    class FakeAccountRepository:
        def __init__(self, session):
            self.session = session

        def get(self, account_id):
            assert account_id == 14
            return db_account

    @contextmanager
    def fake_db_session():
        yield object()

    with app.app_context(), \
         patch("app.db.database.get_db_session", fake_db_session), \
         patch("app.db.repositories.account_repository.AccountRepository", FakeAccountRepository):
        account = routes_emails._account_config_from_db_account_id(14)

    assert account is not None
    assert account.id == hashlib.sha256(b"gmail:nat@example.com").hexdigest()[:16]
    assert account.email == "nat@example.com"
    assert account.provider == "gmail"
    assert account.signature_html == "<p>Nat</p>"
    assert account.signature == "Nat"
    assert account.user_id == 42


@patch("app.api.routes_emails._get_email_by_id")
@patch("app.api.routes_emails._get_authenticated_provider")
def test_process_email_uses_detail_cache_before_provider_detail(
    mock_get_provider,
    mock_get_email_by_id,
    client,
):
    from app.api import routes_emails

    provider = Mock()
    mock_get_provider.return_value = provider
    added_drafts = []

    mock_store = Mock()
    mock_store.get_by_email_id.return_value = None
    mock_store.add.side_effect = added_drafts.append

    mock_label_store = Mock()
    mock_label_store.get_assignment.return_value = None

    mock_container = Mock()
    mock_container.get_pending_draft_store.return_value = mock_store
    mock_container.get_label_store.return_value = mock_label_store

    cached_detail = {
        "id": "email-123",
        "sender": "alex@example.com",
        "sender_name": "Alex",
        "subject": "Question",
        "received_at": "2026-05-18T08:00:00Z",
        "body": "Detail cached body",
        "body_html": "<p>Detail cached body</p>",
        "body_text": "Detail cached body",
        "conversation_id": "thread-123",
        "to": ["nat@example.com"],
        "cc": [],
    }

    with patch("app.api.routes_emails._resolve_account_id_cached", return_value=1), \
         patch("app.api.routes_emails._get_current_account_for_user", return_value=None), \
         patch("app.api.routes_emails._detach_provider_from_request"), \
         patch("app.api.routes_emails._passive_detect_contact_variant"), \
         patch("app.api.routes_emails._fetch_conversation_history_for_contact", return_value=[]), \
         patch("app.api.routes_emails._get_cached_email_detail", return_value=cached_detail), \
         patch("app.api.routes_emails._process_email_with_use_case", return_value=("Draft body", "OK", "Action", 80, "default", {})) as mock_process, \
         patch.object(routes_emails._rh, "_get_container", return_value=mock_container), \
         patch("app.infrastructure.draft_job_queue.enqueue_draft_job", side_effect=_immediate_enqueue_draft_job):
        response = client.post(
            "/api/emails/email-123/process",
            json={"force": True},
        )

    assert response.status_code == 202
    mock_get_email_by_id.assert_not_called()
    assert mock_process.call_args.args[0].body == "Detail cached body"
    assert mock_process.call_args.args[0].provider_source == "detail_cache"
    assert added_drafts


@patch("app.api.routes_emails._get_email_by_id")
@patch("app.api.routes_emails._get_authenticated_provider")
def test_process_email_uses_cached_body_without_provider_detail(
    mock_get_provider,
    mock_get_email_by_id,
    client,
):
    from app.api import routes_emails

    provider = Mock()
    mock_get_provider.return_value = provider

    mock_store = Mock()
    mock_store.get_by_email_id.return_value = None
    mock_container = Mock()
    mock_container.get_pending_draft_store.return_value = mock_store

    with patch("app.api.routes_emails._resolve_account_id_cached", return_value=1), \
         patch("app.api.routes_emails._detach_provider_from_request"), \
         patch.object(routes_emails._rh, "_get_container", return_value=mock_container), \
         patch("app.infrastructure.draft_job_queue.enqueue_draft_job", side_effect=_noop_enqueue_draft_job):
        response = client.post(
            "/api/emails/email-123/process",
            json={"force": True, "cached_email": _cached_email_payload()},
        )

    assert response.status_code == 202
    mock_get_email_by_id.assert_not_called()


@patch("app.api.routes_emails._get_email_by_id")
@patch("app.api.routes_emails._get_authenticated_provider")
def test_process_email_does_not_persist_cached_body_in_pending_draft(
    mock_get_provider,
    mock_get_email_by_id,
    client,
):
    from app.api import routes_emails

    provider = Mock()
    mock_get_provider.return_value = provider
    added_drafts = []

    mock_store = Mock()
    mock_store.get_by_email_id.return_value = None
    mock_store.add.side_effect = added_drafts.append

    mock_label_store = Mock()
    mock_label_store.get_assignment.return_value = None

    mock_container = Mock()
    mock_container.get_pending_draft_store.return_value = mock_store
    mock_container.get_label_store.return_value = mock_label_store

    with patch("app.api.routes_emails._resolve_account_id_cached", return_value=1), \
         patch("app.api.routes_emails._get_current_account_for_user", return_value=None), \
         patch("app.api.routes_emails._detach_provider_from_request"), \
         patch("app.api.routes_emails._passive_detect_contact_variant"), \
         patch("app.api.routes_emails._fetch_conversation_history_for_contact", return_value=[]), \
         patch("app.api.routes_emails._process_email_with_use_case", return_value=("Draft body", "OK", "Action", 80, "default", {})) as mock_process, \
         patch("app.api.routes_emails.should_persist_email_content", return_value=True), \
         patch.object(routes_emails._rh, "_get_container", return_value=mock_container), \
         patch("app.infrastructure.draft_job_queue.enqueue_draft_job", side_effect=_immediate_enqueue_draft_job):
        response = client.post(
            "/api/emails/email-123/process",
            json={"force": True, "cached_email": _cached_email_payload()},
        )

    assert response.status_code == 202
    mock_get_email_by_id.assert_not_called()
    assert mock_process.call_args.args[0].body == "Local cached body"
    assert added_drafts
    assert added_drafts[0].email_body == ""
