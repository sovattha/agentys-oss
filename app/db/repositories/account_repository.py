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
Account repository for account-specific database operations.
"""

import time
from datetime import datetime
from typing import Optional, Sequence

from sqlalchemy import and_, select, update
from sqlalchemy.exc import OperationalError

from app.db.models.account import Account
from app.db.repositories.base import BaseRepository


class AccountRepository(BaseRepository[Account]):
    """
    Repository for Account model operations.
    """

    model = Account

    def get_by_email(self, email: str) -> Optional[Account]:
        """
        Get account by email address.

        Args:
            email: Email address to search for.

        Returns:
            Account if found, None otherwise.
        """
        stmt = select(Account).where(Account.email == email)
        return self.session.scalar(stmt)

    def get_active_accounts(self) -> Sequence[Account]:
        """
        Get all active accounts.

        Returns:
            List of active accounts.
        """
        stmt = select(Account).where(Account.is_active == True).order_by(Account.email)  # noqa: E712
        return self.session.scalars(stmt).all()

    def get_active_accounts_for_user(self, user_id: int) -> Sequence[Account]:
        """
        Get active accounts belonging to a specific JWT user.

        Legacy accounts with user_id=NULL are intentionally excluded: in web
        mode they must not leak between users. Tauri desktop (loopback) callers
        should keep using get_active_accounts().
        """
        stmt = (
            select(Account)
            .where(Account.is_active == True, Account.user_id == user_id)  # noqa: E712
            .order_by(Account.email)
        )
        return self.session.scalars(stmt).all()

    def get_by_provider(self, provider: str) -> Sequence[Account]:
        """
        Get accounts by provider type.

        Args:
            provider: Provider name (gmail, outlook, imap).

        Returns:
            List of accounts with the specified provider.
        """
        stmt = select(Account).where(Account.provider == provider).order_by(Account.email)
        return self.session.scalars(stmt).all()

    def activate_exclusive(self, account_id: int) -> bool:
        """
        Activate one account and deactivate the SAME-USER siblings.

        Pre-2026-04-27 this method deactivated ALL other accounts globally,
        which silently zeroed `is_active` on accounts owned by other JWT
        users every time anyone switched their current account. The visible
        symptom: a legitimate user's primary account vanishes from
        `/api/init` (filtered by `is_active=True`), the frontend falls back
        to a foreign account, the inbox shows the wrong mailbox or 4 emails
        instead of 500. Now: deactivation is scoped to the same `user_id`
        (or to the same NULL-user legacy bucket), preserving cross-user
        isolation.

        Args:
            account_id: ID of the account to activate.

        Returns:
            True if account was activated, False if not found.
        """
        account = self.get(account_id)
        if not account:
            return False

        # Deactivate same-user siblings only. user_id may be NULL on legacy
        # single-tenant accounts; treat the NULL-user bucket as its own
        # "user" so legacy accounts still enforce single-active among
        # themselves without affecting JWT-bound accounts.
        target_user_id = account.user_id
        if target_user_id is None:
            same_user_clause = Account.user_id.is_(None)
        else:
            same_user_clause = Account.user_id == target_user_id

        stmt = update(Account).where(
            and_(Account.id != account_id, same_user_clause)
        ).values(is_active=False)
        self.session.execute(stmt)

        # Activate the target
        account.is_active = True
        self.session.flush()
        return True

    def deactivate(self, account_id: int) -> bool:
        """
        Deactivate an account.

        Args:
            account_id: ID of the account to deactivate.

        Returns:
            True if account was deactivated, False if not found.
        """
        account = self.get(account_id)
        if account:
            account.is_active = False
            self.session.flush()
            # Audit P1-A4 (mother-of-all 2026-04-25) : évince l'entrée
            # auth_backoff du SyncService pour ne pas bloquer une éventuelle
            # ré-activation. Best-effort — si SyncService n'est pas démarré
            # (boot, tests), pas grave : il n'y a rien à évincer.
            try:
                from app.services.sync_service import get_sync_service
                _svc = get_sync_service()
                if _svc is not None:
                    _svc.evict_auth_backoff(account_id)
            except Exception:
                # Silent : éviction best-effort, le TTL (7j) prendra le relais.
                pass
            return True
        return False

    def update_sync_time(self, account_id: int, history_id: str | None = None) -> bool:
        """
        Update the last sync timestamp (and optionally historyId) for an account.

        Args:
            account_id: ID of the account to update.
            history_id: Optional Gmail historyId checkpoint for delta sync.

        Returns:
            True if updated, False if not found.
        """
        account = self.get(account_id)
        if account:
            account.last_sync_at = datetime.utcnow()
            if history_id is not None:
                account.last_history_id = history_id
            # Retry on transient SQLite "database is locked" errors
            for attempt in range(3):
                try:
                    self.session.flush()
                    return True
                except OperationalError as e:
                    if "database is locked" in str(e) and attempt < 2:
                        self.session.rollback()
                        time.sleep(0.5 * (attempt + 1))
                    else:
                        raise
        return False

    def update_tokens(
        self,
        account_id: int,
        access_token: str,
        refresh_token: Optional[str] = None,
        expires_at: Optional["datetime"] = None,
    ) -> bool:
        """
        Update OAuth tokens for an account.

        Args:
            account_id: ID of the account.
            access_token: New access token.
            refresh_token: Optional new refresh token.
            expires_at: Optional token expiration time.

        Returns:
            True if updated, False if not found.
        """

        account = self.get(account_id)
        if account:
            account.access_token = access_token
            if refresh_token:
                account.refresh_token = refresh_token
            if expires_at:
                account.token_expires_at = expires_at
            self.session.flush()
            return True
        return False
