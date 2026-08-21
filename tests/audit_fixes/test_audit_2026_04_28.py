# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Regression tests for the 2026-04-28 audit fix batch.

Covers:
- P0-001 mobile API ignores client-supplied user_id and uses JWT identity
- P0-002 /api/sync/{status,history} filter to JWT-owned account_ids
- P1-005 require_owned_account_id rejects bogus X-Account-Id values
- P1-007 WebSocket connect rejects JWT in URL query string
- P1-008 PendingDraftStore filters do not leak account_id=None drafts
- P1-014 WebSocket connect rejects account_id not owned by JWT user

Each test fails if the corresponding fix is reverted.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("flask_cors")


@pytest.fixture
def app():
    from app.api.app import create_app
    app = create_app(config={"TESTING": True})
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def _stub_jwt(user_id: int, email: str):
    """Make `_decode_jwt` return a fake payload for any token."""
    return patch(
        "app.api.auth._decode_jwt",
        return_value={"sub": user_id, "email": email},
    )


# =============================================================================
# P0-001 — Mobile API trusts only JWT-derived user_id
# =============================================================================


def test_p0_001_mobile_drafts_ignores_client_user_id(app, client):
    """Mobile /drafts endpoint must NOT honour ?user_id=victim — only JWT."""
    from app.api import mobile as mobile_module

    captured = {}

    class _StubService:
        def get_pending_drafts(self, user_id, limit):
            captured["user_id"] = user_id
            return []

        def get_draft(self, draft_id, user_id):
            captured["user_id"] = user_id
            return None

    with _stub_jwt(1, "alice@example.com"), \
         patch.object(mobile_module, "get_service", return_value=_StubService()):
        resp = client.get(
            "/api/mobile/drafts?user_id=victim@evil.com",
            headers={"Authorization": "Bearer any"},
            environ_base={"REMOTE_ADDR": "203.0.113.10"},
        )

    assert resp.status_code == 200
    assert captured["user_id"] == "alice@example.com", (
        f"P0-001 leak: store called with {captured} — should be alice's email "
        "regardless of ?user_id query."
    )


def test_p0_001_mobile_drafts_no_jwt_returns_401(app, client):
    """Without auth, /drafts must 401 (no fallback to client user_id)."""
    resp = client.get(
        "/api/mobile/drafts?user_id=anyone@example.com",
        environ_base={"REMOTE_ADDR": "203.0.113.10"},
    )
    assert resp.status_code in (401, 403)


def test_p0_001_mobile_store_filters_get_pending_by_user_id(tmp_path):
    """The infrastructure store now filters get_pending_drafts by user_id
    when the draft carries an owner. ``MobileDraft`` does not currently
    define ``user_id`` at class level; ownership is attached at runtime
    by callers that have multi-tenant data. We simulate that here."""
    from app.infrastructure.mobile_companion_store import JsonFileMobileSyncStore
    from app.domain.entities.mobile_companion import MobileDraft, MobileDraftAction

    store = JsonFileMobileSyncStore(filepath=tmp_path / "sync.json")

    d_alice = MobileDraft(
        draft_id="d1",
        subject="s",
        recipient="x@x.com",
        body_full="hi",
        action=MobileDraftAction.PENDING,
    )
    d_bob = MobileDraft(
        draft_id="d2",
        subject="s",
        recipient="y@y.com",
        body_full="hi",
        action=MobileDraftAction.PENDING,
    )
    # Attach owner attribute (simulates a future migration that adds user_id
    # to the entity, or a caller that wraps drafts with owner metadata).
    d_alice.user_id = "alice@example.com"
    d_bob.user_id = "bob@example.com"
    store._drafts[d_alice.draft_id] = d_alice
    store._drafts[d_bob.draft_id] = d_bob

    alice_pending = store.get_pending_drafts("alice@example.com")
    bob_pending = store.get_pending_drafts("bob@example.com")

    assert {d.draft_id for d in alice_pending} == {"d1"}
    assert {d.draft_id for d in bob_pending} == {"d2"}

    assert store.get_draft("d2", "alice@example.com") is None
    assert store.get_draft("d2", "bob@example.com") is not None


# =============================================================================
# P0-002 — /api/sync/* filtered to JWT-owned account_ids
# =============================================================================


def test_p0_002_sync_history_filters_to_owned_accounts(app, client):
    """SyncStatus.last_results is global; /history must filter to JWT owner."""
    from dataclasses import dataclass
    from app.api import sync as sync_module

    @dataclass
    class _R:
        account_id: int
        account_email: str
        success: bool
        new_emails_count: int
        error_message: str | None
        duration_ms: int

    class _Status:
        last_results = [
            _R(1, "alice@example.com", True, 5, None, 100),
            _R(2, "bob@example.com", True, 3, None, 200),
            _R(3, "victim@example.com", False, 0, "auth", 50),
        ]
        last_sync_at = None

    class _SyncService:
        status = _Status()
        def get_reauth_required_accounts(self):
            return [2, 3]  # bob + victim

    with _stub_jwt(1, "alice@example.com"), \
         patch.object(sync_module, "get_sync_service", return_value=_SyncService()), \
         patch.object(sync_module, "_owned_account_ids_for_caller", return_value={1}):
        resp = client.get(
            "/api/sync/history",
            headers={"Authorization": "Bearer any"},
            environ_base={"REMOTE_ADDR": "203.0.113.10"},
        )

    assert resp.status_code == 200
    body = resp.get_json()
    aids = {h["account_id"] for h in body["history"]}
    assert aids == {1}, f"P0-002 leak: history returned {aids}, expected only 1"


def test_p0_002_sync_status_filters_reauth_to_owned(app, client):
    """reauth_required_account_ids must only contain accounts owned by JWT."""
    from app.api import sync as sync_module

    class _Status:
        last_results = []
        last_sync_at = None
        next_sync_at = None
        sync_interval_seconds = 60
        is_running = True
        is_syncing = False

    class _SyncService:
        status = _Status()
        def get_reauth_required_accounts(self):
            return [1, 99, 100]

    with _stub_jwt(1, "alice@example.com"), \
         patch.object(sync_module, "get_sync_service", return_value=_SyncService()), \
         patch.object(sync_module, "_owned_account_ids_for_caller", return_value={1}):
        resp = client.get(
            "/api/sync/status",
            headers={"Authorization": "Bearer any"},
            environ_base={"REMOTE_ADDR": "203.0.113.10"},
        )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"]["reauth_required_account_ids"] == [1]


# =============================================================================
# P1-005 — require_owned_account_id rejects bogus header values
# =============================================================================


def test_p1_005_require_owned_account_id_rejects_unowned(app):
    """An X-Account-Id mapping to an account NOT owned by the JWT user must
    return _NO_ACCOUNT_SENTINEL (-1), not silently fall back to the
    caller's current account.

    Also covers the hash-form input path: AccountManager.tsx (frontend)
    sets X-Account-Id from listAccounts(), which returns hash IDs
    (e.g. "458130f56b9bb6f0") rather than DB ints. The validator must
    resolve the hash via AccountManager → email → DB int, then apply
    the same ownership check. An unowned hash still 404s."""
    from app.api.routes_helpers import require_owned_account_id, _NO_ACCOUNT_SENTINEL

    class _Acc:
        def __init__(self, _id, email):
            self.id = _id
            self.email = email

    class _Repo:
        def __init__(self, *_a, **_k): pass
        def get_active_accounts_for_user(self, uid):
            # Simulate JWT user_id linked to a different account (id=9)
            # than the one that matches by email (id=7). This exposes the
            # data-state edge case where multi_accounts.json has user_id=None
            # or a stale value, but the email is the JWT user's own.
            if uid == 1:
                return [_Acc(9, "stale-link@example.com")]
            return []
        def get_by_email(self, email):
            mapping = {
                "alice@example.com": _Acc(7, "alice@example.com"),
                "eve@evil.com": _Acc(42, "eve@evil.com"),
            }
            return mapping.get(email)

    class _SessionCtx:
        def __enter__(self_inner): return MagicMock()
        def __exit__(self_inner, *a): return False

    class _AcctConfig:
        def __init__(self, email): self.email = email

    class _Manager:
        def get_account(self, h):
            return {
                "OWNED_HASH": _AcctConfig("alice@example.com"),
                "FOREIGN_HASH": _AcctConfig("eve@evil.com"),
            }.get(h)

    with app.test_request_context("/api/health"), \
         patch("app.db.repositories.account_repository.AccountRepository", _Repo), \
         patch("app.db.database.get_db_session", return_value=_SessionCtx()), \
         patch("app.multi_accounts.get_account_manager", return_value=_Manager()):
        from flask import g
        g.auth_user = {"id": 1, "email": "alice@example.com"}

        # --- int form ---
        # Email-matched account (id=7): allowed even though user_id resolves
        # to id=9 (stale linkage). Email uniqueness makes this safe.
        assert require_owned_account_id("7") == 7
        # user_id-linked account (id=9): also allowed
        assert require_owned_account_id("9") == 9
        # Foreign int: sentinel
        assert require_owned_account_id("99") == _NO_ACCOUNT_SENTINEL
        # --- non-int form ---
        # Bogus / non-resolvable string: sentinel
        assert require_owned_account_id("DEADBEEF") == _NO_ACCOUNT_SENTINEL
        # Hash → email-matched account (frontend listAccounts() path,
        # legitimate access via own email even if user_id is stale)
        assert require_owned_account_id("OWNED_HASH") == 7
        # Hash → foreign account (different email): sentinel
        assert require_owned_account_id("FOREIGN_HASH") == _NO_ACCOUNT_SENTINEL


def test_p1_005_email_match_blocked_when_account_belongs_to_other_user(app):
    """Regression for audit 41f5affe: the email-match path in
    require_owned_account_id must NOT add an account to `owned` when that
    account's user_id is set to a different user.

    Scenario: JWT user_id=1 (alice), but the DB account with alice's email
    has user_id=2 (bob). This would happen if account ownership was
    re-assigned (rare but possible). The fix gates the email-match behind
    `_acc_uid is None OR _acc_uid == jwt_user_id`."""
    from app.api.routes_helpers import require_owned_account_id, _NO_ACCOUNT_SENTINEL

    class _Acc:
        def __init__(self, _id, email, user_id=None):
            self.id = _id
            self.email = email
            self.user_id = user_id

    class _Repo:
        def __init__(self, *_a, **_k): pass
        def get_active_accounts_for_user(self, uid):
            return []  # JWT user_id=1 owns nothing via user_id linkage
        def get_by_email(self, email):
            if email == "alice@example.com":
                # Account exists for alice's email but is owned by user_id=2
                return _Acc(7, "alice@example.com", user_id=2)
            return None

    class _SessionCtx:
        def __enter__(self_inner): return MagicMock()
        def __exit__(self_inner, *a): return False

    with app.test_request_context("/api/health"), \
         patch("app.db.repositories.account_repository.AccountRepository", _Repo), \
         patch("app.db.database.get_db_session", return_value=_SessionCtx()), \
         patch("app.multi_accounts.get_account_manager", return_value=MagicMock()):
        from flask import g
        g.auth_user = {"id": 1, "email": "alice@example.com"}

        # Account id=7 has alice's email but user_id=2 — must not be granted
        assert require_owned_account_id("7") == _NO_ACCOUNT_SENTINEL


# =============================================================================
# require_owned_account_id — loopback dev relaxation gated on env
# =============================================================================


def test_require_owned_account_id_loopback_dev_relaxation(app):
    """In dev/local mode (loopback request, non-production env), the
    validator must trust the X-Account-Id header even when a JWT is
    present, because dev-login mints arbitrary JWTs from any email on
    loopback so a strict ownership check produces false 404s on the
    user's own inbox after a dev identity switch. Production cloud
    requests (non-loopback OR `_is_production_env=True`) must keep
    the strict P1-005 ownership check."""
    from app.api.routes_helpers import require_owned_account_id, _NO_ACCOUNT_SENTINEL

    class _Acc:
        def __init__(self, _id, email, user_id=None):
            self.id = _id
            self.email = email
            self.user_id = user_id

    class _Repo:
        def __init__(self, *_a, **_k): pass
        def get_active_accounts_for_user(self, uid):
            return []  # JWT user owns nothing per user_id linkage
        def get_by_email(self, email):
            return _Acc(7, "alice@example.com", user_id=1) if email == "alice@example.com" else None

    class _SessionCtx:
        def __enter__(self_inner): return MagicMock()
        def __exit__(self_inner, *a): return False

    # Loopback (127.0.0.1) + non-production env → relaxation kicks in
    with app.test_request_context("/api/health",
                                  environ_overrides={"REMOTE_ADDR": "127.0.0.1"}), \
         patch("app.db.repositories.account_repository.AccountRepository", _Repo), \
         patch("app.db.database.get_db_session", return_value=_SessionCtx()), \
         patch("app.api.auth._is_production_env", False):
        from flask import g
        # JWT identifies a foreign user (e.g. stale dev-login in localStorage)
        g.auth_user = {"id": 999, "email": "stranger@example.com"}
        # Accessing some int → trusted in loopback dev (relaxed)
        assert require_owned_account_id("42") == 42

    # Non-loopback (8.8.8.8) → strict ownership preserved
    with app.test_request_context("/api/health",
                                  environ_overrides={"REMOTE_ADDR": "8.8.8.8"}), \
         patch("app.db.repositories.account_repository.AccountRepository", _Repo), \
         patch("app.db.database.get_db_session", return_value=_SessionCtx()), \
         patch("app.api.auth._is_production_env", False):
        from flask import g
        g.auth_user = {"id": 999, "email": "stranger@example.com"}
        # Foreign user, foreign account → sentinel even outside production
        # (loopback gate requires BOTH non-prod AND loopback)
        assert require_owned_account_id("42") == _NO_ACCOUNT_SENTINEL

    # Loopback + production env → strict ownership preserved (prod gate)
    with app.test_request_context("/api/health",
                                  environ_overrides={"REMOTE_ADDR": "127.0.0.1"}), \
         patch("app.db.repositories.account_repository.AccountRepository", _Repo), \
         patch("app.db.database.get_db_session", return_value=_SessionCtx()), \
         patch("app.api.auth._is_production_env", True):
        from flask import g
        g.auth_user = {"id": 999, "email": "stranger@example.com"}
        # Even loopback can't bypass in prod (defense against misconfigured
        # ProxyFix making the proxy IP look like a client).
        assert require_owned_account_id("42") == _NO_ACCOUNT_SENTINEL


# =============================================================================
# Account isolation — activate_exclusive must scope by user_id
# =============================================================================


def test_activate_exclusive_scopes_to_same_user(tmp_path):
    """`activate_exclusive(account_id)` previously deactivated ALL other
    accounts globally. In a multi-user deployment, that meant any user
    switching their current account silently set `is_active=False` on
    accounts owned by other JWT users. Symptom: a legitimate user's
    primary account vanished from `/api/init` (filtered by is_active),
    the frontend fell back to a foreign account, and the inbox
    rendered the wrong mailbox or dropped to a few emails instead of
    several hundred. The fix scopes the deactivation to siblings of
    the same `user_id` (with NULL-user legacy accounts forming their
    own bucket)."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.db.models.account import Account
    from app.db.models.base import Base
    from app.db.repositories.account_repository import AccountRepository

    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        # Two users, two accounts each, all initially active.
        a_alice_1 = Account(email="a1@x.com", user_id=1, provider="gmail", is_active=True)
        a_alice_2 = Account(email="a2@x.com", user_id=1, provider="outlook", is_active=True)
        a_bob_1 = Account(email="b1@y.com", user_id=2, provider="gmail", is_active=True)
        a_bob_2 = Account(email="b2@y.com", user_id=2, provider="imap", is_active=True)
        session.add_all([a_alice_1, a_alice_2, a_bob_1, a_bob_2])
        session.commit()

        # Alice activates her second account → only her first should
        # be deactivated. Bob's accounts must stay active.
        repo = AccountRepository(session)
        assert repo.activate_exclusive(a_alice_2.id) is True
        session.commit()

        session.refresh(a_alice_1)
        session.refresh(a_alice_2)
        session.refresh(a_bob_1)
        session.refresh(a_bob_2)

        assert a_alice_2.is_active is True, "target account must be active"
        assert a_alice_1.is_active is False, "same-user sibling must be deactivated"
        assert a_bob_1.is_active is True, "cross-user account must NOT be touched"
        assert a_bob_2.is_active is True, "cross-user account must NOT be touched"


# =============================================================================
# P1-007 — WebSocket rejects JWT in URL query string
# =============================================================================


def test_p1_007_ws_connect_rejects_query_token(app):
    """on_daemon_connect must NOT honour ?token=... in the URL — bearer leaks
    to every reverse-proxy access log line otherwise."""
    from app.api import websocket as ws_module

    disconnects = {"called": 0}

    def _fake_disconnect(*a, **k):
        disconnects["called"] += 1

    # Simulate handshake with token only in URL query (no auth payload).
    with app.test_request_context("/socket.io/?token=leakybearer",
                                  environ_base={"REMOTE_ADDR": "203.0.113.10"}), \
         patch("flask_socketio.disconnect", _fake_disconnect), \
         patch("app.api.auth._decode_jwt", return_value={"sub": 1, "email": "alice@example.com"}):
        ws_module.on_daemon_connect(auth=None)

    assert disconnects["called"] >= 1, (
        "P1-007 regression: ws connect accepted JWT from URL query (silently "
        "leaks bearer to every proxy access log line)."
    )


# =============================================================================
# P1-008 — PendingDraftStore filters do not leak account_id=None drafts
# =============================================================================


def test_p1_008_store_excludes_null_account_when_scoped(tmp_path):
    """Drafts persisted with account_id=None must NOT match a scoped query."""
    from app.infrastructure.pending_draft_store import InMemoryPendingDraftStore
    from app.domain.entities.pending_draft import PendingDraft, PendingDraftStatus

    store = InMemoryPendingDraftStore(persist_path=str(tmp_path / "p.json"))

    d_orphan = PendingDraft(
        id="orphan",
        email_id="e1",
        account_id=None,
        email_sender="x@x.com",
        email_subject="s",
        email_body="o",
        draft_subject="ds",
        draft_body="d",
        status=PendingDraftStatus.PENDING,
    )
    d_alice = PendingDraft(
        id="alice-draft",
        email_id="e2",
        account_id="42",
        email_sender="y@y.com",
        email_subject="s",
        email_body="o",
        draft_subject="ds",
        draft_body="d",
        status=PendingDraftStatus.PENDING,
    )
    store.add(d_orphan)
    store.add(d_alice)

    alice_pending = store.get_pending(account_id="42")
    assert {d.id for d in alice_pending} == {"alice-draft"}, (
        "P1-008 leak: orphan draft with account_id=None matched a scoped "
        "query for account_id=42."
    )

    bob_pending = store.get_pending(account_id="99")
    assert bob_pending == []

    # Unscoped query (None) still returns everything for back-compat.
    everything = store.get_pending(account_id=None)
    assert {d.id for d in everything} == {"orphan", "alice-draft"}


def test_p1_008_lookup_by_email_id_refuses_null_account(tmp_path):
    """_lookup_by_email_id must return None when account_id is unset, even
    if exactly one candidate exists (single-account dev install scenario)."""
    from app.infrastructure.pending_draft_store import InMemoryPendingDraftStore
    from app.domain.entities.pending_draft import PendingDraft, PendingDraftStatus

    store = InMemoryPendingDraftStore(persist_path=str(tmp_path / "p.json"))

    d = PendingDraft(
        id="only",
        email_id="e1",
        account_id="42",
        email_sender="x@x.com",
        email_subject="s",
        email_body="o",
        draft_subject="ds",
        draft_body="d",
        status=PendingDraftStatus.PENDING,
    )
    store.add(d)

    # Without account_id, the lookup must refuse the single-candidate fallback.
    assert store._lookup_by_email_id("e1", account_id=None) is None
    # With account_id, normal hit.
    assert store._lookup_by_email_id("e1", account_id="42") == "only"


# =============================================================================
# P1-014 — WS connect rejects unowned account_id
# =============================================================================


def test_p1_014_ws_connect_rejects_unowned_account_id(app):
    """A valid JWT_A supplying account_id of a foreign tenant must be rejected
    so it cannot subscribe to that tenant's room."""
    from app.api import websocket as ws_module

    disconnects = {"called": 0}

    def _fake_disconnect(*a, **k):
        disconnects["called"] += 1

    class _Acc:
        def __init__(self, _id, email):
            self.id = _id
            self.email = email

    class _Repo:
        def __init__(self, *_a, **_k): pass
        def get(self, account_id):
            # account_id 999 belongs to bob, not alice
            if account_id == 999:
                return _Acc(999, "bob@example.com")
            return None

    class _SessionCtx:
        def __enter__(self_inner): return MagicMock()
        def __exit__(self_inner, *a): return False

    with app.test_request_context("/socket.io/",
                                  environ_base={"REMOTE_ADDR": "203.0.113.10"}), \
         patch("flask_socketio.disconnect", _fake_disconnect), \
         patch("app.api.auth._decode_jwt", return_value={"sub": 1, "email": "alice@example.com"}), \
         patch("app.db.repositories.account_repository.AccountRepository", _Repo), \
         patch("app.db.database.get_db_session", return_value=_SessionCtx()):
        ws_module.on_daemon_connect(auth={"token": "alice-jwt", "account_id": 999})

    assert disconnects["called"] >= 1, (
        "P1-014 leak: ws connect accepted account_id=999 (owned by bob) "
        "from a JWT belonging to alice."
    )
