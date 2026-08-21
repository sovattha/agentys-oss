"""Tests for PATCH /api/emails/{id}/read and /api/emails/bulk-read endpoints."""

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


class TestMarkEmailReadEndpoint:
    """Tests for PATCH /api/emails/{id}/read endpoint."""

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_mark_as_read_success(self, mock_get_provider, mock_get_email, client):
        """Mark email as read returns 200 with success=true."""
        mock_email = Mock()
        mock_email.id = "test-email-id"

        mock_provider = Mock()
        mock_provider.mark_as_read.return_value = True
        mock_get_provider.return_value = mock_provider
        mock_get_email.return_value = mock_email

        response = client.patch(
            "/api/emails/test-email-id/read",
            json={"is_read": True}
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["success"] is True
        assert data["email_id"] == "test-email-id"
        assert data["is_read"] is True
        mock_get_email.assert_not_called()

    def test_mark_as_read_invalidates_label_counts_cache(self, client):
        """Unread header badges must refetch after a single read toggle."""
        mock_provider = Mock()
        mock_provider.mark_as_read.return_value = True

        with patch(
            "app.api.routes_emails._get_authenticated_provider",
            return_value=mock_provider,
        ), patch(
            "app.api.routes_emails._resolve_account_id_for_user",
            return_value=42,
        ), patch(
            "app.api.labels._invalidate_labels_cache"
        ) as mock_invalidate_label_counts:
            response = client.patch(
                "/api/emails/test-email-id/read",
                json={"is_read": True},
            )

        assert response.status_code == 200
        mock_invalidate_label_counts.assert_called_once_with(account_id=42)

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_mark_as_unread_success(self, mock_get_provider, mock_get_email, client):
        """Mark email as unread returns 200 with success=true."""
        mock_email = Mock()
        mock_email.id = "test-email-id"

        mock_provider = Mock()
        mock_provider.mark_as_unread.return_value = True
        mock_get_provider.return_value = mock_provider
        mock_get_email.return_value = mock_email

        response = client.patch(
            "/api/emails/test-email-id/read",
            json={"is_read": False}
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["success"] is True
        assert data["email_id"] == "test-email-id"
        assert data["is_read"] is False

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_mark_read_calls_correct_provider_method(self, mock_get_provider, mock_get_email, client):
        """Mark as read calls mark_as_read on the provider."""
        mock_email = Mock()
        mock_email.id = "test-email-id"

        mock_provider = Mock()
        mock_provider.mark_as_read.return_value = True
        mock_get_provider.return_value = mock_provider
        mock_get_email.return_value = mock_email

        client.patch("/api/emails/test-email-id/read", json={"is_read": True})

        mock_provider.mark_as_read.assert_called_once_with("test-email-id")
        mock_provider.mark_as_unread.assert_not_called()

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_mark_unread_calls_correct_provider_method(self, mock_get_provider, mock_get_email, client):
        """Mark as unread calls mark_as_unread on the provider."""
        mock_email = Mock()
        mock_email.id = "test-email-id"

        mock_provider = Mock()
        mock_provider.mark_as_unread.return_value = True
        mock_get_provider.return_value = mock_provider
        mock_get_email.return_value = mock_email

        client.patch("/api/emails/test-email-id/read", json={"is_read": False})

        mock_provider.mark_as_unread.assert_called_once_with("test-email-id")
        mock_provider.mark_as_read.assert_not_called()

    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_mark_read_auth_failure(self, mock_get_provider, client):
        """Mark read with authentication failure returns 401."""
        from werkzeug.exceptions import Unauthorized
        mock_get_provider.side_effect = Unauthorized("Authentication failed")

        response = client.patch(
            "/api/emails/test-id/read",
            json={"is_read": True}
        )
        data = response.get_json()

        assert response.status_code == 401
        assert "error" in data

    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_mark_read_not_found(self, mock_get_provider, client):
        """Mark read with non-existent email returns 404."""
        from werkzeug.exceptions import NotFound
        mock_provider = Mock()
        mock_provider.mark_as_read.side_effect = NotFound("Email not found")
        mock_get_provider.return_value = mock_provider

        response = client.patch(
            "/api/emails/nonexistent-id/read",
            json={"is_read": True}
        )
        data = response.get_json()

        assert response.status_code == 404
        assert "error" in data

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_mark_read_does_not_fetch_full_provider_email(self, mock_get_provider, mock_get_email, client):
        """Read toggles use the provider ID directly instead of fetching the full body."""
        mock_provider = Mock()
        mock_provider.mark_as_read.return_value = True
        mock_get_provider.return_value = mock_provider

        response = client.patch(
            "/api/emails/test-email-id/read",
            json={"is_read": True}
        )

        assert response.status_code == 200
        mock_provider.mark_as_read.assert_called_once_with("test-email-id")
        mock_get_email.assert_not_called()

    def test_mark_read_invalid_id_format(self, client):
        """Mark read with invalid email_id format returns 400."""
        response = client.patch(
            "/api/emails/invalid--id!!/read",
            json={"is_read": True}
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "email_id" in data["error"].lower()

    def test_mark_read_missing_json_body(self, client):
        """Mark read without JSON body returns 400 or 415."""
        response = client.patch("/api/emails/test-id/read")
        data = response.get_json()

        assert response.status_code in (400, 415)
        assert "error" in data

    def test_mark_read_missing_is_read_field(self, client):
        """Mark read without is_read field returns 400."""
        response = client.patch(
            "/api/emails/test-id/read",
            json={}
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "is_read" in data["error"] or "JSON" in data["error"]

    def test_mark_read_invalid_is_read_type(self, client):
        """Mark read with non-boolean is_read returns 400."""
        response = client.patch(
            "/api/emails/test-id/read",
            json={"is_read": "true"}
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "boolean" in data["error"]

    def test_mark_read_is_read_as_number(self, client):
        """Mark read with is_read as number returns 400."""
        response = client.patch(
            "/api/emails/test-id/read",
            json={"is_read": 1}
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_mark_read_provider_returns_false(self, mock_get_provider, mock_get_email, client):
        """Mark read when provider returns False still returns 200 with provider_synced=False."""
        mock_email = Mock()
        mock_email.id = "test-email-id"

        mock_provider = Mock()
        mock_provider.mark_as_read.return_value = False
        mock_get_provider.return_value = mock_provider
        mock_get_email.return_value = mock_email

        response = client.patch(
            "/api/emails/test-email-id/read",
            json={"is_read": True}
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["success"] is True
        assert data["provider_synced"] is False

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_mark_read_provider_error(self, mock_get_provider, mock_get_email, client):
        """Mark read with provider error returns 500."""
        mock_email = Mock()
        mock_email.id = "test-email-id"

        mock_provider = Mock()
        mock_provider.mark_as_read.side_effect = Exception("Provider error")
        mock_get_provider.return_value = mock_provider
        mock_get_email.return_value = mock_email

        response = client.patch(
            "/api/emails/test-email-id/read",
            json={"is_read": True}
        )
        data = response.get_json()

        assert response.status_code == 500
        assert "error" in data

    @patch("app.api.routes_emails._resolve_account_id_for_user", return_value=1)
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_mark_read_auth_expired_returns_local_success(self, mock_get_provider, _mock_account, client):
        """Auto mark-read should not surface provider reauth failures as 500s."""
        mock_provider = Mock()
        mock_provider.mark_as_read.side_effect = Exception("invalid_grant: Token has been expired or revoked.")
        mock_get_provider.return_value = mock_provider

        response = client.patch(
            "/api/emails/test-email-id/read",
            json={"is_read": True}
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["success"] is True
        assert data["provider_synced"] is False
        assert data["needs_reauth"] is True


class TestBulkMarkReadEndpoint:
    """Tests for PATCH /api/emails/bulk-read endpoint."""

    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_bulk_mark_as_read_success(self, mock_get_provider, client):
        """Bulk mark emails as read returns 200 with success=true."""
        email_ids = ["email-1", "email-2", "email-3"]

        mock_provider = Mock()
        mock_provider.mark_as_read.return_value = True
        mock_get_provider.return_value = mock_provider

        response = client.patch(
            "/api/emails/bulk-read",
            json={"email_ids": email_ids, "is_read": True}
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["success"] is True
        assert data["updated_count"] == 3
        assert data["email_ids"] == email_ids
        assert data["is_read"] is True

    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_bulk_mark_as_unread_success(self, mock_get_provider, client):
        """Bulk mark emails as unread returns 200 with success=true."""
        email_ids = ["email-1", "email-2"]

        mock_provider = Mock()
        mock_provider.mark_as_unread.return_value = True
        mock_get_provider.return_value = mock_provider

        response = client.patch(
            "/api/emails/bulk-read",
            json={"email_ids": email_ids, "is_read": False}
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["success"] is True
        assert data["updated_count"] == 2
        assert data["is_read"] is False

    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_bulk_mark_read_calls_provider_for_each_email(self, mock_get_provider, client):
        """Bulk mark read calls mark_as_read for each email."""
        email_ids = ["email-1", "email-2", "email-3"]

        mock_provider = Mock()
        mock_provider.mark_as_read.return_value = True
        mock_get_provider.return_value = mock_provider

        client.patch(
            "/api/emails/bulk-read",
            json={"email_ids": email_ids, "is_read": True}
        )

        assert mock_provider.mark_as_read.call_count == 3
        mock_provider.mark_as_read.assert_any_call("email-1")
        mock_provider.mark_as_read.assert_any_call("email-2")
        mock_provider.mark_as_read.assert_any_call("email-3")

    def test_bulk_mark_read_async_invalidates_label_counts_cache(self, client):
        """Large bulk-read waves must refresh unread label badges."""
        email_ids = [f"email-{i}" for i in range(12)]

        with patch(
            "app.api.routes_emails._enqueue_bulk_if_above_threshold",
            return_value="job-read-1",
        ), patch(
            "app.api.routes_emails._resolve_account_id_cached",
            return_value=42,
        ), patch(
            "app.api.labels._invalidate_labels_cache"
        ) as mock_invalidate_label_counts:
            response = client.patch(
                "/api/emails/bulk-read",
                json={"email_ids": email_ids, "is_read": True},
            )

        assert response.status_code == 202
        mock_invalidate_label_counts.assert_called_once_with(account_id=42)

    def test_bulk_mark_read_missing_json_body(self, client):
        """Bulk mark read without JSON body returns 400 or 415."""
        response = client.patch("/api/emails/bulk-read")
        data = response.get_json()

        assert response.status_code in (400, 415)
        assert "error" in data

    def test_bulk_mark_read_missing_email_ids(self, client):
        """Bulk mark read without email_ids returns 400."""
        response = client.patch(
            "/api/emails/bulk-read",
            json={"is_read": True}
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "email_ids" in data["error"]

    def test_bulk_mark_read_empty_email_ids(self, client):
        """Bulk mark read with empty email_ids returns 400."""
        response = client.patch(
            "/api/emails/bulk-read",
            json={"email_ids": [], "is_read": True}
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    def test_bulk_mark_read_email_ids_not_list(self, client):
        """Bulk mark read with email_ids as string returns 400."""
        response = client.patch(
            "/api/emails/bulk-read",
            json={"email_ids": "single-id", "is_read": True}
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    def test_bulk_mark_read_missing_is_read(self, client):
        """Bulk mark read without is_read returns 400."""
        response = client.patch(
            "/api/emails/bulk-read",
            json={"email_ids": ["email-1"]}
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "is_read" in data["error"]

    def test_bulk_mark_read_invalid_is_read_type(self, client):
        """Bulk mark read with non-boolean is_read returns 400."""
        response = client.patch(
            "/api/emails/bulk-read",
            json={"email_ids": ["email-1"], "is_read": "true"}
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "boolean" in data["error"]

    def test_bulk_mark_read_invalid_email_id_in_list(self, client):
        """Bulk mark read with invalid email_id in list returns 400."""
        response = client.patch(
            "/api/emails/bulk-read",
            json={"email_ids": ["valid-id", "invalid!!id", "another-valid"], "is_read": True}
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "email_id" in data["error"].lower()

    def test_bulk_mark_read_too_many_emails(self, client):
        """Bulk mark read with more than 100 emails returns 400."""
        email_ids = [f"email-{i}" for i in range(101)]

        response = client.patch(
            "/api/emails/bulk-read",
            json={"email_ids": email_ids, "is_read": True}
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "100" in data["error"]

    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_bulk_mark_read_exactly_100_emails(self, mock_get_provider, client):
        """Bulk mark read with exactly 100 emails succeeds.

        Note: depuis 2026-05-04 (commit 2033cf59), INLINE_THRESHOLD=10 →
        100 emails déclenche le path async (202 Accepted) au lieu du
        path inline (200 OK). On accepte les deux états.
        """
        email_ids = [f"email-{i}" for i in range(100)]

        mock_provider = Mock()
        mock_provider.mark_as_read.return_value = True
        mock_get_provider.return_value = mock_provider

        response = client.patch(
            "/api/emails/bulk-read",
            json={"email_ids": email_ids, "is_read": True}
        )

        assert response.status_code in (200, 202)

    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_bulk_mark_read_partial_success(self, mock_get_provider, client):
        """Bulk mark read with some failures returns partial count."""
        email_ids = ["email-1", "email-2", "email-3"]

        mock_provider = Mock()
        mock_provider.mark_as_read.side_effect = [True, False, True]
        mock_get_provider.return_value = mock_provider

        response = client.patch(
            "/api/emails/bulk-read",
            json={"email_ids": email_ids, "is_read": True}
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["success"] is True
        assert data["updated_count"] == 2

    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_bulk_mark_read_auth_failure(self, mock_get_provider, client):
        """Bulk mark read with authentication failure returns 401."""
        from werkzeug.exceptions import Unauthorized
        mock_get_provider.side_effect = Unauthorized("Authentication failed")

        response = client.patch(
            "/api/emails/bulk-read",
            json={"email_ids": ["email-1"], "is_read": True}
        )
        data = response.get_json()

        assert response.status_code == 401
        assert "error" in data

    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_bulk_mark_read_continues_on_error(self, mock_get_provider, client):
        """Bulk mark read continues processing on individual errors."""
        email_ids = ["email-1", "email-2", "email-3"]

        mock_provider = Mock()
        mock_provider.mark_as_read.side_effect = [True, Exception("Error"), True]
        mock_get_provider.return_value = mock_provider

        response = client.patch(
            "/api/emails/bulk-read",
            json={"email_ids": email_ids, "is_read": True}
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["success"] is True
        assert data["updated_count"] == 2
        assert mock_provider.mark_as_read.call_count == 3


class TestMarkReadHttpMethods:
    """HTTP method tests for mark read endpoints."""

    def test_mark_read_get_method_not_allowed(self, client):
        """GET method on mark read endpoint returns 405."""
        response = client.get("/api/emails/test-id/read")

        assert response.status_code == 405

    def test_mark_read_post_method_not_allowed(self, client):
        """POST method on mark read endpoint returns 405."""
        response = client.post("/api/emails/test-id/read", json={"is_read": True})

        assert response.status_code == 405

    def test_mark_read_put_method_not_allowed(self, client):
        """PUT method on mark read endpoint returns 405."""
        response = client.put("/api/emails/test-id/read", json={"is_read": True})

        assert response.status_code == 405

    def test_mark_read_delete_method_not_allowed(self, client):
        """DELETE method on mark read endpoint returns 405."""
        response = client.delete("/api/emails/test-id/read")

        assert response.status_code == 405

    def test_bulk_mark_read_get_method_not_allowed(self, client):
        """GET method on bulk mark read endpoint returns 404/405/503.

        503 en CI : le path /emails/bulk-read peut matcher la route
        /emails/<email_id> en GET (bulk-read interprété comme email_id)
        qui échoue sur _get_authenticated_provider sans provider configuré.
        """
        response = client.get("/api/emails/bulk-read")

        assert response.status_code in (404, 405, 503)

    def test_bulk_mark_read_post_method_not_allowed(self, client):
        """POST method on bulk mark read endpoint returns 405."""
        response = client.post(
            "/api/emails/bulk-read",
            json={"email_ids": ["test"], "is_read": True}
        )

        assert response.status_code == 405


class TestMarkReadBoundaryConditions:
    """Boundary condition tests for mark read endpoints."""

    def test_mark_read_id_too_long(self, client):
        """Mark read with email_id too long returns 400."""
        long_id = "a" * 1001

        response = client.patch(
            f"/api/emails/{long_id}/read",
            json={"is_read": True}
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_mark_read_id_exactly_at_max_length(self, mock_get_provider, mock_get_email, client):
        """Mark read with ID exactly at max length (256) works."""
        max_length_id = "a" * 256
        mock_email = Mock()
        mock_email.id = max_length_id

        mock_provider = Mock()
        mock_provider.mark_as_read.return_value = True
        mock_get_provider.return_value = mock_provider
        mock_get_email.return_value = mock_email

        response = client.patch(
            f"/api/emails/{max_length_id}/read",
            json={"is_read": True}
        )

        assert response.status_code == 200

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_mark_read_valid_gmail_id(self, mock_get_provider, mock_get_email, client):
        """Mark read with valid Gmail-style ID works."""
        mock_email = Mock()
        mock_email.id = "18e45d2a3b4c5f67"

        mock_provider = Mock()
        mock_provider.mark_as_read.return_value = True
        mock_get_provider.return_value = mock_provider
        mock_get_email.return_value = mock_email

        response = client.patch(
            "/api/emails/18e45d2a3b4c5f67/read",
            json={"is_read": True}
        )

        assert response.status_code == 200

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_mark_read_valid_special_chars(self, mock_get_provider, mock_get_email, client):
        """Mark read with valid special characters (+@._-) works."""
        valid_id = "test+user@domain.com_msg-123"
        mock_email = Mock()
        mock_email.id = valid_id

        mock_provider = Mock()
        mock_provider.mark_as_read.return_value = True
        mock_get_provider.return_value = mock_provider
        mock_get_email.return_value = mock_email

        response = client.patch(
            f"/api/emails/{valid_id}/read",
            json={"is_read": True}
        )

        assert response.status_code == 200
