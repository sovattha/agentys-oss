# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests pour GET /api/version.

Contrat :
- Structure : { version, commit_sha, commit_short, branch, commit_message,
                commit_author, deployment_id, environment, started_at }
- Si les env vars RAILWAY_GIT_* sont absentes (local/dev) → `null` sur
  les champs commit/branch/deployment, `environment="local"`
- Si RAILWAY_GIT_COMMIT_SHA est set → `commit_sha` = full SHA, `commit_short` = 8 chars
- HTTP 200 toujours (endpoint public, pas d'auth)
"""

from __future__ import annotations

import pytest

pytest.importorskip("flask_cors")


@pytest.fixture
def client():
    from app.api.app import create_app
    app = create_app(config={"TESTING": True})
    return app.test_client()


EXPECTED_KEYS = {
    "version", "commit_sha", "commit_short", "branch",
    "commit_message", "commit_author", "deployment_id",
    "environment", "started_at",
}


def test_version_returns_expected_structure(client):
    response = client.get("/api/version")
    assert response.status_code == 200
    data = response.get_json()
    assert set(data.keys()) == EXPECTED_KEYS


def test_version_has_api_version(client):
    response = client.get("/api/version")
    assert response.get_json()["version"].startswith("1.0.0")


def test_version_null_git_fields_without_railway_env(client, monkeypatch):
    """En local/dev, sans env vars Railway, les champs git doivent être null."""
    for var in ("RAILWAY_GIT_COMMIT_SHA", "RAILWAY_GIT_BRANCH",
                "RAILWAY_GIT_COMMIT_MESSAGE", "RAILWAY_GIT_AUTHOR",
                "RAILWAY_DEPLOYMENT_ID"):
        monkeypatch.delenv(var, raising=False)

    data = client.get("/api/version").get_json()
    assert data["commit_sha"] is None
    assert data["commit_short"] is None
    assert data["branch"] is None
    assert data["commit_message"] is None
    assert data["commit_author"] is None
    assert data["deployment_id"] is None


def test_version_populates_git_fields_from_railway_env(client, monkeypatch):
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "fa3372ed1234567890abcdef" + "x" * 16)
    monkeypatch.setenv("RAILWAY_GIT_BRANCH", "main")
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_MESSAGE", "ci: retrigger workflows")
    monkeypatch.setenv("RAILWAY_GIT_AUTHOR", "Nathan")
    monkeypatch.setenv("RAILWAY_DEPLOYMENT_ID", "deploy-abc-123")
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")

    data = client.get("/api/version").get_json()
    assert data["commit_sha"] == ("fa3372ed1234567890abcdef" + "x" * 16)[:40]
    assert data["commit_short"] == "fa3372ed"
    assert data["branch"] == "main"
    assert data["commit_message"] == "ci: retrigger workflows"
    assert data["commit_author"] == "Nathan"
    assert data["deployment_id"] == "deploy-abc-123"
    assert data["environment"] == "production"


def test_version_environment_defaults_to_local(client, monkeypatch):
    for var in ("RAILWAY_ENVIRONMENT_NAME", "RAILWAY_ENVIRONMENT", "ENVIRONMENT"):
        monkeypatch.delenv(var, raising=False)

    assert client.get("/api/version").get_json()["environment"] == "local"


def test_version_truncates_long_commit_message(client, monkeypatch):
    """Garde-fou : un commit message géant ne doit pas polluer la réponse JSON."""
    huge = "x" * 500
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_MESSAGE", huge)

    data = client.get("/api/version").get_json()
    assert len(data["commit_message"]) == 200


def test_version_no_auth_required(client):
    """Endpoint public : aucun header Authorization ni X-Account-Id."""
    response = client.get("/api/version")
    assert response.status_code == 200
