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
OnboardingResult model for storing knowledge base analysis results.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.account import Account


class OnboardingResult(Base, TimestampMixin):
    """
    Stores the results of the onboarding knowledge base analysis.

    Each account has at most one active onboarding result. The analysis
    can be re-run, which creates a new result and marks the old one
    as superseded.

    Attributes:
        id: Primary key.
        account_id: Foreign key to the account.
        status: Analysis status (pending, running, completed, failed).
        emails_analysed: Number of emails processed.
        profile_json: JSON string of the UserProfile analysis.
        knowledge_json: JSON string of the KnowledgeBase analysis.
        rules_json: JSON string of the RulesSet analysis.
        error_message: Error details if status is 'failed'.
        started_at: When the analysis started.
        completed_at: When the analysis finished.
    """

    __tablename__ = "onboarding_results"

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True)

    # Account relationship
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Analysis status
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )  # pending, running, completed, failed

    # Metrics
    emails_analysed: Mapped[int] = mapped_column(Integer, default=0)

    # Analysis results (JSON strings)
    profile_json: Mapped[Optional[str]] = mapped_column(Text)
    knowledge_json: Mapped[Optional[str]] = mapped_column(Text)
    rules_json: Mapped[Optional[str]] = mapped_column(Text)
    categories_json: Mapped[Optional[str]] = mapped_column(Text)

    # Error tracking
    error_message: Mapped[Optional[str]] = mapped_column(Text)

    # Timing
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Relationships
    account: Mapped["Account"] = relationship("Account")

    def __repr__(self) -> str:
        return (
            f"<OnboardingResult(id={self.id}, account_id={self.account_id}, "
            f"status='{self.status}')>"
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "account_id": self.account_id,
            "status": self.status,
            "emails_analysed": self.emails_analysed,
            "error_message": self.error_message,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
