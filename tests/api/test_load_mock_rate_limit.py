# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from flask import Flask

from app.api import routes_emails
from app.providers.mock_load_provider import LoadTestEmailProvider


def test_mock_load_rate_limit_bypass_requires_explicit_mock_load_mode(monkeypatch):
    app = Flask(__name__)
    monkeypatch.setenv("AGENTYS_LOAD_TEST_MODE", "true")
    monkeypatch.setenv("AGENTYS_MOCK_LLM", "true")
    monkeypatch.setenv("AGENTYS_MOCK_EMAIL_PROVIDER", "true")
    monkeypatch.setenv("AGENTYS_LOAD_TEST_BYPASS_RATE_LIMIT", "true")

    with app.test_request_context("/", environ_base={"REMOTE_ADDR": "203.0.113.10"}):
        assert routes_emails._mock_load_test_rate_limit_bypass() is True

    monkeypatch.delenv("AGENTYS_LOAD_TEST_BYPASS_RATE_LIMIT")
    with app.test_request_context("/", environ_base={"REMOTE_ADDR": "127.0.0.1"}):
        assert routes_emails._mock_load_test_rate_limit_bypass() is False


def test_mock_load_account_header_allows_remote_mock_partitions(monkeypatch):
    app = Flask(__name__)
    monkeypatch.setenv("AGENTYS_LOAD_TEST_MODE", "true")
    monkeypatch.setenv("AGENTYS_MOCK_LLM", "true")
    monkeypatch.setenv("AGENTYS_MOCK_EMAIL_PROVIDER", "true")

    with app.test_request_context(
        "/",
        headers={"X-Account-Id": "42"},
        environ_base={"REMOTE_ADDR": "203.0.113.10"},
    ):
        assert routes_emails._mock_load_test_account_header() == 42


def test_load_provider_probe_is_closed_outside_load_mode():
    from app.api.app import create_app

    app = create_app(config={"TESTING": True})

    response = app.test_client().get("/api/load-test/provider-probe")

    assert response.status_code == 404


def test_load_provider_probe_reports_mock_outlook(monkeypatch):
    from app.api.app import create_app

    LoadTestEmailProvider.reset_quota_state()
    monkeypatch.setenv("AGENTYS_LOAD_TEST_MODE", "true")
    monkeypatch.setenv("AGENTYS_MOCK_EMAIL_PROVIDER", "true")
    monkeypatch.setenv("AGENTYS_MOCK_EMAIL_PROVIDER_KIND", "outlook")
    app = create_app(config={"TESTING": True})

    response = app.test_client().get(
        "/api/load-test/provider-probe",
        query_string={"operation": "detail", "message_id": "load-email-1"},
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["provider"] == "outlook"
    assert data["operation"] == "detail"
    assert data["count"] == 1


def test_load_provider_probe_can_override_provider_kind_per_request(monkeypatch):
    from app.api.app import create_app

    LoadTestEmailProvider.reset_quota_state()
    monkeypatch.setenv("AGENTYS_LOAD_TEST_MODE", "true")
    monkeypatch.setenv("AGENTYS_MOCK_EMAIL_PROVIDER", "true")
    monkeypatch.setenv("AGENTYS_MOCK_EMAIL_PROVIDER_KIND", "outlook")
    app = create_app(config={"TESTING": True})

    response = app.test_client().get(
        "/api/load-test/provider-probe",
        query_string={
            "operation": "detail",
            "provider_kind": "gmail",
            "message_id": "load-email-1",
        },
    )

    assert response.status_code == 200
    assert response.get_json()["provider"] == "gmail"


def test_load_provider_probe_surfaces_provider_backoff(monkeypatch):
    from app.api.app import create_app

    LoadTestEmailProvider.reset_quota_state()
    monkeypatch.setenv("AGENTYS_LOAD_TEST_MODE", "true")
    monkeypatch.setenv("AGENTYS_MOCK_EMAIL_PROVIDER", "true")
    monkeypatch.setenv("AGENTYS_MOCK_EMAIL_PROVIDER_KIND", "outlook")
    monkeypatch.setenv("AGENTYS_MOCK_OUTLOOK_DETAIL_BACKOFF_EVERY", "1")
    monkeypatch.setenv("AGENTYS_MOCK_OUTLOOK_BACKOFF_SECONDS", "7")
    app = create_app(config={"TESTING": True})

    response = app.test_client().get(
        "/api/load-test/provider-probe",
        query_string={"operation": "detail", "message_id": "load-email-1"},
    )

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "7"
    assert response.get_json()["provider"] == "outlook"
    LoadTestEmailProvider.reset_quota_state()
