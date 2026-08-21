#!/usr/bin/env python3
"""Copy the main Agentys SQLAlchemy database from SQLite/SQLCipher to Postgres.

This migrates only tables declared in app.db.models.Base. Legacy sqlite3 stores
under app.infrastructure.database intentionally remain out of scope for this
first phase.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Boolean, DateTime, Integer, create_engine, delete, func, insert, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.database import (  # noqa: E402
    _create_connection,
    _normalize_database_url,
    get_db_path,
    reset_engine,
)
from app.db.encryption import get_encryption_config  # noqa: E402
from app.db.models import Base  # noqa: E402


def _source_sqlite_engine(source_path: Path) -> Engine:
    encryption_config = get_encryption_config()

    def _creator():
        return _create_connection(source_path, encryption_config)

    return create_engine(
        f"sqlite:///{source_path}",
        creator=_creator,
        future=True,
    )


def _target_postgres_engine(database_url: str) -> Engine:
    normalized = _normalize_database_url(database_url)
    if not normalized.startswith("postgresql+"):
        raise ValueError("Target URL must be PostgreSQL")
    return create_engine(normalized, pool_pre_ping=True, future=True)


def _parse_datetime_value(value: Any) -> Any:
    if value is None or isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return value
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(raw, fmt)
            except ValueError:
                continue
    return value


def _coerce_row(row: dict[str, Any], table) -> dict[str, Any]:
    coerced = dict(row)
    for column in table.columns:
        value = coerced.get(column.name)
        if value is None:
            continue
        if isinstance(column.type, DateTime):
            coerced[column.name] = _parse_datetime_value(value)
        elif isinstance(column.type, Boolean):
            coerced[column.name] = bool(value)
        elif isinstance(column.type, Integer) and not isinstance(value, int):
            coerced[column.name] = int(value)
    return coerced


def _db_error_summary(exc: SQLAlchemyError) -> str:
    original = getattr(exc, "orig", None)
    if original is None:
        return exc.__class__.__name__
    diag = getattr(original, "diag", None)
    message = getattr(diag, "message_primary", None)
    if not message:
        message = str(original).splitlines()[0]
    return f"{original.__class__.__name__}: {message}"


def _table_exists(engine: Engine, table_name: str) -> bool:
    with engine.connect() as conn:
        if engine.dialect.name == "sqlite":
            row = conn.execute(
                text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:name"),
                {"name": table_name},
            ).first()
            return row is not None
        row = conn.execute(
            text("SELECT to_regclass(:name)"),
            {"name": f"public.{table_name}"},
        ).scalar()
        return row is not None


def _count_rows(engine: Engine, table) -> int:
    if not _table_exists(engine, table.name):
        return 0
    with engine.connect() as conn:
        return int(conn.execute(select(func.count()).select_from(table)).scalar() or 0)


def _reset_postgres_sequences(engine: Engine) -> None:
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            for column in table.columns:
                if not column.primary_key or not getattr(column, "autoincrement", False):
                    continue
                sequence_name = conn.execute(
                    text("SELECT pg_get_serial_sequence(:table_name, :column_name)"),
                    {"table_name": table.name, "column_name": column.name},
                ).scalar()
                if not sequence_name:
                    continue
                conn.execute(
                    text(
                        f"""
                        SELECT setval(
                            CAST(:sequence_name AS regclass),
                            COALESCE(MAX({column.name}), 1),
                            MAX({column.name}) IS NOT NULL
                        )
                        FROM {table.name}
                        """
                    ),
                    {"sequence_name": sequence_name},
                )


def _stamp_alembic_head(engine: Engine) -> list[str]:
    config = Config(str(ROOT / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    heads = list(script.get_heads())
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS alembic_version "
            "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
        ))
        conn.execute(text("DELETE FROM alembic_version"))
        for head in heads:
            conn.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:head)"),
                {"head": head},
            )
    return heads


def _upgrade_target_schema(target_url: str) -> None:
    previous_database_url = os.environ.get("DATABASE_URL")
    previous_db_path = os.environ.pop("AGENTYS_DB_PATH", None)
    os.environ["DATABASE_URL"] = target_url
    reset_engine()
    try:
        command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    finally:
        reset_engine()
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url
        if previous_db_path is not None:
            os.environ["AGENTYS_DB_PATH"] = previous_db_path


def _truncate_target(engine: Engine) -> None:
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(delete(table))


def migrate(
    *,
    source_path: Path,
    target_url: str,
    batch_size: int,
    dry_run: bool,
    truncate_target: bool,
    create_schema: bool,
    stamp_head: bool,
) -> int:
    source = _source_sqlite_engine(source_path)
    target: Engine | None = None

    try:
        if create_schema and not dry_run:
            _upgrade_target_schema(target_url)

        target = _target_postgres_engine(target_url)

        if truncate_target and not dry_run:
            _truncate_target(target)

        failures: list[str] = []
        for table in Base.metadata.sorted_tables:
            source_count = _count_rows(source, table)
            target_before = _count_rows(target, table)
            print(
                f"{table.name}: source={source_count} target_before={target_before}",
                flush=True,
            )

            if dry_run or source_count == 0:
                continue
            if target_before > 0 and not truncate_target:
                raise RuntimeError(
                    f"Target table {table.name} is not empty. "
                    "Use --truncate-target for a one-shot import into a disposable target."
                )

            copied = 0
            with source.connect() as source_conn, target.begin() as target_conn:
                result = source_conn.execution_options(stream_results=True).execute(select(table))
                while True:
                    rows = result.mappings().fetchmany(batch_size)
                    if not rows:
                        break
                    payload = [_coerce_row(dict(row), table) for row in rows]
                    try:
                        target_conn.execute(insert(table), payload)
                    except SQLAlchemyError as exc:
                        raise RuntimeError(
                            f"Failed to insert batch into {table.name} "
                            f"at offset {copied}: {_db_error_summary(exc)}"
                        ) from None
                    copied += len(payload)
                    print(f"  copied {copied}/{source_count}", flush=True)

            target_after = _count_rows(target, table)
            if target_after != source_count:
                failures.append(
                    f"{table.name}: expected {source_count}, got {target_after}"
                )

        if dry_run:
            print("Dry run complete; target was not modified.")
            return 0

        if failures:
            print("Verification failed:")
            for failure in failures:
                print(f"  - {failure}")
            return 1

        _reset_postgres_sequences(target)
        if stamp_head and not create_schema:
            heads = _stamp_alembic_head(target)
            print(f"Stamped Alembic heads: {', '.join(heads)}")

        print("Migration complete; row counts match for SQLAlchemy tables.")
        return 0
    finally:
        source.dispose()
        if target is not None:
            target.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=get_db_path(encrypted=bool(os.environ.get("AGENTYS_ENCRYPTION_KEY"))),
        help="SQLite/SQLCipher source DB path. Defaults to the configured Agentys DB.",
    )
    parser.add_argument(
        "--target",
        default=os.environ.get("DATABASE_URL"),
        help="PostgreSQL DATABASE_URL. Defaults to env DATABASE_URL.",
    )
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--truncate-target", action="store_true")
    parser.add_argument(
        "--no-create-schema",
        action="store_true",
        help="Skip alembic upgrade head on the target before importing rows.",
    )
    parser.add_argument(
        "--no-stamp-head",
        action="store_true",
        help="When --no-create-schema is used, skip the legacy manual head stamp.",
    )
    args = parser.parse_args()

    if not args.target:
        parser.error("--target or DATABASE_URL is required")

    return migrate(
        source_path=args.source,
        target_url=args.target,
        batch_size=max(1, args.batch_size),
        dry_run=args.dry_run,
        truncate_target=args.truncate_target,
        create_schema=not args.no_create_schema,
        stamp_head=not args.no_stamp_head,
    )


if __name__ == "__main__":
    raise SystemExit(main())
