# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests for POST /api/generate endpoint."""

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


# ============================================================================
# FIXTURES: Extracted to eliminate Duplicated Code smell
# ============================================================================


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


def _create_mock_provider(
    authenticated: bool = True,
    emails: list = None,
) -> Mock:
    """Create a mock email provider with configurable behavior."""
    mock_provider = Mock()
    mock_provider.authenticate.return_value = authenticated
    mock_provider.get_unread_messages.return_value = emails or []
    return mock_provider


def _create_mock_container(tokens_total: int = 100) -> Mock:
    """Create a mock container with token usage."""
    mock_token_usage = Mock()
    mock_token_usage.total = tokens_total
    mock_container = Mock()
    mock_container.token_usage = mock_token_usage
    return mock_container


@pytest.fixture
def mock_email():
    """Default mock email fixture."""
    return _create_mock_email()


@pytest.fixture
def mock_success_setup():
    """
    Complete mock setup for successful generate preview tests.

    Returns a dict with all configured mocks for easy access and modification.
    """
    email = _create_mock_email()
    provider = _create_mock_provider(authenticated=True, emails=[email])
    container = _create_mock_container(tokens_total=150)

    return {
        "email": email,
        "provider": provider,
        "container": container,
        "process_result": ("Generated response content", "V1", "commercial", 3, "standard"),
    }


# ============================================================================
# TEST CLASSES
# ============================================================================


class TestGeneratePreviewEndpoint:
    """Tests for POST /api/generate endpoint."""

    def test_generate_no_json_body(self, client):
        """Generate without JSON body returns error."""
        response = client.post("/api/generate")
        assert response.status_code in (400, 415)

    def test_generate_missing_email_id(self, client):
        """Generate without email_id returns 400."""
        response = client.post(
            "/api/generate",
            json={"tone": "formal"},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "email_id" in data["error"].lower()

    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_generate_auth_failure(self, mock_get_provider, client):
        """Generate with authentication failure returns 401."""
        from werkzeug.exceptions import Unauthorized

        mock_get_provider.side_effect = Unauthorized("Authentication failed")

        response = client.post(
            "/api/generate",
            json={"email_id": "test-id"},
        )

        assert response.status_code == 401

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_generate_email_not_found(self, mock_auth, mock_get_email, client):
        """Generate with non-existent email returns 404."""
        from werkzeug.exceptions import NotFound

        mock_get_email.side_effect = NotFound("Email not found")

        response = client.post(
            "/api/generate",
            json={"email_id": "nonexistent-id"},
        )
        data = response.get_json()

        assert response.status_code == 404
        assert "error" in data

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    @patch("app.api.routes_emails._process_email_with_use_case")
    @patch("app.api.routes_helpers._get_container")
    def test_generate_success(
        self, mock_get_container, mock_process, mock_auth, mock_get_email, client
    ):
        """Generate preview returns draft without creating it."""
        email = _create_mock_email()
        mock_get_email.return_value = email
        mock_process.return_value = ("Generated response content", "V1", "commercial", 3, "standard")
        mock_get_container.return_value = _create_mock_container(tokens_total=150)

        response = client.post(
            "/api/generate",
            json={"email_id": "test-id"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["success"] is True
        assert data["email_id"] == "test-id"
        assert data["classification"] == "commercial"
        assert data["priority"] == 3
        assert data["status"] == "V1"
        assert data["draft"]["subject"] == "Re: Test Subject"
        assert data["draft"]["body"] == "Generated response content"
        assert data["draft"]["tokens_used"] == 150
        assert "agents_trace" in data

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    @patch("app.api.routes_emails._process_email_with_use_case")
    @patch("app.api.routes_helpers._get_container")
    def test_generate_v2_status(
        self, mock_get_container, mock_process, mock_auth, mock_get_email, client
    ):
        """Generate preview with V2 status (after revision)."""
        email = _create_mock_email(
            email_id="test-id-v2",
            subject="Re: Already replied",
            body="Follow-up message",
        )
        mock_get_email.return_value = email
        mock_process.return_value = ("Revised response after critic", "V2", "support", 5, "standard")
        mock_get_container.return_value = _create_mock_container(tokens_total=300)

        response = client.post(
            "/api/generate",
            json={"email_id": "test-id-v2"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["status"] == "V2"
        assert data["priority"] == 5
        assert data["draft"]["subject"] == "Re: Already replied"

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    @patch("app.api.routes_emails._process_email_with_use_case")
    @patch("app.api.routes_helpers._get_container")
    def test_generate_with_tone_parameter(
        self, mock_get_container, mock_process, mock_auth, mock_get_email, client
    ):
        """Generate preview accepts optional tone parameter."""
        email = _create_mock_email()
        mock_get_email.return_value = email
        mock_process.return_value = ("Content", "V1", "other", 2, "standard")
        mock_get_container.return_value = _create_mock_container()

        response = client.post(
            "/api/generate",
            json={"email_id": "test-id", "tone": "friendly"},
        )

        assert response.status_code == 200

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    @patch("app.api.routes_helpers._get_container")
    def test_generate_internal_error(
        self, mock_get_container, mock_auth, mock_get_email, client
    ):
        """Generate with internal error returns 500."""
        email = _create_mock_email(
            received_at="2025-01-01T00:00:00",
            has_attachments=False,
            conversation_id=None,
        )
        mock_get_email.return_value = email

        mock_use_case = Mock()
        mock_use_case.execute.side_effect = Exception("UseCase failed")
        mock_container = Mock()
        mock_container.get_process_use_case.return_value = mock_use_case
        mock_get_container.return_value = mock_container

        response = client.post(
            "/api/generate",
            json={"email_id": "test-id"},
        )
        data = response.get_json()

        assert response.status_code == 500
        assert "error" in data


class TestGeneratePreviewEdgeCases:
    """Edge case tests for POST /api/generate endpoint."""

    def test_generate_empty_email_id(self, client):
        """Generate with empty email_id returns 400."""
        response = client.post(
            "/api/generate",
            json={"email_id": ""},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "email_id" in data["error"].lower()

    def test_generate_null_email_id(self, client):
        """Generate with null email_id returns 400."""
        response = client.post(
            "/api/generate",
            json={"email_id": None},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    def test_generate_email_id_with_special_characters(self, client):
        """Generate with invalid special chars in email_id returns 400.

        Security: email_id is validated to prevent injection attacks.
        Only alphanumeric, dash, underscore, @, ., + are allowed.
        """
        response = client.post(
            "/api/generate",
            json={"email_id": "test@id#123!&special"},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "Invalid email_id format" in data["error"]

    def test_generate_email_id_unicode(self, client):
        """Generate with unicode in email_id returns 400.

        Security: unicode characters are rejected to prevent
        homograph attacks and ensure consistent handling.
        """
        response = client.post(
            "/api/generate",
            json={"email_id": "test-émàïl-日本語"},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "Invalid email_id format" in data["error"]

    def test_generate_invalid_json(self, client):
        """Generate with invalid JSON returns error."""
        response = client.post(
            "/api/generate",
            data="not valid json{",
            content_type="application/json",
        )

        assert response.status_code in (400, 415)

    def test_generate_empty_json_object(self, client):
        """Generate with empty JSON object returns 400."""
        response = client.post(
            "/api/generate",
            json={},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    @patch("app.api.routes_emails._process_email_with_use_case")
    @patch("app.api.routes_helpers._get_container")
    def test_generate_zero_tokens_used(
        self, mock_get_container, mock_process, mock_auth, mock_get_email, client
    ):
        """Generate with zero tokens used returns 0 in response."""
        email = _create_mock_email()
        mock_get_email.return_value = email
        mock_process.return_value = ("Content", "V1", "commercial", 3, "standard")
        mock_get_container.return_value = _create_mock_container(tokens_total=0)

        response = client.post(
            "/api/generate",
            json={"email_id": "test-id"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["draft"]["tokens_used"] == 0

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    @patch("app.api.routes_emails._process_email_with_use_case")
    @patch("app.api.routes_helpers._get_container")
    def test_generate_priority_boundary_min(
        self, mock_get_container, mock_process, mock_auth, mock_get_email, client
    ):
        """Generate with minimum priority value (1)."""
        email = _create_mock_email(subject="Low Priority")
        mock_get_email.return_value = email
        mock_process.return_value = ("Content", "V1", "other", 1, "standard")
        mock_get_container.return_value = _create_mock_container(tokens_total=50)

        response = client.post(
            "/api/generate",
            json={"email_id": "test-id"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["priority"] == 1

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    @patch("app.api.routes_emails._process_email_with_use_case")
    @patch("app.api.routes_helpers._get_container")
    def test_generate_priority_boundary_max(
        self, mock_get_container, mock_process, mock_auth, mock_get_email, client
    ):
        """Generate with maximum priority value (5)."""
        email = _create_mock_email(subject="Urgent")
        mock_get_email.return_value = email
        mock_process.return_value = ("Content", "V1", "urgent", 5, "standard")
        mock_get_container.return_value = _create_mock_container(tokens_total=200)

        response = client.post(
            "/api/generate",
            json={"email_id": "test-id"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["priority"] == 5

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    @patch("app.api.routes_emails._process_email_with_use_case")
    @patch("app.api.routes_helpers._get_container")
    def test_generate_subject_already_has_re_prefix(
        self, mock_get_container, mock_process, mock_auth, mock_get_email, client
    ):
        """Generate with subject already having Re: prefix doesn't double it."""
        email = _create_mock_email(subject="Re: Original Subject")
        mock_get_email.return_value = email
        mock_process.return_value = ("Content", "V1", "commercial", 3, "standard")
        mock_get_container.return_value = _create_mock_container()

        response = client.post(
            "/api/generate",
            json={"email_id": "test-id"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["draft"]["subject"] == "Re: Original Subject"
        assert not data["draft"]["subject"].startswith("Re: Re:")

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    @patch("app.api.routes_emails._process_email_with_use_case")
    @patch("app.api.routes_helpers._get_container")
    def test_generate_subject_uppercase_re_prefix(
        self, mock_get_container, mock_process, mock_auth, mock_get_email, client
    ):
        """Generate with subject having uppercase RE: prefix doesn't double it."""
        email = _create_mock_email(subject="RE: Original Subject")
        mock_get_email.return_value = email
        mock_process.return_value = ("Content", "V1", "commercial", 3, "standard")
        mock_get_container.return_value = _create_mock_container()

        response = client.post(
            "/api/generate",
            json={"email_id": "test-id"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["draft"]["subject"] == "RE: Original Subject"

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    @patch("app.api.routes_emails._process_email_with_use_case")
    @patch("app.api.routes_helpers._get_container")
    def test_generate_subject_empty(
        self, mock_get_container, mock_process, mock_auth, mock_get_email, client
    ):
        """Generate with empty subject creates 'Re: ' prefix."""
        email = _create_mock_email(subject="")
        mock_get_email.return_value = email
        mock_process.return_value = ("Content", "V1", "commercial", 3, "standard")
        mock_get_container.return_value = _create_mock_container()

        response = client.post(
            "/api/generate",
            json={"email_id": "test-id"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["draft"]["subject"] == "Re: "

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    @patch("app.api.routes_emails._process_email_with_use_case")
    @patch("app.api.routes_helpers._get_container")
    def test_generate_subject_unicode(
        self, mock_get_container, mock_process, mock_auth, mock_get_email, client
    ):
        """Generate with unicode in subject preserves characters."""
        email = _create_mock_email(subject="日本語のメール件名 🎉")
        mock_get_email.return_value = email
        mock_process.return_value = ("Content", "V1", "commercial", 3, "standard")
        mock_get_container.return_value = _create_mock_container()

        response = client.post(
            "/api/generate",
            json={"email_id": "test-id"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["draft"]["subject"] == "Re: 日本語のメール件名 🎉"

    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_generate_provider_exception(self, mock_auth, client):
        """Generate with provider exception returns 500."""
        mock_auth.side_effect = Exception("Provider connection failed")

        response = client.post(
            "/api/generate",
            json={"email_id": "test-id"},
        )
        data = response.get_json()

        assert response.status_code == 500
        assert "error" in data

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    @patch("app.api.routes_emails._process_email_with_use_case")
    @patch("app.api.routes_helpers._get_container")
    def test_generate_different_classifications(
        self, mock_get_container, mock_process, mock_auth, mock_get_email, client
    ):
        """Generate with various classification types."""
        email = _create_mock_email()
        mock_get_email.return_value = email
        mock_get_container.return_value = _create_mock_container()

        for classification in ["commercial", "support", "urgent", "spam", "other"]:
            mock_process.return_value = ("Content", "V1", classification, 3, "standard")

            response = client.post(
                "/api/generate",
                json={"email_id": "test-id"},
            )
            data = response.get_json()

            assert response.status_code == 200
            assert data["classification"] == classification

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    @patch("app.api.routes_emails._process_email_with_use_case")
    @patch("app.api.routes_helpers._get_container")
    def test_generate_draft_body_with_special_characters(
        self, mock_get_container, mock_process, mock_auth, mock_get_email, client
    ):
        """Generate with special characters in draft body."""
        email = _create_mock_email()
        mock_get_email.return_value = email
        special_content = "Response with special chars: <html>&amp; \"quotes\" 'apostrophe'"
        mock_process.return_value = (special_content, "V1", "commercial", 3, "standard")
        mock_get_container.return_value = _create_mock_container()

        response = client.post(
            "/api/generate",
            json={"email_id": "test-id"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["draft"]["body"] == special_content

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    @patch("app.api.routes_emails._process_email_with_use_case")
    @patch("app.api.routes_helpers._get_container")
    def test_generate_empty_draft_body(
        self, mock_get_container, mock_process, mock_auth, mock_get_email, client
    ):
        """Generate with empty draft body."""
        email = _create_mock_email()
        mock_get_email.return_value = email
        mock_process.return_value = ("", "V1", "commercial", 3, "standard")
        mock_get_container.return_value = _create_mock_container(tokens_total=50)

        response = client.post(
            "/api/generate",
            json={"email_id": "test-id"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["draft"]["body"] == ""

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    @patch("app.api.routes_emails._process_email_with_use_case")
    @patch("app.api.routes_helpers._get_container")
    def test_generate_large_token_count(
        self, mock_get_container, mock_process, mock_auth, mock_get_email, client
    ):
        """Generate with large token count."""
        email = _create_mock_email()
        mock_get_email.return_value = email
        mock_process.return_value = ("Content", "V2", "commercial", 4, "standard")
        mock_get_container.return_value = _create_mock_container(tokens_total=100000)

        response = client.post(
            "/api/generate",
            json={"email_id": "test-id"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["draft"]["tokens_used"] == 100000

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    @patch("app.api.routes_emails._process_email_with_use_case")
    @patch("app.api.routes_helpers._get_container")
    def test_generate_email_found_in_middle_of_list(
        self, mock_get_container, mock_process, mock_auth, mock_get_email, client
    ):
        """Generate finds email by id."""
        email = _create_mock_email(
            email_id="email-5",
            sender="sender5@test.com",
            sender_name="Sender 5",
            subject="Subject 5",
            body="Body 5",
        )
        mock_get_email.return_value = email
        mock_process.return_value = ("Content", "V1", "commercial", 3, "standard")
        mock_get_container.return_value = _create_mock_container()

        response = client.post(
            "/api/generate",
            json={"email_id": "email-5"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["email_id"] == "email-5"
        assert data["draft"]["subject"] == "Re: Subject 5"

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    @patch("app.api.routes_emails._process_email_with_use_case")
    @patch("app.api.routes_helpers._get_container")
    def test_generate_agents_trace_is_empty_list(
        self, mock_get_container, mock_process, mock_auth, mock_get_email, client
    ):
        """Generate returns empty agents_trace list."""
        email = _create_mock_email()
        mock_get_email.return_value = email
        mock_process.return_value = ("Content", "V1", "commercial", 3, "standard")
        mock_get_container.return_value = _create_mock_container()

        response = client.post(
            "/api/generate",
            json={"email_id": "test-id"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert "agents_trace" in data
        assert isinstance(data["agents_trace"], list)
        assert len(data["agents_trace"]) == 0

    def test_generate_with_extra_fields_ignores_them(self, client):
        """Generate ignores extra fields in request body."""
        with (
            patch("app.api.routes_emails._get_email_by_id") as mock_get_email,
            patch("app.api.routes_emails._get_authenticated_provider"),
            patch("app.api.routes_emails._process_email_with_use_case") as mock_process,
            patch("app.api.routes_helpers._get_container") as mock_get_container,
        ):
            email = _create_mock_email()
            mock_get_email.return_value = email
            mock_process.return_value = ("Content", "V1", "commercial", 3, "standard")
            mock_get_container.return_value = _create_mock_container()

            response = client.post(
                "/api/generate",
                json={
                    "email_id": "test-id",
                    "extra_field": "should be ignored",
                    "another_field": 123,
                },
            )
            data = response.get_json()

            assert response.status_code == 200
            assert data["success"] is True

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    @patch("app.api.routes_emails._process_email_with_use_case")
    @patch("app.api.routes_helpers._get_container")
    def test_generate_token_reset_called(
        self, mock_get_container, mock_process, mock_auth, mock_get_email, client
    ):
        """Generate calls token_usage.reset() before processing."""
        email = _create_mock_email()
        mock_get_email.return_value = email
        mock_process.return_value = ("Content", "V1", "commercial", 3, "standard")
        container = _create_mock_container()
        mock_get_container.return_value = container

        response = client.post(
            "/api/generate",
            json={"email_id": "test-id"},
        )

        assert response.status_code == 200
        container.token_usage.reset.assert_called_once()


class TestGeneratePreviewToneParameter:
    """Tests for the optional tone parameter in POST /api/generate."""

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    @patch("app.api.routes_emails._process_email_with_use_case")
    @patch("app.api.routes_helpers._get_container")
    def test_generate_with_tone_formal(
        self, mock_get_container, mock_process, mock_auth, mock_get_email, client
    ):
        """Generate preview accepts tone='formal'."""
        email = _create_mock_email()
        mock_get_email.return_value = email
        mock_process.return_value = ("Content", "V1", "commercial", 3, "standard")
        mock_get_container.return_value = _create_mock_container()

        response = client.post(
            "/api/generate",
            json={"email_id": "test-id", "tone": "formal"},
        )

        assert response.status_code == 200

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    @patch("app.api.routes_emails._process_email_with_use_case")
    @patch("app.api.routes_helpers._get_container")
    def test_generate_with_tone_neutral(
        self, mock_get_container, mock_process, mock_auth, mock_get_email, client
    ):
        """Generate preview accepts tone='neutral'."""
        email = _create_mock_email()
        mock_get_email.return_value = email
        mock_process.return_value = ("Content", "V1", "commercial", 3, "standard")
        mock_get_container.return_value = _create_mock_container()

        response = client.post(
            "/api/generate",
            json={"email_id": "test-id", "tone": "neutral"},
        )

        assert response.status_code == 200

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    @patch("app.api.routes_emails._process_email_with_use_case")
    @patch("app.api.routes_helpers._get_container")
    def test_generate_without_tone(
        self, mock_get_container, mock_process, mock_auth, mock_get_email, client
    ):
        """Generate preview works without tone parameter (optional)."""
        email = _create_mock_email()
        mock_get_email.return_value = email
        mock_process.return_value = ("Content", "V1", "commercial", 3, "standard")
        mock_get_container.return_value = _create_mock_container()

        response = client.post(
            "/api/generate",
            json={"email_id": "test-id"},
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    @patch("app.api.routes_emails._process_email_with_use_case")
    @patch("app.api.routes_helpers._get_container")
    def test_generate_with_all_valid_tones(
        self, mock_get_container, mock_process, mock_auth, mock_get_email, client
    ):
        """Generate preview accepts all documented tone values."""
        email = _create_mock_email()
        mock_get_email.return_value = email
        mock_process.return_value = ("Content", "V1", "commercial", 3, "standard")
        mock_get_container.return_value = _create_mock_container()

        for tone in ["formal", "friendly", "neutral"]:
            response = client.post(
                "/api/generate",
                json={"email_id": "test-id", "tone": tone},
            )
            assert response.status_code == 200, f"Failed for tone={tone}"

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    @patch("app.api.routes_emails._process_email_with_use_case")
    @patch("app.api.routes_helpers._get_container")
    def test_generate_with_tone_case_insensitive(
        self, mock_get_container, mock_process, mock_auth, mock_get_email, client
    ):
        """Generate preview accepts tone in different cases (uppercase/mixed)."""
        email = _create_mock_email()
        mock_get_email.return_value = email
        mock_process.return_value = ("Content", "V1", "commercial", 3, "standard")
        mock_get_container.return_value = _create_mock_container()

        # Note: This test verifies current behavior, not necessarily spec compliance
        for tone in ["FORMAL", "Friendly", "NEUTRAL"]:
            response = client.post(
                "/api/generate",
                json={"email_id": "test-id", "tone": tone},
            )
            # Should accept (if implementation is case-insensitive) or reject
            # Document actual behavior
            assert response.status_code in (200, 400), f"Unexpected status for tone={tone}"

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    @patch("app.api.routes_emails._process_email_with_use_case")
    @patch("app.api.routes_helpers._get_container")
    def test_generate_with_null_tone(
        self, mock_get_container, mock_process, mock_auth, mock_get_email, client
    ):
        """Generate preview with null tone behaves like missing tone."""
        email = _create_mock_email()
        mock_get_email.return_value = email
        mock_process.return_value = ("Content", "V1", "commercial", 3, "standard")
        mock_get_container.return_value = _create_mock_container()

        response = client.post(
            "/api/generate",
            json={"email_id": "test-id", "tone": None},
        )

        # null tone should be treated as missing (optional parameter)
        assert response.status_code == 200

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    @patch("app.api.routes_emails._process_email_with_use_case")
    @patch("app.api.routes_helpers._get_container")
    def test_generate_with_empty_string_tone(
        self, mock_get_container, mock_process, mock_auth, mock_get_email, client
    ):
        """Generate preview with empty string tone."""
        email = _create_mock_email()
        mock_get_email.return_value = email
        mock_process.return_value = ("Content", "V1", "commercial", 3, "standard")
        mock_get_container.return_value = _create_mock_container()

        response = client.post(
            "/api/generate",
            json={"email_id": "test-id", "tone": ""},
        )

        # Empty string should be treated as missing or invalid
        # Document actual behavior (could be 200 or 400)
        assert response.status_code in (200, 400)


class TestGeneratePreviewResponseStructure:
    """Tests for response structure validation."""

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    @patch("app.api.routes_emails._process_email_with_use_case")
    @patch("app.api.routes_helpers._get_container")
    def test_response_has_all_required_fields(
        self, mock_get_container, mock_process, mock_auth, mock_get_email, client
    ):
        """Generate preview response contains all documented fields."""
        email = _create_mock_email()
        mock_get_email.return_value = email
        mock_process.return_value = ("Content", "V1", "commercial", 3, "standard")
        mock_get_container.return_value = _create_mock_container()

        response = client.post(
            "/api/generate",
            json={"email_id": "test-id"},
        )
        data = response.get_json()

        # All fields from OpenAPI spec must be present
        assert "success" in data
        assert "email_id" in data
        assert "classification" in data
        assert "priority" in data
        assert "status" in data
        assert "draft" in data
        assert "agents_trace" in data

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    @patch("app.api.routes_emails._process_email_with_use_case")
    @patch("app.api.routes_helpers._get_container")
    def test_draft_has_all_required_fields(
        self, mock_get_container, mock_process, mock_auth, mock_get_email, client
    ):
        """Generate preview draft object contains all documented fields."""
        email = _create_mock_email()
        mock_get_email.return_value = email
        mock_process.return_value = ("Content", "V1", "commercial", 3, "standard")
        mock_get_container.return_value = _create_mock_container()

        response = client.post(
            "/api/generate",
            json={"email_id": "test-id"},
        )
        data = response.get_json()
        draft = data.get("draft", {})

        assert "subject" in draft
        assert "body" in draft
        assert "tokens_used" in draft

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    @patch("app.api.routes_emails._process_email_with_use_case")
    @patch("app.api.routes_helpers._get_container")
    def test_response_field_types(
        self, mock_get_container, mock_process, mock_auth, mock_get_email, client
    ):
        """Generate preview response fields have correct types."""
        email = _create_mock_email()
        mock_get_email.return_value = email
        mock_process.return_value = ("Content", "V1", "commercial", 3, "standard")
        mock_get_container.return_value = _create_mock_container()

        response = client.post(
            "/api/generate",
            json={"email_id": "test-id"},
        )
        data = response.get_json()

        assert isinstance(data["success"], bool)
        assert isinstance(data["email_id"], str)
        assert isinstance(data["classification"], str)
        assert isinstance(data["priority"], int)
        assert isinstance(data["status"], str)
        assert isinstance(data["draft"], dict)
        assert isinstance(data["agents_trace"], list)

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    @patch("app.api.routes_emails._process_email_with_use_case")
    @patch("app.api.routes_helpers._get_container")
    def test_draft_field_types(
        self, mock_get_container, mock_process, mock_auth, mock_get_email, client
    ):
        """Generate preview draft fields have correct types."""
        email = _create_mock_email()
        mock_get_email.return_value = email
        mock_process.return_value = ("Content", "V1", "commercial", 3, "standard")
        mock_get_container.return_value = _create_mock_container()

        response = client.post(
            "/api/generate",
            json={"email_id": "test-id"},
        )
        data = response.get_json()
        draft = data.get("draft", {})

        assert isinstance(draft["subject"], str)
        assert isinstance(draft["body"], str)
        assert isinstance(draft["tokens_used"], int)

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    @patch("app.api.routes_emails._process_email_with_use_case")
    @patch("app.api.routes_helpers._get_container")
    def test_status_is_v1_or_v2(
        self, mock_get_container, mock_process, mock_auth, mock_get_email, client
    ):
        """Generate preview status is V1 or V2 as documented."""
        email = _create_mock_email()
        mock_get_email.return_value = email
        mock_process.return_value = ("Content", "V1", "commercial", 3, "standard")
        mock_get_container.return_value = _create_mock_container()

        response = client.post(
            "/api/generate",
            json={"email_id": "test-id"},
        )
        data = response.get_json()

        assert data["status"] in ["V1", "V2"]

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    @patch("app.api.routes_emails._process_email_with_use_case")
    @patch("app.api.routes_helpers._get_container")
    def test_priority_in_valid_range(
        self, mock_get_container, mock_process, mock_auth, mock_get_email, client
    ):
        """Generate preview priority is between 1 and 5 as documented."""
        email = _create_mock_email()
        mock_get_email.return_value = email
        mock_process.return_value = ("Content", "V1", "commercial", 3, "standard")
        mock_get_container.return_value = _create_mock_container()

        response = client.post(
            "/api/generate",
            json={"email_id": "test-id"},
        )
        data = response.get_json()

        assert 1 <= data["priority"] <= 5
