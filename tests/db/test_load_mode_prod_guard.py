"""Guards for Railway-hosted mocked load-test services."""

from app.db import database


def test_load_test_mode_is_not_treated_as_production(monkeypatch):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
    monkeypatch.setenv("AGENTYS_LOAD_TEST_MODE", "true")

    assert database._is_production_environment() is False
