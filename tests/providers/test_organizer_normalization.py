# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour la normalisation de l'organisateur d'événement (bug 2026-06-01).

Google renvoie l'id du calendrier (hash hex @group.calendar.google.com) comme
``organizer.email`` pour les événements appartenant à un calendrier secondaire /
partagé / de ressource. Affiché tel quel, cela produit un "Organisateur" =
chaîne hex illisible. ``normalize_organizer`` doit :
- laisser passer un vrai email,
- préférer le displayName quand l'email est un id opaque,
- masquer (None) s'il n'y a ni email exploitable ni displayName.
"""

import pytest

from app.interfaces.calendar_provider import normalize_organizer


# Le hash exact vu dans le bug report (capture d'écran 2026-06-01), tronqué à l'écran.
_OPAQUE_HEX = "47f9e61e4f267a2cb9173be1af598ec880047dbffc92938ac687d7f9375960"


class TestNormalizeOrganizer:
    def test_real_email_passes_through(self):
        assert normalize_organizer("karine@gmail.com") == "karine@gmail.com"

    def test_real_email_preferred_over_display_name(self):
        # Pour un événement normal, l'email EST l'info utile (l'utilisateur veut l'email).
        assert normalize_organizer("inviter@example.com", "Jean Inviteur") == "inviter@example.com"

    def test_opaque_group_calendar_id_falls_back_to_display_name(self):
        assert normalize_organizer(
            f"{_OPAQUE_HEX}@group.calendar.google.com", "Karine Morel"
        ) == "Karine Morel"

    def test_opaque_group_calendar_id_without_display_name_is_hidden(self):
        assert normalize_organizer(f"{_OPAQUE_HEX}@group.calendar.google.com", None) is None
        assert normalize_organizer(f"{_OPAQUE_HEX}@group.calendar.google.com", "") is None

    def test_resource_and_holiday_calendars_are_opaque(self):
        assert normalize_organizer("room-101@resource.calendar.google.com") is None
        assert normalize_organizer("fr.french#holiday@group.v.calendar.google.com") is None

    def test_bare_hex_hash_is_hidden(self):
        # Domaine tronqué/absent : on détecte le hash hex sur la partie locale.
        assert normalize_organizer(_OPAQUE_HEX) is None

    def test_empty_inputs_return_none(self):
        assert normalize_organizer(None) is None
        assert normalize_organizer("") is None
        assert normalize_organizer("   ", "  ") is None

    def test_whitespace_is_trimmed(self):
        assert normalize_organizer("  karine@gmail.com  ") == "karine@gmail.com"

    def test_no_email_uses_display_name(self):
        assert normalize_organizer(None, "Service Comptabilité") == "Service Comptabilité"


class TestGmailMapToEventOrganizer:
    """Le bug exact : Google Calendar -> CalendarEvent.organizer."""

    @pytest.fixture
    def adapter(self):
        from app.providers.gmail_calendar import GmailCalendarAdapter
        return GmailCalendarAdapter(account_id="test-google-account")

    def _event_data(self, organizer):
        return {
            "id": "evt1",
            "summary": "Karine: carrousel ou image + texte Thyroïde",
            "start": {"dateTime": "2026-06-05T10:00:00-04:00"},
            "end": {"dateTime": "2026-06-05T11:00:00-04:00"},
            "organizer": organizer,
        }

    def test_secondary_calendar_hash_hidden_when_no_name(self, adapter):
        event = adapter._map_to_event(
            self._event_data({"email": f"{_OPAQUE_HEX}@group.calendar.google.com"})
        )
        assert event.organizer is None

    def test_secondary_calendar_hash_uses_display_name(self, adapter):
        event = adapter._map_to_event(
            self._event_data(
                {"email": f"{_OPAQUE_HEX}@group.calendar.google.com", "displayName": "Karine Morel"}
            )
        )
        assert event.organizer == "Karine Morel"

    def test_normal_organizer_email_shown(self, adapter):
        event = adapter._map_to_event(
            self._event_data({"email": "karine@gmail.com", "displayName": "Karine"})
        )
        assert event.organizer == "karine@gmail.com"

    def test_no_organizer_field(self, adapter):
        data = self._event_data(None)
        del data["organizer"]
        event = adapter._map_to_event(data)
        assert event.organizer is None
