# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""DraftFeedback : explicit user verdict (accept / edit / reject) on an AI draft.

Complements ``draft_edit_events`` (auto-detected diff between IA draft and
sent version) with the user's explicit signal — including the rejection
case which the auto-detector cannot see (no "send" event happens when a
user trashes the draft and writes their own).

See migration ``20260505_000001_add_draft_feedback.py`` for schema rationale.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class DraftFeedbackRecord(Base):
    """Explicit user feedback on an AI-generated draft.

    Rationale for distinct table vs. extending DraftEditEvent: the edit-event
    table is auto-emitted on send-with-modifications. Feedback is user-driven
    and includes the **rejection** case (no send happens) which the edit
    table cannot capture.
    """

    __tablename__ = "draft_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    account_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    draft_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)

    # 'accept' | 'edit' | 'reject' — validated at the application layer
    # (cf. domain entity FeedbackAction enum).
    action: Mapped[str] = mapped_column(String(16), nullable=False)

    # 0.0–1.0, only populated for action='edit'. Other actions leave null.
    edit_distance: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    intent: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_draft_feedback_account_action_created", "account_id", "action", "created_at"),
    )
