# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
# Tests for OutlookCalendarAdapter CRUD operations (create, update, delete).
"""
Tests unitaires pour les opérations CRUD du OutlookCalendarAdapter
(app/providers/outlook_calendar.py).

Vérifie que create_event, update_event, delete_event fonctionnent
correctement avec l'API Microsoft Graph.
"""

import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class FakeEvent:
    """Minimal event object mimicking DomainCalendarEvent."""
    id: str = "evt-123"
    title: str = "Réunion test"
    description: str = "Description de test"
    start_time: datetime = None
    end_time: datetime = None
    all_day: bool = False
    location: str = "Salle A"
    attendees: List[str] = field(default_factory=list)
    reminders: List[int] = field(default_factory=list)
    calendar_id: str = "primary"
    conference: bool = False
    provider_event_id: Optional[str] = None
    is_all_day: Optional[bool] = None

    def __post_init__(self):
        if self.start_time is None:
            self.start_time = datetime(2026, 3, 20, 10, 0, 0)
        if self.end_time is None:
            self.end_time = datetime(2026, 3, 20, 11, 0, 0)


@pytest.fixture
def adapter():
    """Create an OutlookCalendarAdapter pre-authenticated."""
    from app.providers.outlook_calendar import OutlookCalendarAdapter
    a = OutlookCalendarAdapter(account_id="test-account", access_token="fake-token")
    a._authenticated = True
    return a


# ------------------------------------------------------------------ #
#  _build_event_body — reminders                                      #
# ------------------------------------------------------------------ #

class TestBuildEventBodyReminders:
    """Regression (chaos audit 2026-06-02, provider parity): Microsoft Graph
    supports only ONE reminder per event, so a multi-reminder event silently
    lost its extras on Outlook while Gmail kept all of them. Keep the first AND
    warn, instead of dropping silently."""

    def test_single_reminder_no_warning(self, adapter, caplog):
        import logging
        event = FakeEvent(reminders=[30])
        with caplog.at_level(logging.WARNING):
            body = adapter._build_event_body(event)
        assert body["isReminderOn"] is True
        assert body["reminderMinutesBeforeStart"] == 30
        assert "dropping" not in caplog.text.lower()

    def test_multiple_reminders_keeps_first_and_warns(self, adapter, caplog):
        import logging
        event = FakeEvent(reminders=[30, 60, 1440])
        with caplog.at_level(logging.WARNING):
            body = adapter._build_event_body(event)
        assert body["isReminderOn"] is True
        assert body["reminderMinutesBeforeStart"] == 30  # first kept
        # the silent drop is now surfaced
        assert "dropping" in caplog.text.lower()
        assert "60" in caplog.text and "1440" in caplog.text


# ------------------------------------------------------------------ #
#  create_event                                                       #
# ------------------------------------------------------------------ #

class TestCreateEvent:

    @patch("app.providers.outlook_calendar.requests.post")
    def test_create_event_success(self, mock_post, adapter):
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "id": "AAMk-new-event-id",
            "subject": "Réunion test",
        }
        mock_post.return_value = mock_response

        event = FakeEvent()
        result = adapter.create_event(event, "primary")

        assert result == {"event_id": "AAMk-new-event-id", "meet_link": None}
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert "/me/calendar/events" in call_kwargs[0][0] or "/me/calendar/events" in str(call_kwargs)
        body = call_kwargs[1]["json"] if "json" in call_kwargs[1] else call_kwargs.kwargs["json"]
        assert body["subject"] == "Réunion test"
        assert body["isAllDay"] is False

    @patch("app.providers.outlook_calendar.requests.post")
    def test_create_event_specific_calendar(self, mock_post, adapter):
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": "AAMk-cal2-event"}
        mock_post.return_value = mock_response

        event = FakeEvent()
        result = adapter.create_event(event, "cal-id-xyz")

        assert result == {"event_id": "AAMk-cal2-event", "meet_link": None}
        url = mock_post.call_args[0][0]
        assert "/me/calendars/cal-id-xyz/events" in url

    @patch("app.providers.outlook_calendar.requests.post")
    def test_create_event_with_teams_link(self, mock_post, adapter):
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "id": "AAMk-teams-event",
            "onlineMeeting": {
                "joinUrl": "https://teams.microsoft.com/l/meetup-join/abc123"
            },
        }
        mock_post.return_value = mock_response

        event = FakeEvent(conference=True)
        result = adapter.create_event(event)

        assert result == {"event_id": "AAMk-teams-event", "meet_link": "https://teams.microsoft.com/l/meetup-join/abc123"}
        assert adapter._last_meet_link == "https://teams.microsoft.com/l/meetup-join/abc123"
        body = mock_post.call_args[1]["json"]
        assert body["isOnlineMeeting"] is True

    @patch("app.providers.outlook_calendar.requests.post")
    def test_create_event_all_day(self, mock_post, adapter):
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": "AAMk-allday"}
        mock_post.return_value = mock_response

        event = FakeEvent(
            all_day=True,
            start_time=datetime(2026, 3, 20),
            end_time=datetime(2026, 3, 21),
        )
        result = adapter.create_event(event)

        assert result == {"event_id": "AAMk-allday", "meet_link": None}
        body = mock_post.call_args[1]["json"]
        assert body["isAllDay"] is True
        assert body["start"]["dateTime"] == "2026-03-20T00:00:00"

    @patch("app.providers.outlook_calendar.requests.post")
    def test_create_event_with_attendees_and_location(self, mock_post, adapter):
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": "AAMk-attendees"}
        mock_post.return_value = mock_response

        event = FakeEvent(
            attendees=["alice@test.com", "bob@test.com"],
            location="Salle de conférence B",
        )
        result = adapter.create_event(event)

        assert result == {"event_id": "AAMk-attendees", "meet_link": None}
        body = mock_post.call_args[1]["json"]
        assert len(body["attendees"]) == 2
        assert body["attendees"][0]["emailAddress"]["address"] == "alice@test.com"
        assert body["location"]["displayName"] == "Salle de conférence B"

    @patch("app.providers.outlook_calendar.requests.post")
    def test_create_event_403_raises_scope_error(self, mock_post, adapter):
        from app.interfaces.calendar_provider import CalendarScopeError

        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status_code = 403
        mock_response.text = "Forbidden"
        mock_post.return_value = mock_response

        event = FakeEvent()

        with pytest.raises(CalendarScopeError) as exc_info:
            adapter.create_event(event)
        assert "outlook" in str(exc_info.value).lower() or exc_info.value.provider == "outlook"

    @patch("app.providers.outlook_calendar.requests.post")
    def test_create_event_500_returns_none(self, mock_post, adapter):
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_post.return_value = mock_response

        event = FakeEvent()
        result = adapter.create_event(event)
        assert result is None


# ------------------------------------------------------------------ #
#  update_event                                                       #
# ------------------------------------------------------------------ #

class TestUpdateEvent:

    @patch("app.providers.outlook_calendar.requests.patch")
    def test_update_event_success(self, mock_patch, adapter):
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "evt-123"}
        mock_patch.return_value = mock_response

        event = FakeEvent(title="Titre modifié")
        result = adapter.update_event(event)

        assert result is True
        url = mock_patch.call_args[0][0]
        assert "/me/events/evt-123" in url
        body = mock_patch.call_args[1]["json"]
        assert body["subject"] == "Titre modifié"

    @patch("app.providers.outlook_calendar.requests.patch")
    def test_update_event_uses_provider_event_id(self, mock_patch, adapter):
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_patch.return_value = mock_response

        event = FakeEvent(id="local-id", provider_event_id="AAMk-provider-id")
        result = adapter.update_event(event)

        assert result is True
        url = mock_patch.call_args[0][0]
        assert "AAMk-provider-id" in url

    @patch("app.providers.outlook_calendar.requests.patch")
    def test_update_event_404(self, mock_patch, adapter):
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status_code = 404
        mock_response.text = "Not Found"
        mock_patch.return_value = mock_response

        event = FakeEvent()
        result = adapter.update_event(event)
        assert result is False

    @patch("app.providers.outlook_calendar.requests.patch")
    def test_update_event_403_raises_scope_error(self, mock_patch, adapter):
        from app.interfaces.calendar_provider import CalendarScopeError

        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status_code = 403
        mock_response.text = "Forbidden"
        mock_patch.return_value = mock_response

        event = FakeEvent()
        with pytest.raises(CalendarScopeError):
            adapter.update_event(event)


# ------------------------------------------------------------------ #
#  delete_event                                                       #
# ------------------------------------------------------------------ #

class TestDeleteEvent:

    @patch("app.providers.outlook_calendar.requests.delete")
    def test_delete_event_success(self, mock_delete, adapter):
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_delete.return_value = mock_response

        result = adapter.delete_event("AAMk-del-123")

        assert result is True
        url = mock_delete.call_args[0][0]
        assert "/me/events/AAMk-del-123" in url

    @patch("app.providers.outlook_calendar.requests.delete")
    def test_delete_event_404(self, mock_delete, adapter):
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_delete.return_value = mock_response

        result = adapter.delete_event("nonexistent-id")
        assert result is False

    @patch("app.providers.outlook_calendar.requests.delete")
    def test_delete_event_403_raises_scope_error(self, mock_delete, adapter):
        from app.interfaces.calendar_provider import CalendarScopeError

        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_delete.return_value = mock_response

        with pytest.raises(CalendarScopeError):
            adapter.delete_event("some-id")

    @patch("app.providers.outlook_calendar.requests.delete")
    def test_delete_event_server_error(self, mock_delete, adapter):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_delete.return_value = mock_response

        result = adapter.delete_event("some-id")
        assert result is False


# ------------------------------------------------------------------ #
#  _build_event_body + _format_datetime helpers                       #
# ------------------------------------------------------------------ #

class TestHelpers:

    def test_format_datetime_normal(self, adapter):
        dt = datetime(2026, 3, 20, 14, 30, 0)
        result = adapter._format_datetime(dt, all_day=False)
        assert result == {"dateTime": "2026-03-20T14:30:00", "timeZone": "UTC"}

    def test_format_datetime_all_day(self, adapter):
        dt = datetime(2026, 3, 20, 14, 30, 0)
        result = adapter._format_datetime(dt, all_day=True)
        assert result == {"dateTime": "2026-03-20T00:00:00", "timeZone": "UTC"}

    def test_build_event_body_minimal(self, adapter):
        # attendees=[] is the "clear all attendees" signal -> must be sent
        # explicitly so a Graph PATCH drops them (omitting the key preserves them).
        event = FakeEvent(location="", attendees=[], reminders=[])
        body = adapter._build_event_body(event)
        assert body["subject"] == "Réunion test"
        assert "location" not in body
        assert body["attendees"] == []
        assert "isReminderOn" not in body

    def test_build_event_body_attendees_none_omitted(self, adapter):
        # None = "leave attendees untouched" (drag/resize PATCH omits the field).
        event = FakeEvent(location="", attendees=None, reminders=[])
        body = adapter._build_event_body(event)
        assert "attendees" not in body

    def test_build_event_body_with_reminders(self, adapter):
        event = FakeEvent(reminders=[15])
        body = adapter._build_event_body(event)
        assert body["isReminderOn"] is True
        assert body["reminderMinutesBeforeStart"] == 15


# ------------------------------------------------------------------ #
#  Read path: all-day events must not shift a day for non-UTC users   #
# ------------------------------------------------------------------ #

class TestAllDayReadPath:

    def test_all_day_serializes_offsetless_local_date(self, adapter):
        """A Graph all-day payload (UTC midnight) must serialize to an offset-less
        ISO so the FE reads it as a local calendar date, not a UTC instant that
        shifts west-of-UTC users back a day."""
        from app.api.calendar_routes import _serialize_event

        graph_event = {
            "id": "AAMk-allday",
            "subject": "Anniversaire",
            "isAllDay": True,
            "start": {"dateTime": "2026-06-15T00:00:00.0000000", "timeZone": "UTC"},
            "end": {"dateTime": "2026-06-16T00:00:00.0000000", "timeZone": "UTC"},
        }
        event = adapter._map_to_event(graph_event)
        serialized = _serialize_event(event)

        assert serialized["isAllDay"] is True
        assert serialized["start"] == "2026-06-15T00:00:00"
        assert "+00:00" not in serialized["start"]
        assert not serialized["start"].endswith("Z")
        assert serialized["end"] == "2026-06-16T00:00:00"


# ------------------------------------------------------------------ #
#  Token refresh scope (oauth.py)                                     #
# ------------------------------------------------------------------ #

class TestTokenRefreshScope:

    def test_outlook_refresh_scope_includes_calendar(self):
        """Verify that oauth.py refresh scope includes Calendars.ReadWrite."""
        import inspect
        from app.api import oauth
        source = inspect.getsource(oauth._refresh_tokens_server)
        assert "Calendars.ReadWrite" in source, (
            "Outlook token refresh must include Calendars.ReadWrite scope"
        )
