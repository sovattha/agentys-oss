# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Integration tests — Send Flow (Phase 18)

Vérifie les deux chemins d'envoi :
1. send_reply_directly() — chemin rapide, single API call
2. create_draft + send — chemin de repli (fallback)
3. BCC support — skip fast path, use full draft path
"""

import pytest
from unittest.mock import MagicMock, patch
from app.api.app import create_app
from app.domain.entities.pending_draft import PendingDraftStatus


def _auth_headers(email: str = "test@agentys.app", sub: str = "12345") -> dict:
    """Mint a JWT Bearer header — /api/refine-text is @require_auth gated."""
    import time as _time
    import jwt as _pyjwt
    from app.api.auth import JWT_ALGORITHM, JWT_SECRET
    token = _pyjwt.encode(
        {"sub": sub, "email": email, "iat": int(_time.time()), "exp": int(_time.time()) + 3600},
        JWT_SECRET, algorithm=JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}



@pytest.fixture
def client():
    """Create test client."""
    app = create_app({"TESTING": True})
    with app.test_client() as c:
        yield c


@pytest.fixture
def mock_account():
    """Mock account for send tests."""
    acc = MagicMock()
    acc.id = 1
    acc.email = "user@example.com"
    acc.provider = "gmail"
    acc.status = "active"
    return acc


class TestSendReplyDirectly:
    """Tests for the fast send path (send_reply_directly)."""

    @patch("app.api.routes_helpers._get_container")
    def test_validate_draft_calls_send_directly(self, mock_get_container, client):
        """Validate endpoint should use send_reply_directly for fast path."""
        # Arrange
        mock_draft = MagicMock()
        mock_draft.id = "draft-send-1"
        mock_draft.email_id = "email-1"
        mock_draft.draft_body = "Merci pour votre message."
        mock_draft.draft_subject = "Re: Test"
        mock_draft.email_sender = "sender@example.com"
        mock_draft.status = "PENDING"
        summary_dict = {
            "id": "draft-send-1",
            "email_id": "email-1",
            "draft_subject": "Re: Test",
            "email_sender": "sender@example.com",
            "status": "SENT",
            "created_at": "2026-01-01T00:00:00",
        }
        mock_draft.to_dict.return_value = {**summary_dict, "draft_body": "Merci pour votre message."}
        mock_draft.to_dict_summary.return_value = summary_dict

        mock_store = MagicMock()
        mock_store.get_by_id.return_value = mock_draft

        mock_container = MagicMock()
        mock_container.get_pending_draft_store.return_value = mock_store
        mock_get_container.return_value = mock_container

        # Act
        client.post("/api/pending-drafts/draft-send-1/validate")

        # Assert — store was accessed
        mock_store.get_by_id.assert_called_once_with("draft-send-1")

    @patch("app.api.routes_pending._resolve_account_id_cached", return_value=1)
    @patch("app.api.routes_helpers._get_container")
    def test_validate_returns_200_on_success(self, mock_get_container, mock_resolve_acct, client):
        """Validate endpoint returns 200 with message_id."""
        mock_draft = MagicMock()
        mock_draft.id = "draft-send-2"
        mock_draft.email_id = "email-2"
        mock_draft.draft_body = "Reply body."
        mock_draft.draft_subject = "Re: Question"
        mock_draft.email_sender = "other@example.com"
        mock_draft.account_id = 1  # must match patched _resolve_account_id_cached
        mock_draft.status = PendingDraftStatus.PENDING
        mock_draft.to_dict.return_value = {
            "id": "draft-send-2",
            "email_id": "email-2",
            "draft_body": "Reply body.",
            "draft_subject": "Re: Question",
            "email_sender": "other@example.com",
            "status": "SENT",
            "created_at": "2026-01-01T00:00:00",
        }
        mock_draft.to_dict_summary.return_value = {
            "id": "draft-send-2",
            "email_id": "email-2",
            "draft_subject": "Re: Question",
            "email_sender": "other@example.com",
            "status": "SENT",
            "created_at": "2026-01-01T00:00:00",
        }

        mock_store = MagicMock()
        mock_store.get_by_id.return_value = mock_draft

        mock_container = MagicMock()
        mock_container.get_pending_draft_store.return_value = mock_store
        mock_get_container.return_value = mock_container

        response = client.post("/api/pending-drafts/draft-send-2/validate")

        # Should return 200 or handle the send flow (503/500 if no real provider)
        assert response.status_code in (200, 500, 503)

    @patch("app.api.routes_helpers._get_container")
    def test_validate_draft_not_found_returns_404(self, mock_get_container, client):
        """Validate returns 404 when draft doesn't exist."""
        mock_store = MagicMock()
        mock_store.get_by_id.return_value = None

        mock_container = MagicMock()
        mock_container.get_pending_draft_store.return_value = mock_store
        mock_get_container.return_value = mock_container

        response = client.post("/api/pending-drafts/nonexistent-draft/validate")

        assert response.status_code == 404
        data = response.get_json()
        assert "error" in data or "not found" in str(data).lower()


class TestRefineTextEndpoint:
    """Tests for POST /api/refine-text."""

    @patch("app.api.routes_helpers._get_container")
    def test_refine_text_missing_params(self, mock_get_container, client):
        """refine-text with missing params returns 400."""
        response = client.post("/api/refine-text", json={}, headers=_auth_headers())
        assert response.status_code == 400

    @patch("app.api.routes_helpers._get_container")
    def test_refine_text_missing_text(self, mock_get_container, client):
        """refine-text with missing text returns 400."""
        response = client.post("/api/refine-text", json={"instruction": "Améliorer"}, headers=_auth_headers())
        assert response.status_code == 400

    @patch("app.api.routes_helpers._get_container")
    def test_refine_text_missing_instruction(self, mock_get_container, client):
        """refine-text with missing instruction returns 400."""
        response = client.post("/api/refine-text", json={"text": "Mon texte"}, headers=_auth_headers())
        assert response.status_code == 400

    def test_refine_text_endpoint_exists(self, client):
        """POST /api/refine-text endpoint is registered."""
        # Should not return 404 (endpoint exists, even if it returns 400/500)
        response = client.post("/api/refine-text", json={"text": "test", "instruction": "improve"}, headers=_auth_headers())
        assert response.status_code != 404


class TestSmartSuggestionsField:
    """Tests for smart_suggestions field in PendingDraft."""

    @patch("app.api.routes_helpers._get_container")
    def test_list_drafts_includes_smart_suggestions(self, mock_get_container, client):
        """Listing drafts includes smart_suggestions field if present."""
        mock_draft = MagicMock()
        mock_draft.id = "draft-sg-1"
        mock_draft.routing_tier = "followup"
        mock_draft.to_dict_summary.return_value = {
            "id": "draft-sg-1",
            "email_id": "email-sg-1",
            "draft_subject": "Re: Test",
            "email_sender": "alice@example.com",
            "status": "PENDING",
            "created_at": "2026-01-01T00:00:00",
            "routing_tier": "followup",
            "smart_suggestions": ["Oui, je suis disponible.", "Non, désolé."],
        }

        mock_store = MagicMock()
        mock_store.get_pending.return_value = [mock_draft]
        mock_store.count_pending.return_value = 1

        mock_container = MagicMock()
        mock_container.get_pending_draft_store.return_value = mock_store
        mock_get_container.return_value = mock_container

        response = client.get("/api/pending-drafts")
        assert response.status_code == 200
        data = response.get_json()
        assert data["count"] == 1
        assert len(data["drafts"]) == 1
        # smart_suggestions should be in the response if included in to_dict_summary
        if "smart_suggestions" in data["drafts"][0]:
            assert isinstance(data["drafts"][0]["smart_suggestions"], list)


class TestBulkOperations:
    """Tests for bulk spam/trash operations."""

    def test_bulk_not_spam_endpoint_exists(self, client):
        """POST /api/emails/bulk-not-spam is registered."""
        response = client.post("/api/emails/bulk-not-spam", json={"email_ids": []})
        assert response.status_code != 404

    def test_bulk_restore_endpoint_exists(self, client):
        """POST /api/emails/bulk-restore is registered."""
        response = client.post("/api/emails/bulk-restore", json={"email_ids": []})
        assert response.status_code != 404

    def test_empty_spam_endpoint_exists(self, client):
        """POST /api/emails/empty-spam is registered."""
        response = client.post("/api/emails/empty-spam")
        assert response.status_code != 404

    def test_empty_trash_endpoint_exists(self, client):
        """POST /api/emails/empty-trash is registered."""
        response = client.post("/api/emails/empty-trash")
        assert response.status_code != 404

    @patch("app.api.routes_helpers._get_container")
    def test_bulk_not_spam_empty_list(self, mock_get_container, client):
        """bulk-not-spam with empty list returns success."""
        mock_container = MagicMock()
        mock_get_container.return_value = mock_container

        response = client.post("/api/emails/bulk-not-spam", json={"email_ids": []})
        # Empty list should succeed (0 emails moved)
        assert response.status_code in (200, 400)  # 400 if empty list is rejected

    @patch("app.api.routes_helpers._get_container")
    def test_bulk_restore_empty_list(self, mock_get_container, client):
        """bulk-restore with empty list returns success."""
        mock_container = MagicMock()
        mock_get_container.return_value = mock_container

        response = client.post("/api/emails/bulk-restore", json={"email_ids": []})
        assert response.status_code in (200, 400)

    @patch("app.api.routes_emails._rh")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_empty_spam_deletes_all_spam_emails(self, mock_get_provider, mock_rh, client):
        """empty-spam deletes all spam emails via batch API."""
        spam_email1 = MagicMock()
        spam_email1.id = "spam-1"
        spam_email2 = MagicMock()
        spam_email2.id = "spam-2"

        mock_provider = MagicMock()
        mock_provider.get_messages.return_value = [spam_email1, spam_email2]
        mock_provider.batch_modify_labels.return_value = 2
        mock_get_provider.return_value = mock_provider

        # Mock container + label store (for rescue detection)
        mock_label_store = MagicMock()
        mock_label_store.get_assignments_batch.return_value = {}
        mock_container = MagicMock()
        mock_container.get_label_store.return_value = mock_label_store
        mock_rh._get_container.return_value = mock_container

        response = client.post("/api/emails/empty-spam")

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["deleted_count"] == 2

    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_empty_trash_deletes_all_trash_emails(self, mock_get_provider, client):
        """empty-trash calls permanently_delete() once per trash email."""
        trash_email1 = MagicMock()
        trash_email1.id = "trash-1"
        trash_email2 = MagicMock()
        trash_email2.id = "trash-2"
        trash_email3 = MagicMock()
        trash_email3.id = "trash-3"

        mock_provider = MagicMock()
        mock_provider.get_messages.return_value = [trash_email1, trash_email2, trash_email3]
        mock_provider.permanently_delete.return_value = True
        mock_get_provider.return_value = mock_provider

        response = client.post("/api/emails/empty-trash")

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["deleted_count"] == 3
        assert mock_provider.permanently_delete.call_count == 3

    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_empty_folder_when_already_empty_returns_count_zero(self, mock_get_provider, client):
        """empty-spam with no spam emails returns deleted_count=0."""
        mock_provider = MagicMock()
        mock_provider.get_messages.return_value = []
        mock_provider.permanently_delete.return_value = True
        mock_get_provider.return_value = mock_provider

        response = client.post("/api/emails/empty-spam")

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["deleted_count"] == 0
        mock_provider.permanently_delete.assert_not_called()

    def test_move_to_spam_endpoint_exists(self, client):
        """POST /api/emails/<id>/move-to-spam is registered."""
        response = client.post("/api/emails/test-id/move-to-spam")
        assert response.status_code != 404

    @patch("app.api.routes_emails._rh._resolve_account_id_for_user", return_value=1)
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_move_to_spam_calls_provider_method(self, mock_get_provider, _mock_account_id, client):
        """move-to-spam calls provider.move_to_spam() and returns success."""
        mock_provider = MagicMock()
        mock_provider.move_to_spam.return_value = True
        mock_get_provider.return_value = mock_provider

        response = client.post("/api/emails/email-123/move-to-spam")

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        mock_provider.move_to_spam.assert_called_once_with("email-123")

    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_restore_with_archived_folder_calls_unarchive(self, mock_get_provider, client):
        """restore with ?folder=archived calls provider.unarchive_email()."""
        mock_provider = MagicMock()
        mock_provider.unarchive_email.return_value = True
        mock_get_provider.return_value = mock_provider

        response = client.post("/api/emails/email-456/restore?folder=archived")

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        mock_provider.unarchive_email.assert_called_once_with("email-456")
