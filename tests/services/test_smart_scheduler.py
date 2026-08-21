# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour le Smart Meeting Scheduler.

Couvre:
- find_available_slots() avec différentes configurations
- _snap_to_half_hour() utilitaire
- _parse_dt() parsing ISO
- Gestion des weekends, heures de travail, pause déjeuner
- Fusion de blocs occupés
- Extra busy blocks
"""

from datetime import datetime
from app.services.smart_scheduler import (
    find_available_slots,
    _snap_to_half_hour,
    _parse_dt,
)


class TestSnapToHalfHour:
    """Tests pour _snap_to_half_hour()."""

    def test_exact_hour(self):
        dt = datetime(2026, 3, 24, 10, 0, 0)
        assert _snap_to_half_hour(dt) == datetime(2026, 3, 24, 10, 0, 0)

    def test_exact_half_hour(self):
        dt = datetime(2026, 3, 24, 10, 30, 0)
        assert _snap_to_half_hour(dt) == datetime(2026, 3, 24, 10, 30, 0)

    def test_before_half_hour(self):
        dt = datetime(2026, 3, 24, 10, 15, 0)
        assert _snap_to_half_hour(dt) == datetime(2026, 3, 24, 10, 30, 0)

    def test_after_half_hour(self):
        dt = datetime(2026, 3, 24, 10, 45, 0)
        assert _snap_to_half_hour(dt) == datetime(2026, 3, 24, 11, 0, 0)

    def test_one_minute_past_hour(self):
        dt = datetime(2026, 3, 24, 10, 1, 0)
        assert _snap_to_half_hour(dt) == datetime(2026, 3, 24, 10, 30, 0)

    def test_removes_seconds_and_microseconds(self):
        dt = datetime(2026, 3, 24, 10, 0, 45, 123456)
        result = _snap_to_half_hour(dt)
        assert result.second == 0
        assert result.microsecond == 0

    def test_59_minutes_rolls_to_next_hour(self):
        dt = datetime(2026, 3, 24, 10, 59, 0)
        assert _snap_to_half_hour(dt) == datetime(2026, 3, 24, 11, 0, 0)


class TestParseDt:
    """Tests pour _parse_dt()."""

    def test_parse_iso_without_z(self):
        result = _parse_dt("2026-03-24T10:00:00")
        assert result == datetime(2026, 3, 24, 10, 0, 0)

    def test_parse_iso_with_z(self):
        result = _parse_dt("2026-03-24T10:00:00Z")
        assert result.hour == 10
        assert result.tzinfo is not None

    def test_parse_iso_with_offset(self):
        result = _parse_dt("2026-03-24T10:00:00+02:00")
        assert result.hour == 10


class TestFindAvailableSlots:
    """Tests pour find_available_slots()."""

    def test_empty_freebusy_returns_slots(self):
        """Sans aucun bloc occupé, on doit trouver des créneaux."""
        # Lundi 24 mars 2026 (weekday 1 = mardi en fait, vérifions)
        start = datetime(2026, 3, 24, 8, 0, 0)  # Mardi
        end = datetime(2026, 3, 24, 17, 0, 0)
        freebusy = {"calendars": {}}

        slots = find_available_slots(
            freebusy, start, end, duration_minutes=60,
            work_hours_only=True
        )
        assert len(slots) > 0

    def test_respects_max_slots(self):
        start = datetime(2026, 3, 24, 8, 0, 0)
        end = datetime(2026, 3, 27, 17, 0, 0)
        freebusy = {"calendars": {}}

        slots = find_available_slots(
            freebusy, start, end, duration_minutes=30, max_slots=3,
            work_hours_only=True
        )
        assert len(slots) <= 3

    def test_no_slots_when_fully_booked(self):
        """Un seul bloc occupé couvrant toute la journée ne donne aucun créneau."""
        start = datetime(2026, 3, 24, 8, 0, 0)
        end = datetime(2026, 3, 24, 17, 0, 0)
        freebusy = {
            "calendars": {
                "user@example.com": [
                    {"start": "2026-03-24T08:00:00", "end": "2026-03-24T17:00:00"}
                ]
            }
        }

        slots = find_available_slots(
            freebusy, start, end, duration_minutes=60,
            work_hours_only=True
        )
        assert len(slots) == 0

    def test_finds_gap_between_meetings(self):
        """Trouve un créneau libre entre deux réunions."""
        start = datetime(2026, 3, 24, 8, 0, 0)
        end = datetime(2026, 3, 24, 17, 0, 0)
        freebusy = {
            "calendars": {
                "user@example.com": [
                    {"start": "2026-03-24T08:00:00", "end": "2026-03-24T10:00:00"},
                    {"start": "2026-03-24T11:00:00", "end": "2026-03-24T17:00:00"},
                ]
            }
        }

        slots = find_available_slots(
            freebusy, start, end, duration_minutes=60,
            work_hours_only=True
        )
        assert len(slots) >= 1
        # Le créneau doit être entre 10:00 et 11:00
        first_slot_start = _parse_dt(slots[0]["start"])
        assert first_slot_start.hour == 10

    def test_merges_overlapping_busy_blocks(self):
        """Les blocs qui se chevauchent sont fusionnés."""
        start = datetime(2026, 3, 24, 8, 0, 0)
        end = datetime(2026, 3, 24, 17, 0, 0)
        freebusy = {
            "calendars": {
                "alice@example.com": [
                    {"start": "2026-03-24T09:00:00", "end": "2026-03-24T10:30:00"}
                ],
                "bob@example.com": [
                    {"start": "2026-03-24T10:00:00", "end": "2026-03-24T11:00:00"}
                ],
            }
        }

        slots = find_available_slots(
            freebusy, start, end, duration_minutes=30,
            work_hours_only=True
        )
        # Le bloc fusionné est 09:00-11:00, donc le premier créneau est 08:00-08:30
        assert len(slots) > 0
        first_start = _parse_dt(slots[0]["start"])
        assert first_start.hour == 8

    def test_duration_30_minutes(self):
        """Recherche de créneaux de 30 minutes."""
        start = datetime(2026, 3, 24, 8, 0, 0)
        end = datetime(2026, 3, 24, 9, 0, 0)
        freebusy = {"calendars": {}}

        slots = find_available_slots(
            freebusy, start, end, duration_minutes=30,
            work_hours_only=True
        )
        assert len(slots) == 2  # 08:00-08:30 et 08:30-09:00

    def test_extra_busy_blocks_are_considered(self):
        """Les blocs extra busy sont pris en compte."""
        start = datetime(2026, 3, 24, 8, 0, 0)
        end = datetime(2026, 3, 24, 12, 0, 0)
        freebusy = {"calendars": {}}
        extra_busy = [
            {"start": "2026-03-24T08:00:00", "end": "2026-03-24T10:00:00"}
        ]

        slots = find_available_slots(
            freebusy, start, end, duration_minutes=60,
            work_hours_only=True, extra_busy=extra_busy,
            lunch_start=-1,  # Pas de pause déjeuner
        )
        assert len(slots) >= 1
        first_start = _parse_dt(slots[0]["start"])
        assert first_start.hour >= 10

    def test_work_hours_only_false(self):
        """Sans contrainte d'heures de travail, on peut trouver des créneaux le soir."""
        start = datetime(2026, 3, 24, 18, 0, 0)
        end = datetime(2026, 3, 24, 22, 0, 0)
        freebusy = {"calendars": {}}

        slots = find_available_slots(
            freebusy, start, end, duration_minutes=60,
            work_hours_only=False
        )
        assert len(slots) > 0

    def test_skips_invalid_busy_blocks(self):
        """Les blocs busy invalides sont ignorés sans erreur."""
        start = datetime(2026, 3, 24, 8, 0, 0)
        end = datetime(2026, 3, 24, 17, 0, 0)
        freebusy = {
            "calendars": {
                "user@example.com": [
                    {"start": "invalid-date", "end": "2026-03-24T10:00:00"},
                    {"start": "2026-03-24T14:00:00", "end": "2026-03-24T15:00:00"},
                ]
            }
        }
        # Ne doit pas lever d'exception
        slots = find_available_slots(
            freebusy, start, end, duration_minutes=60,
            work_hours_only=True
        )
        assert isinstance(slots, list)

    def test_slot_format(self):
        """Chaque créneau a les clés start et end en format ISO."""
        start = datetime(2026, 3, 24, 8, 0, 0)
        end = datetime(2026, 3, 24, 17, 0, 0)
        freebusy = {"calendars": {}}

        slots = find_available_slots(
            freebusy, start, end, duration_minutes=60,
            work_hours_only=True
        )
        for slot in slots:
            assert "start" in slot
            assert "end" in slot
            # Vérifier que les dates sont parseable
            _parse_dt(slot["start"])
            _parse_dt(slot["end"])
