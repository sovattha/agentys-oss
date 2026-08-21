# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Audit 2026-05-29 (follow-up) — GET /api/stats/activity leaked the live
"time saved" indicator across tenants.

Bug: the handler resolved the caller's account_id then DISCARDED it and called
``get_tracker().get_activity()`` unscoped, so the TimeSavedModal / Learning
dashboard / achievements showed the COMBINED activity of ALL tenants. (The main
audit caught the monthly recap's get_month_activity but missed this live path.)

Fix: the resolved account_id is passed to get_activity(); non-positive / Tauri
desktop → None (global single-user behaviour, unchanged).

Run: pytest tests/audit_fixes/test_isolation_2026_05_29_stats_activity.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("flask_cors")

REMOTE = {"REMOTE_ADDR": "203.0.113.10"}
AUTH = {"Authorization": "Bearer tok"}


@pytest.fixture
def client():
    from app.api.app import create_app
    app = create_app(config={"TESTING": True})
    app.config["TESTING"] = True
    return app.test_client()


def test_stats_activity_scopes_to_caller_account(client):
    """A positive account_id is forwarded to get_activity (as a string)."""
    tracker = MagicMock()
    tracker.get_activity.return_value = {"week": {}, "today": {}}
    with patch("app.api.auth._decode_jwt", return_value={"sub": "5", "email": "a@b.com"}), \
         patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=5), \
         patch("app.draft_quality_tracker.get_tracker", return_value=tracker):
        resp = client.get("/api/stats/activity", headers=AUTH, environ_base=REMOTE)
    assert resp.status_code == 200
    tracker.get_activity.assert_called_once_with(account_id="5")


def test_stats_activity_no_account_stays_global(client):
    """Non-positive resolution (pre-OAuth / desktop) → account_id=None."""
    tracker = MagicMock()
    tracker.get_activity.return_value = {"week": {}, "today": {}}
    with patch("app.api.auth._decode_jwt", return_value={"sub": "9", "email": "x@y.com"}), \
         patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=-1), \
         patch("app.draft_quality_tracker.get_tracker", return_value=tracker):
        resp = client.get("/api/stats/activity", headers=AUTH, environ_base=REMOTE)
    assert resp.status_code == 200
    tracker.get_activity.assert_called_once_with(account_id=None)
