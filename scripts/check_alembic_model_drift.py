#!/usr/bin/env python
# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Fail when Alembic-built schema drifts from SQLAlchemy metadata."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine
from sqlalchemy.schema import Table

from app.db.database import reset_engine
from app.db.models import Base


def _is_ignored_sqlite_fts_diff(diff: Any) -> bool:
    if not isinstance(diff, tuple):
        return False
    if len(diff) < 2 or diff[0] != "remove_table":
        return False
    table = diff[1]
    return isinstance(table, Table) and table.name.startswith("emails_fts")


def _is_ignored_diff(diff: Any) -> bool:
    return _is_ignored_sqlite_fts_diff(diff)


def _upgrade_fresh_sqlite(db_path: Path) -> None:
    previous_db_path = os.environ.get("AGENTYS_DB_PATH")
    previous_database_url = os.environ.pop("DATABASE_URL", None)
    os.environ["AGENTYS_DB_PATH"] = str(db_path)
    reset_engine()
    try:
        command.upgrade(Config("alembic.ini"), "head")
    finally:
        reset_engine()
        if previous_db_path is None:
            os.environ.pop("AGENTYS_DB_PATH", None)
        else:
            os.environ["AGENTYS_DB_PATH"] = previous_db_path
        if previous_database_url is not None:
            os.environ["DATABASE_URL"] = previous_database_url


def collect_unexpected_diffs(db_path: Path) -> list[Any]:
    _upgrade_fresh_sqlite(db_path)
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection,
                opts={"compare_type": True, "compare_server_default": False},
            )
            diffs = compare_metadata(context, Base.metadata)
    finally:
        engine.dispose()
    return [diff for diff in diffs if not _is_ignored_diff(diff)]


def main() -> int:
    with tempfile.TemporaryDirectory() as tmpdir:
        unexpected = collect_unexpected_diffs(Path(tmpdir) / "agentys_drift_gate.db")

    if not unexpected:
        print("Alembic schema contract OK: no unexpected model drift.")
        return 0

    print("Alembic schema contract FAILED: unexpected model drift detected.")
    for diff in unexpected:
        print(repr(diff))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
