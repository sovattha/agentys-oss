# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""OAuth scope introspection for the contact-photo feature.

We can't trust ``creds.scopes`` on the Google client — it reflects what we
constructed the Credentials with (always ``self.SCOPES``), not what the
user actually granted. Probing the People API / Graph contacts endpoint
once and caching the boolean is reliable and cheap.

The probe is intentionally minimal:

  - Gmail   → ``people_service.people().searchContacts(query='', readMask='photos')``
              returns 200 when ``contacts.readonly`` is granted, 403 otherwise.
  - Outlook → ``GET /me/contacts?$top=1`` returns 200 when ``Contacts.Read``
              is granted, 403 otherwise.

Both calls take ~100 ms; the result is cached per-account for 6 h. After
the user re-consents, :func:`invalidate` is called from the OAuth flow so
the banner disappears immediately.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# (account_id, provider_name) -> (cached_at_epoch, has_scope)
_cache: dict[tuple[int, str], tuple[float, bool]] = {}
_cache_lock = threading.Lock()
_TTL_SECONDS = 6 * 3600  # 6h
_HTTP_TIMEOUT = 6


def has_contacts_scope(provider, account_id: int) -> bool:
    """Return True if the user has granted the contact-photo scope.

    Probes the provider once per account/6h. Failures are treated as
    "scope missing" so the banner errs on the side of prompting a
    reconnect — better one extra prompt than silent invisible photos.
    """
    if not account_id or account_id <= 0:
        return False
    provider_name = (getattr(provider, "provider_name", "") or "").lower()
    if provider_name not in ("gmail", "outlook"):
        return False

    cache_key = (int(account_id), provider_name)
    now = time.time()
    with _cache_lock:
        cached = _cache.get(cache_key)
        if cached and (now - cached[0] < _TTL_SECONDS):
            return cached[1]

    granted = False
    try:
        if provider_name == "gmail":
            granted = _probe_gmail(provider)
        elif provider_name == "outlook":
            granted = _probe_outlook(provider)
    except Exception as exc:  # noqa: BLE001
        logger.debug("scope probe failed (%s): %s", provider_name, exc)
        granted = False

    with _cache_lock:
        _cache[cache_key] = (now, granted)
    return granted


def invalidate(account_id: Optional[int] = None) -> int:
    """Drop the cached probe — call after OAuth re-consent so the banner
    re-evaluates immediately instead of waiting for the 6 h TTL."""
    with _cache_lock:
        if account_id is None:
            removed = len(_cache)
            _cache.clear()
            return removed
        keys = [k for k in _cache if k[0] == int(account_id)]
        for k in keys:
            del _cache[k]
        return len(keys)


def _probe_gmail(provider) -> bool:
    creds = getattr(provider, "_credentials", None)
    if creds is None:
        return False
    try:
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
    except ImportError:
        return False
    try:
        people = build("people", "v1", credentials=creds, cache_discovery=False)
        # readMask must be non-empty per the API; ``photos`` is the cheapest.
        people.people().searchContacts(query="x", readMask="photos").execute()
        return True
    except HttpError as exc:
        # 403 / 401 → scope not granted. Other codes (5xx, transient) treated
        # as "unknown" and fall through to False; the next probe in 6 h will
        # retry.
        status = getattr(getattr(exc, "resp", None), "status", 0)
        logger.debug("Gmail contacts scope probe HTTP %s", status)
        return False
    except Exception as exc:  # noqa: BLE001
        logger.debug("Gmail contacts scope probe error: %s", exc)
        return False


def _probe_outlook(provider) -> bool:
    access_token = getattr(provider, "_access_token", None)
    if not access_token:
        return False
    try:
        resp = requests.get(
            "https://graph.microsoft.com/v1.0/me/contacts?$top=1",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=_HTTP_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.debug("Outlook contacts scope probe network error: %s", exc)
        return False
    if resp.ok:
        return True
    if resp.status_code in (401, 403):
        return False
    # Treat unknown server errors as "scope unknown" — same as failure for
    # banner purposes; the cache TTL will retry.
    logger.debug("Outlook contacts scope probe HTTP %d", resp.status_code)
    return False
