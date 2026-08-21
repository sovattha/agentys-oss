# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Shared email-classification heuristics for follow-up gating.

These predicates were lifted out of ``app/api/auto_followup.py`` when the
legacy nudge loop was retired — their callers now span the snoozed-draft
Quick Step handler, the routes layer, and the pending-drafts API, so a
shared module is the right home.

Pure regex / string ops, no LLM, no I/O. Safe to call from hot paths.
"""
from __future__ import annotations

import re

_NOREPLY_PATTERNS = ("noreply", "no-reply", "donotreply", "do-not-reply")

# Patterns that indicate the sender is sharing their availability —
# a reply is expected from the recipient (pick a slot), so a follow-up
# nudge would be noise.
_AVAILABILITY_URL_RE = re.compile(
    r"cal\.com/|calendly\.com/|calendar\.app\.google/|"
    r"outlook\.office\.com/bookwithme/|cal\.id/|tidycal\.com/|"
    r"savvycal\.com/|appointlet\.com/|doodle\.com/",
    re.IGNORECASE,
)
_AVAILABILITY_KEYWORD_RE = re.compile(
    r"\bavailabilit(?:y|ies)\b|"
    r"\bdisponibilit[eé]s?\b|"
    r"\bvoici mes créneaux\b|"
    r"\bhere are my.*(?:times?|slots?|availabilit)\b|"
    r"\bpick a time\b|choisissez un créneau\b|"
    r"\bbook.*(?:slot|meeting|time|call)\b",
    re.IGNORECASE,
)
# ≥2 time-slot lines of the form "14h15 – 15h30" or "14:15 - 15:30"
_TIME_SLOT_RE = re.compile(r"\b\d{1,2}[h:]\d{2}\s*[-–—]\s*\d{1,2}[h:]\d{2}")


def is_availability_email(body: str) -> bool:
    """Return True when the email body is sharing availability slots.

    Heuristic: booking-URL present, OR keyword present, OR ≥2 time-slot lines.
    In all cases a reply is expected from the other side (pick a slot), so a
    follow-up nudge from our side would be noise.
    """
    if not body:
        return False
    text = body[:3000]
    if _AVAILABILITY_URL_RE.search(text):
        return True
    if _AVAILABILITY_KEYWORD_RE.search(text):
        return True
    if len(_TIME_SLOT_RE.findall(text)) >= 2:
        return True
    return False


def is_noreply_recipient(address: str) -> bool:
    """Return True when ``address`` is an unmanned noreply mailbox.

    Substring match on the local part — covers ``noreply@``, ``no-reply@``,
    ``donotreply@``, ``do-not-reply@`` and common variants.
    """
    if not address:
        return False
    local = address.split("@")[0].lower() if "@" in address else address.lower()
    return any(p in local for p in _NOREPLY_PATTERNS)


__all__ = [
    "is_availability_email",
    "is_noreply_recipient",
]
