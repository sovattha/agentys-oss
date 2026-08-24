# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import pytest
from flask import Flask


@pytest.fixture()
def admin_client(tmp_path, monkeypatch):
    """Isolated admin blueprint client with both DB stacks on temp SQLite."""
    from app.api import admin as admin_module
    from app.api.admin import admin_bp
    from app.db import database as sql_database
    from app.infrastructure import database as legacy_database_module
    from app.infrastructure.database import Database

    old_initialized = Database._initialized
    old_connection = getattr(Database._local, "connection", None)
    if old_connection is not None:
        old_connection.close()
    Database._local.connection = None
    Database._initialized = False

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AGENTYS_DB_PATH", str(tmp_path / "sqlalchemy.db"))
    monkeypatch.setenv("AGENTYS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AGENTYS_ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setenv("COST_ENFORCEMENT_ENABLED", "true")
    monkeypatch.setenv("GLOBAL_MONTHLY_CAP_USD", "100")
    monkeypatch.setenv("USER_DAILY_CAP_USD", "10")
    monkeypatch.setenv("COST_WARN_PCT", "0.75")

    sql_database.reset_engine()
    sql_database.init_db()

    legacy_db = Database(tmp_path / "legacy.db")
    monkeypatch.setattr(legacy_database_module, "db", legacy_db)
    monkeypatch.setattr(
        admin_module,
        "_known_users_file_path",
        lambda: str(tmp_path / "known_users.json"),
    )

    from app.infrastructure import cost_enforcer

    cost_enforcer._cache_global = (0.0, 0.0)
    cost_enforcer._cache_user.clear()

    app = Flask(__name__)
    app.register_blueprint(admin_bp, url_prefix="/api/admin")

    try:
        yield app.test_client(), legacy_db
    finally:
        legacy_db.close()
        sql_database.reset_engine()
        Database._initialized = old_initialized
        Database._local.connection = None
