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
Account model for storing connected email accounts.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import BigInteger, Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base, TimestampMixin
from app.db.types import EncryptedString

if TYPE_CHECKING:
    from app.db.models.contact import Contact
    from app.db.models.draft import Draft
    from app.db.models.email import Email


class Account(Base, TimestampMixin):
    """
    Represents a connected email account (Gmail, Outlook, IMAP).

    Attributes:
        id: Primary key.
        email: Email address of the account.
        provider: Email provider (gmail, outlook, imap).
        display_name: User-friendly name for the account.
        access_token: Encrypted OAuth access token.
        refresh_token: Encrypted OAuth refresh token.
        token_expires_at: Token expiration timestamp.
        last_sync_at: Last successful sync timestamp.
        is_active: Whether the account is active.
    """

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)  # gmail, outlook, imap
    display_name: Mapped[Optional[str]] = mapped_column(String(255))
    avatar_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    # OAuth tokens — Fernet-encrypted at the column level (CASA Tier 2).
    # Plaintext never lands on disk; raw SELECT shows opaque base64url
    # ciphertext. See app/db/types/encrypted.py.
    access_token: Mapped[Optional[str]] = mapped_column(EncryptedString)
    refresh_token: Mapped[Optional[str]] = mapped_column(EncryptedString)
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Email signature (migrated from provider on account connection)
    signature_html: Mapped[Optional[str]] = mapped_column(Text)  # HTML signature (unlimited, supports base64 images)
    signature_text: Mapped[Optional[str]] = mapped_column(String(4096))  # Plain text fallback
    signature_user_modified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="0")  # True if user edited signature in Agentys

    # User preferences
    preferred_language: Mapped[str] = mapped_column(String(10), default='fr', nullable=False, server_default='fr')
    settings_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Per-account settings overrides (JSON)
    quick_steps_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # User-defined Quick Steps action chains (JSON list)
    pinned_email_ids_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON array of pinned email IDs

    # Multi-user isolation: links this account to a JWT user (None = legacy/Tauri desktop)
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)

    # Sync tracking
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_history_id: Mapped[Optional[str]] = mapped_column(Text)  # Gmail historyId or Outlook deltaLink checkpoint
    is_active: Mapped[bool] = mapped_column(default=True)

    # Gmail Pub/Sub push tracking (N3 — event-driven sync).
    # gmail_watch_expiration: when the current users.watch() call expires
    # (Gmail caps at 7 days). gmail_watch_topic: fully-qualified Pub/Sub
    # topic name (projects/X/topics/Y). Both NULL when push is not set up.
    gmail_watch_expiration: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    gmail_watch_topic: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    # Relationships
    emails: Mapped[list["Email"]] = relationship(
        "Email",
        back_populates="account",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )
    contacts: Mapped[list["Contact"]] = relationship(
        "Contact",
        back_populates="account",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )
    drafts: Mapped[list["Draft"]] = relationship(
        "Draft",
        back_populates="account",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    def __repr__(self) -> str:
        return f"<Account(id={self.id}, email='{self.email}', provider='{self.provider}')>"

    def to_dict(self) -> dict:
        """Convert account to dictionary (without sensitive tokens)."""
        return {
            "id": self.id,
            "email": self.email,
            "provider": self.provider,
            "display_name": self.display_name,
            "last_sync_at": self.last_sync_at.isoformat() if self.last_sync_at else None,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "has_signature": bool(self.signature_html or self.signature_text),
            "user_id": self.user_id,
        }

    def get_signature(self, html: bool = True) -> Optional[str]:
        """Get the account's email signature.

        Args:
            html: If True, return HTML signature; otherwise return plain text.

        Returns:
            The signature string or None if not set.
        """
        if html and self.signature_html:
            return self.signature_html
        if self.signature_text:
            return self.signature_text
        # Fallback: strip HTML tags from signature_html to produce a plain-text version
        if self.signature_html:
            import re
            return re.sub(r'<[^>]+>', '', self.signature_html).strip() or None
        return None
