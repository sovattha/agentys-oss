"""
FaqAgentLog model — tracks FAQ agent actions for stats and dashboard.
"""

import uuid

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, func

from app.db.models.base import Base


class FaqAgentLog(Base):
    __tablename__ = "faq_agent_logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    # Audit FI-001 (2026-04-27): was Column(String) without FK — type mismatch
    # vs accounts.id (Integer) and orphans accumulated forever on account
    # delete. Now Integer + FK + CASCADE. Migration 018 backfills existing
    # rows by casting the string value with `CAST AS INTEGER`.
    account_id = Column(
        Integer,
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email_id = Column(String, nullable=False)
    action = Column(String, nullable=False)  # "auto_sent" or "skipped"
    confidence_score = Column(Float, nullable=False, default=0.0)
    matched_entry_id = Column(String, nullable=True)
    matched_entry_title = Column(String, nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "account_id": self.account_id,
            "email_id": self.email_id,
            "action": self.action,
            "confidence_score": self.confidence_score,
            "matched_entry_id": self.matched_entry_id,
            "matched_entry_title": self.matched_entry_title,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
