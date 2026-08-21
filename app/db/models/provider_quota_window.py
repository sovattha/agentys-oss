"""Durable provider quota counters for sync dispatch."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, TimestampMixin


class ProviderQuotaWindow(Base, TimestampMixin):
    """Reserved provider units for one scope and one fixed time window."""

    __tablename__ = "provider_quota_windows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    quota_scope: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_key: Mapped[str] = mapped_column(String(128), nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    units_reserved: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "quota_scope",
            "scope_key",
            "window_start",
            name="uq_provider_quota_window",
        ),
        Index("ix_provider_quota_windows_window", "provider", "window_start"),
    )
