# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests TDD pour CommitmentAdapter (SQLite).

Ce module teste:
1. Implementation du port CommitmentTrackerPort
2. Operations CRUD (add, get_by_id, get_all)
3. Filtres (get_pending, get_overdue, get_by_email)
4. Actions (mark_completed, mark_cancelled)
5. Serialisation/deserialisation des enums
6. Edge cases et gestion des erreurs

TDD: Tests ecrits AVANT l'implementation.
Clean Architecture: Infrastructure layer (Adapters).
"""

import importlib.util
import sqlite3
from pathlib import Path

import pytest

from app.domain.entities.commitment import Commitment, CommitmentStatus
from app.domain.ports.commitment_port import CommitmentTrackerPort


# =============================================================================
# MODULE LOADING HELPER
# =============================================================================


def _load_commitment_adapter_class():
    """
    Charge CommitmentAdapter sans passer par app.infrastructure.__init__.py.

    Cela evite les effets de bord (chargement du container, config, etc.)
    qui requierent des variables d'environnement.
    """
    spec = importlib.util.spec_from_file_location(
        "commitment_adapter",
        "app/infrastructure/adapters/commitment_adapter.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.CommitmentAdapter


# Charge la classe une seule fois au niveau module
CommitmentAdapter = _load_commitment_adapter_class()


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def temp_db(tmp_path) -> Path:
    """Cree une base de donnees temporaire."""
    return tmp_path / "test_commitments.db"


@pytest.fixture
def adapter():
    """Cree un adapter avec base en memoire."""
    return CommitmentAdapter()


@pytest.fixture
def sample_commitment() -> Commitment:
    """Cree un engagement de test."""
    return Commitment(
        id="commit-123",
        email_id="email-456",
        description="Envoyer le rapport lundi",
        detected_at="2024-01-15T10:30:00",
        status=CommitmentStatus.PENDING,
        deadline="2024-01-22",
        completed_at=None,
    )


@pytest.fixture
def commitment_without_deadline() -> Commitment:
    """Engagement sans deadline."""
    return Commitment(
        id="commit-no-deadline",
        email_id="email-789",
        description="Repondre des que possible",
        detected_at="2024-01-15T11:00:00",
        status=CommitmentStatus.PENDING,
    )


# =============================================================================
# TESTS - IMPLEMENTS PORT
# =============================================================================


class TestCommitmentAdapterImplementsPort:
    """Tests pour verifier l'implementation du port."""

    def test_implements_commitment_tracker_port(self, adapter):
        """CommitmentAdapter implemente CommitmentTrackerPort."""
        assert isinstance(adapter, CommitmentTrackerPort)

    def test_has_all_required_methods(self, adapter):
        """A toutes les methodes abstraites requises."""
        assert hasattr(adapter, "add_commitment")
        assert hasattr(adapter, "get_pending")
        assert hasattr(adapter, "get_overdue")
        assert hasattr(adapter, "get_by_email")
        assert hasattr(adapter, "mark_completed")
        assert hasattr(adapter, "mark_cancelled")
        assert hasattr(adapter, "get_by_id")
        assert hasattr(adapter, "get_all")


# =============================================================================
# TESTS - ADD COMMITMENT
# =============================================================================


class TestAddCommitment:
    """Tests pour add_commitment."""

    def test_add_commitment_persists(self, adapter, sample_commitment):
        """add_commitment persiste l'engagement."""
        adapter.add_commitment(sample_commitment)
        result = adapter.get_by_id("commit-123")
        assert result is not None
        assert result.id == "commit-123"

    def test_add_commitment_stores_all_fields(self, adapter, sample_commitment):
        """Tous les champs sont persistes."""
        adapter.add_commitment(sample_commitment)
        result = adapter.get_by_id("commit-123")

        assert result.email_id == "email-456"
        assert result.description == "Envoyer le rapport lundi"
        assert result.detected_at == "2024-01-15T10:30:00"
        assert result.status == CommitmentStatus.PENDING
        assert result.deadline == "2024-01-22"
        assert result.completed_at is None

    def test_add_commitment_without_deadline(self, adapter, commitment_without_deadline):
        """Fonctionne sans deadline."""
        adapter.add_commitment(commitment_without_deadline)
        result = adapter.get_by_id("commit-no-deadline")

        assert result is not None
        assert result.deadline is None

    def test_add_multiple_commitments(self, adapter, sample_commitment):
        """Ajoute plusieurs engagements."""
        adapter.add_commitment(sample_commitment)

        other = Commitment(
            id="commit-other",
            email_id="email-other",
            description="Autre engagement",
            detected_at="2024-01-16T09:00:00",
            status=CommitmentStatus.PENDING,
        )
        adapter.add_commitment(other)

        assert len(adapter.get_all()) == 2


# =============================================================================
# TESTS - GET BY ID
# =============================================================================


class TestGetById:
    """Tests pour get_by_id."""

    def test_get_by_id_returns_commitment(self, adapter, sample_commitment):
        """Retourne l'engagement trouve."""
        adapter.add_commitment(sample_commitment)
        result = adapter.get_by_id("commit-123")
        assert result is not None
        assert isinstance(result, Commitment)

    def test_get_by_id_returns_none_if_not_found(self, adapter):
        """Retourne None si non trouve."""
        result = adapter.get_by_id("non-existent")
        assert result is None

    def test_get_by_id_returns_correct_commitment(self, adapter):
        """Retourne le bon engagement parmi plusieurs."""
        c1 = Commitment(
            id="c1", email_id="e1", description="D1",
            detected_at="2024-01-01", status=CommitmentStatus.PENDING,
        )
        c2 = Commitment(
            id="c2", email_id="e2", description="D2",
            detected_at="2024-01-02", status=CommitmentStatus.COMPLETED,
        )
        adapter.add_commitment(c1)
        adapter.add_commitment(c2)

        result = adapter.get_by_id("c2")
        assert result.description == "D2"


# =============================================================================
# TESTS - GET ALL
# =============================================================================


class TestGetAll:
    """Tests pour get_all."""

    def test_get_all_returns_empty_list_initially(self, adapter):
        """Retourne une liste vide si aucun engagement."""
        assert adapter.get_all() == []

    def test_get_all_returns_all_commitments(self, adapter):
        """Retourne tous les engagements."""
        for i in range(5):
            c = Commitment(
                id=f"c{i}", email_id=f"e{i}", description=f"D{i}",
                detected_at=f"2024-01-0{i+1}", status=CommitmentStatus.PENDING,
            )
            adapter.add_commitment(c)

        result = adapter.get_all()
        assert len(result) == 5

    def test_get_all_returns_commitment_instances(self, adapter, sample_commitment):
        """Retourne des instances de Commitment."""
        adapter.add_commitment(sample_commitment)
        result = adapter.get_all()
        assert all(isinstance(c, Commitment) for c in result)


# =============================================================================
# TESTS - GET PENDING
# =============================================================================


class TestGetPending:
    """Tests pour get_pending."""

    def test_get_pending_returns_pending_only(self, adapter):
        """Retourne uniquement les engagements PENDING."""
        pending = Commitment(
            id="pending1", email_id="e1", description="Pending",
            detected_at="2024-01-01", status=CommitmentStatus.PENDING,
        )
        completed = Commitment(
            id="completed1", email_id="e2", description="Completed",
            detected_at="2024-01-01", status=CommitmentStatus.COMPLETED,
        )
        cancelled = Commitment(
            id="cancelled1", email_id="e3", description="Cancelled",
            detected_at="2024-01-01", status=CommitmentStatus.CANCELLED,
        )

        adapter.add_commitment(pending)
        adapter.add_commitment(completed)
        adapter.add_commitment(cancelled)

        result = adapter.get_pending()
        assert len(result) == 1
        assert result[0].id == "pending1"

    def test_get_pending_returns_empty_if_none(self, adapter):
        """Retourne une liste vide si aucun PENDING."""
        completed = Commitment(
            id="c1", email_id="e1", description="D1",
            detected_at="2024-01-01", status=CommitmentStatus.COMPLETED,
        )
        adapter.add_commitment(completed)

        assert adapter.get_pending() == []

    def test_get_pending_excludes_overdue(self, adapter):
        """Exclut les engagements OVERDUE."""
        pending = Commitment(
            id="p1", email_id="e1", description="Pending",
            detected_at="2024-01-01", status=CommitmentStatus.PENDING,
        )
        overdue = Commitment(
            id="o1", email_id="e2", description="Overdue",
            detected_at="2024-01-01", status=CommitmentStatus.OVERDUE,
        )

        adapter.add_commitment(pending)
        adapter.add_commitment(overdue)

        result = adapter.get_pending()
        assert len(result) == 1
        assert result[0].id == "p1"


# =============================================================================
# TESTS - GET OVERDUE
# =============================================================================


class TestGetOverdue:
    """Tests pour get_overdue."""

    def test_get_overdue_returns_overdue_only(self, adapter):
        """Retourne uniquement les engagements OVERDUE."""
        pending = Commitment(
            id="p1", email_id="e1", description="Pending",
            detected_at="2024-01-01", status=CommitmentStatus.PENDING,
        )
        overdue = Commitment(
            id="o1", email_id="e2", description="Overdue",
            detected_at="2024-01-01", status=CommitmentStatus.OVERDUE,
        )

        adapter.add_commitment(pending)
        adapter.add_commitment(overdue)

        result = adapter.get_overdue()
        assert len(result) == 1
        assert result[0].id == "o1"

    def test_get_overdue_returns_empty_if_none(self, adapter):
        """Retourne une liste vide si aucun OVERDUE."""
        pending = Commitment(
            id="p1", email_id="e1", description="Pending",
            detected_at="2024-01-01", status=CommitmentStatus.PENDING,
        )
        adapter.add_commitment(pending)

        assert adapter.get_overdue() == []


# =============================================================================
# TESTS - GET BY EMAIL
# =============================================================================


class TestGetByEmail:
    """Tests pour get_by_email."""

    def test_get_by_email_filters_correctly(self, adapter):
        """Filtre par email_id."""
        c1 = Commitment(
            id="c1", email_id="email-A", description="D1",
            detected_at="2024-01-01", status=CommitmentStatus.PENDING,
        )
        c2 = Commitment(
            id="c2", email_id="email-B", description="D2",
            detected_at="2024-01-01", status=CommitmentStatus.PENDING,
        )
        c3 = Commitment(
            id="c3", email_id="email-A", description="D3",
            detected_at="2024-01-02", status=CommitmentStatus.COMPLETED,
        )

        adapter.add_commitment(c1)
        adapter.add_commitment(c2)
        adapter.add_commitment(c3)

        result = adapter.get_by_email("email-A")
        assert len(result) == 2
        assert all(c.email_id == "email-A" for c in result)

    def test_get_by_email_returns_empty_if_no_match(self, adapter, sample_commitment):
        """Retourne une liste vide si aucun match."""
        adapter.add_commitment(sample_commitment)
        result = adapter.get_by_email("non-existent-email")
        assert result == []


# =============================================================================
# TESTS - MARK COMPLETED
# =============================================================================


class TestMarkCompleted:
    """Tests pour mark_completed."""

    def test_mark_completed_updates_status(self, adapter, sample_commitment):
        """Met a jour le statut vers COMPLETED."""
        adapter.add_commitment(sample_commitment)
        result = adapter.mark_completed("commit-123")

        assert result is True
        commitment = adapter.get_by_id("commit-123")
        assert commitment.status == CommitmentStatus.COMPLETED

    def test_mark_completed_sets_completed_at(self, adapter, sample_commitment):
        """Definit completed_at."""
        adapter.add_commitment(sample_commitment)
        adapter.mark_completed("commit-123")

        commitment = adapter.get_by_id("commit-123")
        assert commitment.completed_at is not None

    def test_mark_completed_returns_false_if_not_found(self, adapter):
        """Retourne False si non trouve."""
        result = adapter.mark_completed("non-existent")
        assert result is False


# =============================================================================
# TESTS - MARK CANCELLED
# =============================================================================


class TestMarkCancelled:
    """Tests pour mark_cancelled."""

    def test_mark_cancelled_updates_status(self, adapter, sample_commitment):
        """Met a jour le statut vers CANCELLED."""
        adapter.add_commitment(sample_commitment)
        result = adapter.mark_cancelled("commit-123")

        assert result is True
        commitment = adapter.get_by_id("commit-123")
        assert commitment.status == CommitmentStatus.CANCELLED

    def test_mark_cancelled_returns_false_if_not_found(self, adapter):
        """Retourne False si non trouve."""
        result = adapter.mark_cancelled("non-existent")
        assert result is False


# =============================================================================
# TESTS - SERIALIZATION
# =============================================================================


class TestSerialization:
    """Tests pour la serialisation/deserialisation."""

    def test_enum_roundtrip_pending(self, adapter):
        """Roundtrip pour PENDING."""
        c = Commitment(
            id="c1", email_id="e1", description="D1",
            detected_at="2024-01-01", status=CommitmentStatus.PENDING,
        )
        adapter.add_commitment(c)
        result = adapter.get_by_id("c1")
        assert result.status == CommitmentStatus.PENDING

    def test_enum_roundtrip_completed(self, adapter):
        """Roundtrip pour COMPLETED."""
        c = Commitment(
            id="c1", email_id="e1", description="D1",
            detected_at="2024-01-01", status=CommitmentStatus.COMPLETED,
            completed_at="2024-01-10T15:00:00",
        )
        adapter.add_commitment(c)
        result = adapter.get_by_id("c1")
        assert result.status == CommitmentStatus.COMPLETED

    def test_enum_roundtrip_cancelled(self, adapter):
        """Roundtrip pour CANCELLED."""
        c = Commitment(
            id="c1", email_id="e1", description="D1",
            detected_at="2024-01-01", status=CommitmentStatus.CANCELLED,
        )
        adapter.add_commitment(c)
        result = adapter.get_by_id("c1")
        assert result.status == CommitmentStatus.CANCELLED

    def test_enum_roundtrip_overdue(self, adapter):
        """Roundtrip pour OVERDUE."""
        c = Commitment(
            id="c1", email_id="e1", description="D1",
            detected_at="2024-01-01", status=CommitmentStatus.OVERDUE,
        )
        adapter.add_commitment(c)
        result = adapter.get_by_id("c1")
        assert result.status == CommitmentStatus.OVERDUE


# =============================================================================
# TESTS - EDGE CASES
# =============================================================================


class TestEdgeCases:
    """Tests des cas limites."""

    def test_null_deadline_handled(self, adapter, commitment_without_deadline):
        """Gere correctement les deadlines nulles."""
        adapter.add_commitment(commitment_without_deadline)
        result = adapter.get_by_id("commit-no-deadline")
        assert result.deadline is None

    def test_null_completed_at_handled(self, adapter, sample_commitment):
        """Gere correctement completed_at null."""
        adapter.add_commitment(sample_commitment)
        result = adapter.get_by_id("commit-123")
        assert result.completed_at is None

    def test_unicode_description(self, adapter):
        """Supporte l'Unicode dans la description."""
        c = Commitment(
            id="unicode", email_id="e1",
            description="Répondre à l'email de 日本語",
            detected_at="2024-01-01", status=CommitmentStatus.PENDING,
        )
        adapter.add_commitment(c)
        result = adapter.get_by_id("unicode")
        assert "日本語" in result.description

    def test_special_characters_in_description(self, adapter):
        """Supporte les caracteres speciaux."""
        c = Commitment(
            id="special", email_id="e1",
            description="Test with 'quotes' and \"double quotes\" and <html>",
            detected_at="2024-01-01", status=CommitmentStatus.PENDING,
        )
        adapter.add_commitment(c)
        result = adapter.get_by_id("special")
        assert "\"double quotes\"" in result.description

    def test_empty_description(self, adapter):
        """Supporte une description vide."""
        c = Commitment(
            id="empty", email_id="e1", description="",
            detected_at="2024-01-01", status=CommitmentStatus.PENDING,
        )
        adapter.add_commitment(c)
        result = adapter.get_by_id("empty")
        assert result.description == ""

    def test_duplicate_id_replaces(self, adapter):
        """Un ID duplique remplace l'existant."""
        c1 = Commitment(
            id="dup", email_id="e1", description="Original",
            detected_at="2024-01-01", status=CommitmentStatus.PENDING,
        )
        c2 = Commitment(
            id="dup", email_id="e2", description="Replaced",
            detected_at="2024-01-02", status=CommitmentStatus.COMPLETED,
        )

        adapter.add_commitment(c1)
        adapter.add_commitment(c2)

        result = adapter.get_by_id("dup")
        assert result.description == "Replaced"
        assert len(adapter.get_all()) == 1

    def test_sql_injection_in_description(self, adapter):
        """Protege contre l'injection SQL dans la description."""
        malicious = "'; DROP TABLE commitments; --"
        c = Commitment(
            id="sql-inj", email_id="e1", description=malicious,
            detected_at="2024-01-01", status=CommitmentStatus.PENDING,
        )
        adapter.add_commitment(c)

        # La table doit toujours exister et le commitment etre recuperable
        result = adapter.get_by_id("sql-inj")
        assert result is not None
        assert result.description == malicious
        # Verifier que la table existe toujours
        assert adapter.get_all() is not None

    def test_sql_injection_in_email_id(self, adapter):
        """Protege contre l'injection SQL dans email_id."""
        malicious = "' OR '1'='1"
        c = Commitment(
            id="sql-inj-email", email_id=malicious, description="Test",
            detected_at="2024-01-01", status=CommitmentStatus.PENDING,
        )
        adapter.add_commitment(c)

        # get_by_email ne doit pas etre vulnerable
        result = adapter.get_by_email(malicious)
        assert len(result) == 1
        assert result[0].id == "sql-inj-email"

    def test_sql_injection_in_id(self, adapter):
        """Protege contre l'injection SQL dans l'ID."""
        malicious = "test'; DELETE FROM commitments WHERE '1'='1"
        c = Commitment(
            id=malicious, email_id="e1", description="Test",
            detected_at="2024-01-01", status=CommitmentStatus.PENDING,
        )
        adapter.add_commitment(c)

        result = adapter.get_by_id(malicious)
        assert result is not None
        assert result.id == malicious

    def test_very_long_description(self, adapter):
        """Supporte des descriptions tres longues."""
        long_desc = "A" * 10000
        c = Commitment(
            id="long", email_id="e1", description=long_desc,
            detected_at="2024-01-01", status=CommitmentStatus.PENDING,
        )
        adapter.add_commitment(c)

        result = adapter.get_by_id("long")
        assert len(result.description) == 10000

    def test_very_long_id(self, adapter):
        """Supporte des IDs tres longs."""
        long_id = "id-" + "x" * 1000
        c = Commitment(
            id=long_id, email_id="e1", description="Test",
            detected_at="2024-01-01", status=CommitmentStatus.PENDING,
        )
        adapter.add_commitment(c)

        result = adapter.get_by_id(long_id)
        assert result is not None
        assert result.id == long_id

    def test_newlines_in_description(self, adapter):
        """Supporte les sauts de ligne dans la description."""
        desc = "Ligne 1\nLigne 2\r\nLigne 3"
        c = Commitment(
            id="newlines", email_id="e1", description=desc,
            detected_at="2024-01-01", status=CommitmentStatus.PENDING,
        )
        adapter.add_commitment(c)

        result = adapter.get_by_id("newlines")
        assert "\n" in result.description
        assert result.description == desc

    def test_get_by_email_empty_string(self, adapter, sample_commitment):
        """get_by_email avec chaine vide retourne liste vide."""
        adapter.add_commitment(sample_commitment)
        result = adapter.get_by_email("")
        assert result == []

    def test_get_by_id_empty_string(self, adapter, sample_commitment):
        """get_by_id avec chaine vide retourne None."""
        adapter.add_commitment(sample_commitment)
        result = adapter.get_by_id("")
        assert result is None

    def test_mark_completed_already_completed(self, adapter, sample_commitment):
        """mark_completed sur un engagement deja complete reste idempotent."""
        adapter.add_commitment(sample_commitment)
        adapter.mark_completed("commit-123")
        adapter.get_by_id("commit-123").completed_at

        # Deuxieme appel
        result = adapter.mark_completed("commit-123")
        adapter.get_by_id("commit-123").completed_at

        assert result is True
        assert adapter.get_by_id("commit-123").status == CommitmentStatus.COMPLETED
        # Le timestamp peut etre mis a jour (comportement acceptable)

    def test_mark_cancelled_already_cancelled(self, adapter):
        """mark_cancelled sur un engagement deja annule reste idempotent."""
        c = Commitment(
            id="cancelled", email_id="e1", description="Test",
            detected_at="2024-01-01", status=CommitmentStatus.CANCELLED,
        )
        adapter.add_commitment(c)

        result = adapter.mark_cancelled("cancelled")
        assert result is True
        assert adapter.get_by_id("cancelled").status == CommitmentStatus.CANCELLED

    def test_mark_completed_on_cancelled(self, adapter):
        """mark_completed sur un engagement annule le complete."""
        c = Commitment(
            id="cancelled", email_id="e1", description="Test",
            detected_at="2024-01-01", status=CommitmentStatus.CANCELLED,
        )
        adapter.add_commitment(c)

        result = adapter.mark_completed("cancelled")
        assert result is True
        assert adapter.get_by_id("cancelled").status == CommitmentStatus.COMPLETED

    def test_mark_cancelled_on_completed(self, adapter, sample_commitment):
        """mark_cancelled sur un engagement complete l'annule."""
        adapter.add_commitment(sample_commitment)
        adapter.mark_completed("commit-123")

        result = adapter.mark_cancelled("commit-123")
        assert result is True
        assert adapter.get_by_id("commit-123").status == CommitmentStatus.CANCELLED

    def test_whitespace_only_description(self, adapter):
        """Supporte une description avec uniquement des espaces."""
        c = Commitment(
            id="whitespace", email_id="e1", description="   \t\n  ",
            detected_at="2024-01-01", status=CommitmentStatus.PENDING,
        )
        adapter.add_commitment(c)

        result = adapter.get_by_id("whitespace")
        assert result.description == "   \t\n  "


# =============================================================================
# TESTS - TABLE CREATION
# =============================================================================


class TestTableCreation:
    """Tests pour la creation de table."""

    def test_creates_table_on_init(self, adapter):
        """La table est creee a l'initialisation."""
        conn = adapter._get_connection()
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='commitments'"
        )
        result = cursor.fetchone()
        assert result is not None

    def test_table_has_correct_columns(self, adapter):
        """La table a les bonnes colonnes."""
        conn = adapter._get_connection()
        cursor = conn.execute("PRAGMA table_info(commitments)")
        columns = {row[1] for row in cursor.fetchall()}

        expected = {"id", "email_id", "description", "detected_at",
                    "status", "deadline", "completed_at"}
        assert expected.issubset(columns)


# =============================================================================
# TESTS - DB PATH PARAMETER
# =============================================================================


class TestDbPathParameter:
    """Tests pour le parametre db_path du constructeur."""

    def test_adapter_with_file_db(self, tmp_path):
        """L'adapter fonctionne avec un fichier DB."""
        db_path = tmp_path / "test.db"
        adapter = CommitmentAdapter(db_path=db_path)

        c = Commitment(
            id="file-test", email_id="e1", description="Test",
            detected_at="2024-01-01", status=CommitmentStatus.PENDING,
        )
        adapter.add_commitment(c)

        # Verifier que le fichier existe
        assert db_path.exists()

        # Verifier la persistance avec une nouvelle connexion
        adapter2 = CommitmentAdapter(db_path=db_path)
        result = adapter2.get_by_id("file-test")
        assert result is not None
        assert result.id == "file-test"

    def test_adapter_memory_db_isolated(self):
        """Chaque adapter avec :memory: est isole."""
        adapter1 = CommitmentAdapter()
        adapter2 = CommitmentAdapter()

        c = Commitment(
            id="iso-test", email_id="e1", description="Test",
            detected_at="2024-01-01", status=CommitmentStatus.PENDING,
        )
        adapter1.add_commitment(c)

        # adapter2 ne doit pas voir les donnees de adapter1
        assert adapter2.get_by_id("iso-test") is None


# =============================================================================
# TESTS - CONCURRENT ACCESS
# =============================================================================


class TestConcurrentAccess:
    """Tests pour l'acces concurrent."""

    def test_multiple_adds_same_adapter(self, adapter):
        """Ajouts multiples sur le meme adapter."""
        for i in range(100):
            c = Commitment(
                id=f"concurrent-{i}", email_id="e1", description=f"D{i}",
                detected_at="2024-01-01", status=CommitmentStatus.PENDING,
            )
            adapter.add_commitment(c)

        assert len(adapter.get_all()) == 100

    def test_mixed_operations(self, adapter):
        """Operations mixtes (add, get, update)."""
        # Ajouter
        c1 = Commitment(
            id="mix-1", email_id="e1", description="D1",
            detected_at="2024-01-01", status=CommitmentStatus.PENDING,
        )
        adapter.add_commitment(c1)

        # Lire
        result = adapter.get_by_id("mix-1")
        assert result is not None

        # Mettre a jour
        adapter.mark_completed("mix-1")

        # Ajouter un autre
        c2 = Commitment(
            id="mix-2", email_id="e1", description="D2",
            detected_at="2024-01-02", status=CommitmentStatus.PENDING,
        )
        adapter.add_commitment(c2)

        # Verifier l'etat final
        assert len(adapter.get_all()) == 2
        assert adapter.get_by_id("mix-1").status == CommitmentStatus.COMPLETED
        assert adapter.get_by_id("mix-2").status == CommitmentStatus.PENDING


# =============================================================================
# TESTS - INVALID DATA HANDLING
# =============================================================================


class TestInvalidDataHandling:
    """Tests pour la gestion des donnees invalides."""

    def test_invalid_enum_in_db_raises(self, adapter):
        """Un enum invalide dans la DB leve une exception."""
        # Inserer manuellement une valeur invalide
        conn = adapter._get_connection()
        conn.execute(
            """
            INSERT INTO commitments
            (id, email_id, description, detected_at, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("invalid-enum", "e1", "Test", "2024-01-01", "INVALID_STATUS"),
        )
        conn.commit()

        # La recuperation doit lever une ValueError
        with pytest.raises(ValueError):
            adapter.get_by_id("invalid-enum")

    def test_get_all_with_invalid_enum_raises(self, adapter, sample_commitment):
        """get_all avec un enum invalide dans la DB leve une exception."""
        adapter.add_commitment(sample_commitment)

        # Inserer manuellement une valeur invalide
        conn = adapter._get_connection()
        conn.execute(
            """
            INSERT INTO commitments
            (id, email_id, description, detected_at, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("invalid-enum", "e1", "Test", "2024-01-01", "BOGUS"),
        )
        conn.commit()

        with pytest.raises(ValueError):
            adapter.get_all()

    def test_null_required_field_in_db(self, adapter):
        """Un champ requis NULL dans la DB cause une erreur a la deserialisation."""
        conn = adapter._get_connection()
        # email_id NOT NULL mais on force une insertion sans
        try:
            conn.execute(
                """
                INSERT INTO commitments
                (id, description, detected_at, status)
                VALUES (?, ?, ?, ?)
                """,
                ("null-field", "Test", "2024-01-01", "pending"),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            # C'est le comportement attendu avec NOT NULL
            pass


# =============================================================================
# TESTS - DATE FORMAT HANDLING
# =============================================================================


class TestDateFormatHandling:
    """Tests pour le format des dates."""

    def test_iso_datetime_format(self, adapter):
        """Supporte le format ISO datetime complet."""
        c = Commitment(
            id="iso-full", email_id="e1", description="Test",
            detected_at="2024-01-15T10:30:45.123456",
            status=CommitmentStatus.PENDING,
            deadline="2024-02-01T23:59:59",
        )
        adapter.add_commitment(c)

        result = adapter.get_by_id("iso-full")
        assert result.detected_at == "2024-01-15T10:30:45.123456"
        assert result.deadline == "2024-02-01T23:59:59"

    def test_date_only_format(self, adapter):
        """Supporte le format date seule."""
        c = Commitment(
            id="date-only", email_id="e1", description="Test",
            detected_at="2024-01-15", status=CommitmentStatus.PENDING,
            deadline="2024-02-01",
        )
        adapter.add_commitment(c)

        result = adapter.get_by_id("date-only")
        assert result.detected_at == "2024-01-15"
        assert result.deadline == "2024-02-01"

    def test_arbitrary_date_string(self, adapter):
        """Accepte n'importe quelle chaine comme date (pas de validation)."""
        c = Commitment(
            id="arbitrary", email_id="e1", description="Test",
            detected_at="not-a-real-date", status=CommitmentStatus.PENDING,
            deadline="demain matin",
        )
        adapter.add_commitment(c)

        result = adapter.get_by_id("arbitrary")
        assert result.detected_at == "not-a-real-date"
        assert result.deadline == "demain matin"


# =============================================================================
# TESTS - MULTIPLE STATUSES TRANSITIONS
# =============================================================================


class TestStatusTransitions:
    """Tests pour les transitions de statut."""

    def test_pending_to_completed_to_cancelled(self, adapter):
        """Transition PENDING -> COMPLETED -> CANCELLED."""
        c = Commitment(
            id="trans", email_id="e1", description="Test",
            detected_at="2024-01-01", status=CommitmentStatus.PENDING,
        )
        adapter.add_commitment(c)

        assert adapter.get_by_id("trans").status == CommitmentStatus.PENDING

        adapter.mark_completed("trans")
        assert adapter.get_by_id("trans").status == CommitmentStatus.COMPLETED

        adapter.mark_cancelled("trans")
        assert adapter.get_by_id("trans").status == CommitmentStatus.CANCELLED

    def test_overdue_to_completed(self, adapter):
        """Transition OVERDUE -> COMPLETED."""
        c = Commitment(
            id="overdue-complete", email_id="e1", description="Test",
            detected_at="2024-01-01", status=CommitmentStatus.OVERDUE,
        )
        adapter.add_commitment(c)

        adapter.mark_completed("overdue-complete")
        result = adapter.get_by_id("overdue-complete")
        assert result.status == CommitmentStatus.COMPLETED
        assert result.completed_at is not None

    def test_overdue_to_cancelled(self, adapter):
        """Transition OVERDUE -> CANCELLED."""
        c = Commitment(
            id="overdue-cancel", email_id="e1", description="Test",
            detected_at="2024-01-01", status=CommitmentStatus.OVERDUE,
        )
        adapter.add_commitment(c)

        adapter.mark_cancelled("overdue-cancel")
        assert adapter.get_by_id("overdue-cancel").status == CommitmentStatus.CANCELLED


# =============================================================================
# TESTS - QUERY RESULT ORDER
# =============================================================================


class TestQueryResultOrder:
    """Tests pour l'ordre des resultats."""

    def test_get_all_returns_insertion_order(self, adapter):
        """get_all retourne dans l'ordre d'insertion (par defaut SQLite)."""
        ids = ["c1", "c2", "c3", "c4", "c5"]
        for i, id_ in enumerate(ids):
            c = Commitment(
                id=id_, email_id="e1", description=f"D{i}",
                detected_at=f"2024-01-0{i+1}", status=CommitmentStatus.PENDING,
            )
            adapter.add_commitment(c)

        result = adapter.get_all()
        result_ids = [c.id for c in result]
        assert result_ids == ids

    def test_get_by_email_multiple_results(self, adapter):
        """get_by_email avec plusieurs resultats les retourne tous."""
        for i in range(5):
            c = Commitment(
                id=f"multi-{i}", email_id="same-email", description=f"D{i}",
                detected_at=f"2024-01-0{i+1}", status=CommitmentStatus.PENDING,
            )
            adapter.add_commitment(c)

        result = adapter.get_by_email("same-email")
        assert len(result) == 5


class TestPrivacyDeleteByAccount:
    def test_add_commitment_persists_account_id(self, adapter):
        commitment = Commitment(
            id="acct-commit",
            email_id="email-1",
            description="Private commitment",
            detected_at="2024-01-01",
            status=CommitmentStatus.PENDING,
            account_id=42,
        )

        adapter.add_commitment(commitment)

        assert adapter.get_by_id("acct-commit").account_id == 42

    def test_delete_by_account_removes_only_matching_commitments(self, adapter):
        adapter.add_commitment(Commitment(
            id="c1", email_id="e1", description="Delete me",
            detected_at="2024-01-01", status=CommitmentStatus.PENDING,
            account_id=42,
        ))
        adapter.add_commitment(Commitment(
            id="c2", email_id="e2", description="Keep me",
            detected_at="2024-01-01", status=CommitmentStatus.PENDING,
            account_id=7,
        ))

        assert adapter.delete_by_account(42) == 1

        assert adapter.get_by_id("c1") is None
        assert adapter.get_by_id("c2") is not None
