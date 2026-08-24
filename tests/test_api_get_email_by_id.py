# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests for GET /api/emails/{id} endpoint."""

from unittest.mock import Mock, patch, MagicMock

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


def _make_email_dict(
    email_id="test-email-123",
    sender="sender@test.com",
    sender_name="Test Sender",
    subject="Test Subject",
    body="Test email body content",
    body_html="<p>Test email body content</p>",
    received_at="2025-01-01T10:00:00",
    has_attachments=False,
    conversation_id="conv-123",
    **overrides,
):
    """Build a cached email dict for mocking _get_cached_email_detail."""
    result = {
        "id": email_id,
        "sender": sender,
        "sender_name": sender_name,
        "subject": subject,
        "body": body,
        "body_html": body_html,
        "body_text": body or "",
        "received_at": received_at,
        "has_attachments": has_attachments,
        "attachments": [],
        "conversation_id": conversation_id,
        "is_read": False,
        "body_preview": (body or "")[:100],
        "has_pending_draft": False,
        "labels": [],
    }
    result.update(overrides)
    return result


def _no_accounts():
    """Return a mock get_account_manager that has no accounts."""
    mgr = MagicMock()
    mgr.get_all_accounts.return_value = []
    return mgr


def _bypass_caches_and_accounts():
    """Return a dict of common patches to bypass caches and force provider path."""
    return {
        "cache": patch("app.api.routes_emails._get_cached_email_detail", return_value=None),
        "list_cache": patch("app.api.routes_emails._find_email_in_list_cache", return_value=None),
        "current_acct": patch("app.multi_accounts.get_current_account", return_value=None),
        "acct_mgr": patch("app.multi_accounts.get_account_manager", return_value=_no_accounts()),
    }


class TestGetEmailByIdEndpoint:
    """Tests for GET /api/emails/{id} endpoint."""

    @patch("app.api.routes_emails._get_cached_email_detail")
    def test_get_email_success(self, mock_cache, client):
        """Get email by ID returns email details."""
        mock_cache.return_value = _make_email_dict()

        response = client.get("/api/emails/test-email-123")
        data = response.get_json()

        assert response.status_code == 200
        assert data["id"] == "test-email-123"
        assert data["sender"] == "sender@test.com"
        assert data["sender_name"] == "Test Sender"
        assert data["subject"] == "Test Subject"
        assert data["received_at"] == "2025-01-01T10:00:00"
        assert data["has_attachments"] is False
        assert data["conversation_id"] == "conv-123"

    def test_get_email_not_found(self, client):
        """Get email with non-existent ID returns 404."""
        patches = _bypass_caches_and_accounts()
        with patches["cache"], patches["list_cache"], patches["current_acct"], patches["acct_mgr"]:
            with patch("app.api.routes_emails._get_authenticated_provider") as mock_auth:
                with patch("app.api.routes_emails._get_email_by_id_for_detail") as mock_get_email:
                    mock_auth.return_value = Mock()
                    mock_get_email.side_effect = NotFound("Email not found")

                    response = client.get("/api/emails/nonexistent-id")
                    response.get_json()

                    assert response.status_code == 404

    def test_get_email_invalid_id(self, client):
        """Get email with invalid ID format returns 400."""
        response = client.get("/api/emails/test!invalid&chars")
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "Invalid email_id format" in data["error"]

    def test_get_email_auth_failure(self, client):
        """Get email with authentication failure returns 503."""
        patches = _bypass_caches_and_accounts()
        with patches["cache"], patches["list_cache"], patches["current_acct"], patches["acct_mgr"]:
            with patch("app.api.routes_emails._get_authenticated_provider") as mock_auth:
                mock_auth.side_effect = ServiceUnavailable("Email provider authentication failed")

                response = client.get("/api/emails/test-id")

                assert response.status_code == 503

    def test_get_email_provider_exception(self, client):
        """Get email with provider exception returns 500."""
        patches = _bypass_caches_and_accounts()
        with patches["cache"], patches["list_cache"], patches["current_acct"], patches["acct_mgr"]:
            with patch("app.api.routes_emails._get_authenticated_provider") as mock_auth:
                mock_auth.side_effect = Exception("Provider connection failed")

                response = client.get("/api/emails/test-id")
                data = response.get_json()

                assert response.status_code == 500
                assert "error" in data


class TestGetEmailByIdEdgeCases:
    """Edge case tests for GET /api/emails/{id} endpoint."""

    def test_get_email_empty_id(self, client):
        """Get email with empty ID returns 404 (no route match)."""
        response = client.get("/api/emails/")

        assert response.status_code == 404

    def test_get_email_special_characters(self, client):
        """Get email with invalid special characters returns 400."""
        response = client.get("/api/emails/test*invalid|chars")
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "Invalid email_id format" in data["error"]

    def test_get_email_unicode_id(self, client):
        """Get email with unicode in ID returns 400."""
        response = client.get("/api/emails/test-émàïl-日本語")
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "Invalid email_id format" in data["error"]

    def test_get_email_id_too_long(self, client):
        """Get email with very long ID returns 400."""
        long_id = "a" * 1000
        response = client.get(f"/api/emails/{long_id}")
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "Invalid email_id format" in data["error"]

    @patch("app.api.routes_emails._get_cached_email_detail")
    def test_get_email_found_in_middle_of_list(self, mock_cache, client):
        """Get email finds email by ID from cache."""
        mock_cache.return_value = _make_email_dict(
            email_id="email-5",
            sender="sender5@test.com",
            sender_name="Sender 5",
            subject="Subject 5",
            body="Body content 5",
            body_html="<p>Body content 5</p>",
        )

        response = client.get("/api/emails/email-5")
        data = response.get_json()

        assert response.status_code == 200
        assert data["id"] == "email-5"
        assert data["sender"] == "sender5@test.com"
        assert data["subject"] == "Subject 5"

    @patch("app.api.routes_emails._get_cached_email_detail")
    def test_get_email_with_attachments(self, mock_cache, client):
        """Get email with attachments returns has_attachments as True."""
        mock_cache.return_value = _make_email_dict(
            email_id="email-with-attachment",
            subject="Email with PDF",
            body="Email body with attachment reference",
            has_attachments=True,
            attachments=[{"filename": "file.pdf", "size": 2048}],
        )

        response = client.get("/api/emails/email-with-attachment")
        data = response.get_json()

        assert response.status_code == 200
        assert data["has_attachments"] is True

    @patch("app.api.routes_emails._get_cached_email_detail")
    def test_get_email_valid_id_formats(self, mock_cache, client):
        """Get email accepts various valid ID formats."""
        valid_ids = [
            "simple-id",
            "email_123",
            "test.email.id",
            "CAM+12345@example.com",
            "192abc123",
        ]

        for valid_id in valid_ids:
            mock_cache.return_value = _make_email_dict(email_id=valid_id)

            response = client.get(f"/api/emails/{valid_id}")

            assert response.status_code == 200, f"Failed for ID: {valid_id}"

    @patch("app.api.routes_emails._get_cached_email_detail")
    def test_get_email_response_content_type(self, mock_cache, client):
        """Response content type is application/json."""
        mock_cache.return_value = _make_email_dict(email_id="test-id")

        response = client.get("/api/emails/test-id")

        assert response.content_type == "application/json"

    @patch("app.api.routes_emails._get_cached_email_detail")
    def test_get_email_preserves_id_case(self, mock_cache, client):
        """ID case is preserved in response."""
        mock_cache.return_value = _make_email_dict(email_id="TestEmailABC123")

        response = client.get("/api/emails/TestEmailABC123")
        data = response.get_json()

        assert data["id"] == "TestEmailABC123"


class TestGetEmailByIdHttpMethods:
    """HTTP method tests for GET /api/emails/{id}."""

    def test_get_email_method_not_allowed_post(self, client):
        """POST instead of GET returns 405."""
        response = client.post("/api/emails/test-id")

        assert response.status_code == 405

    def test_get_email_method_not_allowed_put(self, client):
        """PUT instead of GET returns 405."""
        response = client.put("/api/emails/test-id")

        assert response.status_code == 405

    def test_get_email_method_not_allowed_delete(self, client):
        """DELETE instead of GET returns 405."""
        response = client.delete("/api/emails/test-id")

        assert response.status_code == 405


class TestGetEmailByIdSecurity:
    """Security tests for GET /api/emails/{id}."""

    def test_get_email_path_traversal_attempt(self, client):
        """Path traversal attempt is blocked by Flask routing."""
        response = client.get("/api/emails/..%2F..%2Fetc%2Fpasswd")

        assert response.status_code == 404

    def test_get_email_xss_attempt_script_tag(self, client):
        """XSS attempt with script tag is blocked by Flask routing."""
        response = client.get("/api/emails/<script>alert(1)</script>")

        assert response.status_code == 404

    def test_get_email_xss_attempt_encoded(self, client):
        """Encoded XSS attempt is blocked by Flask routing."""
        response = client.get("/api/emails/%3Cscript%3Ealert%281%29%3C%2Fscript%3E")

        assert response.status_code == 404

    def test_get_email_sql_injection_attempt(self, client):
        """SQL injection attempt returns 400."""
        response = client.get("/api/emails/1'; DROP TABLE emails;--")
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    def test_get_email_null_byte_injection(self, client):
        """Null byte injection returns 400."""
        response = client.get("/api/emails/test%00malicious")
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    def test_get_email_newline_injection(self, client):
        """Newline in ID returns 400 (log injection prevention)."""
        response = client.get("/api/emails/test%0Amalicious")
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    def test_get_email_carriage_return_injection(self, client):
        """Carriage return in ID returns 400."""
        response = client.get("/api/emails/test%0Dmalicious")
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    def test_get_email_emoji_id_rejected(self, client):
        """Emoji in ID returns 400."""
        response = client.get("/api/emails/email-📧")
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data


class TestGetEmailByIdBoundary:
    """Boundary tests for GET /api/emails/{id}."""

    def test_get_email_id_boundary_255_chars(self, client):
        """ID of 255 characters is accepted by validation."""
        valid_id = "a" * 255
        with patch("app.api.routes_emails._get_cached_email_detail") as mock_cache:
            mock_cache.return_value = _make_email_dict(email_id=valid_id)
            response = client.get(f"/api/emails/{valid_id}")

            # Should pass validation (not 400)
            assert response.status_code != 400

    def test_get_email_id_boundary_256_chars(self, client):
        """ID of 256 characters (exact limit) is accepted."""
        valid_id = "a" * 256
        with patch("app.api.routes_emails._get_cached_email_detail") as mock_cache:
            mock_cache.return_value = _make_email_dict(email_id=valid_id)
            response = client.get(f"/api/emails/{valid_id}")

            assert response.status_code != 400

    def test_get_email_id_boundary_257_chars(self, client):
        """ID of 257 characters (limit + 1) returns 400."""
        invalid_id = "a" * 257
        response = client.get(f"/api/emails/{invalid_id}")
        data = response.get_json()

        assert response.status_code == 400
        assert "Invalid email_id format" in data["error"]

    def test_get_email_only_dots(self, client):
        """ID with only dots is valid format."""
        with patch("app.api.routes_emails._get_cached_email_detail") as mock_cache:
            mock_cache.return_value = _make_email_dict(email_id="...")
            response = client.get("/api/emails/...")

            assert response.status_code != 400

    def test_get_email_only_dashes(self, client):
        """ID with only dashes is valid format."""
        with patch("app.api.routes_emails._get_cached_email_detail") as mock_cache:
            mock_cache.return_value = _make_email_dict(email_id="---")
            response = client.get("/api/emails/---")

            assert response.status_code != 400

    def test_get_email_single_char_id(self, client):
        """Single character ID is valid format."""
        with patch("app.api.routes_emails._get_cached_email_detail") as mock_cache:
            mock_cache.return_value = _make_email_dict(email_id="a")
            response = client.get("/api/emails/a")

            assert response.status_code != 400

    def test_get_email_auth_exception(self, client):
        """Exception during provider auth returns 500."""
        patches = _bypass_caches_and_accounts()
        with patches["cache"], patches["list_cache"], patches["current_acct"], patches["acct_mgr"]:
            with patch("app.api.routes_emails._get_authenticated_provider") as mock_auth:
                mock_auth.side_effect = Exception("Network error")

                response = client.get("/api/emails/test-id")
                data = response.get_json()

                assert response.status_code == 500
                assert "error" in data
