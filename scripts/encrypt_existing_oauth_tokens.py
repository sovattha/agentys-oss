#!/usr/bin/env python3
"""One-shot migration: encrypt plaintext OAuth tokens in `accounts` in place.

Before this migration, `accounts.access_token` / `refresh_token` were stored
as plaintext `Text`. After wiring `EncryptedString` (Fernet) on the model,
new writes are encrypted automatically — but rows that predate the change
still contain plaintext. This script re-writes those rows with the Fernet
ciphertext.

Idempotent: rows whose values already start with the Fernet prefix `gAAAAA`
are skipped, so the script can be re-run safely.

Usage:
    python scripts/encrypt_existing_oauth_tokens.py [--dry-run]

The DATABASE_URL env var selects the target (Postgres in prod, SQLite in dev).
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.types.encrypted import _FERNET_TOKEN_PREFIX, _get_fernet

logger = logging.getLogger(__name__)

_TOKEN_COLUMNS = ("access_token", "refresh_token")


@dataclass
class MigrationSummary:
    encrypted: int = 0
    skipped: int = 0
    null: int = 0


def _encrypt(plain: str) -> str:
    return _get_fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def encrypt_oauth_tokens_in_place(
    session: Session,
    *,
    dry_run: bool = False,
) -> MigrationSummary:
    """Walk the `accounts` table and Fernet-encrypt any plaintext token.

    The query bypasses the ORM (raw SQL) so the EncryptedString TypeDecorator
    does not silently decrypt-then-reencrypt. Each cell is inspected by hand:
    if it is NULL → count and skip; if it already starts with the Fernet
    prefix → count and skip; else encrypt and UPDATE.
    """
    summary = MigrationSummary()
    rows = session.execute(
        text("SELECT id, access_token, refresh_token FROM accounts")
    ).all()

    for row in rows:
        account_id = row[0]
        updates: dict[str, str] = {}
        for column, value in zip(_TOKEN_COLUMNS, (row[1], row[2])):
            if value is None:
                summary.null += 1
                continue
            if value.startswith(_FERNET_TOKEN_PREFIX):
                summary.skipped += 1
                continue
            updates[column] = _encrypt(value)
            summary.encrypted += 1

        if updates and not dry_run:
            assignments = ", ".join(f"{col} = :{col}" for col in updates)
            session.execute(
                text(f"UPDATE accounts SET {assignments} WHERE id = :id"),
                {**updates, "id": account_id},
            )

    if not dry_run:
        session.commit()

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    from app.db.database import get_db_session

    with get_db_session() as session:
        summary = encrypt_oauth_tokens_in_place(session, dry_run=args.dry_run)

    verb = "would encrypt" if args.dry_run else "encrypted"
    logger.info(
        "OAuth token migration: %s=%d, already-encrypted=%d, null=%d",
        verb,
        summary.encrypted,
        summary.skipped,
        summary.null,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
