# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests for /api/_internal/scheduler-health — issue #577 item 4.

The endpoint is the bridge between the heartbeat helper and the
GitHub Actions sentinel. Contract:

- 401 without token (same auth as ws-selftest / ws-stats)
- 200 + status="ok" when no scheduler is stale
- 503 + status="degraded" + list of stale schedulers when any is stale

The 503 (not 500) is deliberate: 503 = "service unavailable, retry
later" matches Railway's healthcheck semantics. A 5xx is what makes
the GitHub Actions runner exit non-zero via curl --fail, which fires
the auto-sentinelle alerter.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("OBSERVABILITY_TOKEN", "t-test-secret")
    monkeypatch.delenv("API_CORS_ORIGINS", raising=False)
    from app.api.app import create_app

    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def clean_heartbeats():
    from app.db.database import get_db_session
    from app.db.models.scheduler_heartbeat import SchedulerHeartbeat

    with get_db_session() as session:
        session.query(SchedulerHeartbeat).delete()
    yield
    with get_db_session() as session:
        session.query(SchedulerHeartbeat).delete()


class TestSchedulerHealthAuth:
    def test_returns_401_without_token(self, client):
        resp = client.get("/api/_internal/scheduler-health")
        assert resp.status_code == 401


class TestSchedulerHealthHappyPath:
    def test_no_heartbeats_means_healthy(self, client, clean_heartbeats):
        """Fresh deploy with no scheduler having beaten yet — endpoint
        returns ok, status=ok. We do not 503 just because the table is
        empty; the user might be running a stripped-down deployment.
        """
        resp = client.get(
            "/api/_internal/scheduler-health",
            headers={"X-Observability-Token": "t-test-secret"},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "ok"
        assert body["schedulers"] == []
        assert body["stale_schedulers"] == []

    def test_fresh_heartbeat_is_reported_healthy(
        self, client, clean_heartbeats
    ):
        from app.services.scheduler_heartbeat import record_heartbeat

        record_heartbeat(
            "scheduled_email_scheduler",
            status="ok",
            expected_interval_seconds=120,
        )

        resp = client.get(
            "/api/_internal/scheduler-health",
            headers={"X-Observability-Token": "t-test-secret"},
        )
        body = resp.get_json()
        assert resp.status_code == 200
        assert body["status"] == "ok"
        assert len(body["schedulers"]) == 1
        sched = body["schedulers"][0]
        assert sched["name"] == "scheduled_email_scheduler"
        assert sched["last_status"] == "ok"
        assert sched["stale"] is False
        assert "last_run_at" in sched
        assert sched["expected_interval_seconds"] == 120

    def test_known_preboot_stale_heartbeat_is_ignored_during_boot_grace(
        self, client, clean_heartbeats, monkeypatch
    ):
        from app.api import routes_selftest
        from app.db.database import get_db_session
        from app.db.models.scheduler_heartbeat import SchedulerHeartbeat

        started_at = datetime.now(timezone.utc)
        monkeypatch.setattr(routes_selftest, "_PROCESS_STARTED_AT", started_at)
        monkeypatch.setattr(
            routes_selftest, "_SCHEDULER_BOOT_GRACE_SECONDS", 1800
        )

        with get_db_session() as session:
            session.add(
                SchedulerHeartbeat(
                    name="scheduled_email_scheduler",
                    last_status="ok",
                    expected_interval_seconds=60,
                    last_run_at=started_at - timedelta(seconds=300),
                )
            )

        resp = client.get(
            "/api/_internal/scheduler-health",
            headers={"X-Observability-Token": "t-test-secret"},
        )

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "ok"
        assert body["stale_schedulers"] == []
        assert len(body["schedulers"]) == 1
        sched = body["schedulers"][0]
        assert sched["name"] == "scheduled_email_scheduler"
        assert sched["stale"] is False
        assert sched["boot_grace"] is True


class TestSchedulerHealthDegraded:
    def test_stale_heartbeat_returns_503(self, client, clean_heartbeats):
        """The whole reason this exists. Sentinel sees 503 → exit
        non-zero → alerter opens issue."""
        from app.db.database import get_db_session
        from app.db.models.scheduler_heartbeat import SchedulerHeartbeat

        with get_db_session() as session:
            session.add(
                SchedulerHeartbeat(
                    name="dead_scheduler",
                    last_status="ok",
                    expected_interval_seconds=60,
                    last_run_at=datetime.now(timezone.utc)
                    - timedelta(seconds=200),
                )
            )

        resp = client.get(
            "/api/_internal/scheduler-health",
            headers={"X-Observability-Token": "t-test-secret"},
        )
        assert resp.status_code == 503
        body = resp.get_json()
        assert body["status"] == "degraded"
        assert len(body["stale_schedulers"]) == 1
        assert body["stale_schedulers"][0]["name"] == "dead_scheduler"
        assert "elapsed_seconds" in body["stale_schedulers"][0]
        assert body["stale_schedulers"][0]["elapsed_seconds"] > 60

    def test_one_stale_one_alive_still_returns_503(
        self, client, clean_heartbeats
    ):
        """Any stale scheduler degrades the system — no 'majority rule'."""
        from app.services.scheduler_heartbeat import record_heartbeat
        from app.db.database import get_db_session
        from app.db.models.scheduler_heartbeat import SchedulerHeartbeat

        record_heartbeat(
            "alive_one", status="ok", expected_interval_seconds=60
        )
        with get_db_session() as session:
            session.add(
                SchedulerHeartbeat(
                    name="dead_one",
                    last_status="ok",
                    expected_interval_seconds=60,
                    last_run_at=datetime.now(timezone.utc)
                    - timedelta(seconds=300),
                )
            )

        resp = client.get(
            "/api/_internal/scheduler-health",
            headers={"X-Observability-Token": "t-test-secret"},
        )
        assert resp.status_code == 503
        body = resp.get_json()
        assert {s["name"] for s in body["stale_schedulers"]} == {"dead_one"}
        # The healthy one is still in `schedulers`, just marked stale=False.
        assert {s["name"] for s in body["schedulers"]} == {
            "alive_one",
            "dead_one",
        }
