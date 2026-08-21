from pathlib import Path
import logging

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.db.database import reset_engine
from scripts.check_alembic_model_drift import collect_unexpected_diffs


def _upgrade_fresh_sqlite(tmp_path: Path, monkeypatch) -> Path:
    db_path = tmp_path / "agentys_alembic_contract.db"
    monkeypatch.setenv("AGENTYS_DB_PATH", str(db_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    reset_engine()
    try:
        command.upgrade(Config("alembic.ini"), "head")
    finally:
        reset_engine()
    return db_path


def _column_types(db_path: Path, table_name: str) -> dict[str, str]:
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        inspector = inspect(engine)
        return {
            column["name"]: str(column["type"]).upper()
            for column in inspector.get_columns(table_name)
        }
    finally:
        engine.dispose()


def test_fresh_alembic_upgrade_builds_all_orm_tables(tmp_path, monkeypatch):
    db_path = _upgrade_fresh_sqlite(tmp_path, monkeypatch)
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert {
        "faq_agent_logs",
        "knowledge_entries",
        "pending_actions",
        "relationship_overrides",
        "scheduler_heartbeats",
    } <= tables


def test_fresh_alembic_upgrade_preserves_critical_widened_columns(tmp_path, monkeypatch):
    db_path = _upgrade_fresh_sqlite(tmp_path, monkeypatch)

    account_types = _column_types(db_path, "accounts")
    email_types = _column_types(db_path, "emails")
    contact_types = _column_types(db_path, "contacts")
    bulk_job_types = _column_types(db_path, "bulk_jobs")
    token_usage_types = _column_types(db_path, "token_usage_log")
    billing_types = _column_types(db_path, "billing_subscriptions")

    assert account_types["user_id"] == "BIGINT"
    assert account_types["access_token"] == "TEXT"
    assert account_types["refresh_token"] == "TEXT"
    assert email_types["sender"] == "VARCHAR(1024)"
    assert contact_types["email"] == "VARCHAR(1024)"
    assert bulk_job_types["user_id"] == "BIGINT"
    assert token_usage_types["user_id"] == "BIGINT"
    assert token_usage_types["input_tokens"] == "BIGINT"
    assert token_usage_types["output_tokens"] == "BIGINT"
    assert token_usage_types["cache_creation_input_tokens"] == "BIGINT"
    assert token_usage_types["cache_read_input_tokens"] == "BIGINT"
    assert "stripe_usage_price_id" in billing_types
    assert "current_period_start" in billing_types
    assert "usage_billing_enabled" in billing_types


def test_repair_migration_restores_usage_billing_flag_for_stamped_head(tmp_path, monkeypatch):
    db_path = tmp_path / "agentys_stamped_missing_usage_flag.db"
    monkeypatch.setenv("AGENTYS_DB_PATH", str(db_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    reset_engine()

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
            conn.execute(text("INSERT INTO alembic_version (version_num) VALUES ('036_dictation_usage_log')"))
            conn.execute(text("CREATE TABLE billing_subscriptions (id INTEGER PRIMARY KEY)"))

        command.upgrade(Config("alembic.ini"), "head")

        columns = {
            column["name"]
            for column in inspect(engine).get_columns("billing_subscriptions")
        }
        assert "usage_billing_enabled" in columns
    finally:
        engine.dispose()
        reset_engine()


def test_alembic_metadata_gate_has_no_unexpected_drift(tmp_path):
    unexpected = collect_unexpected_diffs(tmp_path / "agentys_drift_gate.db")

    assert unexpected == []


def test_alembic_upgrade_keeps_existing_app_loggers_enabled(tmp_path, monkeypatch):
    logger = logging.getLogger("app.providers.gmail_adapter")
    original_disabled = logger.disabled
    logger.disabled = False

    try:
        _upgrade_fresh_sqlite(tmp_path, monkeypatch)
        assert logger.disabled is False
    finally:
        logger.disabled = original_disabled
