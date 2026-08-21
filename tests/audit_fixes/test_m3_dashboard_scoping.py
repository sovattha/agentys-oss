"""M-3: dashboard.get_stats must be scoped per account (no cross-account leak).

The legacy Tauri-only HTML dashboard (`app/dashboard.py`) used to call
`history.get_stats()` (unscoped), which both:
  1. Threw AttributeError on the SQLite adapter (no such method)
  2. Would have leaked across accounts if it had existed

Fix: `SqliteDraftHistoryAdapter.get_stats_for_account(account_id)` returns
stats filtered by account_id and returns empty stats for account_id <= 0.
"""

from __future__ import annotations

import sqlite3

import pytest

from app.domain.entities.draft_history import DraftRecord
from app.infrastructure.adapters.sqlite_learning_store import SqliteDraftHistoryAdapter


class _InMemoryDb:
    """Minimal Database-compatible wrapper for SqliteDraftHistoryAdapter."""

    def __init__(self) -> None:
        self._conn = sqlite3.connect(":memory:")
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(
            """
            CREATE TABLE draft_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER,
                email_id TEXT NOT NULL,
                email_sender TEXT,
                email_subject TEXT,
                email_body TEXT,
                draft_v1 TEXT,
                critique TEXT,
                draft_final TEXT,
                status TEXT,
                draft_id TEXT,
                tokens_used INTEGER DEFAULT 0,
                model TEXT,
                processing_time_ms INTEGER,
                priority_score INTEGER DEFAULT 50,
                category TEXT DEFAULT 'NORMAL',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                feedback TEXT,
                feedback_score INTEGER
            );
            """
        )

    def execute(self, query, params=()):
        return self._conn.execute(query, params)

    def fetchone(self, query, params=()):
        return self._conn.execute(query, params).fetchone()

    def fetchall(self, query, params=()):
        return self._conn.execute(query, params).fetchall()

    def commit(self):
        self._conn.commit()


@pytest.fixture
def adapter():
    return SqliteDraftHistoryAdapter(_InMemoryDb())


def _make_record(account_id: int, idx: int, status: str = "V1",
                 category: str = "NORMAL") -> DraftRecord:
    return DraftRecord(
        id=f"draft-{account_id}-{idx}",
        timestamp="2026-04-26T10:00:00",
        email_id=f"email-{account_id}-{idx}",
        email_sender=f"alice{idx}@account{account_id}.com",
        email_subject=f"Test {idx}",
        email_preview="hello",
        draft_v1="draft body v1",
        critique="",
        draft_final="final body",
        status=status,
        account_id=account_id,
        category=category,
        draft_id=f"draft-{account_id}-{idx}",
    )


# --------------------------------------------------------------------------- #
# M-3 regression tests
# --------------------------------------------------------------------------- #


def test_method_exists_on_sqlite_adapter():
    """Regression guard: hasattr(history, 'get_stats_for_account') must
    be True so dashboard.py picks the scoped path instead of falling back
    to the (unscoped + buggy) get_stats()."""
    assert hasattr(SqliteDraftHistoryAdapter, "get_stats_for_account")


def test_returns_empty_when_account_id_invalid(adapter):
    """No leak when no current account resolved (singleton returned -1, 0, None)."""
    for invalid in (0, -1, None):
        stats = adapter.get_stats_for_account(invalid)  # type: ignore
        assert stats["total"] == 0
        assert stats["by_category"] == {}
        assert stats["by_status"] == {}
        assert stats["validated_v1"] == 0


def test_isolates_two_accounts(adapter):
    """Account A's stats must not include account B's records."""
    for i in range(3):
        adapter.add(_make_record(account_id=1, idx=i, status="V1"))
    for i in range(5):
        adapter.add(_make_record(account_id=2, idx=i, status="V2"))

    stats_a = adapter.get_stats_for_account(1)
    stats_b = adapter.get_stats_for_account(2)

    assert stats_a["total"] == 3
    assert stats_a["validated_v1"] == 3
    assert stats_a["corrected_v2"] == 0

    assert stats_b["total"] == 5
    assert stats_b["validated_v1"] == 0
    assert stats_b["corrected_v2"] == 5


def test_by_category_is_per_account(adapter):
    """The category breakdown must not leak between accounts."""
    adapter.add(_make_record(account_id=1, idx=0, category="URGENT"))
    adapter.add(_make_record(account_id=2, idx=0, category="SPAM"))

    stats_a = adapter.get_stats_for_account(1)
    stats_b = adapter.get_stats_for_account(2)

    assert "URGENT" in stats_a["by_category"]
    assert "SPAM" not in stats_a["by_category"]
    assert "SPAM" in stats_b["by_category"]
    assert "URGENT" not in stats_b["by_category"]


def test_by_status_is_per_account(adapter):
    """Status breakdown must not leak between accounts."""
    adapter.add(_make_record(account_id=1, idx=0, status="V1"))
    adapter.add(_make_record(account_id=1, idx=1, status="V2"))
    adapter.add(_make_record(account_id=2, idx=0, status="V1"))

    stats_a = adapter.get_stats_for_account(1)
    stats_b = adapter.get_stats_for_account(2)

    assert stats_a["by_status"].get("V1") == 1
    assert stats_a["by_status"].get("V2") == 1
    assert stats_b["by_status"].get("V1") == 1
    assert stats_b["by_status"].get("V2", 0) == 0
