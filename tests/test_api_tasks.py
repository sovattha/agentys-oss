# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
import pytest
from unittest.mock import patch, MagicMock

TEST_ACCOUNT_ID = 1


class TestTasksAPI:

    @pytest.fixture
    def client(self):
        from app.api.app import create_app
        app = create_app({"TESTING": True})
        with app.test_client() as client:
            yield client

    @pytest.fixture(autouse=True)
    def reset_container(self):
        from app.infrastructure.container import reset_container
        reset_container()
        with patch(
            "app.api.routes_learning._resolve_account_id_for_user",
            return_value=TEST_ACCOUNT_ID,
        ):
            yield
        reset_container()

    @pytest.fixture
    def mock_task_repository(self):
        mock_repo = MagicMock()
        mock_repo.get_all.return_value = [
            {
                "id": 1,
                "email_id": "email-123",
                "title": "Review document",
                "description": "Please review the attached document",
                "priority": "high",
                "deadline": "2024-01-15",
                "status": "pending",
                "created_at": "2024-01-10T10:00:00",
                "completed_at": None,
            },
            {
                "id": 2,
                "email_id": "email-456",
                "title": "Send report",
                "description": "Send the monthly report",
                "priority": "medium",
                "deadline": None,
                "status": "pending",
                "created_at": "2024-01-11T10:00:00",
                "completed_at": None,
            },
        ]
        mock_repo.get_by_id.return_value = {
            "id": 1,
            "email_id": "email-123",
            "title": "Review document",
            "description": "Please review the attached document",
            "priority": "high",
            "deadline": "2024-01-15",
            "status": "pending",
            "created_at": "2024-01-10T10:00:00",
            "completed_at": None,
        }
        mock_repo.mark_completed.return_value = True
        return mock_repo

    def test_list_tasks_returns_pending_by_default(self, client, mock_task_repository):
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.get("/api/tasks")

            assert response.status_code == 200
            data = response.get_json()
            assert "tasks" in data
            assert "count" in data
            assert data["count"] == 2
            mock_task_repository.get_all.assert_called_once_with(status="pending", limit=100, account_id=TEST_ACCOUNT_ID)

    def test_list_tasks_with_status_filter(self, client, mock_task_repository):
        mock_task_repository.get_all.return_value = []
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.get("/api/tasks?status=completed")

            assert response.status_code == 200
            data = response.get_json()
            assert data["count"] == 0
            mock_task_repository.get_all.assert_called_once_with(status="completed", limit=100, account_id=TEST_ACCOUNT_ID)

    def test_list_tasks_with_all_status(self, client, mock_task_repository):
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.get("/api/tasks?status=all")

            assert response.status_code == 200
            mock_task_repository.get_all.assert_called_once_with(status="all", limit=100, account_id=TEST_ACCOUNT_ID)

    def test_list_tasks_with_limit(self, client, mock_task_repository):
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.get("/api/tasks?limit=10")

            assert response.status_code == 200
            mock_task_repository.get_all.assert_called_once_with(status="pending", limit=10, account_id=TEST_ACCOUNT_ID)

    def test_get_task_by_id_success(self, client, mock_task_repository):
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.get("/api/tasks/1")

            assert response.status_code == 200
            data = response.get_json()
            assert data["id"] == 1
            assert data["title"] == "Review document"
            mock_task_repository.get_by_id.assert_called_once_with(1, account_id=TEST_ACCOUNT_ID)

    def test_get_task_by_id_not_found(self, client, mock_task_repository):
        mock_task_repository.get_by_id.return_value = None
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.get("/api/tasks/999")

            assert response.status_code == 404
            data = response.get_json()
            assert "error" in data

    def test_update_task_mark_completed(self, client, mock_task_repository):
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.patch(
                "/api/tasks/1",
                json={"status": "completed"},
                content_type="application/json",
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data["success"] is True
            assert data["task_id"] == 1
            assert data["status"] == "completed"
            mock_task_repository.mark_completed.assert_called_once_with(1, account_id=TEST_ACCOUNT_ID)

    def test_update_task_not_found(self, client, mock_task_repository):
        mock_task_repository.mark_completed.return_value = False
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.patch(
                "/api/tasks/999",
                json={"status": "completed"},
                content_type="application/json",
            )

            assert response.status_code == 404
            data = response.get_json()
            assert "error" in data

    def test_update_task_invalid_status(self, client, mock_task_repository):
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.patch(
                "/api/tasks/1",
                json={"status": "invalid_status"},
                content_type="application/json",
            )

            assert response.status_code == 400
            data = response.get_json()
            assert "error" in data

    def test_update_task_missing_body(self, client, mock_task_repository):
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.patch(
                "/api/tasks/1",
                data="",
                content_type="application/json",
            )

            assert response.status_code == 400

    def test_update_task_invalid_json(self, client, mock_task_repository):
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.patch(
                "/api/tasks/1",
                data="not valid json",
                content_type="application/json",
            )

            assert response.status_code == 400

    # ========================================================================
    # Edge Cases - Limit Parameter (with input validation)
    # ========================================================================

    def test_list_tasks_with_zero_limit_returns_400(self, client, mock_task_repository):
        """Test that limit=0 returns 400 (validation rejects values < 1)."""
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.get("/api/tasks?limit=0")

            assert response.status_code == 400
            data = response.get_json()
            assert "error" in data

    def test_list_tasks_with_negative_limit_returns_400(self, client, mock_task_repository):
        """Test that negative limit returns 400 (validation at API level)."""
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.get("/api/tasks?limit=-5")

            assert response.status_code == 400
            data = response.get_json()
            assert "error" in data

    def test_list_tasks_with_large_limit_returns_400(self, client, mock_task_repository):
        """Test that limit > 1000 returns 400 (validation caps limit)."""
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.get("/api/tasks?limit=10000")

            assert response.status_code == 400
            data = response.get_json()
            assert "error" in data

    def test_list_tasks_with_max_valid_limit(self, client, mock_task_repository):
        """Test that limit=1000 is accepted (max valid value)."""
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.get("/api/tasks?limit=1000")

            assert response.status_code == 200
            mock_task_repository.get_all.assert_called_once_with(status="pending", limit=1000, account_id=TEST_ACCOUNT_ID)

    def test_list_tasks_with_non_integer_limit_returns_400(self, client, mock_task_repository):
        """Test that non-integer limit returns 400."""
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.get("/api/tasks?limit=abc")

            # Flask's type=int returns None for invalid int, which triggers validation error
            assert response.status_code == 400
            data = response.get_json()
            assert "error" in data

    # ========================================================================
    # Edge Cases - Status Parameter (with input validation)
    # ========================================================================

    def test_list_tasks_with_invalid_status_returns_400(self, client, mock_task_repository):
        """Test that invalid status returns 400 (validation at API level)."""
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.get("/api/tasks?status=invalid_status")

            assert response.status_code == 400
            data = response.get_json()
            assert "error" in data
            assert "Invalid status" in data["error"]

    def test_list_tasks_with_empty_status_returns_400(self, client, mock_task_repository):
        """Test that empty status string returns 400."""
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.get("/api/tasks?status=")

            assert response.status_code == 400
            data = response.get_json()
            assert "error" in data

    # ========================================================================
    # Edge Cases - Empty Response
    # ========================================================================

    def test_list_tasks_returns_empty_list(self, client, mock_task_repository):
        """Test response format when no tasks are found."""
        mock_task_repository.get_all.return_value = []
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.get("/api/tasks")

            assert response.status_code == 200
            data = response.get_json()
            assert data["tasks"] == []
            assert data["count"] == 0

    # ========================================================================
    # Edge Cases - Task ID
    # ========================================================================

    def test_get_task_with_zero_id(self, client, mock_task_repository):
        """Test getting task with ID 0."""
        mock_task_repository.get_by_id.return_value = None
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.get("/api/tasks/0")

            assert response.status_code == 404
            mock_task_repository.get_by_id.assert_called_once_with(0, account_id=TEST_ACCOUNT_ID)

    def test_get_task_with_negative_id(self, client, mock_task_repository):
        """Test getting task with negative ID (rejected by Flask routing)."""
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.get("/api/tasks/-1")

            # Flask's <int:task_id> rejects negative integers (no route match)
            assert response.status_code == 404

    def test_get_task_with_string_id_returns_404(self, client, mock_task_repository):
        """Test that string ID returns 404 (Flask routing rejects non-int)."""
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.get("/api/tasks/abc")

            # Flask's <int:task_id> rejects non-integer paths
            assert response.status_code == 404

    def test_update_task_with_string_id_returns_404(self, client, mock_task_repository):
        """Test that string ID for PATCH returns 404."""
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.patch(
                "/api/tasks/abc",
                json={"status": "completed"},
                content_type="application/json",
            )

            assert response.status_code == 404

    # ========================================================================
    # Edge Cases - Request Body
    # ========================================================================

    def test_update_task_with_empty_json_object(self, client, mock_task_repository):
        """Test PATCH with empty JSON object {}."""
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.patch(
                "/api/tasks/1",
                json={},
                content_type="application/json",
            )

            # Empty object means no status key -> 400
            assert response.status_code == 400
            data = response.get_json()
            assert "error" in data

    def test_update_task_with_null_status(self, client, mock_task_repository):
        """Test PATCH with null status value."""
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.patch(
                "/api/tasks/1",
                json={"status": None},
                content_type="application/json",
            )

            assert response.status_code == 400
            data = response.get_json()
            assert "error" in data

    def test_update_task_with_extra_fields(self, client, mock_task_repository):
        """Test PATCH with extra fields (should be ignored)."""
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.patch(
                "/api/tasks/1",
                json={"status": "completed", "extra_field": "value", "another": 123},
                content_type="application/json",
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data["success"] is True

    def test_update_task_without_content_type(self, client, mock_task_repository):
        """PATCH without Content-Type → require_json()'s get_json(silent=True)
        yields no dict body, so the route returns 400 (STAB-02: a clean 400
        rather than Flask's default 415-raising)."""
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.patch(
                "/api/tasks/1",
                data='{"status": "completed"}',
                # No content_type specified
            )

            # require_json() uses get_json(silent=True) → 400 "JSON body required".
            assert response.status_code == 400

    # ========================================================================
    # Edge Cases - Response Format
    # ========================================================================

    def test_list_tasks_response_structure(self, client, mock_task_repository):
        """Test the exact structure of list_tasks response."""
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.get("/api/tasks")

            assert response.status_code == 200
            data = response.get_json()
            assert set(data.keys()) == {"tasks", "count"}
            assert isinstance(data["tasks"], list)
            assert isinstance(data["count"], int)

    def test_get_task_response_contains_all_fields(self, client, mock_task_repository):
        """Test that get_task returns all expected fields."""
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.get("/api/tasks/1")

            assert response.status_code == 200
            data = response.get_json()
            expected_fields = {"id", "email_id", "title", "description", "priority",
                              "deadline", "status", "created_at", "completed_at"}
            assert expected_fields.issubset(set(data.keys()))

    def test_update_task_response_structure(self, client, mock_task_repository):
        """Test the exact structure of update_task success response."""
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.patch(
                "/api/tasks/1",
                json={"status": "completed"},
                content_type="application/json",
            )

            assert response.status_code == 200
            data = response.get_json()
            assert set(data.keys()) == {"success", "task_id", "status"}
            assert data["success"] is True
            assert data["task_id"] == 1
            assert data["status"] == "completed"

    # ========================================================================
    # Edge Cases - Combined Parameters
    # ========================================================================

    def test_list_tasks_with_status_and_limit(self, client, mock_task_repository):
        """Test combining status and limit parameters."""
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.get("/api/tasks?status=completed&limit=5")

            assert response.status_code == 200
            mock_task_repository.get_all.assert_called_once_with(status="completed", limit=5, account_id=TEST_ACCOUNT_ID)

    # ========================================================================
    # POST /api/tasks - Create Task
    # ========================================================================

    def test_create_task_success(self, client, mock_task_repository):
        """Test successful task creation with all fields."""
        mock_task_repository.create.return_value = {
            "id": 1,
            "email_id": None,
            "title": "New manual task",
            "description": "Task description",
            "priority": "high",
            "deadline": "2024-02-01",
            "status": "pending",
            "created_at": "2024-01-15T10:00:00",
            "completed_at": None,
        }
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.post(
                "/api/tasks",
                json={
                    "title": "New manual task",
                    "description": "Task description",
                    "priority": "high",
                    "deadline": "2024-02-01",
                },
                content_type="application/json",
            )

            assert response.status_code == 201
            data = response.get_json()
            assert data["id"] == 1
            assert data["title"] == "New manual task"
            assert data["description"] == "Task description"
            assert data["priority"] == "high"
            assert data["deadline"] == "2024-02-01"
            assert data["status"] == "pending"
            mock_task_repository.create.assert_called_once_with(
                title="New manual task",
                description="Task description",
                priority="high",
                deadline="2024-02-01",
                account_id=TEST_ACCOUNT_ID,
            )

    def test_create_task_minimal_fields(self, client, mock_task_repository):
        """Test task creation with only required fields (title)."""
        mock_task_repository.create.return_value = {
            "id": 2,
            "email_id": None,
            "title": "Minimal task",
            "description": None,
            "priority": "medium",
            "deadline": None,
            "status": "pending",
            "created_at": "2024-01-15T10:00:00",
            "completed_at": None,
        }
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.post(
                "/api/tasks",
                json={"title": "Minimal task"},
                content_type="application/json",
            )

            assert response.status_code == 201
            data = response.get_json()
            assert data["id"] == 2
            assert data["title"] == "Minimal task"
            assert data["priority"] == "medium"
            mock_task_repository.create.assert_called_once_with(
                title="Minimal task",
                description=None,
                priority="medium",
                deadline=None,
                account_id=TEST_ACCOUNT_ID,
            )

    def test_create_task_missing_title_returns_400(self, client, mock_task_repository):
        """Test that missing title returns 400."""
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.post(
                "/api/tasks",
                json={"description": "No title provided"},
                content_type="application/json",
            )

            assert response.status_code == 400
            data = response.get_json()
            assert "error" in data
            assert "title" in data["error"].lower()

    def test_create_task_empty_title_returns_400(self, client, mock_task_repository):
        """Test that empty title returns 400."""
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.post(
                "/api/tasks",
                json={"title": ""},
                content_type="application/json",
            )

            assert response.status_code == 400
            data = response.get_json()
            assert "error" in data

    def test_create_task_whitespace_title_returns_400(self, client, mock_task_repository):
        """Test that whitespace-only title returns 400."""
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.post(
                "/api/tasks",
                json={"title": "   "},
                content_type="application/json",
            )

            assert response.status_code == 400
            data = response.get_json()
            assert "error" in data

    def test_create_task_invalid_priority_returns_400(self, client, mock_task_repository):
        """Test that invalid priority returns 400."""
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.post(
                "/api/tasks",
                json={"title": "Task", "priority": "urgent"},
                content_type="application/json",
            )

            assert response.status_code == 400
            data = response.get_json()
            assert "error" in data
            assert "priority" in data["error"].lower()

    def test_create_task_case_insensitive_priority(self, client, mock_task_repository):
        """Test that priority is case-insensitive."""
        mock_task_repository.create.return_value = {
            "id": 3,
            "email_id": None,
            "title": "Task with HIGH priority",
            "description": None,
            "priority": "high",
            "deadline": None,
            "status": "pending",
            "created_at": "2024-01-15T10:00:00",
            "completed_at": None,
        }
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.post(
                "/api/tasks",
                json={"title": "Task with HIGH priority", "priority": "HIGH"},
                content_type="application/json",
            )

            assert response.status_code == 201
            mock_task_repository.create.assert_called_once_with(
                title="Task with HIGH priority",
                description=None,
                priority="high",
                deadline=None,
                account_id=TEST_ACCOUNT_ID,
            )

    def test_create_task_all_priority_values(self, client, mock_task_repository):
        """Test all valid priority values."""
        for priority in ["low", "medium", "high"]:
            mock_task_repository.create.return_value = {
                "id": 1,
                "email_id": None,
                "title": "Task",
                "description": None,
                "priority": priority,
                "deadline": None,
                "status": "pending",
                "created_at": "2024-01-15T10:00:00",
                "completed_at": None,
            }
            with patch("app.api.routes_helpers._get_container") as mock_container:
                mock_container.return_value.get_task_repository.return_value = mock_task_repository

                response = client.post(
                    "/api/tasks",
                    json={"title": "Task", "priority": priority},
                    content_type="application/json",
                )

                assert response.status_code == 201, f"Priority {priority} should be valid"

    def test_create_task_missing_body_returns_400(self, client, mock_task_repository):
        """Test that missing request body returns 400."""
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.post(
                "/api/tasks",
                data="",
                content_type="application/json",
            )

            assert response.status_code == 400

    def test_create_task_invalid_json_returns_400(self, client, mock_task_repository):
        """Test that invalid JSON returns 400."""
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.post(
                "/api/tasks",
                data="not valid json",
                content_type="application/json",
            )

            assert response.status_code == 400

    def test_create_task_response_structure(self, client, mock_task_repository):
        """Test the exact structure of create_task success response."""
        mock_task_repository.create.return_value = {
            "id": 1,
            "email_id": None,
            "title": "Test task",
            "description": "Description",
            "priority": "medium",
            "deadline": "2024-02-01",
            "status": "pending",
            "created_at": "2024-01-15T10:00:00",
            "completed_at": None,
        }
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.post(
                "/api/tasks",
                json={"title": "Test task", "description": "Description", "deadline": "2024-02-01"},
                content_type="application/json",
            )

            assert response.status_code == 201
            data = response.get_json()
            expected_fields = {"id", "email_id", "title", "description", "priority",
                              "deadline", "status", "created_at", "completed_at"}
            assert expected_fields.issubset(set(data.keys()))

    # ========================================================================
    # POST /api/tasks - Additional Edge Cases
    # ========================================================================

    def test_create_task_null_title_returns_400(self, client, mock_task_repository):
        """Test that explicit null title returns 400."""
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.post(
                "/api/tasks",
                json={"title": None, "description": "Some desc"},
                content_type="application/json",
            )

            assert response.status_code == 400
            data = response.get_json()
            assert "error" in data

    def test_create_task_with_unicode_title(self, client, mock_task_repository):
        """Test task creation with unicode characters in title."""
        mock_task_repository.create.return_value = {
            "id": 1,
            "email_id": None,
            "title": "Tâche avec émojis 🚀 et accents éàü",
            "description": None,
            "priority": "medium",
            "deadline": None,
            "status": "pending",
            "created_at": "2024-01-15T10:00:00",
            "completed_at": None,
        }
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.post(
                "/api/tasks",
                json={"title": "Tâche avec émojis 🚀 et accents éàü"},
                content_type="application/json",
            )

            assert response.status_code == 201
            data = response.get_json()
            assert "🚀" in data["title"]
            assert "é" in data["title"]

    def test_create_task_with_max_valid_title_length(self, client, mock_task_repository):
        """Test task creation with max valid title length (500 chars)."""
        long_title = "A" * 500
        mock_task_repository.create.return_value = {
            "id": 1,
            "email_id": None,
            "title": long_title,
            "description": None,
            "priority": "medium",
            "deadline": None,
            "status": "pending",
            "created_at": "2024-01-15T10:00:00",
            "completed_at": None,
        }
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.post(
                "/api/tasks",
                json={"title": long_title},
                content_type="application/json",
            )

            assert response.status_code == 201
            data = response.get_json()
            assert len(data["title"]) == 500

    def test_create_task_with_title_exceeding_max_length_returns_400(self, client):
        """Test that title exceeding 500 chars is rejected."""
        long_title = "A" * 501
        response = client.post(
            "/api/tasks",
            json={"title": long_title},
            content_type="application/json",
        )

        assert response.status_code == 400
        data = response.get_json()
        assert "exceeds maximum length" in data["error"]
        assert "500" in data["error"]

    def test_create_task_with_description_exceeding_max_length_returns_400(self, client):
        """Test that description exceeding 5000 chars is rejected."""
        long_desc = "A" * 5001
        response = client.post(
            "/api/tasks",
            json={"title": "Valid title", "description": long_desc},
            content_type="application/json",
        )

        assert response.status_code == 400
        data = response.get_json()
        assert "Description exceeds maximum length" in data["error"]

    def test_create_task_with_invalid_deadline_format_returns_400(self, client):
        """Test that invalid deadline format is rejected."""
        response = client.post(
            "/api/tasks",
            json={"title": "Task", "deadline": "2024/01/15"},
            content_type="application/json",
        )

        assert response.status_code == 400
        data = response.get_json()
        assert "YYYY-MM-DD" in data["error"]

    def test_create_task_with_invalid_deadline_date_returns_400(self, client):
        """Test that invalid date values are rejected."""
        response = client.post(
            "/api/tasks",
            json={"title": "Task", "deadline": "2024-13-45"},
            content_type="application/json",
        )

        assert response.status_code == 400
        data = response.get_json()
        assert "valid date" in data["error"]

    def test_create_task_with_valid_deadline(self, client, mock_task_repository):
        """Test that valid deadline is accepted."""
        mock_task_repository.create.return_value = {
            "id": 1,
            "email_id": None,
            "title": "Task",
            "description": None,
            "priority": "medium",
            "deadline": "2024-12-31",
            "status": "pending",
            "created_at": "2024-01-15T10:00:00",
            "completed_at": None,
        }
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.post(
                "/api/tasks",
                json={"title": "Task", "deadline": "2024-12-31"},
                content_type="application/json",
            )

            assert response.status_code == 201
            data = response.get_json()
            assert data["deadline"] == "2024-12-31"

    def test_create_task_with_non_string_title_returns_400(self, client):
        """Test that non-string title is rejected."""
        response = client.post(
            "/api/tasks",
            json={"title": 12345},
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_create_task_with_non_string_description_returns_400(self, client):
        """Test that non-string description is rejected."""
        response = client.post(
            "/api/tasks",
            json={"title": "Task", "description": 12345},
            content_type="application/json",
        )

        assert response.status_code == 400
        data = response.get_json()
        assert "Description must be a string" in data["error"]

    def test_create_task_with_null_priority_uses_default(self, client, mock_task_repository):
        """Test that null priority uses default 'medium'."""
        mock_task_repository.create.return_value = {
            "id": 1,
            "email_id": None,
            "title": "Task",
            "description": None,
            "priority": "medium",
            "deadline": None,
            "status": "pending",
            "created_at": "2024-01-15T10:00:00",
            "completed_at": None,
        }
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.post(
                "/api/tasks",
                json={"title": "Task", "priority": None},
                content_type="application/json",
            )

            # Null priority should trigger validation error since None.lower() fails
            # OR it should use default - depends on implementation
            # Current implementation: priority = data.get("priority", "medium")
            # If priority is explicitly None, it won't use default
            assert response.status_code == 400

    def test_create_task_with_explicit_null_description(self, client, mock_task_repository):
        """Test task creation with explicit null description (valid)."""
        mock_task_repository.create.return_value = {
            "id": 1,
            "email_id": None,
            "title": "Task",
            "description": None,
            "priority": "medium",
            "deadline": None,
            "status": "pending",
            "created_at": "2024-01-15T10:00:00",
            "completed_at": None,
        }
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.post(
                "/api/tasks",
                json={"title": "Task", "description": None},
                content_type="application/json",
            )

            assert response.status_code == 201
            data = response.get_json()
            assert data["description"] is None

    def test_create_task_with_explicit_null_deadline(self, client, mock_task_repository):
        """Test task creation with explicit null deadline (valid)."""
        mock_task_repository.create.return_value = {
            "id": 1,
            "email_id": None,
            "title": "Task",
            "description": None,
            "priority": "medium",
            "deadline": None,
            "status": "pending",
            "created_at": "2024-01-15T10:00:00",
            "completed_at": None,
        }
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.post(
                "/api/tasks",
                json={"title": "Task", "deadline": None},
                content_type="application/json",
            )

            assert response.status_code == 201
            data = response.get_json()
            assert data["deadline"] is None

    def test_create_task_without_content_type_returns_400(self, client, mock_task_repository):
        """POST without Content-Type → require_json()'s get_json(silent=True)
        yields no dict body, so the route returns 400 (STAB-02: a clean 400
        rather than Flask's default 415-raising)."""
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.post(
                "/api/tasks",
                data='{"title": "Task"}',
                # No content_type specified
            )

            # require_json() uses get_json(silent=True) → 400 "JSON body required".
            assert response.status_code == 400

    def test_create_task_with_extra_fields_ignores_them(self, client, mock_task_repository):
        """Test that extra fields in request body are ignored."""
        mock_task_repository.create.return_value = {
            "id": 1,
            "email_id": None,
            "title": "Task",
            "description": None,
            "priority": "medium",
            "deadline": None,
            "status": "pending",
            "created_at": "2024-01-15T10:00:00",
            "completed_at": None,
        }
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.post(
                "/api/tasks",
                json={
                    "title": "Task",
                    "extra_field": "ignored",
                    "another_extra": 123,
                    "nested": {"key": "value"},
                },
                content_type="application/json",
            )

            assert response.status_code == 201
            # Verify create was called only with expected params
            mock_task_repository.create.assert_called_once_with(
                title="Task",
                description=None,
                priority="medium",
                deadline=None,
                account_id=TEST_ACCOUNT_ID,
            )

    def test_create_task_repository_exception_propagates(self, client, mock_task_repository):
        """Test that repository exception propagates (unhandled in current implementation).

        Note: This documents current behavior - the endpoint does not catch
        repository exceptions, so Flask's default error handler returns 500.
        A proper implementation should catch and return a JSON error response.
        """
        mock_task_repository.create.side_effect = Exception("Database error")
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            # Exception propagates to Flask, which returns 500
            response = client.post(
                "/api/tasks",
                json={"title": "Task"},
                content_type="application/json",
            )
            assert response.status_code == 500

    def test_create_task_priority_empty_string_returns_400(self, client, mock_task_repository):
        """Test that empty string priority returns 400."""
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.post(
                "/api/tasks",
                json={"title": "Task", "priority": ""},
                content_type="application/json",
            )

            assert response.status_code == 400
            data = response.get_json()
            assert "error" in data
            assert "priority" in data["error"].lower()

    # ========================================================================
    # GET /api/tasks - Additional Edge Cases
    # ========================================================================

    def test_list_tasks_with_explicit_pending_status(self, client, mock_task_repository):
        """Test explicit 'pending' status parameter (not just default)."""
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.get("/api/tasks?status=pending")

            assert response.status_code == 200
            mock_task_repository.get_all.assert_called_once_with(status="pending", limit=100, account_id=TEST_ACCOUNT_ID)

    def test_list_tasks_with_min_valid_limit(self, client, mock_task_repository):
        """Test limit=1 is accepted (minimum valid value)."""
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.get("/api/tasks?limit=1")

            assert response.status_code == 200
            mock_task_repository.get_all.assert_called_once_with(status="pending", limit=1, account_id=TEST_ACCOUNT_ID)

    def test_list_tasks_repository_exception_propagates(self, client, mock_task_repository):
        """Test that repository exception propagates (unhandled in current implementation).

        Note: Documents current behavior - endpoint lacks try/except for repository errors.
        """
        mock_task_repository.get_all.side_effect = Exception("Database error")
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.get("/api/tasks")
            assert response.status_code == 500

    # ========================================================================
    # GET /api/tasks/<id> - Additional Edge Cases
    # ========================================================================

    def test_get_task_repository_exception_propagates(self, client, mock_task_repository):
        """Test that repository exception propagates (unhandled in current implementation).

        Note: Documents current behavior - endpoint lacks try/except for repository errors.
        """
        mock_task_repository.get_by_id.side_effect = Exception("Database error")
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.get("/api/tasks/1")
            assert response.status_code == 500

    def test_get_task_with_very_large_id(self, client, mock_task_repository):
        """Test getting task with a very large ID."""
        mock_task_repository.get_by_id.return_value = None
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.get("/api/tasks/999999999")

            assert response.status_code == 404
            mock_task_repository.get_by_id.assert_called_once_with(999999999, account_id=TEST_ACCOUNT_ID)

    # ========================================================================
    # PATCH /api/tasks/<id> - Additional Edge Cases
    # ========================================================================

    def test_update_task_with_pending_status_returns_400(self, client, mock_task_repository):
        """Test that setting status to 'pending' returns 400 (only completed supported)."""
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.patch(
                "/api/tasks/1",
                json={"status": "pending"},
                content_type="application/json",
            )

            # According to routes.py, only status=completed is supported
            assert response.status_code == 400
            data = response.get_json()
            assert "error" in data

    def test_update_task_repository_exception_propagates(self, client, mock_task_repository):
        """Test that repository exception propagates (unhandled in current implementation).

        Note: Documents current behavior - endpoint lacks try/except for repository errors.
        """
        mock_task_repository.mark_completed.side_effect = Exception("Database error")
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.patch(
                "/api/tasks/1",
                json={"status": "completed"},
                content_type="application/json",
            )
            assert response.status_code == 500

    def test_update_task_with_empty_status_returns_400(self, client, mock_task_repository):
        """Test that empty status string returns 400."""
        with patch("app.api.routes_helpers._get_container") as mock_container:
            mock_container.return_value.get_task_repository.return_value = mock_task_repository

            response = client.patch(
                "/api/tasks/1",
                json={"status": ""},
                content_type="application/json",
            )

            assert response.status_code == 400
            data = response.get_json()
            assert "error" in data
