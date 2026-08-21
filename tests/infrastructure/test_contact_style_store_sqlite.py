# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests for :class:`SqliteContactStyleStore` (PR6 follow-up).

Covers :
    - schema bootstrap is idempotent (calling twice doesn't error)
    - CRUD round-trips preserve every field of ``ContactStyleProfile``
      (including PR5's ``formality_pending``)
    - ``account_id`` scoping prevents cross-account leakage
    - case-insensitive email lookup
    - the ``migrate_json_to_sqlite`` helper round-trips a legacy dict
"""

from __future__ import annotations


import pytest

from app.domain.entities.writing_style import (
    ContactStyleProfile,
    FormalityLevel,
)
from app.infrastructure.contact_style_store_sqlite import (
    SqliteContactStyleStore,
    migrate_json_to_sqlite,
)


# Use an in-memory SQLite engine isolated from the production DB. We patch
# `app.db.database.get_db_session` so the adapter's calls hit the test
# engine instead of the user's real `~/.agentys/data/agentys.db`.


@pytest.fixture
def isolated_session(tmp_path, monkeypatch):
    """Spin up an isolated SQLite file under tmp_path and patch the
    `get_db_session` context manager used by the adapter. The fixture
    yields a freshly instantiated store with the schema applied."""
    from contextlib import contextmanager
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    db_path = tmp_path / "test_contact_styles.sqlite"
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    @contextmanager
    def _fake_session():
        s = SessionLocal()
        try:
            yield s
        finally:
            s.close()

    monkeypatch.setattr(
        "app.infrastructure.contact_style_store_sqlite.get_db_session",
        _fake_session,
    )
    yield


@pytest.fixture
def store(isolated_session) -> SqliteContactStyleStore:
    return SqliteContactStyleStore()


# ── Schema bootstrap ─────────────────────────────────────────────────────


def test_schema_bootstrap_is_idempotent(isolated_session) -> None:
    """Constructing the store twice MUST NOT raise (table already exists)."""
    SqliteContactStyleStore()
    SqliteContactStyleStore()


# ── CRUD round-trips ─────────────────────────────────────────────────────


def test_upsert_then_get_roundtrips_every_field(store: SqliteContactStyleStore) -> None:
    profile = ContactStyleProfile(
        email="alice@example.com",
        formality_override=FormalityLevel.FORMAL,
        formality_pending=FormalityLevel.MIXED,  # PR5
        formality_locked=True,
        formality_updated_at="2026-05-01T12:00:00+00:00",
        preferred_greeting="Bonjour {first_name},",
        preferred_closing="Cordialement,",
        langue="français",
        langue_variante="fr-CA",
        nickname="Ali",
    )
    assert store.upsert(account_id=1, profile=profile) is True

    loaded = store.get(account_id=1, email="alice@example.com")
    assert loaded is not None
    assert loaded.email == "alice@example.com"
    assert loaded.formality_override == FormalityLevel.FORMAL
    assert loaded.formality_pending == FormalityLevel.MIXED
    assert loaded.formality_locked is True
    assert loaded.formality_updated_at == "2026-05-01T12:00:00+00:00"
    assert loaded.preferred_greeting == "Bonjour {first_name},"
    assert loaded.preferred_closing == "Cordialement,"
    assert loaded.langue == "français"
    assert loaded.langue_variante == "fr-CA"
    assert loaded.nickname == "Ali"


def test_upsert_replaces_existing_row(store: SqliteContactStyleStore) -> None:
    base = ContactStyleProfile(email="bob@example.com", nickname="Bob")
    store.upsert(account_id=1, profile=base)

    updated = ContactStyleProfile(
        email="bob@example.com",
        nickname="Robert",
        formality_override=FormalityLevel.CASUAL,
    )
    store.upsert(account_id=1, profile=updated)

    loaded = store.get(account_id=1, email="bob@example.com")
    assert loaded is not None
    assert loaded.nickname == "Robert"
    assert loaded.formality_override == FormalityLevel.CASUAL


def test_get_returns_none_for_missing_email(store: SqliteContactStyleStore) -> None:
    assert store.get(account_id=1, email="nobody@example.com") is None


def test_get_is_case_insensitive_on_email(store: SqliteContactStyleStore) -> None:
    store.upsert(
        account_id=1,
        profile=ContactStyleProfile(email="Mixed.Case@Example.COM", nickname="Mc"),
    )
    assert store.get(account_id=1, email="mixed.case@example.com") is not None
    assert store.get(account_id=1, email="MIXED.CASE@EXAMPLE.COM") is not None


def test_delete_removes_row(store: SqliteContactStyleStore) -> None:
    store.upsert(account_id=1, profile=ContactStyleProfile(email="a@b.c"))
    assert store.delete(account_id=1, email="a@b.c") is True
    assert store.get(account_id=1, email="a@b.c") is None
    # Second delete is idempotent (returns False, doesn't raise)
    assert store.delete(account_id=1, email="a@b.c") is False


# ── Account scoping ──────────────────────────────────────────────────────


def test_get_does_not_cross_accounts(store: SqliteContactStyleStore) -> None:
    """Two different accounts can use the same contact email without leakage."""
    store.upsert(
        account_id=1,
        profile=ContactStyleProfile(email="shared@example.com", nickname="ForAcct1"),
    )
    store.upsert(
        account_id=2,
        profile=ContactStyleProfile(email="shared@example.com", nickname="ForAcct2"),
    )

    p1 = store.get(account_id=1, email="shared@example.com")
    p2 = store.get(account_id=2, email="shared@example.com")
    assert p1 is not None and p1.nickname == "ForAcct1"
    assert p2 is not None and p2.nickname == "ForAcct2"


def test_list_for_account_returns_only_that_accounts_rows(
    store: SqliteContactStyleStore,
) -> None:
    store.upsert(account_id=1, profile=ContactStyleProfile(email="a@x.c", nickname="A"))
    store.upsert(account_id=1, profile=ContactStyleProfile(email="b@x.c", nickname="B"))
    store.upsert(account_id=2, profile=ContactStyleProfile(email="c@x.c", nickname="C"))

    acct1 = store.list_for_account(1)
    assert len(acct1) == 2
    assert {p.email for p in acct1} == {"a@x.c", "b@x.c"}

    acct2 = store.list_for_account(2)
    assert len(acct2) == 1
    assert acct2[0].nickname == "C"


def test_count_for_account(store: SqliteContactStyleStore) -> None:
    assert store.count_for_account(1) == 0
    store.upsert(account_id=1, profile=ContactStyleProfile(email="a@x.c"))
    store.upsert(account_id=1, profile=ContactStyleProfile(email="b@x.c"))
    assert store.count_for_account(1) == 2
    assert store.count_for_account(2) == 0


# ── Atomic replace ───────────────────────────────────────────────────────


def test_replace_account_clears_then_inserts(store: SqliteContactStyleStore) -> None:
    store.upsert(account_id=1, profile=ContactStyleProfile(email="old@x.c"))
    store.upsert(account_id=2, profile=ContactStyleProfile(email="other@x.c"))

    new_profiles = [
        ContactStyleProfile(email="fresh1@x.c", nickname="F1"),
        ContactStyleProfile(email="fresh2@x.c", nickname="F2"),
    ]
    inserted = store.replace_account(account_id=1, profiles=new_profiles)
    assert inserted == 2

    # Account 1 has only the fresh rows
    acct1_emails = {p.email for p in store.list_for_account(1)}
    assert acct1_emails == {"fresh1@x.c", "fresh2@x.c"}

    # Account 2 is untouched
    assert {p.email for p in store.list_for_account(2)} == {"other@x.c"}


def test_replace_account_skips_profiles_with_empty_email(
    store: SqliteContactStyleStore,
) -> None:
    inserted = store.replace_account(
        account_id=1,
        profiles=[
            ContactStyleProfile(email=""),
            ContactStyleProfile(email="real@x.c"),
        ],
    )
    assert inserted == 1
    assert len(store.list_for_account(1)) == 1


# ── JSON → SQLite migration helper ───────────────────────────────────────


def test_migrate_json_to_sqlite_round_trips_a_legacy_dict(
    store: SqliteContactStyleStore,
) -> None:
    """Simulates the production ``WritingStyleProfile.contact_profiles``
    dict and copies it into the SQLite store via the helper."""
    legacy = {
        "alice@example.com": {
            "email": "alice@example.com",
            "formality_override": "casual",
            "preferred_greeting": "Salut Alice,",
            "nickname": "Ali",
            "langue": "français",
            "langue_variante": "fr-CA",
        },
        "bob@example.com": {
            "email": "bob@example.com",
            "formality_override": "formal",
            "preferred_closing": "Cordialement,",
        },
        # Malformed entry (str instead of dict) — must NOT crash the migration
        "garbage": "this should be skipped",
    }

    inserted = migrate_json_to_sqlite(
        account_id=42, contact_profiles_dict=legacy, store=store
    )
    assert inserted == 2

    alice = store.get(account_id=42, email="alice@example.com")
    assert alice is not None
    assert alice.formality_override == FormalityLevel.CASUAL
    assert alice.nickname == "Ali"
    assert alice.langue_variante == "fr-CA"

    bob = store.get(account_id=42, email="bob@example.com")
    assert bob is not None
    assert bob.formality_override == FormalityLevel.FORMAL
    assert bob.preferred_closing == "Cordialement,"


def test_migrate_is_idempotent(store: SqliteContactStyleStore) -> None:
    """Running the migration twice with the same input is a no-op (final
    state matches the input). This is what makes it safe to call at boot."""
    legacy = {
        "alice@example.com": {
            "email": "alice@example.com",
            "nickname": "Ali",
        },
    }
    migrate_json_to_sqlite(account_id=1, contact_profiles_dict=legacy, store=store)
    count_after_first = store.count_for_account(1)

    migrate_json_to_sqlite(account_id=1, contact_profiles_dict=legacy, store=store)
    count_after_second = store.count_for_account(1)

    assert count_after_first == count_after_second == 1
