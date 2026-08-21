"""Tests unitaires pour les endpoints /api/analytics/*."""

from unittest.mock import Mock, patch

import pytest


@pytest.fixture
def app():
    from app.api.app import create_app

    app = create_app(config={"TESTING": True})
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    class _AdminClient:
        def __init__(self, raw_client):
            self._raw_client = raw_client

        @staticmethod
        def _headers(kwargs):
            headers = dict(kwargs.pop("headers", {}) or {})
            headers.setdefault("Authorization", "Bearer admin-jwt")
            kwargs["headers"] = headers
            return kwargs

        def get(self, *args, **kwargs):
            return self._raw_client.get(*args, **self._headers(kwargs))

        def post(self, *args, **kwargs):
            return self._raw_client.post(*args, **self._headers(kwargs))

        def put(self, *args, **kwargs):
            return self._raw_client.put(*args, **self._headers(kwargs))

        def delete(self, *args, **kwargs):
            return self._raw_client.delete(*args, **self._headers(kwargs))

        def head(self, *args, **kwargs):
            return self._raw_client.head(*args, **self._headers(kwargs))

    with patch("app.api.auth._decode_jwt", return_value={"sub": "1", "email": "admin@example.com"}), \
         patch("app.api.admin._is_admin", return_value=True):
        yield _AdminClient(app.test_client())


class TestAnalyticsQualityEndpoint:

    @patch("app.api.routes_helpers._get_container")
    def test_get_quality_metrics_success(self, mock_get_container, client):
        mock_analytics = Mock()
        mock_analytics.get_quality_metrics.return_value = {
            "avg_score": 85.5,
            "total_drafts": 42,
            "by_level": {"excellent": 10, "good": 25, "needs_improvement": 7},
        }
        mock_container = Mock()
        mock_container.get_analytics.return_value = mock_analytics
        mock_get_container.return_value = mock_container

        response = client.get("/api/analytics/quality")
        data = response.get_json()

        assert response.status_code == 200
        assert data["avg_score"] == 85.5
        assert data["total_drafts"] == 42
        assert "by_level" in data
        mock_analytics.get_quality_metrics.assert_called_once()

    @patch("app.api.routes_helpers._get_container")
    def test_get_quality_metrics_internal_error(self, mock_get_container, client):
        mock_analytics = Mock()
        mock_analytics.get_quality_metrics.side_effect = Exception("Database error")
        mock_container = Mock()
        mock_container.get_analytics.return_value = mock_analytics
        mock_get_container.return_value = mock_container

        # Flask test client ne propage PAS les exceptions par défaut sous
        # TESTING=True (PROPAGATE_EXCEPTIONS=None) — le handler global catche
        # et retourne 500 + JSON {success: false, code, error}. Le test
        # original attendait à tort un pytest.raises (DID NOT RAISE).
        response = client.get("/api/analytics/quality")
        assert response.status_code == 500
        data = response.get_json()
        assert data["success"] is False
        assert data["code"] == "INTERNAL_ERROR"

    def test_get_quality_metrics_method_not_allowed_post(self, client):
        response = client.post("/api/analytics/quality")

        assert response.status_code == 405

    def test_get_quality_metrics_method_not_allowed_put(self, client):
        response = client.put("/api/analytics/quality")

        assert response.status_code == 405

    def test_get_quality_metrics_method_not_allowed_delete(self, client):
        response = client.delete("/api/analytics/quality")

        assert response.status_code == 405

    @patch("app.api.routes_helpers._get_container")
    def test_get_quality_metrics_response_content_type(
        self, mock_get_container, client
    ):
        mock_analytics = Mock()
        mock_analytics.get_quality_metrics.return_value = {"avg_score": 0}
        mock_container = Mock()
        mock_container.get_analytics.return_value = mock_analytics
        mock_get_container.return_value = mock_container

        response = client.get("/api/analytics/quality")

        assert response.content_type == "application/json"

    @patch("app.api.routes_helpers._get_container")
    def test_get_quality_metrics_empty_response(self, mock_get_container, client):
        mock_analytics = Mock()
        mock_analytics.get_quality_metrics.return_value = {}
        mock_container = Mock()
        mock_container.get_analytics.return_value = mock_analytics
        mock_get_container.return_value = mock_container

        response = client.get("/api/analytics/quality")
        data = response.get_json()

        assert response.status_code == 200
        assert data == {}

    @patch("app.api.routes_helpers._get_container")
    def test_get_quality_metrics_with_null_values(self, mock_get_container, client):
        """Test avec des valeurs nulles dans la réponse."""
        mock_analytics = Mock()
        mock_analytics.get_quality_metrics.return_value = {
            "avg_score": None,
            "total_drafts": 0,
            "by_level": None,
        }
        mock_container = Mock()
        mock_container.get_analytics.return_value = mock_analytics
        mock_get_container.return_value = mock_container

        response = client.get("/api/analytics/quality")
        data = response.get_json()

        assert response.status_code == 200
        assert data["avg_score"] is None
        assert data["total_drafts"] == 0
        assert data["by_level"] is None

    @patch("app.api.routes_helpers._get_container")
    def test_get_quality_metrics_with_zero_values(self, mock_get_container, client):
        """Test avec des valeurs à zéro (cas limite)."""
        mock_analytics = Mock()
        mock_analytics.get_quality_metrics.return_value = {
            "avg_score": 0.0,
            "total_drafts": 0,
            "by_level": {"excellent": 0, "good": 0, "needs_improvement": 0},
        }
        mock_container = Mock()
        mock_container.get_analytics.return_value = mock_analytics
        mock_get_container.return_value = mock_container

        response = client.get("/api/analytics/quality")
        data = response.get_json()

        assert response.status_code == 200
        assert data["avg_score"] == 0.0
        assert data["total_drafts"] == 0

    @patch("app.api.routes_helpers._get_container")
    def test_get_quality_metrics_large_numbers(self, mock_get_container, client):
        """Test avec des valeurs très grandes."""
        mock_analytics = Mock()
        mock_analytics.get_quality_metrics.return_value = {
            "avg_score": 100.0,
            "total_drafts": 1_000_000,
            "by_level": {"excellent": 500_000, "good": 300_000, "needs_improvement": 200_000},
        }
        mock_container = Mock()
        mock_container.get_analytics.return_value = mock_analytics
        mock_get_container.return_value = mock_container

        response = client.get("/api/analytics/quality")
        data = response.get_json()

        assert response.status_code == 200
        assert data["total_drafts"] == 1_000_000

    def test_get_quality_metrics_head_method(self, client):
        """Test que HEAD est supporté (implicitement via GET)."""
        response = client.head("/api/analytics/quality")

        # HEAD devrait retourner 200 ou 405 selon l'implémentation Flask
        assert response.status_code in [200, 405]

    @patch("app.api.routes_helpers._get_container")
    def test_get_quality_metrics_with_nested_data(self, mock_get_container, client):
        """Test avec des données imbriquées complexes."""
        mock_analytics = Mock()
        mock_analytics.get_quality_metrics.return_value = {
            "avg_score": 85.5,
            "total_drafts": 100,
            "by_level": {
                "excellent": {"count": 30, "percentage": 30.0},
                "good": {"count": 50, "percentage": 50.0},
                "needs_improvement": {"count": 20, "percentage": 20.0},
            },
            "metadata": {"last_updated": "2025-01-02T10:00:00Z"},
        }
        mock_container = Mock()
        mock_container.get_analytics.return_value = mock_analytics
        mock_get_container.return_value = mock_container

        response = client.get("/api/analytics/quality")
        data = response.get_json()

        assert response.status_code == 200
        assert "metadata" in data
        assert data["by_level"]["excellent"]["count"] == 30


class TestAnalyticsComparisonEndpoint:

    @patch("app.api.routes_helpers._get_container")
    def test_get_comparison_success(self, mock_get_container, client):
        mock_analytics = Mock()
        mock_analytics.get_ai_vs_human_comparison.return_value = {
            "edit_rate": 0.35,
            "avg_edit_ratio": 0.12,
            "common_changes": ["tone", "formatting", "spelling"],
        }
        mock_container = Mock()
        mock_container.get_analytics.return_value = mock_analytics
        mock_get_container.return_value = mock_container

        response = client.get("/api/analytics/comparison")
        data = response.get_json()

        assert response.status_code == 200
        assert data["edit_rate"] == 0.35
        assert data["avg_edit_ratio"] == 0.12
        assert "common_changes" in data
        mock_analytics.get_ai_vs_human_comparison.assert_called_once()

    @patch("app.api.routes_helpers._get_container")
    def test_get_comparison_internal_error(self, mock_get_container, client):
        mock_analytics = Mock()
        mock_analytics.get_ai_vs_human_comparison.side_effect = Exception(
            "Service unavailable"
        )
        mock_container = Mock()
        mock_container.get_analytics.return_value = mock_analytics
        mock_get_container.return_value = mock_container

        # cf. test_get_quality_metrics_internal_error — Flask catche l'exception
        # et retourne 500 + JSON, ne propage pas vers pytest.
        response = client.get("/api/analytics/comparison")
        assert response.status_code == 500
        data = response.get_json()
        assert data["success"] is False
        assert data["code"] == "INTERNAL_ERROR"

    def test_get_comparison_method_not_allowed_post(self, client):
        response = client.post("/api/analytics/comparison")

        assert response.status_code == 405

    def test_get_comparison_method_not_allowed_put(self, client):
        response = client.put("/api/analytics/comparison")

        assert response.status_code == 405

    def test_get_comparison_method_not_allowed_delete(self, client):
        response = client.delete("/api/analytics/comparison")

        assert response.status_code == 405

    @patch("app.api.routes_helpers._get_container")
    def test_get_comparison_response_content_type(self, mock_get_container, client):
        mock_analytics = Mock()
        mock_analytics.get_ai_vs_human_comparison.return_value = {"edit_rate": 0}
        mock_container = Mock()
        mock_container.get_analytics.return_value = mock_analytics
        mock_get_container.return_value = mock_container

        response = client.get("/api/analytics/comparison")

        assert response.content_type == "application/json"

    @patch("app.api.routes_helpers._get_container")
    def test_get_comparison_empty_response(self, mock_get_container, client):
        mock_analytics = Mock()
        mock_analytics.get_ai_vs_human_comparison.return_value = {}
        mock_container = Mock()
        mock_container.get_analytics.return_value = mock_analytics
        mock_get_container.return_value = mock_container

        response = client.get("/api/analytics/comparison")
        data = response.get_json()

        assert response.status_code == 200
        assert data == {}

    @patch("app.api.routes_helpers._get_container")
    def test_get_comparison_with_null_values(self, mock_get_container, client):
        """Test avec des valeurs nulles dans la réponse."""
        mock_analytics = Mock()
        mock_analytics.get_ai_vs_human_comparison.return_value = {
            "edit_rate": None,
            "avg_edit_ratio": None,
            "common_changes": None,
        }
        mock_container = Mock()
        mock_container.get_analytics.return_value = mock_analytics
        mock_get_container.return_value = mock_container

        response = client.get("/api/analytics/comparison")
        data = response.get_json()

        assert response.status_code == 200
        assert data["edit_rate"] is None
        assert data["common_changes"] is None

    @patch("app.api.routes_helpers._get_container")
    def test_get_comparison_with_zero_values(self, mock_get_container, client):
        """Test avec des valeurs à zéro (aucune modification humaine)."""
        mock_analytics = Mock()
        mock_analytics.get_ai_vs_human_comparison.return_value = {
            "edit_rate": 0.0,
            "avg_edit_ratio": 0.0,
            "common_changes": [],
        }
        mock_container = Mock()
        mock_container.get_analytics.return_value = mock_analytics
        mock_get_container.return_value = mock_container

        response = client.get("/api/analytics/comparison")
        data = response.get_json()

        assert response.status_code == 200
        assert data["edit_rate"] == 0.0
        assert data["common_changes"] == []

    @patch("app.api.routes_helpers._get_container")
    def test_get_comparison_with_max_edit_rate(self, mock_get_container, client):
        """Test avec taux de modification à 100%."""
        mock_analytics = Mock()
        mock_analytics.get_ai_vs_human_comparison.return_value = {
            "edit_rate": 1.0,
            "avg_edit_ratio": 0.95,
            "common_changes": ["complete_rewrite"],
        }
        mock_container = Mock()
        mock_container.get_analytics.return_value = mock_analytics
        mock_get_container.return_value = mock_container

        response = client.get("/api/analytics/comparison")
        data = response.get_json()

        assert response.status_code == 200
        assert data["edit_rate"] == 1.0

    def test_get_comparison_head_method(self, client):
        """Test que HEAD est supporté (implicitement via GET)."""
        response = client.head("/api/analytics/comparison")

        # HEAD devrait retourner 200 ou 405 selon l'implémentation Flask
        assert response.status_code in [200, 405]

    @patch("app.api.routes_helpers._get_container")
    def test_get_comparison_with_many_common_changes(self, mock_get_container, client):
        """Test avec une longue liste de types de modifications."""
        mock_analytics = Mock()
        mock_analytics.get_ai_vs_human_comparison.return_value = {
            "edit_rate": 0.75,
            "avg_edit_ratio": 0.30,
            "common_changes": [
                "tone", "formatting", "spelling", "grammar",
                "content_addition", "content_removal", "restructuring",
                "politeness", "clarity", "brevity",
            ],
        }
        mock_container = Mock()
        mock_container.get_analytics.return_value = mock_analytics
        mock_get_container.return_value = mock_container

        response = client.get("/api/analytics/comparison")
        data = response.get_json()

        assert response.status_code == 200
        assert len(data["common_changes"]) == 10

    @patch("app.api.routes_helpers._get_container")
    def test_get_comparison_with_nested_data(self, mock_get_container, client):
        """Test avec des données imbriquées complexes."""
        mock_analytics = Mock()
        mock_analytics.get_ai_vs_human_comparison.return_value = {
            "edit_rate": 0.45,
            "avg_edit_ratio": 0.20,
            "common_changes": ["tone", "formatting"],
            "breakdown": {
                "by_category": {
                    "professional": {"edit_rate": 0.30},
                    "casual": {"edit_rate": 0.60},
                },
            },
        }
        mock_container = Mock()
        mock_container.get_analytics.return_value = mock_analytics
        mock_get_container.return_value = mock_container

        response = client.get("/api/analytics/comparison")
        data = response.get_json()

        assert response.status_code == 200
        assert "breakdown" in data
        assert data["breakdown"]["by_category"]["professional"]["edit_rate"] == 0.30
