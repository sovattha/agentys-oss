"""Tests unitaires pour app.domain.entities.orchestration."""

import pytest
from unittest.mock import MagicMock

from app.domain.entities.orchestration import (
    OrchestrationStatus,
    IterationRecord,
    OrchestrationRequest,
    OrchestrationResult,
)
from app.domain.entities.draft_generation import (
    DraftResult,
    DraftStatus,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_draft(content="Bonjour", confidence=0.8, status=DraftStatus.COMPLETED):
    return DraftResult(content=content, confidence=confidence, status=status)


def _make_critique(score=80, decision="valid"):
    """Crée un mock CritiqueResult."""
    from app.domain.entities.critique import CritiqueDecision
    critique = MagicMock()
    critique.scores.calculate_overall.return_value = score
    critique.decision = CritiqueDecision.VALID if decision == "valid" else CritiqueDecision.REJECT
    critique.suggestions = ["Suggestion 1", "Suggestion 2"]
    return critique


def _make_iteration(num=1, score=80, valid=True, duration_ms=500):
    draft = _make_draft()
    critique = _make_critique(score=score, decision="valid" if valid else "reject")
    return IterationRecord(
        draft_result=draft,
        critique_result=critique,
        iteration_number=num,
        duration_ms=duration_ms,
    )


# ── OrchestrationStatus ─────────────────────────────────────────────────────


class TestOrchestrationStatus:
    def test_values(self):
        assert OrchestrationStatus.IN_PROGRESS.value == "in_progress"
        assert OrchestrationStatus.COMPLETED.value == "completed"
        assert OrchestrationStatus.TIMEOUT.value == "timeout"
        assert OrchestrationStatus.FAILED.value == "failed"


# ── IterationRecord ──────────────────────────────────────────────────────────


class TestIterationRecord:
    def test_creation(self):
        draft = _make_draft()
        record = IterationRecord(
            draft_result=draft,
            critique_result=None,
            iteration_number=1,
            duration_ms=100,
        )
        assert record.iteration_number == 1
        assert record.duration_ms == 100

    def test_invalid_iteration_number(self):
        with pytest.raises(ValueError, match="iteration_number must be >= 1"):
            IterationRecord(
                draft_result=_make_draft(),
                critique_result=None,
                iteration_number=0,
                duration_ms=100,
            )

    def test_negative_duration(self):
        with pytest.raises(ValueError, match="duration_ms must be non-negative"):
            IterationRecord(
                draft_result=_make_draft(),
                critique_result=None,
                iteration_number=1,
                duration_ms=-1,
            )

    def test_get_score_with_critique(self):
        record = _make_iteration(score=85)
        assert record.get_score() == 85

    def test_get_score_without_critique(self):
        record = IterationRecord(
            draft_result=_make_draft(),
            critique_result=None,
            iteration_number=1,
            duration_ms=100,
        )
        assert record.get_score() == 0

    def test_is_valid_true(self):
        record = _make_iteration(valid=True)
        assert record.is_valid() is True

    def test_is_valid_false(self):
        record = _make_iteration(valid=False)
        assert record.is_valid() is False

    def test_is_valid_no_critique(self):
        record = IterationRecord(
            draft_result=_make_draft(),
            critique_result=None,
            iteration_number=1,
            duration_ms=100,
        )
        assert record.is_valid() is False

    def test_to_dict(self):
        record = _make_iteration(num=1, score=80)
        d = record.to_dict()
        assert d["iteration_number"] == 1
        assert d["critique_score"] == 80
        assert d["is_valid"] is True
        assert "started_at" in d

    def test_to_dict_truncates_long_draft(self):
        draft = _make_draft(content="x" * 300)
        record = IterationRecord(
            draft_result=draft,
            critique_result=None,
            iteration_number=1,
            duration_ms=0,
        )
        d = record.to_dict()
        assert d["draft_content"].endswith("...")
        assert len(d["draft_content"]) <= 203  # 200 + "..."


# ── OrchestrationRequest ────────────────────────────────────────────────────


class TestOrchestrationRequest:
    def test_creation_basic(self):
        req = OrchestrationRequest(email_content="Hello there")
        assert req.email_content == "Hello there"
        assert req.max_iterations == 2
        assert req.quality_threshold == 70

    def test_empty_content_raises(self):
        with pytest.raises(ValueError, match="email_content cannot be empty"):
            OrchestrationRequest(email_content="")

    def test_whitespace_content_raises(self):
        with pytest.raises(ValueError, match="email_content cannot be empty"):
            OrchestrationRequest(email_content="   ")

    def test_max_iterations_min(self):
        with pytest.raises(ValueError, match="max_iterations must be >= 1"):
            OrchestrationRequest(email_content="test", max_iterations=0)

    def test_max_iterations_max(self):
        with pytest.raises(ValueError, match="max_iterations must be <= 5"):
            OrchestrationRequest(email_content="test", max_iterations=6)

    def test_quality_threshold_range(self):
        with pytest.raises(ValueError, match="quality_threshold must be between"):
            OrchestrationRequest(email_content="test", quality_threshold=-1)
        with pytest.raises(ValueError, match="quality_threshold must be between"):
            OrchestrationRequest(email_content="test", quality_threshold=101)

    def test_timeout_positive(self):
        with pytest.raises(ValueError, match="timeout_seconds must be positive"):
            OrchestrationRequest(email_content="test", timeout_seconds=0)

    def test_iteration_timeout_positive(self):
        with pytest.raises(ValueError, match="iteration_timeout_seconds must be positive"):
            OrchestrationRequest(email_content="test", iteration_timeout_seconds=-1)

    def test_to_dict(self):
        req = OrchestrationRequest(
            email_content="Hello",
            email_id="e1",
            max_iterations=3,
            quality_threshold=80,
        )
        d = req.to_dict()
        assert d["email_id"] == "e1"
        assert d["max_iterations"] == 3
        assert d["quality_threshold"] == 80

    def test_to_dict_truncates_long_content(self):
        req = OrchestrationRequest(email_content="x" * 300)
        d = req.to_dict()
        assert d["email_content"].endswith("...")

    def test_to_draft_request(self):
        req = OrchestrationRequest(
            email_content="Test email",
            instructions="Be polite",
            recipient_email="bob@test.com",
            subject="Re: Hello",
        )
        dr = req.to_draft_request()
        assert dr.email_content == "Test email"
        assert dr.instructions == "Be polite"
        assert dr.recipient_email == "bob@test.com"


# ── OrchestrationResult ─────────────────────────────────────────────────────


class TestOrchestrationResult:
    def test_creation_basic(self):
        draft = _make_draft()
        result = OrchestrationResult(final_draft=draft)
        assert result.status == OrchestrationStatus.COMPLETED
        assert result.total_duration_ms == 0

    def test_negative_duration_raises(self):
        with pytest.raises(ValueError, match="total_duration_ms must be non-negative"):
            OrchestrationResult(
                final_draft=_make_draft(),
                total_duration_ms=-1,
            )

    def test_negative_tokens_raises(self):
        with pytest.raises(ValueError, match="total_tokens_used must be non-negative"):
            OrchestrationResult(
                final_draft=_make_draft(),
                total_tokens_used=-1,
            )

    def test_string_status_converted(self):
        result = OrchestrationResult(
            final_draft=_make_draft(),
            status="completed",
        )
        assert result.status == OrchestrationStatus.COMPLETED

    def test_invalid_string_status_becomes_failed(self):
        result = OrchestrationResult(
            final_draft=_make_draft(),
            status="invalid_status",
        )
        assert result.status == OrchestrationStatus.FAILED

    def test_get_iteration_count(self):
        result = OrchestrationResult(
            final_draft=_make_draft(),
            iterations=[_make_iteration(1), _make_iteration(2)],
        )
        assert result.get_iteration_count() == 2

    def test_get_best_draft_no_iterations(self):
        draft = _make_draft(content="Final")
        result = OrchestrationResult(final_draft=draft)
        assert result.get_best_draft() is draft

    def test_get_best_draft_with_iterations(self):
        it1 = _make_iteration(1, score=60)
        it2 = _make_iteration(2, score=90)
        result = OrchestrationResult(
            final_draft=_make_draft(),
            iterations=[it1, it2],
        )
        best = result.get_best_draft()
        assert best is it2.draft_result

    def test_get_best_score(self):
        result = OrchestrationResult(
            final_draft=_make_draft(),
            iterations=[_make_iteration(1, score=70), _make_iteration(2, score=95)],
        )
        assert result.get_best_score() == 95

    def test_get_best_score_no_iterations(self):
        result = OrchestrationResult(final_draft=_make_draft())
        assert result.get_best_score() == 0

    def test_get_final_score(self):
        result = OrchestrationResult(
            final_draft=_make_draft(),
            iterations=[_make_iteration(1, score=80)],
        )
        assert result.get_final_score() == 80

    def test_was_validated_true(self):
        result = OrchestrationResult(
            final_draft=_make_draft(),
            iterations=[_make_iteration(1, valid=True)],
        )
        assert result.was_validated() is True

    def test_was_validated_false(self):
        result = OrchestrationResult(
            final_draft=_make_draft(),
            iterations=[_make_iteration(1, valid=False)],
        )
        assert result.was_validated() is False

    def test_is_successful(self):
        result = OrchestrationResult(
            final_draft=_make_draft(content="Hello"),
            status=OrchestrationStatus.COMPLETED,
        )
        assert result.is_successful() is True

    def test_is_successful_empty_content(self):
        result = OrchestrationResult(
            final_draft=_make_draft(content="", confidence=0.0),
            status=OrchestrationStatus.COMPLETED,
        )
        assert result.is_successful() is False

    def test_was_timeout(self):
        result = OrchestrationResult(
            final_draft=_make_draft(),
            status=OrchestrationStatus.TIMEOUT,
        )
        assert result.was_timeout() is True

    def test_to_dict(self):
        result = OrchestrationResult(
            final_draft=_make_draft(),
            iterations=[_make_iteration(1)],
            total_duration_ms=1000,
        )
        d = result.to_dict()
        assert d["iteration_count"] == 1
        assert d["total_duration_ms"] == 1000
        assert d["status"] == "completed"
        assert "completed_at" in d

    def test_create_failed(self):
        result = OrchestrationResult.create_failed("Something went wrong")
        assert result.status == OrchestrationStatus.FAILED
        assert result.error_message == "Something went wrong"
        assert result.final_draft is not None

    def test_create_failed_with_iterations_uses_best(self):
        it1 = _make_iteration(1, score=60)
        it2 = _make_iteration(2, score=85)
        result = OrchestrationResult.create_failed(
            "Timeout",
            iterations=[it1, it2],
        )
        assert result.final_draft is it2.draft_result

    def test_create_timeout(self):
        iterations = [_make_iteration(1, score=75)]
        result = OrchestrationResult.create_timeout(
            iterations=iterations,
            total_duration_ms=60000,
        )
        assert result.status == OrchestrationStatus.TIMEOUT
        assert result.final_draft is iterations[0].draft_result

    def test_create_timeout_no_critiques(self):
        draft = _make_draft()
        it = IterationRecord(
            draft_result=draft,
            critique_result=None,
            iteration_number=1,
            duration_ms=100,
        )
        result = OrchestrationResult.create_timeout(
            iterations=[it],
            total_duration_ms=5000,
        )
        assert result.final_draft is draft

    def test_create_timeout_empty_iterations(self):
        result = OrchestrationResult.create_timeout(
            iterations=[],
            total_duration_ms=5000,
        )
        assert result.final_draft is not None
        assert result.final_draft.status == DraftStatus.FAILED
