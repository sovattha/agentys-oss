#!/usr/bin/env python3
"""Sentinel for SQLite/WAL and account ownership invariants.

Railway usage:
  railway run python scripts/db_invariants_sentinel.py --repair-user-ids --json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.database import get_db_session
from app.db.maintenance import (
    checkpoint_wal,
    database_file_status,
    find_account_user_id_drifts,
    repair_all_account_user_ids,
    run_with_sqlite_lock_retry,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check Agentys DB invariants")
    parser.add_argument(
        "--repair-user-ids",
        action="store_true",
        help="Repair non-null account.user_id drift before reporting final status",
    )
    parser.add_argument(
        "--include-null-user-ids",
        action="store_true",
        help="Also flag/repair NULL user_id rows. Use only for web-owned accounts.",
    )
    parser.add_argument(
        "--checkpoint-wal-over-mb",
        type=int,
        default=64,
        help="Run PRAGMA wal_checkpoint(TRUNCATE) when WAL exceeds this size",
    )
    parser.add_argument(
        "--max-wal-mb",
        type=int,
        default=128,
        help="Exit non-zero if WAL remains above this size after checkpoint",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON output",
    )
    return parser


def _run(args: argparse.Namespace) -> dict[str, Any]:
    before = database_file_status()
    checkpoint = None
    repaired_user_ids = 0

    if before["wal_bytes"] > args.checkpoint_wal_over_mb * 1024 * 1024:
        checkpoint = checkpoint_wal(source="db-sentinel")

    with get_db_session() as session:
        drifts = find_account_user_id_drifts(
            session,
            include_null=args.include_null_user_ids,
        )
        if args.repair_user_ids and drifts:
            repaired_user_ids = repair_all_account_user_ids(
                session,
                include_null=args.include_null_user_ids,
            )
            drifts = find_account_user_id_drifts(
                session,
                include_null=args.include_null_user_ids,
            )

    after = database_file_status()
    wal_ok = after["wal_bytes"] <= args.max_wal_mb * 1024 * 1024
    ok = wal_ok and not drifts
    return {
        "ok": ok,
        "wal_ok": wal_ok,
        "before": before,
        "after": after,
        "checkpoint": checkpoint,
        "account_user_id_drift_count": len(drifts),
        "account_user_id_drifts": drifts,
        "repaired_user_ids": repaired_user_ids,
    }


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        payload = run_with_sqlite_lock_retry(lambda: _run(args), source="db-sentinel")
    except Exception as exc:
        payload = {"ok": False, "error": str(exc)}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"DB sentinel failed: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        status = "OK" if payload["ok"] else "FAIL"
        print(
            f"{status}: wal={payload['after']['wal_bytes']} bytes, "
            f"user_id_drifts={payload['account_user_id_drift_count']}, "
            f"repaired={payload['repaired_user_ids']}"
        )
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
