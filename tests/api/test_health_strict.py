# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests for /api/health/strict — DB-aware healthcheck for Railway.

Issue #577 item 1. Existing /api/health is "always 200" and cannot signal a
container with a broken DB connection (pool exhausted, file-locked, migration
failed). Railway then promotes the bad container and 100% of real requests
fail in 500.

The strict variant probes the DB with SELECT 1 and returns 503 if the probe
fails, so Railway holds the previous container and the badge correctly says
"deploy FAILED" instead of "deploy SUCCESS".
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def app(monkeypatch):
    """Boot the full Flask app — same surface Railway hits in prod."""
    monkeypatch.delenv("API_CORS_ORIGINS", raising=False)
    from app.api.app import create_app

    app = create_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


class TestHealthStrictWhenDbHealthy:
    def test_returns_200(self, client, monkeypatch):
        monkeypatch.setattr(
            "app.api.routes_health._probe_db",
            lambda: (True, None),
        )
        resp = client.get("/api/health/strict")
        assert resp.status_code == 200

    def test_body_reports_db_ok(self, client, monkeypatch):
        monkeypatch.setattr(
            "app.api.routes_health._probe_db",
            lambda: (True, None),
        )
        resp = client.get("/api/health/strict")
        body = resp.get_json()
        assert body["status"] == "ok"
        assert body["db"] == "ok"
        assert "version" in body
        assert "timestamp" in body


class TestHealthStrictWhenDbDown:
    def test_returns_503(self, client, monkeypatch):
        monkeypatch.setattr(
            "app.api.routes_health._probe_db",
            lambda: (False, "OperationalError"),
        )
        resp = client.get("/api/health/strict")
        assert resp.status_code == 503

    def test_body_reports_db_down(self, client, monkeypatch):
        monkeypatch.setattr(
            "app.api.routes_health._probe_db",
            lambda: (False, "OperationalError"),
        )
        resp = client.get("/api/health/strict")
        body = resp.get_json()
        assert body["status"] == "unhealthy"
        assert body["db"] == "down"
        assert body["reason"] == "OperationalError"

    def test_does_not_leak_filesystem_paths_or_traceback(self, client, monkeypatch):
        """Reason must be a short error class name, not a stack trace.

        A leaked path like /Users/you/.agentys/data/agentys.db or a full
        Traceback gives an attacker the disk layout. We only emit the
        exception class name (e.g. "OperationalError").
        """
        monkeypatch.setattr(
            "app.api.routes_health._probe_db",
            lambda: (False, "OperationalError"),
        )
        resp = client.get("/api/health/strict")
        text = resp.get_data(as_text=True)
        assert "/Users/" not in text
        assert "Traceback" not in text
        assert ".agentys" not in text
        assert "sqlite" not in text.lower()


class TestHealthEndpointsArePublic:
    """Regression for the 2026-05-09 prod outage: /api/health/strict is the
    Railway healthcheck path (railway.toml). The Flask test_client defaults
    to remote_addr 127.0.0.1 which the auth guard treats as Tauri desktop
    (loopback bypass), so naive integration tests pass while Railway's
    non-loopback probe gets 401 and the deploy fails.

    This test asserts the explicit whitelist contains the health endpoints
    so a future rename / new health route forces a deliberate update.
    """

    REQUIRED = frozenset({"api.health", "api.health_strict", "api.health_deep"})

    def test_public_endpoints_contain_all_health_routes(self):
        from app.api.routes_helpers import _PUBLIC_ENDPOINTS

        missing = self.REQUIRED - _PUBLIC_ENDPOINTS
        assert not missing, (
            f"_PUBLIC_ENDPOINTS missing {missing}. Without these, the auth "
            f"guard returns 401 for Railway's healthcheck probe (non-loopback) "
            f"and the deploy fails — exactly the 2026-05-09 outage."
        )

    def test_health_strict_returns_200_for_non_loopback_probe(self, client, monkeypatch):
        """Simulate Railway's healthcheck: no Bearer, remote_addr non-loopback."""
        monkeypatch.setattr(
            "app.api.routes_health._probe_db",
            lambda: (True, None),
        )
        # Force a non-loopback REMOTE_ADDR to mimic Railway's internal proxy.
        resp = client.get(
            "/api/health/strict",
            environ_overrides={"REMOTE_ADDR": "100.64.0.2"},
        )
        assert resp.status_code == 200, (
            f"Expected 200 for non-loopback probe; got {resp.status_code}. "
            f"Body: {resp.get_data(as_text=True)}. The auth guard probably "
            f"rejected it — check _PUBLIC_ENDPOINTS."
        )


class TestRailwayRuntimeConfig:
    def test_prod_uses_threading_async_mode(self):
        """Railway must use threading + simple-websocket, not eventlet.

        AGENTYS_ASYNC_MODE is pinned to 'threading' in the Railway entrypoint
        (scripts/railway_entrypoint.py) — which railway.toml's startCommand
        invokes — and defaulted to threading in run_api.py. eventlet must never
        be the forced prod async mode: it monkeypatches ThreadPoolExecutor and
        can starve /api/health while Gmail/Outlook background I/O runs.
        """
        entrypoint = Path("scripts/railway_entrypoint.py").read_text(encoding="utf-8")
        config = Path("railway.toml").read_text(encoding="utf-8")
        requirements = Path("requirements.txt").read_text(encoding="utf-8")
        # The async mode lives in the entrypoint (railway.toml only invokes it).
        assert '"AGENTYS_ASYNC_MODE", "threading"' in entrypoint
        assert '"AGENTYS_ASYNC_MODE", "eventlet"' not in entrypoint
        assert "railway_entrypoint.py" in config
        assert "AGENTYS_ASYNC_MODE=eventlet" not in config
        assert "simple-websocket" in requirements


class TestProbeDbContract:
    """Direct unit test on the probe helper — must not raise even on hostile
    DB state. Returning (False, msg) is the contract; raising is a bug because
    Flask would 500 instead of 503 and Railway would still promote.
    """

    def test_probe_returns_tuple_of_bool_and_str_or_none(self):
        from app.api.routes_health import _probe_db

        healthy, reason = _probe_db()
        assert isinstance(healthy, bool)
        assert reason is None or isinstance(reason, str)

    def test_probe_swallows_exceptions(self, monkeypatch):
        """If get_db_session raises (e.g. encryption key missing), the probe
        must catch it and return (False, error_class_name) — never bubble.
        """
        import app.api.routes_health as routes_health

        def _boom():
            class _Boom:
                def __enter__(self_inner):
                    raise RuntimeError("simulated DB unavailable")

                def __exit__(self_inner, *args):
                    return False

            return _Boom()

        monkeypatch.setattr(
            "app.api.routes_health.get_db_session",
            lambda: _boom(),
        )
        healthy, reason = routes_health._probe_db()
        assert healthy is False
        assert reason == "RuntimeError"
