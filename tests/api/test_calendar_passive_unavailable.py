# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.api.app import create_app
from app.interfaces.calendar_provider import CalendarScopeError


@pytest.fixture()
def client():
    app = create_app(config={"TESTING": True})
    return app.test_client()


def test_upcoming_events_returns_empty_200_when_calendar_provider_unavailable(client):
    with patch("app.api.calendar_routes._resolve_account_id", return_value="acc-1"), \
         patch("app.api.calendar_routes.create_calendar_provider", return_value=None):
        resp = client.get("/api/calendar/upcoming?hours=6&limit=50&account_id=acc-1")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["events"] == []
    assert data["count"] == 0
    assert data["calendar_unavailable"] is True
    assert data["needs_reauth"] is True
    assert data["hours"] == 6


def test_today_events_returns_empty_200_when_calendar_scope_missing(client):
    scope_error = CalendarScopeError("acc-1", "gmail")
    provider = MagicMock()
    provider.get_today_events.side_effect = scope_error

    with patch("app.api.calendar_routes._resolve_account_id", return_value="acc-1"), \
         patch("app.api.calendar_routes.create_calendar_provider", return_value=provider):
        resp = client.get("/api/calendar/today?account_id=acc-1")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["events"] == []
    assert data["count"] == 0
    assert data["calendar_unavailable"] is True
    assert data["needs_reauth"] is True
    assert data["account_id"] == "acc-1"
