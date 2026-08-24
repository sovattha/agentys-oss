# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Append-only audit log for Quick Step executions.

One row per ``engine.execute()`` call (and per ``run_auto_triggers`` step).
Distinct from :class:`QuickStepExecution` — that table is a 60-second
idempotency cache; this table is the long-term history surface used to
answer "did step X run on email Y?" after the cache expires.

Schema rationale:
  - ``step_name`` is denormalized (steps can be renamed or deleted; the log
    must remain readable even if the source step is gone).
  - ``actions_json`` keeps the per-action ok/error breakdown so failed
    chains can be inspected without replaying.
  - ``replay=True`` distinguishes idempotent replays from fresh runs so
    counts on this table are not double-charged for double-clicks.
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class QuickStepAuditLog(Base):
    __tablename__ = "quick_step_audit_log"
    __table_args__ = (
        Index("ix_quick_step_audit_log_account_created", "account_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_id: Mapped[str] = mapped_column(String(64), nullable=False)
    step_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email_id: Mapped[str] = mapped_column(String(255), nullable=False)
    # "manual" (user keypress / palette) | "auto" (daemon trigger).
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    executed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    actions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    replay: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False,
    )
