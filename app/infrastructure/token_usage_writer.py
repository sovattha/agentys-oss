# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Async batched writer for the token_usage_log table (audit 2026-05-06).

The LLM call path is hot — adding a synchronous SQLite write per
completion would add 5-15 ms of lock contention on a 2-3 s draft, which
is wasteful. Instead, ``_track_token_usage`` calls :func:`enqueue` with
the row data; a daemon thread drains the queue every
``_FLUSH_INTERVAL_SECONDS`` and writes a batch insert.

Failure modes:
- DB unavailable → queue keeps growing up to ``_QUEUE_MAX``; oldest are
  dropped (with a counter increment) so memory stays bounded.
- Writer thread crashes → next ``enqueue`` call detects the stop event
  and respawns the worker.
- Process shutdown → ``flush_now`` is idempotent and best-effort, called
  from app teardown.
"""
from __future__ import annotations

import logging
import os
import queue
import threading
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Tuning — overridable via env so ops can tighten the window if drift is
# observed in the admin dashboard ("rows lag too far behind reality").
_FLUSH_INTERVAL_SECONDS = float(os.environ.get("TOKEN_USAGE_FLUSH_SECONDS", "2.0"))
_QUEUE_MAX = int(os.environ.get("TOKEN_USAGE_QUEUE_MAX", "10000"))
_BATCH_MAX = 200  # SQLite likes batches < ~500 rows per executemany


@dataclass
class TokenUsageRecord:
    account_id: Optional[int]
    agent: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    user_id: Optional[int] = None
    feature: str = "unknown"
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


_queue: "queue.Queue[TokenUsageRecord]" = queue.Queue(maxsize=_QUEUE_MAX)
_writer_thread: Optional[threading.Thread] = None
_thread_lock = threading.Lock()
_stop_event = threading.Event()
_dropped_counter = 0
_flushed_counter = 0
_dropped_lock = threading.Lock()


def _safe_int(value, default: int = 0) -> int:
    if value is None or isinstance(value, bool):
        return default
    if not isinstance(value, (int, float, str)):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _calculate_cost_usd(
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
) -> float:
    """Calculate Anthropic-cache-aware cost for a usage row."""
    from app.infrastructure.cost_manager import MODEL_PRICING

    pricing = MODEL_PRICING.get(model) or MODEL_PRICING["default"]
    input_price = float(pricing["input"])
    output_price = float(pricing["output"])
    cost = (
        input_tokens * input_price
        + cache_creation_input_tokens * input_price * 1.25
        + cache_read_input_tokens * input_price * 0.10
        + output_tokens * output_price
    ) / 1_000_000
    return round(float(cost), 6)


def build_record(
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
    agent: Optional[str] = None,
    account_id: Optional[int] = None,
    user_id: Optional[int] = None,
    feature: Optional[str] = None,
) -> TokenUsageRecord:
    """Build a persistent usage row with the active attribution context."""
    try:
        from app.infrastructure.llm_attribution import current_account_id, current_agent

        if agent is None:
            agent = current_agent()
        if account_id is None:
            account_id = current_account_id()
    except Exception:  # pragma: no cover - telemetry must be best-effort
        agent = agent or "unknown"

    try:
        from app.infrastructure.cost_manager import get_usage_context

        context_account_id, context_user_id, context_feature = get_usage_context()
        if account_id is None:
            account_id = context_account_id
        if user_id is None:
            user_id = context_user_id
        if feature is None:
            feature = context_feature
    except Exception:  # pragma: no cover - telemetry must be best-effort
        pass

    clean_input = max(0, _safe_int(input_tokens))
    clean_output = max(0, _safe_int(output_tokens))
    clean_cache_creation = max(0, _safe_int(cache_creation_input_tokens))
    clean_cache_read = max(0, _safe_int(cache_read_input_tokens))
    clean_model = model or "?"

    return TokenUsageRecord(
        account_id=account_id,
        user_id=user_id,
        agent=agent or "unknown",
        feature=feature or "unknown",
        model=clean_model,
        input_tokens=clean_input,
        output_tokens=clean_output,
        cache_creation_input_tokens=clean_cache_creation,
        cache_read_input_tokens=clean_cache_read,
        cost_usd=_calculate_cost_usd(
            model=clean_model,
            input_tokens=clean_input,
            output_tokens=clean_output,
            cache_creation_input_tokens=clean_cache_creation,
            cache_read_input_tokens=clean_cache_read,
        ),
    )


def record_usage(
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
    agent: Optional[str] = None,
    account_id: Optional[int] = None,
    user_id: Optional[int] = None,
    feature: Optional[str] = None,
) -> TokenUsageRecord:
    """Build and enqueue a persistent LLM usage row."""
    record = build_record(
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_input_tokens=cache_creation_input_tokens,
        cache_read_input_tokens=cache_read_input_tokens,
        agent=agent,
        account_id=account_id,
        user_id=user_id,
        feature=feature,
    )
    enqueue(record)
    return record


def enqueue(record: TokenUsageRecord) -> None:
    """Append a record. Non-blocking. Spawns the writer thread if needed.

    If the queue is full (DB unreachable for a long time), the OLDEST
    record is dropped silently — current usage data is more valuable
    than ancient. ``_dropped_counter`` is bumped so a sentinel can alert
    on a saturated queue.
    """
    global _dropped_counter
    _ensure_writer_started()
    try:
        _queue.put_nowait(record)
    except queue.Full:
        # Drop oldest to make room.
        try:
            _queue.get_nowait()
            _queue.put_nowait(record)
        except (queue.Empty, queue.Full):
            pass
        with _dropped_lock:
            _dropped_counter += 1


def _ensure_writer_started() -> None:
    """Idempotent writer-thread start."""
    global _writer_thread
    if _writer_thread is not None and _writer_thread.is_alive():
        return
    with _thread_lock:
        if _writer_thread is not None and _writer_thread.is_alive():
            return
        _stop_event.clear()
        _writer_thread = threading.Thread(
            target=_writer_loop,
            daemon=True,
            name="token-usage-writer",
        )
        _writer_thread.start()


def _writer_loop() -> None:
    """Drain the queue every _FLUSH_INTERVAL_SECONDS until stop_event is set."""
    while not _stop_event.is_set():
        time.sleep(_FLUSH_INTERVAL_SECONDS)
        try:
            _flush_batch()
        except Exception as e:  # pragma: no cover — defensive
            logger.debug("token_usage writer flush failed: %s", e)


def _flush_batch() -> int:
    """Drain up to _BATCH_MAX records and bulk-insert them. Returns count written."""
    global _flushed_counter
    if _queue.empty():
        return 0
    rows: list[TokenUsageRecord] = []
    for _ in range(_BATCH_MAX):
        try:
            rows.append(_queue.get_nowait())
        except queue.Empty:
            break
    if not rows:
        return 0
    try:
        from app.db.database import get_db_session
        from app.db.repositories.token_usage_log_repository import TokenUsageLogRepository

        with get_db_session() as session:
            repo = TokenUsageLogRepository(session)
            for r in rows:
                repo.add(
                    account_id=r.account_id,
                    user_id=r.user_id,
                    agent=r.agent,
                    feature=r.feature,
                    model=r.model,
                    input_tokens=r.input_tokens,
                    output_tokens=r.output_tokens,
                    cache_creation_input_tokens=r.cache_creation_input_tokens,
                    cache_read_input_tokens=r.cache_read_input_tokens,
                    cost_usd=r.cost_usd,
                )
        with _dropped_lock:
            _flushed_counter += len(rows)
        return len(rows)
    except Exception as e:
        # On DB failure, requeue the rows at the END (best-effort: if the
        # queue is full we just drop them — same policy as enqueue).
        logger.debug("token_usage flush failed (%d rows requeued): %s", len(rows), e)
        for r in rows:
            try:
                _queue.put_nowait(r)
            except queue.Full:
                with _dropped_lock:
                    global _dropped_counter
                    _dropped_counter += 1
        return 0


def flush_now() -> int:
    """Force a synchronous flush. Used by app shutdown / tests."""
    return _flush_batch()


def get_writer_stats() -> dict:
    """Snapshot for the admin dashboard / sentinels."""
    with _dropped_lock:
        return {
            "queue_size": _queue.qsize(),
            "queue_max": _QUEUE_MAX,
            "flushed_total": _flushed_counter,
            "dropped_total": _dropped_counter,
            "alive": bool(_writer_thread and _writer_thread.is_alive()),
        }


def stop() -> None:
    """Stop the writer thread. Tests + graceful shutdown only."""
    _stop_event.set()
    flush_now()
