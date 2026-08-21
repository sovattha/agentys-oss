# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Regression tests for the /api/init data leak (2026-04-21).

Before the fix, GET /api/init returned every active account in the DB,
regardless of the JWT user, letting a remote user see accounts owned by
other users (their emails, provider, names were all exposed).

These tests lock in the account scoping behaviour:
  - Web/JWT mode on non-loopback → only the JWT user's accounts are returned,
    and current_account_id is resolved per user.
  - Loopback (Tauri desktop) → behaviour is unchanged (single-user app).

pytest tests/api/test_init_account_scoping.py -v
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest


@dataclass
class _FakeAccount:
    id: int
    email: str
    provider: str = "gmail"
    name: str = ""
    status: str = "active"
    user_id: Optional[int] = None


@pytest.fixture
def app():
    from app.api.app import create_app
    app = create_app(config={"TESTING": True})
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@contextmanager
def _jwt(user_id: Optional[int], email: str):
    """Stub _decode_jwt so apply_auth_guard sets g.auth_user as we want."""
    payload = {"sub": user_id, "email": email} if user_id is not None else None
    with patch("app.api.auth._decode_jwt", return_value=payload):
        yield


_JWT_HEADER = {"Authorization": "Bearer stub-token"}


class _FakeSession:
    """Minimal context manager replacement for _rh.get_db_session()."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    # Scalars/execute stubs for secondary fetches (spam_count / emails)
    def scalar(self, *args, **kwargs):
        return 0


class _FakeRepo:
    """Tracks which of the two fetch methods was called, to assert scoping."""

    def __init__(self, accounts):
        self._accounts = accounts
        self.called_all = False
        self.called_for_user_with = None

    def get_active_accounts(self):
        self.called_all = True
        return list(self._accounts)

    def get_active_accounts_for_user(self, user_id: int):
        self.called_for_user_with = user_id
        return [a for a in self._accounts if a.user_id == user_id]


@contextmanager
def _patched_init(
    repo: _FakeRepo,
    manager_current_by_user=None,
    resolved_account_id: Optional[int] = None,
):
    """Patch the SQLite + container touch points exercised by /api/init.

    Everything outside the account scoping path is stubbed so we isolate the
    regression target (accounts + current_account_id).

    ``resolved_account_id`` simulates ``_resolve_account_id_for_email``'s
    hash → email → DB int lookup that ``/api/init`` performs before
    serialising ``current_account_id`` (so the frontend's int-based match
    works — see ``routes_health.init_data``).
    """
    fake_manager = MagicMock()
    fake_manager.get_current_for_user.side_effect = (
        (lambda uid: (manager_current_by_user or {}).get(uid))
    )
    # Manager.get_account(hash) → object with an .email attribute the
    # handler feeds into _resolve_account_id_for_email().
    fake_manager.get_account.return_value = MagicMock(email="resolved@example.com")
    # Legacy Tauri current lookup — unused in web/JWT mode
    fake_current = MagicMock(id=(manager_current_by_user or {}).get(None))
    fake_current.email = "resolved@example.com"

    # Patch both the submodule path and the package-level re-export so the
    # fake repo is returned regardless of which import style the handler uses.
    with patch("app.api.routes_health._rh.get_db_session", return_value=_FakeSession()), \
         patch("app.api.routes_health._rh.EmailRepository") as _ER, \
         patch("app.api.routes_health._rh._get_container") as _ctr, \
         patch("app.api.routes_health._backfill_legacy_user_id"), \
         patch("app.db.repositories.AccountRepository", lambda session: repo), \
         patch("app.db.repositories.account_repository.AccountRepository",
               lambda session: repo), \
         patch("app.api.routes_health._resolve_account_id_cached", return_value=-1), \
         patch("app.api.routes_helpers._resolve_account_id_for_email",
               return_value=resolved_account_id if resolved_account_id is not None else -1), \
         patch("app.api.routes_health._get_cached_email_response", return_value=None), \
         patch("app.multi_accounts.get_account_manager", return_value=fake_manager), \
         patch("app.multi_accounts.get_current_account",
               return_value=fake_current if (manager_current_by_user or {}).get(None) else None):
        _ER.return_value.get_by_account.return_value = []
        _ctr.return_value.get_label_store.return_value.get_label_counts.return_value = {}
        _ctr.return_value.get_pending_draft_store.return_value.get_pending.return_value = []
        yield


# --------------------------------------------------------------------------- #
# Regression: JWT user on non-loopback must only see their own accounts
# --------------------------------------------------------------------------- #

def test_init_filters_accounts_for_jwt_user_on_non_loopback(app, client):
    """Web user 1 must not see accounts belonging to user 2 in /api/init."""
    accounts = [
        _FakeAccount(id=1, email="alice@example.com", user_id=1),
        _FakeAccount(id=2, email="bob@example.com", user_id=2),
        _FakeAccount(id=3, email="legacy@example.com", user_id=None),
    ]
    repo = _FakeRepo(accounts)

    with _jwt(user_id=1, email="alice@example.com"), \
         _patched_init(
             repo,
             manager_current_by_user={1: "hash-alice"},
             resolved_account_id=1,
         ):
        # Reset call trackers — unrelated helpers in the request path call
        # get_active_accounts() (e.g. _filter_self_sent_drafts on pending
        # drafts); only the handler's fetch for the /api/init "accounts"
        # field is under test here.
        repo.called_for_user_with = None
        resp = client.get(
            "/api/init",
            headers=_JWT_HEADER,
            environ_base={"REMOTE_ADDR": "203.0.113.10"},
        )

    assert resp.status_code == 200, resp.data
    payload = resp.get_json()

    # Behavioural contract: scoped lookup was used and only Alice's account
    # made it to the "accounts" field — Bob and the legacy account are absent.
    assert repo.called_for_user_with == 1
    returned_emails = {a["email"] for a in payload["accounts"]}
    assert returned_emails == {"alice@example.com"}
    # current_account_id is the DB int (post-resolution), not the manager hash
    # — the frontend matches accounts[].id (DB int) by string equality.
    assert payload["current_account_id"] == 1


def test_init_uses_unfiltered_fetch_on_loopback(app, client):
    """Tauri desktop (loopback) keeps the legacy single-user behaviour.

    Even when a JWT happens to be attached (stale web session), loopback
    requests fall back to get_active_accounts() — the desktop app is trusted.
    """
    accounts = [
        _FakeAccount(id=1, email="desktop@example.com", user_id=None),
        _FakeAccount(id=2, email="other@example.com", user_id=None),
    ]
    repo = _FakeRepo(accounts)

    with _jwt(user_id=1, email="alice@example.com"), \
         _patched_init(
             repo,
             manager_current_by_user={None: "hash-desktop"},
             resolved_account_id=1,
         ):
        repo.called_for_user_with = None
        resp = client.get(
            "/api/init",
            headers=_JWT_HEADER,
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )

    assert resp.status_code == 200, resp.data
    payload = resp.get_json()

    # Loopback must NEVER hit the scoped-by-user fetch — that would return an
    # empty list for legacy Tauri accounts (user_id=NULL).
    assert repo.called_for_user_with is None
    returned_emails = {a["email"] for a in payload["accounts"]}
    assert returned_emails == {"desktop@example.com", "other@example.com"}
    # Same contract as JWT path: handler now resolves to the DB int.
    assert payload["current_account_id"] == 1


def test_init_returns_empty_accounts_for_unknown_jwt_user(app, client):
    """A JWT whose user_id has no accounts must get an empty list, not a leak."""
    accounts = [
        _FakeAccount(id=1, email="alice@example.com", user_id=1),
        _FakeAccount(id=2, email="bob@example.com", user_id=2),
    ]
    repo = _FakeRepo(accounts)

    with _jwt(user_id=99, email="ghost@example.com"), \
         _patched_init(repo, manager_current_by_user={}):
        repo.called_for_user_with = None
        resp = client.get(
            "/api/init",
            headers=_JWT_HEADER,
            environ_base={"REMOTE_ADDR": "203.0.113.10"},
        )

    assert resp.status_code == 200, resp.data
    payload = resp.get_json()

    assert repo.called_for_user_with == 99
    assert payload["accounts"] == []
    assert payload["current_account_id"] is None
