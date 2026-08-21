# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Contact avatar service — fetch profile photos from Gmail People API or Microsoft Graph.

Mirrors the avatars the user already sees in Gmail/Outlook by reading their
contacts directory through the provider's OAuth credentials. Falls back to
None on any failure so the frontend can degrade gracefully to initials.

Cache strategy
--------------
- Positive hits (we found a photo): 24h TTL — photos rarely change and the
  user reconnects on token expiry anyway.
- Negative hits (no photo / API error): 1h TTL — short enough that adding
  a contact in Gmail surfaces here within an hour, long enough to absorb
  the per-message lookup load when scrolling a large inbox.

Scope migration
---------------
Gmail contact scopes are intentionally not requested, so Gmail lookups return
None and the frontend keeps showing initials. Outlook can still use
`Contacts.Read`; users with older grants are prompted to reconnect.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional, Tuple

import requests

logger = logging.getLogger(__name__)

# (account_id, email_lower) -> (cached_at_epoch, value-or-None)
_memory_cache: dict[tuple[int, str], tuple[float, Optional[Tuple[bytes, str]]]] = {}
_cache_lock = threading.Lock()

_POSITIVE_TTL = 24 * 3600  # 24h
_NEGATIVE_TTL = 1 * 3600   # 1h
_HTTP_TIMEOUT = 3          # seconds — avatar lookups must fail fast (scope errors return immediately)
_MAX_PHOTO_BYTES = 1 * 1024 * 1024  # 1 MB upper bound; reject pathological responses


def get_contact_avatar(provider, email: str, account_id: int) -> Optional[Tuple[bytes, str]]:
    """Look up the contact's avatar via the user's email provider.

    Args:
        provider: Authenticated provider instance (GmailAdapter or OutlookAdapter).
        email: The contact's email address (case-insensitive).
        account_id: DB account ID — keys the per-account cache so a tenant
            cannot read a sibling's cached photos.

    Returns:
        (photo_bytes, content_type) on success, None otherwise.
    """
    email = (email or "").strip().lower()
    if not email:
        return None

    cache_key = (int(account_id), email)
    now = time.time()

    with _cache_lock:
        cached = _memory_cache.get(cache_key)
        if cached:
            cached_at, value = cached
            ttl = _POSITIVE_TTL if value is not None else _NEGATIVE_TTL
            if now - cached_at < ttl:
                return value

    result: Optional[Tuple[bytes, str]] = None
    try:
        provider_name = getattr(provider, "provider_name", "") or ""
        if provider_name == "gmail":
            result = _fetch_gmail_avatar(provider, email)
        elif provider_name == "outlook":
            result = _fetch_outlook_avatar(provider, email)
    except Exception as exc:  # noqa: BLE001 — graceful degradation across SDKs
        logger.debug("avatar lookup failed for %s: %s", email, exc)
        result = None

    with _cache_lock:
        _memory_cache[cache_key] = (now, result)

    return result


# ---------------------------------------------------------------------------
# Gmail (Google People API)
# ---------------------------------------------------------------------------

def _fetch_gmail_avatar(provider, email: str) -> Optional[Tuple[bytes, str]]:
    """Looks up a Gmail contact via People API + downloads the photo URL."""
    creds = getattr(provider, "_credentials", None)
    if creds is None:
        return None

    # Lazy import — googleapiclient is heavy and only loaded when needed.
    try:
        from googleapiclient.discovery import build
    except ImportError:
        logger.warning("googleapiclient not available — Gmail avatars disabled")
        return None

    try:
        people_service = build("people", "v1", credentials=creds, cache_discovery=False)
    except Exception as exc:
        logger.debug("People API service build failed: %s", exc)
        return None

    photo_url = _gmail_search_photo_url(people_service, email)
    if not photo_url:
        return None

    return _download_photo(photo_url)


def _gmail_search_photo_url(people_service, email: str) -> Optional[str]:
    """Searches user's contacts (named + other) for the email and returns the
    best photo URL.

    Tries `searchContacts` first (named contacts in the user's address book),
    then `otherContacts.search` (auto-built from sent mail). Returns the URL
    from the first match where one of the person's email addresses matches.
    """
    # Named contacts
    try:
        result = people_service.people().searchContacts(
            query=email,
            readMask="photos,emailAddresses",
        ).execute()
        url = _extract_photo_url(result.get("results", []), email)
        if url:
            return url
    except Exception as exc:
        logger.debug("Gmail searchContacts failed for %s: %s", email, exc)

    # Other contacts (auto-saved from past correspondence)
    try:
        result = people_service.otherContacts().search(
            query=email,
            readMask="photos,emailAddresses",
        ).execute()
        url = _extract_photo_url(result.get("results", []), email)
        if url:
            return url
    except Exception as exc:
        logger.debug("Gmail otherContacts.search failed for %s: %s", email, exc)

    return None


def _extract_photo_url(results: list, email: str) -> Optional[str]:
    """Pulls the first non-default photo URL from a People API search result
    where one of the person's emails matches `email` (case-insensitive)."""
    target = email.lower()
    for entry in results:
        person = entry.get("person") or {}
        addresses = person.get("emailAddresses") or []
        if not any((addr.get("value") or "").lower() == target for addr in addresses):
            continue
        photos = person.get("photos") or []
        for photo in photos:
            # Skip Google's default silhouette ("default": true).
            if photo.get("default"):
                continue
            url = photo.get("url")
            if url:
                return url
    return None


# ---------------------------------------------------------------------------
# Outlook (Microsoft Graph)
# ---------------------------------------------------------------------------

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def _fetch_outlook_avatar(provider, email: str) -> Optional[Tuple[bytes, str]]:
    """Looks up an Outlook contact's photo via Graph.

    Two strategies, in order of likelihood for a typical inbox:
        1. /users/{email}/photo/$value — works for senders inside the user's
           own org (same tenant). One round trip.
        2. /me/contacts filtered by email + /me/contacts/{id}/photo/$value —
           works for the user's saved personal contacts.
    """
    access_token = getattr(provider, "_access_token", None)
    if not access_token:
        return None

    headers = {"Authorization": f"Bearer {access_token}"}

    # Strategy 1: same-tenant org user.
    try:
        url = f"{_GRAPH_BASE}/users/{requests.utils.quote(email, safe='@.')}/photo/$value"
        resp = requests.get(url, headers=headers, timeout=_HTTP_TIMEOUT)
        if resp.ok and resp.content:
            return _validate_photo_response(resp)
    except requests.RequestException as exc:
        logger.debug("Graph /users/photo failed for %s: %s", email, exc)

    # Strategy 2: personal contact lookup.
    try:
        # OData filter on emailAddresses[].address. Single quotes in the
        # email are escaped per OData spec by doubling them.
        safe_email = email.replace("'", "''")
        list_url = (
            f"{_GRAPH_BASE}/me/contacts?$select=id,emailAddresses"
            f"&$filter=emailAddresses/any(e:e/address eq '{safe_email}')"
        )
        resp = requests.get(list_url, headers=headers, timeout=_HTTP_TIMEOUT)
        if resp.ok:
            contacts = resp.json().get("value", [])
            for c in contacts:
                cid = c.get("id")
                if not cid:
                    continue
                photo_url = f"{_GRAPH_BASE}/me/contacts/{cid}/photo/$value"
                photo_resp = requests.get(photo_url, headers=headers, timeout=_HTTP_TIMEOUT)
                if photo_resp.ok and photo_resp.content:
                    return _validate_photo_response(photo_resp)
    except requests.RequestException as exc:
        logger.debug("Graph /me/contacts photo failed for %s: %s", email, exc)

    return None


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _download_photo(url: str) -> Optional[Tuple[bytes, str]]:
    """Downloads a public-ish photo URL and returns (bytes, content_type)."""
    try:
        resp = requests.get(url, timeout=_HTTP_TIMEOUT, stream=True)
    except requests.RequestException as exc:
        logger.debug("photo download failed: %s", exc)
        return None
    return _validate_photo_response(resp)


def _validate_photo_response(resp: requests.Response) -> Optional[Tuple[bytes, str]]:
    """Validates a photo HTTP response and returns (bytes, content_type)."""
    if not resp.ok:
        return None
    content_type = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if not content_type.startswith("image/"):
        return None
    # Read up to _MAX_PHOTO_BYTES — pathological large responses get dropped.
    raw = resp.content
    if not raw or len(raw) > _MAX_PHOTO_BYTES:
        return None
    return (raw, content_type)


def invalidate_cache(account_id: Optional[int] = None) -> int:
    """Clears cached avatars. Used on OAuth disconnect / re-consent.

    Args:
        account_id: If provided, only that account's entries are dropped;
            otherwise the whole cache is cleared.

    Returns:
        Number of entries removed.
    """
    with _cache_lock:
        if account_id is None:
            removed = len(_memory_cache)
            _memory_cache.clear()
            return removed
        keys = [k for k in _memory_cache if k[0] == int(account_id)]
        for k in keys:
            del _memory_cache[k]
        return len(keys)
