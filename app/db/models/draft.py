# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Draft model for storing AI-generated email drafts.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base, TimestampMixin
from app.draft_privacy import hide_draft_free_text_fields
from app.email_content_storage import should_persist_email_content

if TYPE_CHECKING:
    from app.db.models.account import Account
    from app.db.models.email import Email


class Draft(Base, TimestampMixin):
    """
    Represents an AI-generated email draft.

    Attributes:
        id: Primary key.
        account_id: Foreign key to the account.
        original_email_id: Foreign key to the email being replied to.
        subject: Draft subject line.
        body_text: Plain text body.
        body_html: HTML body.
        status: Draft status (draft, reviewed, approved, sent).
        generation_prompt: User instructions for generation.
        agent_model: AI model used for generation.
        iteration_count: Number of regenerations.
    """

    __tablename__ = "drafts"

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True)

    # Account relationship
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)

    # Original email reference (nullable for new compositions)
    original_email_id: Mapped[Optional[int]] = mapped_column(ForeignKey("emails.id", ondelete="SET NULL"), index=True)

    # Draft content
    subject: Mapped[Optional[str]] = mapped_column(String(1000))
    recipients: Mapped[Optional[str]] = mapped_column(Text)  # Comma-separated
    cc: Mapped[Optional[str]] = mapped_column(Text)
    bcc: Mapped[Optional[str]] = mapped_column(Text)
    body_text: Mapped[Optional[str]] = mapped_column(Text)
    body_html: Mapped[Optional[str]] = mapped_column(Text)

    # Status tracking
    status: Mapped[str] = mapped_column(String(50), default="draft", index=True)
    # Statuses: draft, reviewed, approved, sent, discarded

    # Generation metadata
    generation_prompt: Mapped[Optional[str]] = mapped_column(Text)
    agent_model: Mapped[Optional[str]] = mapped_column(String(100))
    iteration_count: Mapped[int] = mapped_column(Integer, default=1)
    tokens_used: Mapped[Optional[int]] = mapped_column(Integer)

    # User feedback
    user_edits: Mapped[Optional[str]] = mapped_column(Text)
    feedback_rating: Mapped[Optional[int]] = mapped_column(Integer)  # 1-5 stars
    feedback_notes: Mapped[Optional[str]] = mapped_column(Text)

    # Send tracking
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    sent_email_id: Mapped[Optional[str]] = mapped_column(String(255))

    # Relationships
    account: Mapped["Account"] = relationship("Account", back_populates="drafts")
    original_email: Mapped[Optional["Email"]] = relationship("Email", back_populates="drafts")

    # Composite indexes for common queries
    __table_args__ = (
        # Draft listing by account and status
        Index("ix_drafts_account_status_created", "account_id", "status", "created_at"),
        # Pending drafts sorted by last update
        Index("ix_drafts_account_status_updated", "account_id", "status", "updated_at"),
    )

    def __repr__(self) -> str:
        return f"<Draft(id={self.id}, subject='{self.subject[:30] if self.subject else None}...', status='{self.status}')>"

    def to_dict(self) -> dict:
        """Convert draft to dictionary."""
        return {
            "id": self.id,
            "account_id": self.account_id,
            "original_email_id": self.original_email_id,
            "subject": self.subject,
            "recipients": self.recipients.split(",") if self.recipients else [],
            "cc": self.cc.split(",") if self.cc else [],
            "body_text": self.body_text,
            "status": self.status,
            "iteration_count": self.iteration_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def to_dict_full(self) -> dict:
        """Convert draft to dictionary with all details."""
        data = self.to_dict()
        data.update(
            {
                "bcc": self.bcc.split(",") if self.bcc else [],
                "body_html": self.body_html,
                "generation_prompt": self.generation_prompt,
                "agent_model": self.agent_model,
                "tokens_used": self.tokens_used,
                "user_edits": self.user_edits,
                "feedback_rating": self.feedback_rating,
                "feedback_notes": self.feedback_notes,
                "sent_at": self.sent_at.isoformat() if self.sent_at else None,
                "sent_email_id": self.sent_email_id,
            }
        )
        if not should_persist_email_content():
            hide_draft_free_text_fields(data)
        return data
