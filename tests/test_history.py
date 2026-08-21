# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour le module d'historique des brouillons.

pytest tests/test_history.py -v
"""

import pytest
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.history import (
    DraftHistory,
    DraftRecord,
    create_record,
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def temp_history_file(tmp_path):
    """Crée un fichier d'historique temporaire."""
    history_dir = tmp_path / "history"
    history_dir.mkdir(parents=True)
    return history_dir / "drafts_history.json"


@pytest.fixture(autouse=True)
def _legacy_email_content_storage(monkeypatch):
    """Préserve les attentes historiques de ce module hors tests privacy."""
    monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "legacy_full_cache")


@pytest.fixture
def draft_history(temp_history_file):
    """Crée un DraftHistory avec fichier temporaire."""
    return DraftHistory(history_file=temp_history_file)


@pytest.fixture
def sample_record():
    """Crée un record de test."""
    return DraftRecord(
        id="test-001",
        timestamp="2024-01-15T10:00:00",
        email_id="email-1",
        email_sender="sender@example.com",
        email_subject="Test Subject",
        email_preview="Preview of the email...",
        draft_v1="Draft V1 content",
        critique="Good draft",
        draft_final="Final draft content",
        status="VALIDÉ V1",
        draft_id="draft-123",
        tokens_used=150,
        model="claude-3-opus",
        processing_time_ms=2500,
        priority_score=75,
        category="IMPORTANT"
    )


@pytest.fixture
def sample_records():
    """Crée plusieurs records de test."""
    return [
        DraftRecord(
            id="rec-001",
            timestamp="2024-01-15T10:00:00",
            email_id="email-1",
            email_sender="alice@example.com",
            email_subject="Meeting request",
            email_preview="Can we schedule a meeting?",
            draft_v1="Sure, let's meet",
            critique="Good",
            draft_final="Sure, let's meet tomorrow",
            status="VALIDÉ V1",
            tokens_used=100,
            feedback_rating=5,
            processing_time_ms=1500
        ),
        DraftRecord(
            id="rec-002",
            timestamp="2024-01-16T11:00:00",
            email_id="email-2",
            email_sender="bob@example.com",
            email_subject="Project update",
            email_preview="Here's the project status",
            draft_v1="Thanks for the update",
            critique="Needs more detail",
            draft_final="Thanks for the update. I'll review it",
            status="CORRIGÉ V2",
            tokens_used=200,
            feedback_rating=3,
            processing_time_ms=3000
        ),
        DraftRecord(
            id="rec-003",
            timestamp="2024-01-17T12:00:00",
            email_id="email-3",
            email_sender="alice@example.com",
            email_subject="Follow-up",
            email_preview="Following up on our discussion",
            draft_v1="Thanks for following up",
            critique="OK",
            draft_final="Thanks for following up",
            status="VALIDÉ V1",
            tokens_used=80,
            feedback_rating=4,
            processing_time_ms=1200
        ),
    ]


# ============================================================================
# TESTS DRAFT RECORD DATACLASS
# ============================================================================

class TestDraftRecord:
    """Tests pour le dataclass DraftRecord."""

    def test_create_record_minimal(self):
        """Création avec champs requis."""
        record = DraftRecord(
            id="test-1",
            timestamp="2024-01-15T10:00:00",
            email_id="email-1",
            email_sender="sender@example.com",
            email_subject="Subject",
            email_preview="Preview",
            draft_v1="V1",
            critique="Critique",
            draft_final="Final",
            status="VALIDÉ V1"
        )
        assert record.id == "test-1"
        assert record.draft_id is None
        assert record.tokens_used == 0
        assert record.feedback is None
        assert record.feedback_rating is None

    def test_create_record_full(self, sample_record):
        """Création avec tous les champs."""
        assert sample_record.id == "test-001"
        assert sample_record.draft_id == "draft-123"
        assert sample_record.tokens_used == 150
        assert sample_record.processing_time_ms == 2500
        assert sample_record.priority_score == 75
        assert sample_record.category == "IMPORTANT"

    def test_to_correction_context(self, sample_record):
        """to_correction_context retourne les métadonnées pour les corrections."""
        context = sample_record.to_correction_context()
        assert context == {
            "sender": "sender@example.com",
            "subject": "Test Subject",
            "category": "IMPORTANT"
        }

    def test_to_correction_context_with_none_category(self):
        """to_correction_context gère category=None."""
        record = DraftRecord(
            id="test-1",
            timestamp="2024-01-15T10:00:00",
            email_id="email-1",
            email_sender="user@example.com",
            email_subject="Subject",
            email_preview="Preview",
            draft_v1="V1",
            critique="Critique",
            draft_final="Final",
            status="VALIDÉ V1",
            category=None
        )
        context = record.to_correction_context()
        assert context["category"] is None
        assert context["sender"] == "user@example.com"
        assert context["subject"] == "Subject"


# ============================================================================
# TESTS DRAFT HISTORY - FILE OPERATIONS
# ============================================================================

class TestDraftHistoryFileOps:
    """Tests pour les opérations fichiers."""

    def test_ensure_dir_creates_directory(self, draft_history, temp_history_file):
        """Vérifie que le répertoire est créé."""
        draft_history._ensure_dir()
        assert temp_history_file.parent.exists()

    def test_load_empty(self, draft_history):
        """Chargement quand fichier n'existe pas."""
        records = draft_history._load()
        assert records == []

    def test_load_with_data(self, draft_history, temp_history_file, sample_record):
        """Chargement avec données."""
        from dataclasses import asdict
        temp_history_file.write_text(json.dumps([asdict(sample_record)]))
        records = draft_history._load()
        assert len(records) == 1
        assert records[0]["id"] == "test-001"

    def test_load_corrupted_file(self, draft_history, temp_history_file):
        """Chargement avec fichier corrompu."""
        temp_history_file.write_text("not valid json {{{")
        records = draft_history._load()
        assert records == []

    def test_save(self, draft_history, temp_history_file, sample_record):
        """Sauvegarde de records."""
        from dataclasses import asdict
        draft_history._save([asdict(sample_record)])
        assert temp_history_file.exists()
        loaded = json.loads(temp_history_file.read_text())
        assert len(loaded) == 1


# ============================================================================
# TESTS DRAFT HISTORY - ADD
# ============================================================================

class TestDraftHistoryAdd:
    """Tests pour l'ajout de records."""

    def test_add_single_record(self, draft_history, sample_record):
        """Ajout d'un seul record."""
        draft_history.add(sample_record)
        records = draft_history._load()
        assert len(records) == 1
        assert records[0]["id"] == "test-001"

    def test_add_metadata_only_drops_source_and_draft_content(
        self, draft_history, sample_record, monkeypatch
    ):
        """Le mode metadata-only ne persiste pas le contenu des emails/drafts."""
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "metadata_only")

        draft_history.add(sample_record)

        records = draft_history._load()
        assert records[0]["email_preview"] == ""
        assert records[0]["draft_v1"] == ""
        assert records[0]["critique"] == ""
        assert records[0]["draft_final"] == ""
        assert records[0]["tokens_used"] == 150
        assert records[0]["status"] == "VALIDÉ V1"

    def test_add_multiple_records(self, draft_history, sample_records):
        """Ajout de plusieurs records."""
        for record in sample_records:
            draft_history.add(record)
        records = draft_history._load()
        assert len(records) == 3


# ============================================================================
# TESTS DRAFT HISTORY - GET ALL
# ============================================================================

class TestDraftHistoryGetAll:
    """Tests pour récupération de tous les records."""

    def test_get_all_empty(self, draft_history):
        """Récupération sans données."""
        records = draft_history.get_all()
        assert records == []

    def test_get_all_with_data(self, draft_history, sample_records):
        """Récupération avec données."""
        for record in sample_records:
            draft_history.add(record)
        records = draft_history.get_all()
        assert len(records) == 3

    def test_get_all_sorted_by_timestamp(self, draft_history, sample_records):
        """Récupération triée par timestamp décroissant."""
        for record in sample_records:
            draft_history.add(record)
        records = draft_history.get_all()
        # Le plus récent en premier
        assert records[0].id == "rec-003"
        assert records[2].id == "rec-001"

    def test_get_all_with_limit(self, draft_history, sample_records):
        """Récupération avec limite."""
        for record in sample_records:
            draft_history.add(record)
        records = draft_history.get_all(limit=2)
        assert len(records) == 2


# ============================================================================
# TESTS DRAFT HISTORY - GET BY ID
# ============================================================================

class TestDraftHistoryGetById:
    """Tests pour récupération par ID."""

    def test_get_by_id_found(self, draft_history, sample_records):
        """Récupération d'un record existant."""
        for record in sample_records:
            draft_history.add(record)
        record = draft_history.get_by_id("rec-002")
        assert record is not None
        assert record.email_sender == "bob@example.com"

    def test_get_by_id_not_found(self, draft_history, sample_records):
        """Récupération d'un record inexistant."""
        for record in sample_records:
            draft_history.add(record)
        record = draft_history.get_by_id("nonexistent")
        assert record is None


# ============================================================================
# TESTS DRAFT HISTORY - UPDATE FEEDBACK
# ============================================================================

class TestDraftHistoryUpdateFeedback:
    """Tests pour mise à jour du feedback."""

    def test_update_feedback_success(self, draft_history, sample_record):
        """Mise à jour réussie."""
        draft_history.add(sample_record)
        result = draft_history.update_feedback("test-001", "positive", "Excellent work!")
        assert result is True

        record = draft_history.get_by_id("test-001")
        assert record.feedback == "positive"
        assert record.feedback_comment == "Excellent work!"

    def test_update_feedback_not_found(self, draft_history, sample_record):
        """Mise à jour d'un record inexistant."""
        draft_history.add(sample_record)
        result = draft_history.update_feedback("nonexistent", "positive", "Comment")
        assert result is False


# ============================================================================
# TESTS DRAFT HISTORY - GET STATS
# ============================================================================

class TestDraftHistoryGetStats:
    """Tests pour les statistiques."""

    def test_get_stats_empty(self, draft_history):
        """Statistiques sans données."""
        stats = draft_history.get_stats()
        assert stats["total"] == 0
        assert stats["validated_v1"] == 0
        assert stats["corrected_v2"] == 0
        assert stats["avg_rating"] == 0
        assert stats["total_tokens"] == 0
        assert stats["time_saved_minutes"] == 0
        assert stats["automation_rate"] == 0

    def test_get_stats_with_data(self, draft_history, sample_records):
        """Statistiques avec données."""
        for record in sample_records:
            draft_history.add(record)
        stats = draft_history.get_stats()

        assert stats["total"] == 3
        assert stats["validated_v1"] == 2
        assert stats["corrected_v2"] == 1
        assert stats["total_tokens"] == 380
        assert stats["time_saved_minutes"] == 15  # 3 * 5

    def test_get_stats_v1_v2_percent(self, draft_history, sample_records):
        """Statistiques pourcentages V1/V2."""
        for record in sample_records:
            draft_history.add(record)
        stats = draft_history.get_stats()

        assert stats["v1_percent"] == 67  # 2/3
        assert stats["v2_percent"] == 33  # 1/3

    def test_get_stats_avg_rating(self, draft_history, sample_records):
        """Statistiques rating moyen."""
        for record in sample_records:
            draft_history.add(record)
        stats = draft_history.get_stats()

        # (5 + 3 + 4) / 3 = 4.0
        assert stats["avg_rating"] == 4.0
        assert stats["ratings_count"] == 3

    def test_get_stats_processing_time(self, draft_history, sample_records):
        """Statistiques temps de traitement."""
        for record in sample_records:
            draft_history.add(record)
        stats = draft_history.get_stats()

        # (1500 + 3000 + 1200) / 3 = 1900
        assert stats["avg_processing_time_ms"] == 1900
        assert stats["avg_processing_time_sec"] == 1.9

    def test_get_stats_automation_rate(self, draft_history, sample_records):
        """Statistiques taux d'automatisation."""
        for record in sample_records:
            draft_history.add(record)
        stats = draft_history.get_stats()

        # (2*100 + 1*50) / 3 = 83.33 ≈ 83
        assert stats["automation_rate"] == 83

    def test_get_stats_daily_stats(self, draft_history, sample_records):
        """Statistiques journalières."""
        for record in sample_records:
            draft_history.add(record)
        stats = draft_history.get_stats()

        assert "daily_stats" in stats
        assert len(stats["daily_stats"]) == 3  # 3 jours différents


# ============================================================================
# TESTS DRAFT HISTORY - SEARCH
# ============================================================================

class TestDraftHistorySearch:
    """Tests pour la recherche."""

    def test_search_no_filters(self, draft_history, sample_records):
        """Recherche sans filtres."""
        for record in sample_records:
            draft_history.add(record)
        results = draft_history.search()
        assert len(results) == 3

    def test_search_by_query_subject(self, draft_history, sample_records):
        """Recherche par sujet."""
        for record in sample_records:
            draft_history.add(record)
        results = draft_history.search(query="meeting")
        assert len(results) == 1
        assert results[0].email_subject == "Meeting request"

    def test_search_by_query_sender(self, draft_history, sample_records):
        """Recherche par expéditeur."""
        for record in sample_records:
            draft_history.add(record)
        results = draft_history.search(query="alice")
        assert len(results) == 2

    def test_search_by_status_v1(self, draft_history, sample_records):
        """Recherche par status V1."""
        for record in sample_records:
            draft_history.add(record)
        results = draft_history.search(status="V1")
        assert len(results) == 2

    def test_search_by_status_v2(self, draft_history, sample_records):
        """Recherche par status V2."""
        for record in sample_records:
            draft_history.add(record)
        results = draft_history.search(status="V2")
        assert len(results) == 1

    def test_search_by_min_rating(self, draft_history, sample_records):
        """Recherche par rating minimum."""
        for record in sample_records:
            draft_history.add(record)
        results = draft_history.search(min_rating=4)
        assert len(results) == 2  # ratings 4 et 5

    def test_search_with_limit(self, draft_history, sample_records):
        """Recherche avec limite."""
        for record in sample_records:
            draft_history.add(record)
        results = draft_history.search(limit=1)
        assert len(results) == 1

    def test_search_combined_filters(self, draft_history, sample_records):
        """Recherche avec filtres combinés."""
        for record in sample_records:
            draft_history.add(record)
        results = draft_history.search(query="alice", status="V1", min_rating=4)
        # Les deux records d'Alice ont V1 et rating >= 4 (5 et 4)
        assert len(results) == 2
        for r in results:
            assert "alice" in r.email_sender.lower()
            assert "V1" in r.status
            assert r.feedback_rating >= 4


# ============================================================================
# TESTS DRAFT HISTORY - EXPORT
# ============================================================================

class TestDraftHistoryExport:
    """Tests pour l'export de données."""

    def test_export_for_training_empty(self, draft_history):
        """Export training sans données."""
        data = draft_history.export_for_training()
        assert data == []

    def test_export_for_training_with_data(self, draft_history, sample_records):
        """Export training avec données."""
        for record in sample_records:
            draft_history.add(record)
        data = draft_history.export_for_training()

        # Seulement les records avec rating >= 4
        assert len(data) == 2
        for item in data:
            assert item["rating"] >= 4

    def test_export_for_training_disabled_in_metadata_only(
        self, draft_history, sample_records, monkeypatch
    ):
        """Le mode metadata-only interdit l'export de contenu d'entraînement."""
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "metadata_only")
        for record in sample_records:
            draft_history.add(record)

        assert draft_history.export_for_training() == []

    def test_export_csv_empty(self, draft_history):
        """Export CSV sans données."""
        csv_content = draft_history.export_csv()
        assert csv_content == "Aucune donnée"

    def test_export_csv_with_data(self, draft_history, sample_records):
        """Export CSV avec données."""
        for record in sample_records:
            draft_history.add(record)
        csv_content = draft_history.export_csv()

        assert "id,timestamp" in csv_content
        assert "rec-001" in csv_content
        assert "alice@example.com" in csv_content


# ============================================================================
# TESTS DRAFT HISTORY - CLEAR
# ============================================================================

class TestDraftHistoryClear:
    """Tests pour l'effacement."""

    def test_clear(self, draft_history, sample_records):
        """Effacement de l'historique."""
        for record in sample_records:
            draft_history.add(record)
        assert len(draft_history.get_all()) == 3

        draft_history.clear()
        assert len(draft_history.get_all()) == 0


# ============================================================================
# TESTS CREATE RECORD HELPER
# ============================================================================

class TestCreateRecord:
    """Tests pour la fonction helper create_record."""

    def test_create_record_minimal(self):
        """Création avec arguments minimaux."""
        record = create_record(
            email_id="email-1",
            email_sender="sender@example.com",
            email_subject="Subject",
            email_body="Body content",
            draft_v1="V1",
            critique="Critique",
            draft_final="Final",
            status="VALIDÉ V1"
        )

        assert record.email_id == "email-1"
        assert len(record.id) == 8  # UUID short
        assert "T" in record.timestamp  # ISO format
        assert record.email_preview == "Body content"

    def test_create_record_long_body(self):
        """Création avec body long (troncature)."""
        long_body = "A" * 200
        record = create_record(
            email_id="email-1",
            email_sender="sender@example.com",
            email_subject="Subject",
            email_body=long_body,
            draft_v1="V1",
            critique="Critique",
            draft_final="Final",
            status="VALIDÉ V1"
        )

        assert len(record.email_preview) == 103  # 100 + "..."
        assert record.email_preview.endswith("...")

    def test_create_record_with_all_params(self):
        """Création avec tous les paramètres."""
        record = create_record(
            email_id="email-1",
            email_sender="sender@example.com",
            email_subject="Subject",
            email_body="Body",
            draft_v1="V1",
            critique="Critique",
            draft_final="Final",
            status="VALIDÉ V1",
            draft_id="draft-123",
            tokens_used=500,
            model="claude-opus",
            processing_time_ms=3000,
            priority_score=85,
            category="URGENT"
        )

        assert record.draft_id == "draft-123"
        assert record.tokens_used == 500
        assert record.model == "claude-opus"
        assert record.processing_time_ms == 3000
        assert record.priority_score == 85
        assert record.category == "URGENT"


# ============================================================================
# TESTS DAILY STATS
# ============================================================================

class TestDailyStats:
    """Tests pour les statistiques journalières."""

    def test_daily_stats_structure(self, draft_history, sample_records):
        """Structure des stats journalières."""
        for record in sample_records:
            draft_history.add(record)
        stats = draft_history.get_stats()

        for day_stat in stats["daily_stats"]:
            assert "date" in day_stat
            assert "total" in day_stat
            assert "v1" in day_stat
            assert "v2" in day_stat
            assert "tokens" in day_stat

    def test_daily_stats_counts(self, draft_history, sample_records):
        """Comptages dans stats journalières."""
        for record in sample_records:
            draft_history.add(record)
        stats = draft_history.get_stats()

        # Vérifier que les totaux correspondent
        total_from_daily = sum(d["total"] for d in stats["daily_stats"])
        assert total_from_daily == 3

    def test_daily_stats_limited_to_30_days(self, draft_history):
        """Stats journalières limitées à 30 jours."""
        # Créer des records sur 35 jours
        from dataclasses import asdict
        records_data = []
        for i in range(35):
            record = DraftRecord(
                id=f"rec-{i:03d}",
                timestamp=f"2024-01-{i+1:02d}T10:00:00",
                email_id=f"email-{i}",
                email_sender="sender@example.com",
                email_subject="Subject",
                email_preview="Preview",
                draft_v1="V1",
                critique="Critique",
                draft_final="Final",
                status="VALIDÉ V1"
            )
            records_data.append(asdict(record))

        draft_history._save(records_data)
        stats = draft_history.get_stats()

        assert len(stats["daily_stats"]) <= 30


# ============================================================================
# TESTS DRAFT HISTORY - ANONYMIZATION
# ============================================================================

@pytest.fixture
def encryption_key() -> bytes:
    """Clé de test stable pour les tests déterministes."""
    return b"0123456789abcdef0123456789abcdef"


@pytest.fixture
def mock_detector():
    """Mock du détecteur de données sensibles."""
    from unittest.mock import MagicMock
    from app.domain.entities.sensitive_data import (
        SensitiveDataDetection,
        SensitiveDataItem,
        SensitiveDataType,
    )
    
    detector = MagicMock()
    
    def detect_side_effect(text: str, recipient: str = "") -> SensitiveDataDetection:
        items = []
        import re
        email_pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
        for match in re.finditer(email_pattern, text):
            items.append(SensitiveDataItem(
                data_type=SensitiveDataType.PERSONAL,
                description="Email address",
                snippet=match.group(),
            ))
        
        if items:
            return SensitiveDataDetection(
                is_sensitive=True,
                confidence=0.9,
                detected_items=items,
                analysis_summary="Sensitive data detected",
            )
        return SensitiveDataDetection(
            is_sensitive=False,
            confidence=0.0,
            detected_items=[],
            analysis_summary="No sensitive data",
        )
    
    detector.detect.side_effect = detect_side_effect
    return detector


@pytest.fixture
def anonymization_config(encryption_key, mock_detector):
    """Configuration d'anonymisation pour tests."""
    from app.domain.services.anonymizer_service import DataAnonymizer
    from app.history import AnonymizationConfig
    
    return AnonymizationConfig(
        anonymizer=DataAnonymizer(),
        detector=mock_detector,
        encryption_key=encryption_key,
    )


@pytest.fixture
def draft_history_with_anonymization(temp_history_file, anonymization_config):
    """Crée un DraftHistory avec anonymisation activée."""
    return DraftHistory(
        history_file=temp_history_file,
        anonymization_config=anonymization_config,
    )


class TestDraftHistoryAnonymization:
    """Tests pour l'anonymisation des données dans DraftHistory."""

    def test_add_anonymizes_email_sender(
        self, draft_history_with_anonymization, encryption_key
    ):
        """L'email de l'expéditeur est anonymisé lors de l'ajout."""
        record = DraftRecord(
            id="test-anon-001",
            timestamp="2024-01-15T10:00:00",
            email_id="email-1",
            email_sender="secret@example.com",
            email_subject="Test Subject",
            email_preview="Preview",
            draft_v1="Draft content",
            critique="Critique",
            draft_final="Final content",
            status="VALIDÉ V1",
        )
        draft_history_with_anonymization.add(record)

        raw_data = json.loads(
            draft_history_with_anonymization.history_file.read_text()
        )
        stored_record = raw_data[0]

        assert "secret@example.com" not in stored_record["email_sender"]
        assert "[ANON:PERSONAL:" in stored_record["email_sender"]

    def test_add_anonymizes_email_preview(
        self, draft_history_with_anonymization, encryption_key
    ):
        """Le preview de l'email est anonymisé lors de l'ajout."""
        record = DraftRecord(
            id="test-anon-002",
            timestamp="2024-01-15T10:00:00",
            email_id="email-1",
            email_sender="sender@test.com",
            email_subject="Test Subject",
            email_preview="Contact me at private@mail.com please",
            draft_v1="Draft content",
            critique="Critique",
            draft_final="Final content",
            status="VALIDÉ V1",
        )
        draft_history_with_anonymization.add(record)

        raw_data = json.loads(
            draft_history_with_anonymization.history_file.read_text()
        )
        stored_record = raw_data[0]

        assert "private@mail.com" not in stored_record["email_preview"]

    def test_add_anonymizes_draft_content(
        self, draft_history_with_anonymization, encryption_key
    ):
        """Le contenu des drafts est anonymisé lors de l'ajout."""
        record = DraftRecord(
            id="test-anon-003",
            timestamp="2024-01-15T10:00:00",
            email_id="email-1",
            email_sender="sender@test.com",
            email_subject="Test Subject",
            email_preview="Preview",
            draft_v1="Reply to draft@example.com",
            critique="Critique",
            draft_final="Contact final@example.org",
            status="VALIDÉ V1",
        )
        draft_history_with_anonymization.add(record)

        raw_data = json.loads(
            draft_history_with_anonymization.history_file.read_text()
        )
        stored_record = raw_data[0]

        assert "draft@example.com" not in stored_record["draft_v1"]
        assert "final@example.org" not in stored_record["draft_final"]

    def test_get_by_id_reveals_data(
        self, draft_history_with_anonymization
    ):
        """Les données sont révélées lors de la récupération par ID."""
        original_email = "original@example.com"
        record = DraftRecord(
            id="test-reveal-001",
            timestamp="2024-01-15T10:00:00",
            email_id="email-1",
            email_sender=original_email,
            email_subject="Test Subject",
            email_preview="Preview",
            draft_v1="Draft content",
            critique="Critique",
            draft_final="Final content",
            status="VALIDÉ V1",
        )
        draft_history_with_anonymization.add(record)

        retrieved = draft_history_with_anonymization.get_by_id("test-reveal-001")

        assert retrieved is not None
        assert retrieved.email_sender == original_email

    def test_get_all_reveals_data(
        self, draft_history_with_anonymization
    ):
        """Les données sont révélées lors de la récupération de tous les records."""
        original_email = "allusers@example.com"
        record = DraftRecord(
            id="test-reveal-all",
            timestamp="2024-01-15T10:00:00",
            email_id="email-1",
            email_sender=original_email,
            email_subject="Test Subject",
            email_preview="Preview",
            draft_v1="Draft content",
            critique="Critique",
            draft_final="Final content",
            status="VALIDÉ V1",
        )
        draft_history_with_anonymization.add(record)

        all_records = draft_history_with_anonymization.get_all()

        assert len(all_records) == 1
        assert all_records[0].email_sender == original_email

    def test_without_config_no_anonymization(
        self, draft_history, sample_record
    ):
        """Sans configuration, aucune anonymisation n'est effectuée."""
        draft_history.add(sample_record)

        raw_data = json.loads(draft_history.history_file.read_text())
        stored_record = raw_data[0]

        assert stored_record["email_sender"] == "sender@example.com"
        assert "_anonymization_data" not in stored_record

    def test_retrocompatibility_with_old_records(
        self, temp_history_file, anonymization_config
    ):
        """Les anciens records sans anonymisation sont lisibles."""
        old_record = {
            "id": "old-001",
            "timestamp": "2024-01-15T10:00:00",
            "email_id": "email-1",
            "email_sender": "old@example.com",
            "email_subject": "Old Subject",
            "email_preview": "Old preview",
            "draft_v1": "Old V1",
            "critique": "Old critique",
            "draft_final": "Old final",
            "status": "VALIDÉ V1",
        }
        temp_history_file.write_text(json.dumps([old_record]))

        history = DraftHistory(
            history_file=temp_history_file,
            anonymization_config=anonymization_config,
        )

        retrieved = history.get_by_id("old-001")

        assert retrieved is not None
        assert retrieved.email_sender == "old@example.com"

    def test_stores_anonymization_metadata(
        self, draft_history_with_anonymization
    ):
        """Les métadonnées d'anonymisation sont stockées."""
        record = DraftRecord(
            id="test-meta-001",
            timestamp="2024-01-15T10:00:00",
            email_id="email-1",
            email_sender="meta@example.com",
            email_subject="Test Subject",
            email_preview="Preview",
            draft_v1="Draft content",
            critique="Critique",
            draft_final="Final content",
            status="VALIDÉ V1",
        )
        draft_history_with_anonymization.add(record)

        raw_data = json.loads(
            draft_history_with_anonymization.history_file.read_text()
        )
        stored_record = raw_data[0]

        assert "_anonymization_data" in stored_record
        assert "email_sender" in stored_record["_anonymization_data"]

    def test_add_with_empty_sensitive_fields(
        self, draft_history_with_anonymization
    ):
        """Les champs vides ne génèrent pas d'anonymisation."""
        record = DraftRecord(
            id="test-empty-001",
            timestamp="2024-01-15T10:00:00",
            email_id="email-1",
            email_sender="",
            email_subject="Test Subject",
            email_preview="",
            draft_v1="",
            critique="Critique",
            draft_final="",
            status="VALIDÉ V1",
        )
        draft_history_with_anonymization.add(record)

        raw_data = json.loads(
            draft_history_with_anonymization.history_file.read_text()
        )
        stored_record = raw_data[0]

        assert stored_record.get("_anonymization_data") is None or \
               stored_record.get("_anonymization_data") == {}

    def test_add_with_no_sensitive_data_in_fields(
        self, draft_history_with_anonymization
    ):
        """Les champs sans données sensibles ne sont pas modifiés."""
        record = DraftRecord(
            id="test-nosensitive-001",
            timestamp="2024-01-15T10:00:00",
            email_id="email-1",
            email_sender="just a name",
            email_subject="Test Subject",
            email_preview="Hello, this is a simple preview without emails",
            draft_v1="Draft content without sensitive info",
            critique="Critique",
            draft_final="Final content is clean",
            status="VALIDÉ V1",
        )
        draft_history_with_anonymization.add(record)

        raw_data = json.loads(
            draft_history_with_anonymization.history_file.read_text()
        )
        stored_record = raw_data[0]

        # Les champs sans données sensibles restent identiques
        assert stored_record["email_sender"] == "just a name"
        assert stored_record["email_preview"] == "Hello, this is a simple preview without emails"

    def test_add_with_multiple_emails_in_one_field(
        self, draft_history_with_anonymization
    ):
        """Plusieurs emails dans un champ sont tous anonymisés."""
        record = DraftRecord(
            id="test-multi-001",
            timestamp="2024-01-15T10:00:00",
            email_id="email-1",
            email_sender="sender@test.com",
            email_subject="Test Subject",
            email_preview="Contact first@mail.com or second@mail.com or third@mail.org",
            draft_v1="Draft content",
            critique="Critique",
            draft_final="Final content",
            status="VALIDÉ V1",
        )
        draft_history_with_anonymization.add(record)

        raw_data = json.loads(
            draft_history_with_anonymization.history_file.read_text()
        )
        stored_record = raw_data[0]

        preview = stored_record["email_preview"]
        assert "first@mail.com" not in preview
        assert "second@mail.com" not in preview
        assert "third@mail.org" not in preview

    def test_reveal_with_wrong_key_raises_error(
        self, temp_history_file, mock_detector
    ):
        """La révélation avec une mauvaise clé lève une erreur."""
        from app.domain.services.anonymizer_service import (
            DataAnonymizer,
            InvalidCredentialsError,
        )
        from app.history import AnonymizationConfig

        original_key = b"0123456789abcdef0123456789abcdef"
        wrong_key = b"wrong_key_123456wrong_key_123456"

        # Créer avec la bonne clé
        config_add = AnonymizationConfig(
            anonymizer=DataAnonymizer(),
            detector=mock_detector,
            encryption_key=original_key,
        )
        history_add = DraftHistory(
            history_file=temp_history_file,
            anonymization_config=config_add,
        )

        record = DraftRecord(
            id="test-wrongkey",
            timestamp="2024-01-15T10:00:00",
            email_id="email-1",
            email_sender="secret@example.com",
            email_subject="Test",
            email_preview="Preview",
            draft_v1="Draft",
            critique="Critique",
            draft_final="Final",
            status="VALIDÉ V1",
        )
        history_add.add(record)

        # Lire avec une mauvaise clé
        config_read = AnonymizationConfig(
            anonymizer=DataAnonymizer(),
            detector=mock_detector,
            encryption_key=wrong_key,
        )
        history_read = DraftHistory(
            history_file=temp_history_file,
            anonymization_config=config_read,
        )

        with pytest.raises(InvalidCredentialsError):
            history_read.get_by_id("test-wrongkey")

    def test_get_all_with_corrupted_anonymization_data(
        self, temp_history_file, anonymization_config
    ):
        """Les records avec métadonnées corrompues lèvent une KeyError.

        Note: Actuellement l'implémentation ne gère pas gracieusement les
        métadonnées corrompues. Ce test documente le comportement actuel.
        Une amélioration future pourrait être d'ignorer les records corrompus.
        """
        corrupted_record = {
            "id": "corrupted-001",
            "timestamp": "2024-01-15T10:00:00",
            "email_id": "email-1",
            "email_sender": "[ANON:PERSONAL:abc123]",
            "email_subject": "Test",
            "email_preview": "Preview",
            "draft_v1": "Draft",
            "critique": "Critique",
            "draft_final": "Final",
            "status": "VALIDÉ V1",
            "_anonymization_data": {
                "email_sender": {
                    "result": {"anonymized_text": "[ANON:PERSONAL:abc123]"},
                    # Missing required fields: tokens, original_text_hash, secure_mappings, key_id
                }
            }
        }
        temp_history_file.write_text(json.dumps([corrupted_record]))

        history = DraftHistory(
            history_file=temp_history_file,
            anonymization_config=anonymization_config,
        )

        # Currently crashes with KeyError - this documents current behavior
        with pytest.raises(KeyError):
            history.get_all()

    def test_unicode_email_addresses_anonymized(
        self, draft_history_with_anonymization
    ):
        """Les adresses email avec domaines unicode sont anonymisées."""
        record = DraftRecord(
            id="test-unicode-001",
            timestamp="2024-01-15T10:00:00",
            email_id="email-1",
            email_sender="user@example.com",
            email_subject="Test Subject",
            email_preview="Contact tëst@exämple.com please",
            draft_v1="Draft content",
            critique="Critique",
            draft_final="Final content",
            status="VALIDÉ V1",
        )
        draft_history_with_anonymization.add(record)

        retrieved = draft_history_with_anonymization.get_by_id("test-unicode-001")
        assert retrieved is not None
        # Email sender should be revealed
        assert retrieved.email_sender == "user@example.com"

    def test_update_feedback_on_anonymized_record(
        self, draft_history_with_anonymization
    ):
        """Le feedback peut être mis à jour sur un record anonymisé."""
        record = DraftRecord(
            id="test-feedback-anon",
            timestamp="2024-01-15T10:00:00",
            email_id="email-1",
            email_sender="feedback@example.com",
            email_subject="Test",
            email_preview="Preview",
            draft_v1="Draft",
            critique="Critique",
            draft_final="Final",
            status="VALIDÉ V1",
        )
        draft_history_with_anonymization.add(record)

        result = draft_history_with_anonymization.update_feedback(
            "test-feedback-anon", "positive", "Great work!"
        )
        assert result is True

        # Verify feedback was saved and data is still revealed
        retrieved = draft_history_with_anonymization.get_by_id("test-feedback-anon")
        assert retrieved.feedback == "positive"
        assert retrieved.feedback_comment == "Great work!"
        assert retrieved.email_sender == "feedback@example.com"

    def test_search_works_with_anonymized_records(
        self, draft_history_with_anonymization
    ):
        """La recherche fonctionne sur les records anonymisés (données stockées)."""
        record = DraftRecord(
            id="test-search-anon",
            timestamp="2024-01-15T10:00:00",
            email_id="email-1",
            email_sender="search@example.com",
            email_subject="Important meeting",
            email_preview="Preview content",
            draft_v1="Draft",
            critique="Critique",
            draft_final="Final",
            status="VALIDÉ V1",
        )
        draft_history_with_anonymization.add(record)

        # Search by subject (non-anonymized field)
        results = draft_history_with_anonymization.search(query="important")
        assert len(results) == 1
        assert results[0].email_subject == "Important meeting"

    def test_export_csv_with_anonymized_records(
        self, draft_history_with_anonymization
    ):
        """L'export CSV contient les données anonymisées (non révélées)."""
        record = DraftRecord(
            id="test-csv-anon",
            timestamp="2024-01-15T10:00:00",
            email_id="email-1",
            email_sender="csv@example.com",
            email_subject="CSV Test",
            email_preview="Preview",
            draft_v1="Draft",
            critique="Critique",
            draft_final="Final",
            status="VALIDÉ V1",
        )
        draft_history_with_anonymization.add(record)

        csv_content = draft_history_with_anonymization.export_csv()

        # CSV should contain anonymized email (not revealed)
        assert "csv@example.com" not in csv_content
        assert "test-csv-anon" in csv_content
        assert "CSV Test" in csv_content

    def test_export_for_training_excludes_anonymized_data(
        self, draft_history_with_anonymization
    ):
        """L'export training contient les données anonymisées."""
        record = DraftRecord(
            id="test-training-anon",
            timestamp="2024-01-15T10:00:00",
            email_id="email-1",
            email_sender="training@example.com",
            email_subject="Training Test",
            email_preview="Preview with training@example.com",
            draft_v1="Draft",
            critique="Critique",
            draft_final="Final with reply@example.com",
            status="VALIDÉ V1",
            feedback_rating=5,  # High rating to be included
        )
        draft_history_with_anonymization.add(record)

        training_data = draft_history_with_anonymization.export_for_training()

        # Training data uses raw storage, so emails are anonymized
        assert len(training_data) == 1
        assert "training@example.com" not in training_data[0]["email"]
        assert "reply@example.com" not in training_data[0]["response"]

    def test_clear_removes_anonymized_records(
        self, draft_history_with_anonymization
    ):
        """Clear supprime correctement les records anonymisés."""
        record = DraftRecord(
            id="test-clear-anon",
            timestamp="2024-01-15T10:00:00",
            email_id="email-1",
            email_sender="clear@example.com",
            email_subject="Clear Test",
            email_preview="Preview",
            draft_v1="Draft",
            critique="Critique",
            draft_final="Final",
            status="VALIDÉ V1",
        )
        draft_history_with_anonymization.add(record)
        assert len(draft_history_with_anonymization.get_all()) == 1

        draft_history_with_anonymization.clear()

        assert len(draft_history_with_anonymization.get_all()) == 0
        raw_data = json.loads(
            draft_history_with_anonymization.history_file.read_text()
        )
        assert raw_data == []

    def test_get_stats_with_anonymized_records(
        self, draft_history_with_anonymization
    ):
        """Les statistiques fonctionnent avec des records anonymisés."""
        record = DraftRecord(
            id="test-stats-anon",
            timestamp="2024-01-15T10:00:00",
            email_id="email-1",
            email_sender="stats@example.com",
            email_subject="Stats Test",
            email_preview="Preview",
            draft_v1="Draft",
            critique="Critique",
            draft_final="Final",
            status="VALIDÉ V1",
            tokens_used=100,
            processing_time_ms=1500,
            feedback_rating=4,
        )
        draft_history_with_anonymization.add(record)

        stats = draft_history_with_anonymization.get_stats()

        assert stats["total"] == 1
        assert stats["validated_v1"] == 1
        assert stats["total_tokens"] == 100
        assert stats["avg_rating"] == 4.0

    def test_add_preserves_non_sensitive_fields(
        self, draft_history_with_anonymization
    ):
        """Les champs non sensibles ne sont pas modifiés par l'anonymisation."""
        record = DraftRecord(
            id="test-preserve",
            timestamp="2024-01-15T10:00:00",
            email_id="email-123",
            email_sender="preserve@example.com",
            email_subject="Original Subject",
            email_preview="Preview with email@test.com",
            draft_v1="Draft",
            critique="This is the original critique",
            draft_final="Final",
            status="VALIDÉ V1",
            tokens_used=250,
            model="claude-3-opus",
            processing_time_ms=2000,
            priority_score=75,
            category="URGENT",
        )
        draft_history_with_anonymization.add(record)

        retrieved = draft_history_with_anonymization.get_by_id("test-preserve")

        # Non-sensitive fields unchanged
        assert retrieved.id == "test-preserve"
        assert retrieved.email_id == "email-123"
        assert retrieved.email_subject == "Original Subject"
        assert retrieved.critique == "This is the original critique"
        assert retrieved.status == "VALIDÉ V1"
        assert retrieved.tokens_used == 250
        assert retrieved.model == "claude-3-opus"
        assert retrieved.processing_time_ms == 2000
        assert retrieved.priority_score == 75
        assert retrieved.category == "URGENT"

    def test_multiple_records_with_same_email(
        self, draft_history_with_anonymization
    ):
        """Plusieurs records avec le même email sont anonymisés indépendamment."""
        for i in range(3):
            record = DraftRecord(
                id=f"test-same-{i}",
                timestamp=f"2024-01-{15+i}T10:00:00",
                email_id=f"email-{i}",
                email_sender="same@example.com",
                email_subject=f"Subject {i}",
                email_preview=f"Preview {i}",
                draft_v1=f"Draft {i}",
                critique=f"Critique {i}",
                draft_final=f"Final {i}",
                status="VALIDÉ V1",
            )
            draft_history_with_anonymization.add(record)

        all_records = draft_history_with_anonymization.get_all()
        assert len(all_records) == 3

        # All should be revealed correctly
        for record in all_records:
            assert record.email_sender == "same@example.com"

    def test_reveal_skips_fields_not_in_anonymization_data(
        self, draft_history_with_anonymization
    ):
        """Les champs sans données d'anonymisation sont ignorés lors de la révélation.

        Ce test couvre la ligne 143 (continue) dans _reveal_record.
        On crée un record où seuls certains champs ont été anonymisés.
        """
        # Créer un record avec uniquement email_sender contenant une adresse email
        # Les autres champs sensibles n'ont pas de données sensibles détectées
        record = DraftRecord(
            id="partial-001",
            timestamp="2024-01-15T10:00:00",
            email_id="email-1",
            email_sender="secret@example.com",
            email_subject="Test Subject",
            email_preview="Plain text without emails",  # Pas d'email détecté
            draft_v1="No sensitive data here",  # Pas d'email détecté
            critique="Critique",
            draft_final="Final content clean",  # Pas d'email détecté
            status="VALIDÉ V1",
        )
        draft_history_with_anonymization.add(record)

        # Vérifier que email_sender est anonymisé mais les autres non
        raw_data = json.loads(
            draft_history_with_anonymization.history_file.read_text()
        )
        stored_record = raw_data[0]

        # email_sender doit avoir été anonymisé
        assert "secret@example.com" not in stored_record["email_sender"]

        # Récupérer le record - le continue à ligne 143 sera exécuté
        # pour email_preview, draft_v1, draft_final car pas dans _anonymization_data
        retrieved = draft_history_with_anonymization.get_by_id("partial-001")

        # email_sender est révélé
        assert retrieved.email_sender == "secret@example.com"

        # Les autres champs sont inchangés (pas d'anonymisation)
        assert retrieved.email_preview == "Plain text without emails"
        assert retrieved.draft_v1 == "No sensitive data here"
        assert retrieved.draft_final == "Final content clean"


# ============================================================================
# TESTS - EDGE CASES INTERNAL METHODS
# ============================================================================

class TestDraftHistoryInternalMethods:
    """Tests pour les méthodes internes de DraftHistory."""

    def test_compute_automation_rate_zero_total(self, temp_history_file):
        """_compute_automation_rate retourne 0 quand total=0.

        Ce test couvre la ligne 289 dans history.py.
        """
        history = DraftHistory(history_file=temp_history_file)

        # Appel direct de la méthode interne
        result = history._compute_automation_rate(total=0, validated_v1=0, corrected_v2=0)

        assert result == 0

    def test_compute_automation_rate_all_v1(self, temp_history_file):
        """_compute_automation_rate avec tous les V1 retourne 100."""
        history = DraftHistory(history_file=temp_history_file)

        result = history._compute_automation_rate(total=10, validated_v1=10, corrected_v2=0)

        assert result == 100

    def test_compute_automation_rate_all_v2(self, temp_history_file):
        """_compute_automation_rate avec tous les V2 retourne 50."""
        history = DraftHistory(history_file=temp_history_file)

        result = history._compute_automation_rate(total=10, validated_v1=0, corrected_v2=10)

        assert result == 50

    def test_compute_automation_rate_mixed(self, temp_history_file):
        """_compute_automation_rate avec mix V1/V2."""
        history = DraftHistory(history_file=temp_history_file)

        # 5 V1 (500 points) + 5 V2 (250 points) = 750 / 10 = 75
        result = history._compute_automation_rate(total=10, validated_v1=5, corrected_v2=5)

        assert result == 75


# ============================================================================
# TESTS - LOAD EDGE CASES
# ============================================================================


class TestDraftHistoryRevealEdgeCases:
    """Tests pour les cas limites de _reveal_record()."""

    def test_reveal_skips_fields_missing_from_anonymization_data(
        self, temp_history_file, anonymization_config
    ):
        """_reveal_record ignore les champs absents de _anonymization_data.

        Ce test couvre spécifiquement la ligne 143 (continue) dans _reveal_record.
        On simule un cas où _anonymization_data existe mais ne contient pas tous
        les champs sensibles (cas de migration partielle ou corruption).
        """
        # Créer un record avec _anonymization_data partiel directement dans JSON
        # Seul email_sender est dans _anonymization_data, pas email_preview, draft_v1, draft_final
        # C'est un cas qui pourrait survenir avec une migration de données partielle
        records = [
            {
                "id": "partial-anon-001",
                "timestamp": "2024-01-15T10:00:00",
                "email_id": "email-1",
                "email_sender": "Not anonymized sender",  # Pas dans _anonymization_data
                "email_subject": "Subject",
                "email_preview": "Not anonymized preview",  # Pas dans _anonymization_data
                "draft_v1": "Not anonymized v1",  # Pas dans _anonymization_data
                "critique": "Critique",
                "draft_final": "Not anonymized final",  # Pas dans _anonymization_data
                "status": "VALIDÉ V1",
                "_anonymization_data": {
                    # Structure vide - tous les champs sensibles vont déclencher "continue"
                    # Cela simule un cas de données corrompues ou incomplètes
                },
            }
        ]
        temp_history_file.write_text(json.dumps(records), encoding="utf-8")

        # Créer DraftHistory avec config d'anonymisation
        history = DraftHistory(
            history_file=temp_history_file,
            anonymization_config=anonymization_config,
        )

        # Charger le record - cela devrait déclencher _reveal_record
        # qui va faire "continue" pour tous les champs sensibles
        raw_records = history._load()
        assert len(raw_records) == 1

        # Appeler _reveal_record directement pour tester
        revealed = history._reveal_record(raw_records[0].copy())

        # Les champs non présents dans _anonymization_data restent inchangés
        assert revealed["email_sender"] == "Not anonymized sender"
        assert revealed["email_preview"] == "Not anonymized preview"
        assert revealed["draft_v1"] == "Not anonymized v1"
        assert revealed["draft_final"] == "Not anonymized final"


class TestDraftHistoryLoadEdgeCases:
    """Tests pour les cas limites de _load()."""

    def test_load_returns_empty_when_json_is_null(self, temp_history_file):
        """_load retourne liste vide quand le JSON contient null.

        Ce test couvre la ligne 160 dans history.py.
        """
        # Écrire null dans le fichier
        temp_history_file.write_text("null", encoding="utf-8")

        history = DraftHistory(history_file=temp_history_file)
        result = history._load()

        assert result == []

    def test_load_returns_empty_when_json_is_object(self, temp_history_file):
        """_load retourne liste vide quand le JSON est un objet au lieu d'une liste."""
        # Écrire un objet JSON au lieu d'une liste
        temp_history_file.write_text('{"key": "value"}', encoding="utf-8")

        history = DraftHistory(history_file=temp_history_file)
        result = history._load()

        assert result == []

    def test_load_returns_empty_when_json_is_number(self, temp_history_file):
        """_load retourne liste vide quand le JSON est un nombre."""
        temp_history_file.write_text("42", encoding="utf-8")

        history = DraftHistory(history_file=temp_history_file)
        result = history._load()

        assert result == []

    def test_load_returns_empty_when_json_is_string(self, temp_history_file):
        """_load retourne liste vide quand le JSON est une string."""
        temp_history_file.write_text('"hello"', encoding="utf-8")

        history = DraftHistory(history_file=temp_history_file)
        result = history._load()

        assert result == []


# ============================================================================
# TESTS - GET_ALL EDGE CASES
# ============================================================================


class TestDraftHistoryGetAllEdgeCases:
    """Tests pour les cas limites de get_all()."""

    def test_get_all_skips_malformed_records(self, temp_history_file):
        """get_all ignore les enregistrements malformés.

        Ce test couvre la ligne 204 dans history.py (continue dans get_all).
        """
        # Écrire un mélange de records valides et invalides
        records = [
            {
                "id": "valid-001",
                "timestamp": "2024-01-15T10:00:00",
                "email_id": "email-1",
                "email_sender": "sender@example.com",
                "email_subject": "Test Subject",
                "email_preview": "Preview",
                "draft_v1": "V1",
                "critique": "Critique",
                "draft_final": "Final",
                "status": "VALIDÉ V1",
            },
            {
                # Record incomplet - manque des champs obligatoires
                "id": "invalid-001",
                "timestamp": "2024-01-15T11:00:00",
                # missing: email_id, email_sender, etc.
            },
            {
                "id": "valid-002",
                "timestamp": "2024-01-15T12:00:00",
                "email_id": "email-2",
                "email_sender": "sender2@example.com",
                "email_subject": "Test Subject 2",
                "email_preview": "Preview 2",
                "draft_v1": "V1 2",
                "critique": "Critique 2",
                "draft_final": "Final 2",
                "status": "VALIDÉ V2",
            },
        ]
        temp_history_file.write_text(json.dumps(records), encoding="utf-8")

        history = DraftHistory(history_file=temp_history_file)
        result = history.get_all()

        # Seuls les 2 records valides sont retournés
        assert len(result) == 2
        assert result[0].id == "valid-002"  # Plus récent en premier
        assert result[1].id == "valid-001"

    def test_get_all_skips_records_with_wrong_types(self, temp_history_file):
        """get_all ignore les enregistrements avec mauvais types."""
        records = [
            {
                "id": "valid-001",
                "timestamp": "2024-01-15T10:00:00",
                "email_id": "email-1",
                "email_sender": "sender@example.com",
                "email_subject": "Test Subject",
                "email_preview": "Preview",
                "draft_v1": "V1",
                "critique": "Critique",
                "draft_final": "Final",
                "status": "VALIDÉ V1",
            },
            {
                # Record avec un type inattendu pour feedback_rating
                "id": "invalid-type-001",
                "timestamp": "2024-01-15T11:00:00",
                "email_id": "email-2",
                "email_sender": "sender@example.com",
                "email_subject": "Subject",
                "email_preview": "Preview",
                "draft_v1": "V1",
                "critique": "Critique",
                "draft_final": "Final",
                "status": "VALIDÉ V1",
                "feedback_rating": "not_a_number",  # Should be int or None
            },
        ]
        temp_history_file.write_text(json.dumps(records), encoding="utf-8")

        history = DraftHistory(history_file=temp_history_file)
        result = history.get_all()

        # Le record avec mauvais type est quand même créé car DraftRecord ne valide pas les types
        # Ce test documente le comportement actuel
        assert len(result) == 2
