# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests for app/api/fine_tuning.py API endpoints.

These tests cover all the fine-tuning API endpoints including:
- Corrections endpoints (POST, GET with filters)
- Feedbacks endpoints (POST, GET)
- Patterns endpoints (GET, extract)
- Models endpoints (CRUD, activate, disable)
- Improvements endpoints (apply, get enhancements)
- Sessions endpoints (POST, GET)
- Stats endpoint
"""
from unittest.mock import MagicMock, patch
import pytest


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def temp_storage_dir(tmp_path, monkeypatch):
    """Create temp storage directory and patch all file paths."""
    temp_dir = tmp_path / "fine_tuning_data"
    temp_dir.mkdir(parents=True, exist_ok=True)

    import app.infrastructure.fine_tuning_store as store_module

    monkeypatch.setattr(store_module, "FINE_TUNING_DIR", temp_dir)
    monkeypatch.setattr(store_module, "CORRECTIONS_FILE", temp_dir / "corrections.json")
    monkeypatch.setattr(store_module, "FEEDBACKS_FILE", temp_dir / "feedbacks.json")
    monkeypatch.setattr(store_module, "PATTERNS_FILE", temp_dir / "patterns.json")
    monkeypatch.setattr(store_module, "MODELS_FILE", temp_dir / "models.json")
    monkeypatch.setattr(store_module, "SESSIONS_FILE", temp_dir / "sessions.json")

    return temp_dir


@pytest.fixture
def api_client(temp_storage_dir):
    """Create Flask test client with clean storage."""
    from app.api.app import create_app

    app = create_app({"TESTING": True})
    with app.test_client() as client:
        yield client


@pytest.fixture(autouse=True)
def _stub_draft_ownership(monkeypatch):
    """H-6 (audit security.md, issue #532): /corrections + /feedbacks now
    require the caller to own `draft_id` (`get_by_id_for_account`). The
    existing tests don't seed drafts, so we stub the helpers to always
    resolve to a stub draft. Cross-tenant rejection is regression-tested
    in tests/audit_fixes/test_h_06_fine_tuning_cross_tenant.py.
    """
    fake_draft = MagicMock(id="stub-draft", account_id=1)
    fake_history = MagicMock()
    fake_history.get_by_id_for_account.return_value = fake_draft
    fake_container = MagicMock()
    fake_container.get_draft_history.return_value = fake_history

    monkeypatch.setattr(
        "app.api.fine_tuning._resolve_account_id_for_user", lambda: 1
    )
    monkeypatch.setattr(
        "app.api.fine_tuning._get_container", lambda: fake_container
    )


# =============================================================================
# CORRECTIONS ENDPOINT TESTS
# =============================================================================


class TestCorrectionsEndpoints:
    """Tests for POST/GET /api/fine-tuning/corrections."""

    def test_record_correction_success(self, api_client):
        """Test successful correction recording."""
        response = api_client.post(
            "/api/fine-tuning/corrections",
            json={
                "draft_id": "draft-001",
                "original_text": "Hello world",
                "corrected_text": "Bonjour monde",
                "context": {"tone": "formal"},
                "user_comment": "Translation needed",
            },
        )

        assert response.status_code == 201
        data = response.get_json()
        assert "correction_id" in data
        assert "correction_types" in data
        assert "has_significant_changes" in data
        assert "patterns_found" in data

    def test_record_correction_empty_object(self, api_client):
        """Test correction with empty JSON object."""
        response = api_client.post(
            "/api/fine-tuning/corrections",
            json={},
        )

        # Empty dict is falsy in Python, so API returns "No data provided"
        assert response.status_code == 400
        data = response.get_json()
        # Empty dict evaluates to False in 'if not data:'
        assert data["error"] == "No data provided"

    def test_record_correction_missing_draft_id(self, api_client):
        """Test correction missing draft_id field."""
        response = api_client.post(
            "/api/fine-tuning/corrections",
            json={
                "original_text": "Hello",
                "corrected_text": "Bonjour",
            },
        )

        assert response.status_code == 400
        data = response.get_json()
        assert "Missing field: draft_id" in data["error"]

    def test_record_correction_missing_original_text(self, api_client):
        """Test correction missing original_text field."""
        response = api_client.post(
            "/api/fine-tuning/corrections",
            json={
                "draft_id": "draft-001",
                "corrected_text": "Bonjour",
            },
        )

        assert response.status_code == 400
        data = response.get_json()
        assert "Missing field: original_text" in data["error"]

    def test_record_correction_missing_corrected_text(self, api_client):
        """Test correction missing corrected_text field."""
        response = api_client.post(
            "/api/fine-tuning/corrections",
            json={
                "draft_id": "draft-001",
                "original_text": "Hello",
            },
        )

        assert response.status_code == 400
        data = response.get_json()
        assert "Missing field: corrected_text" in data["error"]

    def test_list_corrections_empty(self, api_client):
        """Test listing corrections when none exist."""
        response = api_client.get("/api/fine-tuning/corrections")

        assert response.status_code == 200
        data = response.get_json()
        assert data["corrections"] == []
        assert data["total"] == 0

    def test_list_corrections_with_limit(self, api_client):
        """Test listing corrections with limit parameter."""
        # Create multiple corrections
        for i in range(5):
            api_client.post(
                "/api/fine-tuning/corrections",
                json={
                    "draft_id": f"draft-{i}",
                    "original_text": f"Original {i}",
                    "corrected_text": f"Corrected {i}",
                },
            )

        response = api_client.get("/api/fine-tuning/corrections?limit=3")

        assert response.status_code == 200
        data = response.get_json()
        assert len(data["corrections"]) <= 3

    def test_list_corrections_filter_by_type(self, api_client):
        """Test filtering corrections by valid type."""
        # Create correction first
        api_client.post(
            "/api/fine-tuning/corrections",
            json={
                "draft_id": "draft-001",
                "original_text": "This is wrong",
                "corrected_text": "This is correct",
            },
        )

        # Filter by 'tone' type (valid CorrectionType)
        response = api_client.get("/api/fine-tuning/corrections?type=tone")

        assert response.status_code == 200
        data = response.get_json()
        assert "corrections" in data

    def test_list_corrections_filter_invalid_type(self, api_client):
        """Test filtering corrections by invalid type."""
        response = api_client.get("/api/fine-tuning/corrections?type=invalid_type")

        assert response.status_code == 400
        data = response.get_json()
        assert "Invalid correction type" in data["error"]


# =============================================================================
# FEEDBACKS ENDPOINT TESTS
# =============================================================================


class TestFeedbacksEndpoints:
    """Tests for POST/GET /api/fine-tuning/feedbacks."""

    def test_record_feedback_success(self, api_client):
        """Test successful feedback recording."""
        response = api_client.post(
            "/api/fine-tuning/feedbacks",
            json={
                "draft_id": "draft-001",
                "rating": 5,
                "comment": "Excellent work!",
                "tags": ["accurate", "professional"],
            },
        )

        assert response.status_code == 201
        data = response.get_json()
        assert "feedback_id" in data
        assert "sentiment" in data
        assert "requires_analysis" in data

    def test_record_feedback_empty_object(self, api_client):
        """Test feedback with empty JSON object."""
        response = api_client.post(
            "/api/fine-tuning/feedbacks",
            json={},
        )

        # Empty dict is falsy in Python, so API returns "No data provided"
        assert response.status_code == 400
        data = response.get_json()
        assert data["error"] == "No data provided"

    def test_record_feedback_missing_draft_id(self, api_client):
        """Test feedback missing draft_id."""
        response = api_client.post(
            "/api/fine-tuning/feedbacks",
            json={"rating": 5},
        )

        assert response.status_code == 400
        data = response.get_json()
        assert "Missing draft_id or rating" in data["error"]

    def test_record_feedback_missing_rating(self, api_client):
        """Test feedback missing rating."""
        response = api_client.post(
            "/api/fine-tuning/feedbacks",
            json={"draft_id": "draft-001"},
        )

        assert response.status_code == 400
        data = response.get_json()
        assert "Missing draft_id or rating" in data["error"]

    def test_record_feedback_rating_too_low(self, api_client):
        """Test feedback with rating below 1."""
        response = api_client.post(
            "/api/fine-tuning/feedbacks",
            json={"draft_id": "draft-001", "rating": 0},
        )

        assert response.status_code == 400
        data = response.get_json()
        assert "Rating must be between 1 and 5" in data["error"]

    def test_record_feedback_rating_too_high(self, api_client):
        """Test feedback with rating above 5."""
        response = api_client.post(
            "/api/fine-tuning/feedbacks",
            json={"draft_id": "draft-001", "rating": 6},
        )

        assert response.status_code == 400
        data = response.get_json()
        assert "Rating must be between 1 and 5" in data["error"]

    def test_record_feedback_rating_not_integer(self, api_client):
        """Test feedback with non-integer rating."""
        response = api_client.post(
            "/api/fine-tuning/feedbacks",
            json={"draft_id": "draft-001", "rating": "five"},
        )

        assert response.status_code == 400
        data = response.get_json()
        assert "Rating must be between 1 and 5" in data["error"]

    def test_list_feedbacks_empty(self, api_client):
        """Test listing feedbacks when none exist."""
        response = api_client.get("/api/fine-tuning/feedbacks")

        assert response.status_code == 200
        data = response.get_json()
        assert data["feedbacks"] == []
        assert data["total"] == 0

    def test_list_feedbacks_with_limit(self, api_client):
        """Test listing feedbacks with limit parameter."""
        # Create multiple feedbacks
        for i in range(5):
            api_client.post(
                "/api/fine-tuning/feedbacks",
                json={"draft_id": f"draft-{i}", "rating": 5},
            )

        response = api_client.get("/api/fine-tuning/feedbacks?limit=3")

        assert response.status_code == 200
        data = response.get_json()
        assert len(data["feedbacks"]) <= 3

    def test_list_feedbacks_average_rating(self, api_client):
        """Test that average_rating is included in response."""
        # Create feedbacks with different ratings
        api_client.post(
            "/api/fine-tuning/feedbacks",
            json={"draft_id": "draft-001", "rating": 4},
        )
        api_client.post(
            "/api/fine-tuning/feedbacks",
            json={"draft_id": "draft-002", "rating": 5},
        )

        response = api_client.get("/api/fine-tuning/feedbacks")

        assert response.status_code == 200
        data = response.get_json()
        assert "average_rating" in data


# =============================================================================
# PATTERNS ENDPOINT TESTS
# =============================================================================


class TestPatternsEndpoints:
    """Tests for GET/POST /api/fine-tuning/patterns."""

    def test_list_patterns_empty(self, api_client):
        """Test listing patterns when none exist."""
        response = api_client.get("/api/fine-tuning/patterns")

        assert response.status_code == 200
        data = response.get_json()
        assert data["patterns"] == []
        assert data["total"] == 0

    def test_list_patterns_with_limit(self, api_client):
        """Test listing patterns with limit parameter."""
        response = api_client.get("/api/fine-tuning/patterns?limit=10")

        assert response.status_code == 200
        data = response.get_json()
        assert "patterns" in data

    def test_list_patterns_with_min_confidence(self, api_client):
        """Test filtering patterns by minimum confidence."""
        response = api_client.get("/api/fine-tuning/patterns?min_confidence=0.8")

        assert response.status_code == 200
        data = response.get_json()
        assert "patterns" in data

    def test_list_patterns_filter_by_type(self, api_client):
        """Test filtering patterns by valid type."""
        response = api_client.get("/api/fine-tuning/patterns?type=grammar")

        assert response.status_code == 200
        data = response.get_json()
        assert "patterns" in data

    def test_list_patterns_filter_invalid_type(self, api_client):
        """Test filtering patterns by invalid type."""
        response = api_client.get("/api/fine-tuning/patterns?type=invalid_type")

        assert response.status_code == 400
        data = response.get_json()
        assert "Invalid pattern type" in data["error"]

    def test_extract_patterns_default(self, api_client):
        """Test extracting patterns with default parameters."""
        response = api_client.post(
            "/api/fine-tuning/patterns/extract",
            json={},
        )

        assert response.status_code == 200
        data = response.get_json()
        assert "patterns_extracted" in data
        assert "patterns_reinforced" in data
        assert "new_patterns" in data

    def test_extract_patterns_with_min_corrections(self, api_client):
        """Test extracting patterns with custom min_corrections."""
        response = api_client.post(
            "/api/fine-tuning/patterns/extract",
            json={"min_corrections": 3},
        )

        assert response.status_code == 200
        data = response.get_json()
        assert "patterns_extracted" in data

    def test_extract_patterns_with_empty_body(self, api_client):
        """Test extracting patterns with empty JSON body."""
        response = api_client.post(
            "/api/fine-tuning/patterns/extract",
            json={},
        )

        assert response.status_code == 200
        data = response.get_json()
        assert "patterns_extracted" in data


# =============================================================================
# MODELS ENDPOINT TESTS
# =============================================================================


class TestModelsEndpoints:
    """Tests for CRUD /api/fine-tuning/models."""

    def test_create_model_success(self, api_client):
        """Test successful model creation."""
        response = api_client.post(
            "/api/fine-tuning/models",
            json={
                "name": "Test Model",
                "description": "A test model for improvements",
                "min_confidence": 0.7,
                "version": "1.0.0",
            },
        )

        assert response.status_code == 201
        data = response.get_json()
        assert "model_id" in data
        assert "model_name" in data
        assert "patterns_included" in data
        assert "prompt_adjustments" in data

    def test_create_model_empty_object(self, api_client):
        """Test model creation with empty JSON object."""
        response = api_client.post(
            "/api/fine-tuning/models",
            json={},
        )

        # Empty dict is falsy in Python, so API returns "No data provided"
        assert response.status_code == 400
        data = response.get_json()
        assert data["error"] == "No data provided"

    def test_create_model_missing_name(self, api_client):
        """Test model creation without name."""
        response = api_client.post(
            "/api/fine-tuning/models",
            json={"description": "A test model"},
        )

        assert response.status_code == 400
        data = response.get_json()
        assert "Missing name or description" in data["error"]

    def test_create_model_missing_description(self, api_client):
        """Test model creation without description."""
        response = api_client.post(
            "/api/fine-tuning/models",
            json={"name": "Test Model"},
        )

        assert response.status_code == 400
        data = response.get_json()
        assert "Missing name or description" in data["error"]

    def test_list_models_empty(self, api_client):
        """Test listing models when none exist."""
        response = api_client.get("/api/fine-tuning/models")

        assert response.status_code == 200
        data = response.get_json()
        assert data["models"] == []
        assert data["total"] == 0

    def test_list_models_filter_by_status(self, api_client):
        """Test filtering models by valid status."""
        # Create a model first
        api_client.post(
            "/api/fine-tuning/models",
            json={"name": "Test", "description": "Test"},
        )

        response = api_client.get("/api/fine-tuning/models?status=pending")

        assert response.status_code == 200
        data = response.get_json()
        assert "models" in data

    def test_list_models_filter_invalid_status(self, api_client):
        """Test filtering models by invalid status."""
        response = api_client.get("/api/fine-tuning/models?status=invalid_status")

        assert response.status_code == 400
        data = response.get_json()
        assert "Invalid status" in data["error"]

    def test_get_model_success(self, api_client):
        """Test getting model details."""
        # Create a model first
        create_response = api_client.post(
            "/api/fine-tuning/models",
            json={"name": "Test Model", "description": "Test description"},
        )
        model_id = create_response.get_json()["model_id"]

        response = api_client.get(f"/api/fine-tuning/models/{model_id}")

        assert response.status_code == 200
        data = response.get_json()
        assert data["id"] == model_id
        assert data["name"] == "Test Model"
        assert data["description"] == "Test description"

    def test_get_model_not_found(self, api_client):
        """Test getting non-existent model."""
        response = api_client.get("/api/fine-tuning/models/nonexistent-id")

        assert response.status_code == 404
        data = response.get_json()
        assert data["error"] == "Model not found"

    def test_activate_model_success(self, api_client):
        """Test activating a model."""
        # Create a model first
        create_response = api_client.post(
            "/api/fine-tuning/models",
            json={"name": "Test Model", "description": "Test"},
        )
        model_id = create_response.get_json()["model_id"]

        response = api_client.post(f"/api/fine-tuning/models/{model_id}/activate")

        assert response.status_code == 200
        data = response.get_json()
        assert data["message"] == "Model activated"
        assert data["model_id"] == model_id

    def test_activate_model_not_found(self, api_client):
        """Test activating non-existent model."""
        response = api_client.post("/api/fine-tuning/models/nonexistent-id/activate")

        assert response.status_code == 404
        data = response.get_json()
        assert "error" in data

    def test_disable_model_success(self, api_client):
        """Test disabling a model."""
        # Create and activate a model first
        create_response = api_client.post(
            "/api/fine-tuning/models",
            json={"name": "Test Model", "description": "Test"},
        )
        model_id = create_response.get_json()["model_id"]
        api_client.post(f"/api/fine-tuning/models/{model_id}/activate")

        response = api_client.post(f"/api/fine-tuning/models/{model_id}/disable")

        assert response.status_code == 200
        data = response.get_json()
        assert data["message"] == "Model disabled"
        assert data["model_id"] == model_id

    def test_disable_model_not_found(self, api_client):
        """Test disabling non-existent model."""
        response = api_client.post("/api/fine-tuning/models/nonexistent-id/disable")

        assert response.status_code == 404
        data = response.get_json()
        assert "error" in data


# =============================================================================
# IMPROVEMENTS ENDPOINT TESTS
# =============================================================================


class TestImprovementsEndpoints:
    """Tests for /api/fine-tuning/improve and /api/fine-tuning/prompt-enhancements."""

    def test_apply_improvements_success(self, api_client):
        """Test applying improvements to text."""
        response = api_client.post(
            "/api/fine-tuning/improve",
            json={"text": "Hello world"},
        )

        assert response.status_code == 200
        data = response.get_json()
        assert "improved_text" in data
        assert "improvements_applied" in data
        assert "patterns_used" in data
        assert "was_improved" in data

    def test_apply_improvements_with_model_id(self, api_client):
        """Test applying improvements with specific model."""
        # Create a model first
        create_response = api_client.post(
            "/api/fine-tuning/models",
            json={"name": "Test Model", "description": "Test"},
        )
        model_id = create_response.get_json()["model_id"]
        api_client.post(f"/api/fine-tuning/models/{model_id}/activate")

        response = api_client.post(
            "/api/fine-tuning/improve",
            json={"text": "Hello world", "model_id": model_id},
        )

        assert response.status_code == 200
        data = response.get_json()
        assert "improved_text" in data

    def test_apply_improvements_empty_object(self, api_client):
        """Test improvements with empty JSON object."""
        response = api_client.post(
            "/api/fine-tuning/improve",
            json={},
        )

        # Should fail because text field is missing
        assert response.status_code == 400
        data = response.get_json()
        assert "Missing text" in data["error"]

    def test_apply_improvements_missing_text(self, api_client):
        """Test improvements without text field."""
        response = api_client.post(
            "/api/fine-tuning/improve",
            json={"model_id": "some-id"},
        )

        assert response.status_code == 400
        data = response.get_json()
        assert "Missing text" in data["error"]

    def test_apply_improvements_empty_text(self, api_client):
        """Test improvements with empty text."""
        response = api_client.post(
            "/api/fine-tuning/improve",
            json={"text": ""},
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["improved_text"] == ""
        assert data["was_improved"] is False

    def test_get_prompt_enhancements(self, api_client):
        """Test getting prompt enhancements."""
        response = api_client.get("/api/fine-tuning/prompt-enhancements")

        assert response.status_code == 200
        data = response.get_json()
        assert "adjustments" in data
        assert "count" in data


# =============================================================================
# SESSIONS ENDPOINT TESTS
# =============================================================================


class TestSessionsEndpoints:
    """Tests for POST/GET /api/fine-tuning/sessions."""

    def test_run_session_default(self, api_client):
        """Test running a session with default parameters."""
        response = api_client.post(
            "/api/fine-tuning/sessions",
            json={},
        )

        assert response.status_code == 200
        data = response.get_json()
        assert "session_id" in data
        assert "corrections_analyzed" in data
        assert "feedbacks_analyzed" in data
        assert "patterns_extracted" in data
        assert "duration_seconds" in data

    def test_run_session_with_params(self, api_client):
        """Test running a session with custom parameters."""
        response = api_client.post(
            "/api/fine-tuning/sessions",
            json={"auto_activate": True, "min_corrections": 5},
        )

        assert response.status_code == 200
        data = response.get_json()
        assert "session_id" in data

    def test_run_session_with_empty_body(self, api_client):
        """Test running a session with empty JSON body."""
        response = api_client.post(
            "/api/fine-tuning/sessions",
            json={},
        )

        assert response.status_code == 200
        data = response.get_json()
        assert "session_id" in data

    def test_run_session_error_handling(self, temp_storage_dir, monkeypatch):
        """Test session error handling by patching at the API module level."""

        # Import the API module for patching
        import app.api.fine_tuning as api_ft_module

        # Create a mock use case that raises an error
        mock_use_case = MagicMock()
        mock_use_case.execute.side_effect = Exception("Test error")

        # Patch at the API module level where it's imported
        with patch.object(api_ft_module, "RunFineTuningSessionUseCase", return_value=mock_use_case):
            from app.api.app import create_app

            app = create_app({"TESTING": True})
            with app.test_client() as client:
                response = client.post(
                    "/api/fine-tuning/sessions",
                    json={},
                )

                assert response.status_code == 500
                data = response.get_json()
                assert "error" in data

    def test_list_sessions_empty(self, api_client):
        """Test listing sessions when none exist."""
        response = api_client.get("/api/fine-tuning/sessions")

        assert response.status_code == 200
        data = response.get_json()
        assert data["sessions"] == []
        assert data["total"] == 0

    def test_list_sessions_with_limit(self, api_client):
        """Test listing sessions with limit parameter."""
        # Run multiple sessions
        for _ in range(3):
            api_client.post("/api/fine-tuning/sessions")

        response = api_client.get("/api/fine-tuning/sessions?limit=2")

        assert response.status_code == 200
        data = response.get_json()
        assert len(data["sessions"]) <= 2

    def test_list_sessions_after_run(self, api_client):
        """Test listing sessions after running one."""
        # Run a session
        run_response = api_client.post(
            "/api/fine-tuning/sessions",
            json={},
        )
        session_id = run_response.get_json()["session_id"]

        response = api_client.get("/api/fine-tuning/sessions")

        assert response.status_code == 200
        data = response.get_json()
        assert data["total"] >= 1
        assert any(s["id"] == session_id for s in data["sessions"])


# =============================================================================
# STATS ENDPOINT TESTS
# =============================================================================


class TestStatsEndpoint:
    """Tests for GET /api/fine-tuning/stats."""

    def test_get_stats_empty(self, api_client):
        """Test getting stats when no data exists."""
        response = api_client.get("/api/fine-tuning/stats")

        assert response.status_code == 200
        data = response.get_json()
        assert "total_corrections" in data
        assert "total_feedbacks" in data
        assert "total_patterns" in data
        assert "active_models" in data
        assert "average_impact" in data
        assert "improvement_rate" in data
        assert "top_correction_types" in data
        assert "feedback_sentiment_distribution" in data
        assert "patterns_by_confidence" in data

    def test_get_stats_with_data(self, api_client):
        """Test getting stats with some data."""
        # Create some data
        api_client.post(
            "/api/fine-tuning/corrections",
            json={
                "draft_id": "draft-001",
                "original_text": "Hello",
                "corrected_text": "Bonjour",
            },
        )
        api_client.post(
            "/api/fine-tuning/feedbacks",
            json={"draft_id": "draft-001", "rating": 5},
        )

        response = api_client.get("/api/fine-tuning/stats")

        assert response.status_code == 200
        data = response.get_json()
        assert data["total_corrections"] >= 1
        assert data["total_feedbacks"] >= 1


# =============================================================================
# INTEGRATION TESTS
# =============================================================================


class TestFineTuningIntegration:
    """Integration tests for the complete fine-tuning workflow."""

    def test_complete_workflow(self, api_client):
        """Test complete fine-tuning workflow."""
        # 1. Record several corrections
        for i in range(5):
            api_client.post(
                "/api/fine-tuning/corrections",
                json={
                    "draft_id": f"draft-{i}",
                    "original_text": f"Hello {i}",
                    "corrected_text": f"Bonjour {i}",
                },
            )

        # 2. Record feedbacks
        for i in range(5):
            api_client.post(
                "/api/fine-tuning/feedbacks",
                json={"draft_id": f"draft-{i}", "rating": 4 + (i % 2)},
            )

        # 3. Extract patterns
        extract_response = api_client.post(
            "/api/fine-tuning/patterns/extract",
            json={},
        )
        assert extract_response.status_code == 200

        # 4. Create model
        model_response = api_client.post(
            "/api/fine-tuning/models",
            json={"name": "Integration Test Model", "description": "Test"},
        )
        assert model_response.status_code == 201
        model_id = model_response.get_json()["model_id"]

        # 5. Activate model
        activate_response = api_client.post(f"/api/fine-tuning/models/{model_id}/activate")
        assert activate_response.status_code == 200

        # 6. Apply improvements
        improve_response = api_client.post(
            "/api/fine-tuning/improve",
            json={"text": "Hello world"},
        )
        assert improve_response.status_code == 200

        # 7. Get stats
        stats_response = api_client.get("/api/fine-tuning/stats")
        assert stats_response.status_code == 200
        stats = stats_response.get_json()
        assert stats["total_corrections"] >= 5
        assert stats["total_feedbacks"] >= 5

    def test_feedback_sentiment_distribution(self, api_client):
        """Test that feedback sentiment distribution is calculated correctly."""
        # Create feedbacks with different ratings
        api_client.post(
            "/api/fine-tuning/feedbacks",
            json={"draft_id": "draft-neg", "rating": 1},  # negative
        )
        api_client.post(
            "/api/fine-tuning/feedbacks",
            json={"draft_id": "draft-neu", "rating": 3},  # neutral
        )
        api_client.post(
            "/api/fine-tuning/feedbacks",
            json={"draft_id": "draft-pos", "rating": 5},  # positive
        )

        response = api_client.get("/api/fine-tuning/stats")

        assert response.status_code == 200
        data = response.get_json()
        assert "feedback_sentiment_distribution" in data

    def test_model_lifecycle(self, api_client):
        """Test model creation, activation, and disabling."""
        # Create
        create_response = api_client.post(
            "/api/fine-tuning/models",
            json={"name": "Lifecycle Test", "description": "Test lifecycle"},
        )
        assert create_response.status_code == 201
        model_id = create_response.get_json()["model_id"]

        # Verify initial status
        get_response = api_client.get(f"/api/fine-tuning/models/{model_id}")
        assert get_response.status_code == 200
        assert get_response.get_json()["status"] == "pending"

        # Activate
        activate_response = api_client.post(f"/api/fine-tuning/models/{model_id}/activate")
        assert activate_response.status_code == 200

        # Verify active status
        get_response = api_client.get(f"/api/fine-tuning/models/{model_id}")
        assert get_response.get_json()["status"] == "active"

        # Disable
        disable_response = api_client.post(f"/api/fine-tuning/models/{model_id}/disable")
        assert disable_response.status_code == 200

        # Verify disabled status
        get_response = api_client.get(f"/api/fine-tuning/models/{model_id}")
        assert get_response.get_json()["status"] == "disabled"


# =============================================================================
# EDGE CASES
# =============================================================================


class TestFineTuningEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_correction_with_special_characters(self, api_client):
        """Test correction with special characters."""
        response = api_client.post(
            "/api/fine-tuning/corrections",
            json={
                "draft_id": "draft-special",
                "original_text": "Hello <script>alert('xss')</script>",
                "corrected_text": "Hello! It's a 'test' with \"quotes\"",
            },
        )

        assert response.status_code == 201

    def test_correction_with_unicode(self, api_client):
        """Test correction with unicode characters."""
        response = api_client.post(
            "/api/fine-tuning/corrections",
            json={
                "draft_id": "draft-unicode",
                "original_text": "Hello 你好 مرحبا",
                "corrected_text": "Bonjour 你好 مرحبا 🎉",
            },
        )

        assert response.status_code == 201

    def test_very_long_text(self, api_client):
        """Test correction with very long text."""
        long_text = "A" * 10000
        response = api_client.post(
            "/api/fine-tuning/corrections",
            json={
                "draft_id": "draft-long",
                "original_text": long_text,
                "corrected_text": long_text + "B",
            },
        )

        assert response.status_code == 201

    def test_feedback_with_optional_fields(self, api_client):
        """Test feedback with all optional fields."""
        response = api_client.post(
            "/api/fine-tuning/feedbacks",
            json={
                "draft_id": "draft-001",
                "rating": 4,
                "comment": "Good but could be better",
                "tags": ["needs-work", "almost-there"],
            },
        )

        assert response.status_code == 201

    def test_pattern_extraction_no_corrections(self, api_client):
        """Test pattern extraction with no corrections."""
        response = api_client.post(
            "/api/fine-tuning/patterns/extract",
            json={},
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["patterns_extracted"] == 0

    def test_model_with_optional_version(self, api_client):
        """Test model creation with optional version."""
        response = api_client.post(
            "/api/fine-tuning/models",
            json={
                "name": "Test Model",
                "description": "Test",
                "min_confidence": 0.8,
                "version": "2.0.0-beta",
            },
        )

        assert response.status_code == 201
        data = response.get_json()
        assert data["model_name"] == "Test Model"
