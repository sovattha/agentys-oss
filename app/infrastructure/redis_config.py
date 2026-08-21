"""Shared Redis configuration helpers."""

from __future__ import annotations

import os


def get_redis_url() -> str:
    """Return the first Redis URL exposed by the runtime."""
    for name in ("REDIS_URL", "REDIS_PRIVATE_URL", "RAILWAY_REDIS_URL"):
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""
