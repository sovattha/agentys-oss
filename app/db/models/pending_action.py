# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
PendingAction model for offline action queue.

Stores actions that need to be synced when connectivity is restored.
Actions are processed in FIFO order based on created_at timestamp.
"""

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.account import Account


class ActionType(str, Enum):
    """Types of actions that can be queued."""

    MARK_READ = "mark_read"
    MARK_UNREAD = "mark_unread"
    MARK_STARRED = "mark_starred"
    MARK_UNSTARRED = "mark_unstarred"
    DELETE = "delete"
    ARCHIVE = "archive"
    MOVE_TO_FOLDER = "move_to_folder"


class ActionStatus(str, Enum):
    """Status of a pending action."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PendingAction(Base, TimestampMixin):
    """
    Represents an action queued while offline.

    Actions are stored when the application is offline and need to
    be synced with the email provider when connectivity is restored.

    Attributes:
        id: Primary key.
        account_id: Foreign key to the account.
        action_type: Type of action (mark_read, mark_unread, etc.).
        email_id: Provider's email ID this action applies to.
        payload: Additional JSON payload for the action.
        status: Current status of the action.
        error_message: Error message if action failed.
        retry_count: Number of retry attempts.
        processed_at: When the action was processed.
    """

    __tablename__ = "pending_actions"

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True)

    # Account relationship
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Action details
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    email_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )  # Provider's email ID
    payload: Mapped[Optional[str]] = mapped_column(Text)  # JSON for additional data

    # Status tracking
    status: Mapped[str] = mapped_column(
        String(20), default=ActionStatus.PENDING.value, index=True
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(default=0)

    # Timestamps
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Relationships
    account: Mapped["Account"] = relationship("Account")

    # Composite indexes for common queries
    __table_args__ = (
        Index("ix_pending_actions_account_status", "account_id", "status"),
        Index("ix_pending_actions_status_created", "status", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<PendingAction(id={self.id}, type='{self.action_type}', "
            f"email='{self.email_id}', status='{self.status}')>"
        )

    def to_dict(self) -> dict:
        """Convert pending action to dictionary."""
        return {
            "id": self.id,
            "account_id": self.account_id,
            "action_type": self.action_type,
            "email_id": self.email_id,
            "payload": self.payload,
            "status": self.status,
            "error_message": self.error_message,
            "retry_count": self.retry_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "processed_at": self.processed_at.isoformat() if self.processed_at else None,
        }
