# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""`include_self` query param on /api/contacts/autocomplete.

Regression: the inline From/To/CC filters in `SmartSearchBar` were returning
"Aucun résultat" when the user typed their own name. Cause: the autocomplete
endpoint strips ALL the user's multi-account emails when `sent_only=false`
(the default search mode). For compose recipients that's correct (avoid
self-references); for search filters it's wrong — finding emails from one's
own other account is a valid intent.

This test locks in the new opt-in `include_self=true` param:
  - default mode: multi-account emails (other than the active account) are
    stripped, matching prior behavior.
  - include_self=true: those emails survive the strip, so search filters
    can surface them.
  - active account's own_email is ALWAYS stripped (typing your active
    address is a no-op for filters; chips handle that path explicitly).
  - cache key differs between modes so the two responses don't alias.
"""
from __future__ import annotations

from collections import namedtuple
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

# Mock row shape matches what SQLAlchemy returns from the senders query
# (Email.sender, Email.sender_name, freq) and recipients query
# (Email.recipients, freq).
SenderRow = namedtuple("SenderRow", ["sender", "sender_name", "freq"])
RecipRow = namedtuple("RecipRow", ["recipients", "freq"])


@pytest.fixture(scope="module")
def app():
    from app.api.app import create_app
    return create_app(config={"TESTING": True})


@pytest.fixture
def client(app):
    return app.test_client()


def _build_session_with(senders, recipients):
    """Build a MagicMock SQLAlchemy session whose .query(...).filter(...)
    chain returns the given mock rows.

    The route builds two distinct queries:
      - senders: `query(Email.sender, Email.sender_name, func.count(...))`  → 3 cols
      - recipients: `query(Email.recipients, func.count(...))`              → 2 cols

    Dispatch on column count, which is the most stable signal across
    SQLAlchemy versions (the column reprs change shape between releases).
    """
    session = MagicMock()

    def query_factory(*cols):
        rows = senders if len(cols) >= 3 else recipients
        q = MagicMock()
        q.filter.return_value = q
        q.group_by.return_value = q
        q.all.return_value = rows
        return q

    session.query.side_effect = query_factory
    return session


def _patch_route_deps(senders, recipients, *, active_email, all_account_emails, account_id=1):
    """Stack of patches that lets the autocomplete handler run without a
    real DB / account manager / JWT.

    `active_email` is the account whose row is currently being filtered;
    `all_account_emails` is the full multi-account list returned by
    `mgr.get_all_accounts()`. Both are normalised to lowercase to match
    what the route compares against.
    """
    session = _build_session_with(senders, recipients)

    @contextmanager
    def fake_db_session():
        yield session

    fake_active = MagicMock()
    fake_active.email = active_email
    fake_all = [MagicMock(email=e) for e in all_account_emails]

    fake_mgr = MagicMock()
    fake_mgr.get_account.return_value = fake_active
    fake_mgr.get_all_accounts.return_value = fake_all

    return [
        patch("app.api.routes_contacts._resolve_account_id_for_user", return_value=account_id),
        patch("app.api.routes_contacts._resolve_account_id_cached", return_value=account_id),
        patch("app.api.routes_contacts._get_current_account_for_user", return_value=fake_active),
        patch("app.api.routes_contacts._get_blocked_senders_set", return_value=set()),
        patch("app.api.routes_helpers.get_db_session", fake_db_session),
        patch("app.db.database.get_db_session", fake_db_session),
        patch("app.api.routes_contacts._rh.get_db_session", fake_db_session),
        patch("app.multi_accounts.get_account_manager", return_value=fake_mgr),
    ]


def _enter(patches):
    """Enter a list of patch context managers, return their __exit__ list."""
    entered = []
    try:
        for p in patches:
            entered.append((p, p.__enter__()))
    except Exception:
        for p, _ in reversed(entered):
            p.__exit__(None, None, None)
        raise
    return entered


def _exit(entered):
    for p, _ in reversed(entered):
        p.__exit__(None, None, None)


# Test fixtures: a user with two accounts who has "Alexandre Simon" as
# their display name on the other account.
ACTIVE_EMAIL = "active@gmail.com"
OTHER_EMAIL = "alex.simon@hotmail.com"
ALL_ACCOUNT_EMAILS = [ACTIVE_EMAIL, OTHER_EMAIL]

SENDERS_MATCHING_ALEX = [
    SenderRow(sender=OTHER_EMAIL, sender_name="Alexandre Simon", freq=12),
]
RECIPIENTS_EMPTY: list[RecipRow] = []


class TestIncludeSelfDefault:
    """Default mode (no include_self param) preserves the prior behaviour:
    multi-account emails are stripped so compose recipient pickers don't
    auto-suggest self-emails."""

    def test_default_mode_strips_other_account_emails(self, client):
        patches = _patch_route_deps(
            SENDERS_MATCHING_ALEX,
            RECIPIENTS_EMPTY,
            active_email=ACTIVE_EMAIL,
            all_account_emails=ALL_ACCOUNT_EMAILS,
        )
        entered = _enter(patches)
        try:
            resp = client.get("/api/contacts/autocomplete?q=alex")
        finally:
            _exit(entered)

        assert resp.status_code == 200
        emails = [c["email"] for c in resp.get_json()]
        assert OTHER_EMAIL not in emails, (
            "default mode must strip multi-account emails — this is what "
            "broke search before the include_self fix"
        )


class TestIncludeSelfTrue:
    """include_self=true keeps multi-account emails, fixing the SmartSearchBar
    From/To/CC filter that returned 'Aucun résultat' on the user's own name."""

    def test_include_self_keeps_other_account_emails(self, client):
        patches = _patch_route_deps(
            SENDERS_MATCHING_ALEX,
            RECIPIENTS_EMPTY,
            active_email=ACTIVE_EMAIL,
            all_account_emails=ALL_ACCOUNT_EMAILS,
        )
        entered = _enter(patches)
        try:
            resp = client.get("/api/contacts/autocomplete?q=alex&include_self=true")
        finally:
            _exit(entered)

        assert resp.status_code == 200
        emails = [c["email"] for c in resp.get_json()]
        assert OTHER_EMAIL in emails, (
            "include_self=true must surface the user's own multi-account "
            "emails so search filters can find them"
        )

    def test_include_self_still_strips_active_account_email(self, client):
        # The active account's own_email is always stripped, even with
        # include_self=true — typing your active address into a filter is
        # never the intent, and chips already handle that path.
        senders = [
            SenderRow(sender=ACTIVE_EMAIL, sender_name="Me", freq=5),
            SenderRow(sender=OTHER_EMAIL, sender_name="Alexandre Simon", freq=12),
        ]
        patches = _patch_route_deps(
            senders,
            RECIPIENTS_EMPTY,
            active_email=ACTIVE_EMAIL,
            all_account_emails=ALL_ACCOUNT_EMAILS,
        )
        entered = _enter(patches)
        try:
            resp = client.get("/api/contacts/autocomplete?q=a&include_self=true")
        finally:
            _exit(entered)

        assert resp.status_code == 200
        emails = [c["email"] for c in resp.get_json()]
        assert ACTIVE_EMAIL not in emails, "active account email is always stripped"
        assert OTHER_EMAIL in emails, "other-account email kept when include_self=true"


class TestCacheKeyIsolation:
    """The backend caches by (account_id, query, sent_only, include_self,
    limit). Two requests with different include_self values must not
    alias the same cache entry — otherwise the second call would return
    the first call's stripped result."""

    def test_cache_key_includes_include_self(self, client):
        # Sequence: include_self=false then include_self=true on the same
        # query. If cache keys collided, the second call would return the
        # cached stripped result (no OTHER_EMAIL).
        patches = _patch_route_deps(
            SENDERS_MATCHING_ALEX,
            RECIPIENTS_EMPTY,
            active_email=ACTIVE_EMAIL,
            all_account_emails=ALL_ACCOUNT_EMAILS,
        )
        entered = _enter(patches)
        try:
            r_false = client.get("/api/contacts/autocomplete?q=alex")
            r_true = client.get("/api/contacts/autocomplete?q=alex&include_self=true")
        finally:
            _exit(entered)

        assert r_false.status_code == 200
        assert r_true.status_code == 200
        emails_false = [c["email"] for c in r_false.get_json()]
        emails_true = [c["email"] for c in r_true.get_json()]
        assert OTHER_EMAIL not in emails_false
        assert OTHER_EMAIL in emails_true, (
            "cache key must include include_self — otherwise the second "
            "call would alias the stripped result from the first call"
        )
