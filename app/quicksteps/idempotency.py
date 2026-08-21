# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Idempotency cache for Quick Step execution.

Two backends, same interface:

- :class:`MemoryIdempotencyStore` — process-local OrderedDict, used in tests
  to keep them fast and isolated.
- :class:`SqliteIdempotencyStore` — backed by ``quick_step_executions``,
  shared across gunicorn workers. Production default.

Records expire after ``ttl_seconds`` (default 60s) to dedupe accidental
double-clicks without keeping a forever log of every execution.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import OrderedDict
from datetime import datetime, timedelta
from typing import Protocol

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 60.0
DEFAULT_MAX_ENTRIES = 2048


class IdempotencyStore(Protocol):
    """Read-and-write side of the cache. Engine talks only to this."""

    def get(self, account_id: int, key: str) -> dict | None: ...
    def put(self, account_id: int, key: str, report_dict: dict) -> None: ...


# --------------------------------------------------------------------------- #
# In-process store — used by tests.
# --------------------------------------------------------------------------- #

class MemoryIdempotencyStore:
    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        max_entries: int = DEFAULT_MAX_ENTRIES,
    ) -> None:
        self._cache: "OrderedDict[tuple[int, str], tuple[float, dict]]" = OrderedDict()
        self._lock = threading.Lock()
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries

    def get(self, account_id: int, key: str) -> dict | None:
        if not key:
            return None
        cache_key = (account_id, key)
        now = time.monotonic()
        with self._lock:
            entry = self._cache.get(cache_key)
            if not entry:
                return None
            ts, payload = entry
            if now - ts >= self.ttl_seconds:
                self._cache.pop(cache_key, None)
                return None
            self._cache.move_to_end(cache_key)
            return payload

    def put(self, account_id: int, key: str, report_dict: dict) -> None:
        if not key:
            return
        now = time.monotonic()
        with self._lock:
            self._cache[(account_id, key)] = (now, report_dict)
            self._cache.move_to_end((account_id, key))
            while len(self._cache) > self.max_entries:
                self._cache.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()


# --------------------------------------------------------------------------- #
# SQLite-backed store — production default.
# --------------------------------------------------------------------------- #

class SqliteIdempotencyStore:
    """Backed by the ``quick_step_executions`` table.

    Reads opportunistically delete expired rows for the queried key (TTL
    eviction without a separate sweeper). Inserts are idempotent: if the
    unique key collides we treat it as a successful "already stored" path
    and let the next ``get`` find it.
    """

    def __init__(self, *, ttl_seconds: float = DEFAULT_TTL_SECONDS) -> None:
        self.ttl_seconds = ttl_seconds

    def get(self, account_id: int, key: str) -> dict | None:
        if not key:
            return None
        from app.db.database import get_db_session
        from app.db.models.quick_step_execution import QuickStepExecution
        cutoff = datetime.utcnow() - timedelta(seconds=self.ttl_seconds)
        try:
            with get_db_session() as session:
                row = (
                    session.query(QuickStepExecution)
                    .filter_by(account_id=account_id, idempotency_key=key)
                    .one_or_none()
                )
                if row is None:
                    return None
                if row.created_at <= cutoff:
                    session.delete(row)
                    session.commit()
                    return None
                return json.loads(row.report_json)
        except Exception as exc:  # noqa: BLE001
            logger.warning("idempotency get failed: %s", exc)
            return None

    def put(self, account_id: int, key: str, report_dict: dict) -> None:
        if not key:
            return
        from sqlalchemy.exc import IntegrityError
        from app.db.database import get_db_session
        from app.db.models.quick_step_execution import QuickStepExecution
        try:
            with get_db_session() as session:
                row = QuickStepExecution(
                    account_id=account_id,
                    idempotency_key=key,
                    report_json=json.dumps(report_dict, ensure_ascii=False),
                )
                session.add(row)
                try:
                    session.commit()
                except IntegrityError:
                    # Another worker already stored this key — that's fine,
                    # idempotency is preserved either way.
                    session.rollback()
        except Exception as exc:  # noqa: BLE001
            logger.warning("idempotency put failed: %s", exc)


# --------------------------------------------------------------------------- #
# Default factory — production picks SQLite, tests inject Memory.
# --------------------------------------------------------------------------- #

_default_store: IdempotencyStore | None = None


def get_default_store() -> IdempotencyStore:
    global _default_store
    if _default_store is None:
        _default_store = SqliteIdempotencyStore()
    return _default_store


def set_default_store(store: IdempotencyStore | None) -> None:
    """Test hook — pass None to revert to SQLite."""
    global _default_store
    _default_store = store
