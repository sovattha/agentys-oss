"""
Email model for storing cached emails.
"""

import json
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.account import Account
    from app.db.models.draft import Draft


# A marker color must be a bare 6-digit hex. We format-check (not whitelist)
# here on purpose: importing the quicksteps schema's palette into the DB model
# would create a circular import. The schema already whitelists the value at
# write time; this fullmatch is defense-in-depth so a corrupt/legacy row can
# never inject arbitrary CSS into the inbox row's style attribute.
_HEX_COLOR_RE = re.compile(r"#[0-9a-fA-F]{6}")


def _decode_emoji_marker(raw: Optional[str]) -> Optional[dict]:
    """Parse the JSON-stored emoji marker into the API response shape.

    Returns None when the column is empty / malformed, or when the marker
    carries neither an emoji nor text, so the inbox row just renders no chip
    rather than crashing the serializer or showing a blank pill.
    """
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    out: dict = {}
    # emoji and text are each optional (the "No emoji" tile ships text-only
    # markers), but at least one must be present for the chip to render.
    emoji = parsed.get("emoji")
    if isinstance(emoji, str) and emoji.strip():
        out["emoji"] = emoji
    text = parsed.get("text")
    if isinstance(text, str) and text.strip():
        out["text"] = text.strip()
    if not out:
        return None
    if parsed.get("include_deadline"):
        out["include_deadline"] = True
    color = parsed.get("color")
    if isinstance(color, str) and _HEX_COLOR_RE.fullmatch(color):
        out["color"] = color
    # chip surfaces only when explicitly False (bare rendering). True/absent
    # is the default pill — omit it so legacy rows decode identically.
    if parsed.get("chip") is False:
        out["chip"] = False
    return out


class Email(Base, TimestampMixin):
    """
    Represents a cached email message.

    Attributes:
        id: Primary key.
        email_id: Provider's unique message ID.
        account_id: Foreign key to the account.
        thread_id: Provider's thread/conversation ID.
        subject: Email subject line.
        sender: Sender email address.
        sender_name: Sender display name.
        recipients: Comma-separated recipient addresses.
        date: Email received/sent date.
        body_text: Plain text body.
        body_html: HTML body.
        is_read: Read status.
        is_starred: Starred/flagged status.
        labels: Comma-separated labels/folders.
        snippet: Short preview text.
    """

    __tablename__ = "emails"

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True)

    # Provider identifiers
    # unique=True removed — composite unique (email_id, account_id) enforced via __table_args__
    email_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    thread_id: Mapped[Optional[str]] = mapped_column(String(255), index=True)

    # Account relationship
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)

    # Email headers
    subject: Mapped[Optional[str]] = mapped_column(String(1000))
    sender: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    sender_name: Mapped[Optional[str]] = mapped_column(String(255))
    recipients: Mapped[Optional[str]] = mapped_column(Text)  # Comma-separated
    cc: Mapped[Optional[str]] = mapped_column(Text)  # Comma-separated
    bcc: Mapped[Optional[str]] = mapped_column(Text)  # Comma-separated

    # Email content
    date: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    body_text: Mapped[Optional[str]] = mapped_column(Text)
    body_html: Mapped[Optional[str]] = mapped_column(Text)
    snippet: Mapped[Optional[str]] = mapped_column(String(500))

    # Status flags
    is_read: Mapped[bool] = mapped_column(default=False)
    is_starred: Mapped[bool] = mapped_column(default=False)
    is_draft: Mapped[bool] = mapped_column(default=False)
    is_sent: Mapped[bool] = mapped_column(default=False)

    # Organization
    labels: Mapped[Optional[str]] = mapped_column(Text)  # Comma-separated
    folder: Mapped[Optional[str]] = mapped_column(String(255))

    # Inferred deadline (e.g. "due Mar 15", "expires 03/15") — populated by
    # the ingest-time deadline extractor (regex over the body). Optional;
    # NULL means no deadline detected. The inbox row renders a clock chip
    # when set, and the `has_deadline_detected` Quick Step trigger
    # condition reads this column. Indexed so a future "sort by deadline"
    # query stays cheap.
    deadline_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, index=True,
    )

    # Emoji marker stamped by the `mark_with_emoji` Quick Step action.
    # JSON shape: {"emoji": "💰", "text": "Stripe", "include_deadline": true}
    # `text` and `include_deadline` optional. Rendered as a chip right
    # after the subject on the inbox row. NULL means no marker. Read by
    # the `has_emoji_marker` trigger condition for chained rules.
    emoji_marker_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Attachments metadata (JSON string)
    attachments_meta: Mapped[Optional[str]] = mapped_column(Text)

    # RFC bulk-classification headers (JSON: {"list-unsubscribe": "<...>", ...}).
    # Populated at sync time by the provider adapter; consumed by the labelizer
    # so RFC noise rules (List-Unsubscribe, Precedence:bulk, Auto-Submitted)
    # actually fire on stored emails. Without this column the headers were
    # extracted but lost on persistence, which silently disabled the strongest
    # bulk-detection signal in the classifier (#bug-2026-05-01).
    raw_headers: Mapped[Optional[str]] = mapped_column(Text)

    # Relationships
    account: Mapped["Account"] = relationship("Account", back_populates="emails")
    drafts: Mapped[list["Draft"]] = relationship(
        "Draft",
        back_populates="original_email",
        passive_deletes=True,  # Let DB handle SET NULL on delete
    )

    # Composite indexes for common queries
    __table_args__ = (
        # Enforce uniqueness per account (IMAP UIDs are per-mailbox, not globally unique)
        Index("ix_emails_email_id_account", "email_id", "account_id", unique=True),
        # Primary listing: emails by account sorted by date
        Index("ix_emails_account_date", "account_id", "date"),
        # Unread count queries
        Index("ix_emails_account_read", "account_id", "is_read"),
        # Thread view: all emails in a conversation
        Index("ix_emails_thread_account_date", "thread_id", "account_id", "date"),
        # Sender filtering: emails from specific contact
        Index("ix_emails_sender_account_date", "sender", "account_id", "date"),
        # Unread list with date ordering (common query pattern)
        Index("ix_emails_account_read_date", "account_id", "is_read", "date"),
        # Starred emails listing
        Index("ix_emails_account_starred_date", "account_id", "is_starred", "date"),
        # Folder-based navigation
        Index("ix_emails_account_folder_date", "account_id", "folder", "date"),
        # Contact autocomplete: recipients field on sent emails
        Index("ix_emails_recipients", "recipients"),
        Index("ix_emails_is_sent_recipients", "is_sent", "recipients"),
    )

    def __repr__(self) -> str:
        return f"<Email(id={self.id}, subject='{self.subject[:30] if self.subject else None}...', sender='{self.sender}')>"

    def to_dict(self) -> dict:
        """Convert email to dictionary.
        BUG-003 fix: use email_id (provider hash ID) as 'id' for API compatibility,
        same as to_dict_headers(). The integer DB primary key is exposed as 'db_id'.
        """
        return {
            "id": self.email_id,   # hash ID — matches what the /process endpoint expects
            "db_id": self.id,      # integer PK — kept for internal/debug use
            "email_id": self.email_id,
            "thread_id": self.thread_id,
            "account_id": self.account_id,
            "subject": self.subject,
            "sender": self.sender,
            "sender_name": self.sender_name,
            "recipients": self.recipients.split(",") if self.recipients else [],
            "date": self.date.replace(tzinfo=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ') if self.date else None,
            "snippet": self.snippet,
            "is_read": self.is_read,
            "is_starred": self.is_starred,
            "labels": self.labels.split(",") if self.labels else [],
        }

    def to_dict_headers(self) -> dict:
        """
        Convert email to dictionary for list view (headers only, no body).

        Optimized for fast inbox rendering - returns only metadata needed
        for the email list, without the full body content.

        Returns:
            Dict with id, sender, subject, date, read status, and snippet.
        """
        # Audit 2026-05-18: compute the spoofed flag at read time so we
        # don't need a DB migration. The detector is pure CPU work, no I/O.
        from app.utils.sender_spoofing import detect_sender_spoofing
        cleaned_name, spoofed = detect_sender_spoofing(self.sender_name)
        return {
            "id": self.email_id,  # Use email_id for API compatibility
            "sender": self.sender,
            "sender_name": cleaned_name or self.sender_name,
            "sender_spoofed": spoofed,
            "subject": self.subject,
            "received_at": self.date.replace(tzinfo=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ') if self.date else None,
            "is_read": self.is_read,
            "snippet": (self.snippet[:150] if self.snippet else (self.body_text[:150] if self.body_text else "")),
            "has_attachments": bool(self.attachments_meta),
            "deadline_at": (
                self.deadline_at.replace(tzinfo=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
                if self.deadline_at else None
            ),
            "emoji_marker": _decode_emoji_marker(self.emoji_marker_json),
        }

    def to_dict_full(self) -> dict:
        """Convert email to dictionary with body content."""
        data = self.to_dict()
        data.update(
            {
                "body_text": self.body_text,
                "body_html": self.body_html,
                "cc": self.cc.split(",") if self.cc else [],
                "bcc": self.bcc.split(",") if self.bcc else [],
                "is_draft": self.is_draft,
                "is_sent": self.is_sent,
                "folder": self.folder,
                "attachments_meta": self.attachments_meta,
            }
        )
        return data
