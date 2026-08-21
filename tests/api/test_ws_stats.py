# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests for /api/_internal/ws-stats — WebSocket rooms observability.

Issue #577 item 3. Without a metric like this, a WS room leak (rooms
that never unsubscribe; the bug class behind #290 reverberations) would
grow memory and degrade latency silently — Railway reboots every 24h
mask the symptom and nobody learns there is a leak.

This endpoint is the observation point. The paired sentinel layer 4 in
``nightly.yml`` polls it daily and opens an auto-sentinelle issue if
thresholds breach.

Auth contract: same ``OBSERVABILITY_TOKEN`` env var as
/ws-selftest. A missing env var must reject every request — never
degrade to an open endpoint.
"""

from __future__ import annotations

import time

import pytest


@pytest.fixture
def client(monkeypatch):
    """Boot create_app() so we exercise the real blueprint registration —
    the /ws-stats route is registered against ``selftest_bp`` and must
    be reachable through the same /api/_internal prefix as ws-selftest.
    """
    monkeypatch.setenv("OBSERVABILITY_TOKEN", "t-test-secret")
    monkeypatch.delenv("API_CORS_ORIGINS", raising=False)
    from app.api.app import create_app

    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def reset_ws_state():
    """Snapshot + restore the websocket module's mutable globals so
    tests stay isolated. Without this, a counter increment in one test
    leaks into the next and turns the whole suite flaky."""
    import app.api.websocket as ws

    saved_pending = dict(ws._pending_events)
    saved_warmup = dict(ws._cache_warmup_last_at)
    saved_counter = ws._emit_counter
    yield ws
    ws._pending_events.clear()
    ws._pending_events.update(saved_pending)
    ws._cache_warmup_last_at.clear()
    ws._cache_warmup_last_at.update(saved_warmup)
    ws._emit_counter = saved_counter


class TestWsStatsAuth:
    def test_returns_401_without_token(self, client):
        resp = client.get("/api/_internal/ws-stats")
        assert resp.status_code == 401

    def test_returns_401_with_wrong_token(self, client):
        resp = client.get(
            "/api/_internal/ws-stats",
            headers={"X-Observability-Token": "wrong"},
        )
        assert resp.status_code == 401

    def test_returns_401_when_env_var_missing(self, client, monkeypatch):
        # Even with a header, a missing env var must reject — refuses
        # to degrade to an open endpoint on a misconfigured deploy.
        monkeypatch.delenv("OBSERVABILITY_TOKEN", raising=False)
        resp = client.get(
            "/api/_internal/ws-stats",
            headers={"X-Observability-Token": "anything"},
        )
        assert resp.status_code == 401

    def test_401_body_does_not_disclose_misconfiguration(
        self, client, monkeypatch
    ):
        """Both 'wrong token' and 'env var missing' must return the same
        body — exposing 'env var missing' would tell an attacker exactly
        which side the misconfiguration is on."""
        monkeypatch.delenv("OBSERVABILITY_TOKEN", raising=False)
        body_missing_env = client.get(
            "/api/_internal/ws-stats",
            headers={"X-Observability-Token": "x"},
        ).get_json()

        monkeypatch.setenv("OBSERVABILITY_TOKEN", "real-secret")
        body_wrong_header = client.get(
            "/api/_internal/ws-stats",
            headers={"X-Observability-Token": "wrong"},
        ).get_json()
        assert body_missing_env == body_wrong_header


class TestWsStatsPayloadShape:
    """The JSON shape is the contract the GitHub Actions sentinel
    parses. Renaming keys without updating the sentinel breaks the
    monitoring silently."""

    REQUIRED_KEYS = {
        "pending_rooms_count",
        "pending_events_total",
        "pending_room_age_seconds_p50",
        "pending_room_age_seconds_p95",
        "cache_warmup_rooms_count",
        "total_emits",
    }

    def test_returns_200_with_token(self, client, reset_ws_state):
        resp = client.get(
            "/api/_internal/ws-stats",
            headers={"X-Observability-Token": "t-test-secret"},
        )
        assert resp.status_code == 200

    def test_payload_has_all_required_keys(self, client, reset_ws_state):
        resp = client.get(
            "/api/_internal/ws-stats",
            headers={"X-Observability-Token": "t-test-secret"},
        )
        body = resp.get_json()
        assert self.REQUIRED_KEYS.issubset(body.keys()), (
            f"missing keys: {self.REQUIRED_KEYS - set(body.keys())}"
        )

    def test_empty_state_yields_zero_counts_and_null_percentiles(
        self, client, reset_ws_state
    ):
        # Reset wiped both dicts. Percentiles must be JSON-null when
        # there is no sample, not 0 (0 is a valid measured value).
        reset_ws_state._pending_events.clear()
        reset_ws_state._cache_warmup_last_at.clear()
        resp = client.get(
            "/api/_internal/ws-stats",
            headers={"X-Observability-Token": "t-test-secret"},
        )
        body = resp.get_json()
        assert body["pending_rooms_count"] == 0
        assert body["pending_events_total"] == 0
        assert body["pending_room_age_seconds_p50"] is None
        assert body["pending_room_age_seconds_p95"] is None
        assert body["cache_warmup_rooms_count"] == 0


class TestWsStatsWithPendingRooms:
    """Populate the pending-events buffer with synthetic rooms and
    verify the metrics aggregate correctly. This exercises the
    percentile path that an empty state would skip."""

    def test_counts_and_percentiles_with_3_rooms(
        self, client, reset_ws_state
    ):
        from collections import deque

        ws = reset_ws_state
        ws._pending_events.clear()
        now = time.time()
        # 3 rooms with ages 10s, 30s, 60s — p50 ~= 30, p95 ~= 57
        # (linear interpolation between 30 and 60 at 0.95 quantile).
        ws._pending_events["alice@x"] = deque(
            [(now - 10.0, "draft_ready", {})]
        )
        ws._pending_events["bob@x"] = deque(
            [(now - 30.0, "new_email", {}), (now - 5.0, "new_email", {})]
        )
        ws._pending_events["carol@x"] = deque(
            [(now - 60.0, "draft_complete", {})]
        )

        resp = client.get(
            "/api/_internal/ws-stats",
            headers={"X-Observability-Token": "t-test-secret"},
        )
        body = resp.get_json()
        assert body["pending_rooms_count"] == 3
        assert body["pending_events_total"] == 4  # 1 + 2 + 1
        # Ages from the OLDEST event per room: 10, 30, 60
        # Sorted: 10, 30, 60 → p50 = 30, p95 = (60-30) * 0.9 + 30 = 57
        assert 25 <= body["pending_room_age_seconds_p50"] <= 35
        assert 50 <= body["pending_room_age_seconds_p95"] <= 65


class TestEmitCounter:
    """The counter must be the same number that the endpoint reports.
    Without that, the sentinel would see a stale or unrelated metric.
    """

    def test_counter_zero_on_fresh_state(self, reset_ws_state):
        from app.api.websocket import get_emit_count

        reset_ws_state._emit_counter = 0
        assert get_emit_count() == 0

    def test_counter_increments_via_helper(self, reset_ws_state):
        from app.api.websocket import (
            _increment_emit_counter,
            get_emit_count,
        )

        reset_ws_state._emit_counter = 0
        _increment_emit_counter()
        _increment_emit_counter()
        _increment_emit_counter()
        assert get_emit_count() == 3

    def test_endpoint_reflects_counter(self, client, reset_ws_state):
        from app.api.websocket import _increment_emit_counter

        reset_ws_state._emit_counter = 0
        for _ in range(5):
            _increment_emit_counter()
        resp = client.get(
            "/api/_internal/ws-stats",
            headers={"X-Observability-Token": "t-test-secret"},
        )
        assert resp.get_json()["total_emits"] == 5
