# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Cost enforcement at the LLM call path (audit 2026-05-06).

Pre-fix: ``app/infrastructure/cost_manager.py`` exposed
``can_proceed()`` and a configurable ``monthly_budget`` but was never
invoked from the request path. The audit table called this out as the
"single biggest cost-defense gap".

Post-fix:
- :class:`CostEnforcer` reads the actual production spend from
  ``token_usage_log`` (persistent, redeploy-resistant) and compares
  against two caps:
    * ``GLOBAL_MONTHLY_CAP_USD`` — total spend across all accounts
      (default 1000 USD).
    * ``USER_DAILY_CAP_USD`` — per-account spend for the current day
      (default 5 USD).
- :class:`CostGatedLLM` wraps any :class:`LLMPort`. Before forwarding
  ``complete()`` / ``stream()`` to the inner adapter, it checks the
  enforcer and raises :class:`CostBudgetExceededError` if a hard cap
  is exceeded. Soft-warn (80% of cap) is logged and emits a structured
  ``[COST_WARN]`` line a Sentinel L3 can scrape.
- Off by default. Enable globally with
  ``COST_ENFORCEMENT_ENABLED=true`` so ops can roll back instantly.

Cache: cap reads hit SQLite once per ``_CACHE_TTL_SECONDS`` (default
60s) — checking on every LLM call would 10x the DB QPS for no benefit;
60s lag is fine for guardrail enforcement.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------
class CostBudgetExceededError(Exception):
    """Raised when a hard cost cap is exceeded.

    Subclass of :class:`Exception` rather than ``LLMUnavailableError``
    so the caller can distinguish "stop and tell the user" from
    "retryable infra failure". Caller paths that catch generic
    ``Exception`` already log + return a fallback gracefully.
    """

    def __init__(
        self,
        scope: str,
        current_usd: float,
        cap_usd: float,
        account_id: Optional[int] = None,
    ):
        self.scope = scope          # 'global_monthly' | 'user_daily'
        self.current_usd = current_usd
        self.cap_usd = cap_usd
        self.account_id = account_id
        super().__init__(
            f"Cost cap exceeded: scope={scope} current=${current_usd:.4f} "
            f"cap=${cap_usd:.4f}"
            + (f" account_id={account_id}" if account_id else "")
        )


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------
def _is_production_env() -> bool:
    """True on a real production deployment (Railway / FLASK_ENV=production)."""
    if os.environ.get("AGENTYS_LOAD_TEST_MODE", "").strip().lower() in (
        "1", "true", "yes", "on",
    ):
        return False
    return any(
        os.environ.get(name) == "production"
        for name in (
            "FLASK_ENV",
            "ENVIRONMENT",
            "RAILWAY_ENVIRONMENT",
            "RAILWAY_ENVIRONMENT_NAME",
        )
    )


def _is_enforcement_enabled() -> bool:
    """Whether the LLM cost caps are enforced.

    Security (audit 2026-05-29, cost-DoS / CWE-770): now defaults ON in
    production so a single abusive/compromised account cannot drive unbounded
    spend on the shared Anthropic key. An explicit ``COST_ENFORCEMENT_ENABLED``
    env var ALWAYS wins (set it to ``false`` for an instant ops rollback);
    dev/test/local stay OFF by default.
    """
    raw = os.environ.get("COST_ENFORCEMENT_ENABLED", "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return _is_production_env()


def _global_monthly_cap_usd() -> Optional[float]:
    raw = os.environ.get("GLOBAL_MONTHLY_CAP_USD", "1000")
    try:
        v = float(raw)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return 1000.0


def _user_daily_cap_usd() -> Optional[float]:
    raw = os.environ.get("USER_DAILY_CAP_USD", "5")
    try:
        v = float(raw)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return 5.0


def _warn_pct() -> float:
    """Soft-warn threshold (default 0.80 — log a [COST_WARN] line)."""
    raw = os.environ.get("COST_WARN_PCT", "0.80")
    try:
        return max(0.0, min(1.0, float(raw)))
    except (TypeError, ValueError):
        return 0.80


# ---------------------------------------------------------------------------
# Enforcer
# ---------------------------------------------------------------------------
@dataclass
class CapStatus:
    cap_usd: float
    current_usd: float
    pct: float

    @property
    def hard_block(self) -> bool:
        return self.cap_usd > 0 and self.current_usd >= self.cap_usd

    @property
    def soft_warn(self) -> bool:
        return self.cap_usd > 0 and self.pct >= _warn_pct()


_CACHE_TTL_SECONDS = 60
_cache_lock = threading.Lock()
_cache_global: tuple[float, float] = (0.0, 0.0)         # (value_usd, ts)
_cache_user: dict[int, tuple[float, float]] = {}         # account_id → (value_usd, ts)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _start_of_today_utc() -> datetime:
    n = _utc_now()
    return n.replace(hour=0, minute=0, second=0, microsecond=0)


def _start_of_month_utc() -> datetime:
    n = _utc_now()
    return n.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _read_global_month_total_usd() -> float:
    """Sum cost_usd from token_usage_log for the current calendar month (UTC)."""
    cutoff = _start_of_month_utc()
    from app.db.database import get_db_session
    from app.db.models.token_usage_log import TokenUsageLogRow
    from sqlalchemy import func, select

    with get_db_session() as session:
        stmt = select(func.coalesce(func.sum(TokenUsageLogRow.cost_usd), 0.0)).where(
            TokenUsageLogRow.created_at >= cutoff
        )
        return float(session.execute(stmt).scalar() or 0.0)


def _read_user_day_total_usd(account_id: int) -> float:
    """Sum cost_usd for one account_id since UTC midnight today."""
    cutoff = _start_of_today_utc()
    from app.db.database import get_db_session
    from app.db.models.token_usage_log import TokenUsageLogRow
    from sqlalchemy import func, select

    with get_db_session() as session:
        stmt = (
            select(func.coalesce(func.sum(TokenUsageLogRow.cost_usd), 0.0))
            .where(TokenUsageLogRow.created_at >= cutoff)
            .where(TokenUsageLogRow.account_id == int(account_id))
        )
        return float(session.execute(stmt).scalar() or 0.0)


def get_global_monthly_status(account_id: Optional[int] = None) -> CapStatus:
    cap = _global_monthly_cap_usd() or 0.0
    now = time.time()
    with _cache_lock:
        v, ts = _cache_global
        if now - ts < _CACHE_TTL_SECONDS:
            current = v
        else:
            try:
                current = _read_global_month_total_usd()
            except Exception as e:
                logger.error("[CostEnforcer] global-month read failed; fail-closed: %s", e)
                raise CostBudgetExceededError(
                    "global_monthly_unavailable", cap, cap, account_id,
                ) from e
            globals()["_cache_global"] = (current, now)
    return CapStatus(
        cap_usd=cap,
        current_usd=round(current, 6),
        pct=(current / cap) if cap > 0 else 0.0,
    )


def get_user_daily_status(account_id: int) -> CapStatus:
    cap = _user_daily_cap_usd() or 0.0
    now = time.time()
    with _cache_lock:
        cached = _cache_user.get(int(account_id))
        if cached and (now - cached[1]) < _CACHE_TTL_SECONDS:
            current = cached[0]
        else:
            try:
                current = _read_user_day_total_usd(account_id)
            except Exception as e:
                logger.error(
                    "[CostEnforcer] user-day read failed; fail-closed account=%d: %s",
                    account_id, e,
                )
                raise CostBudgetExceededError(
                    "user_daily_unavailable", cap, cap, account_id,
                ) from e
            _cache_user[int(account_id)] = (current, now)
    return CapStatus(
        cap_usd=cap,
        current_usd=round(current, 6),
        pct=(current / cap) if cap > 0 else 0.0,
    )


def get_top_spenders_today(limit: int = 10) -> list[dict]:
    """Account-level snapshot for the admin dashboard (today, UTC)."""
    cutoff = _start_of_today_utc()
    try:
        from app.db.database import get_db_session
        from app.db.models.token_usage_log import TokenUsageLogRow
        from sqlalchemy import func, select

        with get_db_session() as session:
            stmt = (
                select(
                    TokenUsageLogRow.account_id,
                    func.sum(TokenUsageLogRow.cost_usd),
                    func.count(TokenUsageLogRow.id),
                )
                .where(TokenUsageLogRow.created_at >= cutoff)
                .where(TokenUsageLogRow.account_id.isnot(None))
                .group_by(TokenUsageLogRow.account_id)
                .order_by(func.sum(TokenUsageLogRow.cost_usd).desc())
                .limit(limit)
            )
            return [
                {
                    "account_id": int(aid),
                    "cost_usd": round(float(s or 0.0), 4),
                    "calls": int(c or 0),
                }
                for aid, s, c in session.execute(stmt).all()
            ]
    except Exception:
        return []


def check_or_raise(account_id: Optional[int]) -> None:
    """Hard-block if either cap is exceeded; soft-warn at 80%.

    Called before each LLM completion via :class:`CostGatedLLM`.
    Fail-closed on DB read errors. A cost ledger outage means we cannot
    prove the account is under budget, so the safe behavior is to stop
    new LLM spend until the ledger is readable again.
    """
    if not _is_enforcement_enabled():
        return

    g = get_global_monthly_status(account_id=account_id)
    if g.hard_block:
        logger.warning(
            "[COST_ENFORCE] global monthly cap hit: $%.4f / $%.4f",
            g.current_usd, g.cap_usd,
        )
        raise CostBudgetExceededError(
            "global_monthly", g.current_usd, g.cap_usd, account_id,
        )
    if g.soft_warn:
        logger.warning(
            "[COST_WARN] scope=global_monthly current=%.4f cap=%.4f pct=%.2f",
            g.current_usd, g.cap_usd, g.pct,
        )

    if account_id is None or account_id <= 0:
        return  # Background path with no caller scope.

    u = get_user_daily_status(account_id)
    if u.hard_block:
        logger.warning(
            "[COST_ENFORCE] user daily cap hit account=%d: $%.4f / $%.4f",
            account_id, u.current_usd, u.cap_usd,
        )
        raise CostBudgetExceededError(
            "user_daily", u.current_usd, u.cap_usd, account_id,
        )
    if u.soft_warn:
        logger.warning(
            "[COST_WARN] scope=user_daily account=%d current=%.4f cap=%.4f pct=%.2f",
            account_id, u.current_usd, u.cap_usd, u.pct,
        )


# ---------------------------------------------------------------------------
# LLM port wrapper
# ---------------------------------------------------------------------------
class CostGatedLLM:
    """Wraps an LLMPort and runs :func:`check_or_raise` before every call.

    Reads ``account_id`` from the LLM-attribution context
    (:mod:`app.infrastructure.llm_attribution`). When the context is
    unset (background path), only the global cap is enforced.

    Mirrors the underlying port's interface: ``complete``, ``stream``,
    ``model`` property, etc. Anything not explicitly proxied falls
    through via ``__getattr__`` so the wrapper is forward-compatible
    with port additions.
    """

    def __init__(self, inner: Any):
        self._inner = inner

    @property
    def name(self) -> str:
        return getattr(self._inner, "name", "cost-gated")

    @property
    def model(self) -> str:
        return getattr(self._inner, "model", "")

    def _check(self) -> None:
        try:
            from app.infrastructure.llm_attribution import current_account_id
            account_id = current_account_id()
        except Exception:
            account_id = None
        if account_id is None:
            try:
                from app.infrastructure.cost_manager import get_usage_context
                account_id = get_usage_context()[0]
            except Exception:
                account_id = None
        check_or_raise(account_id)

    def complete(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        self._check()
        return self._inner.complete(*args, **kwargs)

    def stream(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        self._check()
        return self._inner.stream(*args, **kwargs)

    def __getattr__(self, item: str) -> Any:
        # Forward anything not explicitly handled. ``__getattr__`` is only
        # called when normal lookup fails, so ``self._inner`` doesn't loop.
        return getattr(self._inner, item)
