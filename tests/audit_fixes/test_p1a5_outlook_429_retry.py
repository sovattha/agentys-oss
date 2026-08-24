# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""P1-A5: Outlook delta init + delta sync must honour Microsoft Graph 429
Retry-After.

Bug (mother-of-all 2026-04-25): two raw `http_requests.get()` calls in
`outlook_adapter.py` (delta init at L2740, delta sync at L2825) bypassed
the `_graph_request_with_retry` helper. On Microsoft Graph 429 throttling,
the call returned the throttled response, the sync logged a generic HTTP
failure, and `sync_service` treated it as an auth failure → 10-minute
backoff for what should have been a 30-second Retry-After wait.

Fix: both calls now pass through `_graph_request_with_retry`, which sleeps
the server-specified Retry-After delay and retries up to 2 times before
giving up.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


from app.providers.outlook_adapter import _graph_request_with_retry


class _FakeResponse:
    def __init__(self, status_code, headers=None, json_payload=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._json = json_payload or {}

    def json(self):
        return self._json


def test_helper_returns_immediately_on_200():
    """Happy path: no retry, no sleep on first 200."""
    method = MagicMock(return_value=_FakeResponse(200, json_payload={"value": []}))
    with patch("app.providers.outlook_adapter.time.sleep") as sleep_mock:
        resp = _graph_request_with_retry(method, "https://graph.example/m")
    assert resp.status_code == 200
    assert method.call_count == 1
    sleep_mock.assert_not_called()


def test_helper_retries_on_429_and_honours_retry_after():
    """First call 429 with Retry-After: 2 → sleep 2s → second call 200."""
    method = MagicMock(side_effect=[
        _FakeResponse(429, headers={"Retry-After": "2"}),
        _FakeResponse(200, json_payload={"value": []}),
    ])
    with patch("app.providers.outlook_adapter.time.sleep") as sleep_mock:
        resp = _graph_request_with_retry(
            method, "https://graph.example/m", max_retries=2
        )
    assert resp.status_code == 200
    assert method.call_count == 2
    # First sleep ≈ 2 seconds (server-specified Retry-After).
    assert sleep_mock.call_count == 1
    sleep_arg = sleep_mock.call_args[0][0]
    assert 1.5 <= sleep_arg <= 2.5


def test_helper_returns_429_after_max_retries():
    """If we exhaust max_retries, return the last 429 instead of looping."""
    method = MagicMock(return_value=_FakeResponse(429, headers={"Retry-After": "1"}))
    with patch("app.providers.outlook_adapter.time.sleep"):
        resp = _graph_request_with_retry(
            method, "https://graph.example/m", max_retries=2
        )
    assert resp.status_code == 429
    # max_retries=2 → 1 initial + 2 retries = 3 calls.
    assert method.call_count == 3


def test_helper_falls_back_to_exponential_when_retry_after_missing():
    """No Retry-After header → exponential backoff cap kicks in."""
    method = MagicMock(side_effect=[
        _FakeResponse(429, headers={}),
        _FakeResponse(200, json_payload={"value": []}),
    ])
    with patch("app.providers.outlook_adapter.time.sleep") as sleep_mock:
        resp = _graph_request_with_retry(
            method, "https://graph.example/m", max_retries=2
        )
    assert resp.status_code == 200
    sleep_mock.assert_called_once()


def test_delta_init_routes_through_retry_helper():
    """The delta-init call site (get_current_history_id) must go through
    _graph_request_with_retry, not raw http_requests.get."""
    import inspect
    from app.providers.outlook_adapter import OutlookAdapter
    src = inspect.getsource(OutlookAdapter.get_current_history_id)
    # Both the call AND the import must be present.
    assert "_graph_request_with_retry" in src
    # No raw http_requests.get(url at the top of the loop body.
    assert "http_requests.get(url" not in src


def test_delta_sync_routes_through_retry_helper():
    """get_history_changes — same regression guard."""
    import inspect
    from app.providers.outlook_adapter import OutlookAdapter
    src = inspect.getsource(OutlookAdapter.get_history_changes)
    assert "_graph_request_with_retry" in src
    assert "http_requests.get(url" not in src
