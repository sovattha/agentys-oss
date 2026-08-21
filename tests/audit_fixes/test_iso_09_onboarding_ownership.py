# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Audit fix ISO-09 — `_resolve_db_account_id` skips its ownership check when
`effective_user_email == ""`.

Bug: in `app/api/onboarding.py:25-96`, the ownership check at lines 82-94
is gated on `if effective_user_email:`. If the caller has no JWT and no
loopback session resolves to an account, `effective_user_email` is the
empty string. The function then falls through to
`int(account_id_or_hash)` matching, returning **any** existing account_id
(1, 2, 3 — enumerable). Onboarding then runs on someone else's mailbox.

Fix: refuse to resolve when no caller identity could be established.
Return / raise without doing the integer-id fall-through.

Run: `pytest tests/audit_fixes/test_iso_09_onboarding_ownership.py -v`
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterable, Optional
from unittest.mock import patch

import pytest


@dataclass
class _FakeAccount:
    id: int
    email: str


class _FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeAccountRepo:
    def __init__(self, accounts: Iterable[_FakeAccount]):
        self._accounts = list(accounts)

    def get_active_accounts(self):
        return list(self._accounts)


def _patches(repo: _FakeAccountRepo, current_account: Optional[object] = None):
    fake_session = _FakeSession()

    @contextmanager
    def _fake_get_db_session():
        yield fake_session

    return [
        patch("app.db.database.get_db_session", _fake_get_db_session),
        patch(
            "app.db.repositories.account_repository.AccountRepository",
            lambda session: repo,
        ),
        patch(
            "app.api.routes_helpers._get_current_account_for_user",
            return_value=current_account,
        ),
    ]


def test_resolve_int_id_without_caller_identity_must_be_rejected():
    """ISO-09: when the caller has no JWT and no loopback session resolves
    to an account, `_resolve_db_account_id` MUST refuse — not silently
    return whatever int ID was passed in.

    This prevents an unauthenticated remote user from enumerating
    account_ids and overwriting another user's onboarding_results.
    """
    accounts = [
        _FakeAccount(id=1, email="alice@example.com"),
        _FakeAccount(id=2, email="bob@example.com"),
    ]
    repo = _FakeAccountRepo(accounts)

    patches = _patches(repo, current_account=None)
    for p in patches:
        p.start()
    try:
        from app.api.onboarding import _resolve_db_account_id
        with pytest.raises((PermissionError, ValueError)):
            # Stranger passes account_id=1 (alice's). Without caller identity
            # the function must refuse, not return 1.
            _resolve_db_account_id(1, user_email="")
    finally:
        for p in patches:
            p.stop()


def test_resolve_with_legitimate_caller_still_works():
    """Regression: a user passing their own email still gets resolved."""
    accounts = [
        _FakeAccount(id=1, email="alice@example.com"),
        _FakeAccount(id=2, email="bob@example.com"),
    ]
    repo = _FakeAccountRepo(accounts)

    patches = _patches(repo, current_account=None)
    for p in patches:
        p.start()
    try:
        from app.api.onboarding import _resolve_db_account_id
        resolved = _resolve_db_account_id(2, user_email="bob@example.com")
        assert resolved == 2
    finally:
        for p in patches:
            p.stop()


def test_resolve_blocks_cross_account_enumeration_with_jwt():
    """ISO-09: when bob (with JWT email) asks for alice's account_id=1,
    the resolver must NOT return alice's id.

    Two equally-secure outcomes:
      - Raise PermissionError (defence-in-depth), or
      - Resolve to bob's own account (id=2), since the email match wins.

    Both are safe — we just want to lock in that "bob → 1" never returns 1.
    """
    accounts = [
        _FakeAccount(id=1, email="alice@example.com"),
        _FakeAccount(id=2, email="bob@example.com"),
    ]
    repo = _FakeAccountRepo(accounts)

    patches = _patches(repo, current_account=None)
    for p in patches:
        p.start()
    try:
        from app.api.onboarding import _resolve_db_account_id
        try:
            resolved_id = _resolve_db_account_id(1, user_email="bob@example.com")
        except PermissionError:
            return  # safe outcome
        # If it didn't raise, it MUST have resolved to bob's own account.
        assert resolved_id == 2, (
            f"ISO-09 leak: bob asked for account_id=1 (alice's) and got "
            f"resolved_id={resolved_id!r}"
        )
    finally:
        for p in patches:
            p.stop()
