# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests for app.services.contact_avatar_service.

Covers:
- Cache hit / miss / negative TTL
- Provider dispatch (gmail vs outlook vs unknown)
- Graceful failure on missing credentials, malformed responses, oversized blobs
- invalidate_cache scoping (per-account vs global)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services import contact_avatar_service as svc


@pytest.fixture(autouse=True)
def _clear_cache():
    """Reset module-level cache between tests to avoid cross-test pollution."""
    with svc._cache_lock:
        svc._memory_cache.clear()
    yield
    with svc._cache_lock:
        svc._memory_cache.clear()


# ---------------------------------------------------------------------------
# get_contact_avatar — top-level dispatcher
# ---------------------------------------------------------------------------

def test_returns_none_for_blank_email():
    provider = MagicMock(provider_name="gmail")
    assert svc.get_contact_avatar(provider, "", account_id=1) is None
    assert svc.get_contact_avatar(provider, "   ", account_id=1) is None


def test_returns_none_for_unknown_provider():
    provider = MagicMock(provider_name="imap")
    assert svc.get_contact_avatar(provider, "a@b.com", account_id=1) is None


def test_caches_positive_result_keyed_by_account_and_email():
    provider = MagicMock(provider_name="gmail")
    payload = (b"\x89PNG\x0d\x0a", "image/png")
    with patch.object(svc, "_fetch_gmail_avatar", return_value=payload) as fetch:
        first = svc.get_contact_avatar(provider, "Alice@Example.com", account_id=42)
        second = svc.get_contact_avatar(provider, "alice@example.com", account_id=42)
    assert first == payload
    assert second == payload
    # email is normalised to lower-case → second call hits cache, fetch runs once.
    fetch.assert_called_once()


def test_caches_negative_result_to_avoid_repeated_lookups():
    provider = MagicMock(provider_name="gmail")
    with patch.object(svc, "_fetch_gmail_avatar", return_value=None) as fetch:
        first = svc.get_contact_avatar(provider, "ghost@nowhere.com", account_id=7)
        second = svc.get_contact_avatar(provider, "ghost@nowhere.com", account_id=7)
    assert first is None
    assert second is None
    fetch.assert_called_once()


def test_swallows_provider_exceptions_and_caches_negative():
    provider = MagicMock(provider_name="gmail")
    with patch.object(svc, "_fetch_gmail_avatar", side_effect=RuntimeError("boom")) as fetch:
        result = svc.get_contact_avatar(provider, "x@y.com", account_id=1)
        # Second call hits cache — no second exception raised, no second call.
        result2 = svc.get_contact_avatar(provider, "x@y.com", account_id=1)
    assert result is None
    assert result2 is None
    fetch.assert_called_once()


def test_dispatches_to_outlook_for_outlook_provider():
    provider = MagicMock(provider_name="outlook")
    payload = (b"jpegbytes", "image/jpeg")
    with patch.object(svc, "_fetch_outlook_avatar", return_value=payload) as fetch:
        result = svc.get_contact_avatar(provider, "x@org.com", account_id=1)
    assert result == payload
    fetch.assert_called_once()


# ---------------------------------------------------------------------------
# Response validation
# ---------------------------------------------------------------------------

def test_validate_photo_response_rejects_non_image_content_type():
    fake_resp = MagicMock(ok=True, headers={"Content-Type": "text/html"}, content=b"<html>")
    assert svc._validate_photo_response(fake_resp) is None


def test_validate_photo_response_rejects_oversized_payload():
    huge = b"\x00" * (svc._MAX_PHOTO_BYTES + 1)
    fake_resp = MagicMock(ok=True, headers={"Content-Type": "image/jpeg"}, content=huge)
    assert svc._validate_photo_response(fake_resp) is None


def test_validate_photo_response_rejects_empty_payload():
    fake_resp = MagicMock(ok=True, headers={"Content-Type": "image/jpeg"}, content=b"")
    assert svc._validate_photo_response(fake_resp) is None


def test_validate_photo_response_strips_charset_param():
    fake_resp = MagicMock(
        ok=True,
        headers={"Content-Type": "image/jpeg; charset=binary"},
        content=b"jpegbytes",
    )
    result = svc._validate_photo_response(fake_resp)
    assert result == (b"jpegbytes", "image/jpeg")


# ---------------------------------------------------------------------------
# _extract_photo_url — Gmail People API result parsing
# ---------------------------------------------------------------------------

def test_extract_photo_url_finds_matching_email_case_insensitive():
    results = [
        {
            "person": {
                "emailAddresses": [{"value": "Alice@Example.COM"}],
                "photos": [{"url": "https://lh3.googleusercontent.com/abc"}],
            }
        }
    ]
    assert svc._extract_photo_url(results, "alice@example.com") == "https://lh3.googleusercontent.com/abc"


def test_extract_photo_url_skips_default_silhouette():
    results = [
        {
            "person": {
                "emailAddresses": [{"value": "a@b.com"}],
                "photos": [
                    {"url": "https://default.png", "default": True},
                    {"url": "https://real.jpg"},
                ],
            }
        }
    ]
    assert svc._extract_photo_url(results, "a@b.com") == "https://real.jpg"


def test_extract_photo_url_returns_none_when_no_email_match():
    results = [
        {
            "person": {
                "emailAddresses": [{"value": "other@b.com"}],
                "photos": [{"url": "https://x.jpg"}],
            }
        }
    ]
    assert svc._extract_photo_url(results, "wanted@b.com") is None


def test_extract_photo_url_handles_empty_photos_field():
    results = [{"person": {"emailAddresses": [{"value": "a@b.com"}], "photos": []}}]
    assert svc._extract_photo_url(results, "a@b.com") is None


# ---------------------------------------------------------------------------
# invalidate_cache
# ---------------------------------------------------------------------------

def test_invalidate_cache_per_account():
    provider = MagicMock(provider_name="gmail")
    payload = (b"x", "image/png")
    with patch.object(svc, "_fetch_gmail_avatar", return_value=payload):
        svc.get_contact_avatar(provider, "a@x.com", account_id=1)
        svc.get_contact_avatar(provider, "b@x.com", account_id=1)
        svc.get_contact_avatar(provider, "a@x.com", account_id=2)

    removed = svc.invalidate_cache(account_id=1)
    assert removed == 2

    # account_id=2 entry survives.
    with svc._cache_lock:
        remaining_keys = list(svc._memory_cache.keys())
    assert remaining_keys == [(2, "a@x.com")]


def test_invalidate_cache_global():
    provider = MagicMock(provider_name="gmail")
    payload = (b"x", "image/png")
    with patch.object(svc, "_fetch_gmail_avatar", return_value=payload):
        svc.get_contact_avatar(provider, "a@x.com", account_id=1)
        svc.get_contact_avatar(provider, "b@y.com", account_id=2)

    removed = svc.invalidate_cache()
    assert removed == 2
    with svc._cache_lock:
        assert len(svc._memory_cache) == 0


# ---------------------------------------------------------------------------
# Gmail provider integration (lightweight — heavy SDK calls are mocked)
# ---------------------------------------------------------------------------

def test_fetch_gmail_avatar_returns_none_without_credentials():
    provider = MagicMock(spec=["provider_name"])
    provider.provider_name = "gmail"
    # No _credentials attr → MagicMock without spec attr access raises; use real None.
    provider._credentials = None
    assert svc._fetch_gmail_avatar(provider, "a@b.com") is None
