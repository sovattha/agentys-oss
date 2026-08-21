"""Repository pour ``DraftEditEvent`` (#196).

Utilise la session SQLAlchemy globale (``app.db.database``). Scoped par
``account_id`` pour l'isolation multi-compte.
"""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.draft_edit_event import DraftEditEvent
from app.domain.entities.draft_edit_event import EditCategory, EditEvent


def _entity_from_row(row: DraftEditEvent) -> EditEvent:
    return EditEvent(
        draft_id=row.draft_id,
        account_id=row.account_id,
        category=EditCategory(row.category),
        magnitude=row.magnitude,
        initial_length=row.initial_length,
        final_length=row.final_length,
        intent=row.intent,
        recipient_email=row.recipient_email,
        original_email_id=row.original_email_id,
        created_at=row.created_at,
    )


class DraftEditEventRepository:
    """Repository scoped pour les événements d'édition de drafts."""

    def __init__(self, session: Session):
        self._session = session

    def add(self, event: EditEvent) -> int:
        """Persiste l'événement. Retourne l'ID généré.

        Ne fait pas de commit : c'est la responsabilité du context manager
        appelant (``get_db_session``).
        """
        row = DraftEditEvent(
            account_id=event.account_id,
            draft_id=event.draft_id,
            original_email_id=event.original_email_id,
            category=event.category.value,
            magnitude=event.magnitude,
            initial_length=event.initial_length,
            final_length=event.final_length,
            intent=event.intent,
            recipient_email=event.recipient_email,
        )
        self._session.add(row)
        self._session.flush()
        return row.id

    def list_for_account(
        self,
        account_id: int,
        limit: int = 100,
        category: Optional[EditCategory] = None,
    ) -> List[EditEvent]:
        """Retourne les événements récents pour un compte, optionnellement filtrés."""
        stmt = (
            select(DraftEditEvent)
            .where(DraftEditEvent.account_id == account_id)
            .order_by(DraftEditEvent.created_at.desc())
            .limit(limit)
        )
        if category is not None:
            stmt = stmt.where(DraftEditEvent.category == category.value)
        rows = self._session.execute(stmt).scalars().all()
        return [_entity_from_row(r) for r in rows]

    def category_counts(self, account_id: int) -> dict[str, int]:
        """Agrège les counts par catégorie pour détecter les patterns récurrents.

        Utilisé par la UI « Patterns détectés » — ex : si
        ``length_adjustment`` > N, proposer un ajustement du WritingStyleProfile.
        """
        stmt = (
            select(DraftEditEvent.category, func.count(DraftEditEvent.id))
            .where(DraftEditEvent.account_id == account_id)
            .group_by(DraftEditEvent.category)
        )
        return {cat: int(count) for cat, count in self._session.execute(stmt).all()}
