# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Tests for draft editing endpoints in app/api/routes_drafts.py.

Coverage targets:
- edit_draft_content endpoint
- refine_draft_content endpoint

Copyright (C) 2025 Agentys - All Rights Reserved.
"""

from unittest.mock import Mock, patch

import pytest


@pytest.fixture(autouse=True)
def _resolve_account_id(monkeypatch):
    """Force _resolve_account_id_for_user à retourner 1 (isolation multi-compte)."""
    monkeypatch.setattr(
        "app.api.routes_helpers._resolve_account_id_for_user",
        lambda: 1,
    )
    yield


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
# HELPER FIXTURES
# ============================================================================


def _create_mock_draft_record(
    draft_id: str = "draft-123",
    gmail_draft_id: str = "gmail-456",
    draft_v1: str = "V1 content",
    draft_final: str = "Final content",
    email_subject: str = "Test Subject",
    status: str = "V1",
):
    """Create a mock draft record object."""
    mock = Mock()
    mock.id = draft_id
    mock.draft_id = gmail_draft_id
    mock.draft_v1 = draft_v1
    mock.draft_final = draft_final
    mock.email_subject = email_subject
    mock.status = status
    return mock


def _make_container_mock_for_refine(draft_record, refine_use_case):
    """Create a container mock that routes through draft_history (not pending_draft_store).

    The refine endpoint checks pending_draft_store first, then falls back to
    draft_history.  These tests exercise the draft_history path, so we make
    pending_draft_store.get_by_id() return None.
    """
    mock_draft_history = Mock()
    mock_draft_history.get_by_id.return_value = draft_record
    mock_draft_history.get_by_id_for_account.return_value = draft_record

    mock_pending_store = Mock()
    mock_pending_store.get_by_id.return_value = None  # force draft_history path

    mock_container = Mock()
    mock_container.get_draft_history.return_value = mock_draft_history
    mock_container.get_pending_draft_store.return_value = mock_pending_store
    mock_container.get_refine_use_case.return_value = refine_use_case

    return mock_container, mock_draft_history


# ============================================================================
# TEST edit_draft_content ENDPOINT
# ============================================================================


class TestEditDraftContentEndpoint:
    """Tests for PATCH /api/drafts/{draft_id}/edit endpoint."""

    @patch("app.api.routes_helpers._get_container")
    def test_edit_draft_invalid_id_format(self, mock_get_container, client):
        """Should reject invalid draft ID format (returns 404 since Flask doesn't match)."""
        # Note: Flask URL routing returns 404 for invalid URL patterns
        response = client.patch(
            "/api/drafts/<script>alert(1)</script>/edit",
            json={"body": "New content"},
        )

        # Flask returns 404 for URL with special chars that don't match route
        assert response.status_code == 404

    def test_edit_draft_no_json_body(self, client):
        """Should require JSON body."""
        response = client.patch("/api/drafts/valid-draft-id/edit")

        assert response.status_code in (400, 415)

    def test_edit_draft_empty_payload(self, client):
        """Should require JSON body (empty dict fails initial validation)."""
        response = client.patch(
            "/api/drafts/valid-draft-id/edit",
            json={},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        # Empty JSON body triggers JSON validation error
        assert "JSON body required" in data["error"] or "At least one of" in data["error"]

    @patch("app.api.routes_helpers._get_container")
    def test_edit_draft_subject_too_long(self, mock_get_container, client):
        """Should reject subject exceeding max length."""
        response = client.patch(
            "/api/drafts/valid-draft-id/edit",
            json={"subject": "x" * 1001},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "Subject" in data["error"] and "maximum" in data["error"]

    @patch("app.api.routes_helpers._get_container")
    def test_edit_draft_body_too_long(self, mock_get_container, client):
        """Should reject body exceeding max length."""
        response = client.patch(
            "/api/drafts/valid-draft-id/edit",
            json={"body": "x" * 100001},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "Body" in data["error"] and "maximum" in data["error"]

    @patch("app.api.routes_helpers._get_container")
    def test_edit_draft_not_found(self, mock_get_container, client):
        """Should return 404 when draft not found."""
        mock_draft_history = Mock()
        mock_draft_history.get_by_id.return_value = None
        mock_draft_history.get_by_id_for_account.return_value = None

        mock_container = Mock()
        mock_container.get_draft_history.return_value = mock_draft_history
        mock_get_container.return_value = mock_container

        response = client.patch(
            "/api/drafts/nonexistent-id/edit",
            json={"body": "New content"},
        )
        data = response.get_json()

        assert response.status_code == 404
        assert "error" in data
        assert "not found" in data["error"].lower()

    @patch("app.api.routes_helpers._get_container")
    def test_edit_draft_no_gmail_draft_id(self, mock_get_container, client):
        """Should return 400 when no provider draft ID."""
        mock_draft = _create_mock_draft_record(gmail_draft_id=None)
        mock_draft_history = Mock()
        mock_draft_history.get_by_id.return_value = mock_draft
        mock_draft_history.get_by_id_for_account.return_value = mock_draft

        mock_container = Mock()
        mock_container.get_draft_history.return_value = mock_draft_history
        mock_get_container.return_value = mock_container

        response = client.patch(
            "/api/drafts/draft-123/edit",
            json={"body": "New content"},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "No provider draft ID" in data["error"]

    @patch("app.api.routes_drafts._get_authenticated_provider")
    @patch("app.api.routes_helpers._get_container")
    def test_edit_draft_success_body_only(self, mock_get_container, mock_get_provider, client):
        """Should update draft body successfully."""
        mock_draft = _create_mock_draft_record()
        mock_draft_history = Mock()
        mock_draft_history.get_by_id.return_value = mock_draft
        mock_draft_history.get_by_id_for_account.return_value = mock_draft

        mock_provider = Mock()
        mock_provider.update_draft.return_value = True
        mock_get_provider.return_value = mock_provider

        mock_container = Mock()
        mock_container.get_draft_history.return_value = mock_draft_history
        mock_get_container.return_value = mock_container

        response = client.patch(
            "/api/drafts/draft-123/edit",
            json={"body": "Updated body content"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["success"] is True
        assert data["draft_id"] == "draft-123"
        assert data["provider_draft_id"] == "gmail-456"

    @patch("app.api.routes_drafts._get_authenticated_provider")
    @patch("app.api.routes_helpers._get_container")
    def test_edit_draft_success_subject_only(self, mock_get_container, mock_get_provider, client):
        """Should update draft subject successfully."""
        mock_draft = _create_mock_draft_record()
        mock_draft_history = Mock()
        mock_draft_history.get_by_id.return_value = mock_draft
        mock_draft_history.get_by_id_for_account.return_value = mock_draft

        mock_provider = Mock()
        mock_provider.update_draft.return_value = True
        mock_get_provider.return_value = mock_provider

        mock_container = Mock()
        mock_container.get_draft_history.return_value = mock_draft_history
        mock_get_container.return_value = mock_container

        response = client.patch(
            "/api/drafts/draft-123/edit",
            json={"subject": "Updated subject"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["success"] is True

    @patch("app.api.routes_drafts._get_authenticated_provider")
    @patch("app.api.routes_helpers._get_container")
    def test_edit_draft_success_both_subject_and_body(self, mock_get_container, mock_get_provider, client):
        """Should update both subject and body."""
        mock_draft = _create_mock_draft_record()
        mock_draft_history = Mock()
        mock_draft_history.get_by_id.return_value = mock_draft
        mock_draft_history.get_by_id_for_account.return_value = mock_draft

        mock_provider = Mock()
        mock_provider.update_draft.return_value = True
        mock_get_provider.return_value = mock_provider

        mock_container = Mock()
        mock_container.get_draft_history.return_value = mock_draft_history
        mock_get_container.return_value = mock_container

        response = client.patch(
            "/api/drafts/draft-123/edit",
            json={
                "subject": "New Subject",
                "body": "New Body",
            },
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["success"] is True

        mock_provider.update_draft.assert_called_once_with(
            draft_id="gmail-456",
            subject="New Subject",
            body="New Body",
        )

    @patch("app.api.routes_drafts._get_authenticated_provider")
    @patch("app.api.routes_helpers._get_container")
    def test_edit_draft_gmail_update_fails(self, mock_get_container, mock_get_provider, client):
        """Should return 500 when Gmail update fails."""
        mock_draft = _create_mock_draft_record()
        mock_draft_history = Mock()
        mock_draft_history.get_by_id.return_value = mock_draft
        mock_draft_history.get_by_id_for_account.return_value = mock_draft

        mock_provider = Mock()
        mock_provider.update_draft.return_value = False
        mock_get_provider.return_value = mock_provider

        mock_container = Mock()
        mock_container.get_draft_history.return_value = mock_draft_history
        mock_get_container.return_value = mock_container

        response = client.patch(
            "/api/drafts/draft-123/edit",
            json={"body": "Updated content"},
        )
        data = response.get_json()

        assert response.status_code == 500
        assert "error" in data
        assert "Failed to update" in data["error"]

    @patch("app.api.routes_drafts._get_authenticated_provider")
    @patch("app.api.routes_helpers._get_container")
    def test_edit_draft_updates_local_history(self, mock_get_container, mock_get_provider, client):
        """Should update local draft history when body changes."""
        mock_draft = _create_mock_draft_record()
        mock_draft_history = Mock()
        mock_draft_history.get_by_id.return_value = mock_draft
        mock_draft_history.get_by_id_for_account.return_value = mock_draft

        mock_provider = Mock()
        mock_provider.update_draft.return_value = True
        mock_get_provider.return_value = mock_provider

        mock_container = Mock()
        mock_container.get_draft_history.return_value = mock_draft_history
        mock_get_container.return_value = mock_container

        response = client.patch(
            "/api/drafts/draft-123/edit",
            json={"body": "Updated body content"},
        )

        assert response.status_code == 200
        assert mock_draft.draft_final == "Updated body content"
        mock_draft_history.add.assert_called_once_with(mock_draft)

    @patch("app.api.routes_drafts._get_authenticated_provider")
    @patch("app.api.routes_helpers._get_container")
    def test_edit_draft_exception_handling(self, mock_get_container, mock_get_provider, client):
        """Should handle exceptions gracefully."""
        mock_draft = _create_mock_draft_record()
        mock_draft_history = Mock()
        mock_draft_history.get_by_id.return_value = mock_draft
        mock_draft_history.get_by_id_for_account.return_value = mock_draft

        mock_provider = Mock()
        mock_provider.update_draft.side_effect = Exception("Gmail API error")
        mock_get_provider.return_value = mock_provider

        mock_container = Mock()
        mock_container.get_draft_history.return_value = mock_draft_history
        mock_get_container.return_value = mock_container

        response = client.patch(
            "/api/drafts/draft-123/edit",
            json={"body": "Updated content"},
        )
        data = response.get_json()

        assert response.status_code == 500
        assert "error" in data
        assert "internal error" in data["error"].lower()


# ============================================================================
# TEST refine_draft_content ENDPOINT
# ============================================================================


class MockRefineResult:
    """Mock class for refine use case result."""

    def __init__(
        self,
        draft_v1_content: str = "V1 content",
        critique_is_valid: bool = True,
        critique_reason: str = None,
        critique_raw: str = "Good draft",
        draft_final_content: str = "Final refined content",
        was_corrected: bool = False,
        status: str = "V1",
    ):
        self.draft_v1 = Mock()
        self.draft_v1.content = draft_v1_content

        self.critique = Mock()
        self.critique.is_valid = critique_is_valid
        self.critique.reason = critique_reason
        self.critique.raw_response = critique_raw

        self.draft_final = Mock()
        self.draft_final.content = Mock()
        self.draft_final.content.strip.return_value = draft_final_content

        self.was_corrected = was_corrected

        self.status = Mock()
        self.status.value = status


class TestRefineDraftContentEndpoint:
    """Tests for POST /api/drafts/{draft_id}/refine endpoint."""

    def test_refine_draft_invalid_id_format(self, client):
        """Should reject invalid draft ID format (Flask returns 404)."""
        # Flask URL routing returns 404 for paths with special characters
        response = client.post(
            "/api/drafts/<script>alert(1)</script>/refine",
            json={"instruction": "Make it shorter"},
        )

        # Flask returns 404 for URL with special chars that don't match route
        assert response.status_code == 404

    def test_refine_draft_no_json_body(self, client):
        """Should require JSON body."""
        response = client.post("/api/drafts/valid-draft-id/refine")

        assert response.status_code in (400, 415)

    def test_refine_draft_missing_instruction(self, client):
        """Should require JSON body (empty dict fails validation)."""
        response = client.post(
            "/api/drafts/valid-draft-id/refine",
            json={},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        # Empty body triggers JSON required error or instruction error
        assert "JSON body required" in data["error"] or "instruction" in data["error"].lower()

    def test_refine_draft_empty_instruction(self, client):
        """Should reject empty instruction."""
        response = client.post(
            "/api/drafts/valid-draft-id/refine",
            json={"instruction": "   "},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "empty" in data["error"].lower()

    def test_refine_draft_instruction_not_string(self, client):
        """Should require instruction to be a string."""
        response = client.post(
            "/api/drafts/valid-draft-id/refine",
            json={"instruction": 123},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "string" in data["error"].lower()

    def test_refine_draft_instruction_too_long(self, client):
        """Should reject instruction exceeding max length."""
        response = client.post(
            "/api/drafts/valid-draft-id/refine",
            json={"instruction": "x" * 1001},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "maximum" in data["error"].lower()

    @patch("app.api.routes_helpers._get_container")
    def test_refine_draft_not_found(self, mock_get_container, client):
        """Should return 404 when draft not found in either store."""
        mock_draft_history = Mock()
        mock_draft_history.get_by_id.return_value = None
        mock_draft_history.get_by_id_for_account.return_value = None

        mock_pending_store = Mock()
        mock_pending_store.get_by_id.return_value = None

        mock_container = Mock()
        mock_container.get_draft_history.return_value = mock_draft_history
        mock_container.get_pending_draft_store.return_value = mock_pending_store
        mock_get_container.return_value = mock_container

        response = client.post(
            "/api/drafts/nonexistent-id/refine",
            json={"instruction": "Make it shorter"},
        )
        data = response.get_json()

        assert response.status_code == 404
        assert "error" in data
        assert "not found" in data["error"].lower()

    @patch("app.api.routes_drafts.LegacyModuleLoader.email_provider")
    @patch("app.api.routes_helpers._get_container")
    def test_refine_draft_success(self, mock_get_container, mock_email_provider, client):
        """Should refine draft successfully."""
        mock_draft = _create_mock_draft_record()
        mock_refine_result = MockRefineResult(draft_final_content="Refined content")
        mock_refine_use_case = Mock()
        mock_refine_use_case.execute.return_value = mock_refine_result

        mock_container, _ = _make_container_mock_for_refine(mock_draft, mock_refine_use_case)
        mock_get_container.return_value = mock_container

        mock_provider = Mock()
        mock_provider.authenticate.return_value = True
        mock_provider.update_draft.return_value = True
        mock_email_provider.return_value = mock_provider

        response = client.post(
            "/api/drafts/draft-123/refine",
            json={"instruction": "Make it shorter"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["success"] is True
        assert data["draft_id"] == "draft-123"
        assert data["refined_body"] == "Refined content"

    @patch("app.api.routes_drafts.LegacyModuleLoader.email_provider")
    @patch("app.api.routes_helpers._get_container")
    def test_refine_draft_returns_pipeline_details(
        self, mock_get_container, mock_email_provider, client
    ):
        """Should return pipeline details in response."""
        mock_draft = _create_mock_draft_record()
        mock_refine_result = MockRefineResult(
            draft_v1_content="V1 draft",
            critique_is_valid=True,
            critique_reason="Good tone",
            was_corrected=True,
            draft_final_content="Final refined",
        )
        mock_refine_use_case = Mock()
        mock_refine_use_case.execute.return_value = mock_refine_result

        mock_container, _ = _make_container_mock_for_refine(mock_draft, mock_refine_use_case)
        mock_get_container.return_value = mock_container

        mock_provider = Mock()
        mock_provider.authenticate.return_value = True
        mock_provider.update_draft.return_value = True
        mock_email_provider.return_value = mock_provider

        response = client.post(
            "/api/drafts/draft-123/refine",
            json={"instruction": "Be more formal"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert "pipeline_details" in data
        assert data["pipeline_details"]["draft_v1"] == "V1 draft"
        assert data["pipeline_details"]["critique"]["is_valid"] is True
        assert data["pipeline_details"]["was_corrected"] is True

    @patch("app.api.routes_helpers._get_container")
    def test_refine_draft_empty_result(self, mock_get_container, client):
        """Should return 500 when refinement produces empty result."""
        mock_draft = _create_mock_draft_record()
        mock_refine_result = MockRefineResult(draft_final_content="")
        mock_refine_use_case = Mock()
        mock_refine_use_case.execute.return_value = mock_refine_result

        mock_container, _ = _make_container_mock_for_refine(mock_draft, mock_refine_use_case)
        mock_get_container.return_value = mock_container

        response = client.post(
            "/api/drafts/draft-123/refine",
            json={"instruction": "Make it shorter"},
        )
        data = response.get_json()

        assert response.status_code == 500
        assert "error" in data
        assert "Failed to generate" in data["error"]

    @patch("app.api.routes_drafts.LegacyModuleLoader.email_provider")
    @patch("app.api.routes_helpers._get_container")
    def test_refine_draft_updates_local_history(
        self, mock_get_container, mock_email_provider, client
    ):
        """Should update local draft history with refine results."""
        mock_draft = _create_mock_draft_record()
        mock_refine_result = MockRefineResult(
            draft_v1_content="New V1",
            critique_raw="Looks good",
            draft_final_content="New Final",
            status="V2",
        )
        mock_refine_use_case = Mock()
        mock_refine_use_case.execute.return_value = mock_refine_result

        mock_container, mock_draft_history = _make_container_mock_for_refine(
            mock_draft, mock_refine_use_case
        )
        mock_get_container.return_value = mock_container

        mock_provider = Mock()
        mock_provider.authenticate.return_value = True
        mock_provider.update_draft.return_value = True
        mock_email_provider.return_value = mock_provider

        response = client.post(
            "/api/drafts/draft-123/refine",
            json={"instruction": "Be more formal"},
        )

        assert response.status_code == 200
        assert mock_draft.draft_v1 == "New V1"
        assert mock_draft.critique == "Looks good"
        assert mock_draft.draft_final == "New Final"
        assert mock_draft.status == "V2"
        mock_draft_history.add.assert_called_once_with(mock_draft)

    @patch("app.api.routes_drafts.LegacyModuleLoader.email_provider")
    @patch("app.api.routes_helpers._get_container")
    def test_refine_draft_without_gmail_draft_id(
        self, mock_get_container, mock_email_provider, client
    ):
        """Should still work without Gmail draft ID."""
        mock_draft = _create_mock_draft_record(gmail_draft_id=None)
        mock_refine_result = MockRefineResult()
        mock_refine_use_case = Mock()
        mock_refine_use_case.execute.return_value = mock_refine_result

        mock_container, _ = _make_container_mock_for_refine(mock_draft, mock_refine_use_case)
        mock_get_container.return_value = mock_container

        response = client.post(
            "/api/drafts/draft-123/refine",
            json={"instruction": "Be more formal"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["success"] is True
        mock_email_provider.assert_not_called()

    @patch("app.api.routes_drafts.LegacyModuleLoader.email_provider")
    @patch("app.api.routes_helpers._get_container")
    def test_refine_draft_gmail_update_failure_logs_warning(
        self, mock_get_container, mock_email_provider, client
    ):
        """Should continue even if Gmail update fails."""
        mock_draft = _create_mock_draft_record()
        mock_refine_result = MockRefineResult()
        mock_refine_use_case = Mock()
        mock_refine_use_case.execute.return_value = mock_refine_result

        mock_container, _ = _make_container_mock_for_refine(mock_draft, mock_refine_use_case)
        mock_get_container.return_value = mock_container

        mock_provider = Mock()
        mock_provider.authenticate.return_value = True
        mock_provider.update_draft.return_value = False  # Update fails
        mock_email_provider.return_value = mock_provider

        response = client.post(
            "/api/drafts/draft-123/refine",
            json={"instruction": "Be more formal"},
        )
        data = response.get_json()

        # Should still succeed, Gmail update failure is logged as warning
        assert response.status_code == 200
        assert data["success"] is True

    @patch("app.api.routes_helpers._get_container")
    def test_refine_draft_exception_handling(self, mock_get_container, client):
        """Should handle exceptions gracefully."""
        mock_draft = _create_mock_draft_record()
        mock_refine_use_case = Mock()
        mock_refine_use_case.execute.side_effect = Exception("LLM error")

        mock_container, _ = _make_container_mock_for_refine(mock_draft, mock_refine_use_case)
        mock_get_container.return_value = mock_container

        response = client.post(
            "/api/drafts/draft-123/refine",
            json={"instruction": "Make it shorter"},
        )
        data = response.get_json()

        assert response.status_code == 500
        assert "error" in data
        assert "internal error" in data["error"].lower()

    @patch("app.api.routes_helpers._get_container")
    def test_refine_draft_passes_instruction_to_use_case(self, mock_get_container, client):
        """Should pass instruction to refine use case."""
        mock_draft = _create_mock_draft_record(draft_final="Current body")
        mock_refine_result = MockRefineResult()
        mock_refine_use_case = Mock()
        mock_refine_use_case.execute.return_value = mock_refine_result

        mock_container, _ = _make_container_mock_for_refine(mock_draft, mock_refine_use_case)
        mock_get_container.return_value = mock_container

        client.post(
            "/api/drafts/draft-123/refine",
            json={"instruction": "Be more casual"},
        )

        mock_refine_use_case.execute.assert_called_once_with(
            current_draft="Current body",
            instruction="Be more casual",
            email=None,
        )
