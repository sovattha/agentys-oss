# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import sqlite3

from app.infrastructure.database import Database


def test_database_boot_adds_usage_columns_before_indexes(tmp_path):
    db_path = tmp_path / "agentys.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE token_usage_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model TEXT,
            created_at TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE api_usage_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT,
            created_at TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()

    old_initialized = Database._initialized
    old_connection = getattr(Database._local, "connection", None)
    if old_connection is not None:
        old_connection.close()
    Database._local.connection = None
    Database._initialized = False

    db = Database(db_path)
    try:
        token_columns = {row["name"] for row in db.fetchall("PRAGMA table_info(token_usage_log)")}
        api_columns = {row["name"] for row in db.fetchall("PRAGMA table_info(api_usage_log)")}
        indexes = {row["name"] for row in db.fetchall("SELECT name FROM sqlite_master WHERE type = 'index'")}

        assert {"account_id", "user_id", "agent", "feature", "cache_read_input_tokens"} <= token_columns
        assert {"account_id", "user_id", "feature", "url_host", "auth_type"} <= api_columns
        assert "idx_token_usage_feature_created" in indexes
        assert "idx_api_usage_feature_created" in indexes
    finally:
        db.close()
        Database._initialized = old_initialized
        Database._local.connection = None
