"""
KnowledgeEntry model — structured knowledge base entries with categories.

Each entry belongs to an account and has a category (FAQ, TECHNIQUE, etc.)
to enable targeted agent behaviors like FAQ auto-reply.
"""

import uuid

from sqlalchemy import Column, ForeignKey, Integer, String, Text

from app.db.models.base import Base, TimestampMixin


class KnowledgeEntry(Base, TimestampMixin):
    __tablename__ = "knowledge_entries"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    account_id = Column(
        Integer,
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    category = Column(String, default="GENERAL", nullable=False, index=True)
    source = Column(String, default="manual", nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "account_id": self.account_id,
            "title": self.title,
            "content": self.content,
            "category": self.category,
            "source": self.source,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
