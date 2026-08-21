# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Repository for ``DraftFeedback`` (audit 2026-05-05).

Mirrors :mod:`app.db.repositories.draft_edit_event_repository`. Scoped by
``account_id`` to prevent cross-tenant reads.
"""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.draft_feedback import DraftFeedbackRecord
from app.domain.entities.draft_feedback import DraftFeedback, FeedbackAction


def _entity_from_row(row: DraftFeedbackRecord) -> DraftFeedback:
    return DraftFeedback(
        account_id=row.account_id,
        draft_id=row.draft_id,
        action=FeedbackAction(row.action),
        edit_distance=row.edit_distance,
        intent=row.intent,
        note=row.note,
        created_at=row.created_at,
    )


class DraftFeedbackRepository:
    def __init__(self, session: Session):
        self._session = session

    def add(self, feedback: DraftFeedback) -> int:
        """Persist a feedback row. Caller commits via ``get_db_session`` ctx."""
        row = DraftFeedbackRecord(
            account_id=feedback.account_id,
            draft_id=feedback.draft_id,
            action=feedback.action.value,
            edit_distance=feedback.edit_distance,
            intent=feedback.intent,
            note=feedback.note,
        )
        self._session.add(row)
        self._session.flush()
        return row.id

    def list_for_account(
        self,
        account_id: int,
        limit: int = 100,
        action: Optional[FeedbackAction] = None,
    ) -> List[DraftFeedback]:
        stmt = (
            select(DraftFeedbackRecord)
            .where(DraftFeedbackRecord.account_id == account_id)
            .order_by(DraftFeedbackRecord.created_at.desc())
            .limit(limit)
        )
        if action is not None:
            stmt = stmt.where(DraftFeedbackRecord.action == action.value)
        rows = self._session.execute(stmt).scalars().all()
        return [_entity_from_row(r) for r in rows]

    def action_counts(self, account_id: int) -> dict[str, int]:
        """Aggregate { 'accept': N, 'edit': N, 'reject': N } for the account.

        Source of truth for the rejection-rate metric the Critic threshold
        tuner uses. SQL groups already filter by account so no leakage.
        """
        stmt = (
            select(DraftFeedbackRecord.action, func.count(DraftFeedbackRecord.id))
            .where(DraftFeedbackRecord.account_id == account_id)
            .group_by(DraftFeedbackRecord.action)
        )
        return {act: int(count) for act, count in self._session.execute(stmt).all()}

    def avg_edit_distance(self, account_id: int) -> Optional[float]:
        """Mean edit_distance across all 'edit' rows for this account.

        Returns None if no edit events yet. A high mean (> 0.4) tells the
        Critic tuner that the user systematically heavy-edits drafts —
        suggesting the quality_threshold is too lenient.
        """
        stmt = (
            select(func.avg(DraftFeedbackRecord.edit_distance))
            .where(DraftFeedbackRecord.account_id == account_id)
            .where(DraftFeedbackRecord.action == FeedbackAction.EDIT.value)
            .where(DraftFeedbackRecord.edit_distance.isnot(None))
        )
        avg = self._session.execute(stmt).scalar()
        return float(avg) if avg is not None else None
