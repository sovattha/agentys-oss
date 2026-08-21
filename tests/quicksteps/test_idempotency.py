# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""IdempotencyStore — both MemoryIdempotencyStore (used in tests) and
SqliteIdempotencyStore (production cross-worker dedupe)."""
from __future__ import annotations

import time
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from sqlalchemy.orm import sessionmaker

from app.quicksteps.idempotency import (
    MemoryIdempotencyStore,
    SqliteIdempotencyStore,
)


# --------------------------------------------------------------------------- #
# MemoryIdempotencyStore
# --------------------------------------------------------------------------- #

class TestMemoryStore:
    def test_get_returns_none_for_missing_key(self):
        store = MemoryIdempotencyStore()
        assert store.get(1, "nope") is None

    def test_put_then_get_roundtrip(self):
        store = MemoryIdempotencyStore()
        store.put(1, "K", {"hello": "world"})
        assert store.get(1, "K") == {"hello": "world"}

    def test_account_scoping(self):
        store = MemoryIdempotencyStore()
        store.put(1, "K", {"who": "a"})
        store.put(2, "K", {"who": "b"})
        assert store.get(1, "K") == {"who": "a"}
        assert store.get(2, "K") == {"who": "b"}

    def test_empty_key_is_no_op(self):
        store = MemoryIdempotencyStore()
        store.put(1, "", {"hi": True})
        assert store.get(1, "") is None

    def test_ttl_expires_entries(self):
        store = MemoryIdempotencyStore(ttl_seconds=0.0)
        store.put(1, "K", {"x": 1})
        time.sleep(0.001)
        assert store.get(1, "K") is None

    def test_lru_eviction(self):
        store = MemoryIdempotencyStore(max_entries=3)
        for i in range(5):
            store.put(1, f"K{i}", {"i": i})
        # Oldest two evicted, newest three retained.
        assert store.get(1, "K0") is None
        assert store.get(1, "K1") is None
        assert store.get(1, "K2") == {"i": 2}
        assert store.get(1, "K4") == {"i": 4}

    def test_clear_resets_state(self):
        store = MemoryIdempotencyStore()
        store.put(1, "K", {"x": 1})
        store.clear()
        assert store.get(1, "K") is None


# --------------------------------------------------------------------------- #
# SqliteIdempotencyStore — uses the shared db fixture so we exercise the
# real schema (quick_step_executions table from migration 022).
# --------------------------------------------------------------------------- #

@pytest.fixture
def sqlite_store(engine):
    """Yield a SqliteIdempotencyStore wired to the test in-memory SQLite."""
    SessionLocal = sessionmaker(bind=engine, autoflush=False)

    @contextmanager
    def fake_session_cm():
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    with patch("app.db.database.get_db_session", fake_session_cm):
        yield SqliteIdempotencyStore()


class TestSqliteStore:
    def test_get_returns_none_for_missing_key(self, sqlite_store, sample_account):
        assert sqlite_store.get(sample_account.id, "missing") is None

    def test_put_then_get_roundtrip(self, sqlite_store, sample_account):
        sqlite_store.put(sample_account.id, "K", {"executed": 2, "success": True})
        assert sqlite_store.get(sample_account.id, "K") == {"executed": 2, "success": True}

    def test_account_scoping(self, sqlite_store, sample_account, sample_account_outlook):
        sqlite_store.put(sample_account.id, "K", {"who": "a"})
        sqlite_store.put(sample_account_outlook.id, "K", {"who": "b"})
        assert sqlite_store.get(sample_account.id, "K") == {"who": "a"}
        assert sqlite_store.get(sample_account_outlook.id, "K") == {"who": "b"}

    def test_unicode_payload(self, sqlite_store, sample_account):
        sqlite_store.put(sample_account.id, "K", {"name": "Élodie ✓"})
        assert sqlite_store.get(sample_account.id, "K") == {"name": "Élodie ✓"}

    def test_empty_key_is_no_op(self, sqlite_store, sample_account):
        sqlite_store.put(sample_account.id, "", {"hi": True})
        assert sqlite_store.get(sample_account.id, "") is None

    def test_duplicate_put_is_idempotent(self, sqlite_store, sample_account):
        # Two workers racing on the same idempotency key. The unique
        # constraint catches the second insert; we treat it as success.
        sqlite_store.put(sample_account.id, "RACE", {"v": 1})
        sqlite_store.put(sample_account.id, "RACE", {"v": 2})  # ignored
        # First write wins because the second hit IntegrityError.
        assert sqlite_store.get(sample_account.id, "RACE") == {"v": 1}

    def test_ttl_expires_entries(self, sqlite_store, sample_account):
        store = SqliteIdempotencyStore(ttl_seconds=0.0)
        # Re-attach the patched session by reusing the same fixture's patch.
        # The fixture's `with patch(...)` is still active in this test.
        store.put(sample_account.id, "K", {"x": 1})
        # Fast-forward: TTL=0 means anything older than now is stale.
        assert store.get(sample_account.id, "K") is None
