#!/usr/bin/env python3
# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Audit persisted stores for metadata-only email content regressions."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine


DEFAULT_SNIPPET_MAX_CHARS = 150
CONTACT_SUMMARY_ALLOWED_KEYS = frozenset({"relation_type", "habitual_tone", "language"})
JSON_NONEMPTY_KEYS = frozenset(
    {
        "body_text",
        "body_html",
        "body_excerpt",
        "email_body",
        "draft_v1",
        "draft_final",
        "critique",
        "generation_prompt",
        "user_edits",
        "feedback_notes",
        "body_preview",
    }
)
DB_NONEMPTY_COLUMNS = {
    "emails": ("body_text", "body_html"),
    "drafts": ("generation_prompt", "user_edits", "feedback_notes"),
    "sent_emails": ("body_preview",),
    "draft_history": ("email_body", "draft_v1", "critique", "draft_final"),
    "learned_patterns": ("examples",),
}


@dataclass(frozen=True)
class Finding:
    source: str
    location: str
    detail: str
    count: int | None = None


@dataclass
class AuditReport:
    json_files_scanned: int
    database_checks: int
    findings: list[Finding]

    @property
    def ok(self) -> bool:
        return not self.findings

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "counts": {
                "json_files_scanned": self.json_files_scanned,
                "database_checks": self.database_checks,
                "findings": len(self.findings),
            },
            "findings": [asdict(finding) for finding in self.findings],
        }


def _is_nonempty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict, tuple, set)):
        return bool(value)
    return True


def _pointer(parent: str, key: str | int) -> str:
    if isinstance(key, int):
        return f"{parent}[{key}]"
    if not parent:
        return key
    return f"{parent}.{key}"


def _scan_json_node(
    value: Any,
    *,
    source: str,
    pointer: str,
    ancestors: tuple[str, ...],
    snippet_max_chars: int,
    findings: list[Finding],
) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_pointer = _pointer(pointer, key)
            child_ancestors = (*ancestors, key)

            if key in JSON_NONEMPTY_KEYS and _is_nonempty(child):
                findings.append(
                    Finding(
                        source=source,
                        location=child_pointer,
                        detail=f"non-empty metadata-only forbidden JSON field '{key}'",
                    )
                )

            if (
                key == "subject"
                and "reference_examples" in ancestors
                and _is_nonempty(child)
            ):
                findings.append(
                    Finding(
                        source=source,
                        location=child_pointer,
                        detail="style reference examples must not persist subject text",
                    )
                )

            if (
                key == "snippet"
                and isinstance(child, str)
                and len(child.strip()) > snippet_max_chars
            ):
                findings.append(
                    Finding(
                        source=source,
                        location=child_pointer,
                        detail=(
                            "snippet exceeds metadata-only length budget "
                            f"({len(child.strip())}>{snippet_max_chars})"
                        ),
                    )
                )

            if key == "summary_json" and _is_nonempty(child):
                _scan_summary_json_value(
                    child,
                    source=source,
                    location=child_pointer,
                    findings=findings,
                )

            _scan_json_node(
                child,
                source=source,
                pointer=child_pointer,
                ancestors=child_ancestors,
                snippet_max_chars=snippet_max_chars,
                findings=findings,
            )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_json_node(
                child,
                source=source,
                pointer=_pointer(pointer, index),
                ancestors=ancestors,
                snippet_max_chars=snippet_max_chars,
                findings=findings,
            )


def _scan_summary_json_value(
    value: Any,
    *,
    source: str,
    location: str,
    findings: list[Finding],
) -> None:
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError):
        findings.append(
            Finding(
                source=source,
                location=location,
                detail="summary_json is not valid JSON",
            )
        )
        return

    if not isinstance(parsed, dict):
        findings.append(
            Finding(
                source=source,
                location=location,
                detail="summary_json must be a minimized object",
            )
        )
        return

    extra_keys = sorted(
        key
        for key, child in parsed.items()
        if key not in CONTACT_SUMMARY_ALLOWED_KEYS and _is_nonempty(child)
    )
    if extra_keys:
        findings.append(
            Finding(
                source=source,
                location=location,
                detail=(
                    "summary_json contains non-allowlisted keys: "
                    + ", ".join(extra_keys[:10])
                ),
            )
        )


def scan_json_paths(
    paths: Iterable[Path],
    *,
    snippet_max_chars: int = DEFAULT_SNIPPET_MAX_CHARS,
) -> tuple[int, list[Finding]]:
    findings: list[Finding] = []
    files_scanned = 0

    for base in paths:
        if not base.exists():
            continue
        json_files = [base] if base.is_file() else sorted(base.rglob("*.json"))
        for path in json_files:
            if not path.is_file():
                continue
            files_scanned += 1
            source = path.as_posix()
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, ValueError) as exc:
                findings.append(
                    Finding(
                        source=source,
                        location="$",
                        detail=f"failed to parse JSON file: {exc}",
                    )
                )
                continue

            _scan_json_node(
                payload,
                source=source,
                pointer="",
                ancestors=(),
                snippet_max_chars=snippet_max_chars,
                findings=findings,
            )

    return files_scanned, findings


def _quote(engine: Engine, name: str) -> str:
    return engine.dialect.identifier_preparer.quote(name)


def _count_nonempty(
    engine: Engine,
    table_name: str,
    column_name: str,
    *,
    min_length: int = 0,
) -> int:
    table_sql = _quote(engine, table_name)
    column_sql = _quote(engine, column_name)
    length_sql = f"length(trim(CAST({column_sql} AS TEXT)))"
    query = text(
        f"SELECT count(*) FROM {table_sql} "
        f"WHERE {column_sql} IS NOT NULL AND {length_sql} > :min_length"
    )
    with engine.connect() as conn:
        return int(conn.execute(query, {"min_length": min_length}).scalar_one())


def _scan_contact_summaries(engine: Engine) -> tuple[int, list[Finding]]:
    inspector = inspect(engine)
    if "contacts" not in set(inspector.get_table_names()):
        return 0, []

    columns = {column["name"] for column in inspector.get_columns("contacts")}
    if "summary_json" not in columns:
        return 0, []

    id_column = "id" if "id" in columns else None
    table_sql = _quote(engine, "contacts")
    summary_sql = _quote(engine, "summary_json")
    id_sql = _quote(engine, id_column) if id_column else "NULL"
    query = text(
        f"SELECT {id_sql} AS row_id, {summary_sql} AS summary_json FROM {table_sql} "
        f"WHERE {summary_sql} IS NOT NULL AND length(trim(CAST({summary_sql} AS TEXT))) > 0"
    )

    findings: list[Finding] = []
    rows_checked = 0
    with engine.connect() as conn:
        for row in conn.execute(query):
            rows_checked += 1
            row_id = row._mapping["row_id"]
            location = f"contacts[{row_id}].summary_json" if row_id is not None else "contacts.summary_json"
            _scan_summary_json_value(
                row._mapping["summary_json"],
                source="database",
                location=location,
                findings=findings,
            )
    return rows_checked, findings


def scan_database(
    engine: Engine,
    *,
    snippet_max_chars: int = DEFAULT_SNIPPET_MAX_CHARS,
) -> tuple[int, list[Finding]]:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    findings: list[Finding] = []
    checks = 0

    for table_name, column_names in DB_NONEMPTY_COLUMNS.items():
        if table_name not in tables:
            continue
        columns = {column["name"] for column in inspector.get_columns(table_name)}
        for column_name in column_names:
            if column_name not in columns:
                continue
            checks += 1
            count = _count_nonempty(engine, table_name, column_name)
            if count:
                findings.append(
                    Finding(
                        source="database",
                        location=f"{table_name}.{column_name}",
                        detail="non-empty metadata-only forbidden database column",
                        count=count,
                    )
                )

    if "emails" in tables:
        columns = {column["name"] for column in inspector.get_columns("emails")}
        if "snippet" in columns:
            checks += 1
            count = _count_nonempty(engine, "emails", "snippet", min_length=snippet_max_chars)
            if count:
                findings.append(
                    Finding(
                        source="database",
                        location="emails.snippet",
                        detail=(
                            "snippet exceeds metadata-only length budget "
                            f"(>{snippet_max_chars})"
                        ),
                        count=count,
                    )
                )

    contact_checks, contact_findings = _scan_contact_summaries(engine)
    checks += contact_checks
    findings.extend(contact_findings)
    return checks, findings


def _normalize_database_url(raw_url: str) -> str:
    if raw_url.startswith("postgres://"):
        return "postgresql+psycopg://" + raw_url[len("postgres://") :]
    if raw_url.startswith("postgresql://"):
        return "postgresql+psycopg://" + raw_url[len("postgresql://") :]
    return raw_url


def _connect_database(args: argparse.Namespace) -> Engine | None:
    if args.skip_db:
        return None

    database_url = args.database_url or os.environ.get("DATABASE_URL")
    if database_url:
        return create_engine(_normalize_database_url(database_url), pool_pre_ping=True)

    sqlite_path = args.sqlite_db_path or os.environ.get("AGENTYS_DB_PATH")
    if sqlite_path:
        path = Path(sqlite_path)
        if not path.exists():
            return None
        return create_engine(f"sqlite:///{path.as_posix()}")

    return None


def build_report(args: argparse.Namespace) -> AuditReport:
    data_dirs = [Path(value) for value in (args.data_dir or [])]
    if not data_dirs:
        data_dirs = [Path(os.environ.get("AGENTYS_DATA_DIR", "data"))]

    json_files_scanned, findings = scan_json_paths(
        data_dirs,
        snippet_max_chars=args.snippet_max_chars,
    )

    database_checks = 0
    engine = _connect_database(args)
    if engine is not None:
        try:
            database_checks, db_findings = scan_database(
                engine,
                snippet_max_chars=args.snippet_max_chars,
            )
            findings.extend(db_findings)
        finally:
            engine.dispose()

    return AuditReport(
        json_files_scanned=json_files_scanned,
        database_checks=database_checks,
        findings=findings,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit Agentys metadata-only stores for persisted email content."
    )
    parser.add_argument(
        "--data-dir",
        action="append",
        help="Directory or JSON file to scan. Defaults to AGENTYS_DATA_DIR or ./data.",
    )
    parser.add_argument(
        "--database-url",
        help="SQLAlchemy database URL. Defaults to DATABASE_URL when present.",
    )
    parser.add_argument(
        "--sqlite-db-path",
        help="SQLite database path. Defaults to AGENTYS_DB_PATH when present.",
    )
    parser.add_argument(
        "--skip-db",
        action="store_true",
        help="Skip SQL database checks.",
    )
    parser.add_argument(
        "--snippet-max-chars",
        type=int,
        default=DEFAULT_SNIPPET_MAX_CHARS,
        help="Maximum persisted snippet length allowed in metadata-only mode.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    report = build_report(parse_args(argv))
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
