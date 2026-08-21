#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Standalone admin script — migrate every account's legacy
``WritingStyleProfile.contact_profiles`` dict into the SQLite
``contact_styles`` table.

The same logic is auto-invoked at API boot (``create_app``), but this
script lets an operator :
    - dry-run the migration (``--dry-run`` lists accounts, no writes)
    - target a specific account_id (``--account-id N``)
    - run from a clean cron without booting Flask

The migration is idempotent (cf. ``contact_profiles_migration`` module
docstring) so re-running it is always safe.

Usage:
    python scripts/migrate_contact_profiles_to_sqlite.py [--dry-run] [--account-id N]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Project root setup
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--account-id",
        type=int,
        default=None,
        help="Migrate only this account_id (default: all accounts)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List accounts to migrate without writing to SQLite",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable DEBUG logging"
    )
    args = parser.parse_args()

    _setup_logging(args.verbose)
    logger = logging.getLogger("migrate_contact_profiles")

    from app.infrastructure.contact_profiles_migration import (
        _account_id_from_filename,
        _list_profile_files,
        _resolve_learning_dir,
        migrate_account,
    )

    learning_dir = _resolve_learning_dir()
    if learning_dir is None:
        logger.error("Could not resolve the learning directory via the Container")
        return 1

    files = _list_profile_files(learning_dir)
    if not files:
        logger.info("No profile files found in %s — nothing to migrate", learning_dir)
        return 0

    targets: list[tuple[int, Path]] = []
    for path in files:
        account_id = _account_id_from_filename(path)
        if account_id is None:
            logger.warning("Skipping malformed filename: %s", path.name)
            continue
        if args.account_id is not None and account_id != args.account_id:
            continue
        targets.append((account_id, path))

    if not targets:
        logger.info("No accounts matched the filter")
        return 0

    if args.dry_run:
        logger.info("DRY RUN — would migrate the following accounts:")
        for account_id, path in targets:
            logger.info("  account=%s file=%s", account_id, path.name)
        return 0

    total_rows = 0
    for account_id, path in targets:
        n = migrate_account(account_id)
        logger.info(
            "  account=%s file=%s rows_written=%d", account_id, path.name, n
        )
        total_rows += n

    logger.info(
        "Migration complete : %d rows across %d account(s)",
        total_rows, len(targets),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
