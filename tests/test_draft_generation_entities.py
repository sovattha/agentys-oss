"""Tests unitaires pour app.domain.entities.draft_generation."""

import pytest

from app.domain.entities.draft_generation import (
    DraftTone,
    DraftStatus,
    DraftRequest,
    DraftResult,
    StreamingDraftChunk,
)


# ── DraftTone / DraftStatus ─────────────────────────────────────────────────


class TestEnums:
    def test_draft_tone_values(self):
        assert DraftTone.FORMAL.value == "formal"
        assert DraftTone.FRIENDLY.value == "friendly"
        assert DraftTone.PROFESSIONAL.value == "professional"
        assert DraftTone.NEUTRAL.value == "neutral"
        assert DraftTone.URGENT.value == "urgent"

    def test_draft_status_values(self):
        assert DraftStatus.PENDING.value == "pending"
        assert DraftStatus.GENERATING.value == "generating"
        assert DraftStatus.COMPLETED.value == "completed"
        assert DraftStatus.FAILED.value == "failed"
        assert DraftStatus.RATE_LIMITED.value == "rate_limited"


# ── DraftRequest ─────────────────────────────────────────────────────────────


class TestDraftRequest:
    def test_creation_basic(self):
        req = DraftRequest(email_content="Hello there")
        assert req.email_content == "Hello there"
        assert req.instructions is None
        assert req.tone_hint is None

    def test_empty_content_raises(self):
        with pytest.raises(ValueError, match="email_content cannot be empty"):
            DraftRequest(email_content="")

    def test_whitespace_content_raises(self):
        with pytest.raises(ValueError, match="email_content cannot be empty"):
            DraftRequest(email_content="   ")

    def test_negative_max_length_raises(self):
        with pytest.raises(ValueError, match="max_length must be positive"):
            DraftRequest(email_content="test", max_length=0)

    def test_tone_hint_string_conversion(self):
        req = DraftRequest(email_content="test", tone_hint="formal")
        assert req.tone_hint == DraftTone.FORMAL

    def test_tone_hint_invalid_string_becomes_none(self):
        req = DraftRequest(email_content="test", tone_hint="nonexistent")
        assert req.tone_hint is None

    def test_tone_hint_enum_preserved(self):
        req = DraftRequest(email_content="test", tone_hint=DraftTone.URGENT)
        assert req.tone_hint == DraftTone.URGENT

    def test_to_dict(self):
        req = DraftRequest(
            email_content="Hello",
            instructions="Be polite",
            recipient_email="bob@test.com",
            tone_hint=DraftTone.FRIENDLY,
            max_length=100,
        )
        d = req.to_dict()
        assert d["email_content"] == "Hello"
        assert d["instructions"] == "Be polite"
        assert d["tone_hint"] == "friendly"
        assert d["max_length"] == 100

    def test_has_context_false(self):
        req = DraftRequest(email_content="test")
        assert req.has_context() is False

    def test_get_style_hints_empty(self):
        req = DraftRequest(email_content="test")
        assert req.get_style_hints() == []


# ── DraftResult ──────────────────────────────────────────────────────────────


class TestDraftResult:
    def test_creation_basic(self):
        result = DraftResult(content="Bonjour, merci pour votre email.")
        assert result.content == "Bonjour, merci pour votre email."
        assert result.confidence == 0.8
        assert result.status == DraftStatus.COMPLETED

    def test_word_count_auto_calculated(self):
        result = DraftResult(content="one two three four five")
        assert result.word_count == 5

    def test_word_count_preserved_if_set(self):
        result = DraftResult(content="one two three", word_count=10)
        assert result.word_count == 10

    def test_invalid_confidence_raises(self):
        with pytest.raises(ValueError, match="confidence must be between"):
            DraftResult(content="test", confidence=1.5)
        with pytest.raises(ValueError, match="confidence must be between"):
            DraftResult(content="test", confidence=-0.1)

    def test_negative_generation_time_raises(self):
        with pytest.raises(ValueError, match="generation_time_ms must be non-negative"):
            DraftResult(content="test", generation_time_ms=-1)

    def test_negative_tokens_raises(self):
        with pytest.raises(ValueError, match="tokens_used must be non-negative"):
            DraftResult(content="test", tokens_used=-1)

    def test_negative_retry_raises(self):
        with pytest.raises(ValueError, match="retry_count must be non-negative"):
            DraftResult(content="test", retry_count=-1)

    def test_string_tone_conversion(self):
        result = DraftResult(content="test", tone_detected="friendly")
        assert result.tone_detected == DraftTone.FRIENDLY

    def test_invalid_tone_string_defaults(self):
        result = DraftResult(content="test", tone_detected="invalid")
        assert result.tone_detected == DraftTone.PROFESSIONAL

    def test_string_status_conversion(self):
        result = DraftResult(content="test", status="failed")
        assert result.status == DraftStatus.FAILED

    def test_to_dict(self):
        result = DraftResult(
            content="Hello",
            confidence=0.9,
            tone_detected=DraftTone.FORMAL,
            tokens_used=100,
        )
        d = result.to_dict()
        assert d["content"] == "Hello"
        assert d["confidence"] == 0.9
        assert d["tone_detected"] == "formal"
        assert "generated_at" in d

    def test_is_successful_true(self):
        result = DraftResult(content="Hello", status=DraftStatus.COMPLETED)
        assert result.is_successful() is True

    def test_is_successful_false_empty(self):
        result = DraftResult(content="", confidence=0.0, status=DraftStatus.COMPLETED)
        assert result.is_successful() is False

    def test_is_successful_false_failed(self):
        result = DraftResult(content="Hello", confidence=0.5, status=DraftStatus.FAILED)
        assert result.is_successful() is False

    def test_was_rate_limited(self):
        result = DraftResult(
            content="", confidence=0.0, status=DraftStatus.RATE_LIMITED
        )
        assert result.was_rate_limited() is True

    def test_create_failed(self):
        result = DraftResult.create_failed("API error", retry_count=3)
        assert result.content == ""
        assert result.confidence == 0.0
        assert result.status == DraftStatus.FAILED
        assert result.error_message == "API error"
        assert result.retry_count == 3

    def test_create_rate_limited(self):
        result = DraftResult.create_rate_limited(retry_count=5, generation_time_ms=3000)
        assert result.status == DraftStatus.RATE_LIMITED
        assert result.retry_count == 5


# ── StreamingDraftChunk ──────────────────────────────────────────────────────


class TestStreamingDraftChunk:
    def test_creation(self):
        chunk = StreamingDraftChunk(
            chunk="Hello",
            chunk_index=0,
            accumulated_text="Hello",
        )
        assert chunk.is_final is False
        assert chunk.progress_percent == 0.0

    def test_to_dict(self):
        chunk = StreamingDraftChunk(
            chunk=" world",
            chunk_index=1,
            accumulated_text="Hello world",
            is_final=True,
            progress_percent=100.0,
            tokens_so_far=10,
        )
        d = chunk.to_dict()
        assert d["chunk"] == " world"
        assert d["is_final"] is True
        assert d["progress_percent"] == 100.0
        assert d["tokens_so_far"] == 10
