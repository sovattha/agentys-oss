"""Helpers for minimised email metadata persisted by Agentys Cloud."""

from __future__ import annotations

import json
from typing import Any, Optional


CLASSIFICATION_HEADER_ALLOWLIST = frozenset(
    {
        "list-unsubscribe",
        "precedence",
        "auto-submitted",
        "x-auto-response-suppress",
        "x-mailer",
        "reply-to",
    }
)

_PRESENCE_ONLY_HEADERS = frozenset(
    {
        "list-unsubscribe",
        "x-auto-response-suppress",
    }
)
_MAX_CLASSIFICATION_HEADER_VALUE_CHARS = 256


def sanitize_classification_headers(headers: Any) -> dict[str, str]:
    """Return the minimal classification headers safe to persist.

    The labelizer only needs a small allowlist of RFC/bulk-sender signals. Some
    raw headers, especially List-Unsubscribe, can contain opaque user tokens, so
    presence-only signals are reduced to a boolean-ish marker before storage.
    """
    if not isinstance(headers, dict):
        return {}

    sanitized: dict[str, str] = {}
    for raw_name, raw_value in headers.items():
        if not isinstance(raw_name, str) or raw_value is None:
            continue
        name = raw_name.strip().lower()
        if name not in CLASSIFICATION_HEADER_ALLOWLIST:
            continue
        if name in _PRESENCE_ONLY_HEADERS:
            sanitized[name] = "present"
            continue
        value = " ".join(str(raw_value).split()).strip()
        if not value:
            continue
        sanitized[name] = value[:_MAX_CLASSIFICATION_HEADER_VALUE_CHARS]

    return sanitized


def serialize_classification_headers(headers: Any) -> Optional[str]:
    """Serialize sanitized classification headers for ``Email.raw_headers``."""
    sanitized = sanitize_classification_headers(headers)
    if not sanitized:
        return None
    try:
        return json.dumps(sanitized, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return None
