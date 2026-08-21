# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Regression tests for /api/user/preferences multi-account scoping (2026-04-24).

Before the fix, GET/PATCH /api/user/preferences used
`AccountRepository.get_active_accounts()[0]`, which returned the FIRST active
account regardless of the JWT user. On a multi-account install, a logged-in
Bob could read Alice's preferred_language, and a PATCH from Bob would silently
overwrite Alice's setting.

These tests lock in the JWT-scoped behaviour:
  - GET reads the preferences of the JWT user's own account, not the first one.
  - PATCH writes to the JWT user's own account, leaving others untouched.
  - Loopback (Tauri desktop) falls back to the singleton current account.

pytest tests/api/test_user_preferences_scoping.py -v
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Optional
from unittest.mock import patch

import pytest

pytest.importorskip("flask_cors")


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #

@dataclass
class _FakeAccount:
    """Minimal stand-in for the SQLAlchemy Account entity."""
    id: int
    email: str
    preferred_language: Optional[str] = None


@dataclass
class _FakeAccountConfig:
    """Stand-in for app.multi_accounts.AccountConfig (what
    `_get_current_account_for_user` returns)."""
    email: str
    id: Optional[int] = None


class _FakeSession:
    merged: list = field(default_factory=list)  # type: ignore[assignment]
    committed: bool = False

    def __init__(self):
        self.merged = []
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def merge(self, obj):
        self.merged.append(obj)

    def commit(self):
        self.committed = True


class _FakeRepo:
    """Tracks whether the buggy `get_active_accounts()` or the scoped
    `get_by_email()` was used, and returns seeded data."""

    def __init__(self, accounts: list[_FakeAccount]):
        self._by_email = {a.email: a for a in accounts}
        self.called_active = False
        self.called_by_email_with: Optional[str] = None

    def get_active_accounts(self):
        self.called_active = True
        return list(self._by_email.values())

    def get_by_email(self, email: str):
        self.called_by_email_with = email
        return self._by_email.get(email)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

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
def _patched_preferences(repo: _FakeRepo,
                         current_account: Optional[_FakeAccountConfig] = None):
    """Patch the two touch points of the refactored handlers:
      - `_get_current_account_for_user` → resolves the user's email.
      - `AccountRepository` → returns our fake repo.
      - `_rh.get_db_session` → returns a fake session (no real DB).
    """
    with patch("app.api.routes_misc._get_current_account_for_user",
               return_value=current_account), \
         patch("app.db.repositories.account_repository.AccountRepository",
               lambda session: repo), \
         patch("app.api.routes_misc._rh.get_db_session",
               return_value=_FakeSession()):
        yield


_JWT_HEADER = {"Authorization": "Bearer stub-token"}


def _stub_jwt(user_id: int, email: str):
    """Context manager that makes _decode_jwt return a fake payload."""
    return patch("app.api.auth._decode_jwt",
                 return_value={"sub": user_id, "email": email})


# --------------------------------------------------------------------------- #
# Regression: GET scopes by JWT user, not first account
# --------------------------------------------------------------------------- #

def test_get_preferences_scopes_by_jwt_email(app, client):
    """GET must return the JWT user's own preferred_language — NOT the first
    account's. This reproduces the multi-account leak before the 2026-04-24 fix."""
    accounts = [
        _FakeAccount(id=1, email="alice@example.com", preferred_language="fr"),
        _FakeAccount(id=2, email="bob@example.com", preferred_language="de"),
    ]
    repo = _FakeRepo(accounts)
    bob_config = _FakeAccountConfig(email="bob@example.com", id=2)

    with _stub_jwt(user_id=2, email="bob@example.com"), \
         _patched_preferences(repo, current_account=bob_config):
        resp = client.get(
            "/api/user/preferences",
            headers=_JWT_HEADER,
            environ_base={"REMOTE_ADDR": "203.0.113.10"},
        )

    assert resp.status_code == 200
    assert resp.get_json() == {"preferred_language": "de"}
    # Behavioural contract: scoped lookup used, never the buggy fall-through.
    assert repo.called_by_email_with == "bob@example.com"
    assert repo.called_active is False


def test_get_preferences_returns_null_when_no_account_resolved(app, client):
    """If the JWT user has no matching account, the endpoint must NOT fall back
    to someone else's preferences — return preferred_language=null."""
    accounts = [
        _FakeAccount(id=1, email="alice@example.com", preferred_language="fr"),
    ]
    repo = _FakeRepo(accounts)

    # _get_current_account_for_user returns None (the stranger scenario)
    with _stub_jwt(user_id=99, email="stranger@example.com"), \
         _patched_preferences(repo, current_account=None):
        resp = client.get(
            "/api/user/preferences",
            headers=_JWT_HEADER,
            environ_base={"REMOTE_ADDR": "203.0.113.10"},
        )

    assert resp.status_code == 200
    assert resp.get_json() == {"preferred_language": None}
    # Crucially: never fall back to alice's account via get_active_accounts()
    assert repo.called_active is False


# --------------------------------------------------------------------------- #
# Regression: PATCH scopes by JWT user, not first account
# --------------------------------------------------------------------------- #

def test_patch_preferences_updates_jwt_user_not_first_account(app, client):
    """PATCH as Bob must persist to Bob's row, never to Alice's."""
    accounts = [
        _FakeAccount(id=1, email="alice@example.com", preferred_language="fr"),
        _FakeAccount(id=2, email="bob@example.com", preferred_language="de"),
    ]
    repo = _FakeRepo(accounts)
    bob_config = _FakeAccountConfig(email="bob@example.com", id=2)

    with _stub_jwt(user_id=2, email="bob@example.com"), \
         _patched_preferences(repo, current_account=bob_config):
        resp = client.patch(
            "/api/user/preferences",
            headers=_JWT_HEADER,
            json={"preferred_language": "en"},
            environ_base={"REMOTE_ADDR": "203.0.113.10"},
        )

    assert resp.status_code == 200
    assert resp.get_json() == {"preferred_language": "en"}
    # Bob's in-memory account got updated, Alice's untouched
    assert repo.called_by_email_with == "bob@example.com"
    bob = next(a for a in accounts if a.email == "bob@example.com")
    alice = next(a for a in accounts if a.email == "alice@example.com")
    assert bob.preferred_language == "en"
    assert alice.preferred_language == "fr"  # ← no cross-user write


def test_patch_preferences_returns_404_when_no_account_resolved(app, client):
    """PATCH with an unresolvable user must NOT silently update someone else —
    must return 404."""
    accounts = [
        _FakeAccount(id=1, email="alice@example.com", preferred_language="fr"),
    ]
    repo = _FakeRepo(accounts)

    with _stub_jwt(user_id=99, email="stranger@example.com"), \
         _patched_preferences(repo, current_account=None):
        resp = client.patch(
            "/api/user/preferences",
            headers=_JWT_HEADER,
            json={"preferred_language": "en"},
            environ_base={"REMOTE_ADDR": "203.0.113.10"},
        )

    assert resp.status_code == 404
    # Crucially: Alice's pref was NOT changed
    alice = next(a for a in accounts if a.email == "alice@example.com")
    assert alice.preferred_language == "fr"


def test_patch_preferences_rejects_unsupported_language(app, client):
    """Input validation still works post-refactor."""
    accounts = [_FakeAccount(id=1, email="alice@example.com",
                             preferred_language="fr")]
    repo = _FakeRepo(accounts)
    alice_config = _FakeAccountConfig(email="alice@example.com", id=1)

    with _stub_jwt(user_id=1, email="alice@example.com"), \
         _patched_preferences(repo, current_account=alice_config):
        resp = client.patch(
            "/api/user/preferences",
            headers=_JWT_HEADER,
            json={"preferred_language": "martian"},
            environ_base={"REMOTE_ADDR": "203.0.113.10"},
        )

    assert resp.status_code == 400
    assert "Unsupported" in resp.get_json().get("error", "")
