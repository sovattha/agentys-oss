"""
Repository for OnboardingResult model operations.
"""

from typing import Optional, Sequence

from sqlalchemy import select

from app.db.models.onboarding_result import OnboardingResult
from app.db.repositories.base import BaseRepository


class OnboardingRepository(BaseRepository[OnboardingResult]):
    """
    Repository for OnboardingResult CRUD and queries.
    """

    model = OnboardingResult

    def get_by_account(self, account_id: int) -> Optional[OnboardingResult]:
        """
        Get the latest onboarding result for an account.

        Args:
            account_id: Account ID.

        Returns:
            Latest OnboardingResult or None.
        """
        stmt = (
            select(OnboardingResult)
            .where(OnboardingResult.account_id == account_id)
            .order_by(OnboardingResult.created_at.desc())
            .limit(1)
        )
        return self.session.scalar(stmt)

    # Statuses that mean "this account has a run actively in flight". Anything
    # else (completed/failed/partial) is a terminal state, and the next call
    # to start() should create a fresh row.
    ACTIVE_STATUSES = ("pending", "waiting_for_sync", "running")

    def find_active(self, account_id: int) -> Optional[OnboardingResult]:
        """
        Return the most-recent onboarding row for an account whose status is
        still in-flight (pending / waiting_for_sync / running).

        Used by ``OnboardingManager.start()`` to deduplicate concurrent
        trigger requests — if the frontend fires 4 POSTs in 2 seconds, we
        want to return the single already-running onboarding instead of
        spawning 4 parallel orchestrators (16× LLM cost, file write races).

        Args:
            account_id: Account ID.

        Returns:
            Active OnboardingResult, or None if no active run exists.
        """
        # Order by id DESC (auto-increment, monotonic) rather than created_at
        # which can tie when two rows land in the same wall-clock second.
        stmt = (
            select(OnboardingResult)
            .where(
                OnboardingResult.account_id == account_id,
                OnboardingResult.status.in_(self.ACTIVE_STATUSES),
            )
            .order_by(OnboardingResult.id.desc())
            .limit(1)
        )
        return self.session.scalar(stmt)

    def get_completed_by_account(self, account_id: int) -> Optional[OnboardingResult]:
        """
        Get the latest completed onboarding result for an account.

        Args:
            account_id: Account ID.

        Returns:
            Latest completed OnboardingResult or None.
        """
        stmt = (
            select(OnboardingResult)
            .where(
                OnboardingResult.account_id == account_id,
                OnboardingResult.status == "completed",
            )
            .order_by(OnboardingResult.created_at.desc())
            .limit(1)
        )
        return self.session.scalar(stmt)

    def get_all_by_account(self, account_id: int) -> Sequence[OnboardingResult]:
        """
        Get all onboarding results for an account.

        Args:
            account_id: Account ID.

        Returns:
            List of OnboardingResult ordered by created_at desc.
        """
        stmt = (
            select(OnboardingResult)
            .where(OnboardingResult.account_id == account_id)
            .order_by(OnboardingResult.created_at.desc())
        )
        return self.session.scalars(stmt).all()
