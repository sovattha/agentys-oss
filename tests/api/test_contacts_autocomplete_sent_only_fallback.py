# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""`sent_only=true` soft-fallback + hash account_id acceptance on /api/contacts/autocomplete.

Regression for the 2026-05-12 bug : typing "a" in the compose To field
returned "No contact found" despite the user having months of inbox/sent
history. Two distinct causes were live concurrently :

  1. `routes_contacts.py:112` read `account_id` with `type=int`, silently
     coercing the hash format the frontend sends (e.g. "458130f56b9bb6f0")
     to ``None``. The request then fell through to JWT-resolved account_id
     which, in multi-account setups, may not be the UI-active account →
     contacts came from the wrong account.
  2. The `sent_only=true` filter the compose modal hard-wires on dropped
     EVERY contact whose `is_sent` flag wasn't set. Combined with the
     documented Gmail historyId SENT-folder gap (tasks/lessons.md → Sync),
     this manifested as a fully-empty dropdown even when the matching
     contact existed in the user's inbox.

This file locks in both fixes :

  - ``test_hash_account_id_resolves_via_require_owned_account_id`` — sending
    a hash as ``account_id`` is now resolved by the same helper used by the
    rest of the auth surface, not silently dropped.
  - ``test_sent_only_falls_back_when_no_sent_recipients`` — when the
    sent-only filter would empty the dropdown, the route returns the
    unfiltered sender+recipient set instead of ``[]``.
  - ``test_sent_only_still_strict_when_sent_data_exists`` — guard against
    over-loosening : if sent data IS present, the strict filter still
    applies. Only the empty-dropdown case triggers the fallback.
"""
from __future__ import annotations

from collections import namedtuple
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest


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
    """Dispatch on column count (senders=3 cols, recipients=2 cols) so the
    same mock session can serve both queries the route makes.
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


@pytest.fixture(autouse=True)
def _clear_contacts_cache():
    """The route caches by (account_id, q, sent_only, include_self, limit)
    for 60s — without clearing, tests sharing a cache key see each other's
    results. Clear before AND after to defend against ordering surprises.
    """
    from app.api import routes_contacts as _rc
    _rc._contacts_cache.clear()
    yield
    _rc._contacts_cache.clear()


def _patch_route_deps(senders, recipients, *, active_email, all_account_emails, account_id=1):
    """Patches that let the autocomplete handler run without a real DB / JWT.

    Note : we intentionally do NOT patch ``require_owned_account_id`` here.
    Tests that exercise the explicit-account-id branch must set their own
    patch (otherwise patches stack and the per-test mock's call count is
    swallowed by this default). Tests that don't send ``account_id`` take
    the JWT-fallback path (``_resolve_account_id_for_user`` here), which
    IS patched.
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


# ---------------------------------------------------------------------------
# Fixtures : a user with both inbox senders (no SENT-folder data) and
# sometimes recipients. The "alice" name is searched against to match a
# realistic typing-one-letter scenario.
# ---------------------------------------------------------------------------

ACTIVE_EMAIL = "active@gmail.com"
ALL_ACCOUNT_EMAILS = [ACTIVE_EMAIL]

# Use a non-noise domain (example.com is in _NOISE_DOMAINS as an explicit
# anti-spam filter entry, so it'd get silently dropped — wrong for fixtures).
SENDERS_MATCHING_A = [
    SenderRow(sender="alice@acme.test",  sender_name="Alice Anderson", freq=8),
    SenderRow(sender="bob@acme.test",    sender_name="Bob",            freq=2),
]
RECIPIENTS_EMPTY: list[RecipRow] = []
RECIPIENTS_WITH_ALICE = [RecipRow(recipients="alice@acme.test", freq=5)]


# ---------------------------------------------------------------------------
# Test 1 — sent_only fallback to senders when no sent recipients match
# ---------------------------------------------------------------------------

class TestSentOnlyFallback:
    """Regression for the "No contact found" symptom in compose.

    Pre-fix : sent_only=true + zero matching sent recipients → ``[]``.
    Post-fix : the route falls back to the unfiltered sender+recipient set
    (still subject to noreply / noise / blocked-senders suppression).
    """

    def test_sent_only_falls_back_when_no_sent_recipients(self, client):
        patches = _patch_route_deps(
            SENDERS_MATCHING_A,
            RECIPIENTS_EMPTY,  # ← no sent emails for this account
            active_email=ACTIVE_EMAIL,
            all_account_emails=ALL_ACCOUNT_EMAILS,
        )
        entered = _enter(patches)
        try:
            resp = client.get("/api/contacts/autocomplete?q=a&sent_only=true")
        finally:
            _exit(entered)

        assert resp.status_code == 200
        results = resp.get_json()
        emails = [c["email"] for c in results]
        assert "alice@acme.test" in emails, (
            "sent_only=true with zero sent recipients should fall back to "
            "the unfiltered senders+recipients set, not return [] silently — "
            "that's what caused the 'No contact found' UX bug fixed 2026-05-12"
        )

    def test_sent_only_still_strict_when_sent_data_exists(self, client):
        """When sent recipients DO match, the fallback must NOT activate :
        the strict sent-only filter still hides the senders. Pure recipients
        only.
        """
        patches = _patch_route_deps(
            SENDERS_MATCHING_A,
            RECIPIENTS_WITH_ALICE,  # ← sent data is present
            active_email=ACTIVE_EMAIL,
            all_account_emails=ALL_ACCOUNT_EMAILS,
        )
        entered = _enter(patches)
        try:
            resp = client.get("/api/contacts/autocomplete?q=a&sent_only=true")
        finally:
            _exit(entered)

        assert resp.status_code == 200
        results = resp.get_json()
        # alice should appear (she's a sent recipient)
        emails = [c["email"] for c in results]
        assert "alice@acme.test" in emails
        # bob is only a sender, not a recipient — must be filtered out by
        # the strict sent_only when sent data is present.
        assert "bob@acme.test" not in emails, (
            "When sent recipients exist, strict sent_only mode must hide "
            "pure-senders. Otherwise the fallback is too eager and spam-"
            "vulnerable."
        )


# ---------------------------------------------------------------------------
# Test 2 — hash account_id is accepted (not silently coerced to None)
# ---------------------------------------------------------------------------

class TestHashAccountId:
    """Regression for the hash-vs-int dual-format bug.

    Pre-fix : ``request.args.get("account_id", type=int)`` returned ``None``
    for a hash like "458130f56b9bb6f0", so the explicit-account branch was
    skipped and JWT picked the account. In multi-account setups where JWT
    resolves to a DIFFERENT account than the UI shows, contacts came back
    empty without explanation.

    Post-fix : the route uses ``require_owned_account_id`` which handles
    both int and hash uniformly.
    """

    def test_hash_account_id_resolves_via_require_owned_account_id(self, client):
        """Hash account_id triggers require_owned_account_id (not the silently
        coerced ``type=int`` of pre-fix code). _patch_route_deps does NOT
        include this mock so this test owns it exclusively."""
        with patch(
            "app.api.routes_contacts.require_owned_account_id",
            return_value=42,
        ) as mock_resolver:
            patches = _patch_route_deps(
                SENDERS_MATCHING_A,
                RECIPIENTS_EMPTY,
                active_email=ACTIVE_EMAIL,
                all_account_emails=ALL_ACCOUNT_EMAILS,
                account_id=42,
            )
            entered = _enter(patches)
            try:
                resp = client.get(
                    "/api/contacts/autocomplete?q=a&sent_only=true"
                    "&account_id=458130f56b9bb6f0"
                )
            finally:
                _exit(entered)

            assert resp.status_code == 200
            mock_resolver.assert_called_once()
            # Confirm the hash was passed through to the resolver verbatim,
            # not silently dropped or coerced to None.
            assert mock_resolver.call_args.args[0] == "458130f56b9bb6f0", (
                "require_owned_account_id must receive the hash literal so it "
                "can do the hash→AccountConfig.email→DB int resolution"
            )

    def test_unowned_account_id_returns_403(self, client):
        """When require_owned_account_id returns the -1 sentinel, the route
        must respond 403 — not silently fall through to JWT resolution.
        """
        from app.api.routes_helpers import _NO_ACCOUNT_SENTINEL

        with patch(
            "app.api.routes_contacts.require_owned_account_id",
            return_value=_NO_ACCOUNT_SENTINEL,
        ):
            patches = _patch_route_deps(
                SENDERS_MATCHING_A,
                RECIPIENTS_EMPTY,
                active_email=ACTIVE_EMAIL,
                all_account_emails=ALL_ACCOUNT_EMAILS,
            )
            entered = _enter(patches)
            try:
                resp = client.get(
                    "/api/contacts/autocomplete?q=a&account_id=deadbeefdeadbeef"
                )
            finally:
                _exit(entered)

            assert resp.status_code == 403
            assert "owned account" in resp.get_json().get("error", "").lower()
