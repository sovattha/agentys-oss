"""
Draft repository for draft-specific database operations.
"""

from datetime import datetime
from typing import Optional, Sequence

from sqlalchemy import select, func

from app.config import should_persist_email_content
from app.db.models.draft import Draft
from app.db.repositories.base import BaseRepository
from app.draft_privacy import minimize_draft_free_text_fields


class DraftRepository(BaseRepository[Draft]):
    """
    Repository for Draft model operations.
    """

    model = Draft

    def create(self, entity: Draft) -> Draft:
        if not should_persist_email_content():
            minimize_draft_free_text_fields(entity)
        return super().create(entity)

    def create_all(self, entities: Sequence[Draft]) -> Sequence[Draft]:
        if not should_persist_email_content():
            for entity in entities:
                minimize_draft_free_text_fields(entity)
        return super().create_all(entities)

    def get_by_account(
        self,
        account_id: int,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Draft]:
        """
        Get drafts for an account.

        Args:
            account_id: Account ID to filter by.
            status: Optional status filter (draft, reviewed, approved, sent).
            limit: Maximum number of results.
            offset: Number of results to skip.

        Returns:
            List of drafts ordered by creation date descending.
        """
        stmt = select(Draft).where(Draft.account_id == account_id)

        if status:
            stmt = stmt.where(Draft.status == status)

        stmt = stmt.order_by(Draft.created_at.desc()).limit(limit).offset(offset)
        return self.session.scalars(stmt).all()

    def get_by_original_email(self, original_email_id: int) -> Sequence[Draft]:
        """
        Get all drafts for a specific original email.

        Args:
            original_email_id: ID of the original email.

        Returns:
            List of drafts for the email.
        """
        stmt = (
            select(Draft)
            .where(Draft.original_email_id == original_email_id)
            .order_by(Draft.created_at.desc())
        )
        return self.session.scalars(stmt).all()

    def get_pending_drafts(self, account_id: int) -> Sequence[Draft]:
        """
        Get all pending drafts (not yet sent or discarded).

        Args:
            account_id: Account ID to filter by.

        Returns:
            List of pending drafts.
        """
        stmt = (
            select(Draft)
            .where(
                Draft.account_id == account_id,
                Draft.status.in_(["draft", "reviewed", "approved"]),
            )
            .order_by(Draft.updated_at.desc())
        )
        return self.session.scalars(stmt).all()

    def count_by_account(self, account_id: int, status: Optional[str] = None) -> int:
        """
        Count drafts for an account.

        Args:
            account_id: Account ID to count drafts for.
            status: Optional status filter.

        Returns:
            Number of drafts.
        """
        stmt = select(func.count(Draft.id)).where(Draft.account_id == account_id)
        if status:
            stmt = stmt.where(Draft.status == status)
        return self.session.scalar(stmt) or 0

    def update_status(self, draft_id: int, status: str) -> bool:
        """
        Update draft status.

        Args:
            draft_id: ID of the draft.
            status: New status (draft, reviewed, approved, sent, discarded).

        Returns:
            True if updated, False if not found.
        """
        valid_statuses = {"draft", "reviewed", "approved", "sent", "discarded"}
        if status not in valid_statuses:
            raise ValueError(f"Invalid status. Must be one of: {valid_statuses}")

        draft = self.get(draft_id)
        if draft:
            draft.status = status
            self.session.flush()
            return True
        return False

    def mark_as_sent(
        self,
        draft_id: int,
        sent_email_id: Optional[str] = None,
    ) -> bool:
        """
        Mark a draft as sent.

        Args:
            draft_id: ID of the draft.
            sent_email_id: Provider's ID of the sent email.

        Returns:
            True if updated, False if not found.
        """
        draft = self.get(draft_id)
        if draft:
            draft.status = "sent"
            draft.sent_at = datetime.utcnow()
            if sent_email_id:
                draft.sent_email_id = sent_email_id
            self.session.flush()
            return True
        return False

    def update_content(
        self,
        draft_id: int,
        subject: Optional[str] = None,
        body_text: Optional[str] = None,
        body_html: Optional[str] = None,
    ) -> bool:
        """
        Update draft content.

        Args:
            draft_id: ID of the draft.
            subject: New subject.
            body_text: New plain text body.
            body_html: New HTML body.

        Returns:
            True if updated, False if not found.
        """
        draft = self.get(draft_id)
        if draft:
            if subject is not None:
                draft.subject = subject
            if body_text is not None:
                draft.body_text = body_text
            if body_html is not None:
                draft.body_html = body_html
            draft.iteration_count += 1
            self.session.flush()
            return True
        return False

    def add_feedback(
        self,
        draft_id: int,
        rating: Optional[int] = None,
        notes: Optional[str] = None,
    ) -> bool:
        """
        Add user feedback to a draft.

        Args:
            draft_id: ID of the draft.
            rating: Rating from 1-5.
            notes: Feedback notes.

        Returns:
            True if updated, False if not found.
        """
        if rating is not None and not 1 <= rating <= 5:
            raise ValueError("Rating must be between 1 and 5")

        draft = self.get(draft_id)
        if draft:
            if rating is not None:
                draft.feedback_rating = rating
            if notes is not None:
                draft.feedback_notes = notes if should_persist_email_content() else None
            self.session.flush()
            return True
        return False

    def record_user_edits(self, draft_id: int, edits: str) -> bool:
        """
        Record user's manual edits to the draft.

        Args:
            draft_id: ID of the draft.
            edits: JSON string describing the edits made.

        Returns:
            True if updated, False if not found.
        """
        draft = self.get(draft_id)
        if draft:
            draft.user_edits = edits if should_persist_email_content() else None
            draft.status = "reviewed"
            self.session.flush()
            return True
        return False

    def get_stats_by_account(self, account_id: int) -> dict:
        """
        Get draft statistics for an account.

        Args:
            account_id: Account ID.

        Returns:
            Dict with draft statistics.
        """
        total = self.count_by_account(account_id)
        pending = self.count_by_account(account_id, status="draft")
        reviewed = self.count_by_account(account_id, status="reviewed")
        approved = self.count_by_account(account_id, status="approved")
        sent = self.count_by_account(account_id, status="sent")
        discarded = self.count_by_account(account_id, status="discarded")

        # Average feedback rating
        rating_stmt = select(func.avg(Draft.feedback_rating)).where(
            Draft.account_id == account_id,
            Draft.feedback_rating.isnot(None),
        )
        avg_rating = self.session.scalar(rating_stmt)

        return {
            "total": total,
            "pending": pending,
            "reviewed": reviewed,
            "approved": approved,
            "sent": sent,
            "discarded": discarded,
            "average_rating": float(avg_rating) if avg_rating else None,
        }
