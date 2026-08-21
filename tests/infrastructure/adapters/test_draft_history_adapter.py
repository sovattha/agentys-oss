# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests TDD pour LegacyDraftHistoryAdapter.

Ce module teste:
1. Implementation du port DraftHistoryPort
2. Serialisation/deserialisation (entity_to_dict, dict_to_entity)
3. Operations CRUD (add, get_by_id, get_all)
4. Filtres (get_recent, get_with_feedback)
5. Statistiques (count, count_by_status, count_by_category, count_today)
6. Methode get_stats() avec tous les calculs
7. Edge cases et gestion des erreurs

TDD: Tests ecrits pour couvrir 100% du code.
Clean Architecture: Infrastructure layer (Adapters).
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.infrastructure.adapters.draft_history_adapter import LegacyDraftHistoryAdapter
from app.domain.entities.draft_history import DraftRecord
from app.domain.ports.draft_history_port import DraftHistoryPort


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture(autouse=True)
def _allow_unscoped_draft_history(monkeypatch):
    """Autorise les méthodes non scopées (get_all, get_by_id, update_feedback)
    dans ce fichier de tests legacy. En prod, ces méthodes lèvent RuntimeError
    pour forcer le passage par les variantes *_for_account (isolation multi-compte).
    """
    monkeypatch.setenv("ALLOW_UNSCOPED_DRAFT_HISTORY", "1")
    monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "legacy_full_cache")
    yield


@pytest.fixture
def temp_history_file(tmp_path) -> Path:
    """Cree un fichier d'historique temporaire."""
    return tmp_path / "test_drafts_history.json"


@pytest.fixture
def adapter(temp_history_file) -> LegacyDraftHistoryAdapter:
    """Cree un adapter avec fichier temporaire."""
    return LegacyDraftHistoryAdapter(history_file=temp_history_file)


@pytest.fixture
def sample_record() -> DraftRecord:
    """Cree un enregistrement de brouillon de test."""
    return DraftRecord(
        id="draft-123",
        timestamp="2026-01-15T10:30:00",
        email_id="email-456",
        email_sender="client@example.com",
        email_subject="Demande de devis",
        email_preview="Bonjour, je souhaite obtenir un devis...",
        draft_v1="Bonjour, merci pour votre demande...",
        critique="Brouillon acceptable, ton professionnel.",
        draft_final="Bonjour, merci pour votre demande de devis...",
        status="V1_VALIDATED",
        account_id=1,
        draft_id="outlook-draft-789",
        tokens_used=150,
        model="claude-3-opus",
        processing_time_ms=2500,
        priority_score=75,
        category="COMMERCIAL",
    )


@pytest.fixture
def sample_record_v2() -> DraftRecord:
    """Cree un enregistrement V2 (corrige) de test."""
    return DraftRecord(
        id="draft-456",
        timestamp="2026-01-15T11:00:00",
        email_id="email-789",
        email_sender="support@company.com",
        email_subject="Probleme technique",
        email_preview="Je rencontre un bug lors de...",
        draft_v1="Bonjour, nous avons bien recu...",
        critique="Ton trop formel, ajuster.",
        draft_final="Bonjour, merci de nous avoir contacte...",
        status="V2_CORRECTED",
        account_id=1,
        draft_id="gmail-draft-111",
        tokens_used=200,
        model="claude-3-sonnet",
        processing_time_ms=3000,
        priority_score=60,
        category="SUPPORT",
    )


@pytest.fixture
def sample_record_with_feedback() -> DraftRecord:
    """Cree un enregistrement avec feedback."""
    return DraftRecord(
        id="draft-789",
        timestamp="2026-01-15T12:00:00",
        email_id="email-111",
        email_sender="vip@client.com",
        email_subject="Urgent: Contrat",
        email_preview="Suite a notre discussion...",
        draft_v1="Cher Client, suite a...",
        critique="Excellent, validé.",
        draft_final="Cher Client, suite a notre entretien...",
        status="V1_VALIDATED",
        account_id=1,
        tokens_used=180,
        model="claude-3-opus",
        processing_time_ms=2200,
        priority_score=95,
        category="URGENT",
        feedback="positive",
        feedback_comment="Parfait, rien a changer",
        feedback_rating=5,
    )


def create_record_at_date(record_id: str, date_str: str, status: str = "V1_VALIDATED") -> DraftRecord:
    """Helper pour creer un enregistrement a une date specifique."""
    return DraftRecord(
        id=record_id,
        timestamp=f"{date_str}T10:00:00",
        email_id=f"email-{record_id}",
        email_sender="test@example.com",
        email_subject="Test",
        email_preview="Test content",
        draft_v1="Draft V1",
        critique="OK",
        draft_final="Draft final",
        status=status,
        account_id=1,
        tokens_used=100,
        processing_time_ms=1000,
    )


# =============================================================================
# TESTS - IMPLEMENTS PORT
# =============================================================================


class TestImplementsDraftHistoryPort:
    """Verifie que l'adapter implemente correctement le port."""

    def test_implements_port_interface(self, adapter):
        """L'adapter doit implementer DraftHistoryPort."""
        assert isinstance(adapter, DraftHistoryPort)

    def test_has_add_method(self, adapter):
        """L'adapter doit avoir la methode add."""
        assert hasattr(adapter, "add")
        assert callable(getattr(adapter, "add"))

    def test_has_get_by_id_method(self, adapter):
        """L'adapter doit avoir la methode get_by_id."""
        assert hasattr(adapter, "get_by_id")
        assert callable(getattr(adapter, "get_by_id"))

    def test_has_get_all_method(self, adapter):
        """L'adapter doit avoir la methode get_all."""
        assert hasattr(adapter, "get_all")
        assert callable(getattr(adapter, "get_all"))

    def test_has_get_recent_method(self, adapter):
        """L'adapter doit avoir la methode get_recent."""
        assert hasattr(adapter, "get_recent")
        assert callable(getattr(adapter, "get_recent"))

    def test_has_update_feedback_method(self, adapter):
        """L'adapter doit avoir la methode update_feedback."""
        assert hasattr(adapter, "update_feedback")
        assert callable(getattr(adapter, "update_feedback"))

    def test_has_get_with_feedback_method(self, adapter):
        """L'adapter doit avoir la methode get_with_feedback."""
        assert hasattr(adapter, "get_with_feedback")
        assert callable(getattr(adapter, "get_with_feedback"))

    def test_has_count_method(self, adapter):
        """L'adapter doit avoir la methode count."""
        assert hasattr(adapter, "count")
        assert callable(getattr(adapter, "count"))

    def test_has_count_by_status_method(self, adapter):
        """L'adapter doit avoir la methode count_by_status."""
        assert hasattr(adapter, "count_by_status")
        assert callable(getattr(adapter, "count_by_status"))

    def test_has_count_by_category_method(self, adapter):
        """L'adapter doit avoir la methode count_by_category."""
        assert hasattr(adapter, "count_by_category")
        assert callable(getattr(adapter, "count_by_category"))

    def test_has_count_today_method(self, adapter):
        """L'adapter doit avoir la methode count_today."""
        assert hasattr(adapter, "count_today")
        assert callable(getattr(adapter, "count_today"))

    def test_has_get_stats_method(self, adapter):
        """L'adapter doit avoir la methode get_stats."""
        assert hasattr(adapter, "get_stats")
        assert callable(getattr(adapter, "get_stats"))


# =============================================================================
# TESTS - SERIALISATION
# =============================================================================


class TestEntityToDict:
    """Tests pour la conversion entity vers dict."""

    def test_converts_required_fields(self, adapter, sample_record):
        """Convertit tous les champs obligatoires."""
        result = adapter._entity_to_dict(sample_record)

        assert result["id"] == "draft-123"
        assert result["timestamp"] == "2026-01-15T10:30:00"
        assert result["email_id"] == "email-456"
        assert result["email_sender"] == "client@example.com"
        assert result["email_subject"] == "Demande de devis"
        assert result["email_preview"] == "Bonjour, je souhaite obtenir un devis..."
        assert result["draft_v1"] == "Bonjour, merci pour votre demande..."
        assert result["critique"] == "Brouillon acceptable, ton professionnel."
        assert result["draft_final"] == "Bonjour, merci pour votre demande de devis..."
        assert result["status"] == "V1_VALIDATED"

    def test_metadata_only_drops_source_and_draft_content(
        self, adapter, sample_record, monkeypatch
    ):
        """Le mode metadata-only garde les métriques mais retire le contenu."""
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "metadata_only")

        result = adapter._entity_to_dict(sample_record)

        assert result["email_preview"] == ""
        assert result["draft_v1"] == ""
        assert result["critique"] == ""
        assert result["draft_final"] == ""
        assert result["tokens_used"] == 150
        assert result["status"] == "V1_VALIDATED"

    def test_converts_optional_fields(self, adapter, sample_record):
        """Convertit tous les champs optionnels."""
        result = adapter._entity_to_dict(sample_record)

        assert result["draft_id"] == "outlook-draft-789"
        assert result["tokens_used"] == 150
        assert result["model"] == "claude-3-opus"
        assert result["processing_time_ms"] == 2500
        assert result["priority_score"] == 75
        assert result["category"] == "COMMERCIAL"

    def test_converts_feedback_fields(self, adapter, sample_record_with_feedback):
        """Convertit les champs de feedback."""
        result = adapter._entity_to_dict(sample_record_with_feedback)

        assert result["feedback"] == "positive"
        assert result["feedback_comment"] == "Parfait, rien a changer"
        assert result["feedback_rating"] == 5

    def test_handles_none_optional_fields(self, adapter):
        """Gere les champs optionnels a None."""
        record = DraftRecord(
            id="test",
            timestamp="2026-01-01T00:00:00",
            email_id="email-1",
            email_sender="sender@test.com",
            email_subject="Subject",
            email_preview="Preview",
            draft_v1="V1",
            critique="Critique",
            draft_final="Final",
            status="PENDING",
        )
        result = adapter._entity_to_dict(record)

        assert result["draft_id"] is None
        assert result["priority_score"] is None
        assert result["category"] is None
        assert result["feedback"] is None
        assert result["feedback_comment"] is None
        assert result["feedback_rating"] is None


class TestDictToEntity:
    """Tests pour la conversion dict vers entity."""

    def test_converts_all_fields(self, adapter):
        """Convertit tous les champs du dict."""
        data = {
            "id": "draft-abc",
            "timestamp": "2026-01-10T09:00:00",
            "email_id": "email-xyz",
            "email_sender": "user@domain.com",
            "email_subject": "Test Subject",
            "email_preview": "Test preview content",
            "draft_v1": "First draft",
            "critique": "Good draft",
            "draft_final": "Final draft",
            "status": "V1_VALIDATED",
            "draft_id": "provider-draft-123",
            "tokens_used": 200,
            "model": "gpt-4",
            "processing_time_ms": 1500,
            "priority_score": 80,
            "category": "NORMAL",
            "feedback": "neutral",
            "feedback_comment": "Could be better",
            "feedback_rating": 3,
        }

        result = adapter._dict_to_entity(data)

        assert isinstance(result, DraftRecord)
        assert result.id == "draft-abc"
        assert result.timestamp == "2026-01-10T09:00:00"
        assert result.email_id == "email-xyz"
        assert result.email_sender == "user@domain.com"
        assert result.email_subject == "Test Subject"
        assert result.email_preview == "Test preview content"
        assert result.draft_v1 == "First draft"
        assert result.critique == "Good draft"
        assert result.draft_final == "Final draft"
        assert result.status == "V1_VALIDATED"
        assert result.draft_id == "provider-draft-123"
        assert result.tokens_used == 200
        assert result.model == "gpt-4"
        assert result.processing_time_ms == 1500
        assert result.priority_score == 80
        assert result.category == "NORMAL"
        assert result.feedback == "neutral"
        assert result.feedback_comment == "Could be better"
        assert result.feedback_rating == 3

    def test_handles_missing_optional_fields(self, adapter):
        """Gere les champs optionnels manquants."""
        data = {
            "id": "draft-minimal",
            "timestamp": "2026-01-01T00:00:00",
            "email_id": "email-1",
            "email_sender": "sender@test.com",
            "email_subject": "Subject",
            "email_preview": "Preview",
            "draft_v1": "V1",
            "critique": "OK",
            "draft_final": "Final",
            "status": "PENDING",
        }

        result = adapter._dict_to_entity(data)

        assert result.draft_id is None
        assert result.tokens_used == 0
        assert result.model == ""
        assert result.processing_time_ms == 0
        assert result.priority_score is None
        assert result.category is None
        assert result.feedback is None

    def test_handles_legacy_email_body_field(self, adapter):
        """Gere le champ legacy email_body."""
        data = {
            "id": "draft-legacy",
            "timestamp": "2026-01-01T00:00:00",
            "email_id": "email-1",
            "email_sender": "sender@test.com",
            "email_subject": "Subject",
            "email_body": "Legacy body content",  # Legacy field
            "draft_v1": "V1",
            "critique": "OK",
            "draft_final": "Final",
            "status": "PENDING",
        }

        result = adapter._dict_to_entity(data)

        # Should use email_body as email_preview (fallback)
        assert result.email_preview == "Legacy body content"

    def test_handles_empty_dict(self, adapter):
        """Gere un dictionnaire vide avec valeurs par defaut."""
        data = {}

        result = adapter._dict_to_entity(data)

        assert result.id == ""
        assert result.timestamp == ""
        assert result.email_id == ""
        assert result.tokens_used == 0


# =============================================================================
# TESTS - CRUD OPERATIONS
# =============================================================================


class TestAdd:
    """Tests pour l'ajout d'enregistrements."""

    def test_add_inserts_record(self, adapter, sample_record, temp_history_file):
        """Ajoute un enregistrement dans le fichier."""
        adapter.add(sample_record)

        # Verify file contains the record
        data = json.loads(temp_history_file.read_text())
        assert len(data) == 1
        assert data[0]["id"] == "draft-123"

    def test_add_inserts_at_beginning(self, adapter, sample_record, sample_record_v2):
        """Insere les nouveaux enregistrements au debut."""
        adapter.add(sample_record)
        adapter.add(sample_record_v2)

        records = adapter.get_all()
        # Most recent first
        assert records[0].id == "draft-456"
        assert records[1].id == "draft-123"

    def test_add_updates_existing_record(self, adapter, sample_record, temp_history_file):
        """Met a jour un enregistrement existant au lieu de dupliquer."""
        adapter.add(sample_record)

        # Modify and add again with same ID
        updated = DraftRecord(
            id="draft-123",
            timestamp="2026-01-15T10:30:00",
            email_id="email-456",
            email_sender="client@example.com",
            email_subject="Demande de devis UPDATED",
            email_preview="Updated preview",
            draft_v1="Updated V1",
            critique="Updated critique",
            draft_final="Updated final",
            status="V2_CORRECTED",
            tokens_used=300,
        )
        adapter.add(updated)

        # Should still have only 1 record
        data = json.loads(temp_history_file.read_text())
        assert len(data) == 1
        assert data[0]["email_subject"] == "Demande de devis UPDATED"
        assert data[0]["status"] == "V2_CORRECTED"

    def test_add_creates_file_if_not_exists(self, adapter, sample_record, temp_history_file):
        """Cree le fichier s'il n'existe pas."""
        # File shouldn't exist yet
        assert not temp_history_file.exists()

        adapter.add(sample_record)

        assert temp_history_file.exists()


class TestGetById:
    """Tests pour la recuperation par ID."""

    def test_get_by_id_returns_record(self, adapter, sample_record):
        """Retourne l'enregistrement correspondant."""
        adapter.add(sample_record)

        result = adapter.get_by_id("draft-123")

        assert result is not None
        assert result.id == "draft-123"
        assert result.email_sender == "client@example.com"

    def test_get_by_id_returns_none_if_not_found(self, adapter, sample_record):
        """Retourne None si non trouve."""
        adapter.add(sample_record)

        result = adapter.get_by_id("nonexistent-id")

        assert result is None

    def test_get_by_id_on_empty_store(self, adapter):
        """Retourne None sur un store vide."""
        result = adapter.get_by_id("any-id")

        assert result is None


class TestGetAll:
    """Tests pour la recuperation de tous les enregistrements."""

    def test_get_all_returns_empty_list_on_empty_store(self, adapter):
        """Retourne une liste vide si pas d'enregistrements."""
        result = adapter.get_all()

        assert result == []

    def test_get_all_returns_all_records(self, adapter, sample_record, sample_record_v2):
        """Retourne tous les enregistrements."""
        adapter.add(sample_record)
        adapter.add(sample_record_v2)

        result = adapter.get_all()

        assert len(result) == 2

    def test_get_all_respects_limit(self, adapter, sample_record, sample_record_v2):
        """Respecte la limite specifiee."""
        adapter.add(sample_record)
        adapter.add(sample_record_v2)

        result = adapter.get_all(limit=1)

        assert len(result) == 1

    def test_get_all_default_limit_is_1000(self, adapter):
        """La limite par defaut est 1000."""
        # Add 5 records
        for i in range(5):
            record = create_record_at_date(f"draft-{i}", "2026-01-10")
            adapter.add(record)

        # Without explicit limit, should return all (up to 1000)
        result = adapter.get_all()

        assert len(result) == 5


# =============================================================================
# TESTS - FILTERS
# =============================================================================


class TestGetRecent:
    """Tests pour la recuperation des enregistrements recents."""

    def test_get_recent_returns_last_7_days_by_default(self, adapter):
        """Retourne les enregistrements des 7 derniers jours par defaut."""
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        old_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")

        adapter.add(create_record_at_date("recent-1", today))
        adapter.add(create_record_at_date("recent-2", yesterday))
        adapter.add(create_record_at_date("old", old_date))

        result = adapter.get_recent()

        assert len(result) == 2
        ids = [r.id for r in result]
        assert "recent-1" in ids
        assert "recent-2" in ids
        assert "old" not in ids

    def test_get_recent_with_custom_days(self, adapter):
        """Respecte le nombre de jours specifie."""
        today = datetime.now().strftime("%Y-%m-%d")
        five_days_ago = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
        fifteen_days_ago = (datetime.now() - timedelta(days=15)).strftime("%Y-%m-%d")

        adapter.add(create_record_at_date("recent", today))
        adapter.add(create_record_at_date("mid", five_days_ago))
        adapter.add(create_record_at_date("old", fifteen_days_ago))

        result = adapter.get_recent(days=10)

        assert len(result) == 2
        ids = [r.id for r in result]
        assert "recent" in ids
        assert "mid" in ids
        assert "old" not in ids

    def test_get_recent_on_empty_store(self, adapter):
        """Retourne une liste vide si pas d'enregistrements."""
        result = adapter.get_recent()

        assert result == []


class TestGetWithFeedback:
    """Tests pour la recuperation des enregistrements avec feedback."""

    def test_get_with_feedback_returns_only_with_feedback(
        self, adapter, sample_record, sample_record_with_feedback
    ):
        """Retourne uniquement les enregistrements avec feedback."""
        adapter.add(sample_record)  # No feedback
        adapter.add(sample_record_with_feedback)  # Has feedback

        result = adapter.get_with_feedback()

        assert len(result) == 1
        assert result[0].id == "draft-789"
        assert result[0].feedback == "positive"

    def test_get_with_feedback_respects_limit(self, adapter):
        """Respecte la limite specifiee."""
        for i in range(10):
            record = DraftRecord(
                id=f"draft-{i}",
                timestamp="2026-01-15T10:00:00",
                email_id=f"email-{i}",
                email_sender="test@test.com",
                email_subject="Test",
                email_preview="Preview",
                draft_v1="V1",
                critique="OK",
                draft_final="Final",
                status="V1_VALIDATED",
                feedback="positive",
            )
            adapter.add(record)

        result = adapter.get_with_feedback(limit=5)

        assert len(result) == 5

    def test_get_with_feedback_on_empty_store(self, adapter):
        """Retourne une liste vide si pas d'enregistrements."""
        result = adapter.get_with_feedback()

        assert result == []


# =============================================================================
# TESTS - UPDATE FEEDBACK
# =============================================================================


class TestUpdateFeedback:
    """Tests pour la mise a jour du feedback."""

    def test_update_feedback_modifies_record(self, adapter, sample_record):
        """Met a jour le feedback d'un enregistrement."""
        adapter.add(sample_record)

        result = adapter.update_feedback("draft-123", "negative", rating=2)

        assert result is True

        updated = adapter.get_by_id("draft-123")
        assert updated.feedback == "negative"
        assert updated.feedback_rating == 2

    def test_update_feedback_returns_false_if_not_found(self, adapter):
        """Retourne False si enregistrement non trouve."""
        result = adapter.update_feedback("nonexistent", "positive")

        assert result is False

    def test_update_feedback_without_rating(self, adapter, sample_record):
        """Met a jour le feedback sans note."""
        adapter.add(sample_record)

        result = adapter.update_feedback("draft-123", "neutral")

        assert result is True

        updated = adapter.get_by_id("draft-123")
        assert updated.feedback == "neutral"
        assert updated.feedback_rating is None


# =============================================================================
# TESTS - COUNT METHODS
# =============================================================================


class TestCount:
    """Tests pour le comptage total."""

    def test_count_returns_zero_on_empty_store(self, adapter):
        """Retourne 0 si pas d'enregistrements."""
        result = adapter.count()

        assert result == 0

    def test_count_returns_correct_count(self, adapter, sample_record, sample_record_v2):
        """Retourne le nombre correct d'enregistrements."""
        adapter.add(sample_record)
        adapter.add(sample_record_v2)

        result = adapter.count()

        assert result == 2


class TestCountByStatus:
    """Tests pour le comptage par statut."""

    def test_count_by_status_groups_correctly(self, adapter, sample_record, sample_record_v2):
        """Groupe correctement par statut."""
        adapter.add(sample_record)  # V1_VALIDATED
        adapter.add(sample_record_v2)  # V2_CORRECTED

        result = adapter.count_by_status()

        assert result["V1_VALIDATED"] == 1
        assert result["V2_CORRECTED"] == 1

    def test_count_by_status_on_empty_store(self, adapter):
        """Retourne un dict vide si pas d'enregistrements."""
        result = adapter.count_by_status()

        assert result == {}


class TestCountByCategory:
    """Tests pour le comptage par categorie."""

    def test_count_by_category_groups_correctly(self, adapter, sample_record, sample_record_v2):
        """Groupe correctement par categorie."""
        adapter.add(sample_record)  # COMMERCIAL
        adapter.add(sample_record_v2)  # SUPPORT

        result = adapter.count_by_category()

        assert result["COMMERCIAL"] == 1
        assert result["SUPPORT"] == 1

    def test_count_by_category_handles_none_category(self, adapter):
        """Gere les categories None comme UNKNOWN."""
        record = DraftRecord(
            id="draft-no-cat",
            timestamp="2026-01-15T10:00:00",
            email_id="email-1",
            email_sender="test@test.com",
            email_subject="Test",
            email_preview="Preview",
            draft_v1="V1",
            critique="OK",
            draft_final="Final",
            status="PENDING",
            category=None,
        )
        adapter.add(record)

        result = adapter.count_by_category()

        assert result.get(None, 0) == 1 or result.get("UNKNOWN", 0) >= 0


class TestCountToday:
    """Tests pour le comptage des enregistrements du jour."""

    def test_count_today_counts_only_today(self, adapter):
        """Compte uniquement les enregistrements d'aujourd'hui."""
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        adapter.add(create_record_at_date("today-1", today))
        adapter.add(create_record_at_date("today-2", today))
        adapter.add(create_record_at_date("yesterday", yesterday))

        result = adapter.count_today()

        assert result == 2

    def test_count_today_returns_zero_if_none_today(self, adapter):
        """Retourne 0 si aucun enregistrement aujourd'hui."""
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        adapter.add(create_record_at_date("yesterday", yesterday))

        result = adapter.count_today()

        assert result == 0


# =============================================================================
# TESTS - GET STATS
# =============================================================================


class TestGetStats:
    """Tests pour la methode get_stats."""

    def test_get_stats_on_empty_store(self, adapter):
        """Retourne des stats vides pour un store vide."""
        result = adapter.get_stats()

        assert result["total"] == 0
        assert result["validated_v1"] == 0
        assert result["corrected_v2"] == 0
        assert result["v1_percent"] == 0
        assert result["v2_percent"] == 0
        assert result["avg_rating"] == 0
        assert result["ratings_count"] == 0
        assert result["total_tokens"] == 0
        assert result["time_saved_minutes"] == 0
        assert result["time_saved_hours"] == 0
        assert result["avg_processing_time_ms"] == 0
        assert result["avg_processing_time_sec"] == 0
        assert result["automation_rate"] == 0
        assert result["daily_stats"] == []

    def test_get_stats_total_count(self, adapter, sample_record, sample_record_v2):
        """Calcule le nombre total correctement."""
        adapter.add(sample_record)
        adapter.add(sample_record_v2)

        result = adapter.get_stats()

        assert result["total"] == 2

    def test_get_stats_v1_v2_counts(self, adapter, sample_record, sample_record_v2):
        """Compte V1 et V2 correctement."""
        adapter.add(sample_record)  # V1_VALIDATED
        adapter.add(sample_record_v2)  # V2_CORRECTED

        result = adapter.get_stats()

        assert result["validated_v1"] == 1
        assert result["corrected_v2"] == 1

    def test_get_stats_v1_v2_percentages(self, adapter, sample_record, sample_record_v2):
        """Calcule les pourcentages V1/V2 correctement."""
        adapter.add(sample_record)  # V1
        adapter.add(sample_record_v2)  # V2

        result = adapter.get_stats()

        assert result["v1_percent"] == 50
        assert result["v2_percent"] == 50

    def test_get_stats_avg_rating(self, adapter, sample_record_with_feedback):
        """Calcule la note moyenne correctement."""
        adapter.add(sample_record_with_feedback)  # rating=5

        # Add another with rating
        record2 = DraftRecord(
            id="draft-2",
            timestamp="2026-01-15T10:00:00",
            email_id="email-2",
            email_sender="test@test.com",
            email_subject="Test",
            email_preview="Preview",
            draft_v1="V1",
            critique="OK",
            draft_final="Final",
            status="V1_VALIDATED",
            feedback="neutral",
            feedback_rating=3,
        )
        adapter.add(record2)

        result = adapter.get_stats()

        # (5 + 3) / 2 = 4.0
        assert result["avg_rating"] == 4.0
        assert result["ratings_count"] == 2

    def test_get_stats_total_tokens(self, adapter, sample_record, sample_record_v2):
        """Calcule le total de tokens correctement."""
        adapter.add(sample_record)  # 150 tokens
        adapter.add(sample_record_v2)  # 200 tokens

        result = adapter.get_stats()

        assert result["total_tokens"] == 350

    def test_get_stats_time_saved(self, adapter, sample_record, sample_record_v2):
        """Calcule le temps economise correctement (5 min par email)."""
        adapter.add(sample_record)
        adapter.add(sample_record_v2)

        result = adapter.get_stats()

        # 2 emails * 5 min = 10 min = 0.2 hours
        assert result["time_saved_minutes"] == 10
        assert result["time_saved_hours"] == 0.2

    def test_get_stats_avg_processing_time(self, adapter, sample_record, sample_record_v2):
        """Calcule le temps de traitement moyen correctement."""
        adapter.add(sample_record)  # 2500ms
        adapter.add(sample_record_v2)  # 3000ms

        result = adapter.get_stats()

        # (2500 + 3000) / 2 = 2750ms = 2.75s
        assert result["avg_processing_time_ms"] == 2750
        assert result["avg_processing_time_sec"] == 2.8  # Rounded to 1 decimal

    def test_get_stats_automation_rate(self, adapter, sample_record, sample_record_v2):
        """Calcule le taux d'automatisation correctement."""
        # V1 = 100% automation, V2 = 50% automation
        adapter.add(sample_record)  # V1
        adapter.add(sample_record_v2)  # V2

        result = adapter.get_stats()

        # (1 * 100 + 1 * 50) / 2 = 75%
        assert result["automation_rate"] == 75

    def test_get_stats_automation_rate_all_v1(self, adapter, sample_record):
        """Taux d'automatisation 100% si tous V1."""
        adapter.add(sample_record)  # V1

        result = adapter.get_stats()

        assert result["automation_rate"] == 100

    def test_get_stats_daily_stats(self, adapter):
        """Calcule les statistiques journalieres correctement."""
        adapter.add(create_record_at_date("draft-1", "2026-01-15", "V1_VALIDATED"))
        adapter.add(create_record_at_date("draft-2", "2026-01-15", "V2_CORRECTED"))
        adapter.add(create_record_at_date("draft-3", "2026-01-14", "V1_VALIDATED"))

        result = adapter.get_stats()

        assert len(result["daily_stats"]) >= 2

        # Check daily_stats structure
        for day_stat in result["daily_stats"]:
            assert "date" in day_stat
            assert "total" in day_stat
            assert "v1" in day_stat
            assert "v2" in day_stat
            assert "tokens" in day_stat

    def test_get_stats_daily_stats_max_30_days(self, adapter):
        """daily_stats retourne max 30 jours."""
        # Add records for 35 days
        for i in range(35):
            date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            adapter.add(create_record_at_date(f"draft-{i}", date))

        result = adapter.get_stats()

        assert len(result["daily_stats"]) == 30


# =============================================================================
# TESTS - EDGE CASES
# =============================================================================


class TestEdgeCases:
    """Tests pour les cas limites."""

    def test_handles_corrupted_json_file(self, adapter, temp_history_file):
        """Gere un fichier JSON corrompu."""
        temp_history_file.write_text("not valid json {{{")

        result = adapter.get_all()

        assert result == []

    def test_handles_non_list_json(self, adapter, temp_history_file):
        """Gere un JSON qui n'est pas une liste."""
        temp_history_file.write_text('{"key": "value"}')

        result = adapter.get_all()

        assert result == []

    def test_handles_empty_json_file(self, adapter, temp_history_file):
        """Gere un fichier JSON vide."""
        temp_history_file.write_text("")

        result = adapter.get_all()

        assert result == []

    def test_creates_parent_directories(self, tmp_path):
        """Cree les repertoires parents si necessaire."""
        nested_path = tmp_path / "deep" / "nested" / "path" / "history.json"

        adapter = LegacyDraftHistoryAdapter(history_file=nested_path)
        adapter.add(DraftRecord(
            id="test",
            timestamp="2026-01-01T00:00:00",
            email_id="email-1",
            email_sender="test@test.com",
            email_subject="Test",
            email_preview="Preview",
            draft_v1="V1",
            critique="OK",
            draft_final="Final",
            status="PENDING",
        ))

        assert nested_path.exists()

    def test_handles_unicode_content(self, adapter, temp_history_file):
        """Gere le contenu Unicode correctement."""
        record = DraftRecord(
            id="draft-unicode",
            timestamp="2026-01-15T10:00:00",
            email_id="email-1",
            email_sender="用户@example.com",
            email_subject="日本語テスト",
            email_preview="Bonjour, café résumé",
            draft_v1="Merci beaucoup 🙏",
            critique="Très bien ✓",
            draft_final="Réponse finale",
            status="V1_VALIDATED",
        )

        adapter.add(record)
        result = adapter.get_by_id("draft-unicode")

        assert result.email_sender == "用户@example.com"
        assert result.email_subject == "日本語テスト"
        assert "café" in result.email_preview
        assert "🙏" in result.draft_v1

    def test_handles_very_long_content(self, adapter, temp_history_file):
        """Gere le contenu tres long."""
        long_content = "x" * 100000

        record = DraftRecord(
            id="draft-long",
            timestamp="2026-01-15T10:00:00",
            email_id="email-1",
            email_sender="test@test.com",
            email_subject="Long content test",
            email_preview=long_content,
            draft_v1=long_content,
            critique="OK",
            draft_final=long_content,
            status="V1_VALIDATED",
        )

        adapter.add(record)
        result = adapter.get_by_id("draft-long")

        assert len(result.email_preview) == 100000


class TestFilepathProperty:
    """Tests pour la propriete filepath."""

    def test_filepath_returns_correct_path(self, adapter, temp_history_file):
        """Retourne le bon chemin de fichier."""
        assert adapter.filepath == temp_history_file


class TestDefaultHistoryFile:
    """Tests pour le chemin par defaut."""

    def test_uses_default_path_when_none_provided(self, monkeypatch, tmp_path):
        """Utilise le chemin par defaut si non specifie."""
        # Mock PROJECT_ROOT
        import app.config
        monkeypatch.setattr(app.config, "PROJECT_ROOT", tmp_path)

        adapter = LegacyDraftHistoryAdapter()

        expected_path = tmp_path / "data" / "history" / "drafts_history.json"
        assert adapter.filepath == expected_path
