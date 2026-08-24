# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Small, idempotent SQLite/account maintenance helpers.

These functions are safe to call at boot, from /api/init, or from a
cron/sentinel without changing business state except repairing account
ownership drift.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text

from app.account_identity import user_id_from_email
from app.db.database import get_db_path, get_engine
from app.db.models.account import Account

logger = logging.getLogger(__name__)


def mask_email(email: str | None) -> str:
    """Return a non-sensitive email hint for logs and sentinel JSON."""
    if not email or "@" not in email:
        return "***"
    local, domain = email.split("@", 1)
    if not local:
        masked_local = "***"
    elif len(local) <= 2:
        masked_local = local[0] + "***"
    else:
        masked_local = local[:2] + "***" + local[-1]
    return f"{masked_local}@{domain}"


def _account_drift(account: Account, expected_user_id: int) -> bool:
    return account.user_id != expected_user_id


def is_sqlite_locked(exc: BaseException) -> bool:
    return "database is locked" in str(exc).lower()


def run_with_sqlite_lock_retry(
    operation,
    *,
    attempts: int = 3,
    base_delay: float = 1.0,
    source: str = "db-maintenance",
):
    """Run an operation with short retries for transient SQLite writer locks."""
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except Exception as exc:
            if attempt >= attempts or not is_sqlite_locked(exc):
                raise
            delay = base_delay * attempt
            logger.warning(
                "[%s] SQLite locked; retry %d/%d in %.1fs",
                source,
                attempt + 1,
                attempts,
                delay,
            )
            time.sleep(delay)


def repair_account_user_id(
    session,
    *,
    auth_email: str,
    user_id: int | None = None,
    source: str = "account-repair",
) -> int:
    """Repair account.user_id for the authenticated email.

    This covers both legacy NULL rows and stale non-null rows left by older
    hash implementations. Matching is intentionally restricted to the
    authenticated email to avoid cross-user repairs.
    """
    normalized_email = auth_email.lower()
    expected_user_id = user_id if user_id is not None else user_id_from_email(normalized_email)
    stmt = (
        select(Account)
        .where(
            Account.is_active == True,  # noqa: E712
            func.lower(Account.email) == normalized_email,
        )
    )
    repaired = 0
    for account in session.scalars(stmt).all():
        if not _account_drift(account, expected_user_id):
            continue
        logger.warning(
            "[%s] repairing account user_id drift account_id=%s email=%s old_user_id=%s new_user_id=%s",
            source,
            account.id,
            mask_email(account.email),
            account.user_id,
            expected_user_id,
        )
        account.user_id = expected_user_id
        repaired += 1
    if repaired:
        session.flush()
    return repaired


def find_account_user_id_drifts(
    session,
    *,
    active_only: bool = True,
    include_null: bool = False,
) -> list[dict[str, Any]]:
    """Return account rows whose persisted user_id does not match their email."""
    stmt = select(Account).where(Account.email.is_not(None))
    if active_only:
        stmt = stmt.where(Account.is_active == True)  # noqa: E712

    drifts: list[dict[str, Any]] = []
    for account in session.scalars(stmt).all():
        if account.user_id is None and not include_null:
            continue
        expected = user_id_from_email(account.email)
        if not _account_drift(account, expected):
            continue
        drifts.append(
            {
                "account_id": account.id,
                "email": mask_email(account.email),
                "provider": account.provider,
                "old_user_id": account.user_id,
                "expected_user_id": expected,
            }
        )
    return drifts


def repair_all_account_user_ids(
    session,
    *,
    active_only: bool = True,
    include_null: bool = False,
) -> int:
    """Repair account.user_id drifts found in the local database.

    NULL rows are skipped by default: they are still valid for legacy/Tauri
    desktop accounts. Authenticated web requests repair their own NULL row via
    repair_account_user_id(), where the JWT email proves ownership.
    """
    stmt = select(Account).where(Account.email.is_not(None))
    if active_only:
        stmt = stmt.where(Account.is_active == True)  # noqa: E712

    repaired = 0
    for account in session.scalars(stmt).all():
        if account.user_id is None and not include_null:
            continue
        expected = user_id_from_email(account.email)
        if not _account_drift(account, expected):
            continue
        logger.warning(
            "[account-repair] repairing account_id=%s email=%s old_user_id=%s new_user_id=%s",
            account.id,
            mask_email(account.email),
            account.user_id,
            expected,
        )
        account.user_id = expected
        repaired += 1
    if repaired:
        session.flush()
    return repaired


def database_file_status() -> dict[str, Any]:
    """Return the configured SQLite DB and WAL file sizes."""
    db_url_path = get_engine().url.database
    db_path = Path(db_url_path) if db_url_path else Path(get_db_path())
    wal_path = Path(f"{db_path}-wal")
    shm_path = Path(f"{db_path}-shm")
    return {
        "db_path": str(db_path),
        "db_bytes": db_path.stat().st_size if db_path.exists() else 0,
        "wal_path": str(wal_path),
        "wal_bytes": wal_path.stat().st_size if wal_path.exists() else 0,
        "shm_path": str(shm_path),
        "shm_bytes": shm_path.stat().st_size if shm_path.exists() else 0,
    }


def checkpoint_wal(*, mode: str = "TRUNCATE", source: str = "db-maintenance") -> dict[str, Any]:
    """Run a best-effort WAL checkpoint and return status metadata."""
    normalized_mode = mode.upper()
    if normalized_mode not in {"PASSIVE", "FULL", "RESTART", "TRUNCATE"}:
        raise ValueError(f"Unsupported WAL checkpoint mode: {mode}")

    engine = get_engine()
    if engine.dialect.name != "sqlite":
        result = {
            "mode": normalized_mode,
            "before": {},
            "after": {},
            "result": [],
            "skipped": True,
            "reason": f"unsupported dialect: {engine.dialect.name}",
        }
        logger.info(
            "[%s] SQLite WAL checkpoint skipped for %s backend",
            source,
            engine.dialect.name,
        )
        return result

    before = database_file_status()
    with engine.connect() as conn:
        rows = conn.execute(text(f"PRAGMA wal_checkpoint({normalized_mode})")).fetchall()
    after = database_file_status()
    result = {
        "mode": normalized_mode,
        "before": before,
        "after": after,
        "result": [tuple(row) for row in rows],
    }
    logger.info(
        "[%s] SQLite WAL checkpoint %s: wal_bytes %s -> %s result=%s",
        source,
        normalized_mode,
        before["wal_bytes"],
        after["wal_bytes"],
        result["result"],
    )
    return result
