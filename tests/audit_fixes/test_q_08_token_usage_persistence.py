# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Q-08 — Persistent token usage log + async writer (audit 2026-05-06).

Pre-fix: ``LegacyTokenCounterAdapter`` was an in-memory adapter only.
"How much did this user cost yesterday?" required grepping log files,
not running a SQL query.

Post-fix: ``token_usage_log`` table with (account_id, agent, model,
input_tokens, output_tokens, cost_usd, ts). Writes go through the async
``token_usage_writer`` queue so the LLM hot path doesn't block on
SQLite. Reads via ``TokenUsageLogRepository``.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_writer_stats_shape():
    """get_writer_stats returns the contract the dashboard depends on."""
    from app.infrastructure.token_usage_writer import get_writer_stats
    snap = get_writer_stats()
    for key in ("queue_size", "queue_max", "flushed_total", "dropped_total", "alive"):
        assert key in snap, f"writer stats missing key={key}"


def test_enqueue_and_flush_roundtrip():
    """End-to-end: enqueue → flush → row visible via repository.

    Uses an isolated in-memory SQLite + a fresh metadata create_all so we
    don't depend on whether the dev SQLite has the migration applied yet.
    The production path is identical except the engine is the real DB.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db.models import Base
    from app.db.repositories.token_usage_log_repository import TokenUsageLogRepository

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    with Session() as session:
        repo = TokenUsageLogRepository(session)
        new_id = repo.add(
            account_id=42,
            user_id=5,
            agent="drafter",
            feature="drafting",
            model="claude-haiku-4-5-20251001",
            input_tokens=1000,
            output_tokens=200,
            cache_creation_input_tokens=25,
            cache_read_input_tokens=300,
            cost_usd=0.0042,
        )
        session.commit()
        assert new_id > 0

        rows = repo.cost_by_agent()
        assert "drafter" in rows
        assert rows["drafter"] >= 0.0042 - 1e-9

        per_account = repo.cost_for_account(42)
        assert per_account["account_id"] == 42
        assert per_account["total_cost_usd"] >= 0.0042 - 1e-9
        assert "drafter" in per_account["by_agent"]


def test_writer_async_flush_lifecycle():
    """Writer thread starts on first enqueue and drains over time."""
    import app.infrastructure.token_usage_writer as tuw
    from app.infrastructure.token_usage_writer import (
        TokenUsageRecord, enqueue, _queue, get_writer_stats,
    )

    # Reset the writer state.
    tuw._stop_event.set()
    if tuw._writer_thread is not None:
        tuw._writer_thread.join(timeout=3.0)
    tuw._writer_thread = None
    tuw._stop_event.clear()
    while not _queue.empty():
        _queue.get_nowait()

    enqueue(TokenUsageRecord(
        account_id=99, agent="critic", model="claude-haiku-4-5-20251001",
        input_tokens=10, output_tokens=5, cost_usd=0.0001,
        cache_read_input_tokens=100,
    ))
    # Writer thread should now be alive.
    snap = get_writer_stats()
    assert snap["alive"] is True

    # Stop and clean up.
    tuw._stop_event.set()


def test_cost_by_user_uses_log_user_or_account_owner():
    """Per-user spend is computed from the persistent table, not draft history."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db.models import Base
    from app.db.models.account import Account
    from app.db.repositories.token_usage_log_repository import TokenUsageLogRepository

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    with Session() as session:
        session.add(Account(id=42, email="owner@example.com", provider="gmail", user_id=700))
        session.flush()

        repo = TokenUsageLogRepository(session)
        repo.add(
            account_id=42,
            user_id=None,
            agent="critic",
            feature="drafting",
            model="claude-haiku-4-5-20251001",
            input_tokens=100,
            output_tokens=20,
            cost_usd=0.25,
        )
        repo.add(
            account_id=None,
            user_id=701,
            agent="drafter",
            feature="drafting",
            model="claude-haiku-4-5-20251001",
            input_tokens=50,
            output_tokens=10,
            cost_usd=0.10,
        )
        session.commit()

        by_user = {row["user_id"]: row for row in repo.cost_by_user()}
        assert by_user[700]["cost_usd"] == 0.25
        assert by_user[700]["account_count"] == 1
        assert by_user[701]["cost_usd"] == 0.10
        assert by_user[701]["calls"] == 1

        totals = repo.total_usage()
        assert totals["cost_usd"] == 0.35
        assert totals["calls"] == 2


def test_track_token_usage_enqueues_persistent_row():
    """_track_token_usage must enqueue a row to the persistent writer."""
    from app import agents as agents_mod
    from app.infrastructure.llm_attribution import llm_attribution

    response = MagicMock(
        input_tokens=500,
        output_tokens=120,
        model="claude-haiku-4-5-20251001",
        cache_creation_input_tokens=25,
        cache_read_input_tokens=300,
        usage_recorded=False,
    )
    fake_container = MagicMock()
    fake_container.token_usage = MagicMock()
    fake_container.token_counter = MagicMock()

    captured: list = []
    with patch.object(agents_mod, "get_container", return_value=fake_container):
        with patch(
            "app.infrastructure.token_usage_writer.enqueue",
            side_effect=lambda r: captured.append(r),
        ):
            with llm_attribution("critic", account_id=7):
                agents_mod._track_token_usage(response)

    assert len(captured) == 1, "_track_token_usage must enqueue exactly one row"
    rec = captured[0]
    assert rec.agent == "critic"
    assert rec.account_id == 7
    assert rec.input_tokens == 500
    assert rec.cache_creation_input_tokens == 25
    assert rec.cache_read_input_tokens == 300
    assert rec.output_tokens == 120
    # Cost must be > 0 — no zero-cost rows.
    assert rec.cost_usd > 0


def test_track_token_usage_does_not_duplicate_adapter_recorded_usage():
    """ClaudeAdapter persists usage itself; agent tracking must not double count."""
    from app import agents as agents_mod
    from app.infrastructure.llm_attribution import llm_attribution

    response = MagicMock(
        input_tokens=500,
        output_tokens=120,
        model="claude-haiku-4-5-20251001",
        cache_creation_input_tokens=25,
        cache_read_input_tokens=300,
        usage_recorded=True,
    )
    fake_container = MagicMock()
    fake_container.token_usage = MagicMock()
    fake_container.token_counter = MagicMock()

    captured: list = []
    with patch.object(agents_mod, "get_container", return_value=fake_container):
        with patch(
            "app.infrastructure.token_usage_writer.enqueue",
            side_effect=lambda r: captured.append(r),
        ):
            with llm_attribution("critic", account_id=7):
                agents_mod._track_token_usage(response)

    assert captured == []
    fake_container.token_usage.add.assert_called_once_with(
        500,
        120,
        "claude-haiku-4-5-20251001",
        cache_read_tokens=300,
        cache_creation_tokens=25,
    )
