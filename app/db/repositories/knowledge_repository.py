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
