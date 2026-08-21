# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Token usage log model — queryable cost breakdown per (account, agent, day).

See migration ``20260506_000001_add_token_usage_log.py``.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Float, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class TokenUsageLogRow(Base):
    __tablename__ = "token_usage_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    agent: Mapped[str] = mapped_column(String(64), nullable=False)
    feature: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cache_creation_input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cache_read_input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False,
    )

    __table_args__ = (
        Index("ix_token_usage_log_account_created", "account_id", "created_at"),
        Index("ix_token_usage_log_agent_created", "agent", "created_at"),
        Index("ix_token_usage_log_user_created", "user_id", "created_at"),
        Index("ix_token_usage_log_feature_created", "feature", "created_at"),
    )
