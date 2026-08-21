# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour l'entité CalendarEvent.

Couvre:
- Création avec données valides
- Validations (id vide, titre vide, end_time < start_time)
- Propriété duration_minutes
- Propriété is_followup
- Sérialisation to_dict()
- Désérialisation from_dict() avec parsing datetime et suffixe Z
- Valeurs d'énumération (status, type)
- Valeurs par défaut
"""

from datetime import datetime
import pytest
from app.domain.entities.calendar_event import (
    CalendarEvent,
    CalendarEventStatus,
    CalendarEventType,
)


class TestCalendarEventCreation:
    """Tests pour la création d'événements calendrier."""

    def test_create_with_valid_data(self):
        """Test la création avec des données valides."""
        start = datetime(2026, 3, 24, 10, 0, 0)
        end = datetime(2026, 3, 24, 11, 0, 0)

        event = CalendarEvent(
            id="evt_123",
            title="Team Meeting",
            start_time=start,
            end_time=end,
        )

        assert event.id == "evt_123"
        assert event.title == "Team Meeting"
        assert event.start_time == start
        assert event.end_time == end

    def test_create_with_all_fields(self):
        """Test la création avec tous les champs."""
        start = datetime(2026, 3, 24, 10, 0, 0)
        end = datetime(2026, 3, 24, 11, 30, 0)
        created_at = datetime(2026, 3, 20, 14, 30, 0)
        updated_at = datetime(2026, 3, 23, 15, 45, 0)

        event = CalendarEvent(
            id="evt_456",
            title="Project Planning",
            description="Q2 roadmap discussion",
            start_time=start,
            end_time=end,
            all_day=False,
            location="Conference Room A",
            attendees=["alice@example.com", "bob@example.com"],
            status=CalendarEventStatus.TENTATIVE,
            event_type=CalendarEventType.USER_EVENT,
            provider="gmail",
            provider_event_id="provider_789",
            calendar_id="work@example.com",
            created_at=created_at,
            updated_at=updated_at,
            email_id="email_999",
            recurrence="RRULE:FREQ=WEEKLY;BYDAY=TU",
            reminders=[15, 30, 60],
            color="#FF6B6B",
            html_link="https://calendar.google.com/event",
        )

        assert event.id == "evt_456"
        assert event.title == "Project Planning"
        assert event.description == "Q2 roadmap discussion"
        assert event.location == "Conference Room A"
        assert event.attendees == ["alice@example.com", "bob@example.com"]
        assert event.status == CalendarEventStatus.TENTATIVE
        assert event.event_type == CalendarEventType.USER_EVENT
        assert event.provider == "gmail"
        assert event.provider_event_id == "provider_789"
        assert event.calendar_id == "work@example.com"
        assert event.created_at == created_at
        assert event.updated_at == updated_at
        assert event.email_id == "email_999"
        assert event.recurrence == "RRULE:FREQ=WEEKLY;BYDAY=TU"
        assert event.reminders == [15, 30, 60]
        assert event.color == "#FF6B6B"
        assert event.html_link == "https://calendar.google.com/event"


class TestCalendarEventValidation:
    """Tests pour la validation des événements calendrier."""

    def test_validation_error_empty_id(self):
        """Test que l'id vide lève une ValueError."""
        start = datetime(2026, 3, 24, 10, 0, 0)
        end = datetime(2026, 3, 24, 11, 0, 0)

        with pytest.raises(ValueError, match="CalendarEvent id cannot be empty"):
            CalendarEvent(
                id="",
                title="Meeting",
                start_time=start,
                end_time=end,
            )

    def test_validation_error_empty_title(self):
        """Test que le titre vide lève une ValueError."""
        start = datetime(2026, 3, 24, 10, 0, 0)
        end = datetime(2026, 3, 24, 11, 0, 0)

        with pytest.raises(ValueError, match="CalendarEvent title cannot be empty"):
            CalendarEvent(
                id="evt_123",
                title="",
                start_time=start,
                end_time=end,
            )

    def test_validation_error_end_before_start(self):
        """Test que end_time < start_time lève une ValueError."""
        start = datetime(2026, 3, 24, 11, 0, 0)
        end = datetime(2026, 3, 24, 10, 0, 0)

        with pytest.raises(ValueError, match="end_time cannot be before start_time"):
            CalendarEvent(
                id="evt_123",
                title="Meeting",
                start_time=start,
                end_time=end,
            )

    def test_validation_ok_same_start_end(self):
        """Test que start_time == end_time est valide."""
        time = datetime(2026, 3, 24, 10, 0, 0)

        event = CalendarEvent(
            id="evt_123",
            title="Instantaneous Event",
            start_time=time,
            end_time=time,
        )

        assert event.start_time == time
        assert event.end_time == time


class TestCalendarEventDurationProperty:
    """Tests pour la propriété duration_minutes."""

    def test_duration_minutes_one_hour(self):
        """Test le calcul de durée pour 1 heure."""
        start = datetime(2026, 3, 24, 10, 0, 0)
        end = datetime(2026, 3, 24, 11, 0, 0)

        event = CalendarEvent(
            id="evt_123",
            title="Meeting",
            start_time=start,
            end_time=end,
        )

        assert event.duration_minutes == 60

    def test_duration_minutes_half_hour(self):
        """Test le calcul de durée pour 30 minutes."""
        start = datetime(2026, 3, 24, 10, 0, 0)
        end = datetime(2026, 3, 24, 10, 30, 0)

        event = CalendarEvent(
            id="evt_123",
            title="Quick Sync",
            start_time=start,
            end_time=end,
        )

        assert event.duration_minutes == 30

    def test_duration_minutes_multiple_hours(self):
        """Test le calcul de durée pour plusieurs heures."""
        start = datetime(2026, 3, 24, 9, 0, 0)
        end = datetime(2026, 3, 24, 12, 45, 0)

        event = CalendarEvent(
            id="evt_123",
            title="Workshop",
            start_time=start,
            end_time=end,
        )

        assert event.duration_minutes == 225  # 3 heures 45 minutes

    def test_duration_minutes_zero(self):
        """Test le calcul de durée pour 0 minutes."""
        time = datetime(2026, 3, 24, 10, 0, 0)

        event = CalendarEvent(
            id="evt_123",
            title="Instant Event",
            start_time=time,
            end_time=time,
        )

        assert event.duration_minutes == 0

    def test_duration_minutes_with_seconds(self):
        """Test le calcul de durée avec des secondes (arrondi)."""
        start = datetime(2026, 3, 24, 10, 0, 0)
        end = datetime(2026, 3, 24, 10, 1, 45)  # 1 minute 45 secondes

        event = CalendarEvent(
            id="evt_123",
            title="Meeting",
            start_time=start,
            end_time=end,
        )

        assert event.duration_minutes == 1  # 105 secondes / 60 = 1 minute


class TestCalendarEventIsFollowupProperty:
    """Tests pour la propriété is_followup."""

    def test_is_followup_true_for_followup_type(self):
        """Test que is_followup retourne True pour FOLLOWUP."""
        start = datetime(2026, 3, 24, 10, 0, 0)
        end = datetime(2026, 3, 24, 11, 0, 0)

        event = CalendarEvent(
            id="evt_123",
            title="Follow-up",
            start_time=start,
            end_time=end,
            event_type=CalendarEventType.FOLLOWUP,
        )

        assert event.is_followup is True

    def test_is_followup_false_for_user_event_type(self):
        """Test que is_followup retourne False pour USER_EVENT."""
        start = datetime(2026, 3, 24, 10, 0, 0)
        end = datetime(2026, 3, 24, 11, 0, 0)

        event = CalendarEvent(
            id="evt_123",
            title="User Event",
            start_time=start,
            end_time=end,
            event_type=CalendarEventType.USER_EVENT,
        )

        assert event.is_followup is False

    def test_is_followup_default_false(self):
        """Test que is_followup est False par défaut (USER_EVENT)."""
        start = datetime(2026, 3, 24, 10, 0, 0)
        end = datetime(2026, 3, 24, 11, 0, 0)

        event = CalendarEvent(
            id="evt_123",
            title="Event",
            start_time=start,
            end_time=end,
        )

        assert event.is_followup is False


class TestCalendarEventToDict:
    """Tests pour la sérialisation to_dict()."""

    def test_to_dict_basic(self):
        """Test la sérialisation basique en dictionnaire."""
        start = datetime(2026, 3, 24, 10, 0, 0)
        end = datetime(2026, 3, 24, 11, 0, 0)

        event = CalendarEvent(
            id="evt_123",
            title="Meeting",
            start_time=start,
            end_time=end,
        )

        data = event.to_dict()

        assert data["id"] == "evt_123"
        assert data["title"] == "Meeting"
        assert data["start_time"] == start.isoformat()
        assert data["end_time"] == end.isoformat()
        assert data["description"] == ""
        assert data["all_day"] is False
        assert data["location"] == ""
        assert data["attendees"] == []
        assert data["status"] == "confirmed"
        assert data["event_type"] == "user_event"

    def test_to_dict_with_datetimes(self):
        """Test que les datetimes sont sérialisées en ISO format."""
        start = datetime(2026, 3, 24, 10, 30, 45)
        end = datetime(2026, 3, 24, 11, 30, 45)
        created_at = datetime(2026, 3, 20, 14, 15, 0)
        updated_at = datetime(2026, 3, 23, 16, 45, 0)

        event = CalendarEvent(
            id="evt_123",
            title="Meeting",
            start_time=start,
            end_time=end,
            created_at=created_at,
            updated_at=updated_at,
        )

        data = event.to_dict()

        assert data["start_time"] == "2026-03-24T10:30:45"
        assert data["end_time"] == "2026-03-24T11:30:45"
        assert data["created_at"] == "2026-03-20T14:15:00"
        assert data["updated_at"] == "2026-03-23T16:45:00"

    def test_to_dict_with_all_fields(self):
        """Test la sérialisation avec tous les champs."""
        start = datetime(2026, 3, 24, 10, 0, 0)
        end = datetime(2026, 3, 24, 11, 30, 0)
        created_at = datetime(2026, 3, 20, 14, 30, 0)
        updated_at = datetime(2026, 3, 23, 15, 45, 0)

        event = CalendarEvent(
            id="evt_456",
            title="Project Planning",
            description="Q2 roadmap",
            start_time=start,
            end_time=end,
            all_day=False,
            location="Room A",
            attendees=["alice@example.com", "bob@example.com"],
            status=CalendarEventStatus.TENTATIVE,
            event_type=CalendarEventType.FOLLOWUP,
            provider="gmail",
            provider_event_id="provider_789",
            calendar_id="work@example.com",
            created_at=created_at,
            updated_at=updated_at,
            email_id="email_999",
            recurrence="RRULE:FREQ=WEEKLY",
            reminders=[15, 30, 60],
            color="#FF6B6B",
            html_link="https://calendar.google.com/event",
        )

        data = event.to_dict()

        assert data["id"] == "evt_456"
        assert data["title"] == "Project Planning"
        assert data["description"] == "Q2 roadmap"
        assert data["all_day"] is False
        assert data["location"] == "Room A"
        assert data["attendees"] == ["alice@example.com", "bob@example.com"]
        assert data["status"] == "tentative"
        assert data["event_type"] == "followup"
        assert data["provider"] == "gmail"
        assert data["provider_event_id"] == "provider_789"
        assert data["calendar_id"] == "work@example.com"
        assert data["created_at"] == "2026-03-20T14:30:00"
        assert data["updated_at"] == "2026-03-23T15:45:00"
        assert data["email_id"] == "email_999"
        assert data["recurrence"] == "RRULE:FREQ=WEEKLY"
        assert data["reminders"] == [15, 30, 60]
        assert data["color"] == "#FF6B6B"
        assert data["html_link"] == "https://calendar.google.com/event"

    def test_to_dict_with_none_values(self):
        """Test la sérialisation avec valeurs None."""
        start = datetime(2026, 3, 24, 10, 0, 0)
        end = datetime(2026, 3, 24, 11, 0, 0)

        event = CalendarEvent(
            id="evt_123",
            title="Meeting",
            start_time=start,
            end_time=end,
            created_at=None,
            updated_at=None,
            email_id=None,
            recurrence=None,
            color=None,
            html_link=None,
        )

        data = event.to_dict()

        assert data["created_at"] is None
        assert data["updated_at"] is None
        assert data["email_id"] is None
        assert data["recurrence"] is None
        assert data["color"] is None
        assert data["html_link"] is None


class TestCalendarEventFromDict:
    """Tests pour la désérialisation from_dict()."""

    def test_from_dict_basic(self):
        """Test la désérialisation basique."""
        data = {
            "id": "evt_123",
            "title": "Meeting",
            "start_time": "2026-03-24T10:00:00",
            "end_time": "2026-03-24T11:00:00",
        }

        event = CalendarEvent.from_dict(data)

        assert event.id == "evt_123"
        assert event.title == "Meeting"
        assert event.start_time == datetime(2026, 3, 24, 10, 0, 0)
        assert event.end_time == datetime(2026, 3, 24, 11, 0, 0)

    def test_from_dict_with_z_suffix_utc(self):
        """Test la désérialisation avec suffixe Z (UTC)."""
        data = {
            "id": "evt_123",
            "title": "Meeting",
            "start_time": "2026-03-24T10:00:00Z",
            "end_time": "2026-03-24T11:00:00Z",
        }

        event = CalendarEvent.from_dict(data)

        assert event.id == "evt_123"
        assert event.title == "Meeting"
        # Le Z est converti en UTC timezone-aware datetime
        from datetime import timezone
        assert event.start_time == datetime(2026, 3, 24, 10, 0, 0, tzinfo=timezone.utc)
        assert event.end_time == datetime(2026, 3, 24, 11, 0, 0, tzinfo=timezone.utc)

    def test_from_dict_with_datetime_objects(self):
        """Test la désérialisation avec objets datetime (pas de parsing)."""
        start = datetime(2026, 3, 24, 10, 0, 0)
        end = datetime(2026, 3, 24, 11, 0, 0)

        data = {
            "id": "evt_123",
            "title": "Meeting",
            "start_time": start,
            "end_time": end,
        }

        event = CalendarEvent.from_dict(data)

        assert event.start_time == start
        assert event.end_time == end

    def test_from_dict_with_all_fields(self):
        """Test la désérialisation avec tous les champs."""
        data = {
            "id": "evt_456",
            "title": "Project Planning",
            "description": "Q2 roadmap",
            "start_time": "2026-03-24T10:00:00Z",
            "end_time": "2026-03-24T11:30:00Z",
            "all_day": False,
            "location": "Room A",
            "attendees": ["alice@example.com", "bob@example.com"],
            "status": "tentative",
            "event_type": "followup",
            "provider": "gmail",
            "provider_event_id": "provider_789",
            "calendar_id": "work@example.com",
            "created_at": "2026-03-20T14:30:00Z",
            "updated_at": "2026-03-23T15:45:00Z",
            "email_id": "email_999",
            "recurrence": "RRULE:FREQ=WEEKLY",
            "reminders": [15, 30, 60],
            "color": "#FF6B6B",
            "html_link": "https://calendar.google.com/event",
        }

        event = CalendarEvent.from_dict(data)

        assert event.id == "evt_456"
        assert event.title == "Project Planning"
        assert event.description == "Q2 roadmap"
        assert event.all_day is False
        assert event.location == "Room A"
        assert event.attendees == ["alice@example.com", "bob@example.com"]
        assert event.status == CalendarEventStatus.TENTATIVE
        assert event.event_type == CalendarEventType.FOLLOWUP
        assert event.provider == "gmail"
        assert event.provider_event_id == "provider_789"
        assert event.calendar_id == "work@example.com"
        assert event.email_id == "email_999"
        assert event.recurrence == "RRULE:FREQ=WEEKLY"
        assert event.reminders == [15, 30, 60]
        assert event.color == "#FF6B6B"
        assert event.html_link == "https://calendar.google.com/event"

    def test_from_dict_with_enum_objects(self):
        """Test la désérialisation avec objets enum (pas de parsing)."""
        data = {
            "id": "evt_123",
            "title": "Meeting",
            "start_time": "2026-03-24T10:00:00",
            "end_time": "2026-03-24T11:00:00",
            "status": CalendarEventStatus.CANCELLED,
            "event_type": CalendarEventType.FOLLOWUP,
        }

        event = CalendarEvent.from_dict(data)

        assert event.status == CalendarEventStatus.CANCELLED
        assert event.event_type == CalendarEventType.FOLLOWUP

    def test_from_dict_missing_optional_fields(self):
        """Test la désérialisation sans champs optionnels."""
        data = {
            "id": "evt_123",
            "title": "Meeting",
            "start_time": "2026-03-24T10:00:00",
            "end_time": "2026-03-24T11:00:00",
        }

        event = CalendarEvent.from_dict(data)

        assert event.id == "evt_123"
        assert event.title == "Meeting"
        assert event.description == ""
        assert event.location == ""
        assert event.attendees == []
        assert event.status == CalendarEventStatus.CONFIRMED
        assert event.event_type == CalendarEventType.USER_EVENT
        assert event.provider == ""
        assert event.provider_event_id == ""
        assert event.calendar_id == "primary"
        assert event.created_at is None
        assert event.updated_at is None
        assert event.email_id is None
        assert event.recurrence is None
        assert event.reminders == [30]
        assert event.color is None
        assert event.html_link is None

    def test_from_dict_roundtrip(self):
        """Test la sérialisation/désérialisation (roundtrip)."""
        start = datetime(2026, 3, 24, 10, 0, 0)
        end = datetime(2026, 3, 24, 11, 30, 0)
        created_at = datetime(2026, 3, 20, 14, 30, 0)
        updated_at = datetime(2026, 3, 23, 15, 45, 0)

        original = CalendarEvent(
            id="evt_456",
            title="Project Planning",
            description="Q2 roadmap",
            start_time=start,
            end_time=end,
            all_day=False,
            location="Room A",
            attendees=["alice@example.com", "bob@example.com"],
            status=CalendarEventStatus.TENTATIVE,
            event_type=CalendarEventType.FOLLOWUP,
            provider="gmail",
            provider_event_id="provider_789",
            calendar_id="work@example.com",
            created_at=created_at,
            updated_at=updated_at,
            email_id="email_999",
            recurrence="RRULE:FREQ=WEEKLY",
            reminders=[15, 30, 60],
            color="#FF6B6B",
            html_link="https://calendar.google.com/event",
        )

        # Sérialiser
        data = original.to_dict()

        # Désérialiser
        restored = CalendarEvent.from_dict(data)

        # Vérifier que tout correspond
        assert restored.id == original.id
        assert restored.title == original.title
        assert restored.description == original.description
        assert restored.start_time == original.start_time
        assert restored.end_time == original.end_time
        assert restored.all_day == original.all_day
        assert restored.location == original.location
        assert restored.attendees == original.attendees
        assert restored.status == original.status
        assert restored.event_type == original.event_type
        assert restored.provider == original.provider
        assert restored.provider_event_id == original.provider_event_id
        assert restored.calendar_id == original.calendar_id
        assert restored.created_at == original.created_at
        assert restored.updated_at == original.updated_at
        assert restored.email_id == original.email_id
        assert restored.recurrence == original.recurrence
        assert restored.reminders == original.reminders
        assert restored.color == original.color
        assert restored.html_link == original.html_link


class TestCalendarEventStatusEnum:
    """Tests pour l'énumération CalendarEventStatus."""

    def test_status_enum_values(self):
        """Test les valeurs de l'énumération CalendarEventStatus."""
        assert CalendarEventStatus.CONFIRMED.value == "confirmed"
        assert CalendarEventStatus.TENTATIVE.value == "tentative"
        assert CalendarEventStatus.CANCELLED.value == "cancelled"

    def test_status_enum_creation_from_string(self):
        """Test la création d'énumération à partir de string."""
        confirmed = CalendarEventStatus("confirmed")
        tentative = CalendarEventStatus("tentative")
        cancelled = CalendarEventStatus("cancelled")

        assert confirmed == CalendarEventStatus.CONFIRMED
        assert tentative == CalendarEventStatus.TENTATIVE
        assert cancelled == CalendarEventStatus.CANCELLED

    def test_status_enum_invalid_value(self):
        """Test qu'une valeur invalide lève ValueError."""
        with pytest.raises(ValueError):
            CalendarEventStatus("invalid_status")


class TestCalendarEventTypeEnum:
    """Tests pour l'énumération CalendarEventType."""

    def test_event_type_enum_values(self):
        """Test les valeurs de l'énumération CalendarEventType."""
        assert CalendarEventType.USER_EVENT.value == "user_event"
        assert CalendarEventType.FOLLOWUP.value == "followup"

    def test_event_type_enum_creation_from_string(self):
        """Test la création d'énumération à partir de string."""
        user_event = CalendarEventType("user_event")
        followup = CalendarEventType("followup")

        assert user_event == CalendarEventType.USER_EVENT
        assert followup == CalendarEventType.FOLLOWUP

    def test_event_type_enum_invalid_value(self):
        """Test qu'une valeur invalide lève ValueError."""
        with pytest.raises(ValueError):
            CalendarEventType("invalid_type")


class TestCalendarEventDefaults:
    """Tests pour les valeurs par défaut."""

    def test_default_description(self):
        """Test que description a pour défaut une chaîne vide."""
        start = datetime(2026, 3, 24, 10, 0, 0)
        end = datetime(2026, 3, 24, 11, 0, 0)

        event = CalendarEvent(
            id="evt_123",
            title="Meeting",
            start_time=start,
            end_time=end,
        )

        assert event.description == ""

    def test_default_all_day(self):
        """Test que all_day a pour défaut False."""
        start = datetime(2026, 3, 24, 10, 0, 0)
        end = datetime(2026, 3, 24, 11, 0, 0)

        event = CalendarEvent(
            id="evt_123",
            title="Meeting",
            start_time=start,
            end_time=end,
        )

        assert event.all_day is False

    def test_default_location(self):
        """Test que location a pour défaut une chaîne vide."""
        start = datetime(2026, 3, 24, 10, 0, 0)
        end = datetime(2026, 3, 24, 11, 0, 0)

        event = CalendarEvent(
            id="evt_123",
            title="Meeting",
            start_time=start,
            end_time=end,
        )

        assert event.location == ""

    def test_default_attendees(self):
        """Test que attendees a pour défaut une liste vide."""
        start = datetime(2026, 3, 24, 10, 0, 0)
        end = datetime(2026, 3, 24, 11, 0, 0)

        event = CalendarEvent(
            id="evt_123",
            title="Meeting",
            start_time=start,
            end_time=end,
        )

        assert event.attendees == []

    def test_default_status(self):
        """Test que status a pour défaut CONFIRMED."""
        start = datetime(2026, 3, 24, 10, 0, 0)
        end = datetime(2026, 3, 24, 11, 0, 0)

        event = CalendarEvent(
            id="evt_123",
            title="Meeting",
            start_time=start,
            end_time=end,
        )

        assert event.status == CalendarEventStatus.CONFIRMED

    def test_default_event_type(self):
        """Test que event_type a pour défaut USER_EVENT."""
        start = datetime(2026, 3, 24, 10, 0, 0)
        end = datetime(2026, 3, 24, 11, 0, 0)

        event = CalendarEvent(
            id="evt_123",
            title="Meeting",
            start_time=start,
            end_time=end,
        )

        assert event.event_type == CalendarEventType.USER_EVENT

    def test_default_provider(self):
        """Test que provider a pour défaut une chaîne vide."""
        start = datetime(2026, 3, 24, 10, 0, 0)
        end = datetime(2026, 3, 24, 11, 0, 0)

        event = CalendarEvent(
            id="evt_123",
            title="Meeting",
            start_time=start,
            end_time=end,
        )

        assert event.provider == ""

    def test_default_provider_event_id(self):
        """Test que provider_event_id a pour défaut une chaîne vide."""
        start = datetime(2026, 3, 24, 10, 0, 0)
        end = datetime(2026, 3, 24, 11, 0, 0)

        event = CalendarEvent(
            id="evt_123",
            title="Meeting",
            start_time=start,
            end_time=end,
        )

        assert event.provider_event_id == ""

    def test_default_calendar_id(self):
        """Test que calendar_id a pour défaut 'primary'."""
        start = datetime(2026, 3, 24, 10, 0, 0)
        end = datetime(2026, 3, 24, 11, 0, 0)

        event = CalendarEvent(
            id="evt_123",
            title="Meeting",
            start_time=start,
            end_time=end,
        )

        assert event.calendar_id == "primary"

    def test_default_reminders(self):
        """Test que reminders a pour défaut [30]."""
        start = datetime(2026, 3, 24, 10, 0, 0)
        end = datetime(2026, 3, 24, 11, 0, 0)

        event = CalendarEvent(
            id="evt_123",
            title="Meeting",
            start_time=start,
            end_time=end,
        )

        assert event.reminders == [30]

    def test_default_reminders_isolation(self):
        """Test que chaque instance a sa propre liste reminders."""
        start = datetime(2026, 3, 24, 10, 0, 0)
        end = datetime(2026, 3, 24, 11, 0, 0)

        event1 = CalendarEvent(
            id="evt_123",
            title="Meeting 1",
            start_time=start,
            end_time=end,
        )

        event2 = CalendarEvent(
            id="evt_456",
            title="Meeting 2",
            start_time=start,
            end_time=end,
        )

        event1.reminders.append(60)

        assert event1.reminders == [30, 60]
        assert event2.reminders == [30]

    def test_default_attendees_isolation(self):
        """Test que chaque instance a sa propre liste attendees."""
        start = datetime(2026, 3, 24, 10, 0, 0)
        end = datetime(2026, 3, 24, 11, 0, 0)

        event1 = CalendarEvent(
            id="evt_123",
            title="Meeting 1",
            start_time=start,
            end_time=end,
        )

        event2 = CalendarEvent(
            id="evt_456",
            title="Meeting 2",
            start_time=start,
            end_time=end,
        )

        event1.attendees.append("alice@example.com")

        assert event1.attendees == ["alice@example.com"]
        assert event2.attendees == []
