# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Server-side helpers for the per-account pinned-email list.

The pin list lives on ``Account.pinned_email_ids_json`` (a JSON array of
email/thread ids). The HTTP toggle endpoint
(``routes_emails.toggle_email_pin``) and background callers (the snoozed
follow-up wake sweep, the send/reject draft paths) all mutate it through
these helpers so the JSON shape and the idempotency rules live in one place.

Reads/writes go through ``get_db_session`` (auto-commit on clean exit), so
these are safe to call from the background scheduler context.
"""
from __future__ import annotations

import json
import logging
import threading

logger = logging.getLogger(__name__)

# Process-wide lock serializing the read-modify-write on
# ``Account.pinned_email_ids_json``. The web tier runs as a single process
# (gunicorn --workers 1) and these helpers, the HTTP ``/pin`` toggle, and the
# snoozed-followup wake sweep all mutate the JSON array from in-process threads
# (Flask workers + the shared ThreadPoolExecutor). An unsynchronised RMW dropped
# a concurrent pin/unpin (last-writer-wins). RLock = re-entrant-safe.
# (chaos audit 2026-06-02)
_pin_lock = threading.RLock()


def _load_ids(raw: str | None) -> list[str]:
    """Parse the JSON array column into a list of str ids, defensively."""
    try:
        val = json.loads(raw or "[]")
    except (ValueError, TypeError):
        return []
    return [str(x) for x in val] if isinstance(val, list) else []


def add_pinned_email_id(account_id: int, email_id: str) -> bool:
    """Pin ``email_id`` for ``account_id``. Idempotent.

    Returns True if the id was newly added, False if it was already pinned,
    the account is missing, or the inputs are empty.
    """
    if not account_id or not email_id:
        return False
    from app.db.database import get_db_session
    from app.db.models.account import Account

    try:
        with _pin_lock, get_db_session() as session:
            account = session.get(Account, account_id)
            if account is None:
                return False
            pinned = _load_ids(account.pinned_email_ids_json)
            if email_id in pinned:
                return False
            pinned.append(email_id)
            account.pinned_email_ids_json = json.dumps(pinned)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("[PIN] add_pinned_email_id(%s, %s) failed: %s", account_id, email_id, exc)
        return False


def remove_pinned_email_id(account_id: int, email_id: str) -> bool:
    """Unpin ``email_id`` for ``account_id``. Idempotent.

    Returns True if the id was removed, False if it was not pinned, the
    account is missing, or the inputs are empty.
    """
    if not account_id or not email_id:
        return False
    from app.db.database import get_db_session
    from app.db.models.account import Account

    try:
        with _pin_lock, get_db_session() as session:
            account = session.get(Account, account_id)
            if account is None:
                return False
            pinned = _load_ids(account.pinned_email_ids_json)
            if email_id not in pinned:
                return False
            account.pinned_email_ids_json = json.dumps([p for p in pinned if p != email_id])
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("[PIN] remove_pinned_email_id(%s, %s) failed: %s", account_id, email_id, exc)
        return False


__all__ = ["add_pinned_email_id", "remove_pinned_email_id"]
