"""
Tests for learning-related endpoints in app/api/routes.py.

Coverage targets:
- learning_comparisons endpoint (lines 1724-1783)
- trigger_learning endpoint (lines 1832-1841)
- _extract_issues helper (lines 1791-1803)
- _extract_improvements helper (lines 1808-1818)

Copyright (C) 2025 Agentys - All Rights Reserved.
"""

from unittest.mock import Mock, patch
from datetime import datetime, timedelta

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
def admin_auth():
    """Inject an admin JWT context for routes admin-gated by audit H-7
    (`#533`, `/learning/{stats,patterns,comparisons,all}`, `/followups{,/stats}`)
    and the 2026-05-05 follow-up (`/learning/analyze`, `/learning/all`).

    Tests that hit these endpoints expecting 200 must opt-in to admin
    auth via this fixture; the admin gate is the production behaviour
    and the non-admin rejection is covered separately in
    `tests/audit_fixes/test_h_07_routes_learning_cross_tenant.py`."""
    fake_payload = {"sub": "1", "email": "admin@example.com"}
    with patch("app.api.auth._decode_jwt", return_value=fake_payload), \
         patch("app.api.admin._is_admin", return_value=True):
        yield


# ============================================================================
# HELPER FIXTURES
# ============================================================================


def _create_mock_feedback(
    draft_id: str = "draft-123",
    rating: int = 3,
    comment: str = "",
    created_at: str = None,
) -> Mock:
    """Create a mock feedback object."""
    mock = Mock()
    mock.draft_id = draft_id
    mock.rating = rating
    mock.comment = comment
    mock.created_at = created_at or datetime.now().isoformat()
    return mock


def _create_mock_draft(
    draft_id: str = "draft-123",
    email_subject: str = "Test Email",
    content: str = "Test content",
) -> Mock:
    """Create a mock draft object."""
    mock = Mock()
    mock.id = draft_id
    mock.email_subject = email_subject
    mock.content = content
    return mock


# ============================================================================
# TEST _extract_issues HELPER
# ============================================================================


class TestExtractIssuesHelper:
    """Tests for _extract_issues helper function."""

    def test_extract_issues_detects_formal_tone(self):
        """Should detect 'trop formel' issue."""
        from app.api.routes import _extract_issues

        feedback = Mock()
        feedback.comment = "Le ton est trop formel"

        issues = _extract_issues(feedback)

        assert "Ton trop formel" in issues

    def test_extract_issues_detects_too_short(self):
        """Should detect 'trop court' issue."""
        from app.api.routes import _extract_issues

        feedback = Mock()
        feedback.comment = "La réponse est trop courte"

        issues = _extract_issues(feedback)

        assert "Trop court" in issues

    def test_extract_issues_detects_brief(self):
        """Should detect 'bref' as too short issue."""
        from app.api.routes import _extract_issues

        feedback = Mock()
        feedback.comment = "C'est trop bref"

        issues = _extract_issues(feedback)

        assert "Trop court" in issues

    def test_extract_issues_detects_missing_signature(self):
        """Should detect signature issue."""
        from app.api.routes import _extract_issues

        feedback = Mock()
        feedback.comment = "Il manque la signature"

        issues = _extract_issues(feedback)

        assert "Pas de signature" in issues

    def test_extract_issues_detects_generic(self):
        """Should detect generic issue (without accent)."""
        from app.api.routes import _extract_issues

        feedback = Mock()
        feedback.comment = "Réponse trop generique"  # Without accent

        issues = _extract_issues(feedback)

        assert "Trop generique" in issues

    def test_extract_issues_returns_default_when_no_match(self):
        """Should return default issue when no keywords match."""
        from app.api.routes import _extract_issues

        feedback = Mock()
        feedback.comment = "Pas terrible"

        issues = _extract_issues(feedback)

        assert "A ameliorer" in issues
        assert len(issues) == 1

    def test_extract_issues_handles_empty_comment(self):
        """Should handle empty comment gracefully."""
        from app.api.routes import _extract_issues

        feedback = Mock()
        feedback.comment = ""

        issues = _extract_issues(feedback)

        assert "A ameliorer" in issues

    def test_extract_issues_handles_none_comment(self):
        """Should handle None comment gracefully."""
        from app.api.routes import _extract_issues

        feedback = Mock()
        feedback.comment = None

        issues = _extract_issues(feedback)

        assert "A ameliorer" in issues

    def test_extract_issues_detects_multiple_issues(self):
        """Should detect multiple issues in one comment."""
        from app.api.routes import _extract_issues

        feedback = Mock()
        feedback.comment = "Trop formel et trop court, sans signature"

        issues = _extract_issues(feedback)

        assert "Ton trop formel" in issues
        assert "Trop court" in issues
        assert "Pas de signature" in issues
        assert len(issues) == 3

    def test_extract_issues_case_insensitive(self):
        """Should match keywords case-insensitively."""
        from app.api.routes import _extract_issues

        feedback = Mock()
        feedback.comment = "FORMEL et COURT"

        issues = _extract_issues(feedback)

        assert "Ton trop formel" in issues
        assert "Trop court" in issues


# ============================================================================
# TEST _extract_improvements HELPER
# ============================================================================


class TestExtractImprovementsHelper:
    """Tests for _extract_improvements helper function."""

    def test_extract_improvements_detects_personalized(self):
        """Should detect personalization improvement."""
        from app.api.routes import _extract_improvements

        feedback = Mock()
        feedback.comment = "Réponse bien personnalisée"

        improvements = _extract_improvements(feedback)

        assert "Personnalise" in improvements

    def test_extract_improvements_detects_tone(self):
        """Should detect tone improvement."""
        from app.api.routes import _extract_improvements

        feedback = Mock()
        feedback.comment = "Le ton est parfait"

        improvements = _extract_improvements(feedback)

        assert "Ton adapte" in improvements

    def test_extract_improvements_detects_signature(self):
        """Should detect signature improvement."""
        from app.api.routes import _extract_improvements

        feedback = Mock()
        feedback.comment = "Super avec la signature"

        improvements = _extract_improvements(feedback)

        assert "Signature ajoutee" in improvements

    def test_extract_improvements_returns_default_when_no_match(self):
        """Should return default improvement when no keywords match."""
        from app.api.routes import _extract_improvements

        feedback = Mock()
        feedback.comment = "Parfait!"

        improvements = _extract_improvements(feedback)

        assert "Qualite amelioree" in improvements
        assert len(improvements) == 1

    def test_extract_improvements_handles_empty_comment(self):
        """Should handle empty comment gracefully."""
        from app.api.routes import _extract_improvements

        feedback = Mock()
        feedback.comment = ""

        improvements = _extract_improvements(feedback)

        assert "Qualite amelioree" in improvements

    def test_extract_improvements_handles_none_comment(self):
        """Should handle None comment gracefully."""
        from app.api.routes import _extract_improvements

        feedback = Mock()
        feedback.comment = None

        improvements = _extract_improvements(feedback)

        assert "Qualite amelioree" in improvements

    def test_extract_improvements_detects_multiple(self):
        """Should detect multiple improvements."""
        from app.api.routes import _extract_improvements

        feedback = Mock()
        feedback.comment = "Personnalisé avec un bon ton et signature"

        improvements = _extract_improvements(feedback)

        assert "Personnalise" in improvements
        assert "Ton adapte" in improvements
        assert "Signature ajoutee" in improvements
        assert len(improvements) == 3


# ============================================================================
# TEST learning_comparisons ENDPOINT
# ============================================================================


class TestLearningComparisonsEndpoint:
    """Tests for GET /api/learning/comparisons endpoint.

    Note: this route is admin-gated (audit H-7 / `#533`). Each test
    injects an admin JWT via the `admin_auth` fixture; the non-admin
    rejection lives in `tests/audit_fixes/test_h_07_routes_learning_cross_tenant.py`.
    """

    @pytest.fixture(autouse=True)
    def _admin(self, admin_auth):
        return admin_auth

    @patch("app.api.routes_helpers._get_container")
    def test_comparisons_empty_feedback(self, mock_get_container, client):
        """Should return empty comparisons when no feedback."""
        mock_feedback_store = Mock()
        mock_feedback_store.list_all.return_value = []
        mock_draft_store = Mock()

        mock_container = Mock()
        mock_container.get_feedback_store.return_value = mock_feedback_store
        mock_container.get_draft_store.return_value = mock_draft_store
        mock_get_container.return_value = mock_container

        response = client.get(
            "/api/learning/comparisons",
            headers={"Authorization": "Bearer admin-jwt"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["comparisons"] == []
        assert data["improvement_summary"] is None

    @patch("app.api.routes_helpers._get_container")
    def test_comparisons_no_negative_feedback(self, mock_get_container, client):
        """Should return empty comparisons when no negative feedback."""
        positive_feedback = [_create_mock_feedback(rating=5)]
        mock_feedback_store = Mock()
        mock_feedback_store.list_all.return_value = positive_feedback
        mock_draft_store = Mock()

        mock_container = Mock()
        mock_container.get_feedback_store.return_value = mock_feedback_store
        mock_container.get_draft_store.return_value = mock_draft_store
        mock_get_container.return_value = mock_container

        response = client.get(
            "/api/learning/comparisons",
            headers={"Authorization": "Bearer admin-jwt"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["comparisons"] == []

    @patch("app.api.routes_helpers._get_container")
    def test_comparisons_no_positive_feedback(self, mock_get_container, client):
        """Should return empty comparisons when no positive feedback."""
        negative_feedback = [_create_mock_feedback(rating=1)]
        mock_feedback_store = Mock()
        mock_feedback_store.list_all.return_value = negative_feedback
        mock_draft_store = Mock()

        mock_container = Mock()
        mock_container.get_feedback_store.return_value = mock_feedback_store
        mock_container.get_draft_store.return_value = mock_draft_store
        mock_get_container.return_value = mock_container

        response = client.get(
            "/api/learning/comparisons",
            headers={"Authorization": "Bearer admin-jwt"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["comparisons"] == []

    @patch("app.api.routes_helpers._get_container")
    def test_comparisons_with_matching_feedback(self, mock_get_container, client):
        """Should return comparisons when both negative and positive feedback exist."""
        now = datetime.now()
        neg_feedback = _create_mock_feedback(
            draft_id="neg-draft",
            rating=1,
            comment="Trop formel",
            created_at=(now - timedelta(days=10)).isoformat(),
        )
        pos_feedback = _create_mock_feedback(
            draft_id="pos-draft",
            rating=5,
            comment="Personnalisé",
            created_at=now.isoformat(),
        )

        mock_feedback_store = Mock()
        mock_feedback_store.list_all.return_value = [neg_feedback, pos_feedback]

        neg_draft = _create_mock_draft(draft_id="neg-draft", content="Bad content")
        pos_draft = _create_mock_draft(draft_id="pos-draft", content="Good content")

        mock_draft_store = Mock()
        mock_draft_store.get.side_effect = lambda x: neg_draft if x == "neg-draft" else pos_draft

        mock_container = Mock()
        mock_container.get_feedback_store.return_value = mock_feedback_store
        mock_container.get_draft_store.return_value = mock_draft_store
        mock_get_container.return_value = mock_container

        response = client.get(
            "/api/learning/comparisons",
            headers={"Authorization": "Bearer admin-jwt"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert len(data["comparisons"]) == 1
        assert data["comparisons"][0]["id"] == "neg-draft-pos-draft"
        assert data["comparisons"][0]["before"]["score"] == 1
        assert data["comparisons"][0]["after"]["score"] == 5

    @patch("app.api.routes_helpers._get_container")
    def test_comparisons_draft_not_found(self, mock_get_container, client):
        """Should handle draft not found gracefully."""
        datetime.now()
        neg_feedback = _create_mock_feedback(draft_id="missing", rating=1)
        pos_feedback = _create_mock_feedback(draft_id="also-missing", rating=5)

        mock_feedback_store = Mock()
        mock_feedback_store.list_all.return_value = [neg_feedback, pos_feedback]

        mock_draft_store = Mock()
        mock_draft_store.get.return_value = None

        mock_container = Mock()
        mock_container.get_feedback_store.return_value = mock_feedback_store
        mock_container.get_draft_store.return_value = mock_draft_store
        mock_get_container.return_value = mock_container

        response = client.get(
            "/api/learning/comparisons",
            headers={"Authorization": "Bearer admin-jwt"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["comparisons"] == []

    @patch("app.api.routes_helpers._get_container")
    def test_comparisons_improvement_summary_with_enough_feedback(self, mock_get_container, client):
        """Should calculate improvement summary with 5+ feedbacks."""
        feedbacks = [
            _create_mock_feedback(rating=2, created_at="2025-01-01"),
            _create_mock_feedback(rating=2, created_at="2025-01-02"),
            _create_mock_feedback(rating=4, created_at="2025-01-03"),
            _create_mock_feedback(rating=5, created_at="2025-01-04"),
            _create_mock_feedback(rating=5, created_at="2025-01-05"),
        ]

        mock_feedback_store = Mock()
        mock_feedback_store.list_all.return_value = feedbacks

        mock_draft_store = Mock()
        mock_draft_store.get.return_value = None

        mock_container = Mock()
        mock_container.get_feedback_store.return_value = mock_feedback_store
        mock_container.get_draft_store.return_value = mock_draft_store
        mock_get_container.return_value = mock_container

        response = client.get(
            "/api/learning/comparisons",
            headers={"Authorization": "Bearer admin-jwt"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["improvement_summary"] is not None
        assert "average_score_before" in data["improvement_summary"]
        assert "average_score_after" in data["improvement_summary"]
        assert "improvement_percentage" in data["improvement_summary"]

    @patch("app.api.routes_helpers._get_container")
    def test_comparisons_no_summary_with_few_feedbacks(self, mock_get_container, client):
        """Should not calculate summary with fewer than 5 feedbacks."""
        # Use neutral ratings (3) to avoid triggering comparison logic
        feedbacks = [
            _create_mock_feedback(rating=3),
            _create_mock_feedback(rating=3),
        ]

        mock_feedback_store = Mock()
        mock_feedback_store.list_all.return_value = feedbacks

        mock_draft_store = Mock()
        mock_draft_store.get.return_value = None

        mock_container = Mock()
        mock_container.get_feedback_store.return_value = mock_feedback_store
        mock_container.get_draft_store.return_value = mock_draft_store
        mock_get_container.return_value = mock_container

        response = client.get(
            "/api/learning/comparisons",
            headers={"Authorization": "Bearer admin-jwt"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["improvement_summary"] is None

    @patch("app.api.routes_helpers._get_container")
    def test_comparisons_feedback_store_no_list_all(self, mock_get_container, client):
        """Should handle feedback store without list_all method."""
        mock_feedback_store = Mock(spec=[])  # No list_all method
        mock_draft_store = Mock()

        mock_container = Mock()
        mock_container.get_feedback_store.return_value = mock_feedback_store
        mock_container.get_draft_store.return_value = mock_draft_store
        mock_get_container.return_value = mock_container

        response = client.get(
            "/api/learning/comparisons",
            headers={"Authorization": "Bearer admin-jwt"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["comparisons"] == []

    @patch("app.api.routes_helpers._get_container")
    def test_comparisons_extracts_before_after_issues(self, mock_get_container, client):
        """Should extract issues and improvements from feedback comments."""
        now = datetime.now()
        neg_feedback = _create_mock_feedback(
            draft_id="neg-draft",
            rating=1,
            comment="Trop formel et court",
            created_at=(now - timedelta(days=10)).isoformat(),
        )
        pos_feedback = _create_mock_feedback(
            draft_id="pos-draft",
            rating=5,
            comment="Bien personnalisé et ton adapté",
            created_at=now.isoformat(),
        )

        mock_feedback_store = Mock()
        mock_feedback_store.list_all.return_value = [neg_feedback, pos_feedback]

        neg_draft = _create_mock_draft(draft_id="neg-draft")
        pos_draft = _create_mock_draft(draft_id="pos-draft")

        mock_draft_store = Mock()
        mock_draft_store.get.side_effect = lambda x: neg_draft if x == "neg-draft" else pos_draft

        mock_container = Mock()
        mock_container.get_feedback_store.return_value = mock_feedback_store
        mock_container.get_draft_store.return_value = mock_draft_store
        mock_get_container.return_value = mock_container

        response = client.get(
            "/api/learning/comparisons",
            headers={"Authorization": "Bearer admin-jwt"},
        )
        data = response.get_json()

        assert response.status_code == 200
        if data["comparisons"]:
            comparison = data["comparisons"][0]
            assert "issues" in comparison["before"]
            assert "improvements" in comparison["after"]


# ============================================================================
# TEST trigger_learning ENDPOINT
# ============================================================================


class MockInsights:
    """Simple mock class for learning insights."""

    def __init__(self, total_with_feedback: int, avg_rating: float = 3.5):
        self.total_with_feedback = total_with_feedback
        self.avg_rating = avg_rating


class TestTriggerLearningEndpoint:
    """Tests for POST /api/learning/analyze endpoint.

    Note: this route is admin-gated (audit 2026-05-05 follow-up to H-7,
    `#533`). Each test injects an admin JWT via the `admin_auth` fixture
    so we exercise the happy path; non-admin rejection coverage lives
    in `tests/audit_fixes/test_h_07_routes_learning_cross_tenant.py`.
    """

    @pytest.fixture(autouse=True)
    def _admin(self, admin_auth):
        """Auto-apply admin auth to every test in this class."""
        return admin_auth

    @patch("app.api.routes_helpers._get_container")
    def test_trigger_learning_basic(self, mock_get_container, client):
        """Should trigger learning analysis and return results."""
        mock_insights = MockInsights(total_with_feedback=2)

        mock_learning_service = Mock()
        mock_learning_service.analyze_feedback.return_value = mock_insights
        mock_learning_service.extract_patterns.return_value = []
        mock_learning_service.generate_adjustment.return_value = None

        mock_container = Mock()
        mock_container.get_learning_service.return_value = mock_learning_service
        mock_get_container.return_value = mock_container

        response = client.post(
            "/api/learning/analyze",
            headers={"Authorization": "Bearer admin-jwt"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert "insights" in data
        assert data["new_patterns"] == 0
        assert data["new_adjustment"] is False

    @patch("app.api.routes_helpers._get_container")
    def test_trigger_learning_with_patterns(self, mock_get_container, client):
        """Should extract patterns when enough feedback."""
        mock_insights = MockInsights(total_with_feedback=10)

        mock_patterns = [Mock(), Mock(), Mock()]
        mock_adjustment = Mock()

        mock_learning_service = Mock()
        mock_learning_service.analyze_feedback.return_value = mock_insights
        mock_learning_service.extract_patterns.return_value = mock_patterns
        mock_learning_service.generate_adjustment.return_value = mock_adjustment

        mock_container = Mock()
        mock_container.get_learning_service.return_value = mock_learning_service
        mock_get_container.return_value = mock_container

        response = client.post(
            "/api/learning/analyze",
            headers={"Authorization": "Bearer admin-jwt"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["new_patterns"] == 3
        assert data["new_adjustment"] is True

    @patch("app.api.routes_helpers._get_container")
    def test_trigger_learning_not_enough_feedback(self, mock_get_container, client):
        """Should not extract patterns when not enough feedback."""
        mock_insights = MockInsights(total_with_feedback=1)

        mock_learning_service = Mock()
        mock_learning_service.analyze_feedback.return_value = mock_insights

        mock_container = Mock()
        mock_container.get_learning_service.return_value = mock_learning_service
        mock_get_container.return_value = mock_container

        response = client.post(
            "/api/learning/analyze",
            headers={"Authorization": "Bearer admin-jwt"},
        )
        data = response.get_json()

        assert response.status_code == 200
        mock_learning_service.extract_patterns.assert_not_called()
        mock_learning_service.generate_adjustment.assert_not_called()
        assert data["new_patterns"] == 0

    @patch("app.api.routes_helpers._get_container")
    def test_trigger_learning_insights_without_dict(self, mock_get_container, client):
        """Should handle insights object without __dict__."""
        mock_insights = {"total_with_feedback": 5, "avg_rating": 4.0}

        mock_learning_service = Mock()
        mock_learning_service.analyze_feedback.return_value = mock_insights

        mock_container = Mock()
        mock_container.get_learning_service.return_value = mock_learning_service
        mock_get_container.return_value = mock_container

        response = client.post(
            "/api/learning/analyze",
            headers={"Authorization": "Bearer admin-jwt"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["insights"] == mock_insights

    @patch("app.api.routes_helpers._get_container")
    def test_trigger_learning_patterns_none(self, mock_get_container, client):
        """Should handle None patterns gracefully."""
        mock_insights = MockInsights(total_with_feedback=10)

        mock_learning_service = Mock()
        mock_learning_service.analyze_feedback.return_value = mock_insights
        mock_learning_service.extract_patterns.return_value = None
        mock_learning_service.generate_adjustment.return_value = None

        mock_container = Mock()
        mock_container.get_learning_service.return_value = mock_learning_service
        mock_get_container.return_value = mock_container

        response = client.post(
            "/api/learning/analyze",
            headers={"Authorization": "Bearer admin-jwt"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["new_patterns"] == 0
        assert data["new_adjustment"] is False


# ============================================================================
# TEST IMPROVEMENT CALCULATION
# ============================================================================


class TestImprovementCalculation:
    """Note: hits `/learning/comparisons` (admin-gated). Inject admin auth."""

    @pytest.fixture(autouse=True)
    def _admin(self, admin_auth):
        return admin_auth

    """Tests for improvement percentage calculation in learning_comparisons."""

    @patch("app.api.routes_helpers._get_container")
    def test_improvement_with_score_increase(self, mock_get_container, client):
        """Should calculate positive improvement when scores increase."""
        feedbacks = [
            _create_mock_feedback(rating=2),
            _create_mock_feedback(rating=2),
            _create_mock_feedback(rating=4),
            _create_mock_feedback(rating=4),
            _create_mock_feedback(rating=5),
            _create_mock_feedback(rating=5),
        ]

        mock_feedback_store = Mock()
        mock_feedback_store.list_all.return_value = feedbacks
        mock_draft_store = Mock()
        mock_draft_store.get.return_value = None

        mock_container = Mock()
        mock_container.get_feedback_store.return_value = mock_feedback_store
        mock_container.get_draft_store.return_value = mock_draft_store
        mock_get_container.return_value = mock_container

        response = client.get(
            "/api/learning/comparisons",
            headers={"Authorization": "Bearer admin-jwt"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["improvement_summary"] is not None
        # Old: [2, 2, 4] avg=2.67, New: [4, 5, 5] avg=4.67
        assert data["improvement_summary"]["improvement_percentage"] > 0

    @patch("app.api.routes_helpers._get_container")
    def test_improvement_with_score_decrease(self, mock_get_container, client):
        """Should calculate negative improvement when scores decrease."""
        feedbacks = [
            _create_mock_feedback(rating=5),
            _create_mock_feedback(rating=5),
            _create_mock_feedback(rating=5),
            _create_mock_feedback(rating=2),
            _create_mock_feedback(rating=2),
            _create_mock_feedback(rating=2),
        ]

        mock_feedback_store = Mock()
        mock_feedback_store.list_all.return_value = feedbacks
        mock_draft_store = Mock()
        mock_draft_store.get.return_value = None

        mock_container = Mock()
        mock_container.get_feedback_store.return_value = mock_feedback_store
        mock_container.get_draft_store.return_value = mock_draft_store
        mock_get_container.return_value = mock_container

        response = client.get(
            "/api/learning/comparisons",
            headers={"Authorization": "Bearer admin-jwt"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["improvement_summary"] is not None
        assert data["improvement_summary"]["improvement_percentage"] < 0

    @patch("app.api.routes_helpers._get_container")
    def test_improvement_with_same_scores(self, mock_get_container, client):
        """Should return zero improvement when scores are the same."""
        feedbacks = [
            _create_mock_feedback(rating=3),
            _create_mock_feedback(rating=3),
            _create_mock_feedback(rating=3),
            _create_mock_feedback(rating=3),
            _create_mock_feedback(rating=3),
            _create_mock_feedback(rating=3),
        ]

        mock_feedback_store = Mock()
        mock_feedback_store.list_all.return_value = feedbacks
        mock_draft_store = Mock()
        mock_draft_store.get.return_value = None

        mock_container = Mock()
        mock_container.get_feedback_store.return_value = mock_feedback_store
        mock_container.get_draft_store.return_value = mock_draft_store
        mock_get_container.return_value = mock_container

        response = client.get(
            "/api/learning/comparisons",
            headers={"Authorization": "Bearer admin-jwt"},
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["improvement_summary"] is not None
        assert data["improvement_summary"]["improvement_percentage"] == 0
