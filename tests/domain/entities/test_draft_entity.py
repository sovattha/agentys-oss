# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests for Draft, Critique, and ProcessingResult entities.

TDD: RED phase - Write failing tests first for comprehensive coverage.
"""

import pytest
from app.domain.entities.draft import (
    Draft,
    DraftStatus,
    Critique,
    ProcessingResult,
)
from app.domain.exceptions import InvalidBoundsError


class TestDraftStatus:
    """Tests for DraftStatus enum."""

    def test_all_status_values_exist(self):
        """Test that all expected status values exist."""
        assert DraftStatus.PENDING.value == "pending"
        assert DraftStatus.VALIDATED_V1.value == "validated_v1"
        assert DraftStatus.CORRECTED_V2.value == "corrected_v2"
        assert DraftStatus.REJECTED.value == "rejected"

    def test_status_from_string(self):
        """Test converting strings to status enum."""
        assert DraftStatus("pending") == DraftStatus.PENDING
        assert DraftStatus("validated_v1") == DraftStatus.VALIDATED_V1
        assert DraftStatus("corrected_v2") == DraftStatus.CORRECTED_V2
        assert DraftStatus("rejected") == DraftStatus.REJECTED

    def test_status_comparison(self):
        """Test comparing status enums."""
        assert DraftStatus.PENDING != DraftStatus.VALIDATED_V1
        assert DraftStatus.CORRECTED_V2 != DraftStatus.REJECTED
        assert DraftStatus.VALIDATED_V1 == DraftStatus.VALIDATED_V1


class TestDraft:
    """Tests for Draft dataclass."""

    def test_valid_draft_default_version(self):
        """Test creating a Draft with default version (1)."""
        draft = Draft(content="Hello, this is a response.")
        assert draft.content == "Hello, this is a response."
        assert draft.version == 1

    def test_valid_draft_explicit_version(self):
        """Test creating a Draft with explicit version."""
        draft = Draft(content="Second iteration.", version=2)
        assert draft.content == "Second iteration."
        assert draft.version == 2

    def test_valid_draft_high_version(self):
        """Test creating a Draft with high version number."""
        draft = Draft(content="Many iterations.", version=100)
        assert draft.content == "Many iterations."
        assert draft.version == 100

    def test_draft_with_empty_content(self):
        """Test creating a Draft with empty content (should be allowed)."""
        draft = Draft(content="", version=1)
        assert draft.content == ""
        assert draft.version == 1

    def test_draft_with_long_content(self):
        """Test creating a Draft with very long content."""
        long_content = "A" * 10000
        draft = Draft(content=long_content)
        assert draft.content == long_content
        assert len(draft.content) == 10000

    def test_draft_with_special_characters(self):
        """Test Draft with special characters and accents."""
        content = "Bonjour, ceci est une réponse avec des caractères spéciaux: é, è, ê, à, ù."
        draft = Draft(content=content)
        assert draft.content == content

    def test_draft_with_newlines(self):
        """Test Draft with multiline content."""
        content = "Line 1\nLine 2\nLine 3"
        draft = Draft(content=content)
        assert draft.content == content
        assert "\n" in draft.content

    def test_invalid_version_zero_raises(self):
        """Test that version=0 raises InvalidBoundsError."""
        with pytest.raises(InvalidBoundsError) as exc_info:
            Draft(content="Test", version=0)
        assert "version" in str(exc_info.value).lower()
        assert exc_info.value.field == "version"
        assert exc_info.value.value == 0
        assert exc_info.value.min_val == 1

    def test_invalid_version_negative_raises(self):
        """Test that negative version raises InvalidBoundsError."""
        with pytest.raises(InvalidBoundsError) as exc_info:
            Draft(content="Test", version=-1)
        assert "version" in str(exc_info.value).lower()
        assert exc_info.value.field == "version"
        assert exc_info.value.value == -1

    def test_invalid_version_very_negative_raises(self):
        """Test that very negative version raises InvalidBoundsError."""
        with pytest.raises(InvalidBoundsError) as exc_info:
            Draft(content="Test", version=-999)
        assert exc_info.value.value == -999
        assert exc_info.value.min_val == 1

    def test_draft_str_returns_content(self):
        """Test that __str__ returns the content."""
        content = "This is the draft content."
        draft = Draft(content=content)
        assert str(draft) == content

    def test_draft_str_empty_content(self):
        """Test __str__ with empty content."""
        draft = Draft(content="")
        assert str(draft) == ""

    def test_draft_str_with_special_chars(self):
        """Test __str__ preserves special characters."""
        content = "Réponse spéciale: éàù"
        draft = Draft(content=content)
        assert str(draft) == content

    def test_draft_repr_contains_key_info(self):
        """Test that repr includes key information."""
        draft = Draft(content="Test", version=2)
        repr_str = repr(draft)
        assert "Draft" in repr_str
        assert "content" in repr_str or "Test" in repr_str


class TestCritique:
    """Tests for Critique dataclass."""

    def test_valid_critique_creation(self):
        """Test creating a Critique with basic attributes."""
        critique = Critique(
            raw_response="VALID: This is a great draft.",
            is_valid=True,
            reason=None
        )
        assert critique.raw_response == "VALID: This is a great draft."
        assert critique.is_valid is True
        assert critique.reason is None

    def test_invalid_critique_creation(self):
        """Test creating a Critique with rejection reason."""
        critique = Critique(
            raw_response="Please add more details.",
            is_valid=False,
            reason="Missing important details"
        )
        assert critique.raw_response == "Please add more details."
        assert critique.is_valid is False
        assert critique.reason == "Missing important details"

    def test_critique_str_returns_raw_response(self):
        """Test that __str__ returns raw_response."""
        response = "VALID: Everything looks good."
        critique = Critique(raw_response=response, is_valid=True)
        assert str(critique) == response

    def test_from_response_valid_uppercase(self):
        """Test from_response with VALID (uppercase)."""
        critique = Critique.from_response("VALID: The draft is excellent.")
        assert critique.raw_response == "VALID: The draft is excellent."
        assert critique.is_valid is True
        assert critique.reason is None

    def test_from_response_valid_lowercase(self):
        """Test from_response with valid (lowercase)."""
        critique = Critique.from_response("valid: Looks good to me.")
        assert critique.raw_response == "valid: Looks good to me."
        assert critique.is_valid is True
        assert critique.reason is None

    def test_from_response_valid_mixed_case(self):
        """Test from_response with Valid (mixed case)."""
        critique = Critique.from_response("Valid: This works.")
        assert critique.raw_response == "Valid: This works."
        assert critique.is_valid is True
        assert critique.reason is None

    def test_from_response_valid_no_colon(self):
        """Test from_response with VALID without colon."""
        critique = Critique.from_response("VALID")
        assert critique.raw_response == "VALID"
        assert critique.is_valid is True
        assert critique.reason is None

    def test_from_response_invalid_with_reason(self):
        """Test from_response with rejection sets reason."""
        response = "The draft needs more context and clarity."
        critique = Critique.from_response(response)
        assert critique.raw_response == response
        assert critique.is_valid is False
        assert critique.reason == response

    def test_from_response_reject_keyword(self):
        """Test from_response with REJECT keyword."""
        response = "REJECT: This doesn't meet requirements."
        critique = Critique.from_response(response)
        assert critique.raw_response == response
        assert critique.is_valid is False
        assert critique.reason == response

    def test_from_response_invalid_various_messages(self):
        """Test from_response with various invalid messages."""
        test_cases = [
            "The tone is too formal.",
            "Missing greeting.",
            "Too long.",
            "Needs better closing.",
        ]
        for message in test_cases:
            critique = Critique.from_response(message)
            assert critique.is_valid is False
            assert critique.reason == message

    def test_from_response_strips_whitespace(self):
        """Test that from_response strips leading/trailing whitespace."""
        response = "  VALID: Good job.  "
        critique = Critique.from_response(response)
        assert critique.raw_response == "VALID: Good job."
        assert critique.is_valid is True

    def test_from_response_strips_invalid_response(self):
        """Test that from_response strips whitespace for invalid responses."""
        response = "  Add more details.  "
        critique = Critique.from_response(response)
        assert critique.raw_response == "Add more details."
        assert critique.is_valid is False
        assert critique.reason == "Add more details."

    def test_from_response_multiline_response(self):
        """Test from_response with multiline response (invalid)."""
        response = "Issues found:\n- Missing greeting\n- Tone too casual"
        critique = Critique.from_response(response)
        assert critique.is_valid is False
        assert critique.reason == response
        assert "\n" in critique.reason

    def test_from_response_empty_response(self):
        """Test from_response with empty response."""
        critique = Critique.from_response("")
        assert critique.raw_response == ""
        assert critique.is_valid is False
        assert critique.reason == ""

    def test_from_response_whitespace_only(self):
        """Test from_response with whitespace-only response."""
        critique = Critique.from_response("   ")
        assert critique.raw_response == ""
        assert critique.is_valid is False
        assert critique.reason == ""

    def test_from_response_valid_with_extra_text(self):
        """Test from_response: VALID followed by anything is valid."""
        critique = Critique.from_response("VALID - Perfect response!")
        assert critique.is_valid is True
        assert critique.reason is None

    def test_from_response_almost_valid_fails(self):
        """Test that 'VALID' must be at the start."""
        critique = Critique.from_response("This is VALID but not at start.")
        assert critique.is_valid is False
        assert critique.is_valid is False


class TestProcessingResult:
    """Tests for ProcessingResult dataclass."""

    @pytest.fixture
    def valid_draft_v1(self):
        """Create a valid v1 draft."""
        return Draft(content="Dear Sir or Madam, thank you for your email.", version=1)

    @pytest.fixture
    def valid_draft_v2(self):
        """Create a valid v2 draft."""
        return Draft(content="Dear Sir or Madam,\n\nThank you for your email. I will respond shortly.", version=2)

    @pytest.fixture
    def valid_critique(self):
        """Create a valid critique."""
        return Critique.from_response("VALID: This draft is excellent.")

    @pytest.fixture
    def invalid_critique(self):
        """Create an invalid critique."""
        return Critique.from_response("Please add more formal greeting.")

    def test_valid_processing_result_pending(self, valid_draft_v1, valid_critique):
        """Test creating ProcessingResult with PENDING status."""
        result = ProcessingResult(
            email_id="email-123",
            draft_v1=valid_draft_v1,
            critique=valid_critique,
            draft_final=valid_draft_v1,
            status=DraftStatus.PENDING
        )
        assert result.email_id == "email-123"
        assert result.draft_v1.version == 1
        assert result.critique.is_valid is True
        assert result.draft_final.version == 1
        assert result.status == DraftStatus.PENDING

    def test_valid_processing_result_validated_v1(self, valid_draft_v1, valid_critique):
        """Test ProcessingResult with VALIDATED_V1 status."""
        result = ProcessingResult(
            email_id="email-456",
            draft_v1=valid_draft_v1,
            critique=valid_critique,
            draft_final=valid_draft_v1,
            status=DraftStatus.VALIDATED_V1
        )
        assert result.status == DraftStatus.VALIDATED_V1
        assert result.was_corrected is False

    def test_valid_processing_result_corrected_v2(self, valid_draft_v1, valid_draft_v2, invalid_critique):
        """Test ProcessingResult with CORRECTED_V2 status."""
        result = ProcessingResult(
            email_id="email-789",
            draft_v1=valid_draft_v1,
            critique=invalid_critique,
            draft_final=valid_draft_v2,
            status=DraftStatus.CORRECTED_V2
        )
        assert result.status == DraftStatus.CORRECTED_V2
        assert result.was_corrected is True

    def test_valid_processing_result_rejected(self, valid_draft_v1, invalid_critique):
        """Test ProcessingResult with REJECTED status."""
        result = ProcessingResult(
            email_id="email-999",
            draft_v1=valid_draft_v1,
            critique=invalid_critique,
            draft_final=valid_draft_v1,
            status=DraftStatus.REJECTED
        )
        assert result.status == DraftStatus.REJECTED
        assert result.was_corrected is False

    def test_was_corrected_property_true(self, valid_draft_v1, valid_draft_v2, invalid_critique):
        """Test was_corrected property returns True when CORRECTED_V2."""
        result = ProcessingResult(
            email_id="email-111",
            draft_v1=valid_draft_v1,
            critique=invalid_critique,
            draft_final=valid_draft_v2,
            status=DraftStatus.CORRECTED_V2
        )
        assert result.was_corrected is True

    def test_was_corrected_property_false_pending(self, valid_draft_v1, valid_critique):
        """Test was_corrected property returns False for PENDING."""
        result = ProcessingResult(
            email_id="email-222",
            draft_v1=valid_draft_v1,
            critique=valid_critique,
            draft_final=valid_draft_v1,
            status=DraftStatus.PENDING
        )
        assert result.was_corrected is False

    def test_was_corrected_property_false_validated(self, valid_draft_v1, valid_critique):
        """Test was_corrected property returns False for VALIDATED_V1."""
        result = ProcessingResult(
            email_id="email-333",
            draft_v1=valid_draft_v1,
            critique=valid_critique,
            draft_final=valid_draft_v1,
            status=DraftStatus.VALIDATED_V1
        )
        assert result.was_corrected is False

    def test_was_corrected_property_false_rejected(self, valid_draft_v1, invalid_critique):
        """Test was_corrected property returns False for REJECTED."""
        result = ProcessingResult(
            email_id="email-444",
            draft_v1=valid_draft_v1,
            critique=invalid_critique,
            draft_final=valid_draft_v1,
            status=DraftStatus.REJECTED
        )
        assert result.was_corrected is False

    def test_processing_result_different_drafts(self, valid_draft_v1, valid_draft_v2, invalid_critique):
        """Test that draft_v1 and draft_final can be different."""
        result = ProcessingResult(
            email_id="email-555",
            draft_v1=valid_draft_v1,
            critique=invalid_critique,
            draft_final=valid_draft_v2,
            status=DraftStatus.CORRECTED_V2
        )
        assert result.draft_v1.version == 1
        assert result.draft_final.version == 2
        assert result.draft_v1.content != result.draft_final.content

    def test_processing_result_same_drafts_in_validation(self, valid_draft_v1, valid_critique):
        """Test that draft_v1 and draft_final are same when validated."""
        result = ProcessingResult(
            email_id="email-666",
            draft_v1=valid_draft_v1,
            critique=valid_critique,
            draft_final=valid_draft_v1,
            status=DraftStatus.VALIDATED_V1
        )
        assert result.draft_v1 is result.draft_final
        assert result.draft_v1.content == result.draft_final.content

    def test_processing_result_with_special_email_id(self, valid_draft_v1, valid_critique):
        """Test ProcessingResult with special characters in email_id."""
        email_id = "email-with-special-chars-éàù-123"
        result = ProcessingResult(
            email_id=email_id,
            draft_v1=valid_draft_v1,
            critique=valid_critique,
            draft_final=valid_draft_v1,
            status=DraftStatus.PENDING
        )
        assert result.email_id == email_id

    def test_processing_result_with_empty_draft_content(self, valid_critique):
        """Test ProcessingResult can handle empty draft content."""
        empty_draft = Draft(content="")
        result = ProcessingResult(
            email_id="email-empty",
            draft_v1=empty_draft,
            critique=valid_critique,
            draft_final=empty_draft,
            status=DraftStatus.PENDING
        )
        assert result.draft_v1.content == ""

    def test_processing_result_critique_reflects_status(self, valid_draft_v1, valid_draft_v2):
        """Test that critique validity should align with status."""
        # When status is VALIDATED_V1, critique should be valid
        valid_critique = Critique.from_response("VALID: Good draft.")
        result = ProcessingResult(
            email_id="email-777",
            draft_v1=valid_draft_v1,
            critique=valid_critique,
            draft_final=valid_draft_v1,
            status=DraftStatus.VALIDATED_V1
        )
        assert result.critique.is_valid is True
        assert result.was_corrected is False

        # When status is CORRECTED_V2, critique was likely invalid
        invalid_critique = Critique.from_response("Needs more detail.")
        result2 = ProcessingResult(
            email_id="email-888",
            draft_v1=valid_draft_v1,
            critique=invalid_critique,
            draft_final=valid_draft_v2,
            status=DraftStatus.CORRECTED_V2
        )
        assert result2.critique.is_valid is False
        assert result2.was_corrected is True

    def test_processing_result_all_status_values(self, valid_draft_v1, valid_critique):
        """Test ProcessingResult works with all status values."""
        statuses = [
            DraftStatus.PENDING,
            DraftStatus.VALIDATED_V1,
            DraftStatus.CORRECTED_V2,
            DraftStatus.REJECTED,
        ]
        for status in statuses:
            result = ProcessingResult(
                email_id=f"email-{status.value}",
                draft_v1=valid_draft_v1,
                critique=valid_critique,
                draft_final=valid_draft_v1,
                status=status
            )
            assert result.status == status


class TestDraftAndCritiqueIntegration:
    """Integration tests between Draft and Critique."""

    def test_draft_version_progression(self):
        """Test normal draft version progression workflow."""
        draft_v1 = Draft(content="Initial draft", version=1)
        draft_v2 = Draft(content="Revised draft", version=2)
        draft_v3 = Draft(content="Final draft", version=3)

        assert draft_v1.version < draft_v2.version
        assert draft_v2.version < draft_v3.version

    def test_critique_response_parsing_workflow(self):
        """Test typical workflow of parsing critique responses."""
        valid_response = "VALID: This is exactly what we needed."
        critique_valid = Critique.from_response(valid_response)
        assert critique_valid.is_valid is True

        invalid_response = "The tone needs to be more professional."
        critique_invalid = Critique.from_response(invalid_response)
        assert critique_invalid.is_valid is False
        assert critique_invalid.reason == invalid_response

    def test_processing_result_workflow_happy_path(self):
        """Test happy path: draft created, validated on first try."""
        draft_v1 = Draft(content="Thank you for your inquiry.", version=1)
        critique = Critique.from_response("VALID: Perfect response.")

        result = ProcessingResult(
            email_id="email-happy-path",
            draft_v1=draft_v1,
            critique=critique,
            draft_final=draft_v1,
            status=DraftStatus.VALIDATED_V1
        )

        assert result.draft_v1.version == 1
        assert result.draft_final.version == 1
        assert result.critique.is_valid is True
        assert result.was_corrected is False
        assert result.status == DraftStatus.VALIDATED_V1

    def test_processing_result_workflow_with_correction(self):
        """Test workflow: draft rejected, then corrected and validated."""
        draft_v1 = Draft(content="Thanks.", version=1)
        critique_reject = Critique.from_response("Too brief, needs more detail.")
        draft_v2 = Draft(content="Thank you for your inquiry. I will assist you shortly.", version=2)
        Critique.from_response("VALID: Much better.")

        # First attempt: rejected
        result_v1 = ProcessingResult(
            email_id="email-correction",
            draft_v1=draft_v1,
            critique=critique_reject,
            draft_final=draft_v1,
            status=DraftStatus.REJECTED
        )

        assert result_v1.was_corrected is False
        assert result_v1.status == DraftStatus.REJECTED

        # After correction: corrected
        result_v2 = ProcessingResult(
            email_id="email-correction",
            draft_v1=draft_v1,
            critique=critique_reject,
            draft_final=draft_v2,
            status=DraftStatus.CORRECTED_V2
        )

        assert result_v2.was_corrected is True
        assert result_v2.draft_final.version == 2
        assert result_v2.status == DraftStatus.CORRECTED_V2

    def test_multiple_corrections_scenario(self):
        """Test scenario with multiple correction iterations."""
        drafts = [
            Draft(content="Response", version=1),
            Draft(content="Thank you for your response.", version=2),
            Draft(content="Thank you for your inquiry. I appreciate you reaching out.", version=3),
        ]

        critiques = [
            Critique.from_response("Too vague."),
            Critique.from_response("Better, but could be warmer."),
            Critique.from_response("VALID: Excellent response."),
        ]

        # First attempt
        result1 = ProcessingResult(
            email_id="multi-correction",
            draft_v1=drafts[0],
            critique=critiques[0],
            draft_final=drafts[0],
            status=DraftStatus.REJECTED
        )
        assert result1.was_corrected is False

        # Second attempt
        result2 = ProcessingResult(
            email_id="multi-correction",
            draft_v1=drafts[0],
            critique=critiques[1],
            draft_final=drafts[1],
            status=DraftStatus.CORRECTED_V2
        )
        assert result2.was_corrected is True
        assert result2.draft_final.version == 2

        # Final attempt - though this would be a new processing
        result3 = ProcessingResult(
            email_id="multi-correction",
            draft_v1=drafts[0],
            critique=critiques[2],
            draft_final=drafts[2],
            status=DraftStatus.VALIDATED_V1
        )
        assert result3.was_corrected is False
        assert result3.status == DraftStatus.VALIDATED_V1
