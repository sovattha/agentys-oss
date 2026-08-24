# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""SQLAlchemy model for provider sync jobs.

Sync jobs isolate slow Gmail/Outlook/IMAP work from read-only list endpoints.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, TimestampMixin


SYNC_JOB_STATUS_QUEUED = "queued"
SYNC_JOB_STATUS_RUNNING = "running"
SYNC_JOB_STATUS_RETRY_WAITING = "retry_waiting"
SYNC_JOB_STATUS_COMPLETED = "completed"
SYNC_JOB_STATUS_FAILED = "failed"
SYNC_JOB_ACTIVE_STATUSES = (
    SYNC_JOB_STATUS_QUEUED,
    SYNC_JOB_STATUS_RUNNING,
    SYNC_JOB_STATUS_RETRY_WAITING,
)


class SyncJob(Base, TimestampMixin):
    """One provider synchronization request for an account/folder."""

    __tablename__ = "sync_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    account_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    folder: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    unread_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    coalesced_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    completed_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    backoff_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_units_estimate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        Index("ix_sync_jobs_account_folder_status", "account_id", "folder", "status"),
        Index("ix_sync_jobs_user_status_created", "user_id", "status", "created_at"),
        Index("ix_sync_jobs_status_backoff", "status", "backoff_until"),
        Index("ix_sync_jobs_lease_expires", "lease_expires_at"),
    )
