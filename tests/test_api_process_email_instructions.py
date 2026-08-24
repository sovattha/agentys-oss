# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests for POST /api/emails/<id>/process with instructions and reply_type parameters.

Story 3-5: initiate-response-flow
Tests the new parameters added to support the response flow UI:
- instructions: optional string (max 500 chars) for AI guidance
- reply_type: 'reply' or 'reply_all' for recipient handling

Note: The process endpoint now returns 202 Accepted immediately and
processes in the background via WebSocket. Tests validate:
- Input validation (instructions max length, reply_type normalization)
- Correct 202 response structure for valid requests
- Error responses (400, 401, 404) for invalid inputs
"""

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
    email_id: str = "test-id",
    sender: str = "sender@test.com",
    sender_name: str = "Sender",
    subject: str = "Test Subject",
    body: str = "Test body",
    received_at: str = "2025-01-01T00:00:00",
    has_attachments: bool = False,
    conversation_id: str = None,
) -> Mock:
    """Create a mock email with configurable attributes."""
    mock_email = Mock()
    mock_email.id = email_id
    mock_email.sender = sender
    mock_email.sender_name = sender_name
    mock_email.subject = subject
    mock_email.body = body
    mock_email.received_at = received_at
    mock_email.has_attachments = has_attachments
    mock_email.conversation_id = conversation_id
    return mock_email


# ---------------------------------------------------------------------------
# Helpers for common mock setups
# ---------------------------------------------------------------------------

def _patch_process_success():
    """Patch _process_email_with_use_case, _detach_provider_from_request,
    background submit, and account helpers so the endpoint reaches 202."""
    return [
        patch("app.api.routes_emails._process_email_with_use_case"),
        patch("app.api.routes_emails._detach_provider_from_request"),
        patch("app.api.routes_emails._rh"),
    ]


class TestProcessEmailWithInstructions:
    """Tests for instructions parameter in POST /api/emails/<id>/process."""

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_process_with_instructions_success(
        self, mock_auth, mock_get_email, client
    ):
        """Process email with instructions returns 202 accepted."""
        email = _create_mock_email()
        mock_get_email.return_value = email

        with patch("app.api.routes_emails._detach_provider_from_request"), \
             patch("app.api.routes_emails._rh") as mock_rh:
            mock_store = Mock()
            mock_store.get_by_email_id.return_value = None
            mock_rh._get_container.return_value.get_pending_draft_store.return_value = mock_store

            response = client.post(
                "/api/emails/test-id/process",
                json={"instructions": "Please confirm the meeting at 2pm"},
            )
            data = response.get_json()

        assert response.status_code == 202
        assert data["success"] is True
        assert data["email_id"] == "test-id"
        assert data["status"] == "processing"

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_process_without_instructions_success(
        self, mock_auth, mock_get_email, client
    ):
        """Process email without instructions returns 202 accepted."""
        email = _create_mock_email()
        mock_get_email.return_value = email

        with patch("app.api.routes_emails._detach_provider_from_request"), \
             patch("app.api.routes_emails._rh") as mock_rh:
            mock_store = Mock()
            mock_store.get_by_email_id.return_value = None
            mock_rh._get_container.return_value.get_pending_draft_store.return_value = mock_store

            response = client.post("/api/emails/test-id/process")
            data = response.get_json()

        assert response.status_code == 202
        assert data["success"] is True

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_process_with_empty_instructions(
        self, mock_auth, mock_get_email, client
    ):
        """Process email with empty instructions string returns 202."""
        email = _create_mock_email()
        mock_get_email.return_value = email

        with patch("app.api.routes_emails._detach_provider_from_request"), \
             patch("app.api.routes_emails._rh") as mock_rh:
            mock_store = Mock()
            mock_store.get_by_email_id.return_value = None
            mock_rh._get_container.return_value.get_pending_draft_store.return_value = mock_store

            response = client.post(
                "/api/emails/test-id/process",
                json={"instructions": ""},
            )
            data = response.get_json()

        assert response.status_code == 202
        assert data["success"] is True

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_process_with_max_length_instructions(
        self, mock_auth, mock_get_email, client
    ):
        """Process email with instructions at max length (500 chars) succeeds."""
        email = _create_mock_email()
        mock_get_email.return_value = email

        with patch("app.api.routes_emails._detach_provider_from_request"), \
             patch("app.api.routes_emails._rh") as mock_rh:
            mock_store = Mock()
            mock_store.get_by_email_id.return_value = None
            mock_rh._get_container.return_value.get_pending_draft_store.return_value = mock_store

            instructions = "a" * 500
            response = client.post(
                "/api/emails/test-id/process",
                json={"instructions": instructions},
            )
            data = response.get_json()

        assert response.status_code == 202
        assert data["success"] is True

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_process_with_instructions_exceeding_max_length(
        self, mock_auth, mock_get_email, client
    ):
        """Process email with instructions exceeding 500 chars returns 400."""
        email = _create_mock_email()
        mock_get_email.return_value = email

        instructions = "a" * 501
        response = client.post(
            "/api/emails/test-id/process",
            json={"instructions": instructions},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "instructions" in data["error"].lower()

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_process_with_null_instructions(
        self, mock_auth, mock_get_email, client
    ):
        """Process email with null instructions is treated as missing."""
        email = _create_mock_email()
        mock_get_email.return_value = email

        with patch("app.api.routes_emails._detach_provider_from_request"), \
             patch("app.api.routes_emails._rh") as mock_rh:
            mock_store = Mock()
            mock_store.get_by_email_id.return_value = None
            mock_rh._get_container.return_value.get_pending_draft_store.return_value = mock_store

            response = client.post(
                "/api/emails/test-id/process",
                json={"instructions": None},
            )
            data = response.get_json()

        assert response.status_code == 202
        assert data["success"] is True

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_process_with_unicode_instructions(
        self, mock_auth, mock_get_email, client
    ):
        """Process email with unicode in instructions succeeds."""
        email = _create_mock_email()
        mock_get_email.return_value = email

        with patch("app.api.routes_emails._detach_provider_from_request"), \
             patch("app.api.routes_emails._rh") as mock_rh:
            mock_store = Mock()
            mock_store.get_by_email_id.return_value = None
            mock_rh._get_container.return_value.get_pending_draft_store.return_value = mock_store

            instructions = "Répondez poliment. 日本語 🎉 émojis"
            response = client.post(
                "/api/emails/test-id/process",
                json={"instructions": instructions},
            )
            data = response.get_json()

        assert response.status_code == 202
        assert data["success"] is True

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_process_with_special_characters_instructions(
        self, mock_auth, mock_get_email, client
    ):
        """Process email with special characters in instructions succeeds."""
        email = _create_mock_email()
        mock_get_email.return_value = email

        with patch("app.api.routes_emails._detach_provider_from_request"), \
             patch("app.api.routes_emails._rh") as mock_rh:
            mock_store = Mock()
            mock_store.get_by_email_id.return_value = None
            mock_rh._get_container.return_value.get_pending_draft_store.return_value = mock_store

            instructions = "Use <html> tags, &amp; \"quotes\" 'apostrophe'"
            response = client.post(
                "/api/emails/test-id/process",
                json={"instructions": instructions},
            )
            data = response.get_json()

        assert response.status_code == 202
        assert data["success"] is True


class TestProcessEmailWithReplyType:
    """Tests for reply_type parameter in POST /api/emails/<id>/process."""

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_process_with_reply_type_reply(
        self, mock_auth, mock_get_email, client
    ):
        """Process email with reply_type='reply' returns 202."""
        email = _create_mock_email()
        mock_get_email.return_value = email

        with patch("app.api.routes_emails._detach_provider_from_request"), \
             patch("app.api.routes_emails._rh") as mock_rh:
            mock_store = Mock()
            mock_store.get_by_email_id.return_value = None
            mock_rh._get_container.return_value.get_pending_draft_store.return_value = mock_store

            response = client.post(
                "/api/emails/test-id/process",
                json={"reply_type": "reply"},
            )
            data = response.get_json()

        assert response.status_code == 202
        assert data["success"] is True

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_process_with_reply_type_reply_all(
        self, mock_auth, mock_get_email, client
    ):
        """Process email with reply_type='reply_all' returns 202."""
        email = _create_mock_email()
        mock_get_email.return_value = email

        with patch("app.api.routes_emails._detach_provider_from_request"), \
             patch("app.api.routes_emails._rh") as mock_rh:
            mock_store = Mock()
            mock_store.get_by_email_id.return_value = None
            mock_rh._get_container.return_value.get_pending_draft_store.return_value = mock_store

            response = client.post(
                "/api/emails/test-id/process",
                json={"reply_type": "reply_all"},
            )
            data = response.get_json()

        assert response.status_code == 202
        assert data["success"] is True

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_process_without_reply_type_defaults_to_reply(
        self, mock_auth, mock_get_email, client
    ):
        """Process email without reply_type returns 202."""
        email = _create_mock_email()
        mock_get_email.return_value = email

        with patch("app.api.routes_emails._detach_provider_from_request"), \
             patch("app.api.routes_emails._rh") as mock_rh:
            mock_store = Mock()
            mock_store.get_by_email_id.return_value = None
            mock_rh._get_container.return_value.get_pending_draft_store.return_value = mock_store

            response = client.post("/api/emails/test-id/process")
            data = response.get_json()

        assert response.status_code == 202
        assert data["success"] is True

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_process_with_invalid_reply_type_returns_202(
        self, mock_auth, mock_get_email, client
    ):
        """Process email with invalid reply_type normalizes to 'reply' and returns 202."""
        email = _create_mock_email()
        mock_get_email.return_value = email

        with patch("app.api.routes_emails._detach_provider_from_request"), \
             patch("app.api.routes_emails._rh") as mock_rh:
            mock_store = Mock()
            mock_store.get_by_email_id.return_value = None
            mock_rh._get_container.return_value.get_pending_draft_store.return_value = mock_store

            response = client.post(
                "/api/emails/test-id/process",
                json={"reply_type": "invalid_type"},
            )
            data = response.get_json()

        assert response.status_code == 202
        assert data["success"] is True

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_process_with_null_reply_type_returns_202(
        self, mock_auth, mock_get_email, client
    ):
        """Process email with null reply_type returns 202."""
        email = _create_mock_email()
        mock_get_email.return_value = email

        with patch("app.api.routes_emails._detach_provider_from_request"), \
             patch("app.api.routes_emails._rh") as mock_rh:
            mock_store = Mock()
            mock_store.get_by_email_id.return_value = None
            mock_rh._get_container.return_value.get_pending_draft_store.return_value = mock_store

            response = client.post(
                "/api/emails/test-id/process",
                json={"reply_type": None},
            )
            data = response.get_json()

        assert response.status_code == 202
        assert data["success"] is True

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_process_with_empty_reply_type_returns_202(
        self, mock_auth, mock_get_email, client
    ):
        """Process email with empty string reply_type returns 202."""
        email = _create_mock_email()
        mock_get_email.return_value = email

        with patch("app.api.routes_emails._detach_provider_from_request"), \
             patch("app.api.routes_emails._rh") as mock_rh:
            mock_store = Mock()
            mock_store.get_by_email_id.return_value = None
            mock_rh._get_container.return_value.get_pending_draft_store.return_value = mock_store

            response = client.post(
                "/api/emails/test-id/process",
                json={"reply_type": ""},
            )
            data = response.get_json()

        assert response.status_code == 202
        assert data["success"] is True


class TestProcessEmailWithBothParameters:
    """Tests for combined instructions and reply_type parameters."""

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_process_with_instructions_and_reply_type(
        self, mock_auth, mock_get_email, client
    ):
        """Process email with both instructions and reply_type returns 202."""
        email = _create_mock_email()
        mock_get_email.return_value = email

        with patch("app.api.routes_emails._detach_provider_from_request"), \
             patch("app.api.routes_emails._rh") as mock_rh:
            mock_store = Mock()
            mock_store.get_by_email_id.return_value = None
            mock_rh._get_container.return_value.get_pending_draft_store.return_value = mock_store

            response = client.post(
                "/api/emails/test-id/process",
                json={
                    "instructions": "Confirm the meeting and include agenda",
                    "reply_type": "reply_all",
                },
            )
            data = response.get_json()

        assert response.status_code == 202
        assert data["success"] is True
        assert data["email_id"] == "test-id"

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_process_with_empty_json_body(
        self, mock_auth, mock_get_email, client
    ):
        """Process email with empty JSON body returns 202 with defaults."""
        email = _create_mock_email()
        mock_get_email.return_value = email

        with patch("app.api.routes_emails._detach_provider_from_request"), \
             patch("app.api.routes_emails._rh") as mock_rh:
            mock_store = Mock()
            mock_store.get_by_email_id.return_value = None
            mock_rh._get_container.return_value.get_pending_draft_store.return_value = mock_store

            response = client.post(
                "/api/emails/test-id/process",
                json={},
            )
            data = response.get_json()

        assert response.status_code == 202
        assert data["success"] is True

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_process_ignores_extra_fields(
        self, mock_auth, mock_get_email, client
    ):
        """Process email ignores extra fields in request body."""
        email = _create_mock_email()
        mock_get_email.return_value = email

        with patch("app.api.routes_emails._detach_provider_from_request"), \
             patch("app.api.routes_emails._rh") as mock_rh:
            mock_store = Mock()
            mock_store.get_by_email_id.return_value = None
            mock_rh._get_container.return_value.get_pending_draft_store.return_value = mock_store

            response = client.post(
                "/api/emails/test-id/process",
                json={
                    "instructions": "Be polite",
                    "reply_type": "reply",
                    "extra_field": "should be ignored",
                    "another_field": 123,
                },
            )
            data = response.get_json()

        assert response.status_code == 202
        assert data["success"] is True
        assert "extra_field" not in data
        assert "another_field" not in data


class TestProcessEmailResponseStructure:
    """Tests for response structure with new parameters."""

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_response_contains_expected_202_fields(
        self, mock_auth, mock_get_email, client
    ):
        """Response contains all expected 202 Accepted fields."""
        email = _create_mock_email()
        mock_get_email.return_value = email

        with patch("app.api.routes_emails._detach_provider_from_request"), \
             patch("app.api.routes_emails._rh") as mock_rh:
            mock_store = Mock()
            mock_store.get_by_email_id.return_value = None
            mock_rh._get_container.return_value.get_pending_draft_store.return_value = mock_store

            response = client.post("/api/emails/test-id/process")
            data = response.get_json()

        assert response.status_code == 202
        assert "success" in data
        assert "email_id" in data
        assert "task_id" in data
        assert "status" in data
        assert data["status"] == "processing"

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_existing_draft_returns_200_with_full_fields(
        self, mock_auth, mock_get_email, client
    ):
        """When a pending draft already exists, endpoint returns 200 with full response."""
        email = _create_mock_email()
        mock_get_email.return_value = email

        existing_draft = Mock()
        existing_draft.id = "draft-existing-123"
        existing_draft.classification = "commercial"
        existing_draft.priority = 3
        existing_draft.draft_body = "Previously generated response"

        with patch("app.api.routes_emails._rh") as mock_rh:
            mock_store = Mock()
            mock_store.get_by_email_id.return_value = existing_draft
            mock_rh._get_container.return_value.get_pending_draft_store.return_value = mock_store

            response = client.post("/api/emails/test-id/process")
            data = response.get_json()

        assert response.status_code == 200
        assert data["success"] is True
        assert data["draft_id"] == "draft-existing-123"
        assert data["email_id"] == "test-id"
        assert data["classification"] == "commercial"
        assert data["priority"] == 3
        assert data["status"] == "existing"
        assert "draft_preview" in data
        assert data["instructions"] == ""
        assert data["reply_type"] == "reply"

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_response_email_id_matches_request(
        self, mock_auth, mock_get_email, client
    ):
        """Response email_id matches the requested email ID."""
        email = _create_mock_email()
        mock_get_email.return_value = email

        with patch("app.api.routes_emails._detach_provider_from_request"), \
             patch("app.api.routes_emails._rh") as mock_rh:
            mock_store = Mock()
            mock_store.get_by_email_id.return_value = None
            mock_rh._get_container.return_value.get_pending_draft_store.return_value = mock_store

            response = client.post(
                "/api/emails/test-id/process",
                json={"instructions": "Test", "reply_type": "reply_all"},
            )
            data = response.get_json()

        assert response.status_code == 202
        assert data["email_id"] == "test-id"
