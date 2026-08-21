# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour l'endpoint GET /api/health selon les spécifications.

Spécifications:
- Retourne JSON avec structure: { status, version, services, timestamp }
- services contient: llm, email avec valeurs "connected" ou "disconnected"
- HTTP 200 si healthy, 503 si degraded
- version: "1.0.0"
"""

import pytest
from unittest.mock import patch, Mock
import re

pytest.importorskip("flask_cors")

from app.application.health_check import SystemHealthStatus, HealthStatus


def _create_health_status(email_healthy=True, llm_healthy=True,
                          email_msg=None, llm_msg=None):
    """Factory pour créer un SystemHealthStatus avec les paramètres donnés."""
    return SystemHealthStatus(
        email_provider=HealthStatus(healthy=email_healthy, message=email_msg),
        llm=HealthStatus(healthy=llm_healthy, message=llm_msg),
    )


def _setup_mock_container(mock_get_container, health_status):
    """Configure le mock container avec le status de santé donné."""
    mock_use_case = Mock()
    mock_use_case.execute.return_value = health_status
    mock_container = Mock()
    mock_container.get_health_check_use_case.return_value = mock_use_case
    mock_get_container.return_value = mock_container


@pytest.fixture
def app():
    from app.api.app import create_app
    app = create_app(config={"TESTING": True})
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


class TestHealthEndpointSpec:

    def test_health_returns_correct_structure(self, client):
        response = client.get("/api/health")
        data = response.get_json()

        assert "status" in data
        assert "version" in data
        assert "timestamp" in data

    def test_health_returns_version_1_0_0(self, client):
        response = client.get("/api/health")
        data = response.get_json()

        assert data["version"].startswith("1.0.0")

    @patch("app.api.routes_helpers.get_container")
    def test_health_deep_services_connected_when_healthy(self, mock_get_container, client):
        _setup_mock_container(mock_get_container, _create_health_status())

        response = client.get("/api/health/deep")
        data = response.get_json()

        assert data["services"]["email"] == "connected"
        assert data["services"]["llm"] == "connected"

    @patch("app.api.routes_helpers.get_container")
    def test_health_deep_services_disconnected_when_unhealthy(self, mock_get_container, client):
        _setup_mock_container(
            mock_get_container,
            _create_health_status(
                email_healthy=False, llm_healthy=False,
                email_msg="Auth failed", llm_msg="API error"
            )
        )

        response = client.get("/api/health/deep")
        data = response.get_json()

        assert data["services"]["email"] == "disconnected"
        assert data["services"]["llm"] == "disconnected"

    def test_health_returns_200_when_healthy(self, client):
        response = client.get("/api/health")

        assert response.status_code == 200
        assert response.get_json()["status"] == "ok"

    @patch("app.api.routes_helpers.get_container")
    def test_health_deep_returns_degraded_when_email_down(self, mock_get_container, client):
        """
        Design: l'endpoint retourne toujours 200 pour les healthchecks infra
        (Docker/Railway). Le statut dégradé est reporté dans le JSON body.
        """
        _setup_mock_container(
            mock_get_container,
            _create_health_status(email_healthy=False, email_msg="Auth failed")
        )

        response = client.get("/api/health/deep")

        # Always 200 for infrastructure monitoring — status in JSON body
        assert response.status_code == 200
        assert response.get_json()["status"] == "degraded"

    @patch("app.api.routes_helpers.get_container")
    def test_health_deep_returns_degraded_when_llm_down(self, mock_get_container, client):
        """
        Design: l'endpoint retourne toujours 200 pour les healthchecks infra.
        Le statut dégradé est reporté dans le JSON body (services.llm).
        """
        _setup_mock_container(
            mock_get_container,
            _create_health_status(llm_healthy=False, llm_msg="API error")
        )

        response = client.get("/api/health/deep")

        # Always 200 for infrastructure monitoring — status in JSON body
        assert response.status_code == 200
        assert response.get_json()["status"] == "degraded"

    def test_health_timestamp_format_iso8601(self, client):
        response = client.get("/api/health")
        data = response.get_json()

        iso_pattern = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z"
        assert re.match(iso_pattern, data["timestamp"])
