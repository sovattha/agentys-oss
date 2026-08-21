# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Regression tests for `_is_user_busy_window` (F-01).

Outlook's `get_freebusy` short-circuits to `{"calendars": {}}` when its
inner `/me` probe fails (Graph throttle, token-refresh hiccup, DNS blip)
and the caller passed no explicit attendees. Before F-01, the busy-window
helper flattened that to `False` ("user is free") and the
`available_for_invite` Quick Step condition silently auto-RSVPed onto
conflicting meetings. The contract is: provider failure → return None so
the condition fails closed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.quicksteps import auto_trigger


def _utc_window():
    start = datetime(2026, 5, 12, 9, 0, tzinfo=timezone.utc)
    return start, start + timedelta(hours=1)


class _FakeCalendarProvider:
    """Stub returning a caller-chosen freebusy payload."""

    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get_freebusy(self, attendees, start, end):
        self.calls.append((list(attendees), start, end))
        return self.payload


def _patch_provider(payload):
    """Bypass OAuth resolution and inject the fake provider."""
    return patch.multiple(
        auto_trigger,
        _resolve_oauth_account_id=lambda _aid: "oauth-stub",
    ), patch(
        "app.providers.calendar_factory.create_calendar_provider",
        return_value=_FakeCalendarProvider(payload),
    )


def test_empty_calendars_returns_none_not_false():
    """F-01: `{"calendars": {}}` is provider failure, not a 'free' signal."""
    start, end = _utc_window()
    oauth_patch, factory_patch = _patch_provider({"calendars": {}})
    with oauth_patch, factory_patch:
        result = auto_trigger._is_user_busy_window(account_id=1, start=start, end=end)
    assert result is None, (
        "empty calendars dict must fail closed (None), otherwise an Outlook /me "
        "probe failure during `available_for_invite` evaluation silently "
        "auto-accepts conflicting meetings"
    )


def test_calendar_with_busy_slots_returns_true():
    start, end = _utc_window()
    busy = {"calendars": {"me@x.com": [{"start": "2026-05-12T09:15:00Z", "end": "2026-05-12T09:30:00Z"}]}}
    oauth_patch, factory_patch = _patch_provider(busy)
    with oauth_patch, factory_patch:
        assert auto_trigger._is_user_busy_window(account_id=1, start=start, end=end) is True


def test_calendar_with_no_slots_returns_false():
    """A real query that came back with the primary calendar but no events is genuinely free."""
    start, end = _utc_window()
    free = {"calendars": {"me@x.com": []}}
    oauth_patch, factory_patch = _patch_provider(free)
    with oauth_patch, factory_patch:
        assert auto_trigger._is_user_busy_window(account_id=1, start=start, end=end) is False


def test_provider_raise_returns_none():
    """Existing contract: an exception from get_freebusy fails closed."""
    start, end = _utc_window()

    class _RaisingProvider:
        def get_freebusy(self, *_a, **_kw):
            raise RuntimeError("graph 503")

    with patch.multiple(
        auto_trigger,
        _resolve_oauth_account_id=lambda _aid: "oauth-stub",
    ), patch(
        "app.providers.calendar_factory.create_calendar_provider",
        return_value=_RaisingProvider(),
    ):
        assert auto_trigger._is_user_busy_window(account_id=1, start=start, end=end) is None


def test_invalid_window_returns_none():
    start, _ = _utc_window()
    # start >= end → invariant guard returns None without hitting the provider
    assert auto_trigger._is_user_busy_window(account_id=1, start=start, end=start) is None
    assert auto_trigger._is_user_busy_window(account_id=0, start=start, end=start + timedelta(hours=1)) is None
