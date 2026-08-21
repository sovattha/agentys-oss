"""Tests pour les entités d'orchestration.

Story 5-3: Draft Regeneration Loop
Task 1: Tests unitaires pour OrchestrationRequest, OrchestrationResult, IterationRecord.
"""

import pytest

from app.domain.entities.orchestration import (
    OrchestrationStatus,
    IterationRecord,
    OrchestrationRequest,
    OrchestrationResult,
)
from app.domain.entities.draft_generation import (
    DraftResult,
    DraftStatus,
    DraftTone,
)
from app.domain.entities.critique import (
    CritiqueResult,
    CritiqueDecision,
    CritiqueScores,
)


class TestOrchestrationStatus:
    """Tests pour l'enum OrchestrationStatus."""

    def test_values(self):
        """Vérifie toutes les valeurs de l'enum."""
        assert OrchestrationStatus.IN_PROGRESS.value == "in_progress"
        assert OrchestrationStatus.COMPLETED.value == "completed"
        assert OrchestrationStatus.TIMEOUT.value == "timeout"
        assert OrchestrationStatus.FAILED.value == "failed"

    def test_from_string(self):
        """Vérifie la conversion depuis une chaîne."""
        assert OrchestrationStatus("in_progress") == OrchestrationStatus.IN_PROGRESS
        assert OrchestrationStatus("completed") == OrchestrationStatus.COMPLETED


class TestIterationRecord:
    """Tests pour IterationRecord."""

    @pytest.fixture
    def sample_draft_result(self):
        """Crée un DraftResult de test."""
        return DraftResult(
            content="This is a test draft response.",
            confidence=0.85,
            tone_detected=DraftTone.PROFESSIONAL,
            generation_time_ms=1500,
            tokens_used=250,
            status=DraftStatus.COMPLETED,
        )

    @pytest.fixture
    def sample_critique_result(self):
        """Crée un CritiqueResult de test."""
        scores = CritiqueScores(coherence=80, tone=85, completeness=75, errors=90, conciseness=80, over_commitment=85, emotional_intelligence=75)
        return CritiqueResult(
            scores=scores,
            decision=CritiqueDecision.VALID,
            suggestions=[],
            explanation="Good draft",
            evaluation_time_ms=800,
            tokens_used=150,
        )

    def test_creation_minimal(self, sample_draft_result):
        """Test création avec paramètres minimum."""
        record = IterationRecord(
            draft_result=sample_draft_result,
            critique_result=None,
            iteration_number=1,
            duration_ms=2000,
        )
        assert record.iteration_number == 1
        assert record.duration_ms == 2000
        assert record.critique_result is None

    def test_creation_with_critique(self, sample_draft_result, sample_critique_result):
        """Test création avec critique."""
        record = IterationRecord(
            draft_result=sample_draft_result,
            critique_result=sample_critique_result,
            iteration_number=2,
            duration_ms=2500,
        )
        assert record.iteration_number == 2
        assert record.critique_result is not None
        assert record.get_score() == 81  # (80+85+75+90+80+85+75)//7

    def test_invalid_iteration_number(self, sample_draft_result):
        """Test validation iteration_number >= 1."""
        with pytest.raises(ValueError, match="iteration_number must be >= 1"):
            IterationRecord(
                draft_result=sample_draft_result,
                critique_result=None,
                iteration_number=0,
                duration_ms=1000,
            )

    def test_invalid_duration(self, sample_draft_result):
        """Test validation duration_ms >= 0."""
        with pytest.raises(ValueError, match="duration_ms must be non-negative"):
            IterationRecord(
                draft_result=sample_draft_result,
                critique_result=None,
                iteration_number=1,
                duration_ms=-100,
            )

    def test_get_score_with_critique(self, sample_draft_result, sample_critique_result):
        """Test get_score() avec critique présente."""
        record = IterationRecord(
            draft_result=sample_draft_result,
            critique_result=sample_critique_result,
            iteration_number=1,
            duration_ms=2000,
        )
        assert record.get_score() == 81

    def test_get_score_without_critique(self, sample_draft_result):
        """Test get_score() sans critique."""
        record = IterationRecord(
            draft_result=sample_draft_result,
            critique_result=None,
            iteration_number=1,
            duration_ms=2000,
        )
        assert record.get_score() == 0

    def test_is_valid_with_valid_critique(self, sample_draft_result, sample_critique_result):
        """Test is_valid() avec critique VALID."""
        record = IterationRecord(
            draft_result=sample_draft_result,
            critique_result=sample_critique_result,
            iteration_number=1,
            duration_ms=2000,
        )
        assert record.is_valid() is True

    def test_is_valid_with_reject_critique(self, sample_draft_result):
        """Test is_valid() avec critique REJECT."""
        scores = CritiqueScores(coherence=50, tone=60, completeness=55, errors=70, conciseness=60, over_commitment=55, emotional_intelligence=50)
        critique = CritiqueResult(
            scores=scores,
            decision=CritiqueDecision.REJECT,
            suggestions=["Improve coherence"],
            explanation="Needs work",
        )
        record = IterationRecord(
            draft_result=sample_draft_result,
            critique_result=critique,
            iteration_number=1,
            duration_ms=2000,
        )
        assert record.is_valid() is False

    def test_is_valid_without_critique(self, sample_draft_result):
        """Test is_valid() sans critique."""
        record = IterationRecord(
            draft_result=sample_draft_result,
            critique_result=None,
            iteration_number=1,
            duration_ms=2000,
        )
        assert record.is_valid() is False

    def test_to_dict(self, sample_draft_result, sample_critique_result):
        """Test sérialisation to_dict()."""
        record = IterationRecord(
            draft_result=sample_draft_result,
            critique_result=sample_critique_result,
            iteration_number=1,
            duration_ms=2000,
        )
        d = record.to_dict()
        assert d["iteration_number"] == 1
        assert d["duration_ms"] == 2000
        assert d["critique_score"] == 81
        assert d["critique_decision"] == "valid"
        assert d["is_valid"] is True
        assert "started_at" in d


class TestOrchestrationRequest:
    """Tests pour OrchestrationRequest."""

    def test_creation_minimal(self):
        """Test création avec email_content uniquement."""
        request = OrchestrationRequest(email_content="Test email content")
        assert request.email_content == "Test email content"
        assert request.max_iterations == 2
        assert request.quality_threshold == 70
        assert request.timeout_seconds == 240
        assert request.iteration_timeout_seconds == 60

    def test_creation_with_all_params(self):
        """Test création avec tous les paramètres."""
        request = OrchestrationRequest(
            email_content="Test email",
            email_id="email-123",
            instructions="Be formal",
            style_context="Professional style",
            max_iterations=3,
            quality_threshold=80,
            timeout_seconds=180,
            iteration_timeout_seconds=45,
            session_id="session-456",
            recipient_email="test@example.com",
            subject="Test Subject",
            account_id=1,
        )
        assert request.email_id == "email-123"
        assert request.max_iterations == 3
        assert request.quality_threshold == 80
        assert request.timeout_seconds == 180

    def test_empty_email_content(self):
        """Test validation email_content non vide."""
        with pytest.raises(ValueError, match="email_content cannot be empty"):
            OrchestrationRequest(email_content="")

    def test_whitespace_email_content(self):
        """Test validation email_content pas seulement espaces."""
        with pytest.raises(ValueError, match="email_content cannot be empty"):
            OrchestrationRequest(email_content="   ")

    def test_invalid_max_iterations_zero(self):
        """Test validation max_iterations >= 1."""
        with pytest.raises(ValueError, match="max_iterations must be >= 1"):
            OrchestrationRequest(email_content="Test", max_iterations=0)

    def test_invalid_max_iterations_too_high(self):
        """Test validation max_iterations <= 5."""
        with pytest.raises(ValueError, match="max_iterations must be <= 5"):
            OrchestrationRequest(email_content="Test", max_iterations=10)

    def test_invalid_quality_threshold_negative(self):
        """Test validation quality_threshold >= 0."""
        with pytest.raises(ValueError, match="quality_threshold must be between"):
            OrchestrationRequest(email_content="Test", quality_threshold=-10)

    def test_invalid_quality_threshold_over_100(self):
        """Test validation quality_threshold <= 100."""
        with pytest.raises(ValueError, match="quality_threshold must be between"):
            OrchestrationRequest(email_content="Test", quality_threshold=150)

    def test_invalid_timeout_seconds(self):
        """Test validation timeout_seconds > 0."""
        with pytest.raises(ValueError, match="timeout_seconds must be positive"):
            OrchestrationRequest(email_content="Test", timeout_seconds=0)

    def test_invalid_iteration_timeout(self):
        """Test validation iteration_timeout_seconds > 0."""
        with pytest.raises(ValueError, match="iteration_timeout_seconds must be positive"):
            OrchestrationRequest(email_content="Test", iteration_timeout_seconds=0)

    def test_to_draft_request(self):
        """Test conversion to_draft_request()."""
        request = OrchestrationRequest(
            email_content="Test email",
            instructions="Be formal",
            style_context="Professional",
            recipient_email="test@example.com",
            subject="Subject",
            account_id=1,
            session_id="session-123",
        )
        draft_request = request.to_draft_request()

        assert draft_request.email_content == "Test email"
        assert draft_request.instructions == "Be formal"
        assert draft_request.style_context == "Professional"
        assert draft_request.recipient_email == "test@example.com"
        assert draft_request.subject == "Subject"
        assert draft_request.session_id == "session-123"

    def test_to_dict(self):
        """Test sérialisation to_dict()."""
        request = OrchestrationRequest(
            email_content="Test email content",
            email_id="email-123",
            max_iterations=2,
        )
        d = request.to_dict()
        assert d["email_id"] == "email-123"
        assert d["max_iterations"] == 2
        assert d["quality_threshold"] == 70
        assert "has_context" in d


class TestOrchestrationResult:
    """Tests pour OrchestrationResult."""

    @pytest.fixture
    def sample_draft_result(self):
        """Crée un DraftResult de test."""
        return DraftResult(
            content="Final draft content",
            confidence=0.85,
            generation_time_ms=1500,
            tokens_used=250,
            status=DraftStatus.COMPLETED,
        )

    @pytest.fixture
    def sample_iteration_valid(self, sample_draft_result):
        """Crée une iteration avec critique VALID."""
        scores = CritiqueScores(coherence=85, tone=90, completeness=80, errors=95, conciseness=85, over_commitment=90, emotional_intelligence=80)
        critique = CritiqueResult(
            scores=scores,
            decision=CritiqueDecision.VALID,
            suggestions=[],
            explanation="Excellent draft",
        )
        return IterationRecord(
            draft_result=sample_draft_result,
            critique_result=critique,
            iteration_number=1,
            duration_ms=2500,
        )

    @pytest.fixture
    def sample_iteration_reject(self):
        """Crée une iteration avec critique REJECT."""
        draft = DraftResult(
            content="Draft needing improvement",
            confidence=0.6,
            generation_time_ms=1200,
            tokens_used=200,
        )
        scores = CritiqueScores(coherence=55, tone=60, completeness=50, errors=70, conciseness=55, over_commitment=60, emotional_intelligence=50)
        critique = CritiqueResult(
            scores=scores,
            decision=CritiqueDecision.REJECT,
            suggestions=["Improve coherence", "Address all questions"],
            explanation="Needs improvement",
        )
        return IterationRecord(
            draft_result=draft,
            critique_result=critique,
            iteration_number=1,
            duration_ms=2000,
        )

    def test_creation_minimal(self, sample_draft_result):
        """Test création minimale."""
        result = OrchestrationResult(final_draft=sample_draft_result)
        assert result.final_draft == sample_draft_result
        assert result.status == OrchestrationStatus.COMPLETED
        assert result.get_iteration_count() == 0

    def test_creation_with_iterations(self, sample_draft_result, sample_iteration_valid):
        """Test création avec iterations."""
        result = OrchestrationResult(
            final_draft=sample_draft_result,
            iterations=[sample_iteration_valid],
            total_duration_ms=5000,
            total_tokens_used=500,
        )
        assert result.get_iteration_count() == 1
        assert result.total_duration_ms == 5000
        assert result.total_tokens_used == 500

    def test_invalid_total_duration(self, sample_draft_result):
        """Test validation total_duration_ms >= 0."""
        with pytest.raises(ValueError, match="total_duration_ms must be non-negative"):
            OrchestrationResult(
                final_draft=sample_draft_result,
                total_duration_ms=-100,
            )

    def test_invalid_total_tokens(self, sample_draft_result):
        """Test validation total_tokens_used >= 0."""
        with pytest.raises(ValueError, match="total_tokens_used must be non-negative"):
            OrchestrationResult(
                final_draft=sample_draft_result,
                total_tokens_used=-50,
            )

    def test_status_from_string(self, sample_draft_result):
        """Test conversion status depuis string."""
        result = OrchestrationResult(
            final_draft=sample_draft_result,
            status="completed",
        )
        assert result.status == OrchestrationStatus.COMPLETED

    def test_get_best_draft_single_iteration(self, sample_draft_result, sample_iteration_valid):
        """Test get_best_draft avec une seule itération."""
        result = OrchestrationResult(
            final_draft=sample_draft_result,
            iterations=[sample_iteration_valid],
        )
        best = result.get_best_draft()
        assert best == sample_draft_result

    def test_get_best_draft_multiple_iterations(self, sample_draft_result):
        """Test get_best_draft avec plusieurs itérations."""
        # Iteration 1: score 58
        draft1 = DraftResult(content="Draft 1", confidence=0.6)
        scores1 = CritiqueScores(coherence=55, tone=60, completeness=50, errors=70, conciseness=55, over_commitment=60, emotional_intelligence=50)
        critique1 = CritiqueResult(scores=scores1, decision=CritiqueDecision.REJECT)
        iter1 = IterationRecord(draft_result=draft1, critique_result=critique1, iteration_number=1, duration_ms=2000)

        # Iteration 2: score 87 (meilleur)
        draft2 = DraftResult(content="Draft 2", confidence=0.9)
        scores2 = CritiqueScores(coherence=85, tone=90, completeness=85, errors=90, conciseness=85, over_commitment=90, emotional_intelligence=80)
        critique2 = CritiqueResult(scores=scores2, decision=CritiqueDecision.VALID)
        iter2 = IterationRecord(draft_result=draft2, critique_result=critique2, iteration_number=2, duration_ms=2500)

        result = OrchestrationResult(
            final_draft=draft2,
            iterations=[iter1, iter2],
        )

        best = result.get_best_draft()
        assert best.content == "Draft 2"

    def test_get_best_draft_no_critiques(self, sample_draft_result):
        """Test get_best_draft sans critiques."""
        draft1 = DraftResult(content="Draft 1", confidence=0.7)
        iter1 = IterationRecord(draft_result=draft1, critique_result=None, iteration_number=1, duration_ms=1000)

        result = OrchestrationResult(
            final_draft=sample_draft_result,
            iterations=[iter1],
        )

        best = result.get_best_draft()
        assert best == sample_draft_result

    def test_get_best_score(self, sample_draft_result, sample_iteration_valid):
        """Test get_best_score()."""
        result = OrchestrationResult(
            final_draft=sample_draft_result,
            iterations=[sample_iteration_valid],
        )
        assert result.get_best_score() == 86  # (85+90+80+95+85+90+80)//7

    def test_get_final_score(self, sample_draft_result, sample_iteration_valid):
        """Test get_final_score()."""
        result = OrchestrationResult(
            final_draft=sample_draft_result,
            iterations=[sample_iteration_valid],
        )
        assert result.get_final_score() == 86

    def test_was_validated_true(self, sample_draft_result, sample_iteration_valid):
        """Test was_validated() = True."""
        result = OrchestrationResult(
            final_draft=sample_draft_result,
            iterations=[sample_iteration_valid],
        )
        assert result.was_validated() is True

    def test_was_validated_false(self, sample_draft_result, sample_iteration_reject):
        """Test was_validated() = False."""
        result = OrchestrationResult(
            final_draft=sample_draft_result,
            iterations=[sample_iteration_reject],
        )
        assert result.was_validated() is False

    def test_is_successful_true(self, sample_draft_result):
        """Test is_successful() = True."""
        result = OrchestrationResult(
            final_draft=sample_draft_result,
            status=OrchestrationStatus.COMPLETED,
        )
        assert result.is_successful() is True

    def test_is_successful_false_failed_status(self, sample_draft_result):
        """Test is_successful() = False avec status FAILED."""
        result = OrchestrationResult(
            final_draft=sample_draft_result,
            status=OrchestrationStatus.FAILED,
        )
        assert result.is_successful() is False

    def test_is_successful_false_empty_content(self):
        """Test is_successful() = False avec contenu vide."""
        draft = DraftResult(content="", confidence=0.0, status=DraftStatus.FAILED)
        result = OrchestrationResult(
            final_draft=draft,
            status=OrchestrationStatus.COMPLETED,
        )
        assert result.is_successful() is False

    def test_was_timeout(self, sample_draft_result):
        """Test was_timeout()."""
        result = OrchestrationResult(
            final_draft=sample_draft_result,
            status=OrchestrationStatus.TIMEOUT,
        )
        assert result.was_timeout() is True

    def test_to_dict(self, sample_draft_result, sample_iteration_valid):
        """Test sérialisation to_dict()."""
        result = OrchestrationResult(
            final_draft=sample_draft_result,
            iterations=[sample_iteration_valid],
            total_duration_ms=5000,
            total_tokens_used=500,
        )
        d = result.to_dict()

        assert d["status"] == "completed"
        assert d["iteration_count"] == 1
        assert d["total_duration_ms"] == 5000
        assert d["total_tokens_used"] == 500
        assert d["best_score"] == 86
        assert d["is_successful"] is True
        assert "final_draft" in d
        assert "iterations" in d

    def test_create_failed(self):
        """Test factory create_failed()."""
        result = OrchestrationResult.create_failed(
            error_message="Test error",
            total_duration_ms=1000,
        )
        assert result.status == OrchestrationStatus.FAILED
        assert result.error_message == "Test error"
        assert result.total_duration_ms == 1000
        assert result.is_successful() is False

    def test_create_failed_with_iterations(self):
        """Test create_failed() avec iterations existantes."""
        draft1 = DraftResult(content="Partial draft", confidence=0.7)
        scores = CritiqueScores(coherence=70, tone=75, completeness=65, errors=80, conciseness=70, over_commitment=75, emotional_intelligence=65)
        critique = CritiqueResult(scores=scores, decision=CritiqueDecision.REJECT)
        iter1 = IterationRecord(draft_result=draft1, critique_result=critique, iteration_number=1, duration_ms=2000)

        result = OrchestrationResult.create_failed(
            error_message="Timeout",
            iterations=[iter1],
            total_duration_ms=3000,
        )

        assert result.status == OrchestrationStatus.FAILED
        assert result.final_draft.content == "Partial draft"
        assert len(result.iterations) == 1

    def test_create_timeout(self):
        """Test factory create_timeout()."""
        draft1 = DraftResult(content="Draft before timeout", confidence=0.75)
        scores = CritiqueScores(coherence=72, tone=78, completeness=70, errors=80, conciseness=72, over_commitment=78, emotional_intelligence=70)
        critique = CritiqueResult(scores=scores, decision=CritiqueDecision.REJECT)
        iter1 = IterationRecord(draft_result=draft1, critique_result=critique, iteration_number=1, duration_ms=60000)

        result = OrchestrationResult.create_timeout(
            iterations=[iter1],
            total_duration_ms=240000,
            total_tokens_used=800,
        )

        assert result.status == OrchestrationStatus.TIMEOUT
        assert result.was_timeout() is True
        assert result.final_draft.content == "Draft before timeout"
        assert "timeout" in result.error_message.lower()

    def test_create_timeout_empty_iterations(self):
        """Test create_timeout() sans iterations."""
        result = OrchestrationResult.create_timeout(
            iterations=[],
            total_duration_ms=240000,
        )

        assert result.status == OrchestrationStatus.TIMEOUT
        assert result.final_draft.content == ""
        assert result.final_draft.status == DraftStatus.FAILED
