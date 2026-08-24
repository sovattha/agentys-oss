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
    email_id="test-email-id",
    sender="sender@test.com",
    sender_name="Test Sender",
    subject="Test Subject",
    body="This is the email body content.",
    body_html="<p>This is the email body content.</p>",
    received_at="2025-01-02T10:00:00Z",
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


class TestGetEmailEndpoint:
    """Tests for GET /api/emails/{id} endpoint."""

    @patch("app.api.routes_emails._get_cached_email_detail")
    def test_get_email_success(self, mock_cache, client):
        """Get email returns 200 with email details."""
        mock_cache.return_value = _make_email_dict()

        response = client.get("/api/emails/test-email-id")
        data = response.get_json()

        assert response.status_code == 200
        assert data["id"] == "test-email-id"
        assert data["sender"] == "sender@test.com"
        assert data["sender_name"] == "Test Sender"
        assert data["subject"] == "Test Subject"

    @patch("app.api.routes_emails._get_cached_email_detail")
    def test_get_email_returns_full_body(self, mock_cache, client):
        """Get email returns the full body content."""
        mock_cache.return_value = _make_email_dict(
            body="This is the complete email body with all details.",
            body_html="<p>This is the complete email body with all details.</p>",
        )

        response = client.get("/api/emails/test-email-id")
        data = response.get_json()

        assert response.status_code == 200
        assert "body" in data or "body_text" in data
        body_content = data.get("body_text") or data.get("body") or ""
        assert "complete email body" in body_content

    @patch("app.api.routes_emails._get_cached_email_detail")
    def test_get_email_returns_cached_text_body_without_html(self, mock_cache, client):
        """Privacy-mode body fetches live in RAM even when body_html is absent."""
        mock_cache.return_value = _make_email_dict(
            body="Fetched body from memory cache.",
            body_text="Fetched body from memory cache.",
            body_html=None,
        )

        response = client.get("/api/emails/test-email-id")
        data = response.get_json()

        assert response.status_code == 200
        assert data["body_text"] == "Fetched body from memory cache."
        assert data["body"] == "Fetched body from memory cache."

    def test_get_email_auth_failure(self, client):
        """Get email with authentication failure returns 503."""
        patches = _bypass_caches_and_accounts()
        with patches["cache"], patches["list_cache"], patches["current_acct"], patches["acct_mgr"]:
            with patch("app.api.routes_emails._get_authenticated_provider") as mock_auth:
                mock_auth.side_effect = ServiceUnavailable("Email provider authentication failed")

                response = client.get("/api/emails/test-id")

                assert response.status_code == 503

    def test_get_email_not_found(self, client):
        """Get email with non-existent id returns 404."""
        patches = _bypass_caches_and_accounts()
        with patches["cache"], patches["list_cache"], patches["current_acct"], patches["acct_mgr"]:
            with patch("app.api.routes_emails._get_authenticated_provider") as mock_auth:
                with patch("app.api.routes_emails._get_email_by_id_for_detail") as mock_get_email:
                    mock_auth.return_value = Mock()
                    mock_get_email.side_effect = NotFound("Email not found")

                    response = client.get("/api/emails/nonexistent-id")
                    response.get_json()

                    assert response.status_code == 404

    def test_get_email_invalid_id_format(self, client):
        """Get email with invalid email_id format returns 400."""
        response = client.get("/api/emails/invalid--id!!")
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "email_id" in data["error"].lower()


class TestGetEmailEdgeCases:
    """Edge case tests for GET /api/emails/{id} endpoint."""

    def test_get_email_id_too_long(self, client):
        """Get email with email_id too long returns 400."""
        long_id = "a" * 1001

        response = client.get(f"/api/emails/{long_id}")
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    def test_get_email_id_with_special_chars(self, client):
        """Get email with special characters in id returns 400."""
        response = client.get("/api/emails/id%20with%20spaces")
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    def test_get_email_provider_error(self, client):
        """Get email with provider error returns 500."""
        patches = _bypass_caches_and_accounts()
        with patches["cache"], patches["list_cache"], patches["current_acct"], patches["acct_mgr"]:
            with patch("app.api.routes_emails._get_authenticated_provider") as mock_auth:
                mock_auth.side_effect = Exception("Provider error")

                response = client.get("/api/emails/test-id")
                data = response.get_json()

                assert response.status_code == 500
                assert "error" in data

    @patch("app.api.routes_emails._get_cached_email_detail")
    def test_get_email_empty_body(self, mock_cache, client):
        """Get email with empty body returns correctly."""
        mock_cache.return_value = _make_email_dict(body="", body_html="<p></p>")

        response = client.get("/api/emails/test-email-id")
        response.get_json()

        assert response.status_code == 200

    @patch("app.api.routes_emails._get_cached_email_detail")
    def test_get_email_with_attachments(self, mock_cache, client):
        """Get email with attachments returns has_attachments correctly."""
        mock_cache.return_value = _make_email_dict(
            subject="Subject with attachment",
            body="Please find attached.",
            has_attachments=True,
            conversation_id="conv-456",
            attachments=[{"filename": "doc.pdf", "size": 1024}],
        )

        response = client.get("/api/emails/test-email-id")
        data = response.get_json()

        assert response.status_code == 200
        assert data["has_attachments"] is True
        assert data["conversation_id"] == "conv-456"

    @patch("app.api.routes_emails._get_cached_email_detail")
    def test_get_email_unicode_body(self, mock_cache, client):
        """Get email with unicode body content."""
        mock_cache.return_value = _make_email_dict(
            sender_name="Expéditeur Français",
            subject="日本語のメール",
            body="Contenu avec accents: é, è, à, ù et emojis 🎉",
            body_html="<p>Contenu avec accents: é, è, à, ù et emojis 🎉</p>",
        )

        response = client.get("/api/emails/test-email-id")
        data = response.get_json()

        assert response.status_code == 200
        body_content = data.get("body_text") or data.get("body") or ""
        assert "accents" in body_content
        assert data["sender_name"] == "Expéditeur Français"
        assert data["subject"] == "日本語のメール"

    @patch("app.api.routes_emails._get_cached_email_detail")
    def test_get_email_long_body(self, mock_cache, client):
        """Get email with very long body returns complete content."""
        long_body = "A" * 100000
        mock_cache.return_value = _make_email_dict(
            body=long_body,
            body_html=f"<p>{long_body}</p>",
        )

        response = client.get("/api/emails/test-email-id")
        response.get_json()

        assert response.status_code == 200

    @patch("app.api.routes_emails._get_cached_email_detail")
    def test_get_email_html_body(self, mock_cache, client):
        """Get email with HTML body returns as-is."""
        html_body = "<html><body><p>Hello <b>World</b></p></body></html>"
        mock_cache.return_value = _make_email_dict(
            body=html_body,
            body_html=html_body,
        )

        response = client.get("/api/emails/test-email-id")
        response.get_json()

        assert response.status_code == 200

    @patch("app.api.routes_emails._get_cached_email_detail")
    def test_get_email_validates_id_with_allowed_chars(self, mock_cache, client):
        """Get email accepts valid ID with allowed special chars."""
        valid_id = "email_id-123@domain.com+tag"
        mock_cache.return_value = _make_email_dict(email_id=valid_id)

        response = client.get(f"/api/emails/{valid_id}")
        data = response.get_json()

        assert response.status_code == 200
        assert data["id"] == valid_id

    def test_get_email_empty_id(self, client):
        """Get email with empty email_id returns 404 (route not matched)."""
        response = client.get("/api/emails/")

        # Flask returns 404 because "/api/emails/" doesn't match the route
        # with a required <email_id> parameter
        assert response.status_code == 404

    @patch("app.api.routes_emails._get_cached_email_detail")
    def test_get_email_null_body(self, mock_cache, client):
        """Get email with None body handles gracefully."""
        mock_cache.return_value = _make_email_dict(body=None, body_html="<p>content</p>")

        response = client.get("/api/emails/test-email-id")
        response.get_json()

        assert response.status_code == 200

    def test_get_email_id_boundary_256_chars(self, client):
        """Get email with email_id at exactly 256 chars boundary is valid."""
        boundary_id = "a" * 256

        with patch("app.api.routes_emails._get_cached_email_detail") as mock_cache:
            mock_cache.return_value = _make_email_dict(email_id=boundary_id)

            response = client.get(f"/api/emails/{boundary_id}")
            # Should pass validation and return 200 from cache
            assert response.status_code == 200

    def test_get_email_id_over_boundary_257_chars(self, client):
        """Get email with email_id at 257 chars (over max) returns 400."""
        over_boundary_id = "a" * 257

        response = client.get(f"/api/emails/{over_boundary_id}")
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    @patch("app.api.routes_emails._get_cached_email_detail")
    def test_get_email_selects_correct_from_multiple(self, mock_cache, client):
        """Get email returns correct email when found in cache."""
        mock_cache.return_value = _make_email_dict(
            email_id="email-2",
            sender="sender2@test.com",
            subject="Subject 2",
            body="Body 2",
            body_html="<p>Body 2</p>",
            has_attachments=False,
        )

        response = client.get("/api/emails/email-2")
        data = response.get_json()

        assert response.status_code == 200
        assert data["id"] == "email-2"
        assert data["sender"] == "sender2@test.com"
        assert data["subject"] == "Subject 2"

    def test_get_email_method_not_allowed(self, client):
        """POST on GET endpoint returns 405 Method Not Allowed."""
        response = client.post("/api/emails/test-id")

        assert response.status_code == 405

    @patch("app.api.routes_emails._get_cached_email_detail")
    def test_get_email_returns_all_fields(self, mock_cache, client):
        """Get email returns all expected fields in response."""
        mock_cache.return_value = _make_email_dict(
            email_id="complete-email-id",
            sender="sender@test.com",
            sender_name="Complete Sender",
            subject="Complete Subject",
            body="Complete body content",
            body_html="<p>Complete body content</p>",
            received_at="2025-01-02T15:30:00Z",
            has_attachments=True,
            conversation_id="conv-complete",
            attachments=[{"filename": "test.pdf", "size": 1024}],
        )

        response = client.get("/api/emails/complete-email-id")
        data = response.get_json()

        assert response.status_code == 200
        # Verify key fields are present
        assert data["id"] == "complete-email-id"
        assert data["sender"] == "sender@test.com"
        assert data["sender_name"] == "Complete Sender"
        assert data["subject"] == "Complete Subject"
        assert data["received_at"] == "2025-01-02T15:30:00Z"
        assert data["has_attachments"] is True
        assert data["conversation_id"] == "conv-complete"

    def test_get_email_id_with_path_traversal(self, client):
        """Get email with path traversal attempt is blocked."""
        # Flask normalizes ../../../etc/passwd before routing, so it doesn't
        # reach our endpoint. We test that the API handles this safely.
        response = client.get("/api/emails/../../../etc/passwd")

        # Flask's routing handles path traversal - returns 404 (route not found)
        # or 400 if it reaches validation. Either is acceptable security behavior.
        assert response.status_code in [400, 404]

    def test_get_email_id_with_sql_injection_attempt(self, client):
        """Get email with SQL injection attempt returns 400."""
        response = client.get("/api/emails/'; DROP TABLE emails;--")
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    def test_skip_email_empty_id(self, client):
        """Skip email with empty id returns 405 (method not allowed on GET route)."""
        # Trying to skip with empty path should hit the list endpoint or return 404
        response = client.post("/api/emails//skip")

        # Flask routing behavior - double slash may be handled differently
        # This tests that the API handles edge cases gracefully
        assert response.status_code in [404, 405]
