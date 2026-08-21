# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests pour l'entite Commitment et l'enum CommitmentStatus."""

import pytest

from app.domain.entities.commitment import Commitment, CommitmentStatus


# =============================================================================
# Tests CommitmentStatus Enum
# =============================================================================


class TestCommitmentStatusEnum:
    """Tests pour l'enum CommitmentStatus."""

    def test_pending_value(self):
        assert CommitmentStatus.PENDING.value == "pending"

    def test_completed_value(self):
        assert CommitmentStatus.COMPLETED.value == "completed"

    def test_cancelled_value(self):
        assert CommitmentStatus.CANCELLED.value == "cancelled"

    def test_overdue_value(self):
        assert CommitmentStatus.OVERDUE.value == "overdue"

    def test_all_statuses_count(self):
        """Verifie qu'il y a exactement 4 statuts."""
        assert len(CommitmentStatus) == 4

    def test_status_is_enum(self):
        """Verifie que c'est bien un enum."""
        from enum import Enum

        assert issubclass(CommitmentStatus, Enum)

    def test_status_string_representation(self):
        """Verifie la representation string."""
        assert str(CommitmentStatus.PENDING) == "CommitmentStatus.PENDING"

    def test_status_can_be_compared(self):
        """Verifie les comparaisons."""
        assert CommitmentStatus.PENDING == CommitmentStatus.PENDING
        assert CommitmentStatus.PENDING != CommitmentStatus.COMPLETED

    def test_status_from_value(self):
        """Verifie la creation depuis une valeur."""
        assert CommitmentStatus("pending") == CommitmentStatus.PENDING
        assert CommitmentStatus("completed") == CommitmentStatus.COMPLETED

    def test_status_invalid_value_raises(self):
        """Verifie qu'une valeur invalide leve une exception."""
        with pytest.raises(ValueError):
            CommitmentStatus("invalid")


# =============================================================================
# Tests Commitment Entity - Creation
# =============================================================================


class TestCommitmentCreation:
    """Tests pour la creation d'un Commitment."""

    def test_create_minimal_commitment(self):
        """Creation avec les champs obligatoires uniquement."""
        commitment = Commitment(
            id="commit-001",
            email_id="email-001",
            description="Envoyer le rapport",
            detected_at="2024-01-15T10:00:00Z",
            status=CommitmentStatus.PENDING,
        )
        assert commitment.id == "commit-001"
        assert commitment.email_id == "email-001"
        assert commitment.description == "Envoyer le rapport"
        assert commitment.detected_at == "2024-01-15T10:00:00Z"
        assert commitment.status == CommitmentStatus.PENDING
        assert commitment.deadline is None
        assert commitment.completed_at is None

    def test_create_with_deadline(self):
        """Creation avec une deadline."""
        commitment = Commitment(
            id="commit-002",
            email_id="email-002",
            description="Finaliser le projet",
            detected_at="2024-01-15T10:00:00Z",
            status=CommitmentStatus.PENDING,
            deadline="2024-01-31",
        )
        assert commitment.deadline == "2024-01-31"

    def test_create_with_completed_at(self):
        """Creation avec une date de completion."""
        commitment = Commitment(
            id="commit-003",
            email_id="email-003",
            description="Tache terminee",
            detected_at="2024-01-15T10:00:00Z",
            status=CommitmentStatus.COMPLETED,
            completed_at="2024-01-20T15:30:00Z",
        )
        assert commitment.completed_at == "2024-01-20T15:30:00Z"

    def test_create_with_all_fields(self):
        """Creation avec tous les champs."""
        commitment = Commitment(
            id="commit-004",
            email_id="email-004",
            description="Tache complete",
            detected_at="2024-01-15T10:00:00Z",
            status=CommitmentStatus.COMPLETED,
            deadline="2024-01-31",
            completed_at="2024-01-20T15:30:00Z",
        )
        assert commitment.id == "commit-004"
        assert commitment.deadline == "2024-01-31"
        assert commitment.completed_at == "2024-01-20T15:30:00Z"


# =============================================================================
# Tests Commitment Entity - Edge Cases
# =============================================================================


class TestCommitmentEdgeCases:
    """Tests des cas limites pour Commitment."""

    def test_empty_id(self):
        """Un ID vide est techniquement permis mais devrait etre evite."""
        commitment = Commitment(
            id="",
            email_id="email-001",
            description="Test",
            detected_at="2024-01-15T10:00:00Z",
            status=CommitmentStatus.PENDING,
        )
        assert commitment.id == ""

    def test_empty_description(self):
        """Une description vide est techniquement permise."""
        commitment = Commitment(
            id="commit-001",
            email_id="email-001",
            description="",
            detected_at="2024-01-15T10:00:00Z",
            status=CommitmentStatus.PENDING,
        )
        assert commitment.description == ""

    def test_very_long_description(self):
        """Une tres longue description."""
        long_desc = "A" * 10000
        commitment = Commitment(
            id="commit-001",
            email_id="email-001",
            description=long_desc,
            detected_at="2024-01-15T10:00:00Z",
            status=CommitmentStatus.PENDING,
        )
        assert len(commitment.description) == 10000

    def test_unicode_description(self):
        """Une description avec des caracteres unicode."""
        commitment = Commitment(
            id="commit-001",
            email_id="email-001",
            description="Reunion a 15h avec equipe japonaise",
            detected_at="2024-01-15T10:00:00Z",
            status=CommitmentStatus.PENDING,
        )
        assert "Reunion" in commitment.description

    def test_special_characters_in_id(self):
        """Des caracteres speciaux dans l'ID."""
        commitment = Commitment(
            id="commit-001-abc_xyz",
            email_id="email@special.chars",
            description="Test",
            detected_at="2024-01-15T10:00:00Z",
            status=CommitmentStatus.PENDING,
        )
        assert commitment.id == "commit-001-abc_xyz"

    def test_whitespace_only_description(self):
        """Une description avec uniquement des espaces."""
        commitment = Commitment(
            id="commit-001",
            email_id="email-001",
            description="   ",
            detected_at="2024-01-15T10:00:00Z",
            status=CommitmentStatus.PENDING,
        )
        assert commitment.description == "   "

    def test_newlines_in_description(self):
        """Des retours a la ligne dans la description."""
        desc = "Ligne 1\nLigne 2\nLigne 3"
        commitment = Commitment(
            id="commit-001",
            email_id="email-001",
            description=desc,
            detected_at="2024-01-15T10:00:00Z",
            status=CommitmentStatus.PENDING,
        )
        assert "\n" in commitment.description


# =============================================================================
# Tests Commitment Entity - Immutability (mark_* methods)
# =============================================================================


class TestCommitmentMarkCompleted:
    """Tests pour la methode mark_completed."""

    @pytest.fixture
    def pending_commitment(self):
        return Commitment(
            id="commit-001",
            email_id="email-001",
            description="Tache en cours",
            detected_at="2024-01-15T10:00:00Z",
            status=CommitmentStatus.PENDING,
        )

    def test_mark_completed_returns_new_instance(self, pending_commitment):
        """mark_completed retourne une nouvelle instance."""
        completed = pending_commitment.mark_completed("2024-01-20T15:30:00Z")
        assert completed is not pending_commitment

    def test_mark_completed_preserves_original(self, pending_commitment):
        """L'instance originale n'est pas modifiee."""
        pending_commitment.mark_completed("2024-01-20T15:30:00Z")
        assert pending_commitment.status == CommitmentStatus.PENDING
        assert pending_commitment.completed_at is None

    def test_mark_completed_sets_status(self, pending_commitment):
        """Le statut est bien COMPLETED."""
        completed = pending_commitment.mark_completed("2024-01-20T15:30:00Z")
        assert completed.status == CommitmentStatus.COMPLETED

    def test_mark_completed_sets_completed_at(self, pending_commitment):
        """La date de completion est definie."""
        completed = pending_commitment.mark_completed("2024-01-20T15:30:00Z")
        assert completed.completed_at == "2024-01-20T15:30:00Z"

    def test_mark_completed_preserves_other_fields(self, pending_commitment):
        """Les autres champs sont preserves."""
        completed = pending_commitment.mark_completed("2024-01-20T15:30:00Z")
        assert completed.id == pending_commitment.id
        assert completed.email_id == pending_commitment.email_id
        assert completed.description == pending_commitment.description
        assert completed.detected_at == pending_commitment.detected_at

    def test_mark_completed_with_deadline_preserves_deadline(self):
        """La deadline est preservee."""
        commitment = Commitment(
            id="commit-001",
            email_id="email-001",
            description="Tache",
            detected_at="2024-01-15T10:00:00Z",
            status=CommitmentStatus.PENDING,
            deadline="2024-01-31",
        )
        completed = commitment.mark_completed("2024-01-20T15:30:00Z")
        assert completed.deadline == "2024-01-31"

    def test_mark_completed_idempotent(self):
        """Marquer comme complete un engagement deja complete."""
        commitment = Commitment(
            id="commit-001",
            email_id="email-001",
            description="Deja complete",
            detected_at="2024-01-15T10:00:00Z",
            status=CommitmentStatus.COMPLETED,
            completed_at="2024-01-18T10:00:00Z",
        )
        completed_again = commitment.mark_completed("2024-01-20T15:30:00Z")
        assert completed_again.status == CommitmentStatus.COMPLETED
        assert completed_again.completed_at == "2024-01-20T15:30:00Z"


class TestCommitmentMarkCancelled:
    """Tests pour la methode mark_cancelled."""

    @pytest.fixture
    def pending_commitment(self):
        return Commitment(
            id="commit-001",
            email_id="email-001",
            description="Tache en cours",
            detected_at="2024-01-15T10:00:00Z",
            status=CommitmentStatus.PENDING,
        )

    def test_mark_cancelled_returns_new_instance(self, pending_commitment):
        """mark_cancelled retourne une nouvelle instance."""
        cancelled = pending_commitment.mark_cancelled()
        assert cancelled is not pending_commitment

    def test_mark_cancelled_preserves_original(self, pending_commitment):
        """L'instance originale n'est pas modifiee."""
        pending_commitment.mark_cancelled()
        assert pending_commitment.status == CommitmentStatus.PENDING

    def test_mark_cancelled_sets_status(self, pending_commitment):
        """Le statut est bien CANCELLED."""
        cancelled = pending_commitment.mark_cancelled()
        assert cancelled.status == CommitmentStatus.CANCELLED

    def test_mark_cancelled_preserves_other_fields(self, pending_commitment):
        """Les autres champs sont preserves."""
        cancelled = pending_commitment.mark_cancelled()
        assert cancelled.id == pending_commitment.id
        assert cancelled.email_id == pending_commitment.email_id
        assert cancelled.description == pending_commitment.description
        assert cancelled.detected_at == pending_commitment.detected_at

    def test_mark_cancelled_does_not_set_completed_at(self, pending_commitment):
        """completed_at reste None."""
        cancelled = pending_commitment.mark_cancelled()
        assert cancelled.completed_at is None

    def test_mark_cancelled_from_completed(self):
        """Annuler un engagement complete."""
        commitment = Commitment(
            id="commit-001",
            email_id="email-001",
            description="Complete",
            detected_at="2024-01-15T10:00:00Z",
            status=CommitmentStatus.COMPLETED,
            completed_at="2024-01-20T15:30:00Z",
        )
        cancelled = commitment.mark_cancelled()
        assert cancelled.status == CommitmentStatus.CANCELLED
        # completed_at est preserve car c'est une copie
        assert cancelled.completed_at == "2024-01-20T15:30:00Z"


class TestCommitmentMarkOverdue:
    """Tests pour la methode mark_overdue."""

    @pytest.fixture
    def pending_commitment(self):
        return Commitment(
            id="commit-001",
            email_id="email-001",
            description="Tache en retard",
            detected_at="2024-01-15T10:00:00Z",
            status=CommitmentStatus.PENDING,
            deadline="2024-01-20",
        )

    def test_mark_overdue_returns_new_instance(self, pending_commitment):
        """mark_overdue retourne une nouvelle instance."""
        overdue = pending_commitment.mark_overdue()
        assert overdue is not pending_commitment

    def test_mark_overdue_preserves_original(self, pending_commitment):
        """L'instance originale n'est pas modifiee."""
        pending_commitment.mark_overdue()
        assert pending_commitment.status == CommitmentStatus.PENDING

    def test_mark_overdue_sets_status(self, pending_commitment):
        """Le statut est bien OVERDUE."""
        overdue = pending_commitment.mark_overdue()
        assert overdue.status == CommitmentStatus.OVERDUE

    def test_mark_overdue_preserves_deadline(self, pending_commitment):
        """La deadline est preservee."""
        overdue = pending_commitment.mark_overdue()
        assert overdue.deadline == "2024-01-20"

    def test_mark_overdue_without_deadline(self):
        """Marquer overdue un engagement sans deadline."""
        commitment = Commitment(
            id="commit-001",
            email_id="email-001",
            description="Sans deadline",
            detected_at="2024-01-15T10:00:00Z",
            status=CommitmentStatus.PENDING,
        )
        overdue = commitment.mark_overdue()
        assert overdue.status == CommitmentStatus.OVERDUE
        assert overdue.deadline is None


# =============================================================================
# Tests Commitment Entity - Equality & Hashing
# =============================================================================


class TestCommitmentEquality:
    """Tests pour l'egalite et le hachage."""

    def test_equal_commitments(self):
        """Deux commitments identiques sont egaux."""
        c1 = Commitment(
            id="commit-001",
            email_id="email-001",
            description="Test",
            detected_at="2024-01-15T10:00:00Z",
            status=CommitmentStatus.PENDING,
        )
        c2 = Commitment(
            id="commit-001",
            email_id="email-001",
            description="Test",
            detected_at="2024-01-15T10:00:00Z",
            status=CommitmentStatus.PENDING,
        )
        assert c1 == c2

    def test_different_id_not_equal(self):
        """Des IDs differents -> pas egaux."""
        c1 = Commitment(
            id="commit-001",
            email_id="email-001",
            description="Test",
            detected_at="2024-01-15T10:00:00Z",
            status=CommitmentStatus.PENDING,
        )
        c2 = Commitment(
            id="commit-002",
            email_id="email-001",
            description="Test",
            detected_at="2024-01-15T10:00:00Z",
            status=CommitmentStatus.PENDING,
        )
        assert c1 != c2

    def test_different_status_not_equal(self):
        """Des statuts differents -> pas egaux."""
        c1 = Commitment(
            id="commit-001",
            email_id="email-001",
            description="Test",
            detected_at="2024-01-15T10:00:00Z",
            status=CommitmentStatus.PENDING,
        )
        c2 = Commitment(
            id="commit-001",
            email_id="email-001",
            description="Test",
            detected_at="2024-01-15T10:00:00Z",
            status=CommitmentStatus.COMPLETED,
        )
        assert c1 != c2

    def test_commitment_not_hashable(self):
        """Les commitments mutables ne sont pas hashables (comportement attendu)."""
        c = Commitment(
            id="commit-001",
            email_id="email-001",
            description="Test",
            detected_at="2024-01-15T10:00:00Z",
            status=CommitmentStatus.PENDING,
        )
        # Une dataclass mutable n'est pas hashable par defaut
        with pytest.raises(TypeError):
            hash(c)

    def test_commitments_in_list(self):
        """Les commitments peuvent etre dans une liste."""
        c1 = Commitment(
            id="commit-001",
            email_id="email-001",
            description="Test",
            detected_at="2024-01-15T10:00:00Z",
            status=CommitmentStatus.PENDING,
        )
        c2 = Commitment(
            id="commit-002",
            email_id="email-001",
            description="Test",
            detected_at="2024-01-15T10:00:00Z",
            status=CommitmentStatus.PENDING,
        )
        commitment_list = [c1, c2]
        assert len(commitment_list) == 2

    def test_commitment_as_dict_value(self):
        """Les commitments peuvent etre des valeurs de dictionnaire."""
        c = Commitment(
            id="commit-001",
            email_id="email-001",
            description="Test",
            detected_at="2024-01-15T10:00:00Z",
            status=CommitmentStatus.PENDING,
        )
        d = {"key": c}
        assert d["key"] == c


# =============================================================================
# Tests Commitment Entity - Type Checks
# =============================================================================


class TestCommitmentTypeChecks:
    """Tests de verification des types."""

    def test_is_dataclass(self):
        """Commitment est une dataclass."""
        from dataclasses import is_dataclass

        assert is_dataclass(Commitment)

    def test_required_fields_types(self):
        """Les champs obligatoires ont les bons types."""
        c = Commitment(
            id="commit-001",
            email_id="email-001",
            description="Test",
            detected_at="2024-01-15T10:00:00Z",
            status=CommitmentStatus.PENDING,
        )
        assert isinstance(c.id, str)
        assert isinstance(c.email_id, str)
        assert isinstance(c.description, str)
        assert isinstance(c.detected_at, str)
        assert isinstance(c.status, CommitmentStatus)

    def test_optional_fields_default_to_none(self):
        """Les champs optionnels sont None par defaut."""
        c = Commitment(
            id="commit-001",
            email_id="email-001",
            description="Test",
            detected_at="2024-01-15T10:00:00Z",
            status=CommitmentStatus.PENDING,
        )
        assert c.deadline is None
        assert c.completed_at is None

    def test_missing_required_field_raises(self):
        """Un champ obligatoire manquant leve une exception."""
        with pytest.raises(TypeError):
            Commitment(
                id="commit-001",
                email_id="email-001",
                # missing description
                detected_at="2024-01-15T10:00:00Z",
                status=CommitmentStatus.PENDING,
            )
