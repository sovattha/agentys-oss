# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests for the SQLite to Postgres migration helper."""

from sqlalchemy import Boolean, Column, DateTime, Integer, MetaData, String, Table
from sqlalchemy import create_engine

from app.db.models import Base
from scripts import migrate_sqlite_to_postgres as migration_script
from scripts.migrate_sqlite_to_postgres import _coerce_row, migrate


def test_coerce_row_casts_integer_strings():
    table = Table(
        "sample",
        MetaData(),
        Column("id", Integer),
        Column("enabled", Boolean),
        Column("created_at", DateTime),
        Column("name", String),
    )

    row = _coerce_row(
        {
            "id": "3",
            "enabled": 1,
            "created_at": "2026-05-12T22:10:58",
            "name": "FAQ",
        },
        table,
    )

    assert row["id"] == 3
    assert row["enabled"] is True
    assert row["created_at"].year == 2026
    assert row["name"] == "FAQ"


def test_migrate_uses_alembic_upgrade_instead_of_manual_head_stamp(monkeypatch, tmp_path):
    source_engine = create_engine("sqlite:///:memory:")
    target_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(source_engine)

    upgrade_calls: list[str] = []

    def fake_upgrade_target_schema(target_url: str) -> None:
        upgrade_calls.append(target_url)
        Base.metadata.create_all(target_engine)

    def fail_manual_stamp(_engine):
        raise AssertionError("manual alembic stamp must be skipped after upgrade head")

    monkeypatch.setattr(
        migration_script,
        "_source_sqlite_engine",
        lambda _source_path: source_engine,
    )
    monkeypatch.setattr(
        migration_script,
        "_target_postgres_engine",
        lambda _target_url: target_engine,
    )
    monkeypatch.setattr(
        migration_script,
        "_upgrade_target_schema",
        fake_upgrade_target_schema,
    )
    monkeypatch.setattr(migration_script, "_stamp_alembic_head", fail_manual_stamp)
    monkeypatch.setattr(migration_script, "_reset_postgres_sequences", lambda _engine: None)

    result = migrate(
        source_path=tmp_path / "source.db",
        target_url="postgresql://agentys:test@example.invalid/agentys",
        batch_size=100,
        dry_run=False,
        truncate_target=False,
        create_schema=True,
        stamp_head=True,
    )

    assert result == 0
    assert upgrade_calls == ["postgresql://agentys:test@example.invalid/agentys"]
