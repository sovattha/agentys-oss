# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Pytest fixture wiring for `tests/scripts/`.

Re-exports the SQLAlchemy session fixtures from `tests/db/_fixtures.py` so
migration script tests can use the same in-memory database setup the model
tests rely on.
"""

from tests.db._fixtures import (  # noqa: F401 — pytest fixture re-export
    engine,
    session,
    test_db_path,
)
