"""Regression tests for the Haiku 4.5 token cost backfill migration."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text


def _load_migration_module():
    path = (
        Path(__file__).resolve().parents[2]
        / "app"
        / "db"
        / "migrations"
        / "versions"
        / "20260609_000001_backfill_haiku45_token_costs.py"
    )
    spec = importlib.util.spec_from_file_location("backfill_haiku45_token_costs", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_haiku45_cost_backfill_recomputes_persisted_rows(tmp_path):
    migration = _load_migration_module()
    engine = create_engine(f"sqlite:///{tmp_path / 'token-costs.db'}")

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE token_usage_log (
                    id INTEGER PRIMARY KEY,
                    model TEXT NOT NULL,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    cache_creation_input_tokens INTEGER NOT NULL DEFAULT 0,
                    cache_read_input_tokens INTEGER NOT NULL DEFAULT 0,
                    cost_usd REAL NOT NULL DEFAULT 0
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO token_usage_log (
                    id, model, input_tokens, output_tokens,
                    cache_creation_input_tokens, cache_read_input_tokens, cost_usd
                )
                VALUES
                    (1, 'claude-haiku-4-5-20251001', 1000, 100, 200, 300, 0.001424),
                    (2, 'claude-sonnet-4-6', 1000, 100, 200, 300, 0.999)
                """
            )
        )

        migration.op = SimpleNamespace(
            get_bind=lambda: conn,
            execute=lambda statement: conn.execute(statement),
        )

        migration.upgrade()

        rows = conn.execute(
            text("SELECT id, cost_usd FROM token_usage_log ORDER BY id")
        ).all()
        assert rows[0].cost_usd == pytest.approx(0.00178)
        assert rows[1].cost_usd == pytest.approx(0.999)

        migration.downgrade()

        reverted = conn.execute(
            text("SELECT cost_usd FROM token_usage_log WHERE id = 1")
        ).scalar_one()
        assert reverted == pytest.approx(0.001424)

    engine.dispose()
