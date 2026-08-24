# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from unittest.mock import patch


def test_health_capacity_reports_ok_when_queue_is_clear():
    from app.api.app import create_app

    app = create_app(config={"TESTING": True})
    stats = {
        "queue_depth": 10,
        "queue_max": 200,
        "max_workers": 16,
        "per_account_max": 4,
        "per_account_queue_max": 50,
        "active_workers": 2,
        "jobs_total": 12,
        "rejected_total": 0,
    }

    with patch("app.infrastructure.draft_job_queue.get_draft_queue_stats", return_value=stats):
        response = app.test_client().get("/api/health/capacity")

    data = response.get_json()
    assert response.status_code == 200
    assert data["status"] == "ok"
    assert data["draft_queue"]["queue_utilization"] == 0.05
    assert data["draft_queue"]["worker_utilization"] == 0.125


def test_health_capacity_reports_saturated_when_queue_is_nearly_full():
    from app.api.app import create_app

    app = create_app(config={"TESTING": True})
    stats = {
        "queue_depth": 196,
        "queue_max": 200,
        "max_workers": 16,
        "per_account_max": 4,
        "per_account_queue_max": 50,
        "active_workers": 16,
        "jobs_total": 212,
        "rejected_total": 42,
    }

    with patch("app.infrastructure.draft_job_queue.get_draft_queue_stats", return_value=stats):
        response = app.test_client().get("/api/health/capacity")

    data = response.get_json()
    assert response.status_code == 200
    assert data["status"] == "saturated"
    assert "draft_queue_critical" in data["reasons"]
    assert data["draft_queue"]["queue_utilization"] == 0.98
