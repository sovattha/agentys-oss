# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests pour CommitmentTrackingUseCase."""

import pytest
from unittest.mock import Mock

from app.agents import ExtractedCommitment
from app.domain.entities.commitment import Commitment, CommitmentStatus
from app.domain.ports.commitment_port import CommitmentTrackerPort
from app.application.commitment_tracking import CommitmentTrackingUseCase


@pytest.fixture
def mock_tracker():
    return Mock(spec=CommitmentTrackerPort)


@pytest.fixture
def use_case(mock_tracker):
    return CommitmentTrackingUseCase(tracker=mock_tracker)


@pytest.fixture
def sample_commitment():
    return Commitment(
        id="commit-123",
        email_id="email-456",
        description="Envoyer le rapport demain",
        detected_at="2024-01-15T10:30:00Z",
        status=CommitmentStatus.PENDING,
        deadline="2024-01-16",
    )


class TestTrackCommitment:
    """Tests pour track_commitment."""

    def test_delegates_to_port(self, use_case, mock_tracker, sample_commitment):
        use_case.track_commitment(sample_commitment)
        mock_tracker.add_commitment.assert_called_once_with(sample_commitment)

    def test_returns_none(self, use_case, mock_tracker, sample_commitment):
        result = use_case.track_commitment(sample_commitment)
        assert result is None


class TestGetPending:
    """Tests pour get_pending."""

    def test_delegates_to_port(self, use_case, mock_tracker):
        mock_tracker.get_pending.return_value = []
        use_case.get_pending()
        mock_tracker.get_pending.assert_called_once()

    def test_returns_port_result(self, use_case, mock_tracker, sample_commitment):
        expected = [sample_commitment]
        mock_tracker.get_pending.return_value = expected
        result = use_case.get_pending()
        assert result == expected


class TestGetOverdue:
    """Tests pour get_overdue."""

    def test_delegates_to_port(self, use_case, mock_tracker):
        mock_tracker.get_overdue.return_value = []
        use_case.get_overdue()
        mock_tracker.get_overdue.assert_called_once()

    def test_returns_port_result(self, use_case, mock_tracker, sample_commitment):
        overdue_commitment = Commitment(
            id="commit-789",
            email_id="email-999",
            description="Engagement en retard",
            detected_at="2024-01-10T10:00:00Z",
            status=CommitmentStatus.OVERDUE,
            deadline="2024-01-12",
        )
        expected = [overdue_commitment]
        mock_tracker.get_overdue.return_value = expected
        result = use_case.get_overdue()
        assert result == expected


class TestComplete:
    """Tests pour complete."""

    def test_delegates_to_port(self, use_case, mock_tracker):
        mock_tracker.mark_completed.return_value = True
        use_case.complete("commit-123")
        mock_tracker.mark_completed.assert_called_once_with("commit-123")

    def test_returns_true_when_found(self, use_case, mock_tracker):
        mock_tracker.mark_completed.return_value = True
        result = use_case.complete("commit-123")
        assert result is True

    def test_returns_false_when_not_found(self, use_case, mock_tracker):
        mock_tracker.mark_completed.return_value = False
        result = use_case.complete("non-existent")
        assert result is False


class TestCancel:
    """Tests pour cancel."""

    def test_delegates_to_port(self, use_case, mock_tracker):
        mock_tracker.mark_cancelled.return_value = True
        use_case.cancel("commit-123")
        mock_tracker.mark_cancelled.assert_called_once_with("commit-123")

    def test_returns_true_when_found(self, use_case, mock_tracker):
        mock_tracker.mark_cancelled.return_value = True
        result = use_case.cancel("commit-123")
        assert result is True

    def test_returns_false_when_not_found(self, use_case, mock_tracker):
        mock_tracker.mark_cancelled.return_value = False
        result = use_case.cancel("non-existent")
        assert result is False


class TestGetByEmail:
    """Tests pour get_by_email."""

    def test_delegates_to_port(self, use_case, mock_tracker):
        mock_tracker.get_by_email.return_value = []
        use_case.get_by_email("email-456")
        mock_tracker.get_by_email.assert_called_once_with("email-456")

    def test_returns_port_result(self, use_case, mock_tracker, sample_commitment):
        expected = [sample_commitment]
        mock_tracker.get_by_email.return_value = expected
        result = use_case.get_by_email("email-456")
        assert result == expected

    def test_returns_empty_list_when_no_match(self, use_case, mock_tracker):
        mock_tracker.get_by_email.return_value = []
        result = use_case.get_by_email("unknown-email")
        assert result == []


class TestGetById:
    """Tests pour get_by_id."""

    def test_delegates_to_port(self, use_case, mock_tracker):
        mock_tracker.get_by_id.return_value = None
        use_case.get_by_id("commit-123")
        mock_tracker.get_by_id.assert_called_once_with("commit-123")

    def test_returns_commitment_when_found(self, use_case, mock_tracker, sample_commitment):
        mock_tracker.get_by_id.return_value = sample_commitment
        result = use_case.get_by_id("commit-123")
        assert result == sample_commitment

    def test_returns_none_when_not_found(self, use_case, mock_tracker):
        mock_tracker.get_by_id.return_value = None
        result = use_case.get_by_id("non-existent")
        assert result is None


class TestGetAll:
    """Tests pour get_all."""

    def test_delegates_to_port(self, use_case, mock_tracker):
        mock_tracker.get_all.return_value = []
        use_case.get_all()
        mock_tracker.get_all.assert_called_once()

    def test_returns_port_result(self, use_case, mock_tracker, sample_commitment):
        expected = [sample_commitment]
        mock_tracker.get_all.return_value = expected
        result = use_case.get_all()
        assert result == expected

    def test_returns_empty_list_when_no_commitments(self, use_case, mock_tracker):
        mock_tracker.get_all.return_value = []
        result = use_case.get_all()
        assert result == []


# =============================================================================
# Edge Cases Tests
# =============================================================================


class TestEdgeCasesEmptyStrings:
    """Tests pour les cas limites avec des strings vides."""

    def test_complete_with_empty_id(self, use_case, mock_tracker):
        mock_tracker.mark_completed.return_value = False
        result = use_case.complete("")
        mock_tracker.mark_completed.assert_called_once_with("")
        assert result is False

    def test_cancel_with_empty_id(self, use_case, mock_tracker):
        mock_tracker.mark_cancelled.return_value = False
        result = use_case.cancel("")
        mock_tracker.mark_cancelled.assert_called_once_with("")
        assert result is False

    def test_get_by_id_with_empty_id(self, use_case, mock_tracker):
        mock_tracker.get_by_id.return_value = None
        result = use_case.get_by_id("")
        mock_tracker.get_by_id.assert_called_once_with("")
        assert result is None

    def test_get_by_email_with_empty_id(self, use_case, mock_tracker):
        mock_tracker.get_by_email.return_value = []
        result = use_case.get_by_email("")
        mock_tracker.get_by_email.assert_called_once_with("")
        assert result == []


class TestEdgeCasesMultipleItems:
    """Tests avec plusieurs engagements."""

    def test_get_pending_returns_multiple_items(self, use_case, mock_tracker):
        commitments = [
            Commitment(
                id=f"commit-{i}",
                email_id=f"email-{i}",
                description=f"Engagement {i}",
                detected_at="2024-01-15T10:30:00Z",
                status=CommitmentStatus.PENDING,
            )
            for i in range(5)
        ]
        mock_tracker.get_pending.return_value = commitments
        result = use_case.get_pending()
        assert len(result) == 5
        assert result == commitments

    def test_get_overdue_returns_multiple_items(self, use_case, mock_tracker):
        commitments = [
            Commitment(
                id=f"commit-{i}",
                email_id=f"email-{i}",
                description=f"Engagement en retard {i}",
                detected_at="2024-01-10T10:00:00Z",
                status=CommitmentStatus.OVERDUE,
            )
            for i in range(3)
        ]
        mock_tracker.get_overdue.return_value = commitments
        result = use_case.get_overdue()
        assert len(result) == 3
        assert result == commitments

    def test_get_by_email_returns_multiple_items(self, use_case, mock_tracker):
        email_id = "email-shared"
        commitments = [
            Commitment(
                id=f"commit-{i}",
                email_id=email_id,
                description=f"Engagement {i}",
                detected_at="2024-01-15T10:30:00Z",
                status=CommitmentStatus.PENDING,
            )
            for i in range(4)
        ]
        mock_tracker.get_by_email.return_value = commitments
        result = use_case.get_by_email(email_id)
        assert len(result) == 4
        assert all(c.email_id == email_id for c in result)

    def test_get_all_returns_multiple_items_with_different_statuses(
        self, use_case, mock_tracker
    ):
        statuses = [
            CommitmentStatus.PENDING,
            CommitmentStatus.COMPLETED,
            CommitmentStatus.CANCELLED,
            CommitmentStatus.OVERDUE,
        ]
        commitments = [
            Commitment(
                id=f"commit-{i}",
                email_id=f"email-{i}",
                description=f"Engagement {status.value}",
                detected_at="2024-01-15T10:30:00Z",
                status=status,
            )
            for i, status in enumerate(statuses)
        ]
        mock_tracker.get_all.return_value = commitments
        result = use_case.get_all()
        assert len(result) == 4
        assert {c.status for c in result} == set(statuses)


class TestEdgeCasesExceptions:
    """Tests pour le comportement quand le port leve des exceptions."""

    def test_track_commitment_propagates_exception(self, use_case, mock_tracker, sample_commitment):
        mock_tracker.add_commitment.side_effect = RuntimeError("Storage error")
        with pytest.raises(RuntimeError, match="Storage error"):
            use_case.track_commitment(sample_commitment)

    def test_get_pending_propagates_exception(self, use_case, mock_tracker):
        mock_tracker.get_pending.side_effect = RuntimeError("Database error")
        with pytest.raises(RuntimeError, match="Database error"):
            use_case.get_pending()

    def test_get_overdue_propagates_exception(self, use_case, mock_tracker):
        mock_tracker.get_overdue.side_effect = RuntimeError("Database error")
        with pytest.raises(RuntimeError, match="Database error"):
            use_case.get_overdue()

    def test_complete_propagates_exception(self, use_case, mock_tracker):
        mock_tracker.mark_completed.side_effect = RuntimeError("Update error")
        with pytest.raises(RuntimeError, match="Update error"):
            use_case.complete("commit-123")

    def test_cancel_propagates_exception(self, use_case, mock_tracker):
        mock_tracker.mark_cancelled.side_effect = RuntimeError("Update error")
        with pytest.raises(RuntimeError, match="Update error"):
            use_case.cancel("commit-123")

    def test_get_by_email_propagates_exception(self, use_case, mock_tracker):
        mock_tracker.get_by_email.side_effect = RuntimeError("Query error")
        with pytest.raises(RuntimeError, match="Query error"):
            use_case.get_by_email("email-456")

    def test_get_by_id_propagates_exception(self, use_case, mock_tracker):
        mock_tracker.get_by_id.side_effect = RuntimeError("Query error")
        with pytest.raises(RuntimeError, match="Query error"):
            use_case.get_by_id("commit-123")

    def test_get_all_propagates_exception(self, use_case, mock_tracker):
        mock_tracker.get_all.side_effect = RuntimeError("Query error")
        with pytest.raises(RuntimeError, match="Query error"):
            use_case.get_all()


class TestEdgeCasesSpecialCharacters:
    """Tests avec des caracteres speciaux dans les IDs."""

    def test_complete_with_special_characters(self, use_case, mock_tracker):
        special_id = "commit-123!@#$%^&*()"
        mock_tracker.mark_completed.return_value = True
        result = use_case.complete(special_id)
        mock_tracker.mark_completed.assert_called_once_with(special_id)
        assert result is True

    def test_get_by_id_with_unicode(self, use_case, mock_tracker, sample_commitment):
        unicode_id = "commit-日本語-émojis-🎉"
        mock_tracker.get_by_id.return_value = sample_commitment
        use_case.get_by_id(unicode_id)
        mock_tracker.get_by_id.assert_called_once_with(unicode_id)

    def test_get_by_email_with_whitespace(self, use_case, mock_tracker):
        whitespace_id = "  email with spaces  "
        mock_tracker.get_by_email.return_value = []
        use_case.get_by_email(whitespace_id)
        mock_tracker.get_by_email.assert_called_once_with(whitespace_id)


class TestUseCaseInitialization:
    """Tests pour l'initialisation du use case."""

    def test_use_case_stores_tracker(self, mock_tracker):
        use_case = CommitmentTrackingUseCase(tracker=mock_tracker)
        assert use_case.tracker is mock_tracker

    def test_use_case_is_dataclass(self):
        from dataclasses import is_dataclass
        assert is_dataclass(CommitmentTrackingUseCase)


# =============================================================================
# Tests for track_from_extracted
# =============================================================================


class TestTrackFromExtracted:
    """Tests pour track_from_extracted."""

    def test_converts_and_saves_single_commitment(self, use_case, mock_tracker):
        extracted = [ExtractedCommitment(description="Envoyer le rapport", deadline="2024-01-20")]
        result = use_case.track_from_extracted(extracted, "email-123")

        assert len(result) == 1
        assert mock_tracker.add_commitment.call_count == 1
        saved_commitment = mock_tracker.add_commitment.call_args[0][0]
        assert saved_commitment.email_id == "email-123"
        assert saved_commitment.description == "Envoyer le rapport"
        assert saved_commitment.deadline == "2024-01-20"
        assert saved_commitment.status == CommitmentStatus.PENDING

    def test_converts_and_saves_multiple_commitments(self, use_case, mock_tracker):
        extracted = [
            ExtractedCommitment(description="Première tâche", deadline="2024-01-15"),
            ExtractedCommitment(description="Deuxième tâche", deadline=None),
        ]
        result = use_case.track_from_extracted(extracted, "email-456")

        assert len(result) == 2
        assert mock_tracker.add_commitment.call_count == 2

    def test_returns_created_commitments(self, use_case, mock_tracker):
        extracted = [ExtractedCommitment(description="Rappeler client", deadline=None)]
        result = use_case.track_from_extracted(extracted, "email-789")

        assert len(result) == 1
        assert isinstance(result[0], Commitment)
        assert result[0].description == "Rappeler client"
        assert result[0].email_id == "email-789"

    def test_empty_list_returns_empty_result(self, use_case, mock_tracker):
        result = use_case.track_from_extracted([], "email-000")

        assert result == []
        mock_tracker.add_commitment.assert_not_called()

    def test_commitment_id_is_generated(self, use_case, mock_tracker):
        extracted = [ExtractedCommitment(description="Test ID", deadline=None)]
        result = use_case.track_from_extracted(extracted, "email-id-test")

        assert result[0].id is not None
        assert "email-id-test" in result[0].id

    def test_detected_at_is_set(self, use_case, mock_tracker):
        extracted = [ExtractedCommitment(description="Test date", deadline=None)]
        result = use_case.track_from_extracted(extracted, "email-date")

        assert result[0].detected_at is not None

    def test_handles_none_deadline(self, use_case, mock_tracker):
        extracted = [ExtractedCommitment(description="Sans deadline", deadline=None)]
        result = use_case.track_from_extracted(extracted, "email-no-deadline")

        assert result[0].deadline is None


class TestTrackFromExtractedEdgeCases:
    """Tests edge cases pour track_from_extracted."""

    def test_description_with_unicode_characters(self, use_case, mock_tracker):
        """Teste les descriptions avec caractères Unicode."""
        extracted = [
            ExtractedCommitment(
                description="Réunion 日本語 émojis 🎉 café ñ",
                deadline="2024-01-20"
            )
        ]
        result = use_case.track_from_extracted(extracted, "email-unicode")

        assert len(result) == 1
        assert result[0].description == "Réunion 日本語 émojis 🎉 café ñ"
        mock_tracker.add_commitment.assert_called_once()

    def test_description_with_special_characters(self, use_case, mock_tracker):
        """Teste les descriptions avec caractères spéciaux."""
        extracted = [
            ExtractedCommitment(
                description="Test <script>alert('xss')</script> & \"quotes\" 'single'",
                deadline=None
            )
        ]
        result = use_case.track_from_extracted(extracted, "email-special")

        assert len(result) == 1
        assert "<script>" in result[0].description
        mock_tracker.add_commitment.assert_called_once()

    def test_empty_description(self, use_case, mock_tracker):
        """Teste une description vide."""
        extracted = [ExtractedCommitment(description="", deadline=None)]
        result = use_case.track_from_extracted(extracted, "email-empty-desc")

        assert len(result) == 1
        assert result[0].description == ""
        mock_tracker.add_commitment.assert_called_once()

    def test_whitespace_only_description(self, use_case, mock_tracker):
        """Teste une description avec uniquement des espaces."""
        extracted = [ExtractedCommitment(description="   \t\n  ", deadline=None)]
        result = use_case.track_from_extracted(extracted, "email-whitespace")

        assert len(result) == 1
        assert result[0].description == "   \t\n  "
        mock_tracker.add_commitment.assert_called_once()

    def test_very_long_description(self, use_case, mock_tracker):
        """Teste une description très longue."""
        long_desc = "A" * 10000
        extracted = [ExtractedCommitment(description=long_desc, deadline=None)]
        result = use_case.track_from_extracted(extracted, "email-long")

        assert len(result) == 1
        assert len(result[0].description) == 10000
        mock_tracker.add_commitment.assert_called_once()

    def test_multiple_commitments_same_hash(self, use_case, mock_tracker):
        """Teste plusieurs engagements avec même description (même hash)."""
        extracted = [
            ExtractedCommitment(description="Same description", deadline=None),
            ExtractedCommitment(description="Same description", deadline=None),
        ]
        result = use_case.track_from_extracted(extracted, "email-same")

        assert len(result) == 2
        # Les deux auront le même ID (basé sur hash)
        assert result[0].id == result[1].id
        assert mock_tracker.add_commitment.call_count == 2

    def test_large_batch_of_commitments(self, use_case, mock_tracker):
        """Teste un grand nombre d'engagements."""
        extracted = [
            ExtractedCommitment(description=f"Engagement {i}", deadline=None)
            for i in range(100)
        ]
        result = use_case.track_from_extracted(extracted, "email-batch")

        assert len(result) == 100
        assert mock_tracker.add_commitment.call_count == 100

    def test_exception_during_add_stops_processing(self, use_case, mock_tracker):
        """Teste qu'une exception arrête le traitement (pas de partial save silencieux)."""
        mock_tracker.add_commitment.side_effect = RuntimeError("DB Error")

        extracted = [
            ExtractedCommitment(description="First", deadline=None),
            ExtractedCommitment(description="Second", deadline=None),
        ]

        with pytest.raises(RuntimeError, match="DB Error"):
            use_case.track_from_extracted(extracted, "email-error")

    def test_exception_on_second_add_preserves_first(self, use_case, mock_tracker):
        """Teste qu'une exception sur le 2e add n'affecte pas le 1er appel."""
        mock_tracker.add_commitment.side_effect = [None, RuntimeError("DB Error")]

        extracted = [
            ExtractedCommitment(description="First", deadline=None),
            ExtractedCommitment(description="Second", deadline=None),
        ]

        with pytest.raises(RuntimeError, match="DB Error"):
            use_case.track_from_extracted(extracted, "email-partial")

        # Le premier add a été appelé
        assert mock_tracker.add_commitment.call_count == 2

    def test_deadline_format_variations(self, use_case, mock_tracker):
        """Teste différents formats de deadline."""
        extracted = [
            ExtractedCommitment(description="ISO date", deadline="2024-01-15"),
            ExtractedCommitment(description="ISO datetime", deadline="2024-01-15T10:30:00Z"),
            ExtractedCommitment(description="Natural", deadline="vendredi prochain"),
        ]
        result = use_case.track_from_extracted(extracted, "email-dates")

        assert len(result) == 3
        assert result[0].deadline == "2024-01-15"
        assert result[1].deadline == "2024-01-15T10:30:00Z"
        assert result[2].deadline == "vendredi prochain"

    def test_email_id_with_special_characters(self, use_case, mock_tracker):
        """Teste un email_id avec caractères spéciaux."""
        special_email_id = "email-<test>-123!@#$%"
        extracted = [ExtractedCommitment(description="Test", deadline=None)]
        result = use_case.track_from_extracted(extracted, special_email_id)

        assert len(result) == 1
        assert result[0].email_id == special_email_id
        assert special_email_id in result[0].id

    def test_newlines_in_description(self, use_case, mock_tracker):
        """Teste une description avec retours à la ligne."""
        extracted = [
            ExtractedCommitment(
                description="Ligne 1\nLigne 2\r\nLigne 3",
                deadline=None
            )
        ]
        result = use_case.track_from_extracted(extracted, "email-newlines")

        assert len(result) == 1
        assert "\n" in result[0].description
