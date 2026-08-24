# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Agentys Database Layer.

SQLAlchemy 2.x ORM with SQLite backend.
"""

from app.db.database import (
    get_engine,
    get_session,
    get_session_factory,
    init_db,
    get_db_path,
)

__all__ = [
    "get_engine",
    "get_session",
    "get_session_factory",
    "init_db",
    "get_db_path",
]
