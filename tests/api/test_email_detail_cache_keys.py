"""
Regression tests for the email detail cache key format.

Bug: the canonical cache key is ``(account_id, email_id)`` (set by
``_set_cached_email_detail``), but the background body fetch in
``routes_emails._fetch_body_html_background`` used to write a bare
``email_id`` string key. When ``_get_email_from_memory_list_cache`` later
iterated the cache with ``for (_, eid), entry in _email_detail_cache.items():``,
it tried to unpack a string like ``"14166"`` into two vars and crashed with
``ValueError: too many values to unpack (expected 2)``. The whole lookup
returned ``None``, so ``get_email_by_id`` fell through to a 404 on
``POST /api/emails/<id>/process``.

These tests lock in:
1. Poisoned non-tuple keys in the cache no longer crash the lookup.
2. A properly keyed ``(account_id, email_id)`` entry is returned when fresh.
"""
from __future__ import annotations

import time

import pytest

from app.api import routes_helpers as rh


@pytest.fixture(autouse=True)
def _clear_cache():
    with rh._email_detail_cache_lock:
        rh._email_detail_cache.clear()
    yield
    with rh._email_detail_cache_lock:
        rh._email_detail_cache.clear()


def _put_entry(key, email_id: str, body: str = "hello"):
    now = time.time()
    with rh._email_detail_cache_lock:
        rh._email_detail_cache[key] = {
            "data": {
                "id": email_id,
                "sender": "a@example.com",
                "sender_name": "A",
                "to": ["me@example.com"],
                "subject": "s",
                "body": body,
                "body_html": None,
                "received_at": "2026-04-14T12:00:00+00:00",
                "is_read": False,
                "has_attachments": False,
                "conversation_id": email_id,
            },
            "timestamp": now,
        }


def test_lookup_tolerates_poisoned_string_key(monkeypatch):
    """A legacy writer that used ``email_id`` (string) as the cache key
    must not make the detail-cache scan crash with
    ``ValueError: too many values to unpack (expected 2)`` — the lookup
    should tolerantly handle both tuple and string keys."""
    _put_entry("14166", email_id="14166", body="legacy body")  # poisoned: bare string key

    # Must not raise a ValueError, even though the key isn't the canonical
    # 2-tuple form. The old code crashed here; the fix makes the scan skip
    # non-2-tuples gracefully — string keys are treated as (null, email_id)
    # for best-effort recovery so stale cache entries don't break lookups.
    result = rh._get_email_from_memory_list_cache("14166")

    assert result is not None
    assert result.id == "14166"


def test_lookup_returns_entry_for_tuple_key():
    """With the canonical tuple key ``(account_id, email_id)``, the detail
    cache scan should find the entry and hydrate a StandardEmail from it."""
    _put_entry((1, "14166"), email_id="14166", body="body from cache")

    result = rh._get_email_from_memory_list_cache("14166")

    # The helper only consults the detail cache after missing the list cache,
    # so when no list entry exists and the detail cache has a fresh tuple
    # keyed entry, we should get a StandardEmail back.
    assert result is not None
    assert result.id == "14166"
    assert result.body == "body from cache"


def test_lookup_survives_mixed_key_cache(monkeypatch):
    """Cache containing BOTH a poisoned string key AND a valid tuple key
    must return the valid one without tripping on the poisoned one."""
    _put_entry("stale-14179", email_id="stale-14179")  # poisoned
    _put_entry((1, "14179"), email_id="14179", body="valid body")

    result = rh._get_email_from_memory_list_cache("14179")

    assert result is not None
    assert result.id == "14179"
    assert result.body == "valid body"
