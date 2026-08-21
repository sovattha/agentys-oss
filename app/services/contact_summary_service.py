# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Contact summary service — pre-computed long-term context for the drafter.

Replaces the bulk of the 20-email conversation history in drafter prompts
with a structured, cached summary (relation, tone, recurring topics,
key facts, formulas). Saves ~46k input tokens per draft.

Flow:
    1. Draft hot path calls `get_summary_for_prompt(account_id, contact_email)`
    2. Service checks in-memory cache (15 min TTL).
    3. On miss: loads Contact row, checks staleness via message_id.
    4. If stale or missing: schedules a bounded background refresh.
    5. Returns a fresh/stale precomputed dict or None if unavailable.

Safety rails:
    - Skip for contacts with < 5 email interactions.
    - Any error → None → caller falls back to raw history behavior.
    - Feature-flagged via ENABLE_CONTACT_SUMMARY env var.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from app.contact_summary_privacy import minimize_contact_summary
from app.config import should_persist_email_content
from app.db.database import get_db_session
from app.db.repositories.contact_repository import ContactRepository
from app.db.repositories.email_repository import EmailRepository

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 15 * 60  # 15 min
_MIN_INTERACTIONS = 5
_SUMMARIZATION_EMAIL_POOL = 30  # how many past emails to feed the summarizer

_memory_cache: dict[tuple[int, str], tuple[float, Optional[dict]]] = {}
_cache_lock = threading.Lock()
_refresh_lock = threading.Lock()
_refresh_inflight: set[tuple[int, str]] = set()
_refresh_executor = ThreadPoolExecutor(
    max_workers=max(1, int(os.environ.get("CONTACT_SUMMARY_REFRESH_WORKERS", "2"))),
    thread_name_prefix="contact-summary-refresh",
)


def _feature_enabled() -> bool:
    val = os.environ.get("ENABLE_CONTACT_SUMMARY", "true").strip().lower()
    return val not in ("0", "false", "no", "off")


def _cache_get(key: tuple[int, str]) -> Optional[dict]:
    with _cache_lock:
        entry = _memory_cache.get(key)
        if not entry:
            return None
        ts, value = entry
        if time.time() - ts > _CACHE_TTL_SECONDS:
            _memory_cache.pop(key, None)
            return None
        return value


def _cache_set(key: tuple[int, str], value: Optional[dict]) -> None:
    with _cache_lock:
        _memory_cache[key] = (time.time(), value)
        # Trim to a reasonable bound to avoid unbounded growth.
        if len(_memory_cache) > 512:
            oldest = sorted(_memory_cache.items(), key=lambda kv: kv[1][0])[:128]
            for k, _ in oldest:
                _memory_cache.pop(k, None)


def invalidate_contact_summary(account_id: int, contact_email: str) -> None:
    """Drop a cached summary, e.g. after a new inbound email arrives."""
    with _cache_lock:
        _memory_cache.pop((account_id, contact_email.lower()), None)


def _summary_for_prompt(summary: object) -> Optional[dict]:
    if not isinstance(summary, dict):
        return None
    if should_persist_email_content():
        return summary
    minimized = minimize_contact_summary(summary)
    return minimized or None


def _submit_refresh(fn) -> None:
    _refresh_executor.submit(fn)


def _run_summary_refresh(
    account_id: int,
    contact_email: str,
    user_email: str,
    key: tuple[int, str],
) -> None:
    started = time.perf_counter()
    success = False
    usage_tokens = None
    try:
        try:
            from app.infrastructure.cost_manager import set_usage_context

            usage_tokens = set_usage_context(
                account_id=account_id,
                feature="contact_summary",
            )
        except Exception:
            usage_tokens = None

        with get_db_session() as session:
            contact_repo = ContactRepository(session)
            email_repo = EmailRepository(session)

            contact = contact_repo.get_by_email(contact_email, account_id)
            if not contact or (contact.email_count or 0) < _MIN_INTERACTIONS:
                _cache_set(key, None)
                return

            latest_msg_id = email_repo.get_latest_message_id_by_sender(
                contact_email, account_id
            )
            is_fresh = (
                contact.summary_json
                and contact.summary_last_message_id
                and contact.summary_last_message_id == latest_msg_id
            )
            if is_fresh:
                try:
                    parsed = json.loads(contact.summary_json)
                except Exception:
                    parsed = None
                _cache_set(key, _summary_for_prompt(parsed))
                return

            raw_emails = email_repo.get_by_sender(
                contact_email, account_id, limit=_SUMMARIZATION_EMAIL_POOL
            )
            if len(raw_emails) < 3:
                _cache_set(key, None)
                return

            email_dicts = [
                {
                    "sender": em.sender or "",
                    "subject": em.subject or "",
                    "date": em.date.isoformat() if em.date else "",
                    "body": (
                        (em.body_text or em.snippet or "")[:1500]
                        if should_persist_email_content()
                        else ""
                    ),
                }
                for em in raw_emails
            ]
            contact_id = contact.id

        # LLM call outside the DB session to avoid holding DB locks.
        from app.agents import ContactSummarizerAgent

        agent = ContactSummarizerAgent(account_id=account_id)
        summary = agent.summarize(email_dicts, user_email=user_email)
        if not summary:
            _cache_set(key, None)
            return

        summary_for_prompt = _summary_for_prompt(summary)
        if not summary_for_prompt:
            _cache_set(key, None)
            return

        summary_for_storage = (
            summary if should_persist_email_content() else summary_for_prompt
        )

        try:
            with get_db_session() as session:
                contact_repo = ContactRepository(session)
                contact_repo.update_summary(
                    contact_id=contact_id,
                    summary_json=json.dumps(summary_for_storage, ensure_ascii=False),
                    last_message_id=latest_msg_id,
                )
        except Exception as e:
            logger.warning(f"contact_summary_service: persist failed: {e}")

        _cache_set(key, summary_for_prompt)
        success = True

    except Exception as e:
        logger.warning(f"contact_summary_service: background refresh failed: {e}")
    finally:
        if usage_tokens is not None:
            try:
                from app.infrastructure.cost_manager import reset_usage_context

                reset_usage_context(usage_tokens)
            except Exception:
                pass
        with _refresh_lock:
            _refresh_inflight.discard(key)
        logger.info(
            "[PERF-DRAFT] phase=contact_summary_refresh account_id=%s "
            "contact=%s success=%s ms=%s",
            account_id,
            contact_email,
            success,
            int((time.perf_counter() - started) * 1000),
        )


def _schedule_summary_refresh(
    account_id: int,
    contact_email: str,
    user_email: str,
    key: tuple[int, str],
) -> None:
    with _refresh_lock:
        if key in _refresh_inflight:
            return
        _refresh_inflight.add(key)

    try:
        _submit_refresh(
            lambda: _run_summary_refresh(account_id, contact_email, user_email, key)
        )
    except Exception:
        with _refresh_lock:
            _refresh_inflight.discard(key)
        raise


def get_summary_for_prompt(
    account_id: int,
    contact_email: str,
    user_email: str = "",
) -> Optional[dict]:
    """Return a structured summary dict ready for prompt injection, or None.

    Steps:
        1. Feature flag check.
        2. Memory cache lookup.
        3. DB read + staleness check.
        4. Background refresh if stale/missing.
        5. Return a fresh/stale precomputed summary or None.

    Any exception path returns None so the caller falls back gracefully.
    """
    if not _feature_enabled():
        return None
    if not contact_email:
        return None

    key = (account_id, contact_email.lower())
    cached = _cache_get(key)
    if cached is not None:
        return _summary_for_prompt(cached)

    try:
        with get_db_session() as session:
            contact_repo = ContactRepository(session)
            email_repo = EmailRepository(session)

            contact = contact_repo.get_by_email(contact_email, account_id)
            if not contact:
                _cache_set(key, None)
                return None
            if (contact.email_count or 0) < _MIN_INTERACTIONS:
                _cache_set(key, None)
                return None

            latest_msg_id = email_repo.get_latest_message_id_by_sender(
                contact_email, account_id
            )
            is_fresh = (
                contact.summary_json
                and contact.summary_last_message_id
                and contact.summary_last_message_id == latest_msg_id
            )

            if is_fresh:
                try:
                    parsed = json.loads(contact.summary_json)
                except Exception:
                    parsed = None
                parsed = _summary_for_prompt(parsed)
                _cache_set(key, parsed)
                return parsed

            stale_summary = None
            if contact.summary_json:
                try:
                    stale_summary = _summary_for_prompt(json.loads(contact.summary_json))
                except Exception:
                    stale_summary = None

        if stale_summary:
            _cache_set(key, stale_summary)
            _schedule_summary_refresh(account_id, contact_email, user_email, key)
            return stale_summary

        _cache_set(key, None)
        _schedule_summary_refresh(account_id, contact_email, user_email, key)
        return None

    except Exception as e:
        logger.warning(f"contact_summary_service: get_summary_for_prompt failed: {e}")
        return None
