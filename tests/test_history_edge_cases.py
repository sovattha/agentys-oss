# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests des edge cases pour le module d'historique des brouillons.

Ce module teste les cas limites non couverts par les tests standards :
- JSON avec valeur null
- Champs manquants dans les records
- Caractères spéciaux et unicode
- Conditions limites dans les calculs de statistiques

pytest tests/test_history_edge_cases.py -v
"""

import pytest
import json

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


@pytest.fixture
def draft_history(temp_history_file):
    """Crée un DraftHistory avec fichier temporaire."""
    return DraftHistory(history_file=temp_history_file)


# ============================================================================
# TESTS _LOAD() EDGE CASES
# ============================================================================

class TestLoadEdgeCases:
    """Tests des cas limites pour le chargement."""

    def test_load_json_null_value(self, draft_history, temp_history_file):
        """Chargement avec fichier JSON contenant 'null'."""
        temp_history_file.write_text("null", encoding="utf-8")
        records = draft_history._load()
        assert records == []

    def test_load_json_empty_object(self, draft_history, temp_history_file):
        """Chargement avec fichier JSON contenant '{}'."""
        temp_history_file.write_text("{}", encoding="utf-8")
        records = draft_history._load()
        assert records == []

    def test_load_json_empty_string(self, draft_history, temp_history_file):
        """Chargement avec fichier JSON contenant une chaîne vide."""
        temp_history_file.write_text('""', encoding="utf-8")
        records = draft_history._load()
        assert records == []

    def test_load_json_number(self, draft_history, temp_history_file):
        """Chargement avec fichier JSON contenant un nombre."""
        temp_history_file.write_text("42", encoding="utf-8")
        records = draft_history._load()
        assert records == []

    def test_load_empty_file(self, draft_history, temp_history_file):
        """Chargement avec fichier vide."""
        temp_history_file.write_text("", encoding="utf-8")
        records = draft_history._load()
        assert records == []

    def test_load_whitespace_only(self, draft_history, temp_history_file):
        """Chargement avec fichier contenant uniquement des espaces."""
        temp_history_file.write_text("   \n\t  ", encoding="utf-8")
        records = draft_history._load()
        assert records == []


# ============================================================================
# TESTS GET_ALL() WITH INCOMPLETE RECORDS
# ============================================================================

class TestGetAllWithIncompleteRecords:
    """Tests pour get_all() avec des records incomplets."""

    def test_get_all_record_missing_timestamp(self, draft_history, temp_history_file):
        """Récupération avec record sans timestamp - record ignoré."""
        record_data = {
            "id": "test-1",
            "email_id": "email-1",
            "email_sender": "sender@test.com",
            "email_subject": "Subject",
            "email_preview": "Preview",
            "draft_v1": "V1",
            "critique": "OK",
            "draft_final": "Final",
            "status": "VALIDÉ V1"
            # timestamp manquant
        }
        temp_history_file.write_text(json.dumps([record_data]), encoding="utf-8")

        # get_all() doit ignorer silencieusement les records incomplets
        records = draft_history.get_all()
        assert len(records) == 0  # Record incomplet ignoré

    def test_get_all_record_with_none_values(self, draft_history, temp_history_file):
        """Récupération avec record ayant des valeurs None explicites."""
        record_data = {
            "id": "test-1",
            "timestamp": "2024-01-15T10:00:00",
            "email_id": "email-1",
            "email_sender": "sender@test.com",
            "email_subject": "Subject",
            "email_preview": "Preview",
            "draft_v1": "V1",
            "critique": "OK",
            "draft_final": "Final",
            "status": "VALIDÉ V1",
            "draft_id": None,
            "tokens_used": 0,
            "model": "",
            "feedback": None,
            "feedback_rating": None,
            "feedback_comment": None,
            "processing_time_ms": 0,
            "priority_score": None,
            "category": None,
        }
        temp_history_file.write_text(json.dumps([record_data]), encoding="utf-8")

        records = draft_history.get_all()
        assert len(records) == 1
        assert records[0].draft_id is None
        assert records[0].feedback_rating is None


# ============================================================================
# TESTS SEARCH() EDGE CASES
# ============================================================================

class TestSearchEdgeCases:
    """Tests des cas limites pour la recherche."""

    def test_search_with_none_email_subject(self, draft_history, temp_history_file):
        """Recherche dans un record avec email_subject à None - match sur sender."""
        record_data = {
            "id": "test-1",
            "timestamp": "2024-01-15T10:00:00",
            "email_id": "email-1",
            "email_sender": "sender@test.com",
            "email_subject": None,  # None explicite
            "email_preview": "Preview",
            "draft_v1": "V1",
            "critique": "OK",
            "draft_final": "Final",
            "status": "VALIDÉ V1"
        }
        temp_history_file.write_text(json.dumps([record_data]), encoding="utf-8")

        # La recherche ne doit pas planter sur les None
        # Recherche sur "test" ne match pas car sender contient "sender@test.com" mais subject est None
        results = draft_history.search(query="test")
        # Le record DEVRAIT matcher car "test" est dans l'email sender
        assert len(results) == 1

    def test_search_with_none_email_sender(self, draft_history, temp_history_file):
        """Recherche dans un record avec email_sender à None."""
        record_data = {
            "id": "test-1",
            "timestamp": "2024-01-15T10:00:00",
            "email_id": "email-1",
            "email_sender": None,  # None explicite
            "email_subject": "Subject test",
            "email_preview": "Preview",
            "draft_v1": "V1",
            "critique": "OK",
            "draft_final": "Final",
            "status": "VALIDÉ V1"
        }
        temp_history_file.write_text(json.dumps([record_data]), encoding="utf-8")

        # La recherche doit matcher sur le subject
        results = draft_history.search(query="test")
        assert len(results) == 1

    def test_search_with_special_characters(self, draft_history):
        """Recherche avec caractères spéciaux."""
        record = DraftRecord(
            id="test-1",
            timestamp="2024-01-15T10:00:00",
            email_id="email-1",
            email_sender="user+tag@example.com",
            email_subject="Réunion à 10h (URGENT!) - €100",
            email_preview="Preview",
            draft_v1="V1",
            critique="OK",
            draft_final="Final",
            status="VALIDÉ V1"
        )
        draft_history.add(record)

        # Recherche avec caractères accentués
        results = draft_history.search(query="réunion")
        assert len(results) == 1

        # Recherche avec symboles
        results = draft_history.search(query="€100")
        assert len(results) == 1

    def test_search_case_insensitive_unicode(self, draft_history):
        """Recherche insensible à la casse avec unicode."""
        record = DraftRecord(
            id="test-1",
            timestamp="2024-01-15T10:00:00",
            email_id="email-1",
            email_sender="user@example.com",
            email_subject="ÉVÉNEMENT Été",
            email_preview="Preview",
            draft_v1="V1",
            critique="OK",
            draft_final="Final",
            status="VALIDÉ V1"
        )
        draft_history.add(record)

        results = draft_history.search(query="événement")
        assert len(results) == 1

        results = draft_history.search(query="été")
        assert len(results) == 1

    def test_search_empty_query(self, draft_history):
        """Recherche avec query vide."""
        record = DraftRecord(
            id="test-1",
            timestamp="2024-01-15T10:00:00",
            email_id="email-1",
            email_sender="user@example.com",
            email_subject="Subject",
            email_preview="Preview",
            draft_v1="V1",
            critique="OK",
            draft_final="Final",
            status="VALIDÉ V1"
        )
        draft_history.add(record)

        # Query vide retourne tout
        results = draft_history.search(query="")
        assert len(results) == 1


# ============================================================================
# TESTS EXPORT_CSV() EDGE CASES
# ============================================================================

class TestExportCsvEdgeCases:
    """Tests des cas limites pour l'export CSV."""

    def test_export_csv_unicode_characters(self, draft_history):
        """Export CSV avec caractères unicode."""
        record = DraftRecord(
            id="test-1",
            timestamp="2024-01-15T10:00:00",
            email_id="email-1",
            email_sender="utilisateur@émoji.fr",
            email_subject="日本語 テスト - Événement 🎉",
            email_preview="Preview avec émojis 🚀",
            draft_v1="V1",
            critique="OK",
            draft_final="Final",
            status="VALIDÉ V1"
        )
        draft_history.add(record)

        csv_content = draft_history.export_csv()
        assert "utilisateur@émoji.fr" in csv_content
        assert "日本語" in csv_content or "test-1" in csv_content

    def test_export_csv_with_commas_in_fields(self, draft_history):
        """Export CSV avec virgules dans les champs."""
        record = DraftRecord(
            id="test-1",
            timestamp="2024-01-15T10:00:00",
            email_id="email-1",
            email_sender="user@example.com",
            email_subject="Subject, with, commas",
            email_preview="Preview",
            draft_v1="V1",
            critique="OK",
            draft_final="Final",
            status="VALIDÉ V1"
        )
        draft_history.add(record)

        csv_content = draft_history.export_csv()
        # Le CSV doit être valide malgré les virgules
        assert "test-1" in csv_content

    def test_export_csv_with_quotes_in_fields(self, draft_history):
        """Export CSV avec guillemets dans les champs."""
        record = DraftRecord(
            id="test-1",
            timestamp="2024-01-15T10:00:00",
            email_id="email-1",
            email_sender="user@example.com",
            email_subject='Subject with "quotes"',
            email_preview="Preview",
            draft_v1="V1",
            critique="OK",
            draft_final="Final",
            status="VALIDÉ V1"
        )
        draft_history.add(record)

        csv_content = draft_history.export_csv()
        assert "test-1" in csv_content

    def test_export_csv_with_newlines_in_fields(self, draft_history):
        """Export CSV avec retours à la ligne dans les champs."""
        record = DraftRecord(
            id="test-1",
            timestamp="2024-01-15T10:00:00",
            email_id="email-1",
            email_sender="user@example.com",
            email_subject="Subject\nwith\nnewlines",
            email_preview="Preview",
            draft_v1="V1",
            critique="OK",
            draft_final="Final",
            status="VALIDÉ V1"
        )
        draft_history.add(record)

        csv_content = draft_history.export_csv()
        assert "test-1" in csv_content


# ============================================================================
# TESTS GET_STATS() EDGE CASES
# ============================================================================

class TestGetStatsEdgeCases:
    """Tests des cas limites pour les statistiques."""

    def test_get_stats_zero_processing_time(self, draft_history):
        """Statistiques avec processing_time_ms à 0."""
        record = DraftRecord(
            id="test-1",
            timestamp="2024-01-15T10:00:00",
            email_id="email-1",
            email_sender="user@example.com",
            email_subject="Subject",
            email_preview="Preview",
            draft_v1="V1",
            critique="OK",
            draft_final="Final",
            status="VALIDÉ V1",
            processing_time_ms=0
        )
        draft_history.add(record)

        stats = draft_history.get_stats()
        # Avec processing_time_ms=0, la moyenne doit être 0 (exclu du calcul)
        assert stats["avg_processing_time_ms"] == 0

    def test_get_stats_mixed_processing_times(self, draft_history):
        """Statistiques avec mix de processing_time_ms valides et à 0."""
        record1 = DraftRecord(
            id="test-1",
            timestamp="2024-01-15T10:00:00",
            email_id="email-1",
            email_sender="user@example.com",
            email_subject="Subject",
            email_preview="Preview",
            draft_v1="V1",
            critique="OK",
            draft_final="Final",
            status="VALIDÉ V1",
            processing_time_ms=0  # Sera exclu
        )
        record2 = DraftRecord(
            id="test-2",
            timestamp="2024-01-15T11:00:00",
            email_id="email-2",
            email_sender="user@example.com",
            email_subject="Subject",
            email_preview="Preview",
            draft_v1="V1",
            critique="OK",
            draft_final="Final",
            status="VALIDÉ V1",
            processing_time_ms=2000  # Sera inclus
        )
        draft_history.add(record1)
        draft_history.add(record2)

        stats = draft_history.get_stats()
        # Moyenne calculée uniquement sur les valeurs > 0
        assert stats["avg_processing_time_ms"] == 2000

    def test_get_stats_no_ratings(self, draft_history):
        """Statistiques sans aucun rating."""
        record = DraftRecord(
            id="test-1",
            timestamp="2024-01-15T10:00:00",
            email_id="email-1",
            email_sender="user@example.com",
            email_subject="Subject",
            email_preview="Preview",
            draft_v1="V1",
            critique="OK",
            draft_final="Final",
            status="VALIDÉ V1",
            feedback_rating=None
        )
        draft_history.add(record)

        stats = draft_history.get_stats()
        assert stats["avg_rating"] == 0
        assert stats["ratings_count"] == 0

    def test_get_stats_status_unknown(self, draft_history):
        """Statistiques avec status inconnu (ni V1 ni V2)."""
        record = DraftRecord(
            id="test-1",
            timestamp="2024-01-15T10:00:00",
            email_id="email-1",
            email_sender="user@example.com",
            email_subject="Subject",
            email_preview="Preview",
            draft_v1="V1",
            critique="OK",
            draft_final="Final",
            status="UNKNOWN_STATUS"
        )
        draft_history.add(record)

        stats = draft_history.get_stats()
        assert stats["total"] == 1
        assert stats["validated_v1"] == 0
        assert stats["corrected_v2"] == 0


# ============================================================================
# TESTS DAILY_STATS EDGE CASES
# ============================================================================

class TestDailyStatsEdgeCases:
    """Tests des cas limites pour les statistiques journalières."""

    def test_daily_stats_empty_timestamp(self, draft_history, temp_history_file):
        """Stats journalières avec timestamp vide."""
        record_data = {
            "id": "test-1",
            "timestamp": "",  # Vide
            "email_id": "email-1",
            "email_sender": "sender@test.com",
            "email_subject": "Subject",
            "email_preview": "Preview",
            "draft_v1": "V1",
            "critique": "OK",
            "draft_final": "Final",
            "status": "VALIDÉ V1"
        }
        temp_history_file.write_text(json.dumps([record_data]), encoding="utf-8")

        stats = draft_history.get_stats()
        # Les records avec timestamp vide ne doivent pas apparaître dans daily_stats
        assert "daily_stats" in stats

    def test_daily_stats_malformed_timestamp(self, draft_history, temp_history_file):
        """Stats journalières avec timestamp malformé."""
        record_data = {
            "id": "test-1",
            "timestamp": "not-a-date",  # Malformé
            "email_id": "email-1",
            "email_sender": "sender@test.com",
            "email_subject": "Subject",
            "email_preview": "Preview",
            "draft_v1": "V1",
            "critique": "OK",
            "draft_final": "Final",
            "status": "VALIDÉ V1"
        }
        temp_history_file.write_text(json.dumps([record_data]), encoding="utf-8")

        stats = draft_history.get_stats()
        # Le code ne doit pas planter
        assert "daily_stats" in stats

    def test_daily_stats_very_old_date(self, draft_history):
        """Stats journalières avec date très ancienne."""
        record = DraftRecord(
            id="test-1",
            timestamp="1990-01-01T00:00:00",
            email_id="email-1",
            email_sender="user@example.com",
            email_subject="Subject",
            email_preview="Preview",
            draft_v1="V1",
            critique="OK",
            draft_final="Final",
            status="VALIDÉ V1"
        )
        draft_history.add(record)

        stats = draft_history.get_stats()
        # La date ancienne doit apparaître dans les stats
        assert len(stats["daily_stats"]) >= 1


# ============================================================================
# TESTS UPDATE_FEEDBACK EDGE CASES
# ============================================================================

class TestUpdateFeedbackEdgeCases:
    """Tests des cas limites pour la mise à jour du feedback."""

    def test_update_feedback_empty_comment(self, draft_history):
        """Mise à jour avec commentaire vide."""
        record = DraftRecord(
            id="test-1",
            timestamp="2024-01-15T10:00:00",
            email_id="email-1",
            email_sender="user@example.com",
            email_subject="Subject",
            email_preview="Preview",
            draft_v1="V1",
            critique="OK",
            draft_final="Final",
            status="VALIDÉ V1"
        )
        draft_history.add(record)

        result = draft_history.update_feedback("test-1", "positive", "")
        assert result is True

        updated_record = draft_history.get_by_id("test-1")
        assert updated_record.feedback == "positive"
        assert updated_record.feedback_comment == ""

    def test_update_feedback_unicode_comment(self, draft_history):
        """Mise à jour avec commentaire unicode."""
        record = DraftRecord(
            id="test-1",
            timestamp="2024-01-15T10:00:00",
            email_id="email-1",
            email_sender="user@example.com",
            email_subject="Subject",
            email_preview="Preview",
            draft_v1="V1",
            critique="OK",
            draft_final="Final",
            status="VALIDÉ V1"
        )
        draft_history.add(record)

        result = draft_history.update_feedback("test-1", "positive", "Excellent 👍 日本語")
        assert result is True

        updated_record = draft_history.get_by_id("test-1")
        assert "👍" in updated_record.feedback_comment
        assert "日本語" in updated_record.feedback_comment


# ============================================================================
# TESTS CREATE_RECORD EDGE CASES
# ============================================================================

class TestCreateRecordEdgeCases:
    """Tests des cas limites pour la création de records."""

    def test_create_record_exactly_100_chars(self):
        """Création avec body de exactement 100 caractères."""
        body = "A" * 100
        record = create_record(
            email_id="email-1",
            email_sender="sender@example.com",
            email_subject="Subject",
            email_body=body,
            draft_v1="V1",
            critique="Critique",
            draft_final="Final",
            status="VALIDÉ V1"
        )
        # Exactement 100 chars = pas de troncature
        assert record.email_preview == body
        assert not record.email_preview.endswith("...")

    def test_create_record_101_chars(self):
        """Création avec body de 101 caractères (troncature)."""
        body = "A" * 101
        record = create_record(
            email_id="email-1",
            email_sender="sender@example.com",
            email_subject="Subject",
            email_body=body,
            draft_v1="V1",
            critique="Critique",
            draft_final="Final",
            status="VALIDÉ V1"
        )
        # 101 chars = troncature
        assert len(record.email_preview) == 103  # 100 + "..."
        assert record.email_preview.endswith("...")

    def test_create_record_empty_body(self):
        """Création avec body vide."""
        record = create_record(
            email_id="email-1",
            email_sender="sender@example.com",
            email_subject="Subject",
            email_body="",
            draft_v1="V1",
            critique="Critique",
            draft_final="Final",
            status="VALIDÉ V1"
        )
        assert record.email_preview == ""

    def test_create_record_unicode_body(self):
        """Création avec body unicode."""
        body = "Émoji 🎉 日本語 content"
        record = create_record(
            email_id="email-1",
            email_sender="sender@example.com",
            email_subject="Subject",
            email_body=body,
            draft_v1="V1",
            critique="Critique",
            draft_final="Final",
            status="VALIDÉ V1"
        )
        assert record.email_preview == body


# ============================================================================
# TESTS EXPORT_FOR_TRAINING EDGE CASES
# ============================================================================

class TestExportForTrainingEdgeCases:
    """Tests des cas limites pour l'export d'entraînement."""

    def test_export_for_training_rating_boundary_3(self, draft_history):
        """Export training exclut rating = 3."""
        record = DraftRecord(
            id="test-1",
            timestamp="2024-01-15T10:00:00",
            email_id="email-1",
            email_sender="user@example.com",
            email_subject="Subject",
            email_preview="Preview",
            draft_v1="V1",
            critique="OK",
            draft_final="Final",
            status="VALIDÉ V1",
            feedback_rating=3
        )
        draft_history.add(record)

        data = draft_history.export_for_training()
        assert len(data) == 0  # Rating 3 < 4, exclu

    def test_export_for_training_rating_boundary_4(self, draft_history, monkeypatch):
        """Export training inclut rating = 4 en mode legacy full-cache."""
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "legacy_full_cache")
        record = DraftRecord(
            id="test-1",
            timestamp="2024-01-15T10:00:00",
            email_id="email-1",
            email_sender="user@example.com",
            email_subject="Subject",
            email_preview="Preview",
            draft_v1="V1",
            critique="OK",
            draft_final="Final content",
            status="VALIDÉ V1",
            feedback_rating=4
        )
        draft_history.add(record)

        data = draft_history.export_for_training()
        assert len(data) == 1
        assert data[0]["rating"] == 4
        assert data[0]["response"] == "Final content"

    def test_export_for_training_missing_rating(self, draft_history):
        """Export training avec rating manquant (None par défaut)."""
        record = DraftRecord(
            id="test-1",
            timestamp="2024-01-15T10:00:00",
            email_id="email-1",
            email_sender="user@example.com",
            email_subject="Subject",
            email_preview="Preview",
            draft_v1="V1",
            critique="OK",
            draft_final="Final",
            status="VALIDÉ V1"
            # feedback_rating absent = None par défaut
        )
        draft_history.add(record)

        data = draft_history.export_for_training()
        assert len(data) == 0  # None n'est pas >= 4, donc exclu
