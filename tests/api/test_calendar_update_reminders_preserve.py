# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Regression (audit 2026-06-02): dragging/resizing an event must NOT silently
reset its reminders to a single 30-min popup.

A drag/resize PATCH omits the `reminders` field. `_parse_event_body` used to
default it to `[30]`, which the provider builders then wrote, clobbering the
user's real reminders (e.g. "1 day before"). The fix defaults reminders to
``None`` on UPDATE (event_id present) so the builder OMITS the field and the
provider preserves the existing reminders, while CREATE still defaults to [30].
Mirrors the attendees None-vs-[] contract.
"""
from __future__ import annotations

from app.api.calendar_routes import _parse_event_body

_BASE = {
    "title": "Sync",
    "start_time": "2026-06-17T15:00:00",
    "end_time": "2026-06-17T16:00:00",
}


def test_update_omitted_reminders_is_none_so_builder_preserves():
    ev = _parse_event_body(dict(_BASE), event_id="evt-1")
    assert ev.reminders is None


def test_create_omitted_reminders_defaults_to_30():
    ev = _parse_event_body(dict(_BASE))  # no event_id => create
    assert ev.reminders == [30]


def test_explicit_empty_reminders_clears_on_update():
    ev = _parse_event_body({**_BASE, "reminders": []}, event_id="evt-1")
    assert ev.reminders == []


def test_explicit_reminders_pass_through():
    ev = _parse_event_body({**_BASE, "reminders": [1440]}, event_id="evt-1")
    assert ev.reminders == [1440]


def test_gmail_builder_omits_reminders_when_none_preserving_existing():
    """End-to-end: an omitted-reminders update yields a provider body with NO
    reminders key, so Google's events.update() keeps the existing reminders."""
    from app.providers.gmail_calendar import GmailCalendarAdapter

    ev = _parse_event_body(dict(_BASE), event_id="evt-1")
    body = GmailCalendarAdapter()._build_event_body(ev)
    assert "reminders" not in body


def test_gmail_builder_writes_reminders_when_provided():
    from app.providers.gmail_calendar import GmailCalendarAdapter

    ev = _parse_event_body({**_BASE, "reminders": [10]}, event_id="evt-1")
    body = GmailCalendarAdapter()._build_event_body(ev)
    assert body["reminders"]["overrides"] == [{"method": "popup", "minutes": 10}]
