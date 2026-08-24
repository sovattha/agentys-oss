# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests for GET /api/emails/{id}/thread endpoint."""

from contextlib import contextmanager
from unittest.mock import Mock, patch

import pytest


@pytest.fixture
def app():
    """Application Flask de test."""
    from app.api.app import create_app

    app = create_app(config={"TESTING": True})
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    """Client de test Flask."""
    return app.test_client()


def _create_mock_email(
    email_id: str,
    sender: str = "sender@test.com",
    subject: str = "Test Subject",
    conversation_id: str = "thread-123",
    received_at: str = "2025-01-01T10:00:00",
    body: str = "Test email body",
) -> Mock:
    """Helper to create mock email objects."""
    mock_email = Mock()
    mock_email.id = email_id
    mock_email.sender = sender
    mock_email.sender_name = "Test Sender"
    mock_email.subject = subject
    mock_email.received_at = received_at
    mock_email.has_attachments = False
    mock_email.conversation_id = conversation_id
    mock_email.body = body
    mock_email.body_html = None
    mock_email.is_read = True
    mock_email.to = []
    mock_email.cc = []
    mock_email.recipients = []
    mock_email.attachments = []
    return mock_email


def _make_provider_mock(emails):
    """Create a mock provider that returns the given emails."""
    mock_provider = Mock()
    mock_provider.authenticate.return_value = True
    mock_provider.get_unread_messages.return_value = emails
    mock_provider.get_messages.return_value = emails
    mock_provider.get_thread_messages.return_value = emails
    return mock_provider


def _patch_thread_endpoint(mock_emails, target_email_id=None):
    """
    Return a list of patch context managers for the thread endpoint.

    Patches:
    - _get_authenticated_provider -> returns a mock provider
    - _get_email_by_id -> returns the email matching target_email_id from mock_emails
    - _get_pending_draft_email_ids -> returns empty set (no draft dependencies)
    - _get_email_labels -> returns empty list (no label dependencies)
    """
    provider = _make_provider_mock(mock_emails)

    def fake_get_email_by_id(prov, eid, *, account_id=None):
        # account_id kwarg ajouté par le fix isolation 2026-04-24 (commit 007ddcfb)
        # — accepté ici pour compat mais ignoré dans le mock (test ne dépend pas
        # du scope account car il fournit son propre dataset).
        del account_id
        for e in mock_emails:
            if e.id == eid:
                return e
        from flask import abort
        abort(404, description="Email not found")

    patches = [
        patch("app.api.routes_emails._get_authenticated_provider", return_value=provider),
        patch("app.api.routes_emails._get_email_by_id", side_effect=fake_get_email_by_id),
        patch("app.api.routes_emails._get_pending_draft_email_ids", return_value=set()),
        patch("app.api.routes_emails._get_email_labels", return_value=[]),
    ]
    return patches, provider


class TestGetEmailThreadEndpoint:
    """Tests for GET /api/emails/{id}/thread endpoint."""

    def test_get_thread_success_multiple_emails(self, client):
        """Get thread returns all emails in conversation sorted by date."""
        mock_emails = [
            _create_mock_email("email-1", received_at="2025-01-01T08:00:00", subject="Original"),
            _create_mock_email("email-2", received_at="2025-01-01T09:00:00", subject="Re: Original"),
            _create_mock_email("email-3", received_at="2025-01-01T10:00:00", subject="Re: Re: Original"),
        ]

        patches, provider = _patch_thread_endpoint(mock_emails, target_email_id="email-1")
        with patches[0], patches[1], patches[2], patches[3]:
            response = client.get("/api/emails/email-1/thread")
            data = response.get_json()

        assert response.status_code == 200
        assert "emails" in data
        assert len(data["emails"]) == 3
        # Verify chronological order (oldest first)
        assert data["emails"][0]["id"] == "email-1"
        assert data["emails"][1]["id"] == "email-2"
        assert data["emails"][2]["id"] == "email-3"

    def test_get_thread_single_email(self, client):
        """Get thread with single email returns that email."""
        mock_email = _create_mock_email("email-single", conversation_id="thread-single")

        patches, provider = _patch_thread_endpoint([mock_email], target_email_id="email-single")
        with patches[0], patches[1], patches[2], patches[3]:
            response = client.get("/api/emails/email-single/thread")
            data = response.get_json()

        assert response.status_code == 200
        assert len(data["emails"]) == 1
        assert data["emails"][0]["id"] == "email-single"

    def test_get_thread_email_not_found(self, client):
        """Get thread for non-existent email returns 404."""
        patches, provider = _patch_thread_endpoint([], target_email_id="nonexistent")
        with patches[0], patches[1], patches[2], patches[3]:
            response = client.get("/api/emails/nonexistent/thread")
            data = response.get_json()

        assert response.status_code == 404
        assert "error" in data

    def test_get_thread_invalid_id(self, client):
        """Get thread with invalid email ID format returns 400."""
        response = client.get("/api/emails/invalid!@#$/thread")
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "Invalid email_id format" in data["error"]

    def test_get_thread_no_conversation_id(self, client):
        """Get thread for email without conversation_id returns only that email."""
        mock_email = _create_mock_email("email-no-thread", conversation_id=None)

        patches, provider = _patch_thread_endpoint([mock_email], target_email_id="email-no-thread")
        with patches[0], patches[1], patches[2], patches[3]:
            response = client.get("/api/emails/email-no-thread/thread")
            data = response.get_json()

        assert response.status_code == 200
        assert len(data["emails"]) == 1

    def test_get_thread_auth_failure(self, client):
        """Get thread with authentication failure returns 401 or 503."""
        with patch("app.api.routes_emails._get_authenticated_provider") as mock_auth:
            from flask import abort
            mock_auth.side_effect = lambda: abort(503, description="Email provider authentication failed")

            response = client.get("/api/emails/test-id/thread")
            data = response.get_json()

        assert response.status_code == 503
        assert "error" in data

    def test_get_thread_includes_body(self, client):
        """Get thread includes body for each email."""
        mock_email = _create_mock_email("email-with-body", body="<p>HTML content</p>")

        patches, provider = _patch_thread_endpoint([mock_email], target_email_id="email-with-body")
        with patches[0], patches[1], patches[2], patches[3]:
            response = client.get("/api/emails/email-with-body/thread")
            data = response.get_json()

        assert response.status_code == 200
        assert data["emails"][0]["body"] == "<p>HTML content</p>"

    def test_get_thread_refreshes_synthetic_cache_from_provider(self, client, monkeypatch):
        """A partial cache with reply-* placeholders must not hide provider thread history."""
        from app.api import routes_emails

        original = _create_mock_email(
            "email-original",
            subject="Project",
            conversation_id="thread-123",
            received_at="2025-01-01T08:00:00",
        )
        sent_real = _create_mock_email(
            "email-sent-real",
            sender="me@test.com",
            subject="Re: Project",
            conversation_id="thread-123",
            received_at="2025-01-01T09:00:00",
        )
        latest = _create_mock_email(
            "email-latest",
            subject="Re: Project",
            conversation_id="thread-123",
            received_at="2025-01-01T10:00:00",
        )
        synthetic_sent = _create_mock_email(
            "reply-1735722000",
            sender="me@test.com",
            subject="Re: Project",
            conversation_id="thread-123",
            received_at="2025-01-01T09:00:00",
        )

        patches, provider = _patch_thread_endpoint(
            [original, sent_real, latest],
            target_email_id="email-latest",
        )
        provider.get_thread_messages.return_value = [original, sent_real, latest]

        @contextmanager
        def fake_session():
            yield object()

        class FakeEmailRepository:
            def __init__(self, session):
                del session

            def get_by_thread(self, thread_id, account_id):
                assert thread_id == "thread-123"
                assert account_id == 123
                return [synthetic_sent, latest]

        monkeypatch.setattr(routes_emails._rh, "get_db_session", fake_session)
        monkeypatch.setattr(routes_emails._rh, "EmailRepository", FakeEmailRepository)
        monkeypatch.setattr(routes_emails, "_db_email_to_standard", lambda email: email)
        monkeypatch.setattr(routes_emails, "_resolve_account_id_for_provider", lambda provider: 123)

        with patches[0], patches[1], patches[2], patches[3]:
            response = client.get("/api/emails/email-latest/thread")
            data = response.get_json()

        assert response.status_code == 200
        assert [email["id"] for email in data["emails"]] == [
            "email-original",
            "email-sent-real",
            "email-latest",
        ]
        provider.get_thread_messages.assert_called_once_with("thread-123")


class TestGetEmailThreadEdgeCases:
    """Edge case tests for GET /api/emails/{id}/thread endpoint."""

    def test_get_thread_empty_id(self, client):
        """Get thread with empty ID returns redirect or 404 (Flask behavior)."""
        response = client.get("/api/emails//thread")
        # Flask may redirect or 404 depending on strict_slashes
        assert response.status_code in (308, 404)

    def test_get_thread_preserves_order(self, client):
        """Thread emails are sorted chronologically (oldest first)."""
        # Create emails out of order
        mock_emails = [
            _create_mock_email("email-c", received_at="2025-01-01T12:00:00"),
            _create_mock_email("email-a", received_at="2025-01-01T08:00:00"),
            _create_mock_email("email-b", received_at="2025-01-01T10:00:00"),
        ]

        patches, provider = _patch_thread_endpoint(mock_emails, target_email_id="email-a")
        with patches[0], patches[1], patches[2], patches[3]:
            response = client.get("/api/emails/email-a/thread")
            data = response.get_json()

        assert response.status_code == 200
        # Should be sorted chronologically
        assert data["emails"][0]["id"] == "email-a"
        assert data["emails"][1]["id"] == "email-b"
        assert data["emails"][2]["id"] == "email-c"

    def test_get_thread_response_format(self, client):
        """Thread response has correct structure."""
        mock_email = _create_mock_email("email-1")

        patches, provider = _patch_thread_endpoint([mock_email], target_email_id="email-1")
        with patches[0], patches[1], patches[2], patches[3]:
            response = client.get("/api/emails/email-1/thread")
            data = response.get_json()

        assert response.status_code == 200
        assert response.content_type == "application/json"
        assert "emails" in data
        assert "count" in data
        assert data["count"] == len(data["emails"])

    def test_get_thread_exception(self, client):
        """Get thread with provider exception returns 500."""
        with patch("app.api.routes_emails._get_authenticated_provider") as mock_auth:
            mock_auth.side_effect = Exception("Provider error")

            response = client.get("/api/emails/test-id/thread")
            data = response.get_json()

        assert response.status_code == 500
        assert "error" in data
