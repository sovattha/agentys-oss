# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Booking-tool (Calendly) confirmation parsing → appointment meeting_meta.

Mirrors the real screenshot bug: a Calendly confirmation rendered as raw HTML
with no Accept/Decline card, because the only extractor understood iCal. These
tests cover the new ``extract_appointment_from_body`` path and its integration
into ``extract_meeting_from_body``.
"""
from __future__ import annotations

from app.providers.gmail_calendar import (
    extract_appointment_from_body,
    extract_meeting_from_body,
)

# A faithful reduction of the email in the report (FR, Eastern time, in-person
# maderotherapy appointment — no video link, no .ics attachment).
CALENDLY_FR_HTML = """
<html><body>
  <h1>PULSA | Madérothérapie 90 min ✧ 160$</h1>
  <p>Rituel corporel de madérothérapie soutenant le drainage.</p>
  <p>Lieu: 10 rue Principale Nord, Sutton, J0E 2K0</p>
  <p>Numéro de téléphone: +1 514-581-2265</p>
  <p>Souhaitez-vous apporter des modifications à cet événement?</p>
  <p>Annuler: https://calendly.com/cancellations/d334b94a-9496-4c36-8807-61a7a15b368d</p>
  <p>Replanifier: https://calendly.com/reschedulings/d334b94a-9496-4c36-8807-61a7a15b368d</p>
  <p>Alimenté par Calendly.com</p>
  <p>Quand</p>
  <p>mercredi 17 juin 2026 · 15:00 — 16:30 (Heure de l'Est - Toronto)</p>
  <p>Emplacement</p>
</body></html>
"""


class TestCalendlyFrenchConfirmation:
    def test_detects_appointment_kind(self):
        meta = extract_appointment_from_body("", CALENDLY_FR_HTML)
        assert meta is not None
        assert meta["kind"] == "appointment"
        assert meta["provider"] == "calendly"

    def test_extracts_reschedule_and_cancel_links(self):
        meta = extract_appointment_from_body("", CALENDLY_FR_HTML)
        assert meta["reschedule_url"] == (
            "https://calendly.com/reschedulings/d334b94a-9496-4c36-8807-61a7a15b368d"
        )
        assert meta["cancel_url"] == (
            "https://calendly.com/cancellations/d334b94a-9496-4c36-8807-61a7a15b368d"
        )

    def test_parses_french_datetime(self):
        meta = extract_appointment_from_body("", CALENDLY_FR_HTML)
        # 15:00 → 16:30 on 2026-06-17, naive (timezone carried in tz_label).
        assert meta["dtstart"] == "2026-06-17T15:00:00"
        assert meta["dtend"] == "2026-06-17T16:30:00"

    def test_captures_timezone_label(self):
        meta = extract_appointment_from_body("", CALENDLY_FR_HTML)
        assert meta["tz_label"] == "Heure de l'Est - Toronto"

    def test_extracts_physical_location(self):
        meta = extract_appointment_from_body("", CALENDLY_FR_HTML)
        assert meta["location"] == "10 rue Principale Nord, Sutton, J0E 2K0"

    def test_extracts_service_title(self):
        meta = extract_appointment_from_body("", CALENDLY_FR_HTML)
        assert meta["summary"] == "PULSA | Madérothérapie 90 min"


class TestCalendlyEnglishConfirmation:
    EN_HTML = """
      <div>Consultation | Discovery call 30 min</div>
      <div>Powered by Calendly</div>
      <div>When</div>
      <div>Wednesday, June 17, 2026 3:00 – 3:30pm (Eastern Time - US & Canada)</div>
      <div>Reschedule: https://calendly.com/reschedule/abc-123-def</div>
      <div>Cancel: https://calendly.com/cancellations/abc-123-def</div>
    """

    def test_parses_english_mdy_and_12h(self):
        meta = extract_appointment_from_body("", self.EN_HTML)
        assert meta is not None
        # 3:00 – 3:30pm → 15:00 – 15:30 (lone pm marker applies to both sides).
        assert meta["dtstart"] == "2026-06-17T15:00:00"
        assert meta["dtend"] == "2026-06-17T15:30:00"

    def test_handles_singular_reschedule_path(self):
        meta = extract_appointment_from_body("", self.EN_HTML)
        # "/reschedule/" (singular) also matches the /reschedulings?/ pattern.
        assert meta["reschedule_url"].endswith("/reschedule/abc-123-def")


class TestNegativeCases:
    def test_non_calendly_returns_none(self):
        assert extract_appointment_from_body("Just a normal email about lunch.") is None

    def test_calendly_footer_mention_without_action_returns_none(self):
        # A passing mention with no date and no reschedule/cancel link must not
        # render an empty appointment card.
        html = "<p>We use calendly.com for scheduling. Reply to book.</p>"
        assert extract_appointment_from_body("", html) is None

    def test_date_without_time_yields_no_dtstart(self):
        html = (
            "<p>Powered by Calendly</p>"
            "<p>Reschedule: https://calendly.com/reschedulings/xyz</p>"
            "<p>When: Wednesday, June 17, 2026</p>"
        )
        meta = extract_appointment_from_body("", html)
        # Still an appointment (has a reschedule link) but no dtstart.
        assert meta is not None
        assert meta["dtstart"] is None
        assert meta["reschedule_url"].endswith("/reschedulings/xyz")


class TestExtractMeetingIntegration:
    def test_extract_meeting_from_body_falls_through_to_appointment(self):
        meta = extract_meeting_from_body("", CALENDLY_FR_HTML)
        assert meta is not None
        assert meta["kind"] == "appointment"
        assert meta["dtstart"] == "2026-06-17T15:00:00"

    def test_ical_still_returns_invite_kind(self):
        ical = (
            "BEGIN:VCALENDAR\r\n"
            "METHOD:REQUEST\r\n"
            "BEGIN:VEVENT\r\n"
            "UID:abc@example.com\r\n"
            "SUMMARY:Project sync\r\n"
            "DTSTART:20260617T150000Z\r\n"
            "DTEND:20260617T153000Z\r\n"
            "LOCATION:meet.google.com/abc\r\n"
            "ORGANIZER:mailto:boss@acme.com\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        meta = extract_meeting_from_body(ical)
        assert meta is not None
        assert meta["kind"] == "invite"
        assert meta["summary"] == "Project sync"
        assert meta["organizer"] == "boss@acme.com"

    def test_plain_email_returns_none(self):
        assert extract_meeting_from_body("Hi, are we still on for lunch?") is None


class TestInviteTimezone:
    """Regression: a UTC/TZID invite must serialize a tz-aware dtstart so the FE
    renders the correct instant (previously the 'Z' was stripped and the naive
    clock number shown, off by the user's UTC offset; the free/busy badge was
    likewise computed against the wrong time)."""

    def _ical(self, dtstart: str, dtend: str) -> str:
        return (
            "BEGIN:VCALENDAR\r\n"
            "METHOD:REQUEST\r\n"
            "BEGIN:VEVENT\r\n"
            "UID:tz@example.com\r\n"
            "SUMMARY:Project sync\r\n"
            f"DTSTART:{dtstart}\r\n"
            f"DTEND:{dtend}\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )

    def test_utc_dtstart_serializes_with_offset(self):
        meta = extract_meeting_from_body(
            self._ical("20260617T150000Z", "20260617T153000Z")
        )
        assert meta is not None and meta["kind"] == "invite"
        # tz-aware ISO: either '+00:00' or 'Z'-style offset, never a bare naive string.
        assert meta["dtstart"] in ("2026-06-17T15:00:00+00:00", "2026-06-17T15:00:00Z")
        assert meta["dtstart"].endswith(("+00:00", "Z"))
        assert meta["dtend"].endswith(("+00:00", "Z"))

    def test_tzid_param_localizes_dtstart(self):
        ical = (
            "BEGIN:VCALENDAR\r\n"
            "BEGIN:VEVENT\r\n"
            "UID:tzid@example.com\r\n"
            "SUMMARY:NY meeting\r\n"
            "DTSTART;TZID=America/New_York:20260617T110000\r\n"
            "DTEND;TZID=America/New_York:20260617T113000\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        meta = extract_meeting_from_body(ical)
        assert meta is not None
        # 11:00 in America/New_York on 2026-06-17 is EDT (-04:00).
        assert "-04:00" in meta["dtstart"]
        assert meta["dtstart"].startswith("2026-06-17T11:00:00")

    def test_all_day_dtstart_stays_naive_local_date(self):
        ical = (
            "BEGIN:VCALENDAR\r\n"
            "BEGIN:VEVENT\r\n"
            "UID:allday@example.com\r\n"
            "SUMMARY:Holiday\r\n"
            "DTSTART;VALUE=DATE:20260617\r\n"
            "DTEND;VALUE=DATE:20260618\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        meta = extract_meeting_from_body(ical)
        assert meta is not None
        # No offset: the FE must read an all-day date as a local calendar date,
        # not a UTC instant that would shift west-of-UTC users back a day.
        assert meta["dtstart"] == "2026-06-17T00:00:00"
        assert "+" not in meta["dtstart"] and not meta["dtstart"].endswith("Z")

    # --- untrusted-input audit 2026-06-02: non-IANA TZID forms -------------
    # ZoneInfo only accepts canonical IANA names; the old _dt swallowed every
    # other form and degraded the invite to floating local time (wrong instant,
    # also RSVP-written back to Google Cal). _resolve_tzid now handles them.

    def test_windows_tzid_localizes_dtstart(self):
        """Outlook/Exchange emit Windows display names (e.g. 'Eastern Standard
        Time'), not IANA — a very large share of real invites."""
        ical = (
            "BEGIN:VCALENDAR\r\n"
            "BEGIN:VEVENT\r\n"
            "UID:wintz@example.com\r\n"
            "SUMMARY:NY meeting\r\n"
            "DTSTART;TZID=Eastern Standard Time:20260617T110000\r\n"
            "DTEND;TZID=Eastern Standard Time:20260617T113000\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        meta = extract_meeting_from_body(ical)
        assert meta is not None
        # 2026-06-17 is EDT (-04:00) in America/New_York.
        assert meta["dtstart"].startswith("2026-06-17T11:00:00")
        assert "-04:00" in meta["dtstart"]
        assert "-04:00" in meta["dtend"]

    def test_quoted_tzid_localizes_dtstart(self):
        """RFC 5545 permits a DQUOTE-quoted TZID param value."""
        ical = (
            "BEGIN:VCALENDAR\r\n"
            "BEGIN:VEVENT\r\n"
            "UID:qtz@example.com\r\n"
            "SUMMARY:Paris meeting\r\n"
            'DTSTART;TZID="Europe/Paris":20260617T110000\r\n'
            'DTEND;TZID="Europe/Paris":20260617T113000\r\n'
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        meta = extract_meeting_from_body(ical)
        assert meta is not None
        # Paris is CEST (+02:00) in June.
        assert meta["dtstart"].startswith("2026-06-17T11:00:00")
        assert "+02:00" in meta["dtstart"]

    def test_lowercase_iana_tzid_localizes_dtstart(self):
        """Non-canonical casing must still resolve (ZoneInfo is case-sensitive)."""
        ical = (
            "BEGIN:VCALENDAR\r\n"
            "BEGIN:VEVENT\r\n"
            "UID:lctz@example.com\r\n"
            "SUMMARY:Paris meeting\r\n"
            "DTSTART;TZID=europe/paris:20260617T110000\r\n"
            "DTEND;TZID=europe/paris:20260617T113000\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        meta = extract_meeting_from_body(ical)
        assert meta is not None
        assert meta["dtstart"].startswith("2026-06-17T11:00:00")
        assert "+02:00" in meta["dtstart"]

    def test_unknown_tzid_falls_back_to_naive_without_crashing(self):
        """A genuinely unresolvable TZID must degrade to naive local, not raise."""
        ical = (
            "BEGIN:VCALENDAR\r\n"
            "BEGIN:VEVENT\r\n"
            "UID:badtz@example.com\r\n"
            "SUMMARY:x\r\n"
            "DTSTART;TZID=Totally/Bogus:20260617T110000\r\n"
            "DTEND;TZID=Totally/Bogus:20260617T113000\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        meta = extract_meeting_from_body(ical)
        assert meta is not None
        assert meta["dtstart"] == "2026-06-17T11:00:00"  # naive, no offset
