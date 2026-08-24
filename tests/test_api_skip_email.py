# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests for POST /api/emails/{id}/skip endpoint."""

from unittest.mock import Mock, patch

import pytest
from werkzeug.exceptions import NotFound, ServiceUnavailable


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


def _mock_provider():
    """Create a mock provider for skip tests."""
    provider = Mock()
    provider.mark_as_read.return_value = True
    return provider


class TestSkipEmailEndpoint:
    """Tests for POST /api/emails/{id}/skip endpoint."""

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_skip_email_success(self, mock_auth, mock_get_email, client):
        """Skip email returns 200 with success=true."""
        mock_email = Mock()
        mock_email.id = "test-email-id"
        mock_get_email.return_value = mock_email
        mock_auth.return_value = _mock_provider()

        response = client.post("/api/emails/test-email-id/skip")
        data = response.get_json()

        assert response.status_code == 200
        assert data["success"] is True
        assert data["email_id"] == "test-email-id"

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_skip_email_marks_as_read(self, mock_auth, mock_get_email, client):
        """Skip email calls mark_as_read on the provider."""
        mock_email = Mock()
        mock_email.id = "test-email-id"
        mock_get_email.return_value = mock_email
        mock_provider = _mock_provider()
        mock_auth.return_value = mock_provider

        client.post("/api/emails/test-email-id/skip")

        mock_provider.mark_as_read.assert_called_once_with("test-email-id")

    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_skip_email_auth_failure(self, mock_auth, client):
        """Skip email with authentication failure returns 503."""
        mock_auth.side_effect = ServiceUnavailable("Email provider authentication failed")

        response = client.post("/api/emails/test-id/skip")
        response.get_json()

        assert response.status_code == 503

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_skip_email_not_found(self, mock_auth, mock_get_email, client):
        """Skip email with non-existent email returns 404."""
        mock_auth.return_value = _mock_provider()
        mock_get_email.side_effect = NotFound("Email not found")

        response = client.post("/api/emails/nonexistent-id/skip")
        response.get_json()

        assert response.status_code == 404

    def test_skip_email_invalid_id_format(self, client):
        """Skip email with invalid email_id format returns 400."""
        response = client.post("/api/emails/invalid--id!!/skip")
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "email_id" in data["error"].lower()

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_skip_email_with_reason(self, mock_auth, mock_get_email, client):
        """Skip email accepts optional reason in JSON body."""
        mock_email = Mock()
        mock_email.id = "test-email-id"
        mock_get_email.return_value = mock_email
        mock_auth.return_value = _mock_provider()

        response = client.post(
            "/api/emails/test-email-id/skip",
            json={"reason": "Not relevant to my work"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["success"] is True
        assert data["email_id"] == "test-email-id"

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_skip_email_without_body(self, mock_auth, mock_get_email, client):
        """Skip email works without JSON body."""
        mock_email = Mock()
        mock_email.id = "test-email-id"
        mock_get_email.return_value = mock_email
        mock_auth.return_value = _mock_provider()

        response = client.post("/api/emails/test-email-id/skip")
        data = response.get_json()

        assert response.status_code == 200
        assert data["success"] is True

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_skip_email_provider_error(self, mock_auth, mock_get_email, client):
        """Skip email with provider error returns 500."""
        mock_email = Mock()
        mock_email.id = "test-email-id"
        mock_get_email.return_value = mock_email
        mock_provider = _mock_provider()
        mock_provider.mark_as_read.side_effect = Exception("Provider error")
        mock_auth.return_value = mock_provider

        response = client.post("/api/emails/test-email-id/skip")
        data = response.get_json()

        assert response.status_code == 500
        assert "error" in data


class TestSkipEmailEdgeCases:
    """Edge case tests for POST /api/emails/{id}/skip endpoint."""

    def test_skip_email_id_too_long(self, client):
        """Skip email with email_id too long returns 400."""
        long_id = "a" * 1001

        response = client.post(f"/api/emails/{long_id}/skip")
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_skip_email_empty_reason_allowed(self, mock_auth, mock_get_email, client):
        """Skip email with empty reason is allowed."""
        mock_email = Mock()
        mock_email.id = "test-email-id"
        mock_get_email.return_value = mock_email
        mock_auth.return_value = _mock_provider()

        response = client.post(
            "/api/emails/test-email-id/skip",
            json={"reason": ""},
        )

        assert response.status_code == 200

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_skip_email_ignores_extra_fields(self, mock_auth, mock_get_email, client):
        """Skip email ignores extra fields in request."""
        mock_email = Mock()
        mock_email.id = "test-email-id"
        mock_get_email.return_value = mock_email
        mock_auth.return_value = _mock_provider()

        response = client.post(
            "/api/emails/test-email-id/skip",
            json={
                "reason": "Not relevant",
                "extra_field": "should be ignored",
                "another": 123,
            },
        )

        assert response.status_code == 200

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_skip_email_unicode_reason(self, mock_auth, mock_get_email, client):
        """Skip email with unicode reason works correctly."""
        mock_email = Mock()
        mock_email.id = "test-email-id"
        mock_get_email.return_value = mock_email
        mock_auth.return_value = _mock_provider()

        response = client.post(
            "/api/emails/test-email-id/skip",
            json={"reason": "Pas pertinent pour moi 日本語 🎉"},
        )

        assert response.status_code == 200

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_skip_email_null_reason_allowed(self, mock_auth, mock_get_email, client):
        """Skip email with null reason is allowed."""
        mock_email = Mock()
        mock_email.id = "test-email-id"
        mock_get_email.return_value = mock_email
        mock_auth.return_value = _mock_provider()

        response = client.post(
            "/api/emails/test-email-id/skip",
            json={"reason": None},
        )

        assert response.status_code == 200

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_skip_email_reason_as_number_ignored(self, mock_auth, mock_get_email, client):
        """Skip email with reason as number is ignored (not validated)."""
        mock_email = Mock()
        mock_email.id = "test-email-id"
        mock_get_email.return_value = mock_email
        mock_auth.return_value = _mock_provider()

        response = client.post(
            "/api/emails/test-email-id/skip",
            json={"reason": 12345},
        )

        assert response.status_code == 200

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_skip_email_invalid_json(self, mock_auth, mock_get_email, client):
        """Skip email with invalid JSON still works (body is optional)."""
        mock_email = Mock()
        mock_email.id = "test-id"
        mock_get_email.return_value = mock_email
        mock_auth.return_value = _mock_provider()

        response = client.post(
            "/api/emails/test-id/skip",
            data="not valid json{",
            content_type="application/json",
        )

        assert response.status_code in (200, 400, 415)

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_skip_email_with_empty_json_body(self, mock_auth, mock_get_email, client):
        """Skip email with empty JSON body works."""
        mock_email = Mock()
        mock_email.id = "test-email-id"
        mock_get_email.return_value = mock_email
        mock_auth.return_value = _mock_provider()

        response = client.post(
            "/api/emails/test-email-id/skip",
            json={},
        )

        assert response.status_code == 200

    def test_skip_email_special_chars_in_id(self, client):
        """Skip email with special characters in ID returns 400."""
        response = client.post("/api/emails/invalid$chars%here/skip")
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_skip_email_valid_gmail_id(self, mock_auth, mock_get_email, client):
        """Skip email with valid Gmail-style ID works."""
        mock_email = Mock()
        mock_email.id = "18e45d2a3b4c5f67"
        mock_get_email.return_value = mock_email
        mock_auth.return_value = _mock_provider()

        response = client.post("/api/emails/18e45d2a3b4c5f67/skip")

        assert response.status_code == 200

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_skip_email_valid_alphanumeric_id(self, mock_auth, mock_get_email, client):
        """Skip email with alphanumeric ID works."""
        mock_email = Mock()
        mock_email.id = "AAMkAGI2TG93AAA"
        mock_get_email.return_value = mock_email
        mock_auth.return_value = _mock_provider()

        response = client.post("/api/emails/AAMkAGI2TG93AAA/skip")

        assert response.status_code == 200


class TestSkipEmailBoundaryConditions:
    """Boundary condition tests for POST /api/emails/{id}/skip endpoint."""

    def test_skip_email_empty_id(self, client):
        """Skip email with empty email_id returns 405 (Flask routing)."""
        # Flask routing treats "/api/emails//skip" as "/api/emails/skip"
        # which has no POST handler, resulting in 405 Method Not Allowed
        response = client.post("/api/emails//skip")

        assert response.status_code == 405

    def test_skip_email_whitespace_only_id(self, client):
        """Skip email with whitespace-only ID returns 400."""
        response = client.post("/api/emails/%20%20%20/skip")
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_skip_email_id_exactly_at_max_length(self, mock_auth, mock_get_email, client):
        """Skip email with ID exactly at max length (256) works."""
        max_length_id = "a" * 256
        mock_email = Mock()
        mock_email.id = max_length_id
        mock_get_email.return_value = mock_email
        mock_auth.return_value = _mock_provider()

        response = client.post(f"/api/emails/{max_length_id}/skip")

        assert response.status_code == 200

    def test_skip_email_id_one_over_max_length(self, client):
        """Skip email with ID one char over max length (257) returns 400."""
        over_max_id = "a" * 257

        response = client.post(f"/api/emails/{over_max_id}/skip")
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    def test_skip_email_id_with_leading_space(self, client):
        """Skip email with leading space in ID returns 400."""
        response = client.post("/api/emails/%20test-id/skip")
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    def test_skip_email_id_with_trailing_space(self, client):
        """Skip email with trailing space in ID returns 400."""
        response = client.post("/api/emails/test-id%20/skip")
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_skip_email_id_with_valid_special_chars(self, mock_auth, mock_get_email, client):
        """Skip email with valid special characters (+@._-) works."""
        valid_id = "test+user@domain.com_msg-123"
        mock_email = Mock()
        mock_email.id = valid_id
        mock_get_email.return_value = mock_email
        mock_auth.return_value = _mock_provider()

        response = client.post(f"/api/emails/{valid_id}/skip")

        assert response.status_code == 200


class TestSkipEmailHttpMethods:
    """HTTP method tests for POST /api/emails/{id}/skip endpoint."""

    def test_skip_email_get_method_not_allowed(self, client):
        """GET method on skip endpoint returns 405."""
        response = client.get("/api/emails/test-id/skip")

        assert response.status_code == 405

    def test_skip_email_put_method_not_allowed(self, client):
        """PUT method on skip endpoint returns 405."""
        response = client.put("/api/emails/test-id/skip")

        assert response.status_code == 405

    def test_skip_email_delete_method_not_allowed(self, client):
        """DELETE method on skip endpoint returns 405."""
        response = client.delete("/api/emails/test-id/skip")

        assert response.status_code == 405

    def test_skip_email_patch_method_not_allowed(self, client):
        """PATCH method on skip endpoint returns 405."""
        response = client.patch("/api/emails/test-id/skip")

        assert response.status_code == 405


class TestSkipEmailProviderBehavior:
    """Tests for provider behavior in skip_email endpoint."""

    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_skip_email_provider_returns_none(self, mock_auth, client):
        """Skip email when provider returns None on authentication aborts 503."""
        mock_auth.side_effect = ServiceUnavailable("No email provider configured")

        response = client.post("/api/emails/test-id/skip")

        assert response.status_code == 503

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_skip_email_mark_as_read_returns_false(self, mock_auth, mock_get_email, client):
        """Skip email when mark_as_read returns False still returns 200."""
        mock_email = Mock()
        mock_email.id = "test-id"
        mock_get_email.return_value = mock_email
        mock_provider = _mock_provider()
        mock_provider.mark_as_read.return_value = False
        mock_auth.return_value = mock_provider

        response = client.post("/api/emails/test-id/skip")

        # Implementation doesn't check return value, so 200 is expected
        assert response.status_code == 200

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_skip_email_get_email_not_found(self, mock_auth, mock_get_email, client):
        """Skip email when email not found returns 404."""
        mock_auth.return_value = _mock_provider()
        mock_get_email.side_effect = NotFound("Email not found")

        response = client.post("/api/emails/test-id/skip")
        response.get_json()

        assert response.status_code == 404

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_skip_email_get_email_raises(self, mock_auth, mock_get_email, client):
        """Skip email when _get_email_by_id raises exception returns 500."""
        mock_auth.return_value = _mock_provider()
        mock_get_email.side_effect = Exception("Network error")

        response = client.post("/api/emails/test-id/skip")
        data = response.get_json()

        assert response.status_code == 500
        assert "error" in data

    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_skip_email_authenticate_raises_exception(self, mock_auth, client):
        """Skip email when authenticate raises exception returns 500."""
        mock_auth.side_effect = Exception("Auth service down")

        response = client.post("/api/emails/test-id/skip")
        data = response.get_json()

        assert response.status_code == 500
        assert "error" in data


class TestSkipEmailIdempotency:
    """Idempotency tests for POST /api/emails/{id}/skip endpoint."""

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_skip_email_idempotent_multiple_calls(self, mock_auth, mock_get_email, client):
        """Skip email can be called multiple times on same email."""
        mock_email = Mock()
        mock_email.id = "test-id"
        mock_get_email.return_value = mock_email
        mock_provider = _mock_provider()
        mock_auth.return_value = mock_provider

        # First call
        response1 = client.post("/api/emails/test-id/skip")
        # Second call (idempotent behavior)
        response2 = client.post("/api/emails/test-id/skip")

        assert response1.status_code == 200
        assert response2.status_code == 200
        assert mock_provider.mark_as_read.call_count == 2


class TestSkipEmailReasonField:
    """Tests for reason field handling in skip_email endpoint."""

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_skip_email_very_long_reason(self, mock_auth, mock_get_email, client):
        """Skip email with very long reason string is accepted."""
        mock_email = Mock()
        mock_email.id = "test-id"
        mock_get_email.return_value = mock_email
        mock_auth.return_value = _mock_provider()

        long_reason = "x" * 10000

        response = client.post(
            "/api/emails/test-id/skip",
            json={"reason": long_reason},
        )

        assert response.status_code == 200

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_skip_email_reason_with_html(self, mock_auth, mock_get_email, client):
        """Skip email with HTML in reason is accepted (no XSS risk in JSON response)."""
        mock_email = Mock()
        mock_email.id = "test-id"
        mock_get_email.return_value = mock_email
        mock_auth.return_value = _mock_provider()

        response = client.post(
            "/api/emails/test-id/skip",
            json={"reason": "<script>alert('xss')</script>"},
        )

        assert response.status_code == 200

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_skip_email_reason_with_sql_injection_attempt(self, mock_auth, mock_get_email, client):
        """Skip email with SQL injection in reason is accepted (no SQL vulnerability)."""
        mock_email = Mock()
        mock_email.id = "test-id"
        mock_get_email.return_value = mock_email
        mock_auth.return_value = _mock_provider()

        response = client.post(
            "/api/emails/test-id/skip",
            json={"reason": "'; DROP TABLE users; --"},
        )

        assert response.status_code == 200

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_skip_email_reason_as_dict(self, mock_auth, mock_get_email, client):
        """Skip email with reason as dict is accepted (ignored)."""
        mock_email = Mock()
        mock_email.id = "test-id"
        mock_get_email.return_value = mock_email
        mock_auth.return_value = _mock_provider()

        response = client.post(
            "/api/emails/test-id/skip",
            json={"reason": {"nested": "object"}},
        )

        assert response.status_code == 200

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_skip_email_reason_as_list(self, mock_auth, mock_get_email, client):
        """Skip email with reason as list is accepted (ignored)."""
        mock_email = Mock()
        mock_email.id = "test-id"
        mock_get_email.return_value = mock_email
        mock_auth.return_value = _mock_provider()

        response = client.post(
            "/api/emails/test-id/skip",
            json={"reason": ["item1", "item2"]},
        )

        assert response.status_code == 200
