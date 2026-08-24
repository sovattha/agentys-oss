# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Migration Alembic 046 — programme ambassadeur.

Exécute ``upgrade()`` / ``downgrade()`` contre une connexion SQLite éphémère
pour prouver que la migration est exécutable, réversible et idempotente.
"""

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect

MIGRATION = Path(
    "app/db/migrations/versions/20260618_000001_add_ambassador_program.py"
)
TABLES = {"ambassadors", "ambassador_referrals", "ambassador_commissions"}


def _load_migration():
    spec = importlib.util.spec_from_file_location("mig_ambassador", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_creates_tables_then_downgrade_drops_them():
    mig = _load_migration()
    engine = create_engine("sqlite://")
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            mig.upgrade()
        assert TABLES <= set(inspect(conn).get_table_names())

        with Operations.context(ctx):
            mig.downgrade()
        assert not (TABLES & set(inspect(conn).get_table_names()))


def test_upgrade_is_idempotent():
    mig = _load_migration()
    engine = create_engine("sqlite://")
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            mig.upgrade()
            mig.upgrade()  # rejouer ne doit pas lever
        assert TABLES <= set(inspect(conn).get_table_names())


def test_revision_chains_from_current_head():
    mig = _load_migration()
    assert mig.revision == "046_add_ambassador_program"
    assert mig.down_revision == "045_add_commitments"
