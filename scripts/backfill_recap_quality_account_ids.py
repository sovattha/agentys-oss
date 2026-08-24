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

"""Backfill account_id on draft_quality.db events from canonical emails.

Dry-run by default. With --apply, only updates blank account_id rows whose
email_id maps to exactly one account in the SQL emails table.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Iterable


TABLES = ("send_events", "email_interactions")


def _month_bounds(month: str) -> tuple[str, str]:
    year, raw_month = month.split("-", 1)
    y = int(year)
    m = int(raw_month)
    start = f"{y:04d}-{m:02d}-01 00:00:00"
    if m == 12:
        end = f"{y + 1:04d}-01-01 00:00:00"
    else:
        end = f"{y:04d}-{m + 1:02d}-01 00:00:00"
    return start, end


def _default_quality_db() -> Path:
    db_path = os.environ.get("AGENTYS_DB_PATH")
    if db_path:
        return Path(db_path.replace("agentys.db", "draft_quality.db"))
    data_dir = os.environ.get("AGENTYS_DATA_DIR")
    if data_dir:
        return Path(data_dir) / "draft_quality.db"
    return Path.home() / ".agentys" / "draft_quality.db"


def _normalize_database_url(raw_url: str) -> str:
    if raw_url.startswith("postgres://"):
        return "postgresql://" + raw_url[len("postgres://") :]
    return raw_url


def _chunks(items: list[str], size: int) -> Iterable[list[str]]:
    for idx in range(0, len(items), size):
        yield items[idx : idx + size]


def _ensure_account_columns(conn: sqlite3.Connection) -> None:
    for table in TABLES:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN account_id TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass


def _load_blank_events(conn: sqlite3.Connection, month: str) -> dict[str, list[sqlite3.Row]]:
    start, end = _month_bounds(month)
    result: dict[str, list[sqlite3.Row]] = {}
    for table in TABLES:
        result[table] = conn.execute(
            f"""
            SELECT id, email_id
            FROM {table}
            WHERE (account_id IS NULL OR account_id = '')
              AND email_id != ''
              AND created_at >= ?
              AND created_at < ?
            """,
            (start, end),
        ).fetchall()
    return result


def _resolve_accounts(database_url: str, email_ids: list[str]) -> tuple[dict[str, str], set[str]]:
    import psycopg

    if not email_ids:
        return {}, set()

    mapping: dict[str, str] = {}
    ambiguous: set[str] = set()
    with psycopg.connect(_normalize_database_url(database_url)) as pg:
        with pg.cursor() as cur:
            for batch in _chunks(email_ids, 1000):
                cur.execute(
                    """
                    SELECT email_id, array_agg(DISTINCT account_id ORDER BY account_id) AS account_ids
                    FROM emails
                    WHERE email_id = ANY(%s)
                    GROUP BY email_id
                    """,
                    (batch,),
                )
                for email_id, account_ids in cur.fetchall():
                    account_ids = [value for value in account_ids if value is not None]
                    if len(account_ids) == 1:
                        mapping[email_id] = str(account_ids[0])
                    elif len(account_ids) > 1:
                        ambiguous.add(email_id)
    return mapping, ambiguous


def build_plan(args: argparse.Namespace) -> tuple[dict, list[tuple[str, int, str]]]:
    db_path = Path(args.quality_db)
    if not db_path.exists():
        raise SystemExit(f"quality DB not found: {db_path}")
    database_url = args.database_url or os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required to resolve email account_ids")

    with sqlite3.connect(str(db_path), timeout=10) as conn:
        conn.row_factory = sqlite3.Row
        _ensure_account_columns(conn)
        blank_by_table = _load_blank_events(conn, args.month)

    email_ids = sorted({row["email_id"] for rows in blank_by_table.values() for row in rows})
    mapping, ambiguous = _resolve_accounts(database_url, email_ids)
    target_account = str(args.account_id) if args.account_id else None

    updates: list[tuple[str, int, str]] = []
    stats = {
        "month": args.month,
        "quality_db": str(db_path),
        "apply": bool(args.apply),
        "target_account_id": target_account,
        "tables": {},
    }

    for table, rows in blank_by_table.items():
        table_updates: list[tuple[str, int, str]] = []
        unresolved = 0
        skipped_other_account = 0
        table_ambiguous = 0
        by_account: Counter[str] = Counter()
        for row in rows:
            email_id = row["email_id"]
            account_id = mapping.get(email_id)
            if email_id in ambiguous:
                table_ambiguous += 1
                continue
            if not account_id:
                unresolved += 1
                continue
            if target_account and account_id != target_account:
                skipped_other_account += 1
                continue
            table_updates.append((table, int(row["id"]), account_id))
            by_account[account_id] += 1
        updates.extend(table_updates)
        stats["tables"][table] = {
            "blank_rows": len(rows),
            "updates": len(table_updates),
            "unresolved": unresolved,
            "ambiguous": table_ambiguous,
            "skipped_other_account": skipped_other_account,
            "updates_by_account": dict(sorted(by_account.items())),
        }

    return stats, updates


def apply_updates(db_path: Path, updates: list[tuple[str, int, str]]) -> None:
    with sqlite3.connect(str(db_path), timeout=10) as conn:
        for table, row_id, account_id in updates:
            conn.execute(
                f"UPDATE {table} SET account_id = ? WHERE id = ? AND (account_id IS NULL OR account_id = '')",
                (account_id, row_id),
            )
        conn.commit()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month", required=True, help="Month to backfill, format YYYY-MM.")
    parser.add_argument("--quality-db", default=str(_default_quality_db()))
    parser.add_argument("--database-url", help="Defaults to DATABASE_URL.")
    parser.add_argument("--account-id", help="Only apply rows that resolve to this account id.")
    parser.add_argument("--apply", action="store_true", help="Apply updates. Default is dry-run.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    stats, updates = build_plan(args)
    if args.apply and updates:
        apply_updates(Path(args.quality_db), updates)
    print(json.dumps(stats, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
