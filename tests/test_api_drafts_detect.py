"""Tests for POST /api/drafts/detect endpoint."""

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


@pytest.fixture
def mock_is_draft_true():
    """Mock is_draft_request returning True."""
    with patch("app.api.routes_learning._get_legacy_modules") as mock_legacy:
        mock_legacy.return_value = {"is_draft_request": Mock(return_value=True)}
        yield mock_legacy


@pytest.fixture
def mock_is_draft_false():
    """Mock is_draft_request returning False."""
    with patch("app.api.routes_learning._get_legacy_modules") as mock_legacy:
        mock_legacy.return_value = {"is_draft_request": Mock(return_value=False)}
        yield mock_legacy


class TestDetectDraftEndpoint:
    """Tests for POST /api/drafts/detect input validation."""

    def test_detect_draft_no_json_body(self, client):
        """Detect draft without JSON body returns error."""
        response = client.post("/api/drafts/detect")
        assert response.status_code in (400, 415)

    def test_detect_draft_missing_text(self, client):
        """Detect draft without text field returns 400."""
        response = client.post(
            "/api/drafts/detect",
            json={"other_field": "value"},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "text" in data["error"].lower()

    def test_detect_draft_empty_text(self, client):
        """Detect draft with empty text returns 400."""
        response = client.post(
            "/api/drafts/detect",
            json={"text": ""},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "text" in data["error"].lower()

    def test_detect_draft_null_text(self, client):
        """Detect draft with null text returns 400."""
        response = client.post(
            "/api/drafts/detect",
            json={"text": None},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    def test_detect_draft_empty_json_object(self, client):
        """Detect draft with empty JSON object returns 400."""
        response = client.post(
            "/api/drafts/detect",
            json={},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    def test_detect_draft_invalid_json(self, client):
        """Detect draft with invalid JSON returns error."""
        response = client.post(
            "/api/drafts/detect",
            data="not valid json{",
            content_type="application/json",
        )

        assert response.status_code in (400, 415)

    @patch("app.api.routes_learning._get_legacy_modules")
    def test_detect_draft_success_returns_true(self, mock_legacy, client):
        """Detect draft with draft text returns is_draft_request=True."""
        mock_legacy.return_value = {"is_draft_request": Mock(return_value=True)}

        response = client.post(
            "/api/drafts/detect",
            json={"text": "Brouillon: test content"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["is_draft_request"] is True

    @patch("app.api.routes_learning._get_legacy_modules")
    def test_detect_draft_success_returns_false(self, mock_legacy, client):
        """Detect draft with normal text returns is_draft_request=False."""
        mock_legacy.return_value = {"is_draft_request": Mock(return_value=False)}

        response = client.post(
            "/api/drafts/detect",
            json={"text": "Normal email content without draft markers"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["is_draft_request"] is False


class TestDetectDraftEdgeCases:
    """Edge case tests for POST /api/drafts/detect endpoint."""

    @patch("app.api.routes_learning._get_legacy_modules")
    def test_detect_draft_unicode_input(self, mock_legacy, client):
        """Detect draft with unicode characters in text."""
        mock_legacy.return_value = {"is_draft_request": Mock(return_value=True)}

        response = client.post(
            "/api/drafts/detect",
            json={"text": "日本語のテスト\n- 挨拶する\n- 会議を提案する 🎉"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert "is_draft_request" in data

    @patch("app.api.routes_learning._get_legacy_modules")
    def test_detect_draft_special_characters(self, mock_legacy, client):
        """Detect draft with special characters in text."""
        mock_legacy.return_value = {"is_draft_request": Mock(return_value=False)}

        response = client.post(
            "/api/drafts/detect",
            json={"text": "Test with <html>&amp; \"quotes\" 'apostrophe' chars"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert "is_draft_request" in data

    @patch("app.api.routes_learning._get_legacy_modules")
    def test_detect_draft_emojis(self, mock_legacy, client):
        """Detect draft with emojis in text."""
        mock_legacy.return_value = {"is_draft_request": Mock(return_value=True)}

        response = client.post(
            "/api/drafts/detect",
            json={"text": "📧 Draft: Send email 📝 with 🎯 action items"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert "is_draft_request" in data

    def test_detect_draft_very_long_text_returns_400(self, client):
        """Detect draft with text exceeding MAX_DETECT_TEXT_LENGTH returns 400."""
        # MAX_DETECT_TEXT_LENGTH is 5000, so 10000 exceeds it
        long_text = "A" * 10000

        response = client.post(
            "/api/drafts/detect",
            json={"text": long_text},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "exceeds maximum length" in data["error"]

    @patch("app.api.routes_learning._get_legacy_modules")
    def test_detect_draft_long_text_within_limit(self, mock_legacy, client):
        """Detect draft with long text within limit succeeds."""
        mock_legacy.return_value = {"is_draft_request": Mock(return_value=False)}

        # 4990 chars is within the 5000 limit
        long_text = "A" * 4990

        response = client.post(
            "/api/drafts/detect",
            json={"text": long_text},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert "is_draft_request" in data

    @patch("app.api.routes_learning._get_legacy_modules")
    def test_detect_draft_multiline_text(self, mock_legacy, client):
        """Detect draft with multi-line text."""
        mock_legacy.return_value = {"is_draft_request": Mock(return_value=True)}

        response = client.post(
            "/api/drafts/detect",
            json={
                "text": """Brouillon:
- Point 1
- Point 2
- Point 3

Cordialement"""
            },
        )
        data = response.get_json()

        assert response.status_code == 200
        assert "is_draft_request" in data

    @patch("app.api.routes_learning._get_legacy_modules")
    def test_detect_draft_extra_fields_ignored(self, mock_legacy, client):
        """Detect draft ignores extra fields in request body."""
        mock_legacy.return_value = {"is_draft_request": Mock(return_value=True)}

        response = client.post(
            "/api/drafts/detect",
            json={
                "text": "Draft content",
                "extra_field": "should be ignored",
                "another_field": 123,
            },
        )
        data = response.get_json()

        assert response.status_code == 200
        assert "is_draft_request" in data

    @patch("app.api.routes_learning._get_legacy_modules")
    def test_detect_draft_whitespace_only_text(self, mock_legacy, client):
        """Detect draft with whitespace-only text is processed (no validation).

        NOTE: Current behavior accepts whitespace-only text as valid input.
        The text passes `if not text` check and is sent to is_draft_request.
        """
        mock_legacy.return_value = {"is_draft_request": Mock(return_value=False)}

        response = client.post(
            "/api/drafts/detect",
            json={"text": "   \n\t  "},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert "is_draft_request" in data

    @patch("app.api.routes_learning._get_legacy_modules")
    def test_detect_draft_text_with_leading_whitespace(self, mock_legacy, client):
        """Detect draft with leading/trailing whitespace in text."""
        mock_legacy.return_value = {"is_draft_request": Mock(return_value=True)}

        response = client.post(
            "/api/drafts/detect",
            json={"text": "   Draft content with spaces   "},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert "is_draft_request" in data

    @patch("app.api.routes_learning._get_legacy_modules")
    def test_detect_draft_single_character(self, mock_legacy, client):
        """Detect draft with single character text."""
        mock_legacy.return_value = {"is_draft_request": Mock(return_value=False)}

        response = client.post(
            "/api/drafts/detect",
            json={"text": "a"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert "is_draft_request" in data


class TestDetectDraftErrors:
    """Error handling tests for POST /api/drafts/detect endpoint.

    NOTE: The endpoint does not have explicit try/catch error handling,
    so exceptions propagate up and may result in different status codes
    depending on Flask's error handlers.
    """

    @patch("app.api.routes_learning._get_legacy_modules")
    def test_detect_draft_is_draft_function_exception_propagates(self, mock_legacy, client):
        """Detect draft with is_draft_request exception → 500 JSON.

        Flask test client sous TESTING=True catche les exceptions et retourne
        500 + body JSON {success: false, code, error}. La note originale du
        test (« endpoint doesn't have try/catch, so exceptions propagate »)
        était erronée — Flask a TOUJOURS un handler global.
        """
        mock_is_draft = Mock(side_effect=Exception("Detection failed"))
        mock_legacy.return_value = {"is_draft_request": mock_is_draft}

        response = client.post(
            "/api/drafts/detect",
            json={"text": "Test content"},
        )
        assert response.status_code == 500

    @patch("app.api.routes_learning._get_legacy_modules")
    def test_detect_draft_legacy_modules_exception_propagates(self, mock_legacy, client):
        """Detect draft with _get_legacy_modules exception → 500 JSON.

        cf. test_detect_draft_is_draft_function_exception_propagates pour
        l'explication.
        """
        mock_legacy.side_effect = Exception("Legacy modules failed")

        response = client.post(
            "/api/drafts/detect",
            json={"text": "Test content"},
        )
        assert response.status_code == 500

    @patch("app.api.routes_learning._get_legacy_modules")
    def test_detect_draft_key_error_in_legacy_modules_propagates(self, mock_legacy, client):
        """Detect draft with missing key in legacy modules → 500 JSON.

        cf. test_detect_draft_is_draft_function_exception_propagates pour
        l'explication.
        """
        mock_legacy.return_value = {}

        response = client.post(
            "/api/drafts/detect",
            json={"text": "Test content"},
        )
        assert response.status_code == 500

    @patch("app.api.routes_learning._get_legacy_modules")
    def test_detect_draft_none_return_from_is_draft(self, mock_legacy, client):
        """Detect draft when is_draft_request returns None."""
        mock_legacy.return_value = {"is_draft_request": Mock(return_value=None)}

        response = client.post(
            "/api/drafts/detect",
            json={"text": "Test content"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["is_draft_request"] is None


class TestDetectDraftResponseStructure:
    """Tests for response structure validation."""

    @patch("app.api.routes_learning._get_legacy_modules")
    def test_detect_draft_response_has_all_required_fields(self, mock_legacy, client):
        """Detect draft response has all required fields."""
        mock_legacy.return_value = {"is_draft_request": Mock(return_value=True)}

        response = client.post(
            "/api/drafts/detect",
            json={"text": "Test content for detection"},
        )
        data = response.get_json()

        assert response.status_code == 200
        required_fields = ["is_draft_request", "text_preview"]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"

    @patch("app.api.routes_learning._get_legacy_modules")
    def test_detect_draft_response_is_draft_request_is_boolean(self, mock_legacy, client):
        """Detect draft response is_draft_request field is boolean."""
        mock_legacy.return_value = {"is_draft_request": Mock(return_value=True)}

        response = client.post(
            "/api/drafts/detect",
            json={"text": "Test content"},
        )
        data = response.get_json()

        assert isinstance(data["is_draft_request"], bool)

    @patch("app.api.routes_learning._get_legacy_modules")
    def test_detect_draft_response_text_preview_is_string(self, mock_legacy, client):
        """Detect draft response text_preview field is string."""
        mock_legacy.return_value = {"is_draft_request": Mock(return_value=False)}

        response = client.post(
            "/api/drafts/detect",
            json={"text": "Test content"},
        )
        data = response.get_json()

        assert isinstance(data["text_preview"], str)

    @patch("app.api.routes_learning._get_legacy_modules")
    def test_detect_draft_response_no_extra_fields(self, mock_legacy, client):
        """Detect draft response has only expected fields."""
        mock_legacy.return_value = {"is_draft_request": Mock(return_value=True)}

        response = client.post(
            "/api/drafts/detect",
            json={"text": "Test content"},
        )
        data = response.get_json()

        expected_fields = {"is_draft_request", "text_preview"}
        actual_fields = set(data.keys())
        assert actual_fields == expected_fields

    @patch("app.api.routes_learning._get_legacy_modules")
    def test_detect_draft_response_text_preview_matches_input(self, mock_legacy, client):
        """Detect draft text_preview contains beginning of input text."""
        mock_legacy.return_value = {"is_draft_request": Mock(return_value=True)}

        input_text = "Short text for preview"

        response = client.post(
            "/api/drafts/detect",
            json={"text": input_text},
        )
        data = response.get_json()

        assert data["text_preview"] == input_text

    @patch("app.api.routes_learning._get_legacy_modules")
    def test_detect_draft_error_response_structure(self, mock_legacy, client):
        """Detect draft error response has error field."""
        response = client.post(
            "/api/drafts/detect",
            json={},
        )
        data = response.get_json()

        assert "error" in data
        assert isinstance(data["error"], str)


class TestDetectDraftTextPreview:
    """Tests for text_preview truncation (max 100 characters)."""

    @patch("app.api.routes_learning._get_legacy_modules")
    def test_detect_draft_text_preview_short_text_not_truncated(self, mock_legacy, client):
        """Detect draft text_preview with short text is not truncated."""
        mock_legacy.return_value = {"is_draft_request": Mock(return_value=True)}

        short_text = "Short text"

        response = client.post(
            "/api/drafts/detect",
            json={"text": short_text},
        )
        data = response.get_json()

        assert data["text_preview"] == short_text
        assert "..." not in data["text_preview"]

    @patch("app.api.routes_learning._get_legacy_modules")
    def test_detect_draft_text_preview_exactly_100_chars(self, mock_legacy, client):
        """Detect draft text_preview with exactly 100 chars is not truncated."""
        mock_legacy.return_value = {"is_draft_request": Mock(return_value=True)}

        text_100 = "A" * 100

        response = client.post(
            "/api/drafts/detect",
            json={"text": text_100},
        )
        data = response.get_json()

        assert data["text_preview"] == text_100
        assert len(data["text_preview"]) == 100
        assert "..." not in data["text_preview"]

    @patch("app.api.routes_learning._get_legacy_modules")
    def test_detect_draft_text_preview_101_chars_truncated(self, mock_legacy, client):
        """Detect draft text_preview with 101 chars is truncated."""
        mock_legacy.return_value = {"is_draft_request": Mock(return_value=True)}

        text_101 = "A" * 101

        response = client.post(
            "/api/drafts/detect",
            json={"text": text_101},
        )
        data = response.get_json()

        assert data["text_preview"].endswith("...")
        assert len(data["text_preview"]) == 103  # 100 + 3 for "..."

    @patch("app.api.routes_learning._get_legacy_modules")
    def test_detect_draft_text_preview_long_text_truncated(self, mock_legacy, client):
        """Detect draft text_preview with long text is truncated to 100 chars + ellipsis."""
        mock_legacy.return_value = {"is_draft_request": Mock(return_value=False)}

        long_text = "B" * 200

        response = client.post(
            "/api/drafts/detect",
            json={"text": long_text},
        )
        data = response.get_json()

        assert len(data["text_preview"]) == 103
        assert data["text_preview"] == "B" * 100 + "..."

    @patch("app.api.routes_learning._get_legacy_modules")
    def test_detect_draft_text_preview_unicode_truncation(self, mock_legacy, client):
        """Detect draft text_preview truncates unicode correctly."""
        mock_legacy.return_value = {"is_draft_request": Mock(return_value=True)}

        unicode_text = "日" * 150

        response = client.post(
            "/api/drafts/detect",
            json={"text": unicode_text},
        )
        data = response.get_json()

        assert data["text_preview"] == "日" * 100 + "..."
        assert len(data["text_preview"]) == 103


class TestDetectDraftHTTPMethods:
    """Tests for HTTP method validation."""

    def test_detect_draft_get_method_not_allowed(self, client):
        """GET method on /api/drafts/detect returns 404 or 405."""
        response = client.get("/api/drafts/detect")

        assert response.status_code in (404, 405)

    def test_detect_draft_put_method_not_allowed(self, client):
        """PUT method on /api/drafts/detect returns 404 or 405."""
        response = client.put(
            "/api/drafts/detect",
            json={"text": "Test input"},
        )

        assert response.status_code in (404, 405)

    def test_detect_draft_delete_method_not_allowed(self, client):
        """DELETE method on /api/drafts/detect returns 404 or 405."""
        response = client.delete("/api/drafts/detect")

        assert response.status_code in (404, 405)

    def test_detect_draft_patch_method_not_allowed(self, client):
        """PATCH method on /api/drafts/detect returns 404 or 405."""
        response = client.patch(
            "/api/drafts/detect",
            json={"text": "Test input"},
        )

        assert response.status_code in (404, 405)


class TestDetectDraftContentType:
    """Tests for Content-Type header validation."""

    def test_detect_draft_text_plain_content_type(self, client):
        """Detect draft with text/plain Content-Type returns error."""
        response = client.post(
            "/api/drafts/detect",
            data='{"text": "Test input"}',
            content_type="text/plain",
        )

        assert response.status_code in (400, 415)

    def test_detect_draft_form_urlencoded_content_type(self, client):
        """Detect draft with form-urlencoded Content-Type returns error."""
        response = client.post(
            "/api/drafts/detect",
            data="text=Test+input",
            content_type="application/x-www-form-urlencoded",
        )

        assert response.status_code in (400, 415)

    def test_detect_draft_no_content_type(self, client):
        """Detect draft without Content-Type header returns error."""
        response = client.post(
            "/api/drafts/detect",
            data='{"text": "Test input"}',
        )

        assert response.status_code in (400, 415)


class TestDetectDraftTypeValidation:
    """Tests for type validation of input parameters.

    The endpoint validates that text is a string.
    Non-string values are rejected with 400 error.
    """

    def test_detect_draft_text_as_list_rejected(self, client):
        """Detect draft with text as list returns 400."""
        response = client.post(
            "/api/drafts/detect",
            json={"text": ["item1", "item2"]},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "string" in data["error"].lower()

    def test_detect_draft_text_as_dict_rejected(self, client):
        """Detect draft with text as dict returns 400."""
        response = client.post(
            "/api/drafts/detect",
            json={"text": {"content": "some text"}},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "string" in data["error"].lower()

    def test_detect_draft_text_as_number_rejected(self, client):
        """Detect draft with text as number returns 400."""
        response = client.post(
            "/api/drafts/detect",
            json={"text": 12345},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "string" in data["error"].lower()

    def test_detect_draft_text_as_boolean_rejected(self, client):
        """Detect draft with text as boolean True returns 400."""
        response = client.post(
            "/api/drafts/detect",
            json={"text": True},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "string" in data["error"].lower()

    def test_detect_draft_text_as_zero_rejected(self, client):
        """Detect draft with text as zero returns 400."""
        response = client.post(
            "/api/drafts/detect",
            json={"text": 0},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    def test_detect_draft_text_as_false_rejected(self, client):
        """Detect draft with text as False returns 400."""
        response = client.post(
            "/api/drafts/detect",
            json={"text": False},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    def test_detect_draft_text_as_empty_list_rejected(self, client):
        """Detect draft with text as empty list returns 400."""
        response = client.post(
            "/api/drafts/detect",
            json={"text": []},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    def test_detect_draft_text_as_empty_dict_rejected(self, client):
        """Detect draft with text as empty dict returns 400."""
        response = client.post(
            "/api/drafts/detect",
            json={"text": {}},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data


class TestDetectDraftTextPreviewAdditional:
    """Additional tests for text_preview edge cases."""

    @patch("app.api.routes_learning._get_legacy_modules")
    def test_detect_draft_text_preview_99_chars_not_truncated(self, mock_legacy, client):
        """Detect draft text_preview with exactly 99 chars is not truncated."""
        mock_legacy.return_value = {"is_draft_request": Mock(return_value=True)}

        text_99 = "A" * 99

        response = client.post(
            "/api/drafts/detect",
            json={"text": text_99},
        )
        data = response.get_json()

        assert data["text_preview"] == text_99
        assert len(data["text_preview"]) == 99
        assert "..." not in data["text_preview"]

    @patch("app.api.routes_learning._get_legacy_modules")
    def test_detect_draft_text_preview_emoji_truncation_boundary(self, mock_legacy, client):
        """Detect draft text_preview with emojis at truncation boundary."""
        mock_legacy.return_value = {"is_draft_request": Mock(return_value=True)}

        # 98 chars + 1 emoji (may be multi-byte)
        text_with_emoji = "A" * 98 + "🎉" + "B" * 10

        response = client.post(
            "/api/drafts/detect",
            json={"text": text_with_emoji},
        )
        data = response.get_json()

        # Le texte fait plus de 100 caractères donc doit être tronqué
        assert data["text_preview"].endswith("...")

    @patch("app.api.routes_learning._get_legacy_modules")
    def test_detect_draft_text_preview_preserves_newlines(self, mock_legacy, client):
        """Detect draft text_preview preserves newlines in short text."""
        mock_legacy.return_value = {"is_draft_request": Mock(return_value=True)}

        text_with_newlines = "Line 1\nLine 2\nLine 3"

        response = client.post(
            "/api/drafts/detect",
            json={"text": text_with_newlines},
        )
        data = response.get_json()

        assert data["text_preview"] == text_with_newlines
        assert "\n" in data["text_preview"]

    @patch("app.api.routes_learning._get_legacy_modules")
    def test_detect_draft_text_preview_truncates_multiline_correctly(self, mock_legacy, client):
        """Detect draft text_preview truncates multi-line text correctly."""
        mock_legacy.return_value = {"is_draft_request": Mock(return_value=True)}

        # Create text with newlines that exceeds 100 chars
        lines = ["Line " + str(i) + " " * 20 for i in range(10)]
        long_multiline = "\n".join(lines)

        response = client.post(
            "/api/drafts/detect",
            json={"text": long_multiline},
        )
        data = response.get_json()

        assert data["text_preview"].endswith("...")
        assert len(data["text_preview"]) == 103


class TestDetectDraftTypeValidationExtended:
    """Extended type validation tests for edge cases."""

    def test_detect_draft_text_as_float_rejected(self, client):
        """Detect draft with text as float returns 400."""
        response = client.post(
            "/api/drafts/detect",
            json={"text": 3.14159},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "string" in data["error"].lower()

    def test_detect_draft_text_as_zero_float_rejected(self, client):
        """Detect draft with text as 0.0 returns 400."""
        response = client.post(
            "/api/drafts/detect",
            json={"text": 0.0},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    def test_detect_draft_text_as_nested_list_rejected(self, client):
        """Detect draft with text as nested list returns 400."""
        response = client.post(
            "/api/drafts/detect",
            json={"text": [["nested", "list"], ["another"]]},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "string" in data["error"].lower()


class TestDetectDraftHTTPMethodsExtended:
    """Extended HTTP method tests."""

    def test_detect_draft_head_method_not_allowed(self, client):
        """HEAD method on /api/drafts/detect returns 404 or 405."""
        response = client.head("/api/drafts/detect")

        assert response.status_code in (404, 405)

    def test_detect_draft_options_method(self, client):
        """OPTIONS method on /api/drafts/detect for CORS preflight."""
        response = client.options("/api/drafts/detect")

        # OPTIONS peut retourner 200 (CORS) ou 404/405 selon la config
        assert response.status_code in (200, 204, 404, 405)


class TestDetectDraftBoundaryConditions:
    """Tests for boundary conditions and special inputs."""

    @patch("app.api.routes_learning._get_legacy_modules")
    def test_detect_draft_newlines_only(self, mock_legacy, client):
        """Detect draft with newlines only is processed (no whitespace validation).

        NOTE: Whitespace-only strings pass `if not text` check.
        """
        mock_legacy.return_value = {"is_draft_request": Mock(return_value=False)}

        response = client.post(
            "/api/drafts/detect",
            json={"text": "\n\n\n"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert "is_draft_request" in data

    @patch("app.api.routes_learning._get_legacy_modules")
    def test_detect_draft_tabs_only(self, mock_legacy, client):
        """Detect draft with tabs only is processed (no whitespace validation).

        NOTE: Whitespace-only strings pass `if not text` check.
        """
        mock_legacy.return_value = {"is_draft_request": Mock(return_value=False)}

        response = client.post(
            "/api/drafts/detect",
            json={"text": "\t\t\t"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert "is_draft_request" in data

    @patch("app.api.routes_learning._get_legacy_modules")
    def test_detect_draft_mixed_whitespace_only(self, mock_legacy, client):
        """Detect draft with mixed whitespace only is processed.

        NOTE: Whitespace-only strings pass `if not text` check.
        """
        mock_legacy.return_value = {"is_draft_request": Mock(return_value=False)}

        response = client.post(
            "/api/drafts/detect",
            json={"text": " \n\t \n "},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert "is_draft_request" in data

    @patch("app.api.routes_learning._get_legacy_modules")
    def test_detect_draft_html_content(self, mock_legacy, client):
        """Detect draft with HTML content."""
        mock_legacy.return_value = {"is_draft_request": Mock(return_value=False)}

        response = client.post(
            "/api/drafts/detect",
            json={"text": "<html><body><p>Test</p></body></html>"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert "is_draft_request" in data

    @patch("app.api.routes_learning._get_legacy_modules")
    def test_detect_draft_json_string_content(self, mock_legacy, client):
        """Detect draft with JSON string as text content."""
        mock_legacy.return_value = {"is_draft_request": Mock(return_value=False)}

        response = client.post(
            "/api/drafts/detect",
            json={"text": '{"key": "value", "nested": {"a": 1}}'},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert "is_draft_request" in data

    @patch("app.api.routes_learning._get_legacy_modules")
    def test_detect_draft_sql_injection_attempt(self, mock_legacy, client):
        """Detect draft with SQL injection attempt in text."""
        mock_legacy.return_value = {"is_draft_request": Mock(return_value=False)}

        response = client.post(
            "/api/drafts/detect",
            json={"text": "'; DROP TABLE users; --"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert "is_draft_request" in data

    @patch("app.api.routes_learning._get_legacy_modules")
    def test_detect_draft_script_injection_attempt(self, mock_legacy, client):
        """Detect draft with script injection attempt in text."""
        mock_legacy.return_value = {"is_draft_request": Mock(return_value=False)}

        response = client.post(
            "/api/drafts/detect",
            json={"text": '<script>alert("xss")</script>'},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert "is_draft_request" in data

    @patch("app.api.routes_learning._get_legacy_modules")
    def test_detect_draft_backslashes(self, mock_legacy, client):
        """Detect draft with backslashes in text."""
        mock_legacy.return_value = {"is_draft_request": Mock(return_value=True)}

        response = client.post(
            "/api/drafts/detect",
            json={"text": "C:\\Users\\Documents\\file.txt"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert "is_draft_request" in data

    @patch("app.api.routes_learning._get_legacy_modules")
    def test_detect_draft_null_bytes(self, mock_legacy, client):
        """Detect draft with null bytes in text."""
        mock_legacy.return_value = {"is_draft_request": Mock(return_value=False)}

        response = client.post(
            "/api/drafts/detect",
            json={"text": "test\x00content"},
        )

        assert response.status_code in (200, 400, 500)
