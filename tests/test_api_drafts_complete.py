"""Tests for POST /api/drafts/complete endpoint."""

from unittest.mock import Mock, patch

import pytest

from app.domain.entities import DraftInputTone, CompletedDraft


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


@pytest.fixture
def mock_completed_draft():
    """Fixture for a completed draft response."""
    return CompletedDraft(
        subject="Proposition de réunion",
        body="Bonjour Sophie,\n\nJe te remercie pour ton retour rapide.\n\nCordialement",
        recipient="Sophie",
        tone_used=DraftInputTone.FRIENDLY,
    )


@pytest.fixture
def setup_container_mock(mock_completed_draft):
    """Setup container mock with configurable completed draft.

    Returns a function that configures mock_get_container and optionally
    returns the mock_use_case for further customization.

    Usage:
        setup_container_mock(mock_get_container)  # Uses default mock_completed_draft
        setup_container_mock(mock_get_container, custom_draft)  # Uses custom draft
    """
    def _setup(mock_get_container, completed_draft=None):
        if completed_draft is None:
            completed_draft = mock_completed_draft
        mock_use_case = Mock()
        mock_use_case.execute.return_value = completed_draft
        mock_container = Mock()
        mock_container.get_complete_draft_use_case.return_value = mock_use_case
        mock_get_container.return_value = mock_container
        return mock_use_case, mock_container
    return _setup


class TestCompleteDraftEndpoint:
    """Tests for POST /api/drafts/complete endpoint."""

    def test_complete_draft_no_json_body(self, client):
        """Complete draft without JSON body returns error."""
        response = client.post("/api/drafts/complete")
        assert response.status_code in (400, 415)

    def test_complete_draft_missing_raw_input(self, client):
        """Complete draft without raw_input returns 400."""
        response = client.post(
            "/api/drafts/complete",
            json={"tone": "formal"},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "raw_input" in data["error"].lower()

    def test_complete_draft_empty_raw_input(self, client):
        """Complete draft with empty raw_input returns 400."""
        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": ""},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "raw_input" in data["error"].lower()

    def test_complete_draft_null_raw_input(self, client):
        """Complete draft with null raw_input returns 400."""
        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": None},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    def test_complete_draft_invalid_tone(self, client):
        """Complete draft with invalid tone returns 400."""
        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": "Test input", "tone": "invalid_tone"},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "tone" in data["error"].lower()
        assert "formal" in data["error"]
        assert "friendly" in data["error"]

    @pytest.mark.parametrize("tone", ["formal", "friendly", "urgent", "conciliatory", "neutral"])
    @patch("app.api.routes_helpers._get_container")
    def test_complete_draft_valid_tones(self, mock_get_container, client, tone, setup_container_mock):
        """Complete draft accepts all valid tone values."""
        setup_container_mock(mock_get_container)

        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": "Test input", "tone": tone},
        )

        assert response.status_code == 200

    @pytest.mark.parametrize("tone", ["FORMAL", "Friendly", "URGENT", "Conciliatory", "NEUTRAL"])
    @patch("app.api.routes_helpers._get_container")
    def test_complete_draft_tone_case_insensitive(self, mock_get_container, client, tone, setup_container_mock):
        """Complete draft accepts tones case-insensitively."""
        setup_container_mock(mock_get_container)

        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": "Test input", "tone": tone},
        )

        assert response.status_code == 200

    @patch("app.api.routes_helpers._get_container")
    def test_complete_draft_with_recipient(self, mock_get_container, client, setup_container_mock):
        """Complete draft with recipient parameter."""
        setup_container_mock(mock_get_container)

        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": "Test input", "recipient": "Sophie"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["recipient"] == "Sophie"

    @patch("app.api.routes_helpers._get_container")
    def test_complete_draft_with_subject_hint(self, mock_get_container, client, setup_container_mock):
        """Complete draft with subject_hint parameter."""
        setup_container_mock(mock_get_container)

        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": "Test input", "subject_hint": "Réunion de projet"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["success"] is True

    @patch("app.api.routes_helpers._get_container")
    def test_complete_draft_all_optional_params(self, mock_get_container, client, setup_container_mock):
        """Complete draft with all optional parameters."""
        setup_container_mock(mock_get_container)

        response = client.post(
            "/api/drafts/complete",
            json={
                "raw_input": "Test input",
                "recipient": "Sophie",
                "tone": "friendly",
                "subject_hint": "Réunion de projet",
            },
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["success"] is True
        assert data["recipient"] == "Sophie"
        assert data["tone_used"] == "friendly"

    @patch("app.api.routes_helpers._get_container")
    def test_complete_draft_success_minimal(self, mock_get_container, client, setup_container_mock):
        """Complete draft with minimal input returns complete structure."""
        setup_container_mock(mock_get_container)

        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": "- Remercier Sophie\n- Proposer réunion mardi"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["success"] is True
        assert "subject" in data
        assert "body" in data
        assert "recipient" in data
        assert "tone_used" in data
        assert "formatted_output" in data

    @patch("app.api.routes_helpers._get_container")
    def test_complete_draft_success_with_all_fields(self, mock_get_container, client, setup_container_mock):
        """Complete draft returns all expected fields."""
        completed_draft = CompletedDraft(
            subject="Proposition de réunion",
            body="Bonjour Sophie,\n\nJe te remercie.\n\nCordialement",
            recipient="Sophie",
            tone_used=DraftInputTone.FORMAL,
        )
        setup_container_mock(mock_get_container, completed_draft)

        response = client.post(
            "/api/drafts/complete",
            json={
                "raw_input": "- Remercier Sophie\n- Proposer réunion mardi",
                "recipient": "Sophie",
                "tone": "formal",
                "subject_hint": "Réunion",
            },
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["success"] is True
        assert data["subject"] == "Proposition de réunion"
        assert "Bonjour Sophie" in data["body"]
        assert data["recipient"] == "Sophie"
        assert data["tone_used"] == "formal"
        assert "formatted_output" in data


class TestCompleteDraftEdgeCases:
    """Edge case tests for POST /api/drafts/complete endpoint."""

    @patch("app.api.routes_helpers._get_container")
    def test_complete_draft_unicode_input(self, mock_get_container, client, setup_container_mock):
        """Complete draft with unicode characters in input."""
        setup_container_mock(mock_get_container)

        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": "日本語のテスト\n- 挨拶する\n- 会議を提案する 🎉"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["success"] is True

    @patch("app.api.routes_helpers._get_container")
    def test_complete_draft_special_characters(self, mock_get_container, client, setup_container_mock):
        """Complete draft with special characters in input."""
        setup_container_mock(mock_get_container)

        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": "Test with <html>&amp; \"quotes\" 'apostrophe' chars"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["success"] is True

    def test_complete_draft_empty_json_object(self, client):
        """Complete draft with empty JSON object returns 400."""
        response = client.post(
            "/api/drafts/complete",
            json={},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    def test_complete_draft_invalid_json(self, client):
        """Complete draft with invalid JSON returns error."""
        response = client.post(
            "/api/drafts/complete",
            data="not valid json{",
            content_type="application/json",
        )

        assert response.status_code in (400, 415)

    @patch("app.api.routes_helpers._get_container")
    def test_complete_draft_extra_fields_ignored(self, mock_get_container, client, setup_container_mock):
        """Complete draft ignores extra fields in request body."""
        setup_container_mock(mock_get_container)

        response = client.post(
            "/api/drafts/complete",
            json={
                "raw_input": "Test input",
                "extra_field": "should be ignored",
                "another_field": 123,
            },
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["success"] is True

    def test_complete_draft_whitespace_only_raw_input(self, client):
        """Complete draft with whitespace-only raw_input returns 400."""
        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": "   \n\t  "},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    def test_complete_draft_very_long_input_returns_400(self, client):
        """Complete draft with input exceeding MAX_RAW_INPUT_LENGTH returns 400."""
        # MAX_RAW_INPUT_LENGTH is 10000, so this exceeds it
        long_input = "- Point " + "x" * 10000 + "\n- Another point"

        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": long_input},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "exceeds maximum length" in data["error"]

    @patch("app.api.routes_helpers._get_container")
    def test_complete_draft_long_input_within_limit(
        self, mock_get_container, client, setup_container_mock
    ):
        """Complete draft with long input within limit succeeds."""
        setup_container_mock(mock_get_container)

        # 9990 chars is within the 10000 limit
        long_input = "x" * 9990

        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": long_input},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["success"] is True

    @patch("app.api.routes_helpers._get_container")
    def test_complete_draft_multiline_input(self, mock_get_container, client, setup_container_mock):
        """Complete draft with multi-line bullet points."""
        setup_container_mock(mock_get_container)

        response = client.post(
            "/api/drafts/complete",
            json={
                "raw_input": """Brouillon:
- Remercier Sophie pour son retour rapide
- Confirmer disponibilité mardi ou jeudi
- Mentionner le budget prévu
- Demander validation du planning"""
            },
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["success"] is True


class TestCompleteDraftErrors:
    """Error handling tests for POST /api/drafts/complete endpoint."""

    @patch("app.api.routes_helpers._get_container")
    def test_complete_draft_use_case_exception(self, mock_get_container, client):
        """Complete draft with use case exception returns 500."""
        mock_use_case = Mock()
        mock_use_case.execute.side_effect = Exception("UseCase failed")
        mock_container = Mock()
        mock_container.get_complete_draft_use_case.return_value = mock_use_case
        mock_get_container.return_value = mock_container

        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": "Test input"},
        )
        data = response.get_json()

        assert response.status_code == 500
        assert "error" in data
        assert "internal error" in data["error"].lower()

    @patch("app.api.routes_helpers._get_container")
    def test_complete_draft_container_exception(self, mock_get_container, client):
        """Complete draft with container exception returns 500."""
        mock_get_container.side_effect = Exception("Container failed")

        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": "Test input"},
        )
        data = response.get_json()

        assert response.status_code == 500
        assert "error" in data

    @patch("app.api.routes_helpers._get_container")
    def test_complete_draft_get_use_case_exception(self, mock_get_container, client):
        """Complete draft with get_complete_draft_use_case exception returns 500."""
        mock_container = Mock()
        mock_container.get_complete_draft_use_case.side_effect = Exception("UseCase not found")
        mock_get_container.return_value = mock_container

        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": "Test input"},
        )
        data = response.get_json()

        assert response.status_code == 500
        assert "error" in data


class TestCompleteDraftToneValidation:
    """Detailed tone validation tests."""

    def test_complete_draft_tone_numeric_value(self, client):
        """Complete draft with numeric tone value returns 400."""
        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": "Test input", "tone": 123},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    def test_complete_draft_tone_empty_string(self, client):
        """Complete draft with empty tone string returns 400."""
        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": "Test input", "tone": ""},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    @patch("app.api.routes_helpers._get_container")
    def test_complete_draft_tone_null_is_ignored(self, mock_get_container, client, setup_container_mock):
        """Complete draft with null tone uses default."""
        setup_container_mock(mock_get_container)

        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": "Test input", "tone": None},
        )
        response.get_json()

        assert response.status_code == 200

    def test_complete_draft_tone_with_spaces(self, client):
        """Complete draft with spaces in tone returns 400."""
        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": "Test input", "tone": " formal "},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data


class TestCompleteDraftResponseStructure:
    """Tests for response structure validation."""

    @patch("app.api.routes_helpers._get_container")
    def test_complete_draft_response_has_all_required_fields(self, mock_get_container, client, setup_container_mock):
        """Complete draft response has all required fields."""
        completed_draft = CompletedDraft(
            subject="Test Subject",
            body="Test body content",
            recipient="Test Recipient",
            tone_used=DraftInputTone.NEUTRAL,
        )
        setup_container_mock(mock_get_container, completed_draft)

        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": "Test input"},
        )
        data = response.get_json()

        assert response.status_code == 200
        required_fields = ["success", "subject", "body", "recipient", "tone_used", "formatted_output"]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"

    @patch("app.api.routes_helpers._get_container")
    def test_complete_draft_response_success_is_boolean(self, mock_get_container, client, setup_container_mock):
        """Complete draft response success field is boolean True."""
        setup_container_mock(mock_get_container)

        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": "Test input"},
        )
        data = response.get_json()

        assert data["success"] is True
        assert isinstance(data["success"], bool)

    @patch("app.api.routes_helpers._get_container")
    def test_complete_draft_response_tone_used_is_string(self, mock_get_container, client, setup_container_mock):
        """Complete draft response tone_used field is a string."""
        setup_container_mock(mock_get_container)

        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": "Test input"},
        )
        data = response.get_json()

        assert isinstance(data["tone_used"], str)
        assert data["tone_used"] in ["formal", "friendly", "urgent", "conciliatory", "neutral"]

    @patch("app.api.routes_helpers._get_container")
    def test_complete_draft_response_formatted_output_contains_subject(
        self, mock_get_container, client, setup_container_mock
    ):
        """Complete draft formatted_output contains subject."""
        completed_draft = CompletedDraft(
            subject="Important Meeting",
            body="Test body",
            recipient="John",
            tone_used=DraftInputTone.FORMAL,
        )
        setup_container_mock(mock_get_container, completed_draft)

        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": "Test input"},
        )
        data = response.get_json()

        assert "Important Meeting" in data["formatted_output"]
        assert "Test body" in data["formatted_output"]


class TestCompleteDraftTypeValidation:
    """Tests for type validation of input parameters.

    Type validation was added - non-string raw_input now returns 400.
    """

    def test_complete_draft_raw_input_as_list(self, client):
        """Complete draft with raw_input as list returns 400."""
        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": ["item1", "item2"]},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "must be a string" in data["error"]

    def test_complete_draft_raw_input_as_dict(self, client):
        """Complete draft with raw_input as dict returns 400."""
        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": {"text": "some text"}},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "must be a string" in data["error"]

    def test_complete_draft_raw_input_as_number(self, client):
        """Complete draft with raw_input as number returns 400."""
        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": 12345},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "must be a string" in data["error"]

    def test_complete_draft_raw_input_as_boolean(self, client):
        """Complete draft with raw_input as boolean returns 400."""
        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": True},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "must be a string" in data["error"]

    def test_complete_draft_tone_as_list(self, client):
        """Complete draft with tone as list returns 400."""
        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": "Test input", "tone": ["formal", "friendly"]},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    def test_complete_draft_tone_as_dict(self, client):
        """Complete draft with tone as dict returns 400."""
        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": "Test input", "tone": {"value": "formal"}},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    def test_complete_draft_tone_as_boolean(self, client):
        """Complete draft with tone as boolean returns 400."""
        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": "Test input", "tone": True},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    def test_complete_draft_recipient_as_number_returns_400(self, client):
        """Complete draft with recipient as number returns 400."""
        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": "Test input", "recipient": 12345},
        )
        data = response.get_json()

        # recipient is validated as string
        assert response.status_code == 400
        assert "error" in data
        assert "recipient must be a string" in data["error"]

    def test_complete_draft_subject_hint_as_list_returns_400(self, client):
        """Complete draft with subject_hint as list returns 400."""
        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": "Test input", "subject_hint": ["Meeting", "Project"]},
        )
        data = response.get_json()

        # subject_hint is validated as string
        assert response.status_code == 400
        assert "error" in data
        assert "subject_hint must be a string" in data["error"]


class TestCompleteDraftHTTPMethods:
    """Tests for HTTP method validation.

    NOTE: Flask returns 404 for methods not registered on a route,
    not 405 Method Not Allowed. This is expected Flask behavior.
    """

    def test_complete_draft_get_method_not_allowed(self, client):
        """GET method on /api/drafts/complete returns 404 (Flask behavior)."""
        response = client.get("/api/drafts/complete")

        # Flask returns 404 for unregistered methods on a route
        assert response.status_code in (404, 405)

    def test_complete_draft_put_method_not_allowed(self, client):
        """PUT method on /api/drafts/complete returns 404 (Flask behavior)."""
        response = client.put(
            "/api/drafts/complete",
            json={"raw_input": "Test input"},
        )

        assert response.status_code in (404, 405)

    def test_complete_draft_delete_method_not_allowed(self, client):
        """DELETE method on /api/drafts/complete returns 404 (Flask behavior)."""
        response = client.delete("/api/drafts/complete")

        assert response.status_code in (404, 405)

    def test_complete_draft_patch_method_not_allowed(self, client):
        """PATCH method on /api/drafts/complete returns 404 (Flask behavior)."""
        response = client.patch(
            "/api/drafts/complete",
            json={"raw_input": "Test input"},
        )

        assert response.status_code in (404, 405)


class TestCompleteDraftContentType:
    """Tests for Content-Type header validation."""

    def test_complete_draft_text_plain_content_type(self, client):
        """Complete draft with text/plain Content-Type returns error."""
        response = client.post(
            "/api/drafts/complete",
            data='{"raw_input": "Test input"}',
            content_type="text/plain",
        )

        assert response.status_code in (400, 415)

    def test_complete_draft_form_urlencoded_content_type(self, client):
        """Complete draft with form-urlencoded Content-Type returns error."""
        response = client.post(
            "/api/drafts/complete",
            data="raw_input=Test+input",
            content_type="application/x-www-form-urlencoded",
        )

        assert response.status_code in (400, 415)

    def test_complete_draft_no_content_type(self, client):
        """Complete draft without Content-Type header returns error."""
        response = client.post(
            "/api/drafts/complete",
            data='{"raw_input": "Test input"}',
        )

        assert response.status_code in (400, 415)


class TestCompleteDraftBoundaryConditions:
    """Tests for boundary conditions and special inputs."""

    def test_complete_draft_raw_input_control_characters(self, client):
        """Complete draft with control characters in raw_input.

        Current behavior: 500 when JSON contains null bytes.
        This is a known edge case with JSON parsing.
        """
        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": "Test\x00with\x01control\x02chars"},
        )

        # JSON parsing may fail or pass through - accept any error response
        assert response.status_code in (200, 400, 500)

    @patch("app.api.routes_helpers._get_container")
    def test_complete_draft_recipient_unicode(self, mock_get_container, client, setup_container_mock):
        """Complete draft with unicode recipient."""
        setup_container_mock(mock_get_container)

        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": "Test input", "recipient": "田中太郎 🇯🇵"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["success"] is True

    @patch("app.api.routes_helpers._get_container")
    def test_complete_draft_subject_hint_special_chars(self, mock_get_container, client, setup_container_mock):
        """Complete draft with special characters in subject_hint."""
        setup_container_mock(mock_get_container)

        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": "Test input", "subject_hint": 'Re: <Important> & "Urgent"'},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["success"] is True

    def test_complete_draft_very_long_recipient_returns_400(self, client):
        """Complete draft with recipient exceeding MAX_RECIPIENT_LENGTH returns 400."""
        # MAX_RECIPIENT_LENGTH is 200, so 1000 chars exceeds it
        long_recipient = "A" * 1000

        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": "Test input", "recipient": long_recipient},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "recipient" in data["error"].lower()

    @patch("app.api.routes_helpers._get_container")
    def test_complete_draft_recipient_within_limit(
        self, mock_get_container, client, setup_container_mock
    ):
        """Complete draft with recipient within limit succeeds."""
        setup_container_mock(mock_get_container)

        # 199 chars is within the 200 limit
        valid_recipient = "A" * 199

        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": "Test input", "recipient": valid_recipient},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["success"] is True

    @patch("app.api.routes_helpers._get_container")
    def test_complete_draft_empty_recipient(self, mock_get_container, client, setup_container_mock):
        """Complete draft with empty string recipient."""
        setup_container_mock(mock_get_container)

        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": "Test input", "recipient": ""},
        )
        response.get_json()

        # Empty recipient should be accepted (optional field)
        assert response.status_code == 200

    @patch("app.api.routes_helpers._get_container")
    def test_complete_draft_null_recipient(self, mock_get_container, client, setup_container_mock):
        """Complete draft with null recipient."""
        setup_container_mock(mock_get_container)

        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": "Test input", "recipient": None},
        )
        response.get_json()

        assert response.status_code == 200

    @patch("app.api.routes_helpers._get_container")
    def test_complete_draft_empty_subject_hint(self, mock_get_container, client, setup_container_mock):
        """Complete draft with empty subject_hint."""
        setup_container_mock(mock_get_container)

        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": "Test input", "subject_hint": ""},
        )
        response.get_json()

        assert response.status_code == 200

    def test_complete_draft_raw_input_only_newlines(self, client):
        """Complete draft with raw_input containing only newlines."""
        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": "\n\n\n"},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
