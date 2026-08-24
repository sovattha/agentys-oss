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
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.account_identity import user_id_from_email
from app.db.models import Account, Base
from app.db.maintenance import (
    checkpoint_wal,
    find_account_user_id_drifts,
    repair_account_user_id,
    repair_all_account_user_ids,
)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys = ON")
        cur.close()

    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False)
    session = SessionLocal()
    yield session
    session.rollback()
    session.close()
    engine.dispose()


def test_repair_account_user_id_updates_stale_non_null_hash(db_session):
    account = Account(
        email="nathanroy@gmail.com",
        provider="gmail",
        user_id=32691,
        is_active=True,
    )
    other = Account(
        email="other@example.com",
        provider="gmail",
        user_id=123,
        is_active=True,
    )
    db_session.add_all([account, other])
    db_session.commit()

    repaired = repair_account_user_id(
        db_session,
        auth_email="NathanRoy@gmail.com",
        user_id=user_id_from_email("nathanroy@gmail.com"),
        source="test",
    )

    assert repaired == 1
    assert account.user_id == user_id_from_email("nathanroy@gmail.com")
    assert other.user_id == 123


def test_repair_account_user_id_updates_legacy_null_hash(db_session):
    account = Account(
        email="legacy@example.com",
        provider="gmail",
        user_id=None,
        is_active=True,
    )
    db_session.add(account)
    db_session.commit()

    repaired = repair_account_user_id(
        db_session,
        auth_email="legacy@example.com",
        source="test",
    )

    assert repaired == 1
    assert account.user_id == user_id_from_email("legacy@example.com")


def test_find_and_repair_all_account_user_id_drifts(db_session):
    stale = Account(
        email="stale@example.com",
        provider="gmail",
        user_id=42,
        is_active=True,
    )
    valid = Account(
        email="valid@example.com",
        provider="outlook",
        user_id=user_id_from_email("valid@example.com"),
        is_active=True,
    )
    db_session.add_all([stale, valid])
    db_session.commit()

    drifts = find_account_user_id_drifts(db_session)
    assert len(drifts) == 1
    assert drifts[0]["account_id"] == stale.id
    assert drifts[0]["email"].startswith("st***e@")

    assert repair_all_account_user_ids(db_session) == 1
    assert find_account_user_id_drifts(db_session) == []
    assert stale.user_id == user_id_from_email("stale@example.com")


def test_repair_all_skips_legacy_null_accounts_by_default(db_session):
    legacy = Account(
        email="desktop-legacy@example.com",
        provider="gmail",
        user_id=None,
        is_active=True,
    )
    db_session.add(legacy)
    db_session.commit()

    assert find_account_user_id_drifts(db_session) == []
    assert repair_all_account_user_ids(db_session) == 0
    assert legacy.user_id is None

    assert len(find_account_user_id_drifts(db_session, include_null=True)) == 1


def test_checkpoint_wal_skips_non_sqlite_backend(monkeypatch):
    class FakeDialect:
        name = "postgresql"

    class FakeEngine:
        dialect = FakeDialect()

        def connect(self):  # pragma: no cover - should never be called
            raise AssertionError("Postgres must not receive SQLite PRAGMA")

    monkeypatch.setattr("app.db.maintenance.get_engine", lambda: FakeEngine())

    result = checkpoint_wal(source="test")

    assert result["skipped"] is True
    assert result["reason"] == "unsupported dialect: postgresql"
    assert result["result"] == []
