# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour RecapService — fonctions helper et pures.

Couvre:
- _prev_month(): calcul du mois précédent (changement d'année)
- _month_label(): conversion YYYY-MM en label anglais
- _compute_basic_metrics(): calcul temps économisé pour un mois
- _build_comparison(): détection amélioration/déclin/statut
- _load_best_records() / _save_best_records(): persistance JSON
- get_recap(): intégration complète avec dépendances moquées
"""

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch, mock_open

from app.services.recap_service import (
    _prev_month,
    _month_label,
    _compute_basic_metrics,
    _build_comparison,
    _load_best_records,
    _save_best_records,
    get_recap,
    MONTH_NAMES_EN,
)


class TestPrevMonth:
    """Tests pour _prev_month()."""

    def test_regular_month(self):
        """Mois normal — retourne le mois précédent."""
        assert _prev_month("2026-03") == "2026-02"
        assert _prev_month("2026-06") == "2026-05"

    def test_january_to_december_previous_year(self):
        """Janvier retourne décembre de l'année précédente."""
        assert _prev_month("2026-01") == "2025-12"
        assert _prev_month("2025-01") == "2024-12"

    def test_year_rollover(self):
        """Vérifier le changement d'année pour tous les mois."""
        assert _prev_month("2020-01") == "2019-12"
        assert _prev_month("2099-01") == "2098-12"

    def test_maintains_zero_padding(self):
        """Vérifie que le mois est toujours au format MM (02 pas 2)."""
        assert _prev_month("2026-10") == "2026-09"
        assert _prev_month("2026-02") == "2026-01"

    def test_various_months(self):
        """Teste plusieurs mois pour valider le pattern."""
        test_cases = [
            ("2026-03", "2026-02"),
            ("2026-04", "2026-03"),
            ("2026-12", "2026-11"),
            ("2025-07", "2025-06"),
        ]
        for month, expected in test_cases:
            assert _prev_month(month) == expected


class TestMonthLabel:
    """Tests pour _month_label()."""

    def test_january(self):
        """Janvier → 'JANUARY 2026'."""
        assert _month_label("2026-01") == "JANUARY 2026"

    def test_december(self):
        """Décembre → 'DECEMBER 2026'."""
        assert _month_label("2026-12") == "DECEMBER 2026"

    def test_march(self):
        """Mars → 'MARCH 2026'."""
        assert _month_label("2026-03") == "MARCH 2026"

    def test_all_months(self):
        """Teste tous les mois de l'année."""
        for i in range(1, 13):
            month_str = f"2026-{i:02d}"
            label = _month_label(month_str)
            expected = f"{MONTH_NAMES_EN[i - 1].upper()} 2026"
            assert label == expected

    def test_different_years(self):
        """Teste avec différentes années."""
        assert _month_label("2025-06") == "JUNE 2025"
        assert _month_label("2024-12") == "DECEMBER 2024"
        assert _month_label("2099-01") == "JANUARY 2099"

    def test_format_consistency(self):
        """Vérifie que le format est toujours MONTH YYYY."""
        label = _month_label("2026-05")
        assert label.isupper()
        assert "2026" in label
        assert "MAY" in label


class TestComputeBasicMetrics:
    """Tests pour _compute_basic_metrics()."""

    @patch("app.infrastructure.container.get_container")
    def test_empty_draft_history(self, mock_get_container):
        """Pas de brouillons → time_saved_hours = 0."""
        mock_container = MagicMock()
        mock_draft_history = MagicMock()
        mock_draft_history.get_all.return_value = []
        mock_container.get_draft_history.return_value = mock_draft_history
        mock_get_container.return_value = mock_container

        result = _compute_basic_metrics("2026-03")
        assert result["time_saved_hours"] == 0

    @patch("app.infrastructure.container.get_container")
    def test_counts_drafts_for_month(self, mock_get_container):
        """Compte les brouillons du mois spécifié (account-scoped depuis commit 18aa46fb)."""
        mock_container = MagicMock()
        mock_draft_history = MagicMock()

        # Créer des records mock avec timestamps
        record1 = Mock()
        record1.timestamp = "2026-03-10T08:00:00"
        record1.draft_final = True
        record1.draft_v1 = None

        record2 = Mock()
        record2.timestamp = "2026-03-15T09:00:00"
        record2.draft_final = None
        record2.draft_v1 = "draft content"

        record3 = Mock()
        record3.timestamp = "2026-02-28T10:00:00"  # Mois différent
        record3.draft_final = True
        record3.draft_v1 = None

        # Le refactor d'isolation multi-compte (#18aa46fb) appelle get_all_for_account
        # au lieu de get_all. On mocke les deux pour robustesse.
        mock_draft_history.get_all_for_account.return_value = [record1, record2, record3]
        mock_draft_history.get_all.return_value = [record1, record2, record3]
        mock_container.get_draft_history.return_value = mock_draft_history
        mock_get_container.return_value = mock_container

        result = _compute_basic_metrics("2026-03", account_id=1)
        # 2 drafts * 3 minutes / 60 = 0.1 hours
        assert result["time_saved_hours"] == 0.1

    @patch("app.infrastructure.container.get_container")
    def test_missing_account_id_returns_zero(self, mock_get_container):
        """Sans account_id, retourne 0 (isolation multi-compte stricte)."""
        result = _compute_basic_metrics("2026-03", account_id=None)
        assert result["time_saved_hours"] == 0
        # Le container ne devrait même pas être appelé
        mock_get_container.assert_not_called()

    @patch("app.infrastructure.container.get_container")
    def test_handles_missing_container(self, mock_get_container):
        """Gère l'absence de conteneur (exception)."""
        mock_get_container.side_effect = Exception("Container error")

        result = _compute_basic_metrics("2026-03")
        assert result["time_saved_hours"] == 0

    @patch("app.infrastructure.container.get_container")
    def test_calculates_hours_correctly(self, mock_get_container):
        """Calcule correctement les heures économisées (account-scoped)."""
        mock_container = MagicMock()
        mock_draft_history = MagicMock()

        # 10 drafts = 30 minutes = 0.5 heures
        records = []
        for i in range(10):
            record = Mock()
            record.timestamp = f"2026-03-{(i % 28) + 1:02d}T08:00:00"
            record.draft_final = True
            record.draft_v1 = None
            records.append(record)

        mock_draft_history.get_all_for_account.return_value = records
        mock_draft_history.get_all.return_value = records
        mock_container.get_draft_history.return_value = mock_draft_history
        mock_get_container.return_value = mock_container

        result = _compute_basic_metrics("2026-03", account_id=1)
        assert result["time_saved_hours"] == 0.5


class TestBuildComparison:
    """Tests pour _build_comparison()."""

    def test_improving_month(self):
        """Détecte amélioration (delta > 0.5)."""
        result = _build_comparison(
            current_hours=5.0,
            prev_hours=2.0,
            prev_month="2026-02",
            current_month="2026-03"
        )
        assert result["type"] == "improving"
        assert result["delta_hours"] == 3.0
        assert "accélérez" in result["message"].lower()
        assert "3.0 h" in result["message"]

    def test_declining_month(self):
        """Détecte déclin (delta < -0.5)."""
        result = _build_comparison(
            current_hours=1.0,
            prev_hours=4.0,
            prev_month="2026-02",
            current_month="2026-03"
        )
        assert result["type"] == "declining"
        assert result["delta_hours"] == -3.0
        assert "moins" in result["message"].lower()
        assert "3.0 h" in result["message"]

    def test_same_month(self):
        """Détecte même niveau (delta entre -0.5 et 0.5)."""
        result = _build_comparison(
            current_hours=3.0,
            prev_hours=3.1,
            prev_month="2026-02",
            current_month="2026-03"
        )
        assert result["type"] == "same"
        assert abs(result["delta_hours"]) < 0.5
        assert "stable" in result["message"].lower()

    @patch("app.services.recap_tracker.get_recap_tracker")
    def test_first_month_no_history(self, mock_get_tracker):
        """Détecte premier mois (pas d'historique)."""
        mock_tracker = MagicMock()
        mock_tracker.get_all_data.return_value = {
            "active_dates": []  # Vide
        }
        mock_get_tracker.return_value = mock_tracker

        result = _build_comparison(
            current_hours=2.0,
            prev_hours=0,
            prev_month="2026-02",
            current_month="2026-03"
        )
        assert result["type"] == "first_month"
        assert result["delta_hours"] == 0
        assert "référence" in result["message"].lower()

    @patch("app.services.recap_tracker.get_recap_tracker")
    def test_first_month_with_history(self, mock_get_tracker):
        """Pas premier mois si historique existe."""
        mock_tracker = MagicMock()
        mock_tracker.get_all_data.return_value = {
            "active_dates": ["2026-01-15"]  # Des données antérieures
        }
        mock_get_tracker.return_value = mock_tracker

        result = _build_comparison(
            current_hours=2.0,
            prev_hours=0,
            prev_month="2026-02",
            current_month="2026-03"
        )
        # Pas premier mois puisqu'il y a de l'historique
        assert result["type"] != "first_month"

    def test_zero_delta(self):
        """Teste delta exactement zéro."""
        result = _build_comparison(
            current_hours=3.0,
            prev_hours=3.0,
            prev_month="2026-02",
            current_month="2026-03"
        )
        assert result["type"] == "same"
        assert result["delta_hours"] == 0

    def test_empty_when_current_and_previous_are_zero(self):
        """Zéro donnée sur deux mois n'est pas une comparaison stable."""
        result = _build_comparison(
            current_hours=0,
            prev_hours=0,
            prev_month="2026-02",
            current_month="2026-03"
        )
        assert result["type"] == "empty"


class TestLoadBestRecords:
    """Tests pour _load_best_records()."""

    @patch("app.services.recap_service._BEST_RECORDS_FILE")
    def test_loads_existing_records(self, mock_file):
        """Charge les records existants depuis le fichier."""
        test_data = {
            "inbox_zero_days": 15,
            "avg_reply_time_minutes": 5.0,
        }
        mock_file.exists.return_value = True
        mock_file.open = mock_open(read_data=json.dumps(test_data))

        with patch("builtins.open", mock_open(read_data=json.dumps(test_data))):
            result = _load_best_records()
            assert result == test_data

    @patch("app.services.recap_service._BEST_RECORDS_FILE")
    def test_returns_empty_when_no_file(self, mock_file):
        """Retourne {} si le fichier n'existe pas."""
        mock_file.exists.return_value = False

        result = _load_best_records()
        assert result == {}

    @patch("app.services.recap_service._BEST_RECORDS_FILE")
    def test_handles_corrupted_json(self, mock_file):
        """Gère le JSON corrompu et retourne {}."""
        mock_file.exists.return_value = True
        bad_json = "not valid json{{{"
        with patch("builtins.open", mock_open(read_data=bad_json)):
            result = _load_best_records()
            assert result == {}

    @patch("app.services.recap_service._BEST_RECORDS_FILE")
    def test_handles_io_error(self, mock_file):
        """Gère les erreurs d'accès fichier."""
        mock_file.exists.return_value = True
        with patch("builtins.open", side_effect=IOError("Access denied")):
            result = _load_best_records()
            assert result == {}


class TestSaveBestRecords:
    """Tests pour _save_best_records()."""

    @patch("app.services.recap_service._BEST_RECORDS_FILE")
    def test_saves_records_to_file(self, mock_file):
        """Sauvegarde les records en JSON."""
        mock_file.parent.mkdir = MagicMock()
        test_data = {
            "inbox_zero_days": 20,
            "avg_reply_time_minutes": 4.5,
        }

        with patch("builtins.open", mock_open()):
            with patch.object(Path, "parent", create=True):
                _save_best_records(test_data)
                # Vérifier que open() a été appelé avec 'w'
                # (on vérifie simplement que la fonction s'exécute sans erreur)

    @patch("app.services.recap_service._BEST_RECORDS_FILE")
    def test_creates_parent_directory(self, mock_file):
        """Crée le répertoire parent si nécessaire."""
        mock_file.parent = MagicMock()
        test_data = {"key": "value"}

        with patch("builtins.open", mock_open()):
            _save_best_records(test_data)
            mock_file.parent.mkdir.assert_called_once_with(parents=True, exist_ok=True)

    @patch("app.services.recap_service._BEST_RECORDS_FILE")
    def test_handles_io_error_silently(self, mock_file):
        """Gère silencieusement les erreurs d'écriture."""
        mock_file.parent = MagicMock()
        mock_file.parent.mkdir.side_effect = IOError("Permission denied")

        with patch("app.services.recap_service.logger"):
            # Ne doit pas lever d'exception
            _save_best_records({"key": "value"})


class TestGetRecapIntegration:
    """Tests d'intégration pour get_recap()."""

    @patch("app.services.recap_tracker.get_recap_tracker")
    @patch("app.infrastructure.container.get_container")
    @patch("app.services.recap_service._load_best_records")
    @patch("app.services.recap_service._save_best_records")
    def test_get_recap_full_flow(
        self,
        mock_save_best,
        mock_load_best,
        mock_get_container,
        mock_get_tracker
    ):
        """Teste le flux complet de get_recap()."""
        # Setup tracker
        mock_tracker = MagicMock()
        mock_tracker.get_month_data.return_value = {
            "reply_times": [10.0, 15.0],
            "inbox_zero_dates": ["2026-03-15", "2026-03-20"],
            "active_dates": ["2026-03-15", "2026-03-16", "2026-03-20"],
        }
        mock_tracker.get_all_data.return_value = {
            "active_dates": ["2026-03-15"]  # A history
        }
        mock_get_tracker.return_value = mock_tracker

        # Setup draft history
        mock_container = MagicMock()
        mock_draft_history = MagicMock()

        record1 = Mock()
        record1.timestamp = "2026-03-10T08:00:00"
        record1.draft_final = True
        record1.draft_v1 = None

        record2 = Mock()
        record2.timestamp = "2026-03-15T09:00:00"
        record2.draft_final = None
        record2.draft_v1 = "draft"

        mock_draft_history.get_all_for_account.return_value = [record1, record2]
        mock_draft_history.get_all.return_value = [record1, record2]
        mock_container.get_draft_history.return_value = mock_draft_history
        mock_get_container.return_value = mock_container

        # Setup best records
        mock_load_best.return_value = {}

        # Call get_recap (post-18aa46fb: account_id required for draft counting)
        result = get_recap("2026-03", account_id=1)

        # Assertions
        assert result["month"] == "2026-03"
        assert result["month_label"] == "MARCH 2026"
        assert result["emails_processed"] == 2
        assert result["drafts_generated"] == 2
        assert result["inbox_zero_days"] == 2
        assert result["days_active"] == 3
        assert result["avg_reply_time_minutes"] == 12.5
        assert result["fastest_reply_minutes"] == 10.0
        assert result["ai_assisted_percent"] == 100.0
        assert "comparison" in result
        assert "best" in result
        assert "feature_breakdown" in result

    @patch("app.services.recap_tracker.get_recap_tracker")
    @patch("app.infrastructure.container.get_container")
    @patch("app.services.recap_service._load_best_records")
    @patch("app.services.recap_service._save_best_records")
    def test_get_recap_defaults_to_previous_month(
        self,
        mock_save_best,
        mock_load_best,
        mock_get_container,
        mock_get_tracker
    ):
        """Teste que get_recap() par défaut utilise le mois précédent."""
        mock_tracker = MagicMock()
        mock_tracker.get_month_data.return_value = {
            "reply_times": [],
            "inbox_zero_dates": [],
            "active_dates": [],
        }
        mock_tracker.get_all_data.return_value = {"active_dates": []}
        mock_get_tracker.return_value = mock_tracker

        mock_container = MagicMock()
        mock_draft_history = MagicMock()
        mock_draft_history.get_all.return_value = []
        mock_container.get_draft_history.return_value = mock_draft_history
        mock_get_container.return_value = mock_container

        mock_load_best.return_value = {}

        with patch("app.services.recap_service.date") as mock_date:
            mock_date.today.return_value = date(2026, 3, 24)

            result = get_recap()

            # Devrait utiliser février 2026 (mois précédent de mars)
            expected_month = "2026-02"
            assert result["month"] == expected_month

    @patch("app.services.recap_tracker.get_recap_tracker")
    @patch("app.infrastructure.container.get_container")
    @patch("app.services.recap_service._load_best_records")
    @patch("app.services.recap_service._save_best_records")
    def test_get_recap_updates_best_records(
        self,
        mock_save_best,
        mock_load_best,
        mock_get_container,
        mock_get_tracker
    ):
        """Teste la mise à jour des meilleurs records."""
        mock_tracker = MagicMock()
        mock_tracker.get_month_data.return_value = {
            "reply_times": [5.0],
            "inbox_zero_dates": ["2026-03-15"],
            "active_dates": ["2026-03-15"],
        }
        mock_tracker.get_all_data.return_value = {"active_dates": []}
        mock_get_tracker.return_value = mock_tracker

        mock_container = MagicMock()
        mock_draft_history = MagicMock()
        mock_draft_history.get_all.return_value = []
        mock_container.get_draft_history.return_value = mock_draft_history
        mock_get_container.return_value = mock_container

        # Meilleurs records vides initialement
        mock_load_best.return_value = {}

        get_recap("2026-03")

        # _save_best_records doit être appelé
        assert mock_save_best.called

    @patch("app.services.recap_tracker.get_recap_tracker")
    @patch("app.infrastructure.container.get_container")
    @patch("app.services.recap_service._load_best_records")
    @patch("app.services.recap_service._save_best_records")
    def test_get_recap_handles_missing_tracker_activity(
        self,
        mock_save_best,
        mock_load_best,
        mock_get_container,
        mock_get_tracker
    ):
        """Gère l'absence de DraftQualityTracker avec gracieux fallback."""
        mock_tracker = MagicMock()
        mock_tracker.get_month_data.return_value = {
            "reply_times": [],
            "inbox_zero_dates": [],
            "active_dates": [],
        }
        mock_tracker.get_all_data.return_value = {"active_dates": []}
        mock_get_tracker.return_value = mock_tracker

        mock_container = MagicMock()
        mock_draft_history = MagicMock()
        mock_draft_history.get_all.return_value = []
        mock_container.get_draft_history.return_value = mock_container
        mock_get_container.return_value = mock_container

        mock_load_best.return_value = {}

        with patch("app.draft_quality_tracker.get_tracker", side_effect=Exception("Tracker unavailable")):
            # Ne doit pas lever d'exception
            result = get_recap("2026-03")
            assert result is not None
            assert "feature_breakdown" in result

    @patch("app.services.recap_tracker.get_recap_tracker")
    @patch("app.infrastructure.container.get_container")
    @patch("app.services.recap_service._load_best_records")
    @patch("app.services.recap_service._save_best_records")
    def test_get_recap_uses_scoped_tracker_activity_when_draft_history_empty(
        self,
        mock_save_best,
        mock_load_best,
        mock_get_container,
        mock_get_tracker
    ):
        """Un brouillon IA tracké doit apparaître même sans draft_history."""
        mock_tracker = MagicMock()
        mock_tracker.get_month_data.return_value = {
            "reply_times": [],
            "inbox_zero_dates": [],
            "active_dates": ["2026-03-15"],
        }
        mock_tracker.get_all_data.return_value = {"active_dates": []}
        mock_get_tracker.return_value = mock_tracker

        mock_container = MagicMock()
        mock_draft_history = MagicMock()
        mock_draft_history.get_all_for_account.return_value = []
        mock_container.get_draft_history.return_value = mock_draft_history
        mock_get_container.return_value = mock_container
        mock_load_best.return_value = {}

        empty_activity = {
            "drafts": 0,
            "tiers": {"simple": 0, "standard": 0, "complex": 0, "followup": 0},
            "features": {"compose_ai": 0, "refine_ai": 0, "auto_reply": 0, "attachment_reminder": 0, "deep_work_emails": 0, "shortcut": 0, "auto_label": 0, "auto_archive_action": 0},
            "archives": 0,
            "labels": 0,
            "time_saved_min": 0,
            "time_breakdown": {"drafts": 0, "archive": 0, "label": 0, "followup": 0, "attachment_reminder": 0, "deep_work": 0, "shortcuts": 0},
        }
        current_activity = {
            **empty_activity,
            "features": {**empty_activity["features"], "compose_ai": 2},
            "time_saved_min": 10,
            "time_breakdown": {**empty_activity["time_breakdown"], "drafts": 10},
        }
        mock_quality = MagicMock()
        mock_quality.get_month_activity.side_effect = (
            lambda month, account_id=None: current_activity if month == "2026-03" else empty_activity
        )

        with patch("app.draft_quality_tracker.get_tracker", return_value=mock_quality):
            result = get_recap("2026-03", account_id=1)

        assert result["drafts_generated"] == 2
        assert result["emails_processed"] == 2
        assert result["time_saved_hours"] == 0.2
        assert result["ai_assisted_percent"] == 100.0
        assert result["data_quality"] == "partial"
