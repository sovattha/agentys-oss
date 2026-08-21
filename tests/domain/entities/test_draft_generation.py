"""Tests pour les entités de génération de brouillons.

Story 5-1: DrafterAgent Implementation
Task 1: Tests unitaires pour DraftRequest et DraftResult
"""

import pytest

from app.domain.entities.draft_generation import (
    DraftTone,
    DraftStatus,
    DraftRequest,
    DraftResult,
    StreamingDraftChunk,
)


# ============================================================================
# DraftTone Tests
# ============================================================================

class TestDraftTone:
    """Tests pour l'enum DraftTone."""

    def test_all_values_exist(self):
        """Vérifie que toutes les valeurs attendues existent."""
        assert DraftTone.FORMAL.value == "formal"
        assert DraftTone.FRIENDLY.value == "friendly"
        assert DraftTone.PROFESSIONAL.value == "professional"
        assert DraftTone.NEUTRAL.value == "neutral"
        assert DraftTone.URGENT.value == "urgent"

    def test_value_from_string(self):
        """Vérifie la création depuis une string."""
        assert DraftTone("formal") == DraftTone.FORMAL
        assert DraftTone("professional") == DraftTone.PROFESSIONAL


# ============================================================================
# DraftStatus Tests
# ============================================================================

class TestDraftStatus:
    """Tests pour l'enum DraftStatus."""

    def test_all_values_exist(self):
        """Vérifie que toutes les valeurs attendues existent."""
        assert DraftStatus.PENDING.value == "pending"
        assert DraftStatus.GENERATING.value == "generating"
        assert DraftStatus.COMPLETED.value == "completed"
        assert DraftStatus.FAILED.value == "failed"
        assert DraftStatus.RATE_LIMITED.value == "rate_limited"


# ============================================================================
# DraftRequest Tests
# ============================================================================

class TestDraftRequest:
    """Tests pour DraftRequest."""

    def test_minimal_creation(self):
        """Vérifie la création minimale avec email_content uniquement."""
        request = DraftRequest(email_content="Hello, I need help.")
        assert request.email_content == "Hello, I need help."
        assert request.instructions is None
        assert request.context_result is None
        assert request.style_context is None

    def test_full_creation(self):
        """Vérifie la création avec tous les champs."""
        request = DraftRequest(
            email_content="Hello, I need help.",
            instructions="Be polite and concise",
            style_context="formal tone",
            recipient_email="test@example.com",
            subject="Re: Help needed",
            account_id=1,
            session_id="session-123",
            tone_hint=DraftTone.FORMAL,
            max_length=200,
        )
        assert request.email_content == "Hello, I need help."
        assert request.instructions == "Be polite and concise"
        assert request.style_context == "formal tone"
        assert request.recipient_email == "test@example.com"
        assert request.subject == "Re: Help needed"
        assert request.account_id == 1
        assert request.session_id == "session-123"
        assert request.tone_hint == DraftTone.FORMAL
        assert request.max_length == 200

    def test_tone_hint_string_conversion(self):
        """Vérifie la conversion string -> DraftTone."""
        request = DraftRequest(
            email_content="Hello",
            tone_hint="formal",  # type: ignore
        )
        assert request.tone_hint == DraftTone.FORMAL

    def test_invalid_tone_hint_becomes_none(self):
        """Vérifie qu'un tone_hint invalide devient None."""
        request = DraftRequest(
            email_content="Hello",
            tone_hint="invalid_tone",  # type: ignore
        )
        assert request.tone_hint is None

    def test_empty_email_content_raises(self):
        """Vérifie qu'un email_content vide lève une erreur."""
        with pytest.raises(ValueError, match="email_content cannot be empty"):
            DraftRequest(email_content="")

    def test_whitespace_email_content_raises(self):
        """Vérifie qu'un email_content whitespace lève une erreur."""
        with pytest.raises(ValueError, match="email_content cannot be empty"):
            DraftRequest(email_content="   ")

    def test_invalid_max_length_raises(self):
        """Vérifie qu'un max_length <= 0 lève une erreur."""
        with pytest.raises(ValueError, match="max_length must be positive"):
            DraftRequest(email_content="Hello", max_length=0)
        with pytest.raises(ValueError, match="max_length must be positive"):
            DraftRequest(email_content="Hello", max_length=-10)

    def test_to_dict(self):
        """Vérifie la sérialisation en dictionnaire."""
        request = DraftRequest(
            email_content="Hello",
            instructions="Be formal",
            tone_hint=DraftTone.FORMAL,
        )
        result = request.to_dict()
        assert result["email_content"] == "Hello"
        assert result["instructions"] == "Be formal"
        assert result["tone_hint"] == "formal"

    def test_has_context_without_context(self):
        """Vérifie has_context() sans contexte."""
        request = DraftRequest(email_content="Hello")
        assert request.has_context() is False

    def test_get_style_hints_without_context(self):
        """Vérifie get_style_hints() sans contexte."""
        request = DraftRequest(email_content="Hello")
        assert request.get_style_hints() == []


# ============================================================================
# DraftResult Tests
# ============================================================================

class TestDraftResult:
    """Tests pour DraftResult."""

    def test_minimal_creation(self):
        """Vérifie la création minimale."""
        result = DraftResult(content="Here is my response.")
        assert result.content == "Here is my response."
        assert result.confidence == 0.8
        assert result.status == DraftStatus.COMPLETED
        assert result.word_count == 4  # "Here is my response."

    def test_full_creation(self):
        """Vérifie la création avec tous les champs."""
        result = DraftResult(
            content="Response text here.",
            confidence=0.95,
            tone_detected=DraftTone.PROFESSIONAL,
            generation_time_ms=1500,
            tokens_used=250,
            status=DraftStatus.COMPLETED,
            retry_count=0,
            context_used=True,
            style_applied=True,
        )
        assert result.content == "Response text here."
        assert result.confidence == 0.95
        assert result.tone_detected == DraftTone.PROFESSIONAL
        assert result.generation_time_ms == 1500
        assert result.tokens_used == 250
        assert result.context_used is True
        assert result.style_applied is True

    def test_word_count_calculation(self):
        """Vérifie le calcul automatique du nombre de mots."""
        result = DraftResult(content="One two three four five")
        assert result.word_count == 5

    def test_confidence_validation(self):
        """Vérifie la validation du score de confiance."""
        with pytest.raises(ValueError, match="confidence must be between"):
            DraftResult(content="Test", confidence=1.5)
        with pytest.raises(ValueError, match="confidence must be between"):
            DraftResult(content="Test", confidence=-0.1)

    def test_generation_time_validation(self):
        """Vérifie la validation du temps de génération."""
        with pytest.raises(ValueError, match="generation_time_ms must be non-negative"):
            DraftResult(content="Test", generation_time_ms=-100)

    def test_tokens_used_validation(self):
        """Vérifie la validation des tokens utilisés."""
        with pytest.raises(ValueError, match="tokens_used must be non-negative"):
            DraftResult(content="Test", tokens_used=-10)

    def test_retry_count_validation(self):
        """Vérifie la validation du nombre de retries."""
        with pytest.raises(ValueError, match="retry_count must be non-negative"):
            DraftResult(content="Test", retry_count=-1)

    def test_tone_string_conversion(self):
        """Vérifie la conversion string -> DraftTone."""
        result = DraftResult(
            content="Test",
            tone_detected="formal",  # type: ignore
        )
        assert result.tone_detected == DraftTone.FORMAL

    def test_status_string_conversion(self):
        """Vérifie la conversion string -> DraftStatus."""
        result = DraftResult(
            content="Test",
            status="completed",  # type: ignore
        )
        assert result.status == DraftStatus.COMPLETED

    def test_is_successful_true(self):
        """Vérifie is_successful() pour une génération réussie."""
        result = DraftResult(content="Response", status=DraftStatus.COMPLETED)
        assert result.is_successful() is True

    def test_is_successful_false_empty(self):
        """Vérifie is_successful() pour un contenu vide."""
        result = DraftResult(content="", status=DraftStatus.COMPLETED)
        assert result.is_successful() is False

    def test_is_successful_false_failed(self):
        """Vérifie is_successful() pour un statut FAILED."""
        result = DraftResult(content="Test", status=DraftStatus.FAILED)
        assert result.is_successful() is False

    def test_was_rate_limited(self):
        """Vérifie was_rate_limited()."""
        result = DraftResult(content="", status=DraftStatus.RATE_LIMITED)
        assert result.was_rate_limited() is True

        result2 = DraftResult(content="Test", status=DraftStatus.COMPLETED)
        assert result2.was_rate_limited() is False

    def test_to_dict(self):
        """Vérifie la sérialisation en dictionnaire."""
        result = DraftResult(
            content="Test response",
            confidence=0.9,
            tone_detected=DraftTone.FORMAL,
            status=DraftStatus.COMPLETED,
        )
        d = result.to_dict()
        assert d["content"] == "Test response"
        assert d["confidence"] == 0.9
        assert d["tone_detected"] == "formal"
        assert d["status"] == "completed"
        assert "generated_at" in d

    def test_create_failed(self):
        """Vérifie la création d'un résultat d'échec."""
        result = DraftResult.create_failed(
            error_message="API error",
            retry_count=2,
            generation_time_ms=5000,
        )
        assert result.content == ""
        assert result.confidence == 0.0
        assert result.status == DraftStatus.FAILED
        assert result.error_message == "API error"
        assert result.retry_count == 2
        assert result.generation_time_ms == 5000

    def test_create_rate_limited(self):
        """Vérifie la création d'un résultat rate limited."""
        result = DraftResult.create_rate_limited(
            retry_count=3,
            generation_time_ms=10000,
        )
        assert result.content == ""
        assert result.status == DraftStatus.RATE_LIMITED
        assert "Rate limit exceeded" in result.error_message
        assert result.retry_count == 3


# ============================================================================
# StreamingDraftChunk Tests
# ============================================================================

class TestStreamingDraftChunk:
    """Tests pour StreamingDraftChunk."""

    def test_creation(self):
        """Vérifie la création d'un chunk."""
        chunk = StreamingDraftChunk(
            chunk="Hello ",
            chunk_index=0,
            accumulated_text="Hello ",
            is_final=False,
            progress_percent=25.0,
            tokens_so_far=5,
        )
        assert chunk.chunk == "Hello "
        assert chunk.chunk_index == 0
        assert chunk.accumulated_text == "Hello "
        assert chunk.is_final is False
        assert chunk.progress_percent == 25.0
        assert chunk.tokens_so_far == 5

    def test_final_chunk(self):
        """Vérifie un chunk final."""
        chunk = StreamingDraftChunk(
            chunk="!",
            chunk_index=3,
            accumulated_text="Hello world!",
            is_final=True,
            progress_percent=100.0,
        )
        assert chunk.is_final is True
        assert chunk.progress_percent == 100.0

    def test_to_dict(self):
        """Vérifie la sérialisation pour WebSocket."""
        chunk = StreamingDraftChunk(
            chunk="test",
            chunk_index=1,
            accumulated_text="Hello test",
            progress_percent=50.0,
        )
        d = chunk.to_dict()
        assert d["chunk"] == "test"
        assert d["chunk_index"] == 1
        assert d["accumulated_text"] == "Hello test"
        assert d["is_final"] is False
        assert d["progress_percent"] == 50.0
