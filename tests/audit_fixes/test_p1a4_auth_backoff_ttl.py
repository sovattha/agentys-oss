# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""P1-A4: _auth_backoff TTL eviction must run even when no accounts exist.

Bug (mother-of-all audit 2026-04-25): when the user deletes their last
account, the sync loop returns early at `if not accounts: return` BEFORE
the per-account eviction loop. Backoff entries from the deleted account
survive forever (until process restart).

Fix: eviction runs unconditionally, before the early return.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from app.services.sync_service import SyncService


@pytest.fixture
def service():
    """Build a sync service without starting its thread."""
    svc = SyncService(sync_interval=60)
    return svc


def test_eviction_runs_when_zero_accounts(service):
    """A stale entry from a deleted account must be evicted by the next sync
    iteration even if no active accounts remain."""
    # Seed a stale entry: timestamp older than TTL (7 days = 604800 sec).
    now = time.monotonic()
    stale_ts = now - service._AUTH_BACKOFF_TTL - 60  # 1 min past TTL
    service._auth_backoff[42] = (5, now + 1000, stale_ts)

    # Mock get_db_session to return zero accounts (the deleted-all case).
    with patch("app.services.sync_service.get_db_session") as mock_session, \
         patch("app.services.sync_service.AccountRepository") as mock_repo:
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_repo.return_value.get_active_accounts.return_value = []

        service._perform_sync()

    # The entry must be gone — the eviction ran in the no-account path.
    assert 42 not in service._auth_backoff


def test_fresh_entry_survives_zero_accounts(service):
    """A non-stale entry should NOT be evicted by the no-account path."""
    now = time.monotonic()
    service._auth_backoff[7] = (1, now + 60, now)

    with patch("app.services.sync_service.get_db_session") as mock_session, \
         patch("app.services.sync_service.AccountRepository") as mock_repo:
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_repo.return_value.get_active_accounts.return_value = []

        service._perform_sync()

    assert 7 in service._auth_backoff
    failures, _, _ = service._auth_backoff[7]
    assert failures == 1


def test_evict_auth_backoff_explicit(service):
    """Explicit eviction by account_id (called when accounts are deactivated)."""
    now = time.monotonic()
    service._auth_backoff[100] = (3, now + 60, now)

    assert service.evict_auth_backoff(100) is True
    assert 100 not in service._auth_backoff
    # Idempotent: returns False when entry is gone.
    assert service.evict_auth_backoff(100) is False


def test_get_reauth_required_accounts_threshold(service):
    """Backoff API: surfaces accounts that need user re-OAuth."""
    now = time.monotonic()
    service._auth_backoff[1] = (5, now + 60, now)   # over threshold
    service._auth_backoff[2] = (1, now + 60, now)   # under threshold

    needs_reauth = service.get_reauth_required_accounts(threshold=3)
    assert 1 in needs_reauth
    assert 2 not in needs_reauth


def test_missing_oauth_scopes_count_as_reauth_required():
    """A Gmail 403 insufficient-scopes failure needs OAuth reconnection."""
    from app.services.sync_service import _is_reauth_required_error_message

    assert _is_reauth_required_error_message(
        "HttpError 403: Request had insufficient authentication scopes."
    ) is True
