# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour l'entité DraftRecord."""

from app.domain.entities.draft_history import DraftRecord


class TestDraftRecordCreation:
    """Tests pour la création de DraftRecord."""

    def _make_record(self, **kwargs):
        defaults = {
            "id": "d1",
            "timestamp": "2026-03-01T10:00:00",
            "email_id": "e1",
            "email_sender": "sender@example.com",
            "email_subject": "Test Subject",
            "email_preview": "Preview text...",
            "draft_v1": "First version",
            "critique": "Looks good",
            "draft_final": "Final version",
            "status": "V1",
        }
        defaults.update(kwargs)
        return DraftRecord(**defaults)

    def test_create_minimal(self):
        record = self._make_record()
        assert record.id == "d1"
        assert record.email_sender == "sender@example.com"
        assert record.status == "V1"

    def test_optional_fields_default(self):
        record = self._make_record()
        assert record.draft_id is None
        assert record.tokens_used == 0
        assert record.model == ""
        assert record.processing_time_ms == 0
        assert record.priority_score is None
        assert record.category is None
        assert record.feedback is None
        assert record.feedback_comment is None
        assert record.feedback_rating is None


class TestDraftRecordEmailBodyAlias:
    """Tests pour l'alias email_body."""

    def _make_record(self, preview="Preview text"):
        return DraftRecord(
            id="d1", timestamp="2026-03-01", email_id="e1",
            email_sender="s@e.com", email_subject="Sub",
            email_preview=preview, draft_v1="v1", critique="c",
            draft_final="vf", status="V1",
        )

    def test_email_body_returns_preview(self):
        record = self._make_record(preview="Hello there")
        assert record.email_body == "Hello there"


class TestDraftRecordToCorrectionContext:
    """Tests pour to_correction_context."""

    def _make_record(self, **kwargs):
        defaults = {
            "id": "d1", "timestamp": "2026-03-01", "email_id": "e1",
            "email_sender": "sender@example.com", "email_subject": "Subject",
            "email_preview": "Preview", "draft_v1": "v1", "critique": "c",
            "draft_final": "vf", "status": "V1",
        }
        defaults.update(kwargs)
        return DraftRecord(**defaults)

    def test_correction_context_keys(self):
        record = self._make_record(category="URGENT")
        ctx = record.to_correction_context()
        assert "sender" in ctx
        assert "subject" in ctx
        assert "category" in ctx

    def test_correction_context_values(self):
        record = self._make_record(
            email_sender="boss@company.com",
            email_subject="Important",
            category="URGENT",
        )
        ctx = record.to_correction_context()
        assert ctx["sender"] == "boss@company.com"
        assert ctx["subject"] == "Important"
        assert ctx["category"] == "URGENT"

    def test_correction_context_none_category(self):
        record = self._make_record()
        ctx = record.to_correction_context()
        assert ctx["category"] is None


class TestDraftRecordWithFeedback:
    """Tests pour with_feedback."""

    def _make_record(self):
        return DraftRecord(
            id="d1", timestamp="2026-03-01", email_id="e1",
            email_sender="s@e.com", email_subject="Sub",
            email_preview="Preview", draft_v1="v1", critique="c",
            draft_final="vf", status="V1", tokens_used=100,
            model="sonnet", processing_time_ms=500,
            priority_score=80, category="NORMAL",
        )

    def test_with_feedback_creates_new_instance(self):
        record = self._make_record()
        updated = record.with_feedback("positive", "Great!", 5)
        assert updated is not record
        assert updated.feedback == "positive"
        assert updated.feedback_comment == "Great!"
        assert updated.feedback_rating == 5

    def test_with_feedback_preserves_fields(self):
        record = self._make_record()
        updated = record.with_feedback("negative", "Bad")
        assert updated.id == record.id
        assert updated.timestamp == record.timestamp
        assert updated.email_id == record.email_id
        assert updated.email_sender == record.email_sender
        assert updated.tokens_used == record.tokens_used
        assert updated.model == record.model
        assert updated.priority_score == record.priority_score

    def test_with_feedback_original_unchanged(self):
        record = self._make_record()
        record.with_feedback("positive")
        assert record.feedback is None

    def test_with_feedback_defaults(self):
        record = self._make_record()
        updated = record.with_feedback("neutral")
        assert updated.feedback_comment == ""
        assert updated.feedback_rating is None

    def test_with_feedback_rating_values(self):
        record = self._make_record()
        for rating in [1, 2, 3, 4, 5]:
            updated = record.with_feedback("positive", rating=rating)
            assert updated.feedback_rating == rating
