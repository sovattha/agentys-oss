"""Audit regression: PATCH /api/emails/{id}/read must surface provider_synced.

Contract (documented in update_email_read_status): the top-level "success"
field stays True even when the provider mark_as_read/mark_as_unread call
returns False (idempotent already-read is benign and callers depend on
success:true). The accurate provider outcome is carried in "provider_synced"
so a caller that needs to distinguish a real sync from a no-op/failure can
gate on provider_synced:false. These tests pin that body shape so the field
can never be silently dropped.

Mirrors the fixtures/mocking patterns in tests/test_api_mark_read.py.
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


class TestMarkReadProviderSyncedContract:
    """provider_synced is present and accurate in the mark-read response body."""

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_provider_synced_false_present_when_mark_as_read_false(
        self, mock_get_provider, mock_get_email, client
    ):
        """When provider.mark_as_read returns False, body keeps success:true
        but exposes provider_synced:false so callers can gate on it."""
        mock_provider = Mock()
        mock_provider.mark_as_read.return_value = False
        mock_get_provider.return_value = mock_provider

        response = client.patch(
            "/api/emails/test-email-id/read",
            json={"is_read": True},
        )
        data = response.get_json()

        assert response.status_code == 200
        # Documented contract: success stays True (idempotent already-read).
        assert data["success"] is True
        # The field must be present and accurately False.
        assert "provider_synced" in data
        assert data["provider_synced"] is False
        mock_get_email.assert_not_called()

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_provider_synced_false_present_when_mark_as_unread_false(
        self, mock_get_provider, mock_get_email, client
    ):
        """Same contract on the unread path (mark_as_unread returns False)."""
        mock_provider = Mock()
        mock_provider.mark_as_unread.return_value = False
        mock_get_provider.return_value = mock_provider

        response = client.patch(
            "/api/emails/test-email-id/read",
            json={"is_read": False},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["success"] is True
        assert "provider_synced" in data
        assert data["provider_synced"] is False

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_provider_synced_true_when_mark_as_read_true(
        self, mock_get_provider, mock_get_email, client
    ):
        """A genuine provider sync reports provider_synced:true."""
        mock_provider = Mock()
        mock_provider.mark_as_read.return_value = True
        mock_get_provider.return_value = mock_provider

        response = client.patch(
            "/api/emails/test-email-id/read",
            json={"is_read": True},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["success"] is True
        assert data["provider_synced"] is True
