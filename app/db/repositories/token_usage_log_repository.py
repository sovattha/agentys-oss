# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Repository for the token_usage_log table (audit 2026-05-06).

Appends are async (caller path uses a background queue — see
``app.infrastructure.token_usage_writer``). Reads serve the admin
dashboard, the per-user cost cards, and any future cost-cap enforcement.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.account import Account
from app.db.models.token_usage_log import TokenUsageLogRow


class TokenUsageLogRepository:
    def __init__(self, session: Session):
        self._session = session

    def add(
        self,
        *,
        account_id: Optional[int],
        user_id: Optional[int] = None,
        agent: str,
        feature: str = "unknown",
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_creation_input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
        cost_usd: float,
    ) -> int:
        row = TokenUsageLogRow(
            account_id=account_id,
            user_id=user_id,
            agent=agent or "unknown",
            feature=feature or "unknown",
            model=model or "?",
            input_tokens=int(input_tokens or 0),
            output_tokens=int(output_tokens or 0),
            cache_creation_input_tokens=int(cache_creation_input_tokens or 0),
            cache_read_input_tokens=int(cache_read_input_tokens or 0),
            cost_usd=float(cost_usd or 0.0),
        )
        self._session.add(row)
        self._session.flush()
        return row.id

    def cost_by_agent(self, since: Optional[datetime] = None) -> dict[str, float]:
        """Total $ spent per agent label since a cutoff (default last 30d)."""
        cutoff = since or (datetime.now(timezone.utc) - timedelta(days=30))
        stmt = (
            select(TokenUsageLogRow.agent, func.sum(TokenUsageLogRow.cost_usd))
            .where(TokenUsageLogRow.created_at >= cutoff)
            .group_by(TokenUsageLogRow.agent)
        )
        return {a: round(float(s or 0.0), 4) for a, s in self._session.execute(stmt).all()}

    def cost_by_account(self, since: Optional[datetime] = None) -> List[dict]:
        """Total $ spent per account_id since a cutoff (default last 30d)."""
        cutoff = since or (datetime.now(timezone.utc) - timedelta(days=30))
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
        )
        return [
            {
                "account_id": int(aid),
                "cost_usd": round(float(s or 0.0), 4),
                "calls": int(c or 0),
            }
            for aid, s, c in self._session.execute(stmt).all()
        ]

    def cost_by_user(self, since: Optional[datetime] = None) -> List[dict]:
        """Total usage per user_id since a cutoff (default last 30d).

        Rows written before background jobs propagated ``user_id`` can still
        be attributed when their ``account_id`` points to an account with a
        stable owner.
        """
        cutoff = since or (datetime.now(timezone.utc) - timedelta(days=30))
        user_expr = func.coalesce(TokenUsageLogRow.user_id, Account.user_id)
        total_tokens_expr = (
            TokenUsageLogRow.input_tokens
            + TokenUsageLogRow.output_tokens
            + TokenUsageLogRow.cache_creation_input_tokens
            + TokenUsageLogRow.cache_read_input_tokens
        )
        stmt = (
            select(
                user_expr.label("user_id"),
                func.count(func.distinct(TokenUsageLogRow.account_id)),
                func.sum(TokenUsageLogRow.cost_usd),
                func.sum(TokenUsageLogRow.input_tokens),
                func.sum(TokenUsageLogRow.output_tokens),
                func.sum(TokenUsageLogRow.cache_creation_input_tokens),
                func.sum(TokenUsageLogRow.cache_read_input_tokens),
                func.sum(total_tokens_expr),
                func.count(TokenUsageLogRow.id),
            )
            .outerjoin(Account, Account.id == TokenUsageLogRow.account_id)
            .where(TokenUsageLogRow.created_at >= cutoff)
            .where(user_expr.isnot(None))
            .group_by(user_expr)
            .order_by(func.sum(TokenUsageLogRow.cost_usd).desc())
        )
        return [
            {
                "user_id": int(user_id),
                "account_count": int(account_count or 0),
                "cost_usd": round(float(cost or 0.0), 4),
                "input_tokens": int(input_tokens or 0),
                "output_tokens": int(output_tokens or 0),
                "cache_creation_input_tokens": int(cache_creation_tokens or 0),
                "cache_read_input_tokens": int(cache_read_tokens or 0),
                "total_tokens": int(total_tokens or 0),
                "calls": int(calls or 0),
            }
            for (
                user_id,
                account_count,
                cost,
                input_tokens,
                output_tokens,
                cache_creation_tokens,
                cache_read_tokens,
                total_tokens,
                calls,
            ) in self._session.execute(stmt).all()
        ]

    def cost_for_user_period(
        self,
        *,
        user_id: int,
        start: datetime,
        end: datetime,
    ) -> dict:
        """Total token usage for one user over a billing period."""
        user_expr = func.coalesce(TokenUsageLogRow.user_id, Account.user_id)
        total_tokens_expr = (
            TokenUsageLogRow.input_tokens
            + TokenUsageLogRow.output_tokens
            + TokenUsageLogRow.cache_creation_input_tokens
            + TokenUsageLogRow.cache_read_input_tokens
        )
        stmt = (
            select(
                func.sum(TokenUsageLogRow.cost_usd),
                func.sum(total_tokens_expr),
                func.count(TokenUsageLogRow.id),
            )
            .outerjoin(Account, Account.id == TokenUsageLogRow.account_id)
            .where(user_expr == int(user_id))
            .where(TokenUsageLogRow.created_at >= start)
            .where(TokenUsageLogRow.created_at < end)
        )
        cost, total_tokens, calls = self._session.execute(stmt).one()
        return {
            "user_id": int(user_id),
            "cost_usd": round(float(cost or 0.0), 6),
            "total_tokens": int(total_tokens or 0),
            "calls": int(calls or 0),
        }

    def total_usage(self, since: Optional[datetime] = None) -> dict:
        """Total persisted usage since a cutoff (default last 30d)."""
        cutoff = since or (datetime.now(timezone.utc) - timedelta(days=30))
        total_tokens_expr = (
            TokenUsageLogRow.input_tokens
            + TokenUsageLogRow.output_tokens
            + TokenUsageLogRow.cache_creation_input_tokens
            + TokenUsageLogRow.cache_read_input_tokens
        )
        stmt = (
            select(
                func.sum(TokenUsageLogRow.cost_usd),
                func.sum(total_tokens_expr),
                func.count(TokenUsageLogRow.id),
            )
            .where(TokenUsageLogRow.created_at >= cutoff)
        )
        cost, total_tokens, calls = self._session.execute(stmt).one()
        return {
            "cost_usd": round(float(cost or 0.0), 4),
            "total_tokens": int(total_tokens or 0),
            "calls": int(calls or 0),
        }

    def daily_cost(self, days: int = 30) -> List[dict]:
        """Per-day total cost for the last `days` days, sorted oldest → newest."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        stmt = (
            select(
                func.date(TokenUsageLogRow.created_at).label("day"),
                func.sum(TokenUsageLogRow.cost_usd),
                func.count(TokenUsageLogRow.id),
            )
            .where(TokenUsageLogRow.created_at >= cutoff)
            .group_by(func.date(TokenUsageLogRow.created_at))
            .order_by(func.date(TokenUsageLogRow.created_at))
        )
        return [
            {
                "day": str(d),
                "cost_usd": round(float(s or 0.0), 4),
                "calls": int(c or 0),
            }
            for d, s, c in self._session.execute(stmt).all()
        ]

    def cost_for_account(
        self, account_id: int, days: int = 30
    ) -> dict:
        """Per-(agent, day) breakdown for a single account."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        # Total per agent
        per_agent_stmt = (
            select(TokenUsageLogRow.agent, func.sum(TokenUsageLogRow.cost_usd))
            .where(TokenUsageLogRow.created_at >= cutoff)
            .where(TokenUsageLogRow.account_id == account_id)
            .group_by(TokenUsageLogRow.agent)
        )
        per_agent = {
            a: round(float(s or 0.0), 4)
            for a, s in self._session.execute(per_agent_stmt).all()
        }
        # Daily totals
        daily_stmt = (
            select(
                func.date(TokenUsageLogRow.created_at).label("day"),
                func.sum(TokenUsageLogRow.cost_usd),
            )
            .where(TokenUsageLogRow.created_at >= cutoff)
            .where(TokenUsageLogRow.account_id == account_id)
            .group_by(func.date(TokenUsageLogRow.created_at))
            .order_by(func.date(TokenUsageLogRow.created_at))
        )
        daily = [
            {"day": str(d), "cost_usd": round(float(s or 0.0), 4)}
            for d, s in self._session.execute(daily_stmt).all()
        ]
        total = round(sum(per_agent.values()), 4)
        return {
            "account_id": account_id,
            "total_cost_usd": total,
            "by_agent": per_agent,
            "daily": daily,
            "window_days": days,
        }
