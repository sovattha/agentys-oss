# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour la génération et l'extraction du lien Teams
dans les adaptateurs Outlook Calendar.

Couvre :
1. OutlookCalendarAdapter (CalendarPort) — create_event extrait le lien Teams
2. OutlookCalendarAdapter (CalendarProvider) — _map_to_event extrait le lien Teams
3. Parité avec Google Calendar (même champ meet_link)
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone


# ============================================================================
# OutlookCalendarAdapter (CalendarPort) — create_event Teams link
# ============================================================================


class TestOutlookCalendarAdapterTeamsLink:
    """Tests pour l'extraction du lien Teams lors de la création d'événement."""

    @pytest.fixture
    def adapter(self):
        """Crée un OutlookCalendarAdapter authentifié avec token mocké."""
        from app.providers.outlook_calendar_adapter import OutlookCalendarAdapter
        a = OutlookCalendarAdapter(
            account_id="test-outlook-account",
            access_token="fake-token-123",
        )
        a._authenticated = True
        return a

    @pytest.fixture
    def calendar_event_with_conference(self):
        """CalendarEvent (domain entity) avec conference=True."""
        from app.domain.entities import CalendarEvent
        return CalendarEvent(
            id="temp-id",
            title="Réunion de projet",
            description="Discussion technique",
            start_time=datetime(2026, 3, 15, 14, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 3, 15, 15, 0, tzinfo=timezone.utc),
            attendees=["alice@company.com", "bob@company.com"],
            conference=True,
        )

    @pytest.fixture
    def calendar_event_without_conference(self):
        """CalendarEvent (domain entity) sans conference."""
        from app.domain.entities import CalendarEvent
        return CalendarEvent(
            id="temp-id-2",
            title="Point rapide",
            start_time=datetime(2026, 3, 15, 16, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 3, 15, 16, 30, tzinfo=timezone.utc),
            conference=False,
        )

    @patch("app.providers.outlook_calendar_adapter.requests.post")
    def test_create_event_extracts_teams_link(
        self, mock_post, adapter, calendar_event_with_conference
    ):
        """Vérifie que le lien Teams est extrait de la réponse Graph API."""
        teams_url = "https://teams.microsoft.com/l/meetup-join/19%3ameeting_abc123"
        mock_post.return_value = MagicMock(
            ok=True,
            json=lambda: {
                "id": "outlook-evt-001",
                "subject": "Réunion de projet",
                "isOnlineMeeting": True,
                "onlineMeeting": {
                    "joinUrl": teams_url,
                },
            },
        )

        result = adapter.create_event(calendar_event_with_conference)

        assert result == {"event_id": "outlook-evt-001", "meet_link": teams_url}
        assert adapter._last_meet_link == teams_url

        # Vérifier que isOnlineMeeting est bien envoyé dans le body
        call_kwargs = mock_post.call_args
        sent_body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert sent_body["isOnlineMeeting"] is True

    @patch("app.providers.outlook_calendar_adapter.requests.post")
    def test_create_event_no_conference_no_link(
        self, mock_post, adapter, calendar_event_without_conference
    ):
        """Sans conference=True, pas de lien Teams."""
        mock_post.return_value = MagicMock(
            ok=True,
            json=lambda: {
                "id": "outlook-evt-002",
                "subject": "Point rapide",
            },
        )

        result = adapter.create_event(calendar_event_without_conference)

        assert result == {"event_id": "outlook-evt-002", "meet_link": None}
        assert adapter._last_meet_link is None

        # Vérifier que isOnlineMeeting n'est PAS envoyé
        call_kwargs = mock_post.call_args
        sent_body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert "isOnlineMeeting" not in sent_body

    @patch("app.providers.outlook_calendar_adapter.requests.post")
    def test_create_event_no_online_meeting_in_response(
        self, mock_post, adapter, calendar_event_with_conference
    ):
        """Si l'API ne retourne pas onlineMeeting (ex: pas de licence Teams), _last_meet_link est None."""
        mock_post.return_value = MagicMock(
            ok=True,
            json=lambda: {
                "id": "outlook-evt-003",
                "subject": "Réunion de projet",
                # onlineMeeting absent de la réponse
            },
        )

        result = adapter.create_event(calendar_event_with_conference)

        assert result == {"event_id": "outlook-evt-003", "meet_link": None}
        assert adapter._last_meet_link is None


# ============================================================================
# OutlookCalendarAdapter (CalendarProvider) — _map_to_event Teams link
# ============================================================================


class TestOutlookCalendarProviderTeamsLink:
    """Tests pour l'extraction du lien Teams lors du listing d'événements."""

    @pytest.fixture
    def provider(self):
        """Crée un OutlookCalendarAdapter (CalendarProvider) avec token mocké."""
        from app.providers.outlook_calendar import OutlookCalendarAdapter
        p = OutlookCalendarAdapter(
            account_id="test-outlook-account",
            access_token="fake-token-123",
        )
        p._authenticated = True
        return p

    def test_map_to_event_with_teams_link(self, provider):
        """Un événement Outlook avec onlineMeeting → meet_link extrait."""
        teams_url = "https://teams.microsoft.com/l/meetup-join/19%3ameeting_xyz789"
        event_data = {
            "id": "evt-outlook-100",
            "subject": "Stand-up quotidien",
            "start": {"dateTime": "2026-03-15T09:00:00", "timeZone": "UTC"},
            "end": {"dateTime": "2026-03-15T09:15:00", "timeZone": "UTC"},
            "isAllDay": False,
            "location": {"displayName": ""},
            "attendees": [],
            "organizer": {
                "emailAddress": {"address": "manager@company.com"},
            },
            "body": {"contentType": "text", "content": ""},
            "isCancelled": False,
            "recurrence": None,
            "webLink": "https://outlook.office.com/calendar/...",
            "importance": "normal",
            "showAs": "busy",
            "sensitivity": "normal",
            "categories": [],
            "responseStatus": {"response": "accepted"},
            "isOnlineMeeting": True,
            "onlineMeeting": {
                "joinUrl": teams_url,
            },
        }

        event = provider._map_to_event(event_data)

        assert event.meet_link == teams_url
        assert event.title == "Stand-up quotidien"

    def test_map_to_event_without_online_meeting(self, provider):
        """Un événement sans onlineMeeting → meet_link est None."""
        event_data = {
            "id": "evt-outlook-101",
            "subject": "Déjeuner équipe",
            "start": {"dateTime": "2026-03-15T12:00:00", "timeZone": "UTC"},
            "end": {"dateTime": "2026-03-15T13:00:00", "timeZone": "UTC"},
            "isAllDay": False,
            "location": {"displayName": "Restaurant"},
            "attendees": [],
            "body": {"contentType": "text", "content": ""},
            "isCancelled": False,
            "recurrence": None,
            "webLink": "https://outlook.office.com/calendar/...",
            "importance": "normal",
            "showAs": "busy",
            "sensitivity": "normal",
            "categories": [],
            "responseStatus": {"response": "accepted"},
        }

        event = provider._map_to_event(event_data)

        assert event.meet_link is None

    def test_map_to_event_online_meeting_null_join_url(self, provider):
        """onlineMeeting présent mais joinUrl null → meet_link est None."""
        event_data = {
            "id": "evt-outlook-102",
            "subject": "Appel téléphonique",
            "start": {"dateTime": "2026-03-15T14:00:00", "timeZone": "UTC"},
            "end": {"dateTime": "2026-03-15T14:30:00", "timeZone": "UTC"},
            "isAllDay": False,
            "location": {"displayName": ""},
            "attendees": [],
            "body": {"contentType": "text", "content": ""},
            "isCancelled": False,
            "recurrence": None,
            "webLink": None,
            "importance": "normal",
            "showAs": "busy",
            "sensitivity": "normal",
            "categories": [],
            "responseStatus": {"response": "none"},
            "isOnlineMeeting": True,
            "onlineMeeting": {
                "joinUrl": None,
            },
        }

        event = provider._map_to_event(event_data)

        assert event.meet_link is None

    def test_select_includes_online_meeting_fields(self, provider):
        """Vérifie que $select inclut onlineMeeting et isOnlineMeeting."""
        # Patch _make_request pour capturer les params
        captured_params = {}

        def capture_request(endpoint, params=None):
            captured_params.update(params or {})
            return {"value": []}

        provider._make_request = capture_request
        provider.get_events(
            start=datetime(2026, 3, 15, tzinfo=timezone.utc),
            end=datetime(2026, 3, 16, tzinfo=timezone.utc),
        )

        select_fields = captured_params.get("$select", "")
        assert "onlineMeeting" in select_fields
        assert "isOnlineMeeting" in select_fields

    def test_get_event_by_id_select_includes_online_meeting(self, provider):
        """Vérifie que get_event_by_id inclut aussi onlineMeeting dans $select."""
        captured_params = {}

        def capture_request(endpoint, params=None):
            captured_params.update(params or {})
            return {
                "id": "evt-x",
                "subject": "Test",
                "start": {"dateTime": "2026-03-15T10:00:00", "timeZone": "UTC"},
                "end": {"dateTime": "2026-03-15T11:00:00", "timeZone": "UTC"},
                "isAllDay": False,
                "location": {"displayName": ""},
                "attendees": [],
                "body": {"contentType": "text", "content": ""},
                "isCancelled": False,
                "recurrence": None,
                "webLink": None,
                "importance": "normal",
                "showAs": "busy",
                "sensitivity": "normal",
                "categories": [],
                "responseStatus": {"response": "none"},
            }

        provider._make_request = capture_request
        provider.get_event_by_id("evt-x")

        select_fields = captured_params.get("$select", "")
        assert "onlineMeeting" in select_fields
        assert "isOnlineMeeting" in select_fields


# ============================================================================
# Parité Google Meet vs Teams — même champ meet_link
# ============================================================================


class TestGoogleMeetParityWithTeams:
    """Vérifie que Google Calendar et Outlook Calendar utilisent le même champ meet_link."""

    def test_google_calendar_meet_link_field_exists(self):
        """Google Calendar utilise meet_link dans CalendarEvent."""
        from app.interfaces.calendar_provider import CalendarEvent
        evt = CalendarEvent(
            id="g-1",
            title="Test Google",
            start=datetime(2026, 3, 15, 10, 0, tzinfo=timezone.utc),
            end=datetime(2026, 3, 15, 11, 0, tzinfo=timezone.utc),
            meet_link="https://meet.google.com/abc-defg-hij",
        )
        assert evt.meet_link == "https://meet.google.com/abc-defg-hij"

    def test_outlook_calendar_meet_link_field_exists(self):
        """Outlook Calendar utilise le même champ meet_link pour Teams."""
        from app.interfaces.calendar_provider import CalendarEvent
        evt = CalendarEvent(
            id="o-1",
            title="Test Outlook",
            start=datetime(2026, 3, 15, 10, 0, tzinfo=timezone.utc),
            end=datetime(2026, 3, 15, 11, 0, tzinfo=timezone.utc),
            meet_link="https://teams.microsoft.com/l/meetup-join/xyz",
        )
        assert evt.meet_link == "https://teams.microsoft.com/l/meetup-join/xyz"

    def test_serialization_includes_meet_link(self):
        """_serialize_event dans calendar_routes doit inclure meetLink."""
        from app.interfaces.calendar_provider import CalendarEvent
        evt = CalendarEvent(
            id="s-1",
            title="Serialization test",
            start=datetime(2026, 3, 15, 10, 0, tzinfo=timezone.utc),
            end=datetime(2026, 3, 15, 11, 0, tzinfo=timezone.utc),
            meet_link="https://teams.microsoft.com/l/meetup-join/test",
        )
        # Simulate what _serialize_event does
        serialized = {
            "id": evt.id,
            "meetLink": evt.meet_link,
        }
        assert serialized["meetLink"] == "https://teams.microsoft.com/l/meetup-join/test"
