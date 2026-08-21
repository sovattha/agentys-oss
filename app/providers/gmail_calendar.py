# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Adaptateur Google Calendar.

Implémente l'interface CalendarProvider pour Google Calendar API.
Réutilise les tokens OAuth des comptes Gmail existants.
"""

import base64
import html as _html
import json
import os
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional

try:  # zoneinfo ships with the stdlib on 3.9+; guard so a missing tzdata never crashes parsing
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment, misc]

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.interfaces.calendar_provider import (
    CalendarProvider,
    Calendar,
    CalendarEvent,
    CalendarScopeError,
    CalendarEventPermissionError,
    normalize_organizer,
)


# Google 403 ``reason`` values that genuinely mean the OAuth token lacks the
# required scope — re-auth fixes these. Everything else returned on a calendar
# WRITE op (``forbiddenForNonOrganizer``, read-only calendar, …) is an
# event-level permission issue that re-auth does NOT fix. Compared
# case-insensitively. See audit 2026-05-27.
_SCOPE_403_REASONS = frozenset({
    "insufficientpermissions",
    "access_token_scope_insufficient",
    "insufficientscope",
})


def _extract_403_reason(http_error) -> str:
    """Best-effort extract of Google's 403 ``reason`` (e.g.
    'forbiddenForNonOrganizer', 'insufficientPermissions') from an HttpError.

    Returns '' when the body is absent or unparseable — callers treat an
    unknown reason as a permission issue (the safe default for a write op).
    """
    try:
        raw = getattr(http_error, "content", b"") or b""
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        data = json.loads(raw) if raw else {}
        errors = ((data.get("error") or {}).get("errors")) or []
        if errors and isinstance(errors[0], dict):
            return str(errors[0].get("reason") or "").strip()
    except Exception:
        pass
    return ""


def _is_scope_403_reason(reason: str) -> bool:
    """True iff a 403 ``reason`` indicates a missing/insufficient OAuth scope."""
    return (reason or "").strip().lower() in _SCOPE_403_REASONS


def _raise_for_calendar_write_403(http_error, account_id: str) -> None:
    """Map a 403 on a calendar WRITE op (create/update/delete) to the right
    exception and raise it.

    Scope reason → :class:`CalendarScopeError` (the FE shows a reconnect
    banner). Anything else — non-organizer, read-only calendar, unknown —
    → :class:`CalendarEventPermissionError` (the FE shows "you can't edit this
    event"; re-auth would not help). Always raises.
    """
    reason = _extract_403_reason(http_error)
    if _is_scope_403_reason(reason):
        raise CalendarScopeError(account_id=account_id or "", provider="gmail")
    raise CalendarEventPermissionError(
        account_id=account_id or "", provider="gmail", reason=reason
    )

logger = logging.getLogger(__name__)


_ICAL_MIME_TYPES = frozenset({
    "text/calendar",
    "application/ics",
    "application/octet-stream",  # some mail clients use generic type for .ics
})


def _is_ical_part(part: dict) -> bool:
    """True if this MIME part is (or could be) an iCalendar file."""
    mime = part.get("mimeType", "").lower()
    if "calendar" in mime or mime in _ICAL_MIME_TYPES:
        return True
    filename = (part.get("filename") or "").lower()
    return filename.endswith(".ics")


def _decode_ical_part(part: dict, gmail_svc, message_id: str) -> Optional[str]:
    """Decode the body of a MIME part.  Falls back to attachments.get for large parts."""
    body = part.get("body", {})
    data = body.get("data")
    if data:
        try:
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
        except Exception:
            return None
    # Attachment stored separately (> ~2 MB or mail client didn't embed inline)
    att_id = body.get("attachmentId")
    if att_id and gmail_svc and message_id:
        try:
            att = gmail_svc.users().messages().attachments().get(
                userId="me", messageId=message_id, id=att_id
            ).execute()
            raw = att.get("data", "")
            if raw:
                return base64.urlsafe_b64decode(raw + "==").decode("utf-8", errors="replace")
        except Exception:
            pass
    return None


def _find_ical_text(payload: dict, gmail_svc, message_id: str) -> Optional[str]:
    """Recursively search MIME parts for iCal content.  Returns decoded text or None."""
    if _is_ical_part(payload):
        text = _decode_ical_part(payload, gmail_svc, message_id)
        if text and "BEGIN:VCALENDAR" in text:
            return text
    for part in payload.get("parts", []):
        text = _find_ical_text(part, gmail_svc, message_id)
        if text:
            return text
    return None


def _parse_ical_field(ical_text: str, field: str) -> Optional[str]:
    """Extract a simple (non-multi-line) iCal field value, handling folded lines."""
    # Unfold folded lines (CRLF + space/tab)
    unfolded = re.sub(r"\r?\n[ \t]", "", ical_text)
    match = re.search(rf"^{re.escape(field)}(?:;[^:]*)?:(.+)$", unfolded, re.MULTILINE | re.IGNORECASE)
    return match.group(1).strip() if match else None


# --- iCal TZID resolution ---------------------------------------------------
# ``zoneinfo.ZoneInfo`` only accepts canonical IANA names, but real .ics invites
# also carry: (a) Windows display names — Outlook/Exchange emit these by default
# (e.g. "Eastern Standard Time"); (b) RFC 5545 DQUOTE-quoted values
# (``TZID="Europe/Paris"``); (c) non-canonical casing (``europe/paris``). Each of
# those raised inside ``_dt``'s ``try/except`` and silently degraded the invite to
# floating local time, so the meeting rendered (and was RSVP-written back to the
# provider) at the WRONG instant. ``_resolve_tzid`` handles all three.
#
# NB: we deliberately do NOT use ``dateutil.tz.gettz`` for Windows names — it
# resolves them via the registry on Windows but NOT on Linux, so it would pass on
# a dev box and silently fail in (Linux) production.
#
# CLDR ``windowsZones.xml`` subset (territory "001" defaults), covering the zones
# seen in real invites for an FR/EU + US user base. Extend as needed.
_WINDOWS_TZ_TO_IANA = {
    "utc": "UTC",
    "gmt standard time": "Europe/London",
    "greenwich standard time": "Atlantic/Reykjavik",
    "w. europe standard time": "Europe/Berlin",
    "central europe standard time": "Europe/Budapest",
    "central european standard time": "Europe/Warsaw",
    "romance standard time": "Europe/Paris",
    "e. europe standard time": "Europe/Chisinau",
    "gtb standard time": "Europe/Bucharest",
    "russian standard time": "Europe/Moscow",
    "turkey standard time": "Europe/Istanbul",
    "eastern standard time": "America/New_York",
    "central standard time": "America/Chicago",
    "mountain standard time": "America/Denver",
    "pacific standard time": "America/Los_Angeles",
    "us eastern standard time": "America/Indiana/Indianapolis",
    "us mountain standard time": "America/Phoenix",
    "atlantic standard time": "America/Halifax",
    "alaskan standard time": "America/Anchorage",
    "hawaiian standard time": "Pacific/Honolulu",
    "eastern standard time (mexico)": "America/Cancun",
    "central standard time (mexico)": "America/Mexico_City",
    "mountain standard time (mexico)": "America/Chihuahua",
    "pacific standard time (mexico)": "America/Tijuana",
    "sa pacific standard time": "America/Bogota",
    "argentina standard time": "America/Argentina/Buenos_Aires",
    "e. south america standard time": "America/Sao_Paulo",
    "tokyo standard time": "Asia/Tokyo",
    "china standard time": "Asia/Shanghai",
    "singapore standard time": "Asia/Singapore",
    "korea standard time": "Asia/Seoul",
    "india standard time": "Asia/Kolkata",
    "israel standard time": "Asia/Jerusalem",
    "arabian standard time": "Asia/Dubai",
    "w. central africa standard time": "Africa/Lagos",
    "south africa standard time": "Africa/Johannesburg",
    "aus eastern standard time": "Australia/Sydney",
    "new zealand standard time": "Pacific/Auckland",
}

# Lazily-built lowercase IANA name -> canonical name, for case-insensitive match.
_IANA_LOWER_TO_CANONICAL: dict = {}


def _resolve_tzid(raw_tzid: Optional[str]):
    """Best-effort map an iCal ``TZID`` parameter value to a ``tzinfo``.

    Handles canonical IANA, RFC 5545 DQUOTE-quoted values, Windows display names
    (Outlook/Exchange) and non-canonical casing. Returns a ``ZoneInfo`` or
    ``None`` when nothing matches (caller then falls back to floating local time).
    """
    if not raw_tzid or ZoneInfo is None:
        return None
    name = raw_tzid.strip().strip('"').strip("'").strip()
    if not name:
        return None
    # 1) canonical IANA (fast path — the conformant case)
    try:
        return ZoneInfo(name)
    except Exception:
        pass
    # 2) Windows display name -> IANA (Outlook/Exchange default emission)
    iana = _WINDOWS_TZ_TO_IANA.get(name.lower())
    if iana:
        try:
            return ZoneInfo(iana)
        except Exception:
            return None
    # 3) case-insensitive IANA match (e.g. "europe/paris")
    if not _IANA_LOWER_TO_CANONICAL:
        try:
            from zoneinfo import available_timezones

            for z in available_timezones():
                _IANA_LOWER_TO_CANONICAL[z.lower()] = z
        except Exception:
            pass
    canon = _IANA_LOWER_TO_CANONICAL.get(name.lower())
    if canon:
        try:
            return ZoneInfo(canon)
        except Exception:
            return None
    return None


def _parse_vevent(ical_text: str) -> Optional[dict]:
    """Extract core fields from the first VEVENT block."""
    m = re.search(r"BEGIN:VEVENT(.+?)END:VEVENT", ical_text, re.DOTALL)
    if not m:
        return None
    vevent = m.group(1)
    unfolded = re.sub(r"\r?\n[ \t]", "", vevent)

    def _field(name: str) -> Optional[str]:
        hit = re.search(rf"^{re.escape(name)}(?:;[^:]*)?:(.+)$", unfolded, re.MULTILINE | re.IGNORECASE)
        return hit.group(1).strip() if hit else None

    def _field_with_params(name: str):
        """Return (value, params) for an iCal property, e.g. DTSTART;TZID=...:value."""
        hit = re.search(rf"^{re.escape(name)}(;[^:]*)?:(.+)$", unfolded, re.MULTILINE | re.IGNORECASE)
        if not hit:
            return None, ""
        return hit.group(2).strip(), (hit.group(1) or "")

    def _dt(raw: Optional[str], params: str = "") -> Optional[datetime]:
        """Parse an iCal DATE/DATE-TIME into a (tz-aware where possible) datetime.

        Critically preserves the timezone so the FE renders the correct instant:
        - trailing ``Z`` -> UTC-aware (isoformat emits ``+00:00``);
        - ``;TZID=Area/City`` param -> localized via zoneinfo;
        - bare date (all-day) -> naive, so the FE reads it as a local calendar date.
        Previously the ``Z`` was stripped and the value returned naive, so a
        UTC invite displayed at the raw clock number (off by the user's offset).
        """
        if not raw:
            return None
        raw = raw.strip()
        is_utc = raw.endswith("Z")
        if is_utc:
            raw = raw[:-1]
        for fmt in ("%Y%m%dT%H%M%S", "%Y%m%d"):
            try:
                dt = datetime.strptime(raw, fmt)
            except ValueError:
                continue
            if fmt == "%Y%m%d":
                # All-day / date-only: keep naive (a local calendar date, not an instant).
                return dt
            if is_utc:
                return dt.replace(tzinfo=timezone.utc)
            tzid = re.search(r"TZID=([^;:]+)", params or "", re.IGNORECASE)
            if tzid:
                resolved = _resolve_tzid(tzid.group(1))
                if resolved is not None:
                    return dt.replace(tzinfo=resolved)
            return dt  # no/unknown TZID -> floating local time (best effort)
        return None

    _dtstart_v, _dtstart_p = _field_with_params("DTSTART")
    _dtend_v, _dtend_p = _field_with_params("DTEND")

    return {
        "uid": _field("UID"),
        "summary": _field("SUMMARY") or "(Sans titre)",
        "dtstart": _dt(_dtstart_v, _dtstart_p),
        "dtend": _dt(_dtend_v, _dtend_p),
        "location": _field("LOCATION") or "",
        "description": _field("DESCRIPTION") or "",
        "organizer": re.sub(r"^mailto:", "", _field("ORGANIZER") or "", flags=re.IGNORECASE),
    }


def extract_meeting_from_body(
    body_text: str, body_html: str = "", subject: Optional[str] = None
) -> Optional[dict]:
    """Return a serialisable meeting dict for a calendar email, else None.

    Two sources, in priority order:

    1. **iCal** (``BEGIN:VCALENDAR``) — a standard meeting *invitation* with a
       ``METHOD:REQUEST`` you can RSVP to. Returns ``kind="invite"`` so the
       UI shows Accept / Maybe / Decline.
    2. **Booking-tool confirmation** (Calendly & friends) — the appointment is
       already booked; the email is human-readable HTML, not iCal. Returns
       ``kind="appointment"`` with reschedule/cancel deep-links so the UI shows
       Add-to-calendar / Reschedule / Cancel instead of an RSVP it can't honour.

    All datetimes are ISO-8601 strings so the result is JSON-serialisable.
    """
    combined = (body_text or "") + "\n" + (body_html or "")
    if "BEGIN:VCALENDAR" in combined.upper():
        m = re.search(r"BEGIN:VCALENDAR.*?END:VCALENDAR", combined, re.DOTALL | re.IGNORECASE)
        if m:
            vevent = _parse_vevent(m.group(0))
            if vevent:
                return {
                    "summary": vevent.get("summary") or "",
                    "dtstart": vevent["dtstart"].isoformat() if vevent.get("dtstart") else None,
                    "dtend": vevent["dtend"].isoformat() if vevent.get("dtend") else None,
                    "location": vevent.get("location") or "",
                    "organizer": vevent.get("organizer") or "",
                    "kind": "invite",
                }
    # No parseable iCal — fall through to a booking-tool confirmation.
    return extract_appointment_from_body(body_text, body_html, subject)


# ---------------------------------------------------------------------------
# Booking-tool confirmation parsing (Calendly, etc.)
#
# These emails are NOT iCal. They render the appointment as styled HTML
# ("Quand : mercredi 17 juin 2026 · 15:00 — 16:30", reschedule/cancel links).
# Gmail/Outlook never show an Accept/Decline badge here either — it's a
# confirmation of a slot the user already picked, not an RSVP request. So we
# surface the actions the email itself offers: add-to-calendar / reschedule /
# cancel.
# ---------------------------------------------------------------------------

# Month names across the locales Agentys ships (en / fr / es), plus common
# abbreviations. Accent-stripped variants included so mangled UTF-8 still maps.
_APPT_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "août": 8, "aout": 8, "septembre": 9, "octobre": 10,
    "novembre": 11, "décembre": 12, "decembre": 12,
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}
_APPT_MONTH_ALT = "|".join(sorted((re.escape(m) for m in _APPT_MONTHS), key=len, reverse=True))
# Day-Month-Year (fr/es: "17 juin 2026", "17 de junio de 2026")
_APPT_DATE_DMY = re.compile(
    rf"(\d{{1,2}})\s+(?:de\s+)?({_APPT_MONTH_ALT})\.?\s+(?:de\s+|del\s+)?(\d{{4}})", re.IGNORECASE
)
# Month-Day-Year (en: "June 17, 2026")
_APPT_DATE_MDY = re.compile(
    rf"({_APPT_MONTH_ALT})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})", re.IGNORECASE
)
_APPT_TIME_RANGE = re.compile(
    r"(\d{1,2})[:h](\d{2})\s*([ap]\.?\s?m\.?)?\s*(?:[-–—]|to|à|hasta|until)\s*"
    r"(\d{1,2})[:h](\d{2})\s*([ap]\.?\s?m\.?)?",
    re.IGNORECASE,
)
_APPT_TIME_SINGLE = re.compile(r"(\d{1,2})[:h](\d{2})\s*([ap]\.?\s?m\.?)?", re.IGNORECASE)
_TZ_KEYWORDS = re.compile(
    r"(time|heure|hora|gmt|utc|est\b|edt|cst|cdt|mst|mdt|pst|pdt|cet|cest|"
    r"toronto|montr[eé]al|new\s*york|paris|madrid|london)",
    re.IGNORECASE,
)


def _appt_to_24h(hour: str, minute: str, ampm: Optional[str]):
    h, m = int(hour), int(minute)
    if ampm:
        a = ampm.lower().replace(".", "").replace(" ", "")
        if a == "pm" and h != 12:
            h += 12
        elif a == "am" and h == 12:
            h = 0
    return h, m


def _appt_html_to_text(raw: str) -> str:
    """Strip HTML to newline-preserving plain text for human-date scanning."""
    if not raw:
        return ""
    txt = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.DOTALL | re.IGNORECASE)
    # Block-level tags → newline so "Lieu: …" / "Quand: …" keep their own line.
    txt = re.sub(r"(?i)<\s*(br|/p|/div|/tr|/li|/h[1-6]|/td)\s*/?>", "\n", txt)
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = _html.unescape(txt)
    txt = txt.replace("\xa0", " ")
    # Collapse spaces/tabs but keep newlines.
    txt = re.sub(r"[ \t]+", " ", txt)
    txt = re.sub(r"\n\s*\n+", "\n", txt)
    return txt.strip()


def _appt_first_url(combined: str, frag: str) -> Optional[str]:
    m = re.search(rf"https?://[^\s\"'<>]*{frag}[^\s\"'<>]+", combined, re.IGNORECASE)
    if not m:
        return None
    url = _html.unescape(m.group(0))
    # Trim trailing punctuation that commonly clings to inline links.
    return url.rstrip(").,;'\"")


def _appt_parse_when(text: str) -> dict:
    """Best-effort parse of the human 'When'/'Quand' line into naive datetimes.

    Returns floating (timezone-naive) ISO strings — the appointment is in the
    timezone the email states (carried separately in ``tz_label``), and for the
    common case the viewer is in that same zone. Returns ``{}`` on no match.
    """
    year = month = day = None
    md = _APPT_DATE_DMY.search(text)
    if md:
        day, month, year = int(md.group(1)), _APPT_MONTHS[md.group(2).lower().rstrip(".")], int(md.group(3))
    else:
        md = _APPT_DATE_MDY.search(text)
        if md:
            month, day, year = _APPT_MONTHS[md.group(1).lower().rstrip(".")], int(md.group(2)), int(md.group(3))
    if not (year and month and day):
        return {}

    sh = sm = eh = em = None
    tr = _APPT_TIME_RANGE.search(text)
    if tr:
        a1, a2 = tr.group(3), tr.group(6)
        # "3:00 – 4:30pm": the lone am/pm marker applies to both sides.
        a1 = a1 or a2
        a2 = a2 or a1
        sh, sm = _appt_to_24h(tr.group(1), tr.group(2), a1)
        eh, em = _appt_to_24h(tr.group(4), tr.group(5), a2)
    else:
        ts = _APPT_TIME_SINGLE.search(text)
        if ts:
            sh, sm = _appt_to_24h(ts.group(1), ts.group(2), ts.group(3))
    if sh is None:
        return {}  # a date with no time isn't useful for a calendar event

    try:
        start = datetime(year, month, day, sh, sm)
    except ValueError:
        return {}
    end = None
    if eh is not None:
        try:
            end = datetime(year, month, day, eh, em)
            if end <= start:
                end = end + timedelta(days=1)  # crosses midnight
        except ValueError:
            end = None

    tz_label = None
    for cand in re.findall(r"\(([^)]{2,40})\)", text):
        if _TZ_KEYWORDS.search(cand):
            tz_label = cand.strip()
            break

    return {
        "dtstart": start.isoformat(),
        "dtend": end.isoformat() if end else None,
        "tz_label": tz_label,
    }


def _appt_extract_location(text: str) -> str:
    m = re.search(
        r"(?im)^\s*(?:emplacement|location|lieu|ubicaci[oó]n|o[uù]|d[oó]nde)\s*[:：]\s*(.+)$",
        text,
    )
    if not m:
        return ""
    loc = m.group(1).strip()
    # Skip when the "location" is actually a video link (handled as a link, not
    # a physical address) or boilerplate.
    if loc.lower().startswith(("http", "powered by", "alimenté", "alimente")):
        return ""
    return loc[:140]


def _appt_extract_title(text: str) -> str:
    """Pull a service-booking event name like 'PULSA | Madérothérapie 90 min'."""
    for line in text.split("\n"):
        line = line.strip()
        if not line or len(line) > 120:
            continue
        if "|" in line and re.search(
            r"\b\d+\s*(?:min|minutes?|mins?|heures?|hours?|hrs?|h)\b", line, re.IGNORECASE
        ):
            # Trim a trailing price / decorative separator ("✧ 160$").
            line = re.sub(r"\s*[✧✦●•·|–—-]*\s*\$?\s*\d[\d.,]*\s*\$?\s*$", "", line).strip()
            return line[:100]
    return ""


def extract_appointment_from_body(
    body_text: str, body_html: str = "", subject: Optional[str] = None
) -> Optional[dict]:
    """Parse a booking-tool confirmation (Calendly) into a meeting_meta dict.

    Returns ``None`` for anything that isn't recognisably a Calendly
    confirmation — the detection gate is a cheap substring check so this is
    safe to call on every non-iCal email.
    """
    combined = (body_text or "") + "\n" + (body_html or "")
    low = combined.lower()
    if (
        "calendly.com" not in low
        and "powered by calendly" not in low
        and "alimenté par calendly" not in low
        and "alimente par calendly" not in low
    ):
        return None

    text = _appt_html_to_text(combined)
    when = _appt_parse_when(text)
    reschedule_url = _appt_first_url(combined, r"calendly\.com/reschedul(?:ings?|e)/")
    cancel_url = _appt_first_url(combined, r"calendly\.com/cancellations?/")

    # Require at least one actionable signal so we don't render an empty card
    # for a passing "calendly.com" footer mention.
    if not (when.get("dtstart") or reschedule_url or cancel_url):
        return None

    return {
        "summary": _appt_extract_title(text),
        "dtstart": when.get("dtstart"),
        "dtend": when.get("dtend"),
        "location": _appt_extract_location(text),
        "organizer": "",
        "kind": "appointment",
        "provider": "calendly",
        "reschedule_url": reschedule_url,
        "cancel_url": cancel_url,
        "tz_label": when.get("tz_label"),
    }


class GmailCalendarAdapter(CalendarProvider):
    """
    Adaptateur Google Calendar via Google Calendar API.

    Réutilise les tokens OAuth des comptes Gmail pour accéder au calendrier.
    Les scopes calendrier doivent être demandés lors de l'authentification OAuth initiale.

    Variables d'environnement optionnelles:
    - GOOGLE_CLIENT_ID : Client ID pour le refresh token
    - GOOGLE_CLIENT_SECRET : Client Secret pour le refresh token
    """

    PROVIDER_NAME = "google_calendar"

    CALENDAR_SCOPES = [
        "https://www.googleapis.com/auth/calendar.readonly",
        "https://www.googleapis.com/auth/calendar.events",
    ]

    def __init__(
        self,
        account_id: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
    ):
        """
        Initialise l'adaptateur Google Calendar.

        Args:
            account_id: ID du compte pour tokens server-side (OAuth web).
            client_id: Google Client ID (pour refresh token).
            client_secret: Google Client Secret (pour refresh token).
        """
        self.account_id = account_id
        self.client_id = client_id or os.getenv("GOOGLE_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("GOOGLE_CLIENT_SECRET")

        self._credentials: Optional[Credentials] = None
        self._service = None
        self._authenticated = False

    @property
    def provider_name(self) -> str:
        return self.PROVIDER_NAME

    def _get_server_tokens(self) -> Optional[dict]:
        """
        Récupère les tokens depuis le stockage serveur.

        Returns:
            Token data dict ou None si non trouvé.
        """
        if not self.account_id:
            return None

        try:
            from app.api.oauth import get_tokens_server, _refresh_tokens_server
            import time

            token_data = get_tokens_server(self.account_id)
            if not token_data:
                return None

            # Auto-refresh si nécessaire (5 min buffer)
            expires_at = token_data.get("expires_at", 0)
            if time.time() > (expires_at - 5 * 60):
                logger.info(f"Token expirant pour {self.account_id}, rafraîchissement...")
                token_data = _refresh_tokens_server(self.account_id)
                if not token_data:
                    logger.warning(f"Échec du rafraîchissement pour {self.account_id}")
                    return None

            return token_data

        except Exception as e:
            logger.warning(f"Erreur récupération tokens serveur: {e}")
            return None

    def authenticate(self) -> bool:
        """
        Authentifie via Google OAuth2.

        Réutilise les tokens OAuth du compte Gmail associé.

        Returns:
            True si l'authentification réussit.
        """
        try:
            creds = None

            # Récupérer les tokens stockés côté serveur
            if self.account_id:
                server_tokens = self._get_server_tokens()
                if server_tokens:
                    access_token = server_tokens.get("access_token")
                    refresh_token = server_tokens.get("refresh_token")
                    if access_token:
                        creds = Credentials(
                            token=access_token,
                            refresh_token=refresh_token,
                            token_uri="https://oauth2.googleapis.com/token",
                            client_id=self.client_id,
                            client_secret=self.client_secret,
                            scopes=self.CALENDAR_SCOPES
                        )
                        logger.info(f"Tokens serveur chargés pour calendrier {self.account_id}")

            if not creds:
                logger.warning("Pas de tokens disponibles pour Google Calendar")
                return False

            # Rafraîchir si nécessaire
            if creds.refresh_token and (not creds.valid or creds.expired):
                creds.refresh(Request())

            self._credentials = creds
            self._service = build("calendar", "v3", credentials=creds)
            self._authenticated = True
            logger.info("[OK] Authentification Google Calendar réussie")
            return True

        except Exception as e:
            logger.error(f"[FAIL] Authentification Google Calendar échouée: {e}")
            self._authenticated = False
            return False

    def _ensure_authenticated(self) -> None:
        """S'assure que le service est authentifié."""
        if not self._authenticated or not self._service:
            if not self.authenticate():
                raise RuntimeError("Authentification Google Calendar requise")

    def _map_to_calendar(self, cal_data: dict) -> Calendar:
        """Convertit un calendrier Google en Calendar standard."""
        return Calendar(
            id=cal_data.get("id", ""),
            name=cal_data.get("summary", "Sans nom"),
            description=cal_data.get("description"),
            color=cal_data.get("backgroundColor"),
            is_primary=cal_data.get("primary", False),
            can_edit=cal_data.get("accessRole") in ["owner", "writer"],
            provider_source=self.PROVIDER_NAME,
        )

    def _parse_datetime(self, dt_data: dict) -> datetime:
        """Parse une date/heure depuis le format Google Calendar."""
        from dateutil import parser

        # Format date-only (événement journée entière)
        if "date" in dt_data:
            return parser.parse(dt_data["date"])

        # Format date-time
        if "dateTime" in dt_data:
            return parser.parse(dt_data["dateTime"])

        return datetime.now()

    def _map_to_event(self, event_data: dict, source_calendar_id: str = "primary") -> CalendarEvent:
        """Convertit un événement Google Calendar en CalendarEvent standard."""
        # Déterminer si c'est un événement journée entière
        is_all_day = "date" in event_data.get("start", {})

        # Parser les dates
        start = self._parse_datetime(event_data.get("start", {}))
        end = self._parse_datetime(event_data.get("end", {}))

        # Extraire les participants
        attendees = []
        for attendee in event_data.get("attendees", []):
            email = attendee.get("email")
            if email:
                attendees.append(email)

        # Extraire l'organisateur. Pour un calendrier secondaire/partagé, Google
        # renvoie l'id du calendrier (hash hex @group.calendar.google.com) comme
        # email — on lui préfère le displayName, sinon on masque (cf. bug 2026-06-01).
        org_obj = event_data.get("organizer") or {}
        organizer = normalize_organizer(org_obj.get("email"), org_obj.get("displayName"))

        # Déterminer le statut
        status = event_data.get("status", "confirmed")
        if status == "cancelled":
            status = "cancelled"
        elif event_data.get("transparency") == "transparent":
            status = "tentative"

        return CalendarEvent(
            id=event_data.get("id", ""),
            title=event_data.get("summary", "(Sans titre)"),
            start=start,
            end=end,
            is_all_day=is_all_day,
            location=event_data.get("location"),
            description=event_data.get("description"),
            attendees=attendees,
            # Was: organizer.email — broke filtering for accepted invitations
            # because the organizer is the inviter, not the user's calendar.
            # Use the calendar we actually fetched from instead.
            calendar_id=source_calendar_id,
            status=status,
            provider_source=self.PROVIDER_NAME,
            organizer=organizer,
            is_recurring=bool(event_data.get("recurrence")),
            recurrence_rule=event_data.get("recurrence", [None])[0] if event_data.get("recurrence") else None,
            html_link=event_data.get("htmlLink"),
            color=event_data.get("colorId"),
            meet_link=event_data.get("hangoutLink") or next(
                (ep.get("uri") for ep in event_data.get("conferenceData", {}).get("entryPoints", []) if ep.get("entryPointType") == "video"),
                None
            ),
            raw_metadata={
                "etag": event_data.get("etag"),
                "kind": event_data.get("kind"),
                "visibility": event_data.get("visibility"),
            }
        )

    def list_calendars(self) -> List[Calendar]:
        """
        Liste les calendriers de l'utilisateur.

        Returns:
            Liste des calendriers disponibles.
        """
        self._ensure_authenticated()

        try:
            result = self._service.calendarList().list().execute()
            calendars = result.get("items", [])

            return [self._map_to_calendar(cal) for cal in calendars]

        except HttpError as e:
            if e.resp.status == 403:
                logger.warning(f"Google Calendar 403 (list) for {self.account_id}: insufficient scopes")
                raise CalendarScopeError(account_id=self.account_id or "", provider="gmail")
            logger.error(f"Erreur API Google Calendar (list): {e}")
            return []

    def get_events(
        self,
        start: datetime,
        end: datetime,
        calendar_id: str = "primary",
        max_results: int = 100
    ) -> List[CalendarEvent]:
        """
        Récupère les événements dans une plage de dates.

        Args:
            start: Date/heure de début de la plage.
            end: Date/heure de fin de la plage.
            calendar_id: ID du calendrier (défaut: principal).
            max_results: Nombre maximum d'événements à récupérer.

        Returns:
            Liste d'événements normalisés.
        """
        self._ensure_authenticated()

        try:
            # Formater les dates en RFC 3339
            start_rfc = start.isoformat() + "Z" if not start.tzinfo else start.isoformat()
            end_rfc = end.isoformat() + "Z" if not end.tzinfo else end.isoformat()

            result = self._service.events().list(
                calendarId=calendar_id,
                timeMin=start_rfc,
                timeMax=end_rfc,
                maxResults=max_results,
                singleEvents=True,  # Expand recurring events
                orderBy="startTime"
            ).execute()

            events = result.get("items", [])
            logger.info(f"Google Calendar: {len(events)} événements trouvés")

            return [self._map_to_event(event, source_calendar_id=calendar_id) for event in events]

        except HttpError as e:
            if e.resp.status == 403:
                logger.warning(f"Google Calendar 403 (events) for {self.account_id}: insufficient scopes")
                raise CalendarScopeError(account_id=self.account_id or "", provider="gmail")
            logger.error(f"Erreur API Google Calendar (events): {e}")
            return []

    def get_event_by_id(
        self,
        event_id: str,
        calendar_id: str = "primary"
    ) -> Optional[CalendarEvent]:
        """
        Récupère un événement spécifique par son ID.

        Args:
            event_id: Identifiant unique de l'événement.
            calendar_id: ID du calendrier.

        Returns:
            L'événement normalisé ou None si non trouvé.
        """
        self._ensure_authenticated()

        try:
            event = self._service.events().get(
                calendarId=calendar_id,
                eventId=event_id
            ).execute()

            return self._map_to_event(event, source_calendar_id=calendar_id)

        except HttpError as e:
            logger.error(f"Événement non trouvé: {event_id} - {e}")
            return None

    def _format_datetime(self, dt: datetime, all_day: bool = False) -> dict:
        """Formate une datetime pour l'API Google Calendar."""
        if all_day:
            return {"date": dt.strftime("%Y-%m-%d")}
        return {"dateTime": dt.isoformat(), "timeZone": "UTC"}

    def _build_event_body(self, event) -> dict:
        """Construit le body JSON pour l'API Google Calendar depuis un événement domaine."""
        # Support both DomainCalendarEvent (start_time/end_time/all_day)
        # and interface CalendarEvent (start/end/is_all_day)
        start_dt = getattr(event, "start_time", None) or getattr(event, "start", None)
        end_dt = getattr(event, "end_time", None) or getattr(event, "end", None)
        all_day = getattr(event, "all_day", None)
        if all_day is None:
            all_day = getattr(event, "is_all_day", False)

        body: dict = {
            "summary": event.title,
            "description": getattr(event, "description", "") or "",
            "location": getattr(event, "location", "") or "",
            "start": self._format_datetime(start_dt, all_day),
            "end": self._format_datetime(end_dt, all_day),
        }

        # attendees: None means "don't touch" (e.g. a drag/resize PATCH that omits
        # the field — _parse_event_body passes None so the key stays absent and
        # Google's events().update() PRESERVES the existing attendees). An explicit
        # [] means "clear all attendees": sending the empty list is what makes
        # Google drop them. (Omitting the key would silently keep them.)
        attendees = getattr(event, "attendees", None)
        if attendees is not None:
            body["attendees"] = [{"email": e} for e in attendees]

        reminders = getattr(event, "reminders", [])
        if reminders:
            body["reminders"] = {
                "useDefault": False,
                "overrides": [{"method": "popup", "minutes": m} for m in reminders],
            }

        recurrence = getattr(event, "recurrence", None)
        if recurrence:
            body["recurrence"] = [recurrence]

        # Label / project color. hexToGcalColorId on the FE already maps hex →
        # Google colorId "1".."11", so event.color arrives as a valid colorId
        # string. update_event reuses this builder, so the edit path is fixed too.
        color = getattr(event, "color", None)
        if color:
            body["colorId"] = str(color)

        return body

    def create_event(self, event, calendar_id: str = "primary"):
        """Crée un événement dans Google Calendar. Retourne dict avec event_id et meet_link, ou None."""
        self._ensure_authenticated()
        try:
            body = self._build_event_body(event)

            insert_kwargs: dict = {"calendarId": calendar_id, "body": body}

            # Add Google Meet conference link
            if getattr(event, "conference", False):
                import uuid as _uuid
                body["conferenceData"] = {
                    "createRequest": {
                        "requestId": str(_uuid.uuid4()),
                        "conferenceSolutionKey": {"type": "hangoutsMeet"},
                    }
                }
                insert_kwargs["conferenceDataVersion"] = 1

            created = self._service.events().insert(**insert_kwargs).execute()
            event_id = created.get("id")

            # Extract Google Meet link
            meet_link = created.get("hangoutLink")
            if not meet_link:
                for ep in created.get("conferenceData", {}).get("entryPoints", []):
                    if ep.get("entryPointType") == "video":
                        meet_link = ep.get("uri")
                        break

            logger.info(f"[GmailCalendar] Événement créé: {event_id}" + (f" | Meet: {meet_link}" if meet_link else ""))
            return {"event_id": event_id, "meet_link": meet_link}
        except HttpError as e:
            if e.resp.status == 403:
                raise CalendarScopeError(account_id=self.account_id or "", provider="gmail")
            logger.error(f"[GmailCalendar] Erreur création événement: {e}")
            return None

    def update_event(self, event, calendar_id: str = "primary") -> bool:
        """Met à jour un événement existant. Retourne True si succès."""
        self._ensure_authenticated()
        try:
            body = self._build_event_body(event)
            self._service.events().update(
                calendarId=calendar_id,
                eventId=event.id,
                body=body,
            ).execute()
            logger.info(f"[GmailCalendar] Événement mis à jour: {event.id}")
            return True
        except HttpError as e:
            if e.resp.status == 404:
                logger.warning(
                    "[GmailCalendar] 404 sur update event — eventId=%s calendarId=%s account=%s. "
                    "Cause probable: event sur un autre calendrier, event_id stale après resync, "
                    "ou tentative d'update sur calendrier read-only (Holidays).",
                    event.id, calendar_id, self.account_id,
                )
                return False
            if e.resp.status == 403:
                # Audit 2026-05-27: distinguish a genuine missing-scope 403 from
                # a non-organizer / read-only-calendar 403 (which re-auth cannot
                # fix) so a drag-drop move stops showing the misleading
                # "missing_calendar_scope". Raises CalendarScopeError or
                # CalendarEventPermissionError as appropriate.
                _raise_for_calendar_write_403(e, self.account_id or "")
            logger.error(f"[GmailCalendar] Erreur mise à jour événement: {e}")
            return False

    def delete_event(self, event_id: str, calendar_id: str = "primary") -> bool:
        """Supprime un événement. Retourne True si succès."""
        self._ensure_authenticated()
        try:
            self._service.events().delete(
                calendarId=calendar_id,
                eventId=event_id,
            ).execute()
            logger.info(f"[GmailCalendar] Événement supprimé: {event_id}")
            return True
        except HttpError as e:
            # Audit 2026-05-11 (P2): 410 Gone = already deleted upstream;
            # idempotently treat as success. 404 = never existed, also
            # success-shaped for delete semantics.
            if e.resp.status in (404, 410):
                logger.debug("[GmailCalendar] delete idempotent (status=%s)", e.resp.status)
                return True
            if e.resp.status == 403:
                raise CalendarScopeError(account_id=self.account_id or "", provider="gmail")
            logger.error(f"[GmailCalendar] Erreur suppression événement: {e}")
            return False

    def get_freebusy(
        self,
        attendees: List[str],
        start_time: datetime,
        end_time: datetime,
    ) -> dict:
        """Query Google FreeBusy API across the user's calendars + attendees.

        Mirrors GoogleCalendarAdapter.get_freebusy so the rsvp_meeting Quick
        Action can detect conflicts before auto-accepting an invitation.
        """
        self._ensure_authenticated()
        try:
            items: list[dict] = []
            seen: set[str] = set()
            try:
                cal_list = self._service.calendarList().list().execute()
                for cal in cal_list.get("items", []):
                    cal_id = cal.get("id", "")
                    if cal_id and cal_id not in seen:
                        items.append({"id": cal_id})
                        seen.add(cal_id)
            except HttpError as e:
                logger.warning(f"[FreeBusy] Cannot list calendars, falling back to primary: {e}")
                items = [{"id": "primary"}]
                seen = {"primary"}

            if "primary" not in seen:
                items.insert(0, {"id": "primary"})
                seen.add("primary")

            for email in attendees or []:
                if email not in seen:
                    items.append({"id": email})
                    seen.add(email)

            body = {
                "timeMin": start_time.isoformat(),
                "timeMax": end_time.isoformat(),
                "items": items,
            }
            result = self._service.freebusy().query(body=body).execute()
            calendars: dict[str, list] = {}
            for email, info in result.get("calendars", {}).items():
                busy = [
                    {"start": b["start"], "end": b["end"]}
                    for b in info.get("busy", [])
                ]
                calendars[email] = busy

            # FreeBusy silently omits transparent/declined events. If the user's
            # own calendars returned 0 blocks, fall back to events.list() on
            # primary to catch all opaque events.
            attendee_set = set(attendees or [])
            own_busy_count = sum(
                len(v) for k, v in calendars.items() if k not in attendee_set
            )
            if own_busy_count == 0:
                try:
                    ev_result = self._service.events().list(
                        calendarId="primary",
                        timeMin=body["timeMin"],
                        timeMax=body["timeMax"],
                        singleEvents=True,
                        orderBy="startTime",
                        maxResults=100,
                    ).execute()
                    fallback = []
                    for ev in ev_result.get("items", []):
                        if ev.get("transparency") == "transparent":
                            continue
                        if ev.get("status") == "cancelled":
                            continue
                        s = ev.get("start", {})
                        e = ev.get("end", {})
                        ev_start = s.get("dateTime") or s.get("date")
                        ev_end = e.get("dateTime") or e.get("date")
                        if ev_start and ev_end:
                            fallback.append({"start": ev_start, "end": ev_end})
                    if fallback:
                        calendars["__primary_fallback__"] = fallback
                except HttpError as fb_err:
                    logger.error(f"[FreeBusy] Fallback events.list() failed: {fb_err}")

            return {"calendars": calendars}
        except HttpError as e:
            logger.error(f"[GmailCalendar] FreeBusy error: {e}")
            return {"calendars": {}}

    def get_meeting_time_from_email(self, email_id: str) -> Optional[dict]:
        """Extract DTSTART / DTEND from the iCal data in a Gmail message.

        Returns {"dtstart": datetime, "dtend": datetime} or None.
        """
        self._ensure_authenticated()
        try:
            from googleapiclient.discovery import build as _build
            gmail_svc = _build("gmail", "v1", credentials=self._credentials, cache_discovery=False)
            msg = gmail_svc.users().messages().get(
                userId="me", id=email_id, format="full"
            ).execute()
            ical_text = _find_ical_text(msg.get("payload", {}), gmail_svc, email_id)
            if not ical_text:
                return None
            vevent = _parse_vevent(ical_text)
            if not vevent or not vevent.get("dtstart"):
                return None
            return {
                "dtstart": vevent["dtstart"],
                "dtend": vevent.get("dtend") or vevent["dtstart"],
            }
        except Exception as exc:
            logger.warning("[GmailCalendar] get_meeting_time_from_email failed: %s", exc)
            return None

    def rsvp_event(self, email_id: str, response: str) -> dict:
        """Accept, decline, or tentatively accept a meeting invitation.

        Flow:
        1. Fetch the Gmail message and extract the iCal data (.ics attachment or
           inline text/calendar MIME part).
        2. Look up the event in Google Calendar by iCal UID.
        3a. If found → patch the user's attendee responseStatus.
        3b. If not found (e.g. Teams invite to Gmail) → create the event from the
            iCal data so it appears in the calendar.

        Args:
            email_id: Gmail message ID.
            response: 'accepted' | 'declined' | 'tentative'

        Returns:
            dict with keys: ok (bool), event_id (str|None), error (str|None)
        """
        _VALID = {"accepted", "declined", "tentative"}
        if response not in _VALID:
            return {"ok": False, "error": "invalid_response"}

        self._ensure_authenticated()

        # Build Gmail API service from the same OAuth credentials.
        try:
            from googleapiclient.discovery import build as _build
            gmail_svc = _build("gmail", "v1", credentials=self._credentials, cache_discovery=False)
        except Exception as exc:
            logger.error("[GmailCalendar] rsvp: gmail service build failed: %s", exc)
            return {"ok": False, "error": "gmail_service_failed"}

        # Fetch full MIME message.
        try:
            msg = gmail_svc.users().messages().get(
                userId="me", id=email_id, format="full"
            ).execute()
        except Exception as exc:
            logger.error("[GmailCalendar] rsvp: message fetch failed: %s", exc)
            return {"ok": False, "error": "email_fetch_failed"}

        # Extract iCal text (handles text/calendar, application/ics, .ics attachments).
        ical_text = _find_ical_text(msg.get("payload", {}), gmail_svc, email_id)
        if not ical_text:
            logger.warning("[GmailCalendar] rsvp: no iCal data found in email %s", email_id)
            return {"ok": False, "error": "no_ical_uid"}

        vevent = _parse_vevent(ical_text)
        uid = vevent.get("uid") if vevent else None

        # Try to find an existing Calendar event by iCal UID.
        existing_event = None
        existing_id = None
        if uid:
            try:
                result = self._service.events().list(
                    calendarId="primary",
                    iCalUID=uid,
                    maxResults=1,
                ).execute()
                items = result.get("items", [])
                if items:
                    existing_event = items[0]
                    existing_id = existing_event["id"]
            except HttpError as exc:
                logger.warning("[GmailCalendar] rsvp: event lookup error (continuing): %s", exc)

        if existing_event and existing_id:
            # Event already in calendar — patch attendee response.
            try:
                attendees = existing_event.get("attendees", [])
                updated = [
                    {**att, "responseStatus": response} if att.get("self") else att
                    for att in attendees
                ]
                patch_body: dict = {"attendees": updated} if updated else {}
                self._service.events().patch(
                    calendarId="primary",
                    eventId=existing_id,
                    body=patch_body,
                    sendUpdates="all",
                ).execute()
                logger.info("[GmailCalendar] rsvp patch: %s → %s (event %s)", email_id, response, existing_id)
                return {"ok": True, "event_id": existing_id, "response": response}
            except HttpError as exc:
                if exc.resp.status == 403:
                    raise CalendarScopeError(account_id=self.account_id or "", provider="gmail")
                logger.error("[GmailCalendar] rsvp: patch failed: %s", exc)
                return {"ok": False, "error": "patch_failed"}

        # Event not in calendar yet (e.g. external Teams/Zoom invite).
        # Only create if user accepts or tentatively accepts.
        if response == "declined":
            # Nothing to add to calendar for a declined invite with no existing event.
            logger.info("[GmailCalendar] rsvp declined (no calendar event): %s", email_id)
            return {"ok": True, "event_id": None, "response": response}

        if not vevent or not vevent.get("dtstart"):
            return {"ok": False, "error": "ical_parse_failed"}

        try:
            event_body: dict = {
                "summary": vevent["summary"],
                "description": vevent.get("description", ""),
                "location": vevent.get("location", ""),
                "start": self._format_datetime(vevent["dtstart"]),
                "end": self._format_datetime(vevent["dtend"] or vevent["dtstart"]),
                "status": "confirmed",
            }
            if vevent.get("organizer"):
                event_body["organizer"] = {"email": vevent["organizer"]}
            if uid:
                event_body["iCalUID"] = uid

            created = self._service.events().insert(
                calendarId="primary",
                body=event_body,
                sendUpdates="none",
            ).execute()
            created_id = created.get("id")
            logger.info("[GmailCalendar] rsvp created event: %s (source email %s)", created_id, email_id)
            return {"ok": True, "event_id": created_id, "response": response}
        except HttpError as exc:
            if exc.resp.status == 403:
                raise CalendarScopeError(account_id=self.account_id or "", provider="gmail")
            logger.error("[GmailCalendar] rsvp: event create failed: %s", exc)
            return {"ok": False, "error": "create_failed"}
