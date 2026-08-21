# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour RecapTracker.

Couvre:
- Chargement/sauvegarde depuis fichier
- record_reply_time, record_inbox_zero, record_activity
- get_month_data, get_all_data
- Gestion des erreurs (fichier corrompu, IOError)
"""

import json
from datetime import datetime, date, timezone
import pytest
from app.services.recap_tracker import RecapTracker


@pytest.fixture
def tracker(tmp_path):
    """Crée un RecapTracker avec un fichier temporaire."""
    tracking_file = tmp_path / "recap" / "daily_tracking.json"
    return RecapTracker(tracking_file=tracking_file)


class TestRecapTrackerInit:
    """Tests pour l'initialisation."""

    def test_creates_parent_directory(self, tmp_path):
        tracking_file = tmp_path / "sub" / "dir" / "tracking.json"
        RecapTracker(tracking_file=tracking_file)
        assert tracking_file.parent.exists()

    def test_loads_empty_data_when_no_file(self, tracker):
        data = tracker.get_all_data()
        assert data == {
            "reply_times_minutes": {},
            "inbox_zero_dates": [],
            "active_dates": [],
        }

    def test_loads_existing_data(self, tmp_path):
        tracking_file = tmp_path / "tracking.json"
        tracking_file.parent.mkdir(parents=True, exist_ok=True)
        existing = {
            "reply_times_minutes": {"2026-03": [5.0, 10.0]},
            "inbox_zero_dates": ["2026-03-20"],
            "active_dates": ["2026-03-20", "2026-03-21"],
        }
        tracking_file.write_text(json.dumps(existing))
        tracker = RecapTracker(tracking_file=tracking_file)
        data = tracker.get_all_data()
        assert data["reply_times_minutes"]["2026-03"] == [5.0, 10.0]
        assert "2026-03-20" in data["inbox_zero_dates"]

    def test_handles_corrupted_file(self, tmp_path):
        tracking_file = tmp_path / "tracking.json"
        tracking_file.parent.mkdir(parents=True, exist_ok=True)
        tracking_file.write_text("not valid json{{{")
        tracker = RecapTracker(tracking_file=tracking_file)
        data = tracker.get_all_data()
        assert data == {
            "reply_times_minutes": {},
            "inbox_zero_dates": [],
            "active_dates": [],
        }


class TestRecapTrackerRecordReplyTime:
    """Tests pour record_reply_time()."""

    def test_records_reply_time(self, tracker):
        received = "2026-03-24T08:00:00+00:00"
        validated = datetime(2026, 3, 24, 8, 30, 0, tzinfo=timezone.utc)
        tracker.record_reply_time(received, validated_at=validated)

        month_key = date.today().strftime("%Y-%m")
        data = tracker.get_all_data()
        assert month_key in data["reply_times_minutes"]
        assert len(data["reply_times_minutes"][month_key]) == 1
        assert data["reply_times_minutes"][month_key][0] == 30.0

    def test_records_multiple_reply_times(self, tracker):
        r1 = "2026-03-24T08:00:00+00:00"
        v1 = datetime(2026, 3, 24, 8, 10, 0, tzinfo=timezone.utc)
        r2 = "2026-03-24T09:00:00+00:00"
        v2 = datetime(2026, 3, 24, 9, 45, 0, tzinfo=timezone.utc)

        tracker.record_reply_time(r1, validated_at=v1)
        tracker.record_reply_time(r2, validated_at=v2)

        month_key = date.today().strftime("%Y-%m")
        times = tracker.get_all_data()["reply_times_minutes"][month_key]
        assert len(times) == 2
        assert times[0] == 10.0
        assert times[1] == 45.0

    def test_ignores_empty_received_at(self, tracker):
        tracker.record_reply_time("")
        assert tracker.get_all_data()["reply_times_minutes"] == {}

    def test_handles_z_suffix(self, tracker):
        received = "2026-03-24T08:00:00Z"
        validated = datetime(2026, 3, 24, 8, 5, 0, tzinfo=timezone.utc)
        tracker.record_reply_time(received, validated_at=validated)
        month_key = date.today().strftime("%Y-%m")
        times = tracker.get_all_data()["reply_times_minutes"].get(month_key, [])
        assert len(times) == 1
        assert times[0] == 5.0

    def test_saves_to_file(self, tracker):
        received = "2026-03-24T08:00:00+00:00"
        validated = datetime(2026, 3, 24, 8, 15, 0, tzinfo=timezone.utc)
        tracker.record_reply_time(received, validated_at=validated)
        # Vérifier que le fichier existe et contient les données
        assert tracker._file.exists()
        saved = json.loads(tracker._file.read_text())
        assert "reply_times_minutes" in saved


class TestRecapTrackerRecordInboxZero:
    """Tests pour record_inbox_zero()."""

    def test_records_inbox_zero(self, tracker):
        tracker.record_inbox_zero()
        data = tracker.get_all_data()
        today = date.today().isoformat()
        assert today in data["inbox_zero_dates"]

    def test_does_not_duplicate_same_day(self, tracker):
        tracker.record_inbox_zero()
        tracker.record_inbox_zero()
        data = tracker.get_all_data()
        today = date.today().isoformat()
        assert data["inbox_zero_dates"].count(today) == 1


class TestRecapTrackerRecordActivity:
    """Tests pour record_activity()."""

    def test_records_activity(self, tracker):
        tracker.record_activity()
        data = tracker.get_all_data()
        today = date.today().isoformat()
        assert today in data["active_dates"]

    def test_does_not_duplicate_same_day(self, tracker):
        tracker.record_activity()
        tracker.record_activity()
        data = tracker.get_all_data()
        today = date.today().isoformat()
        assert data["active_dates"].count(today) == 1


class TestRecapTrackerGetMonthData:
    """Tests pour get_month_data()."""

    def test_get_month_data_empty(self, tracker):
        data = tracker.get_month_data("2026-03")
        assert data == {
            "reply_times": [],
            "inbox_zero_dates": [],
            "active_dates": [],
        }

    def test_get_month_data_filters_by_month(self, tmp_path):
        tracking_file = tmp_path / "tracking.json"
        tracking_file.parent.mkdir(parents=True, exist_ok=True)
        existing = {
            "reply_times_minutes": {
                "2026-02": [5.0],
                "2026-03": [10.0, 15.0],
            },
            "inbox_zero_dates": ["2026-02-15", "2026-03-01", "2026-03-10"],
            "active_dates": ["2026-02-10", "2026-03-01"],
        }
        tracking_file.write_text(json.dumps(existing))
        tracker = RecapTracker(tracking_file=tracking_file)

        data = tracker.get_month_data("2026-03")
        assert data["reply_times"] == [10.0, 15.0]
        assert data["inbox_zero_dates"] == ["2026-03-01", "2026-03-10"]
        assert data["active_dates"] == ["2026-03-01"]


class TestRecapTrackerGetAllData:
    """Tests pour get_all_data()."""

    def test_returns_copy_of_data(self, tracker):
        tracker.record_activity()
        data1 = tracker.get_all_data()
        data2 = tracker.get_all_data()
        # Les deux appels retournent des dicts séparés
        assert data1 is not data2
