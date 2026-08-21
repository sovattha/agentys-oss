# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour app.domain.entities.draft."""

import pytest
from app.domain.entities.draft import Draft, DraftStatus, Critique, ProcessingResult
from app.domain.exceptions import InvalidBoundsError


# ============================================================================
# DraftStatus
# ============================================================================

class TestDraftStatus:
    def test_all_values(self):
        assert DraftStatus.PENDING.value == "pending"
        assert DraftStatus.VALIDATED_V1.value == "validated_v1"
        assert DraftStatus.CORRECTED_V2.value == "corrected_v2"
        assert DraftStatus.REJECTED.value == "rejected"


# ============================================================================
# Draft
# ============================================================================

class TestDraft:
    def test_create_valid_draft(self):
        draft = Draft(content="Bonjour, bien reçu.", version=1)
        assert draft.content == "Bonjour, bien reçu."
        assert draft.version == 1

    def test_default_version_is_one(self):
        draft = Draft(content="Hello")
        assert draft.version == 1

    def test_version_zero_raises(self):
        with pytest.raises(InvalidBoundsError):
            Draft(content="Hello", version=0)

    def test_version_negative_raises(self):
        with pytest.raises(InvalidBoundsError):
            Draft(content="Hello", version=-1)

    def test_version_two_is_valid(self):
        draft = Draft(content="Corrected", version=2)
        assert draft.version == 2

    def test_str_returns_content(self):
        draft = Draft(content="Mon contenu")
        assert str(draft) == "Mon contenu"

    def test_empty_content_allowed(self):
        draft = Draft(content="")
        assert draft.content == ""


# ============================================================================
# Critique
# ============================================================================

class TestCritique:
    def test_create_critique(self):
        critique = Critique(raw_response="VALID", is_valid=True)
        assert critique.is_valid is True
        assert critique.reason is None

    def test_from_response_valid(self):
        critique = Critique.from_response("VALID - Good response")
        assert critique.is_valid is True
        assert critique.reason is None

    def test_from_response_valid_lowercase(self):
        critique = Critique.from_response("valid response looks good")
        assert critique.is_valid is True

    def test_from_response_invalid(self):
        critique = Critique.from_response("REJET: Le ton est trop informel")
        assert critique.is_valid is False
        assert critique.reason == "REJET: Le ton est trop informel"

    def test_from_response_with_whitespace(self):
        critique = Critique.from_response("  VALID  ")
        assert critique.is_valid is True

    def test_str_returns_raw_response(self):
        critique = Critique(raw_response="Test response", is_valid=False, reason="Test")
        assert str(critique) == "Test response"


# ============================================================================
# ProcessingResult
# ============================================================================

class TestProcessingResult:
    def _make_result(self, status=DraftStatus.VALIDATED_V1) -> ProcessingResult:
        return ProcessingResult(
            email_id="email-123",
            draft_v1=Draft(content="V1 content"),
            critique=Critique(raw_response="VALID", is_valid=True),
            draft_final=Draft(content="V1 content"),
            status=status,
        )

    def test_was_corrected_false_for_v1(self):
        result = self._make_result(DraftStatus.VALIDATED_V1)
        assert result.was_corrected is False

    def test_was_corrected_true_for_v2(self):
        result = self._make_result(DraftStatus.CORRECTED_V2)
        assert result.was_corrected is True

    def test_was_corrected_false_for_rejected(self):
        result = self._make_result(DraftStatus.REJECTED)
        assert result.was_corrected is False

    def test_email_id_stored(self):
        result = self._make_result()
        assert result.email_id == "email-123"
