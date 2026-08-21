# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Email cache manager.

Enforces the email cache limit per account by removing oldest emails
when the limit is exceeded.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import DEFAULT_CACHE_CONFIG
from app.db.models import Email

logger = logging.getLogger(__name__)


@dataclass
class CacheCleanupResult:
    """Result of a cache cleanup operation."""

    account_id: int
    emails_before: int
    emails_deleted: int
    emails_after: int
    oldest_deleted_date: Optional[datetime] = None
    newest_deleted_date: Optional[datetime] = None


class EmailCacheManager:
    """
    Manages email cache limits per account.

    Enforces a maximum number of emails per account by removing
    the oldest emails (by reception date) when the limit is exceeded.
    """

    def __init__(self, cache_limit: Optional[int] = None):
        """
        Initialize the cache manager.

        Args:
            cache_limit: Maximum emails per account. Uses config default if None.
        """
        self.cache_limit = cache_limit or DEFAULT_CACHE_CONFIG.email_cache_limit

    def get_email_count(self, session: Session, account_id: int) -> int:
        """
        Get the current email count for an account.

        Args:
            session: Database session.
            account_id: Account to count emails for.

        Returns:
            Number of emails cached for the account.
        """
        return (
            session.query(func.count(Email.id))
            .filter(Email.account_id == account_id)
            .scalar()
            or 0
        )

    def get_cache_stats(self, session: Session, account_id: int) -> dict:
        """
        Get cache statistics for an account.

        Args:
            session: Database session.
            account_id: Account to get stats for.

        Returns:
            Dictionary with cache statistics.
        """
        email_count = self.get_email_count(session, account_id)

        # Get date range
        oldest_date = (
            session.query(func.min(Email.date))
            .filter(Email.account_id == account_id)
            .scalar()
        )
        newest_date = (
            session.query(func.max(Email.date))
            .filter(Email.account_id == account_id)
            .scalar()
        )

        return {
            "account_id": account_id,
            "email_count": email_count,
            "cache_limit": self.cache_limit,
            "cache_usage_percent": round((email_count / self.cache_limit) * 100, 1)
            if self.cache_limit > 0
            else 0,
            "oldest_email": oldest_date.isoformat() if oldest_date else None,
            "newest_email": newest_date.isoformat() if newest_date else None,
        }

    def enforce_limit(
        self, session: Session, account_id: int, commit: bool = True
    ) -> CacheCleanupResult:
        """
        Enforce cache limit by removing oldest emails if count exceeds limit.

        Args:
            session: Database session.
            account_id: Account to enforce limit for.
            commit: Whether to commit the transaction.

        Returns:
            CacheCleanupResult with cleanup details.
        """
        emails_before = self.get_email_count(session, account_id)

        if emails_before <= self.cache_limit:
            return CacheCleanupResult(
                account_id=account_id,
                emails_before=emails_before,
                emails_deleted=0,
                emails_after=emails_before,
            )

        excess = emails_before - self.cache_limit

        # Get the oldest emails to delete (by date, not id)
        oldest_emails = (
            session.query(Email.id, Email.date)
            .filter(Email.account_id == account_id)
            .order_by(Email.date.asc())
            .limit(excess)
            .all()
        )

        if not oldest_emails:
            return CacheCleanupResult(
                account_id=account_id,
                emails_before=emails_before,
                emails_deleted=0,
                emails_after=emails_before,
            )

        email_ids_to_delete = [e.id for e in oldest_emails]
        oldest_deleted_date = oldest_emails[0].date
        newest_deleted_date = oldest_emails[-1].date

        # Delete the emails
        # SQLAlchemy will handle the cascade (SET NULL for drafts)
        # noqa: account-scoping -- email_ids_to_delete déjà filtrés par account_id ligne 137
        deleted_count = (
            session.query(Email)  # noqa: account-scoping -- IDs déjà scopés par account_id à la récupération
            .filter(Email.id.in_(email_ids_to_delete))
            .delete(synchronize_session=False)
        )

        if commit:
            session.commit()

        emails_after = emails_before - deleted_count

        logger.info(
            f"Cache cleanup for account {account_id}: "
            f"deleted {deleted_count} emails (before={emails_before}, after={emails_after})"
        )

        return CacheCleanupResult(
            account_id=account_id,
            emails_before=emails_before,
            emails_deleted=deleted_count,
            emails_after=emails_after,
            oldest_deleted_date=oldest_deleted_date,
            newest_deleted_date=newest_deleted_date,
        )

    def enforce_limit_all_accounts(
        self, session: Session, account_ids: List[int]
    ) -> List[CacheCleanupResult]:
        """
        Enforce cache limit for multiple accounts.

        Args:
            session: Database session.
            account_ids: List of account IDs to process.

        Returns:
            List of CacheCleanupResult for each account.
        """
        results = []

        for account_id in account_ids:
            try:
                result = self.enforce_limit(session, account_id, commit=False)
                results.append(result)
            except Exception as e:
                logger.error(f"Error enforcing cache limit for account {account_id}: {e}")
                results.append(
                    CacheCleanupResult(
                        account_id=account_id,
                        emails_before=0,
                        emails_deleted=0,
                        emails_after=0,
                    )
                )

        # Commit all changes at once
        session.commit()

        total_deleted = sum(r.emails_deleted for r in results)
        if total_deleted > 0:
            logger.info(
                f"Cache cleanup complete: {total_deleted} emails deleted "
                f"across {len(account_ids)} accounts"
            )

        return results


# Global cache manager instance
_cache_manager: Optional[EmailCacheManager] = None


def get_cache_manager() -> EmailCacheManager:
    """Get the global cache manager instance."""
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = EmailCacheManager()
    return _cache_manager


def init_cache_manager(cache_limit: Optional[int] = None) -> EmailCacheManager:
    """
    Initialize the global cache manager.

    Args:
        cache_limit: Maximum emails per account.

    Returns:
        The initialized EmailCacheManager instance.
    """
    global _cache_manager
    _cache_manager = EmailCacheManager(cache_limit=cache_limit)
    return _cache_manager
