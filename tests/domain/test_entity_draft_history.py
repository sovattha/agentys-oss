# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour app.domain.entities.draft_history."""

from app.domain.entities.draft_history import DraftRecord


class TestDraftRecord:
    """Tests pour DraftRecord."""

    def _make_record(self, **kwargs) -> DraftRecord:
        defaults = dict(
            id="dr-1",
            timestamp="2026-03-24T10:00:00",
            email_id="e-1",
            email_sender="alice@example.com",
            email_subject="Demande de devis",
            email_preview="Bonjour, je souhaite...",
            draft_v1="Bonjour Alice, merci pour votre demande.",
            critique="VALID",
            draft_final="Bonjour Alice, merci pour votre demande.",
            status="V1",
        )
        defaults.update(kwargs)
        return DraftRecord(**defaults)

    # --- Création ---

    def test_create_with_required_fields(self):
        record = self._make_record()
        assert record.id == "dr-1"
        assert record.email_sender == "alice@example.com"
        assert record.status == "V1"

    def test_default_optional_fields(self):
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

    def test_create_with_all_fields(self):
        record = self._make_record(
            draft_id="gd-1",
            tokens_used=500,
            model="claude-sonnet-4-20250514",
            processing_time_ms=1200,
            priority_score=80,
            category="URGENT",
            feedback="positive",
            feedback_comment="Excellent",
            feedback_rating=5,
        )
        assert record.draft_id == "gd-1"
        assert record.tokens_used == 500
        assert record.priority_score == 80
        assert record.feedback_rating == 5

    # --- email_body alias ---

    def test_email_body_alias(self):
        record = self._make_record(email_preview="Preview text")
        assert record.email_body == "Preview text"

    # --- to_correction_context ---

    def test_to_correction_context(self):
        record = self._make_record(category="NORMAL")
        ctx = record.to_correction_context()
        assert ctx == {
            "sender": "alice@example.com",
            "subject": "Demande de devis",
            "category": "NORMAL",
        }

    def test_to_correction_context_no_category(self):
        record = self._make_record()
        ctx = record.to_correction_context()
        assert ctx["category"] is None

    # --- with_feedback ---

    def test_with_feedback_returns_new_instance(self):
        record = self._make_record()
        updated = record.with_feedback("positive", "Bon travail", 5)
        assert updated.feedback == "positive"
        assert updated.feedback_comment == "Bon travail"
        assert updated.feedback_rating == 5
        # Original unchanged
        assert record.feedback is None

    def test_with_feedback_preserves_all_fields(self):
        record = self._make_record(
            draft_id="gd-1",
            tokens_used=300,
            model="test-model",
            processing_time_ms=800,
            priority_score=60,
            category="NORMAL",
        )
        updated = record.with_feedback("negative")
        assert updated.id == record.id
        assert updated.draft_id == "gd-1"
        assert updated.tokens_used == 300
        assert updated.model == "test-model"
        assert updated.priority_score == 60

    def test_with_feedback_default_comment_and_rating(self):
        record = self._make_record()
        updated = record.with_feedback("neutral")
        assert updated.feedback_comment == ""
        assert updated.feedback_rating is None
