# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import time

from app.infrastructure.cost_manager import reset_usage_context, set_usage_context
from app.infrastructure.database import Database
from app.infrastructure import api_usage_probe


def test_api_usage_probe_records_authenticated_external_call(tmp_path, monkeypatch):
    from app.infrastructure import database as database_module

    old_initialized = Database._initialized
    old_connection = getattr(Database._local, "connection", None)
    if old_connection is not None:
        old_connection.close()
    Database._local.connection = None
    Database._initialized = False
    temp_db = Database(tmp_path / "agentys.db")
    monkeypatch.setattr(database_module, "db", temp_db)

    tokens = set_usage_context(account_id=42, user_id=7, feature="drafting")
    try:
        api_usage_probe._record_api_usage(
            "POST",
            "https://api.telegram.org/bot1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZ/sendMessage?token=secret",
            {"Authorization": "Bearer secret"},
            200,
            time.perf_counter() - 0.01,
            True,
        )
    finally:
        reset_usage_context(tokens)

    row = temp_db.fetchone("SELECT * FROM api_usage_log")
    assert row["account_id"] == 42
    assert row["user_id"] == 7
    assert row["feature"] == "drafting"
    assert row["provider"] == "telegram"
    assert row["url_host"] == "api.telegram.org"
    assert row["url_path"] == "/[redacted]/sendMessage"
    assert "secret" not in row["url_path"]
    assert row["auth_present"] == 1
    assert row["success"] == 1

    temp_db.close()
    Database._initialized = old_initialized
    Database._local.connection = None


def test_api_usage_probe_derives_user_id_from_account(tmp_path, monkeypatch):
    from app.infrastructure import database as database_module

    old_initialized = Database._initialized
    old_connection = getattr(Database._local, "connection", None)
    if old_connection is not None:
        old_connection.close()
    Database._local.connection = None
    Database._initialized = False
    temp_db = Database(tmp_path / "agentys.db")
    temp_db.execute("CREATE TABLE IF NOT EXISTS accounts (id INTEGER PRIMARY KEY, email TEXT, user_id INTEGER)")
    temp_db.execute("INSERT INTO accounts (id, email, user_id) VALUES (?, ?, ?)", (42, "nat@example.com", 7))
    temp_db.commit()
    monkeypatch.setattr(database_module, "db", temp_db)

    tokens = set_usage_context(account_id=42, user_id=None, feature="sync")
    try:
        api_usage_probe._record_api_usage(
            "GET",
            "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            {"Authorization": "Bearer secret"},
            200,
            time.perf_counter() - 0.01,
            True,
        )
    finally:
        reset_usage_context(tokens)

    row = temp_db.fetchone("SELECT account_id, user_id, feature, provider FROM api_usage_log")
    assert row["account_id"] == 42
    assert row["user_id"] == 7
    assert row["feature"] == "sync"
    assert row["provider"] == "gmail"

    temp_db.close()
    Database._initialized = old_initialized
    Database._local.connection = None


def test_api_usage_probe_skips_unknown_unauthenticated_call(tmp_path, monkeypatch):
    from app.infrastructure import database as database_module

    old_initialized = Database._initialized
    old_connection = getattr(Database._local, "connection", None)
    if old_connection is not None:
        old_connection.close()
    Database._local.connection = None
    Database._initialized = False
    temp_db = Database(tmp_path / "agentys.db")
    monkeypatch.setattr(database_module, "db", temp_db)

    api_usage_probe._record_api_usage(
        "GET",
        "https://example.org/public",
        {},
        200,
        time.perf_counter(),
        True,
    )

    row = temp_db.fetchone("SELECT COUNT(*) AS count FROM api_usage_log")
    assert row["count"] == 0

    temp_db.close()
    Database._initialized = old_initialized
    Database._local.connection = None
