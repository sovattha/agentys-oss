"""Email content storage mode helpers without application boot side effects."""

from __future__ import annotations

import os

EMAIL_CONTENT_STORAGE_METADATA_ONLY = "metadata_only"
EMAIL_CONTENT_STORAGE_LEGACY_FULL_CACHE = "legacy_full_cache"
EMAIL_CONTENT_STORAGE_MODES = {
    EMAIL_CONTENT_STORAGE_METADATA_ONLY,
    EMAIL_CONTENT_STORAGE_LEGACY_FULL_CACHE,
}


def get_email_content_storage_mode() -> str:
    """Return the configured email content storage mode."""
    mode = os.getenv(
        "AGENTYS_EMAIL_CONTENT_STORAGE_MODE",
        EMAIL_CONTENT_STORAGE_METADATA_ONLY,
    )
    return mode.strip().lower() or EMAIL_CONTENT_STORAGE_METADATA_ONLY


def should_persist_email_content() -> bool:
    """True only for the explicit legacy full-cache mode."""
    return get_email_content_storage_mode() == EMAIL_CONTENT_STORAGE_LEGACY_FULL_CACHE
