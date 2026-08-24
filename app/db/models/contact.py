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
Contact model for storing email contacts.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.account import Account


class Contact(Base, TimestampMixin):
    """
    Represents an email contact extracted from email history.

    Attributes:
        id: Primary key.
        account_id: Foreign key to the account.
        email: Contact's email address.
        name: Contact's display name.
        email_count: Number of emails exchanged.
        last_contacted_at: Last email exchange timestamp.
        relationship_strength: Calculated relationship score.
        notes: User notes about the contact.
    """

    __tablename__ = "contacts"

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True)

    # Account relationship
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)

    # Contact info
    email: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    company: Mapped[Optional[str]] = mapped_column(String(255))
    title: Mapped[Optional[str]] = mapped_column(String(255))

    # Interaction tracking
    email_count: Mapped[int] = mapped_column(Integer, default=0)
    sent_count: Mapped[int] = mapped_column(Integer, default=0)
    received_count: Mapped[int] = mapped_column(Integer, default=0)
    last_contacted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    first_contacted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # AI analysis
    relationship_strength: Mapped[Optional[int]] = mapped_column(Integer)  # 0-100 score
    detected_tone: Mapped[Optional[str]] = mapped_column(String(50))  # formal, casual, friendly
    notes: Mapped[Optional[str]] = mapped_column(Text)

    # Pre-computed long-term context for drafter (replaces 20-email history)
    summary_json: Mapped[Optional[str]] = mapped_column(Text)
    summary_last_message_id: Mapped[Optional[str]] = mapped_column(String(255))
    summary_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Relationships
    account: Mapped["Account"] = relationship("Account", back_populates="contacts")

    # Composite indexes for common queries
    __table_args__ = (
        # Unique contact per account
        Index("ix_contacts_account_email", "account_id", "email", unique=True),
        # Top contacts by interaction count
        Index("ix_contacts_account_emailcount", "account_id", "email_count"),
        # Recent contacts by last interaction
        Index("ix_contacts_account_lastcontacted", "account_id", "last_contacted_at"),
    )

    def __repr__(self) -> str:
        return f"<Contact(id={self.id}, email='{self.email}', name='{self.name}')>"

    def to_dict(self) -> dict:
        """Convert contact to dictionary."""
        return {
            "id": self.id,
            "account_id": self.account_id,
            "email": self.email,
            "name": self.name,
            "company": self.company,
            "title": self.title,
            "email_count": self.email_count,
            "sent_count": self.sent_count,
            "received_count": self.received_count,
            "last_contacted_at": self.last_contacted_at.isoformat() if self.last_contacted_at else None,
            "relationship_strength": self.relationship_strength,
            "detected_tone": self.detected_tone,
        }
