# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Audit 2026-05-29 — POST /api/emails/<id>/restore built a provider from the
GLOBAL email-owner lookup with no caller-ownership check, letting a tenant
un-archive/un-trash another tenant's email (cross-mailbox write).

Fix: ``_caller_owns_account(owner_int)`` gates the owner-resolved provider.
Same-user multi-account (Gmail+Outlook share user_id) stays allowed; a
cross-tenant owner falls back to the caller's own JWT-scoped provider.

Run: pytest tests/audit_fixes/test_isolation_2026_05_29_email_restore_owner.py -v
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _session_ctx(session):
    cm = MagicMock()
    cm.__enter__.return_value = session
    cm.__exit__.return_value = False
    return cm


def _run(owner_user_id, caller_uid):
    """Invoke _caller_owns_account with a mocked DB account owned by
    owner_user_id, as caller caller_uid."""
    from app.api.routes_emails import _caller_owns_account
    repo = MagicMock()
    repo.get.return_value = (
        None if owner_user_id is None else SimpleNamespace(user_id=owner_user_id)
    )
    with patch("app.api._auth_helpers.get_auth_user_id", return_value=caller_uid), \
         patch("app.db.database.get_db_session", return_value=_session_ctx(MagicMock())), \
         patch("app.db.repositories.account_repository.AccountRepository", return_value=repo):
        return _caller_owns_account(123)


def test_owner_same_user_allowed():
    """Caller 42 owns account whose user_id is 42 → True (multi-account)."""
    assert _run(owner_user_id=42, caller_uid=42) is True


def test_cross_tenant_owner_rejected():
    """Caller 42, account owned by user 99 → False (no cross-mailbox write)."""
    assert _run(owner_user_id=99, caller_uid=42) is False


def test_missing_account_rejected():
    assert _run(owner_user_id=None, caller_uid=42) is False


def test_loopback_no_jwt_trusted():
    """Tauri desktop (get_auth_user_id None) → True, no DB lookup needed."""
    from app.api.routes_emails import _caller_owns_account
    with patch("app.api._auth_helpers.get_auth_user_id", return_value=None):
        assert _caller_owns_account(123) is True
