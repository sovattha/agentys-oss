# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Quick Step execution log — backs the cross-worker idempotency cache.

One row per (account_id, idempotency_key) — the unique constraint dedupes
retries. ``report_json`` stores the serialized ExecutionReport so a replay
returns the same outcome the first call produced.
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class QuickStepExecution(Base):
    __tablename__ = "quick_step_executions"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "idempotency_key",
            name="uq_quick_step_executions_account_key",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    report_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False, index=True,
    )
