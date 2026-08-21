"""
SQLAlchemy model for email-label assignments (SQLite table).

Mirrors the JSON assignments stored in label_store for fast SQL queries.
"""

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class EmailLabelRecord(Base):
    """
    Maps email_id → label_name for SQL-based label search.

    Written by LabelStore.save_assignment() (dual-write).
    Backfilled from assignments.json on first startup.
    """

    __tablename__ = "email_labels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email_id: Mapped[str] = mapped_column(String(255), nullable=False)
    account_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        default=1,
    )
    label_name: Mapped[str] = mapped_column(String(100), nullable=False)

    __table_args__ = (
        Index("ix_email_labels_label_account", "label_name", "account_id"),
        Index("ix_email_labels_email_id", "email_id"),
    )
