# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import json
from datetime import datetime, timedelta, timezone

import pytest
from flask import Flask

from app.api import admin as admin_module
from app.api.admin import admin_bp
from app.api.auth import user_id_from_email
from app.infrastructure.database import Database


@pytest.fixture()
def admin_client(tmp_path, monkeypatch):
    from app.infrastructure import database as database_module

    old_initialized = Database._initialized
    old_connection = getattr(Database._local, "connection", None)
    if old_connection is not None:
        old_connection.close()
    Database._local.connection = None

    Database._initialized = False
    temp_db = Database(tmp_path / "agentys.db")
    temp_db.execute("CREATE TABLE IF NOT EXISTS accounts (id INTEGER PRIMARY KEY, email TEXT, user_id INTEGER)")
    temp_db.commit()
    monkeypatch.setattr(database_module, "db", temp_db)
    monkeypatch.setattr(admin_module, "_known_users_file_path", lambda: str(tmp_path / "known_users.json"))
    monkeypatch.setenv("AGENTYS_ADMIN_TOKEN", "test-admin-token")

    app = Flask(__name__)
    app.register_blueprint(admin_bp, url_prefix="/api/admin")

    try:
        yield app.test_client(), temp_db
    finally:
        temp_db.close()
        Database._initialized = old_initialized
        Database._local.connection = None


def test_ops_overview_requires_admin_token(admin_client):
    client, _ = admin_client

    response = client.get("/api/admin/ops/overview")

    assert response.status_code == 403


def test_db_browser_requires_admin_token(admin_client):
    client, _ = admin_client

    response = client.get("/api/admin/db/tables")

    assert response.status_code == 403


def test_db_browser_tables_expose_only_safe_columns(admin_client):
    client, _ = admin_client

    response = client.get(
        "/api/admin/db/tables",
        headers={"X-Admin-Token": "test-admin-token", "X-Admin-Actor": "Nat"},
    )

    assert response.status_code == 200
    tables = {table["name"]: table for table in response.get_json()["tables"]}
    assert "draft_history" in tables
    assert "api_usage_log" in tables
    assert "email_body" not in tables["draft_history"]["columns"]
    assert "draft_v1" not in tables["draft_history"]["columns"]
    assert "critique" not in tables["draft_history"]["columns"]
    assert "draft_final" not in tables["draft_history"]["columns"]


def test_db_browser_rows_are_paginated_and_searchable(admin_client):
    client, db = admin_client
    now = datetime.now(timezone.utc).isoformat()
    db.execute(
        """
        INSERT INTO api_usage_log (
            account_id, user_id, feature, provider, method, url_host, url_path,
            status_code, success, duration_ms, auth_present, auth_type, process_name, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (42, 7, "drafting", "anthropic", "POST", "api.anthropic.com", "/v1/messages", 200, 1, 450, 1, "header:x-api-key", "backend", now),
    )
    db.commit()

    response = client.get(
        "/api/admin/db/rows?table=api_usage_log&q=anthropic&limit=10&offset=0",
        headers={"X-Admin-Token": "test-admin-token", "X-Admin-Actor": "Nat"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["table"] == "api_usage_log"
    assert payload["total"] == 1
    assert payload["columns"] == [
        "id", "account_id", "user_id", "feature", "provider", "method",
        "url_host", "url_path", "status_code", "success", "duration_ms",
        "auth_present", "auth_type", "process_name", "created_at",
    ]
    assert payload["rows"][0]["provider"] == "anthropic"
    assert payload["rows"][0]["url_host"] == "api.anthropic.com"


def test_db_browser_rejects_unlisted_tables(admin_client):
    client, _ = admin_client

    response = client.get(
        "/api/admin/db/rows?table=sqlite_master",
        headers={"X-Admin-Token": "test-admin-token", "X-Admin-Actor": "Nat"},
    )

    assert response.status_code == 404


def test_llm_stats_accepts_server_to_server_admin_token(admin_client):
    client, _ = admin_client

    response = client.get(
        "/api/admin/llm-stats?days=7",
        headers={"X-Admin-Token": "test-admin-token", "X-Admin-Actor": "Nat"},
    )

    assert response.status_code == 200
    assert "token_writer" in response.get_json()


def test_ops_overview_returns_token_and_product_metrics(admin_client):
    client, db = admin_client
    base = datetime.now(timezone.utc).replace(hour=14, minute=30, second=0, microsecond=0)
    now = base.isoformat()
    previous = (base - timedelta(days=1)).replace(hour=9, minute=5).isoformat()
    db.execute("INSERT INTO accounts (id, email, user_id) VALUES (?, ?, ?)", (42, "nat@example.com", 7))
    db.execute(
        """
        INSERT INTO token_usage_log (
            account_id, agent_name, feature, model, input_tokens, output_tokens,
            cache_creation_input_tokens, cache_read_input_tokens, cost_usd, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (42, "DrafterAgent", "drafting", "claude-haiku-4-5-20251001", 1000, 500, 200, 300, 0.004, now),
    )
    db.execute(
        """
        INSERT INTO draft_history (email_id, status, tokens_used, model, processing_time_ms, feedback_score, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("email-1", "V1", 1500, "claude-haiku-4-5-20251001", 1200, 5, now),
    )
    db.execute(
        """
        INSERT INTO api_usage_log (
            account_id, user_id, feature, provider, method, url_host, url_path,
            status_code, success, duration_ms, auth_present, auth_type, process_name, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (42, None, "drafting", "anthropic", "POST", "api.anthropic.com", "/v1/messages", 200, 1, 450, 1, "header:x-api-key", "backend", now),
    )
    db.execute(
        """
        INSERT INTO api_usage_log (
            account_id, user_id, feature, provider, method, url_host, url_path,
            status_code, success, duration_ms, auth_present, auth_type, process_name, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (42, None, "drafting", "google", "GET", "www.googleapis.com", "/calendar/v3", 400, 0, 80, 1, "oauth", "scheduler", previous),
    )
    db.commit()

    response = client.get(
        "/api/admin/ops/overview?days=7",
        headers={"X-Admin-Token": "test-admin-token", "X-Admin-Actor": "Nat"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["summary"]["spend_usd"] == 0.004
    assert payload["summary"]["total_tokens"] == 2000
    assert payload["summary"]["draft_count"] == 1
    assert payload["summary"]["draft_latency_p95_ms"] == 1200
    assert payload["tokens"]["by_model"][0]["model"] == "claude-haiku-4-5-20251001"
    assert payload["tokens"]["by_user"][0]["user_id"] == 7
    assert payload["tokens"]["by_user"][0]["user_email"] == "nat@example.com"
    assert payload["tokens"]["by_user"][0]["tokens"] == 2000
    assert payload["tokens"]["top_features"][0]["feature"] == "drafting"
    assert payload["api_usage"]["total_calls"] == 2
    assert {row["provider"] for row in payload["api_usage"]["by_provider"]} == {"anthropic", "google"}
    assert payload["api_usage"]["top_users"][0]["user_id"] == 7
    assert payload["api_usage"]["top_users"][0]["user_email"] == "nat@example.com"
    assert payload["api_usage"]["top_users"][0]["user_label"] == "nat@example.com"
    assert payload["api_usage"]["top_users"][0]["account_count"] == 1
    assert payload["api_usage"]["top_users"][0]["calls"] == 2
    assert payload["api_usage"]["top_users"][0]["failure_count"] == 1
    assert payload["api_usage"]["top_users"][0]["accounts"][0]["account_label"] == "nat@example.com"
    assert {row["provider"] for row in payload["api_usage"]["top_users"][0]["providers"]} == {"anthropic", "google"}
    assert payload["api_usage"]["top_users"][0]["features"][0]["feature"] == "drafting"
    assert len(payload["api_usage"]["top_users"][0]["hourly"]) == 24
    assert payload["api_usage"]["top_users"][0]["hourly"][9]["calls"] == 1
    assert payload["api_usage"]["top_users"][0]["hourly"][14]["calls"] == 1
    assert len(payload["api_usage"]["top_users"][0]["daily"]) == 2
    assert {row["status_code"] for row in payload["api_usage"]["top_users"][0]["status_codes"]} == {"200", "400"}
    assert payload["api_usage"]["top_users"][0]["endpoints"][0]["host"] in {"api.anthropic.com", "www.googleapis.com"}
    assert {row["process_name"] for row in payload["api_usage"]["top_users"][0]["processes"]} == {"backend", "scheduler"}
    assert payload["api_usage"]["top_users"][0]["recent_failures"][0]["status_code"] == 400
    assert payload["api_usage"]["top_users"][0]["recent_failures"][0]["auth_type"] == "oauth"
    assert payload["security"]["admin_audit"][0]["actor"] == "Nat"


def test_ops_overview_resolves_user_email_from_known_users(admin_client):
    client, db = admin_client
    now = datetime.now(timezone.utc).isoformat()
    email = "alex@example.com"
    user_id = user_id_from_email(email)
    with open(admin_module._known_users_file_path(), "w", encoding="utf-8") as f:
        json.dump([{"email": email}], f)

    db.execute(
        """
        INSERT INTO api_usage_log (
            account_id, user_id, feature, provider, method, url_host, url_path,
            status_code, success, duration_ms, auth_present, auth_type, process_name, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (None, user_id, "calendar", "google", "GET", "www.googleapis.com", "/calendar/v3", 200, 1, 130, 1, "oauth", "backend", now),
    )
    db.commit()

    response = client.get(
        "/api/admin/ops/overview?days=7",
        headers={"X-Admin-Token": "test-admin-token", "X-Admin-Actor": "Alex"},
    )

    assert response.status_code == 200
    top_user = response.get_json()["api_usage"]["top_users"][0]
    assert top_user["user_id"] == user_id
    assert top_user["user_email"] == email
    assert top_user["user_label"] == email
    assert top_user["providers"][0]["provider"] == "google"
    assert top_user["features"][0]["feature"] == "calendar"


def test_ops_overview_summarizes_background_without_detail_breakdowns(admin_client):
    client, db = admin_client
    now = datetime.now(timezone.utc).isoformat()

    db.execute(
        """
        INSERT INTO api_usage_log (
            account_id, user_id, feature, provider, method, url_host, url_path,
            status_code, success, duration_ms, auth_present, auth_type, process_name, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (None, None, "sync", "gmail", "GET", "www.googleapis.com", "/gmail/v1", 200, 1, 120, 1, "oauth", "scheduler", now),
    )
    db.commit()

    response = client.get(
        "/api/admin/ops/overview?days=7",
        headers={"X-Admin-Token": "test-admin-token", "X-Admin-Actor": "Nat"},
    )

    assert response.status_code == 200
    background = response.get_json()["api_usage"]["top_users"][0]
    assert background["user_key"] == "background"
    assert background["calls"] == 1
    assert background["providers"] == []
    assert background["recent_failures"] == []
    assert len(background["hourly"]) == 24


def test_ops_overview_aggregates_claude_tokens_by_user(admin_client):
    client, db = admin_client
    now = datetime.now(timezone.utc).isoformat()
    email = "tokens@example.com"
    user_id = user_id_from_email(email)
    with open(admin_module._known_users_file_path(), "w", encoding="utf-8") as f:
        json.dump([{"email": email}], f)

    db.execute("INSERT INTO accounts (id, email, user_id) VALUES (?, ?, ?)", (42, "primary@example.com", user_id))
    db.execute("INSERT INTO accounts (id, email, user_id) VALUES (?, ?, ?)", (43, "secondary@example.com", user_id))
    db.execute("INSERT INTO accounts (id, email, user_id) VALUES (?, ?, ?)", (44, "openai@example.com", 99))
    db.execute(
        """
        INSERT INTO token_usage_log (
            account_id, user_id, agent_name, feature, model, input_tokens, output_tokens,
            cache_creation_input_tokens, cache_read_input_tokens, cost_usd, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (42, None, "DrafterAgent", "drafting", "claude-haiku-4-5-20251001", 100, 50, 25, 75, 0.001, now),
    )
    db.execute(
        """
        INSERT INTO token_usage_log (
            account_id, user_id, agent_name, feature, model, input_tokens, output_tokens,
            cache_creation_input_tokens, cache_read_input_tokens, cost_usd, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (43, user_id, "CriticAgent", "drafting", "claude-sonnet-4-6", 200, 80, 0, 20, 0.002, now),
    )
    db.execute(
        """
        INSERT INTO token_usage_log (
            account_id, user_id, agent_name, feature, model, input_tokens, output_tokens,
            cache_creation_input_tokens, cache_read_input_tokens, cost_usd, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (44, 99, "OpenAI", "other", "gpt-4o-mini", 900, 100, 0, 0, 0.003, now),
    )
    db.commit()

    response = client.get(
        "/api/admin/ops/overview?days=7",
        headers={"X-Admin-Token": "test-admin-token", "X-Admin-Actor": "Nat"},
    )

    assert response.status_code == 200
    by_user = response.get_json()["tokens"]["by_user"]
    assert len(by_user) == 1
    row = by_user[0]
    assert row["user_id"] == user_id
    assert row["user_email"] == email
    assert row["user_label"] == email
    assert row["account_count"] == 2
    assert set(row["account_labels"]) == {"primary@example.com", "secondary@example.com"}
    assert row["spend_usd"] == 0.003
    assert row["tokens"] == 550
    assert row["input_tokens"] == 300
    assert row["output_tokens"] == 130
    assert row["cache_creation_input_tokens"] == 25
    assert row["cache_read_input_tokens"] == 95
    assert row["request_count"] == 2


def test_ops_overview_prefers_canonical_token_rollup(admin_client, monkeypatch):
    client, _ = admin_client
    canonical = {
        "current": {
            "spend_usd": 0.1234,
            "total_tokens": 12345,
            "input_tokens": 9000,
            "output_tokens": 3000,
            "cache_creation_input_tokens": 100,
            "cache_read_input_tokens": 245,
            "request_count": 4,
        },
        "spend": 0.1234,
        "prev_spend": 0.01,
        "request_count": 4,
        "cache_hit_rate": 0.0262,
        "series": [
            {"date": "2026-05-20", "spend_usd": 0.1234, "tokens": 12345, "request_count": 4, "drafts": 0}
        ],
        "by_model": [
            {"model": "claude-haiku-4-5-20251001", "spend_usd": 0.1234, "tokens": 12345, "request_count": 4}
        ],
        "top_features": [
            {"feature": "drafting", "spend_usd": 0.1234, "tokens": 12345, "request_count": 4}
        ],
        "top_accounts": [
            {"account_id": 42, "account_label": "nat@example.com", "spend_usd": 0.1234, "tokens": 12345, "request_count": 4}
        ],
        "token_users": [
            {
                "user_key": "7",
                "user_id": 7,
                "user_email": "nat@example.com",
                "user_label": "nat@example.com",
                "account_count": 1,
                "account_labels": ["nat@example.com"],
                "spend_usd": 0.1234,
                "tokens": 12345,
                "input_tokens": 9000,
                "output_tokens": 3000,
                "cache_creation_input_tokens": 100,
                "cache_read_input_tokens": 245,
                "request_count": 4,
            }
        ],
    }
    monkeypatch.setattr(admin_module, "_canonical_token_rollup", lambda _days, _now: canonical)

    response = client.get(
        "/api/admin/ops/overview?days=7",
        headers={"X-Admin-Token": "test-admin-token", "X-Admin-Actor": "Nat"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["summary"]["total_tokens"] == 12345
    assert payload["summary"]["request_count"] == 4
    assert payload["tokens"]["by_model"][0]["tokens"] == 12345
    assert payload["tokens"]["top_accounts"][0]["account_label"] == "nat@example.com"
    assert payload["tokens"]["by_user"][0]["input_tokens"] == 9000
