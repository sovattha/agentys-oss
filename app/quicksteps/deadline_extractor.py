# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Regex-based deadline extraction from email body text.

Cheap, no-LLM pass that catches the common "due / by / expires / payment
due" phrasings most invoice / contract / scheduling emails use. Returns
a timezone-aware ``datetime`` in UTC or ``None`` when no candidate is
found. The email-ingest pipeline (``sync_service.SyncService``) calls
this on every received email and stamps ``emails.deadline_at`` so the
inbox row renders a clock chip and the ``has_deadline_detected`` Quick
Step trigger condition can fire downstream rules.

Design notes:
- We deliberately avoid sweeping every date that appears in an email
  (the "sent on Friday" false-positive). A date only counts when
  preceded by a deadline-marker phrase like "due", "expires", "by",
  "deadline", "payment due", "RSVP by".
- Both English and French markers, since the user base is FR/EN. Add
  ES/DE phrases when localized templates start showing in the corpus.
- We use ``dateutil.parser`` for the date text itself so "Mar 15",
  "March 15th, 2026", "03/15/2026" and "15/03/2026" all parse. The
  ``fuzzy_with_tokens`` mode is intentionally avoided — it accepts way
  more than we want.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from dateutil import parser as date_parser

logger = logging.getLogger(__name__)

# Marker phrases that flag the *next* date token as a deadline. Casefold-
# matched with a non-greedy capture for the date span. Order matters
# only marginally — the first successful match wins.
_DEADLINE_MARKERS = (
    # English. ``due`` accepts the most common prepositions PLUS the
    # Franglish form ``due pour le`` / ``due le`` that French SaaS
    # invoices routinely use ("Facture due pour le 31 mai 2026"). The
    # bare ``due`` arm covers ``due Mar 15`` with no preposition.
    r"\b(?:payment\s+due|payable\s+by|"
    r"due\s+(?:pour\s+le|by|on|before|le|pour)?|"
    r"deadline\s*[:\-]?|"
    r"expires?\s+(?:on|by)?|RSVP\s+(?:by|before)|please\s+respond\s+by|"
    r"reply\s+by|complete\s+by|submit\s+by|finalize\s+by|"
    r"no\s+later\s+than|by)\s*[:\-]?\s*",
    # French. ``à régler`` / ``à payer`` accept ``avant``, ``d'ici``,
    # ``pour le``, ``pour`` and bare ``le`` so SaaS invoices in either
    # style match. Bare ``pour le`` is intentionally NOT a standalone
    # marker — it's too generic ("pour le client" would false-positive).
    r"\b(?:"
    r"à\s+régler\s+(?:avant\s+le|avant|d'ici\s+le|d'ici|pour\s+le|pour|le)|"
    r"à\s+payer\s+(?:avant\s+le|avant|d'ici\s+le|d'ici|pour\s+le|pour|le)|"
    r"date\s+limite\s*[:\-]?|"
    r"échéance\s*[:\-]?|"
    r"expire\s+(?:le|avant)|"
    r"date\s+d['e]?\s*expiration\s*[:\-]?|"
    r"avant\s+le|d'ici\s+le|"
    r"RSVP\s+avant|à\s+rendre\s+(?:avant|pour)"
    r")\s*[:\-]?\s*",
)

# What "a date" looks like. Greedy enough to grab "Mar 15th, 2026" but
# stops at punctuation that won't be in a date.
_DATE_TOKEN = (
    r"("
    # Month name + day [+ year]: "March 15", "Mar 15th, 2026"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-zéû]*\s+"
    r"\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{2,4})?"
    r"|"
    # French month: "15 mars 2026"
    r"\d{1,2}\s+"
    r"(?:janv|févr|mars|avr|mai|juin|juil|août|sept|oct|nov|déc)[a-zéû.]*"
    r"(?:\s+\d{2,4})?"
    r"|"
    # Numeric: "03/15", "03/15/2026", "15-03-2026", "2026-03-15"
    r"\d{1,4}[\-/]\d{1,2}[\-/]\d{1,4}"
    r"|"
    # Short numeric: "03/15", "15-03"
    r"\d{1,2}[\-/]\d{1,2}"
    r"|"
    # Relative tokens — EOD / EOW / EOM / EOY are normalized below.
    r"EOD|end\s+of\s+day|EOW|end\s+of\s+week|EOM|end\s+of\s+month|"
    r"EOY|end\s+of\s+year|tomorrow|today|demain|aujourd'hui"
    r")"
)

_DEADLINE_RE = re.compile(
    "(?:" + "|".join(_DEADLINE_MARKERS) + ")" + _DATE_TOKEN,
    re.IGNORECASE,
)

# Tokens that don't go through dateutil — we resolve them relative to "now".
_RELATIVE_TOKEN_OFFSETS: dict[str, timedelta] = {
    "today": timedelta(days=0),
    "aujourd'hui": timedelta(days=0),
    "tomorrow": timedelta(days=1),
    "demain": timedelta(days=1),
}

# `dateutil.parser.parse` only knows English month names. French invoice
# templates almost universally say "31 mai 2026" or "15 juin 2026", so
# we replace French month words with their English equivalents before
# parsing. Full names first (longest match), then 3-letter abbreviations
# Frenchies use casually ("janv.", "févr.", "déc."). Match boundaries are
# enforced by \b on both sides so "marsupial" doesn't get mangled.
_FR_TO_EN_MONTHS = [
    ("janvier", "January"), ("février", "February"), ("mars", "March"),
    ("avril", "April"), ("mai", "May"), ("juin", "June"),
    ("juillet", "July"), ("août", "August"), ("septembre", "September"),
    ("octobre", "October"), ("novembre", "November"), ("décembre", "December"),
    # Abbreviated (trailing "." optional).
    ("janv", "Jan"), ("févr", "Feb"), ("avr", "Apr"),
    ("juil", "Jul"), ("sept", "Sep"), ("oct", "Oct"),
    ("nov", "Nov"), ("déc", "Dec"),
]


def _normalise_french_months(token: str) -> str:
    """Rewrite French month names → English so dateutil can parse them."""
    out = token
    for fr, en in _FR_TO_EN_MONTHS:
        out = re.sub(rf"\b{fr}\b\.?", en, out, flags=re.IGNORECASE)
    return out


def _resolve_eo_token(token_lower: str, now: datetime) -> Optional[datetime]:
    """Handle end-of-period tokens (EOD/EOW/EOM/EOY)."""
    today_end = now.replace(hour=23, minute=59, second=0, microsecond=0)
    if token_lower in ("eod", "end of day"):
        return today_end
    if token_lower in ("eow", "end of week"):
        # ISO week ends on Sunday (weekday=6).
        days_left = 6 - now.weekday()
        return (now + timedelta(days=days_left)).replace(
            hour=23, minute=59, second=0, microsecond=0,
        )
    if token_lower in ("eom", "end of month"):
        # Last day of current month — go to first of next month, back off 1d.
        if now.month == 12:
            first_next = now.replace(year=now.year + 1, month=1, day=1)
        else:
            first_next = now.replace(month=now.month + 1, day=1)
        return (first_next - timedelta(days=1)).replace(
            hour=23, minute=59, second=0, microsecond=0,
        )
    if token_lower in ("eoy", "end of year"):
        return now.replace(month=12, day=31, hour=23, minute=59, second=0, microsecond=0)
    return None


def _user_local_now(now: datetime, user_timezone: Optional[str]) -> datetime:
    """Convert ``now`` to the user's IANA timezone so relative / end-of-period
    tokens resolve against the user's LOCAL calendar day. Falls back to ``now``
    unchanged when no/invalid tz (preserves the pre-fix UTC behaviour)."""
    if not user_timezone:
        return now
    try:
        from zoneinfo import ZoneInfo
        return now.astimezone(ZoneInfo(user_timezone))
    except Exception:
        return now


def _load_user_timezone(account_id: Optional[int]) -> Optional[str]:
    """Best-effort IANA timezone from the account's settings (or None)."""
    if not account_id or account_id <= 0:
        return None
    try:
        from app.api.settings import load_settings
        tz = (load_settings(account_id=account_id).get("user_timezone") or "").strip()
        return tz or None
    except Exception:
        return None


def extract_deadline(
    *,
    body: str,
    subject: str = "",
    now: Optional[datetime] = None,
    user_timezone: Optional[str] = None,
    account_id: Optional[int] = None,
) -> Optional[datetime]:
    """Return a UTC datetime if a deadline marker + parsable date is found in
    the email body or subject, else ``None``.

    Scans subject first (deadlines often live in the subject line of
    invoice / RSVP emails), then body. The first valid match wins.

    ``user_timezone`` (IANA name) anchors RELATIVE / end-of-period tokens
    ("today" / "tomorrow" / "demain" / EOD…) to the user's LOCAL calendar day —
    without it they resolved against the UTC day and landed on the wrong date for
    non-UTC users (chaos audit 2026-06-02). Pass ``account_id`` to resolve the tz
    from settings automatically. Absolute dates are unaffected.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if user_timezone is None and account_id is not None:
        user_timezone = _load_user_timezone(account_id)
    # Relative / end-of-period tokens resolve against the user's LOCAL day.
    local_now = _user_local_now(now, user_timezone)

    haystack = ((subject or "") + "\n\n" + (body or "")).strip()
    if not haystack:
        return None

    for match in _DEADLINE_RE.finditer(haystack):
        token = (match.group(1) or "").strip()
        if not token:
            continue
        token_lower = token.lower()

        # Relative tokens (today / tomorrow / demain) — anchored to the user's
        # local day, then normalized back to UTC for storage.
        if token_lower in _RELATIVE_TOKEN_OFFSETS:
            return (local_now + _RELATIVE_TOKEN_OFFSETS[token_lower]).replace(
                hour=23, minute=59, second=0, microsecond=0,
            ).astimezone(timezone.utc)

        # End-of-period tokens (also resolved against the user's local day).
        eo = _resolve_eo_token(token_lower, local_now)
        if eo is not None:
            return eo.astimezone(timezone.utc)

        # Absolute date — let dateutil parse it. Normalise French months
        # to English first so "15 juin 2026" / "31 mai 2026" parse.
        try:
            parsed = date_parser.parse(
                _normalise_french_months(token),
                default=now.replace(hour=17, minute=0, second=0, microsecond=0),
                dayfirst=_looks_french(haystack),
                fuzzy=False,
            )
        except (ValueError, OverflowError):
            continue

        # Reject dates that landed in the past — most of the time the
        # regex caught noise (e.g. "due 03/15" from a prior year). Allow
        # a 24h grace so a deadline that just barely passed (RSVP an hour
        # ago) still surfaces.
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        if parsed < now - timedelta(hours=24):
            continue
        return parsed.astimezone(timezone.utc)

    return None


def _looks_french(text: str) -> bool:
    """Heuristic: French markers present → prefer dayfirst date parsing."""
    return bool(
        re.search(
            r"\b(?:avant\s+le|échéance|date\s+limite|expire\s+le|d'ici|à\s+régler)\b",
            text,
            re.IGNORECASE,
        )
    )


__all__ = ["extract_deadline"]
