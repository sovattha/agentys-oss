"""
Repository for KnowledgeEntry CRUD + category filtering.
"""

from typing import Optional, Sequence

from sqlalchemy import select

from app.db.models.knowledge_entry import KnowledgeEntry
from app.db.repositories.base import BaseRepository


class KnowledgeRepository(BaseRepository[KnowledgeEntry]):
    model = KnowledgeEntry

    def get_by_account(
        self,
        account_id: int,
        category: Optional[str] = None,
        limit: int = 200,
    ) -> Sequence[KnowledgeEntry]:
        stmt = (
            select(KnowledgeEntry)
            .where(KnowledgeEntry.account_id == account_id)
        )
        if category:
            stmt = stmt.where(KnowledgeEntry.category == category)
        stmt = stmt.order_by(KnowledgeEntry.updated_at.desc()).limit(limit)
        return self.session.scalars(stmt).all()

    def get_faq_entries(self, account_id: int) -> Sequence[KnowledgeEntry]:
        return self.get_by_account(account_id, category="FAQ")

    def get_category_counts(self, account_id: int) -> dict[str, int]:
        entries = self.get_by_account(account_id)
        counts: dict[str, int] = {}
        for e in entries:
            counts[e.category] = counts.get(e.category, 0) + 1
        return counts
