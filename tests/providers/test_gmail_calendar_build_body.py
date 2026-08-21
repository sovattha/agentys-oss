# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Unit tests for GmailCalendarAdapter._build_event_body.

Covers two audit fixes (2026-06-02):
 - label/project color must be emitted as Google ``colorId`` (was silently dropped);
 - attendees semantics: ``None`` = leave untouched (drag/resize PATCH omits the
   field), ``[]`` = clear all attendees (must be sent explicitly so Google drops
   them), a populated list = set them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from app.providers.gmail_calendar import GmailCalendarAdapter


@dataclass
class FakeEvent:
    id: str = "evt-1"
    title: str = "Réunion test"
    description: str = ""
    location: str = ""
    start_time: datetime = field(default_factory=lambda: datetime(2026, 6, 17, 15, 0, 0))
    end_time: datetime = field(default_factory=lambda: datetime(2026, 6, 17, 16, 0, 0))
    all_day: bool = False
    attendees: Optional[List[str]] = None
    reminders: List[int] = field(default_factory=list)
    recurrence: Optional[str] = None
    color: Optional[str] = None
    conference: bool = False


def _build(**kwargs) -> dict:
    return GmailCalendarAdapter()._build_event_body(FakeEvent(**kwargs))


class TestColor:
    def test_color_emitted_as_colorid(self):
        body = _build(color="5")
        assert body["colorId"] == "5"

    def test_no_color_omits_colorid(self):
        body = _build()
        assert "colorId" not in body


class TestAttendees:
    def test_none_leaves_attendees_untouched(self):
        # A drag/resize PATCH omits attendees -> _parse_event_body passes None ->
        # the key must stay absent so Google preserves the existing guest list.
        body = _build(attendees=None)
        assert "attendees" not in body

    def test_empty_list_clears_attendees(self):
        # The edit form cleared the field -> [] must be sent so Google drops them.
        body = _build(attendees=[])
        assert body["attendees"] == []

    def test_populated_list_sets_attendees(self):
        body = _build(attendees=["a@x.com", "b@y.com"])
        assert body["attendees"] == [{"email": "a@x.com"}, {"email": "b@y.com"}]
