# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Privacy helpers for durable contact summaries."""

from __future__ import annotations

import json
from typing import Any

_ALLOWED_RELATION_TYPES = {
    "client",
    "colleague",
    "manager",
    "friend",
    "vendor",
    "prospect",
    "other",
}
_ALLOWED_TONES = {"formal", "semi_formal", "casual", "very_casual"}
_ALLOWED_LANGUAGES = {"fr", "en", "es", "de", "it", "pt", "other"}


def minimize_contact_summary(summary: dict[str, Any] | None) -> dict[str, str]:
    """Keep only abstract, enum-like contact signals.

    Full contact summaries are derived from email bodies and may contain
    paraphrases, facts, topics, or exact formulas. In metadata-only mode we
    keep only coarse labels safe enough to persist and inject into prompts.
    """
    if not isinstance(summary, dict):
        return {}

    minimized: dict[str, str] = {}

    relation = str(summary.get("relation_type") or "").lower().strip()
    if relation in _ALLOWED_RELATION_TYPES:
        minimized["relation_type"] = relation

    tone = str(summary.get("habitual_tone") or "").lower().strip()
    if tone in _ALLOWED_TONES:
        minimized["habitual_tone"] = tone

    language = str(summary.get("language") or "").lower().strip()
    if language in _ALLOWED_LANGUAGES:
        minimized["language"] = language

    return minimized


def minimize_contact_summary_json(summary_json: str | None) -> str:
    """Return a JSON object containing only metadata-only safe fields."""
    if not summary_json:
        return "{}"

    try:
        parsed = json.loads(summary_json)
    except (TypeError, ValueError, json.JSONDecodeError):
        return "{}"

    return json.dumps(
        minimize_contact_summary(parsed),
        ensure_ascii=False,
        sort_keys=True,
    )
