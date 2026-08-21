# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Audit fix ISO-04 + ISO-05 + ISO-13 — `get_active_accounts()[0]` fall-through.

Bug: a dozen call sites resolve "the current account" by picking the first
result of `AccountRepository.get_active_accounts()` (sorted alphabetically
by email). On a multi-account install, this returns an arbitrary account
rather than the one belonging to the JWT caller. Endpoints affected:

  * `POST /api/sync/full` (sync.py:196)              — ISO-04
  * `GET /api/agent-marketplace/faq/stats`           — ISO-05
  * `GET /api/agent-marketplace/faq/history`         — ISO-05
  * `GET /api/labels._get_active_user_email`         — ISO-13 (used for CC)
  * background bodies in routes_emails, learning_refresh, daemon — ISO-13

Fix: route every "current account" lookup through
`_resolve_account_id_for_user` / `_get_current_account_for_user` (JWT-aware
helpers in `routes_helpers.py`), and refuse the request (or skip the
background side-effect) when no account can be scoped to the caller.

Run: `pytest tests/audit_fixes/test_iso_04_13_get_active_accounts_zero.py -v`
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterable, Optional
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("flask_cors")


@dataclass
class _FakeAccount:
    id: int
    email: str
    provider: str = "gmail"
    status: str = "active"


class _FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def close(self):
        pass


class _FakeAccountRepo:
    """Tracks whether `get_active_accounts()` or `get_by_email()` was used."""

    def __init__(self, accounts: Iterable[_FakeAccount]):
        self._by_email = {a.email: a for a in accounts}
        self.called_active = False
        self.called_by_email_with: Optional[str] = None

    def get_active_accounts(self):
        self.called_active = True
        return list(self._by_email.values())

    def get_by_email(self, email: str):
        self.called_by_email_with = email
        return self._by_email.get(email)

    def get(self, account_id: int):
        for a in self._by_email.values():
            if a.id == account_id:
                return a
        return None


@pytest.fixture
def app():
    from app.api.app import create_app
    return create_app(config={"TESTING": True})


@pytest.fixture
def client(app):
    return app.test_client()


def _stub_jwt(user_id: int, email: str):
    return patch(
        "app.api.auth._decode_jwt",
        return_value={"sub": user_id, "email": email},
    )


# --------------------------------------------------------------------------- #
# ISO-05: agent_marketplace.faq_stats / faq_history fall back to first account
# --------------------------------------------------------------------------- #


def _patched_marketplace(repo: _FakeAccountRepo, account_for_user_email: str):
    """Patch the routes used by faq_stats / faq_history to inject our fakes.

    The endpoint imports AccountRepository / FaqLogRepository / get_db_session
    INSIDE the handler — so we have to patch the modules they import from,
    not `app.api.agent_marketplace.X`.
    """
    fake_session = _FakeSession()

    @contextmanager
    def _fake_get_db_session():
        yield fake_session

    fake_faq_repo = MagicMock(
        get_stats=MagicMock(return_value={
            "auto_sent_count": 99,  # poisoned canary — must NEVER appear
            "skipped_count": 99,
            "avg_confidence": 0.99,
            "top_entries": [{"poisoned": True}],
            "period_days": 30,
        }),
        get_history=MagicMock(return_value=[
            MagicMock(to_dict=lambda: {"poisoned": True}),
        ]),
    )
    return [
        patch("app.db.database.get_db_session", _fake_get_db_session),
        patch(
            "app.db.repositories.account_repository.AccountRepository",
            lambda session: repo,
        ),
        patch(
            "app.db.repositories.faq_log_repository.FaqLogRepository",
            lambda session: fake_faq_repo,
        ),
    ]


def test_faq_stats_does_not_fall_back_to_first_active_account(app, client):
    """ISO-05: a JWT caller without an explicit `account_id` query param
    MUST NOT silently default to `accounts[0].id`. The endpoint should
    either resolve the JWT user's account or return a no-op payload —
    never fetch FaqLogRepository.get_stats(<somebody-else's-account>).
    """
    accounts = [
        _FakeAccount(id=1, email="alice@example.com"),
        _FakeAccount(id=2, email="bob@example.com"),
    ]
    # Bob is the JWT user. Alice sorts first alphabetically — buggy code
    # would default to alice.id == 1 because she sorts first in the
    # result of get_active_accounts().
    repo = _FakeAccountRepo(accounts)

    patches = _patched_marketplace(repo, account_for_user_email="bob@example.com")
    for p in patches:
        p.start()
    try:
        with _stub_jwt(user_id=2, email="stranger@example.com"):
            # `stranger` has no DB account → must not poach alice's.
            resp = client.get(
                "/api/agent-marketplace/faq/stats?days=30",
                headers={"Authorization": "Bearer stub"},
                environ_base={"REMOTE_ADDR": "203.0.113.10"},
            )
    finally:
        for p in patches:
            p.stop()

    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    # If the endpoint had used the buggy fall-through, it would have
    # returned the poisoned canary (auto_sent_count=99 from alice's faq).
    assert body.get("auto_sent_count", 0) != 99, (
        f"ISO-05 leak: stranger received the canary alice payload: {body!r}"
    )
    assert body.get("top_entries", []) == [], body
    # And the legacy fall-through must not have been used.
    assert repo.called_active is False, (
        "ISO-05 leak: faq_stats fell back to get_active_accounts()[0]"
    )


def test_faq_history_does_not_fall_back_to_first_active_account(app, client):
    """Same contract as above for /faq/history."""
    accounts = [
        _FakeAccount(id=1, email="alice@example.com"),
        _FakeAccount(id=2, email="bob@example.com"),
    ]
    repo = _FakeAccountRepo(accounts)

    patches = _patched_marketplace(repo, account_for_user_email="bob@example.com")
    for p in patches:
        p.start()
    try:
        with _stub_jwt(user_id=2, email="stranger@example.com"):
            resp = client.get(
                "/api/agent-marketplace/faq/history?limit=20",
                headers={"Authorization": "Bearer stub"},
                environ_base={"REMOTE_ADDR": "203.0.113.10"},
            )
    finally:
        for p in patches:
            p.stop()

    assert resp.status_code == 200
    body = resp.get_json()
    # Buggy fall-through would have returned alice's poisoned history.
    assert body == [], f"ISO-05 leak: stranger received: {body!r}"
    assert repo.called_active is False, (
        "ISO-05 leak: faq_history fell back to get_active_accounts()[0]"
    )


# --------------------------------------------------------------------------- #
# ISO-04: /api/sync/full pulls accounts[0].id
# --------------------------------------------------------------------------- #


def test_sync_full_does_not_use_first_active_account(app, client):
    """ISO-04: POST /api/sync/full must scope to the JWT caller — not pick
    `accounts[0]` and re-fetch IMAP into someone else's emails table.

    We don't actually run the IMAP fetch — we just guarantee that when the
    JWT user has no DB account, the endpoint refuses (does not silently
    operate on alice's account).
    """
    accounts = [
        _FakeAccount(id=1, email="alice@example.com"),
        _FakeAccount(id=2, email="bob@example.com"),
    ]
    repo = _FakeAccountRepo(accounts)
    fake_session = _FakeSession()

    @contextmanager
    def _fake_get_db_session():
        yield fake_session

    # Patch the IMAP factory to a hard sentinel — it must never be reached
    # if the scoping is correct.
    fake_provider = MagicMock(
        authenticate=MagicMock(side_effect=AssertionError(
            "ISO-04 leak: sync proceeded despite no scoped account_id"
        )),
    )

    # Stranger (no DB row) calls /sync/full. The sync handler imports its
    # dependencies INSIDE the function, so we patch the source modules.
    with patch("app.db.database.get_db_session", _fake_get_db_session), \
         patch("app.db.repositories.account_repository.AccountRepository",
               lambda session: repo), \
         patch("app.providers.factory.get_email_provider", return_value=fake_provider), \
         _stub_jwt(user_id=999, email="stranger@example.com"):
        resp = client.post(
            "/api/sync/full",
            headers={"Authorization": "Bearer stub"},
            environ_base={"REMOTE_ADDR": "203.0.113.10"},
        )

    # Acceptable outcomes: 400 (no account), 401, 403, or 404.
    # NOT acceptable: 200 (which would mean we ran sync on alice's account).
    assert resp.status_code in (400, 401, 403, 404), (
        f"ISO-04 leak: stranger was allowed to /sync/full and got "
        f"{resp.status_code} {resp.get_data(as_text=True)[:200]}"
    )
    # The buggy fall-through must not have been used.
    assert repo.called_active is False or repo.called_by_email_with is not None, (
        "Endpoint should resolve the user via get_by_email, not "
        "fall through to get_active_accounts()[0]"
    )
