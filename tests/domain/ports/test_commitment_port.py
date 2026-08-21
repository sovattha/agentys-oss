# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests pour CommitmentTrackerPort."""

import pytest
from abc import ABC
from typing import List, Optional

from app.domain.ports.commitment_port import CommitmentTrackerPort
from app.domain.entities.commitment import Commitment, CommitmentStatus


class TestCommitmentTrackerPortIsAbstract:
    """Verifie que CommitmentTrackerPort est une interface abstraite."""

    def test_inherits_from_abc(self):
        assert issubclass(CommitmentTrackerPort, ABC)

    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            CommitmentTrackerPort()


class TestCommitmentTrackerPortHasMethods:
    """Verifie que le port a toutes les methodes requises."""

    def test_has_add_commitment_method(self):
        assert hasattr(CommitmentTrackerPort, "add_commitment")

    def test_has_get_pending_method(self):
        assert hasattr(CommitmentTrackerPort, "get_pending")

    def test_has_get_by_email_method(self):
        assert hasattr(CommitmentTrackerPort, "get_by_email")

    def test_has_get_overdue_method(self):
        assert hasattr(CommitmentTrackerPort, "get_overdue")

    def test_has_mark_completed_method(self):
        assert hasattr(CommitmentTrackerPort, "mark_completed")

    def test_has_mark_cancelled_method(self):
        assert hasattr(CommitmentTrackerPort, "mark_cancelled")

    def test_has_get_by_id_method(self):
        assert hasattr(CommitmentTrackerPort, "get_by_id")

    def test_has_get_all_method(self):
        assert hasattr(CommitmentTrackerPort, "get_all")


class FakeCommitmentTracker(CommitmentTrackerPort):
    """Implementation fake pour tester le contrat du port."""

    def __init__(self):
        self._commitments: List[Commitment] = []

    def add_commitment(self, commitment: Commitment) -> None:
        self._commitments.append(commitment)

    def get_pending(self) -> List[Commitment]:
        return [c for c in self._commitments if c.status == CommitmentStatus.PENDING]

    def get_by_email(self, email_id: str) -> List[Commitment]:
        return [c for c in self._commitments if c.email_id == email_id]

    def get_overdue(self) -> List[Commitment]:
        return [c for c in self._commitments if c.status == CommitmentStatus.OVERDUE]

    def mark_completed(self, commitment_id: str) -> bool:
        for i, c in enumerate(self._commitments):
            if c.id == commitment_id:
                self._commitments[i] = c.mark_completed("2024-01-20T00:00:00Z")
                return True
        return False

    def mark_cancelled(self, commitment_id: str) -> bool:
        for i, c in enumerate(self._commitments):
            if c.id == commitment_id:
                self._commitments[i] = c.mark_cancelled()
                return True
        return False

    def get_by_id(self, commitment_id: str) -> Optional[Commitment]:
        for c in self._commitments:
            if c.id == commitment_id:
                return c
        return None

    def get_all(self) -> List[Commitment]:
        return list(self._commitments)


class TestFakeImplementation:
    """Verifie qu'une implementation concrete fonctionne."""

    @pytest.fixture
    def tracker(self):
        return FakeCommitmentTracker()

    @pytest.fixture
    def sample_commitment(self):
        return Commitment(
            id="commit-123",
            email_id="email-456",
            description="Test commitment",
            detected_at="2024-01-15T10:30:00Z",
            status=CommitmentStatus.PENDING,
        )

    def test_add_and_get_by_id(self, tracker, sample_commitment):
        tracker.add_commitment(sample_commitment)
        result = tracker.get_by_id("commit-123")
        assert result is not None
        assert result.id == "commit-123"

    def test_get_pending(self, tracker, sample_commitment):
        tracker.add_commitment(sample_commitment)
        pending = tracker.get_pending()
        assert len(pending) == 1
        assert pending[0].status == CommitmentStatus.PENDING

    def test_get_by_email(self, tracker, sample_commitment):
        tracker.add_commitment(sample_commitment)
        by_email = tracker.get_by_email("email-456")
        assert len(by_email) == 1
        assert by_email[0].email_id == "email-456"

    def test_mark_completed(self, tracker, sample_commitment):
        tracker.add_commitment(sample_commitment)
        result = tracker.mark_completed("commit-123")
        assert result is True
        updated = tracker.get_by_id("commit-123")
        assert updated.status == CommitmentStatus.COMPLETED

    def test_mark_completed_not_found(self, tracker):
        result = tracker.mark_completed("non-existent")
        assert result is False

    def test_mark_cancelled(self, tracker, sample_commitment):
        tracker.add_commitment(sample_commitment)
        result = tracker.mark_cancelled("commit-123")
        assert result is True
        updated = tracker.get_by_id("commit-123")
        assert updated.status == CommitmentStatus.CANCELLED

    def test_get_all(self, tracker, sample_commitment):
        tracker.add_commitment(sample_commitment)
        another = Commitment(
            id="commit-789",
            email_id="email-999",
            description="Another",
            detected_at="2024-01-16T10:30:00Z",
            status=CommitmentStatus.PENDING,
        )
        tracker.add_commitment(another)
        all_commitments = tracker.get_all()
        assert len(all_commitments) == 2


# =============================================================================
# Tests Edge Cases
# =============================================================================


class TestEdgeCasesEmptyTracker:
    """Tests des cas limites avec un tracker vide."""

    @pytest.fixture
    def tracker(self):
        return FakeCommitmentTracker()

    def test_get_pending_empty(self, tracker):
        """get_pending retourne une liste vide si aucun engagement."""
        result = tracker.get_pending()
        assert result == []
        assert isinstance(result, list)

    def test_get_by_email_empty(self, tracker):
        """get_by_email retourne une liste vide si aucun email."""
        result = tracker.get_by_email("non-existent-email")
        assert result == []
        assert isinstance(result, list)

    def test_get_overdue_empty(self, tracker):
        """get_overdue retourne une liste vide si aucun engagement en retard."""
        result = tracker.get_overdue()
        assert result == []
        assert isinstance(result, list)

    def test_get_all_empty(self, tracker):
        """get_all retourne une liste vide si aucun engagement."""
        result = tracker.get_all()
        assert result == []
        assert isinstance(result, list)

    def test_get_by_id_not_found(self, tracker):
        """get_by_id retourne None si l'ID n'existe pas."""
        result = tracker.get_by_id("non-existent-id")
        assert result is None

    def test_mark_cancelled_not_found(self, tracker):
        """mark_cancelled retourne False si l'ID n'existe pas."""
        result = tracker.mark_cancelled("non-existent-id")
        assert result is False


class TestEdgeCasesMultipleCommitments:
    """Tests avec plusieurs engagements."""

    @pytest.fixture
    def tracker(self):
        return FakeCommitmentTracker()

    @pytest.fixture
    def multiple_commitments(self, tracker):
        """Ajoute plusieurs engagements avec differents statuts et emails."""
        commits = [
            Commitment(
                id="pending-1",
                email_id="email-A",
                description="Pending 1",
                detected_at="2024-01-15T10:00:00Z",
                status=CommitmentStatus.PENDING,
            ),
            Commitment(
                id="pending-2",
                email_id="email-A",
                description="Pending 2",
                detected_at="2024-01-15T11:00:00Z",
                status=CommitmentStatus.PENDING,
            ),
            Commitment(
                id="completed-1",
                email_id="email-A",
                description="Completed 1",
                detected_at="2024-01-15T12:00:00Z",
                status=CommitmentStatus.COMPLETED,
                completed_at="2024-01-16T10:00:00Z",
            ),
            Commitment(
                id="overdue-1",
                email_id="email-B",
                description="Overdue 1",
                detected_at="2024-01-15T13:00:00Z",
                status=CommitmentStatus.OVERDUE,
                deadline="2024-01-10",
            ),
            Commitment(
                id="cancelled-1",
                email_id="email-B",
                description="Cancelled 1",
                detected_at="2024-01-15T14:00:00Z",
                status=CommitmentStatus.CANCELLED,
            ),
        ]
        for c in commits:
            tracker.add_commitment(c)
        return commits

    def test_get_pending_filters_correctly(self, tracker, multiple_commitments):
        """get_pending retourne uniquement les engagements PENDING."""
        pending = tracker.get_pending()
        assert len(pending) == 2
        for c in pending:
            assert c.status == CommitmentStatus.PENDING

    def test_get_overdue_filters_correctly(self, tracker, multiple_commitments):
        """get_overdue retourne uniquement les engagements OVERDUE."""
        overdue = tracker.get_overdue()
        assert len(overdue) == 1
        assert overdue[0].id == "overdue-1"
        assert overdue[0].status == CommitmentStatus.OVERDUE

    def test_get_by_email_filters_correctly(self, tracker, multiple_commitments):
        """get_by_email retourne tous les engagements pour un email."""
        email_a = tracker.get_by_email("email-A")
        assert len(email_a) == 3
        for c in email_a:
            assert c.email_id == "email-A"

        email_b = tracker.get_by_email("email-B")
        assert len(email_b) == 2
        for c in email_b:
            assert c.email_id == "email-B"

    def test_get_all_returns_all(self, tracker, multiple_commitments):
        """get_all retourne tous les engagements."""
        all_commits = tracker.get_all()
        assert len(all_commits) == 5

    def test_mark_completed_updates_status(self, tracker, multiple_commitments):
        """mark_completed met a jour le statut d'un engagement PENDING."""
        result = tracker.mark_completed("pending-1")
        assert result is True
        updated = tracker.get_by_id("pending-1")
        assert updated.status == CommitmentStatus.COMPLETED
        # Verifie que get_pending ne le retourne plus
        pending = tracker.get_pending()
        assert len(pending) == 1
        assert pending[0].id == "pending-2"

    def test_mark_cancelled_updates_status(self, tracker, multiple_commitments):
        """mark_cancelled met a jour le statut d'un engagement."""
        result = tracker.mark_cancelled("pending-2")
        assert result is True
        updated = tracker.get_by_id("pending-2")
        assert updated.status == CommitmentStatus.CANCELLED


class TestEdgeCasesSpecialValues:
    """Tests avec des valeurs speciales."""

    @pytest.fixture
    def tracker(self):
        return FakeCommitmentTracker()

    def test_empty_email_id(self, tracker):
        """get_by_email avec un email vide."""
        commit = Commitment(
            id="commit-1",
            email_id="",
            description="Empty email",
            detected_at="2024-01-15T10:00:00Z",
            status=CommitmentStatus.PENDING,
        )
        tracker.add_commitment(commit)
        result = tracker.get_by_email("")
        assert len(result) == 1
        assert result[0].email_id == ""

    def test_empty_id_get_by_id(self, tracker):
        """get_by_id avec un ID vide."""
        commit = Commitment(
            id="",
            email_id="email-1",
            description="Empty ID",
            detected_at="2024-01-15T10:00:00Z",
            status=CommitmentStatus.PENDING,
        )
        tracker.add_commitment(commit)
        result = tracker.get_by_id("")
        assert result is not None
        assert result.id == ""

    def test_mark_completed_empty_id(self, tracker):
        """mark_completed avec un ID vide."""
        commit = Commitment(
            id="",
            email_id="email-1",
            description="Empty ID",
            detected_at="2024-01-15T10:00:00Z",
            status=CommitmentStatus.PENDING,
        )
        tracker.add_commitment(commit)
        result = tracker.mark_completed("")
        assert result is True
        updated = tracker.get_by_id("")
        assert updated.status == CommitmentStatus.COMPLETED

    def test_unicode_email_id(self, tracker):
        """get_by_email avec des caracteres unicode."""
        commit = Commitment(
            id="commit-1",
            email_id="utilisateur@domaine.fr",
            description="Unicode email",
            detected_at="2024-01-15T10:00:00Z",
            status=CommitmentStatus.PENDING,
        )
        tracker.add_commitment(commit)
        result = tracker.get_by_email("utilisateur@domaine.fr")
        assert len(result) == 1

    def test_duplicate_commitment_ids(self, tracker):
        """Ajouter deux engagements avec le meme ID (edge case)."""
        commit1 = Commitment(
            id="duplicate-id",
            email_id="email-1",
            description="First",
            detected_at="2024-01-15T10:00:00Z",
            status=CommitmentStatus.PENDING,
        )
        commit2 = Commitment(
            id="duplicate-id",
            email_id="email-2",
            description="Second",
            detected_at="2024-01-15T11:00:00Z",
            status=CommitmentStatus.PENDING,
        )
        tracker.add_commitment(commit1)
        tracker.add_commitment(commit2)
        # Le comportement depend de l'implementation
        # Ici on verifie juste que get_all retourne les deux
        all_commits = tracker.get_all()
        assert len(all_commits) == 2


class TestEdgeCasesStateTransitions:
    """Tests des transitions d'etat."""

    @pytest.fixture
    def tracker(self):
        return FakeCommitmentTracker()

    def test_mark_completed_already_completed(self, tracker):
        """Marquer comme complete un engagement deja complete."""
        commit = Commitment(
            id="commit-1",
            email_id="email-1",
            description="Already completed",
            detected_at="2024-01-15T10:00:00Z",
            status=CommitmentStatus.COMPLETED,
            completed_at="2024-01-16T10:00:00Z",
        )
        tracker.add_commitment(commit)
        result = tracker.mark_completed("commit-1")
        assert result is True
        updated = tracker.get_by_id("commit-1")
        assert updated.status == CommitmentStatus.COMPLETED

    def test_mark_cancelled_already_cancelled(self, tracker):
        """Annuler un engagement deja annule."""
        commit = Commitment(
            id="commit-1",
            email_id="email-1",
            description="Already cancelled",
            detected_at="2024-01-15T10:00:00Z",
            status=CommitmentStatus.CANCELLED,
        )
        tracker.add_commitment(commit)
        result = tracker.mark_cancelled("commit-1")
        assert result is True
        updated = tracker.get_by_id("commit-1")
        assert updated.status == CommitmentStatus.CANCELLED

    def test_mark_completed_overdue(self, tracker):
        """Marquer comme complete un engagement en retard."""
        commit = Commitment(
            id="commit-1",
            email_id="email-1",
            description="Overdue",
            detected_at="2024-01-15T10:00:00Z",
            status=CommitmentStatus.OVERDUE,
            deadline="2024-01-10",
        )
        tracker.add_commitment(commit)
        result = tracker.mark_completed("commit-1")
        assert result is True
        updated = tracker.get_by_id("commit-1")
        assert updated.status == CommitmentStatus.COMPLETED

    def test_mark_cancelled_completed(self, tracker):
        """Annuler un engagement complete."""
        commit = Commitment(
            id="commit-1",
            email_id="email-1",
            description="Completed",
            detected_at="2024-01-15T10:00:00Z",
            status=CommitmentStatus.COMPLETED,
            completed_at="2024-01-16T10:00:00Z",
        )
        tracker.add_commitment(commit)
        result = tracker.mark_cancelled("commit-1")
        assert result is True
        updated = tracker.get_by_id("commit-1")
        assert updated.status == CommitmentStatus.CANCELLED
