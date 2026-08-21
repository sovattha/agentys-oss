"""Tests for critique entities.

Story 5-2: CriticAgent Implementation
Task 1: Tests unitaires pour les entities

TDD: RED phase - Write failing tests first
"""

import pytest
from datetime import datetime, timezone
from app.domain.entities.critique import (
    CritiqueDecision,
    CritiqueStatus,
    CritiqueScores,
    CritiqueRequest,
    CritiqueResult,
)


class TestCritiqueDecision:
    """Tests for CritiqueDecision enum."""

    def test_valid_decision_values(self):
        """Test that VALID and REJECT are available."""
        assert CritiqueDecision.VALID.value == "valid"
        assert CritiqueDecision.REJECT.value == "reject"

    def test_decision_from_string(self):
        """Test converting strings to enum."""
        assert CritiqueDecision("valid") == CritiqueDecision.VALID
        assert CritiqueDecision("reject") == CritiqueDecision.REJECT


class TestCritiqueStatus:
    """Tests for CritiqueStatus enum."""

    def test_status_values(self):
        """Test all status values."""
        assert CritiqueStatus.PENDING.value == "pending"
        assert CritiqueStatus.EVALUATING.value == "evaluating"
        assert CritiqueStatus.COMPLETED.value == "completed"
        assert CritiqueStatus.FAILED.value == "failed"
        assert CritiqueStatus.RATE_LIMITED.value == "rate_limited"


class TestCritiqueScores:
    """Tests for CritiqueScores dataclass."""

    def test_valid_scores(self):
        """Test creating valid scores."""
        scores = CritiqueScores(
            coherence=85,
            tone=90,
            completeness=75,
            errors=95,
            conciseness=85,
            over_commitment=90,
            emotional_intelligence=80,
        )
        assert scores.coherence == 85
        assert scores.tone == 90
        assert scores.completeness == 75
        assert scores.errors == 95
        assert scores.conciseness == 85
        assert scores.over_commitment == 90
        assert scores.emotional_intelligence == 80

    def test_calculate_overall_average(self):
        """Test overall score calculation (simple average)."""
        scores = CritiqueScores(
            coherence=80,
            tone=80,
            completeness=80,
            errors=80,
            conciseness=80,
            over_commitment=80,
            emotional_intelligence=80,
        )
        assert scores.calculate_overall() == 80

    def test_calculate_overall_mixed(self):
        """Test overall with mixed scores."""
        scores = CritiqueScores(
            coherence=100,
            tone=50,
            completeness=75,
            errors=75,
            conciseness=60,
            over_commitment=80,
            emotional_intelligence=70,
        )
        # (100 + 50 + 75 + 75 + 60 + 80 + 70) / 7 = 510 / 7 = 72
        assert scores.calculate_overall() == 72

    def test_calculate_weighted(self):
        """Test weighted score calculation."""
        scores = CritiqueScores(
            coherence=100,  # weight 0.25
            tone=50,        # weight 0.15
            completeness=80, # weight 0.20
            errors=60,      # weight 0.10
            conciseness=70,  # weight 0.10
            over_commitment=90,  # weight 0.10
            emotional_intelligence=75,  # weight 0.10
        )
        # 100*0.25 + 50*0.15 + 80*0.20 + 60*0.10 + 70*0.10 + 90*0.10 + 75*0.10
        # = 25 + 7.5 + 16 + 6 + 7 + 9 + 7.5 = 78
        assert scores.calculate_weighted(
            coherence_weight=0.25,
            tone_weight=0.15,
            completeness_weight=0.20,
            errors_weight=0.10,
            conciseness_weight=0.10,
            over_commitment_weight=0.10,
            emotional_intelligence_weight=0.10,
        ) == 78

    def test_get_weak_criteria_all_good(self):
        """Test no weak criteria when all scores are above threshold."""
        scores = CritiqueScores(
            coherence=85,
            tone=90,
            completeness=75,
            errors=95,
            conciseness=80,
            over_commitment=85,
            emotional_intelligence=75,
        )
        assert scores.get_weak_criteria(threshold=70) == []

    def test_get_weak_criteria_some_weak(self):
        """Test detecting weak criteria below threshold."""
        scores = CritiqueScores(
            coherence=85,
            tone=60,  # Below 70
            completeness=50,  # Below 70
            errors=95,
            conciseness=80,
            over_commitment=85,
            emotional_intelligence=75,
        )
        weak = scores.get_weak_criteria(threshold=70)
        assert "tone" in weak
        assert "completeness" in weak
        assert "coherence" not in weak
        assert "errors" not in weak
        assert "conciseness" not in weak
        assert "over_commitment" not in weak
        assert "emotional_intelligence" not in weak

    def test_invalid_score_too_high(self):
        """Test validation rejects scores > 100."""
        with pytest.raises(ValueError) as exc_info:
            CritiqueScores(coherence=150, tone=80, completeness=80, errors=80,
                           conciseness=80, over_commitment=80, emotional_intelligence=80)
        assert "coherence" in str(exc_info.value)

    def test_invalid_score_negative(self):
        """Test validation rejects negative scores."""
        with pytest.raises(ValueError) as exc_info:
            CritiqueScores(coherence=-10, tone=80, completeness=80, errors=80,
                           conciseness=80, over_commitment=80, emotional_intelligence=80)
        assert "coherence" in str(exc_info.value)

    def test_to_dict(self):
        """Test conversion to dictionary."""
        scores = CritiqueScores(
            coherence=85,
            tone=90,
            completeness=75,
            errors=95,
            conciseness=85,
            over_commitment=90,
            emotional_intelligence=80,
        )
        result = scores.to_dict()
        assert result["coherence"] == 85
        assert result["tone"] == 90
        assert result["completeness"] == 75
        assert result["errors"] == 95
        assert result["conciseness"] == 85
        assert result["over_commitment"] == 90
        assert result["emotional_intelligence"] == 80
        assert result["overall"] == 85  # (85+90+75+95+85+90+80)/7 = 600/7 = 85

    def test_from_dict(self):
        """Test creating from dictionary."""
        data = {
            "coherence": 85,
            "tone": 90,
            "completeness": 75,
            "errors": 95,
        }
        scores = CritiqueScores.from_dict(data)
        assert scores.coherence == 85
        assert scores.tone == 90

    def test_from_dict_with_defaults(self):
        """Test from_dict with missing values uses defaults."""
        data = {"coherence": 85}
        scores = CritiqueScores.from_dict(data)
        assert scores.coherence == 85
        assert scores.tone == 50  # default
        assert scores.completeness == 50  # default
        assert scores.errors == 50  # default
        assert scores.conciseness == 50  # default
        assert scores.over_commitment == 50  # default
        assert scores.emotional_intelligence == 50  # default

    def test_create_default(self):
        """Test creating default scores (all 50)."""
        scores = CritiqueScores.create_default()
        assert scores.coherence == 50
        assert scores.tone == 50
        assert scores.completeness == 50
        assert scores.errors == 50
        assert scores.conciseness == 50
        assert scores.over_commitment == 50
        assert scores.emotional_intelligence == 50


class TestCritiqueRequest:
    """Tests for CritiqueRequest dataclass."""

    def test_valid_request(self):
        """Test creating a valid request."""
        request = CritiqueRequest(
            draft_content="Hello, I am responding to your email.",
            original_email="Hi, please send me the report.",
            email_id="email-123",
        )
        assert request.draft_content == "Hello, I am responding to your email."
        assert request.original_email == "Hi, please send me the report."
        assert request.email_id == "email-123"

    def test_empty_draft_content_raises(self):
        """Test that empty draft_content raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            CritiqueRequest(
                draft_content="",
                original_email="Hi, please send me the report.",
            )
        assert "draft_content" in str(exc_info.value)

    def test_empty_original_email_raises(self):
        """Test that empty original_email raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            CritiqueRequest(
                draft_content="Hello, I am responding.",
                original_email="",
            )
        assert "original_email" in str(exc_info.value)

    def test_whitespace_only_raises(self):
        """Test that whitespace-only content raises ValueError."""
        with pytest.raises(ValueError):
            CritiqueRequest(
                draft_content="   ",
                original_email="Valid email",
            )

    def test_optional_fields(self):
        """Test optional fields default to None."""
        request = CritiqueRequest(
            draft_content="Hello",
            original_email="Hi",
        )
        assert request.email_id is None
        assert request.context is None
        assert request.style_context is None
        assert request.expected_tone is None
        assert request.session_id is None

    def test_has_context_true(self):
        """Test has_context returns True when context exists."""
        request = CritiqueRequest(
            draft_content="Hello",
            original_email="Hi",
            context="User wants formal response",
        )
        assert request.has_context() is True

    def test_has_context_false(self):
        """Test has_context returns False when no context."""
        request = CritiqueRequest(
            draft_content="Hello",
            original_email="Hi",
        )
        assert request.has_context() is False

    def test_has_context_empty_string_false(self):
        """Test has_context returns False for empty string."""
        request = CritiqueRequest(
            draft_content="Hello",
            original_email="Hi",
            context="   ",
        )
        assert request.has_context() is False

    def test_to_dict(self):
        """Test conversion to dictionary."""
        request = CritiqueRequest(
            draft_content="Hello",
            original_email="Hi",
            email_id="email-123",
            context="Some context",
        )
        result = request.to_dict()
        assert result["draft_content"] == "Hello"
        assert result["original_email"] == "Hi"
        assert result["email_id"] == "email-123"
        assert result["context"] == "Some context"


class TestCritiqueResult:
    """Tests for CritiqueResult dataclass."""

    @pytest.fixture
    def valid_scores(self):
        """Create valid scores fixture."""
        return CritiqueScores(
            coherence=85,
            tone=90,
            completeness=75,
            errors=95,
            conciseness=85,
            over_commitment=90,
            emotional_intelligence=80,
        )

    def test_valid_result(self, valid_scores):
        """Test creating a valid result."""
        result = CritiqueResult(
            scores=valid_scores,
            decision=CritiqueDecision.VALID,
            suggestions=[],
            explanation="Draft meets quality standards",
        )
        assert result.decision == CritiqueDecision.VALID
        assert result.explanation == "Draft meets quality standards"
        assert result.status == CritiqueStatus.COMPLETED

    def test_is_acceptable_valid_above_threshold(self, valid_scores):
        """Test is_acceptable returns True when VALID and above threshold."""
        result = CritiqueResult(
            scores=valid_scores,  # overall = 85
            decision=CritiqueDecision.VALID,
        )
        assert result.is_acceptable(threshold=70) is True

    def test_is_acceptable_valid_below_threshold(self):
        """Test is_acceptable returns False when below threshold."""
        low_scores = CritiqueScores(
            coherence=50,
            tone=50,
            completeness=50,
            errors=50,
            conciseness=50,
            over_commitment=50,
            emotional_intelligence=50,
        )  # overall = 50
        result = CritiqueResult(
            scores=low_scores,
            decision=CritiqueDecision.VALID,
        )
        assert result.is_acceptable(threshold=70) is False

    def test_is_acceptable_reject_decision(self, valid_scores):
        """Test is_acceptable returns False when decision is REJECT."""
        result = CritiqueResult(
            scores=valid_scores,  # even with good scores
            decision=CritiqueDecision.REJECT,
        )
        assert result.is_acceptable(threshold=70) is False

    def test_is_successful(self, valid_scores):
        """Test is_successful returns True for COMPLETED status."""
        result = CritiqueResult(
            scores=valid_scores,
            decision=CritiqueDecision.VALID,
            status=CritiqueStatus.COMPLETED,
        )
        assert result.is_successful() is True

    def test_is_successful_failed(self, valid_scores):
        """Test is_successful returns False for FAILED status."""
        result = CritiqueResult(
            scores=valid_scores,
            decision=CritiqueDecision.REJECT,
            status=CritiqueStatus.FAILED,
        )
        assert result.is_successful() is False

    def test_was_rate_limited(self, valid_scores):
        """Test was_rate_limited detection."""
        result = CritiqueResult(
            scores=valid_scores,
            decision=CritiqueDecision.REJECT,
            status=CritiqueStatus.RATE_LIMITED,
        )
        assert result.was_rate_limited() is True

    def test_get_overall_score(self, valid_scores):
        """Test get_overall_score shortcut."""
        result = CritiqueResult(
            scores=valid_scores,
            decision=CritiqueDecision.VALID,
        )
        assert result.get_overall_score() == 85

    def test_to_dict(self, valid_scores):
        """Test conversion to dictionary."""
        result = CritiqueResult(
            scores=valid_scores,
            decision=CritiqueDecision.VALID,
            suggestions=["Add greeting"],
            explanation="Good draft",
            evaluation_time_ms=1500,
            tokens_used=100,
        )
        data = result.to_dict()
        assert data["decision"] == "valid"
        assert data["suggestions"] == ["Add greeting"]
        assert data["explanation"] == "Good draft"
        assert data["evaluation_time_ms"] == 1500
        assert data["tokens_used"] == 100
        assert data["overall_score"] == 85
        assert data["is_acceptable"] is True

    def test_string_to_enum_conversion(self, valid_scores):
        """Test that string decision is converted to enum."""
        result = CritiqueResult(
            scores=valid_scores,
            decision="valid",  # string instead of enum
        )
        assert result.decision == CritiqueDecision.VALID

    def test_invalid_decision_string_defaults_to_reject(self, valid_scores):
        """Test unknown decision string defaults to REJECT."""
        result = CritiqueResult(
            scores=valid_scores,
            decision="unknown",
        )
        assert result.decision == CritiqueDecision.REJECT

    def test_negative_evaluation_time_raises(self, valid_scores):
        """Test that negative evaluation_time_ms raises ValueError."""
        with pytest.raises(ValueError):
            CritiqueResult(
                scores=valid_scores,
                decision=CritiqueDecision.VALID,
                evaluation_time_ms=-100,
            )

    def test_create_failed(self):
        """Test create_failed factory method."""
        result = CritiqueResult.create_failed(
            error_message="Connection timeout",
            retry_count=3,
            evaluation_time_ms=5000,
        )
        assert result.status == CritiqueStatus.FAILED
        assert result.decision == CritiqueDecision.REJECT
        assert result.error_message == "Connection timeout"
        assert result.retry_count == 3
        assert result.evaluation_time_ms == 5000
        assert "Unable to evaluate" in result.suggestions[0]

    def test_create_rate_limited(self):
        """Test create_rate_limited factory method."""
        result = CritiqueResult.create_rate_limited(
            retry_count=3,
            evaluation_time_ms=10000,
        )
        assert result.status == CritiqueStatus.RATE_LIMITED
        assert result.decision == CritiqueDecision.REJECT
        assert "Rate limit" in result.error_message

    def test_create_valid(self, valid_scores):
        """Test create_valid factory method."""
        result = CritiqueResult.create_valid(
            scores=valid_scores,
            explanation="Excellent draft",
            evaluation_time_ms=1000,
            tokens_used=50,
        )
        assert result.decision == CritiqueDecision.VALID
        assert result.suggestions == []
        assert result.explanation == "Excellent draft"

    def test_create_reject(self, valid_scores):
        """Test create_reject factory method."""
        result = CritiqueResult.create_reject(
            scores=valid_scores,
            suggestions=["Add salutation", "Fix grammar"],
            explanation="Needs improvement",
            evaluation_time_ms=1500,
            tokens_used=75,
        )
        assert result.decision == CritiqueDecision.REJECT
        assert len(result.suggestions) == 2
        assert "Add salutation" in result.suggestions

    def test_evaluated_at_is_set(self, valid_scores):
        """Test that evaluated_at is automatically set."""
        before = datetime.now(timezone.utc)
        result = CritiqueResult(
            scores=valid_scores,
            decision=CritiqueDecision.VALID,
        )
        after = datetime.now(timezone.utc)
        assert before <= result.evaluated_at <= after
