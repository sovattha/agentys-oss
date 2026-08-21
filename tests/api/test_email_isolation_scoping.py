# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Regression tests for cross-tenant email leaks (2026-04-24).

Before the fix, `_get_email_by_id` (app/api/routes_helpers.py) and its five
fallback layers (SQLite cache, bodyless cache, memory list cache, numeric-PK
resolver, direct SQLite-by-column) did NOT filter by `account_id`. If user A
and user B happened to share a provider `email_id` (Gmail hex, IMAP UID,
newsletter IDs, test IDs), user A could open user B's email — and worse,
user A's thread view would show user B's messages because
`conversation_id` was then used downstream to fetch threads.

These tests lock in the account-scoped behaviour at every layer:
  - `_get_email_from_cache(email_id, account_id)` — SQLite row must match account_id.
  - `_find_email_in_list_cache(email_id, account_key=...)` — cache iteration must filter on key[0].
  - `_get_email_from_memory_list_cache(email_id, account_key=...)` — same.
  - `_get_email_by_id(provider, email_id, account_id)` — end-to-end: user A cannot fetch user B's email via ANY fallback.

pytest tests/api/test_email_isolation_scoping.py -v
"""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, Account, Email
from app.db.repositories.email_repository import EmailRepository


# --------------------------------------------------------------------------- #
# Fixtures: isolated in-memory SQLite with two accounts + two emails that
# share the same provider email_id (the collision that triggers the leak).
# --------------------------------------------------------------------------- #

@pytest.fixture
def engine_two_tenants():
    """Fresh in-memory SQLite DB with foreign keys + tables."""
    engine = create_engine("sqlite:///:memory:", echo=False)

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys = ON")
        cur.close()

    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session_two_tenants(engine_two_tenants):
    SessionLocal = sessionmaker(bind=engine_two_tenants, autoflush=False)
    session = SessionLocal()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def two_tenants(session_two_tenants):
    """Seed two Agentys users (Alex + Nat) who each have an Email with the
    SAME provider email_id — the cross-tenant collision scenario. Returns
    (session, alex_account_id, sov_account_id, shared_email_id)."""
    alex = Account(email="alex@example.com", provider="gmail", display_name="Alex", is_active=True)
    nat = Account(email="nat@example.com", provider="gmail", display_name="Nat", is_active=True)
    session_two_tenants.add_all([alex, nat])
    session_two_tenants.commit()

    shared_eid = "deadbeef0123"
    alex_email = Email(
        email_id=shared_eid, thread_id="alex_thread", account_id=alex.id,
        subject="Alex private", sender="schahla@example.com", sender_name="Schahla",
        recipients="alex@example.com", date=datetime.utcnow(),
        body_text="Alex's PRIVATE body — must never leak to Nat.",
        snippet="Alex snippet", is_read=False,
    )
    sov_email = Email(
        email_id=shared_eid, thread_id="sov_thread", account_id=nat.id,
        subject="Nat confidential", sender="schahla@example.com", sender_name="Schahla",
        recipients="nat@example.com", date=datetime.utcnow(),
        body_text="Nat's CONFIDENTIAL body — must never leak to Alex.",
        snippet="Nat snippet", is_read=False,
    )
    session_two_tenants.add_all([alex_email, sov_email])
    session_two_tenants.commit()

    return session_two_tenants, alex.id, nat.id, shared_eid


# --------------------------------------------------------------------------- #
# Layer 1: EmailRepository.get_by_email_id must scope by account when asked.
# --------------------------------------------------------------------------- #

def test_repo_get_by_email_id_scopes_by_account(two_tenants):
    """Repository-level contract: when account_id is supplied, the query MUST
    filter by it even if email_id is globally unique. Without this, every
    higher-level cache that forwards email_id leaks across tenants."""
    session, alex_id, sov_id, shared_eid = two_tenants
    repo = EmailRepository(session)

    alex_row = repo.get_by_email_id(shared_eid, account_id=alex_id)
    sov_row = repo.get_by_email_id(shared_eid, account_id=sov_id)

    assert alex_row is not None
    assert sov_row is not None
    assert alex_row.id != sov_row.id
    assert alex_row.account_id == alex_id
    assert sov_row.account_id == sov_id
    assert "PRIVATE" in alex_row.body_text
    assert "CONFIDENTIAL" in sov_row.body_text


def test_repo_get_by_email_id_wrong_account_returns_none(two_tenants):
    """If Alex queries with Nat's account_id (unlikely but defensive),
    the row returned must belong to THAT account, not Alex's — proves the
    WHERE clause is actually applied."""
    session, alex_id, sov_id, shared_eid = two_tenants
    repo = EmailRepository(session)

    # Simulate a malicious / buggy caller passing a sentinel that matches nothing
    miss = repo.get_by_email_id(shared_eid, account_id=-1)
    assert miss is None, "Sentinel account_id=-1 must return None, not any row"


def test_repo_get_emails_missing_snippet_scopes_by_account(two_tenants):
    """Body/snippet backfill must not select another account's colliding UID."""
    session, alex_id, sov_id, _shared_eid = two_tenants
    repo = EmailRepository(session)
    colliding_id = "missing-body-uid"
    session.add_all([
        Email(
            email_id=colliding_id, thread_id="alex_missing", account_id=alex_id,
            subject="Alex missing body", sender="sender@example.com",
            recipients="alex@example.com", date=datetime.utcnow(),
            body_text=None, body_html=None, snippet=None, is_read=False,
        ),
        Email(
            email_id=colliding_id, thread_id="sov_missing", account_id=sov_id,
            subject="Nat missing body", sender="sender@example.com",
            recipients="nat@example.com", date=datetime.utcnow(),
            body_text=None, body_html=None, snippet=None, is_read=False,
        ),
    ])
    session.commit()

    alex_rows = repo.get_emails_missing_snippet([colliding_id], account_id=alex_id)
    sov_rows = repo.get_emails_missing_snippet([colliding_id], account_id=sov_id)
    miss_rows = repo.get_emails_missing_snippet([colliding_id], account_id=-1)

    assert [row.account_id for row in alex_rows] == [alex_id]
    assert [row.account_id for row in sov_rows] == [sov_id]
    assert miss_rows == []


# --------------------------------------------------------------------------- #
# Layer 2: _get_email_from_cache scopes SQLite lookup to the account.
# --------------------------------------------------------------------------- #

def test_get_email_from_cache_is_account_scoped(two_tenants, monkeypatch):
    """_get_email_from_cache MUST pass account_id to the repository so two
    tenants sharing an email_id see only their own row."""
    session, alex_id, sov_id, shared_eid = two_tenants

    # Patch get_db_session to yield our in-memory test session
    from contextlib import contextmanager
    @contextmanager
    def _fake_session():
        yield session

    from app.api import routes_helpers
    monkeypatch.setattr(routes_helpers, "get_db_session", _fake_session)

    alex_hit = routes_helpers._get_email_from_cache(shared_eid, account_id=alex_id)
    sov_hit = routes_helpers._get_email_from_cache(shared_eid, account_id=sov_id)

    assert alex_hit is not None
    assert sov_hit is not None
    assert "PRIVATE" in alex_hit.body
    assert "CONFIDENTIAL" in sov_hit.body
    # Crucially: neither body leaks into the other tenant's result
    assert "CONFIDENTIAL" not in alex_hit.body
    assert "PRIVATE" not in sov_hit.body


def test_get_email_from_cache_sentinel_returns_none(two_tenants, monkeypatch):
    """An unresolved JWT user (sentinel -1) must NEVER see any row —
    this is the default when account_id resolution fails."""
    session, _alex_id, _sov_id, shared_eid = two_tenants

    from contextlib import contextmanager
    @contextmanager
    def _fake_session():
        yield session

    from app.api import routes_helpers
    monkeypatch.setattr(routes_helpers, "get_db_session", _fake_session)

    result = routes_helpers._get_email_from_cache(
        shared_eid, account_id=routes_helpers._NO_ACCOUNT_SENTINEL
    )
    assert result is None, "Sentinel account must never hit any tenant's row"


# --------------------------------------------------------------------------- #
# Layer 3: _find_email_in_list_cache filters by account_key.
# --------------------------------------------------------------------------- #

def test_find_email_in_list_cache_filters_by_account_key(monkeypatch):
    """In-memory list cache is keyed by (account, folder, filter). Without
    filtering, user A's detail lookup would return user B's cached email."""
    from app.api import routes_helpers

    # Populate cache with two entries that share an email_id under different accounts
    cache: OrderedDict = OrderedDict()
    cache[("alex_acct", "inbox", "all")] = {
        "timestamp": 9e12,
        "data": {"emails": [{"id": "collide123", "subject": "Alex private", "body_preview": "Alex"}]},
    }
    cache[("sov_acct", "inbox", "all")] = {
        "timestamp": 9e12,
        "data": {"emails": [{"id": "collide123", "subject": "Nat confidential", "body_preview": "Nat"}]},
    }
    monkeypatch.setattr(routes_helpers, "_email_cache", cache)

    alex_hit = routes_helpers._find_email_in_list_cache("collide123", account_key="alex_acct")
    sov_hit = routes_helpers._find_email_in_list_cache("collide123", account_key="sov_acct")
    foreign_hit = routes_helpers._find_email_in_list_cache("collide123", account_key="nonexistent")

    assert alex_hit is not None and alex_hit["subject"] == "Alex private"
    assert sov_hit is not None and sov_hit["subject"] == "Nat confidential"
    assert foreign_hit is None, "Unknown account_key must not return any cached email"


def test_find_email_in_list_cache_legacy_none_key_is_unfiltered(monkeypatch):
    """account_key=None preserves legacy behaviour for non-user-facing callers
    (internal sync/background jobs). Verified so we don't silently break them."""
    from app.api import routes_helpers

    cache: OrderedDict = OrderedDict()
    cache[("any_acct", "inbox", "all")] = {
        "timestamp": 9e12,
        "data": {"emails": [{"id": "legacy999", "subject": "Legacy"}]},
    }
    monkeypatch.setattr(routes_helpers, "_email_cache", cache)

    # Explicit None = legacy; returns whatever matches the email_id
    legacy_hit = routes_helpers._find_email_in_list_cache("legacy999", account_key=None)
    assert legacy_hit is not None


# --------------------------------------------------------------------------- #
# Layer 4: _get_email_from_memory_list_cache filters by account_key.
# --------------------------------------------------------------------------- #

def test_memory_list_cache_filters_by_account_key(monkeypatch):
    """The deepest fallback (used when SQLite and IMAP both miss) must also
    filter by account_key — otherwise Alex's /process call could pick up
    Nat's email from the memory cache."""
    from app.api import routes_helpers

    cache: OrderedDict = OrderedDict()
    cache[("alex_acct", "inbox", "all")] = {
        "timestamp": 9e12,
        "data": {"emails": [{
            "id": "leak42", "sender": "a@x.com", "subject": "Alex", "body_preview": "Alex body",
            "conversation_id": "conv_alex",
        }]},
    }
    cache[("sov_acct", "inbox", "all")] = {
        "timestamp": 9e12,
        "data": {"emails": [{
            "id": "leak42", "sender": "b@x.com", "subject": "Nat", "body_preview": "Nat body",
            "conversation_id": "conv_sov",
        }]},
    }
    monkeypatch.setattr(routes_helpers, "_email_cache", cache)
    monkeypatch.setattr(routes_helpers, "_email_detail_cache", OrderedDict())

    alex_email = routes_helpers._get_email_from_memory_list_cache("leak42", account_key="alex_acct")
    sov_email = routes_helpers._get_email_from_memory_list_cache("leak42", account_key="sov_acct")

    assert alex_email is not None
    assert sov_email is not None
    assert alex_email.subject == "Alex"
    assert sov_email.subject == "Nat"
    # The critical assertion: conversation_id must not leak (it's what drives
    # the downstream thread fetch — the original symptom in the user's screenshot)
    assert alex_email.conversation_id == "conv_alex"
    assert sov_email.conversation_id == "conv_sov"


def test_memory_detail_cache_skips_legacy_bare_keys_when_scoped(monkeypatch):
    """The detail cache (_email_detail_cache) has historically used both
    (account_id, email_id) tuples AND bare string email_id keys. When
    account_key is enforced, bare-string legacy keys must be SKIPPED — they
    carry no tenant tag and could belong to any user."""
    from app.api import routes_helpers

    detail: OrderedDict = OrderedDict()
    # Legacy bare-string key (cross-tenant-unsafe)
    detail["legacykey"] = {"timestamp": 9e12, "data": {"sender": "anyone@x.com", "subject": "Legacy"}}
    # Scoped tuple key for a different tenant
    detail[("sov_acct", "legacykey")] = {"timestamp": 9e12, "data": {"sender": "nat@x.com", "subject": "Nat"}}

    monkeypatch.setattr(routes_helpers, "_email_cache", OrderedDict())
    monkeypatch.setattr(routes_helpers, "_email_detail_cache", detail)

    # Alex asks for the email. Legacy bare key MUST be ignored (no tenant proof).
    # Nat's tuple-keyed entry MUST be ignored (wrong tenant).
    result = routes_helpers._get_email_from_memory_list_cache("legacykey", account_key="alex_acct")
    assert result is None, (
        "Alex must not see any entry: the bare-string key is cross-tenant-unsafe "
        "and the tuple-keyed entry belongs to Nat"
    )


# --------------------------------------------------------------------------- #
# Layer 5: end-to-end — _get_email_by_id with an authenticated provider that
# returns nothing MUST NOT fall through to another tenant's cache.
# --------------------------------------------------------------------------- #

def test_get_email_by_id_cross_tenant_leak_is_blocked(two_tenants, monkeypatch):
    """The reproducer of the reported bug.

    Setup: shared_eid exists for both Alex and Nat in SQLite. Alex's provider
    doesn't have it (Alex never received the message — it belongs to Nat in
    this scenario). Before the fix, Alex's `/process` request would resolve
    the SQLite row for Nat's email via the unscoped fallback chain and leak
    Nat's body, conversation_id, and ultimately the full thread.
    """
    session, alex_id, _sov_id, shared_eid = two_tenants

    from contextlib import contextmanager
    @contextmanager
    def _fake_session():
        yield session

    from app.api import routes_helpers
    monkeypatch.setattr(routes_helpers, "get_db_session", _fake_session)
    monkeypatch.setattr(routes_helpers, "_email_cache", OrderedDict())
    monkeypatch.setattr(routes_helpers, "_email_detail_cache", OrderedDict())
    # Bypass _get_current_account_for_user (pulls in Flask.g); return None so
    # account_key falls back to str(account_id) derived from the explicit arg.
    monkeypatch.setattr(routes_helpers, "_get_current_account_for_user", lambda: None)

    # Alex's provider — authenticated to Alex's mailbox only. Nat's email is
    # not in it, so get_message_by_id returns None.
    alex_provider = MagicMock()
    alex_provider.get_message_by_id.return_value = None

    # Under the old code, this would return SOME row for shared_eid
    # (whichever happened to be first in SQLite). Under the fix, Alex's
    # account_id scopes every fallback to Alex's row only.
    result = routes_helpers._get_email_by_id(alex_provider, shared_eid, account_id=alex_id)

    # Alex's row DOES exist — he has his own copy of the shared email_id —
    # so the request should resolve to Alex's row, never Nat's.
    assert result is not None
    assert "PRIVATE" in (result.body or ""), "Alex must see Alex's body"
    assert "CONFIDENTIAL" not in (result.body or ""), (
        "Alex must NEVER see Nat's body even though they share email_id"
    )


@pytest.fixture
def app_ctx():
    """Flask app context — required when exercising code paths that use
    `abort(404)` + `jsonify` (404 emits a JSON response via current_app)."""
    from flask import Flask
    _app = Flask(__name__)
    with _app.app_context():
        yield _app


def test_get_email_by_id_sentinel_account_hits_only_provider(two_tenants, monkeypatch, app_ctx):
    """When account resolution fails (no JWT, no singleton), every SQLite
    fallback MUST return empty — the only way to fetch an email is through
    the authenticated provider (which is already scoped to a mailbox)."""
    session, _alex_id, _sov_id, shared_eid = two_tenants

    from contextlib import contextmanager
    @contextmanager
    def _fake_session():
        yield session

    from app.api import routes_helpers
    monkeypatch.setattr(routes_helpers, "get_db_session", _fake_session)
    monkeypatch.setattr(routes_helpers, "_email_cache", OrderedDict())
    monkeypatch.setattr(routes_helpers, "_email_detail_cache", OrderedDict())
    monkeypatch.setattr(routes_helpers, "_get_current_account_for_user", lambda: None)

    # Patch get_db_session in app.db.database too — the 5th fallback
    # re-imports it locally.
    from app.db import database as _db_mod
    monkeypatch.setattr(_db_mod, "get_db_session", _fake_session)

    provider = MagicMock()
    provider.get_message_by_id.return_value = None  # Provider has nothing

    # abort(404) is raised as HTTPException when every layer misses
    from werkzeug.exceptions import HTTPException
    with pytest.raises(HTTPException) as excinfo:
        routes_helpers._get_email_by_id(
            provider, shared_eid,
            account_id=routes_helpers._NO_ACCOUNT_SENTINEL,
        )
    status = excinfo.value.code or (getattr(excinfo.value.response, "status_code", None))
    assert status == 404, (
        f"Unauthenticated lookup with missing provider data must 404 — "
        f"got {status}; never silently return another tenant's email"
    )


def test_numeric_pk_resolver_scopes_by_account(two_tenants, monkeypatch, app_ctx):
    """The BUG-003 numeric-PK resolver (if a caller sends the DB integer id
    instead of the hash email_id) must also filter by account. Without the
    filter, Alex sending Nat's DB id as a number would resolve to Nat's hash
    email_id and then leak Nat's email further down the pipeline."""
    session, alex_id, sov_id, _shared_eid = two_tenants

    # Find Nat's integer PK — Alex must NOT be able to resolve it via a
    # numeric lookup even though PKs are globally unique.
    sov_row = session.query(Email).filter(Email.account_id == sov_id).one()
    sov_pk = str(sov_row.id)

    from contextlib import contextmanager
    @contextmanager
    def _fake_session():
        yield session

    from app.api import routes_helpers
    monkeypatch.setattr(routes_helpers, "get_db_session", _fake_session)
    monkeypatch.setattr(routes_helpers, "_email_cache", OrderedDict())
    monkeypatch.setattr(routes_helpers, "_email_detail_cache", OrderedDict())
    monkeypatch.setattr(routes_helpers, "_get_current_account_for_user", lambda: None)
    from app.db import database as _db_mod
    monkeypatch.setattr(_db_mod, "get_db_session", _fake_session)

    alex_provider = MagicMock()
    alex_provider.get_message_by_id.return_value = None

    from werkzeug.exceptions import HTTPException
    with pytest.raises(HTTPException) as excinfo:
        routes_helpers._get_email_by_id(alex_provider, sov_pk, account_id=alex_id)
    status = excinfo.value.code or (getattr(excinfo.value.response, "status_code", None))
    assert status == 404, (
        f"Alex attempting to fetch Nat's row by numeric DB PK must 404 — "
        f"got {status}; account_id filter on the resolver prevents hash leak"
    )
