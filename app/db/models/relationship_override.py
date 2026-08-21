# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
SQLAlchemy model for storing user overrides of relationship type detection.
"""

from sqlalchemy import ForeignKey, Integer, String, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, TimestampMixin


class RelationshipOverride(Base, TimestampMixin):
    """
    Stores user manual overrides of relationship type detection.

    When a user corrects the automatically detected relationship type,
    the override is stored here and takes precedence over auto-detection.

    Attributes:
        id: Primary key.
        account_id: The user's account ID.
        contact_email: Email address of the contact.
        relationship_type: The user-specified relationship type.
        created_at: When the override was first created.
        updated_at: When the override was last modified.
    """

    __tablename__ = "relationship_overrides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contact_email: Mapped[str] = mapped_column(String(255), nullable=False)
    relationship_type: Mapped[str] = mapped_column(String(50), nullable=False)

    __table_args__ = (
        UniqueConstraint("account_id", "contact_email", name="uq_account_contact_relationship"),
        Index("ix_relationship_override_account_contact", "account_id", "contact_email"),
    )

    def __repr__(self) -> str:
        return (
            f"<RelationshipOverride(id={self.id}, account_id={self.account_id}, "
            f"contact_email='{self.contact_email}', relationship_type='{self.relationship_type}')>"
        )
