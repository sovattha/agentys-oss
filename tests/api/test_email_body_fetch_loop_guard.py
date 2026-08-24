# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Regression tests for the WS-refetch loop bug in `_fetch_body_html_background`.

Incident 2026-05-04: an email whose body the provider could not return
(truly-empty MIME, deleted message, parse failure) hit a self-feeding cycle:

    GET /api/emails/<id>
      → SQLite has body_html=NULL, response carries body_html=null
      → backend spawns _fetch_body_html_background
          → provider returns empty body
          → SQLite stays NULL (the `if body_html:` persistence branch was skipped)
          → emit `email_body_ready` *unconditionally*
      → frontend WS handler refetches /api/emails/<id>
      → SQLite still NULL → backend respawns the bg fetch → re-emits → …

Result: 890 fetches in 4 minutes for one email, peaking at ~6 req/s, until the
modal closed.

These tests lock in the two fixes that break the cycle:

  1. The bg fetch persists `EMPTY_BODY_PLACEHOLDER` to SQLite when the provider
     returns nothing AND SQLite has nothing better. Subsequent reads see
     body_ready=True and short-circuit the bg fetch.

  2. `email_body_ready` is emitted **only** when the user-visible state
     actually moved forward. No-op fetches and sentinel-only persistence do
     NOT emit, so the frontend handler can't be re-triggered into a loop.

Run: pytest tests/api/test_email_body_fetch_loop_guard.py -v
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator
from unittest.mock import MagicMock, patch

import pytest

from app.api import routes_emails as re_mod


# ---------- helpers ---------------------------------------------------------


@pytest.fixture
def app():
    """A real Flask app context — _fetch_body_html_background needs one to
    run its inner closure (uses current_app + emit_to_account)."""
    from app.api.app import create_app
    return create_app(config={"TESTING": True})


@pytest.fixture(autouse=True)
def legacy_body_cache(monkeypatch):
    """Existing loop-guard tests exercise the legacy full-cache behavior."""
    monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "legacy_full_cache")


def _make_db_email(body_html=None, body_text=None, attachments_meta=None):
    """SQLAlchemy-style row stand-in. Attribute writes mutate `db_email` so
    the test can assert what the bg fetch persisted."""
    e = MagicMock()
    e.body_html = body_html
    e.body_text = body_text
    e.attachments_meta = attachments_meta
    return e


def _make_provider_email(body_html="", body="", attachments=None):
    """Stand-in for the StandardEmail returned by `provider.get_message_by_id`."""
    em = MagicMock()
    em.body_html = body_html
    em.body = body
    em.attachments = attachments or []
    em.sender = "from@example.com"
    em.sender_name = "Sender"
    em.subject = "Subject"
    em.received_at = ""
    em.is_read = True
    em.has_attachments = bool(attachments)
    return em


@contextmanager
def _sync_threads() -> Iterator[None]:
    """Run threads synchronously. _fetch_body_html_background spawns a daemon
    thread; for deterministic assertions we just call the target inline."""
    real_thread = threading.Thread

    class _SyncThread(real_thread):  # type: ignore[misc]
        def start(self):  # type: ignore[override]
            self.run()

    with patch.object(threading, "Thread", _SyncThread):
        yield


@contextmanager
def _patched_provider_and_db(provider_email, db_email):
    """Wire the bg fetch's account-resolution + provider + DB plumbing to mocks."""
    provider = MagicMock()
    provider.authenticate.return_value = True
    provider.get_message_by_id.return_value = provider_email

    acct = MagicMock(email="user@example.com", db_id=1, id="hash123")
    mgr = MagicMock()
    mgr.get_account.return_value = acct

    repo = MagicMock()
    repo.get_by_email_id.return_value = db_email
    session = MagicMock()
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=session)
    ctx.__exit__ = MagicMock(return_value=False)

    with patch("app.multi_accounts.get_account_manager", return_value=mgr), \
         patch("app.multi_accounts.create_provider_for_account", return_value=provider), \
         patch("app.api.routes_helpers.get_db_session", return_value=ctx), \
         patch("app.api.routes_helpers.EmailRepository", return_value=repo), \
         patch("app.api.routes_helpers._resolve_account_id_for_email", return_value=1), \
         patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=1), \
         patch("app.api.routes_emails._get_email_labels", return_value=[]):
        yield


# ---------- tests -----------------------------------------------------------


def test_empty_provider_response_persists_sentinel_and_skips_emit(app):
    """Provider returns nothing → SQLite gets EMPTY_BODY_PLACEHOLDER, no WS emit.

    This is the loop-breaker: subsequent GETs see body_html=PLACEHOLDER,
    the body_ready check passes, and no further bg fetch is spawned.
    """
    db_email = _make_db_email(body_html=None, body_text=None)
    provider_email = _make_provider_email(body_html="", body="")

    emit_calls: list[tuple] = []
    fake_emit = lambda *args, **kwargs: emit_calls.append((args, kwargs)) or True  # noqa: E731

    with app.app_context(), \
         _sync_threads(), \
         _patched_provider_and_db(provider_email, db_email), \
         patch("app.api.websocket.emit_to_account", side_effect=fake_emit):
        re_mod._fetch_body_html_background(
            email_id="msg-empty-1",
            raw_email_id="msg-empty-1",
            is_sent=False,
            account_id="hash123",
            db_account_id=1,
        )

    assert db_email.body_html == re_mod.EMPTY_BODY_PLACEHOLDER, (
        f"sentinel must be persisted to break the bg-fetch loop; "
        f"got body_html={db_email.body_html!r}"
    )
    assert emit_calls == [], (
        f"email_body_ready must NOT fire when provider returned nothing — "
        f"emitting on no-content is what made the runaway loop possible. "
        f"Got {emit_calls!r}"
    )


def test_real_body_response_persists_html_and_emits(app):
    """Provider returns real HTML → SQLite gets it, WS event fires once."""
    db_email = _make_db_email(body_html=None, body_text=None)
    provider_email = _make_provider_email(
        body_html="<p>Hello world</p>",
        body="Hello world",
    )

    emit_calls: list[tuple] = []
    fake_emit = lambda *args, **kwargs: emit_calls.append((args, kwargs)) or True  # noqa: E731

    with app.app_context(), \
         _sync_threads(), \
         _patched_provider_and_db(provider_email, db_email), \
         patch("app.api.websocket.emit_to_account", side_effect=fake_emit):
        re_mod._fetch_body_html_background(
            email_id="msg-real-1",
            raw_email_id="msg-real-1",
            is_sent=False,
            account_id="hash123",
            db_account_id=1,
        )

    assert db_email.body_html == "<p>Hello world</p>"
    assert db_email.body_text == "Hello world"
    assert len(emit_calls) == 1, (
        f"email_body_ready must fire once for real new content; got {emit_calls!r}"
    )
    args, _ = emit_calls[0]
    assert args[0] == "email_body_ready"
    assert args[1] == {"email_id": "msg-real-1"}


def test_unchanged_body_does_not_re_emit(app):
    """Provider returns the same HTML already in SQLite → no emit.

    This guards the case where a transient failure (CID-stale html that the
    provider can't refresh) would otherwise re-emit on every retry, feeding
    the same loop the empty-body case caused.
    """
    same_html = "<p>Existing body</p>"
    db_email = _make_db_email(body_html=same_html, body_text="Existing body")
    provider_email = _make_provider_email(body_html=same_html, body="Existing body")

    emit_calls: list[tuple] = []
    fake_emit = lambda *args, **kwargs: emit_calls.append((args, kwargs)) or True  # noqa: E731

    with app.app_context(), \
         _sync_threads(), \
         _patched_provider_and_db(provider_email, db_email), \
         patch("app.api.websocket.emit_to_account", side_effect=fake_emit):
        re_mod._fetch_body_html_background(
            email_id="msg-noop-1",
            raw_email_id="msg-noop-1",
            is_sent=False,
            account_id="hash123",
            db_account_id=1,
        )

    assert emit_calls == [], (
        f"unchanged content must not re-emit (loop guard); got {emit_calls!r}"
    )


def test_empty_provider_does_not_downgrade_existing_real_html(app):
    """Provider returns nothing but SQLite already has real body_html → keep it.

    The sentinel exists to break the loop for emails that *never* had content.
    It must not overwrite real content that was previously fetched (e.g. via
    a different code path, or via a successful earlier bg fetch whose CID
    refresh attempt now happens to come back empty).
    """
    real_html = "<p>Previously fetched body</p>"
    db_email = _make_db_email(body_html=real_html, body_text="Previously fetched body")
    provider_email = _make_provider_email(body_html="", body="")

    emit_calls: list[tuple] = []
    fake_emit = lambda *args, **kwargs: emit_calls.append((args, kwargs)) or True  # noqa: E731

    with app.app_context(), \
         _sync_threads(), \
         _patched_provider_and_db(provider_email, db_email), \
         patch("app.api.websocket.emit_to_account", side_effect=fake_emit):
        re_mod._fetch_body_html_background(
            email_id="msg-keep-1",
            raw_email_id="msg-keep-1",
            is_sent=False,
            account_id="hash123",
            db_account_id=1,
        )

    assert db_email.body_html == real_html, (
        "empty provider response must NOT downgrade existing real content to sentinel"
    )
    assert emit_calls == [], "no-change → no emit"


def test_text_only_email_wraps_and_emits(app):
    """Provider returns body but no body_html → wrap text and emit."""
    db_email = _make_db_email(body_html=None, body_text=None)
    provider_email = _make_provider_email(body_html="", body="Hello plaintext")

    emit_calls: list[tuple] = []
    fake_emit = lambda *args, **kwargs: emit_calls.append((args, kwargs)) or True  # noqa: E731

    with app.app_context(), \
         _sync_threads(), \
         _patched_provider_and_db(provider_email, db_email), \
         patch("app.api.websocket.emit_to_account", side_effect=fake_emit):
        re_mod._fetch_body_html_background(
            email_id="msg-text-1",
            raw_email_id="msg-text-1",
            is_sent=False,
            account_id="hash123",
            db_account_id=1,
        )

    assert db_email.body_html, "text-only email must produce a wrapped body_html"
    assert "Hello plaintext" in db_email.body_html
    assert db_email.body_html != re_mod.EMPTY_BODY_PLACEHOLDER, (
        "text-only emails must NOT trigger the sentinel path — body_text counts as content"
    )
    assert len(emit_calls) == 1, "text-only persistence must emit once"


def test_metadata_only_fetch_updates_cache_without_persisting_body(app, monkeypatch):
    """metadata_only can display provider content without writing it to SQLite."""
    monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "metadata_only")
    db_email = _make_db_email(body_html=None, body_text=None)
    provider_email = _make_provider_email(
        body_html="<p>Private content</p>",
        body="Private content",
    )

    emit_calls: list[tuple] = []
    fake_emit = lambda *args, **kwargs: emit_calls.append((args, kwargs)) or True  # noqa: E731

    with app.app_context(), \
         _sync_threads(), \
         _patched_provider_and_db(provider_email, db_email), \
         patch("app.api.websocket.emit_to_account", side_effect=fake_emit):
        re_mod._fetch_body_html_background(
            email_id="msg-private-1",
            raw_email_id="msg-private-1",
            is_sent=False,
            account_id="hash123",
            db_account_id=1,
        )

    assert db_email.body_html is None
    assert db_email.body_text is None
    assert len(emit_calls) == 1


def _seed_metadata_only_db(tmp_path, monkeypatch, email_id, db_name):
    """metadata_only DB seeded with one headers-only (no body) email row.
    Returns the account_id. Bodies are never persisted in this mode, so every
    open needs a live fetch — which is why the body-fetch path must be reliable.
    """
    from app.db.database import get_db_session, init_db, reset_engine
    from app.db.models.account import Account
    from app.db.models.email import Email

    db_path = tmp_path / db_name
    monkeypatch.setenv("AGENTYS_DB_PATH", str(db_path))
    monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "metadata_only")
    reset_engine()
    init_db()
    with get_db_session() as session:
        account = Account(email="detail@example.com", provider="gmail", user_id=42)
        session.add(account)
        session.flush()
        account_id = account.id
        session.add(
            Email(
                email_id=email_id,
                account_id=account_id,
                thread_id="thread-meta-detail",
                subject="Metadata-only detail",
                sender="sender@example.com",
                sender_name="Sender",
                recipients="detail@example.com",
                date=datetime.now(timezone.utc),
                body_text=None,
                body_html=None,
                snippet=None,
                is_read=False,
                is_starred=False,
                folder="inbox",
            )
        )
    return account_id


def test_metadata_only_no_body_fetches_body_synchronously(tmp_path, monkeypatch):
    """Regression fix 2026-05-20 (ref 1b5721e8 "serve email headers while body
    loads"): opening a metadata_only row with no cached body does a BOUNDED
    SYNCHRONOUS provider fetch and returns the body IN the response — it must NOT
    serve headers-only and lean solely on the async background fetch.

    1b5721e8 made the no-body open async-only; in metadata_only mode (the default)
    every open hits that path, and the Semaphore(3)/per-call-re-auth/silent-failure
    async fetch left bodies stuck on "This email content could not be loaded".
    The synchronous fetch (pooled provider, no per-call re-auth) is reliable.
    """
    from app.api.app import create_app
    from app.db.database import reset_engine

    account_id = _seed_metadata_only_db(
        tmp_path, monkeypatch, "msg-sync-detail", "metadata_only_sync.db"
    )
    try:
        app = create_app(config={"TESTING": True})
        client = app.test_client()
        account_config = MagicMock(id="oauth-detail", email="detail@example.com")
        provider = MagicMock()
        full_dict = {
            "id": "msg-sync-detail",
            "sender": "sender@example.com",
            "subject": "Metadata-only detail",
            "body": "Hello from the provider",
            "body_html": "<p>Hello from the provider</p>",
            "body_text": "Hello from the provider",
            "attachments": [],
        }

        with patch("app.api.routes_emails._rh.require_owned_account_id", return_value=account_id), \
             patch("app.api.routes_emails._get_account_config_for_db_account_id", return_value=account_config), \
             patch("app.api.routes_emails._get_pending_draft_email_ids", return_value=set()), \
             patch("app.api.routes_emails._get_email_labels", return_value=[]), \
             patch("app.api.routes_emails._find_email_in_list_cache", return_value=None), \
             patch("app.api.routes_emails._fetch_body_html_background") as bg_fetch, \
             patch("app.providers.factory.get_pooled_provider", return_value=provider), \
             patch("app.api.routes_emails._get_email_by_id", return_value=MagicMock()), \
             patch("app.api.routes_emails._email_to_full_dict", return_value=full_dict):
            response = client.get("/api/emails/msg-sync-detail")

        assert response.status_code == 200
        data = response.get_json()
        # Body came back IN the response — no reliance on the flaky async fetch.
        assert data["body_html"] == "<p>Hello from the provider</p>"
        assert not data.get("body_fetch_pending")
        bg_fetch.assert_not_called()
    finally:
        reset_engine()


def test_metadata_only_provider_busy_serves_headers_and_async(tmp_path, monkeypatch):
    """Busy fallback (2026-05-20): when the provider-detail semaphore is saturated,
    a no-body open degrades to headers + body_fetch_pending + async background
    fetch (so the frontend polls the body in) instead of a hard 429.
    """
    from app.api.app import create_app
    from app.api import routes_emails as re_mod
    from app.db.database import reset_engine

    account_id = _seed_metadata_only_db(
        tmp_path, monkeypatch, "msg-busy-detail", "metadata_only_busy.db"
    )
    try:
        app = create_app(config={"TESTING": True})
        client = app.test_client()
        account_config = MagicMock(id="oauth-detail", email="detail@example.com")

        with patch("app.api.routes_emails._rh.require_owned_account_id", return_value=account_id), \
             patch("app.api.routes_emails._get_account_config_for_db_account_id", return_value=account_config), \
             patch("app.api.routes_emails._get_pending_draft_email_ids", return_value=set()), \
             patch("app.api.routes_emails._get_email_labels", return_value=[]), \
             patch("app.api.routes_emails._find_email_in_list_cache", return_value=None), \
             patch.object(re_mod._provider_detail_semaphore, "acquire", return_value=False), \
             patch("app.api.routes_emails._fetch_body_html_background") as bg_fetch, \
             patch("app.api.routes_emails._get_email_by_id") as get_email_by_id:
            response = client.get("/api/emails/msg-busy-detail")

        assert response.status_code == 200
        data = response.get_json()
        assert data["body_fetch_pending"] is True
        # Provider busy → no synchronous fetch; async kicked instead.
        bg_fetch.assert_called_once()
        get_email_by_id.assert_not_called()
    finally:
        reset_engine()


def test_detail_auth_expired_serves_cached_headers(monkeypatch):
    """Stale list-cache rows must not turn provider reauth failures into 500s."""
    from app.api.app import create_app

    monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "metadata_only")
    app = create_app(config={"TESTING": True})
    client = app.test_client()
    account_config = MagicMock(id="oauth-detail", email="detail@example.com")

    session_ctx = MagicMock()
    session_ctx.__enter__.return_value = MagicMock()
    session_ctx.__exit__.return_value = False
    repo = MagicMock()
    repo.get_by_email_id.return_value = None

    list_hit = {
        "id": "msg-auth-detail",
        "sender": "sender@example.com",
        "subject": "Cached header",
        "snippet": "Cached preview",
        "is_read": False,
    }

    with patch("app.api.routes_emails._rh.require_owned_account_id", return_value=1), \
         patch("app.api.routes_emails._get_account_config_for_db_account_id", return_value=account_config), \
         patch("app.api.routes_emails._get_cached_email_detail", return_value=None), \
         patch("app.api.routes_emails._rh.get_db_session", return_value=session_ctx), \
         patch("app.api.routes_emails._rh.EmailRepository", return_value=repo), \
         patch("app.api.routes_emails._find_email_in_list_cache", return_value=list_hit), \
         patch("app.providers.factory.get_pooled_provider", side_effect=Exception("invalid_grant: revoked")):
        response = client.get("/api/emails/msg-auth-detail")

    assert response.status_code == 200
    data = response.get_json()
    assert data["subject"] == "Cached header"
    assert data["body_fetch_pending"] is True
    assert data["provider_unavailable"] is True
    assert data["needs_reauth"] is True


def test_detail_body_fetch_auth_expired_serves_headers(monkeypatch):
    """Auth can also fail after provider init, during the body fetch itself."""
    from app.api.app import create_app

    monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "metadata_only")
    app = create_app(config={"TESTING": True})
    client = app.test_client()
    account_config = MagicMock(id="oauth-detail", email="detail@example.com")

    session_ctx = MagicMock()
    session_ctx.__enter__.return_value = MagicMock()
    session_ctx.__exit__.return_value = False
    repo = MagicMock()
    repo.get_by_email_id.return_value = None

    list_hit = {
        "id": "msg-auth-body",
        "sender": "sender@example.com",
        "subject": "Cached header",
        "snippet": "Cached preview",
        "is_read": False,
    }

    with patch("app.api.routes_emails._rh.require_owned_account_id", return_value=1), \
         patch("app.api.routes_emails._get_account_config_for_db_account_id", return_value=account_config), \
         patch("app.api.routes_emails._get_cached_email_detail", return_value=None), \
         patch("app.api.routes_emails._rh.get_db_session", return_value=session_ctx), \
         patch("app.api.routes_emails._rh.EmailRepository", return_value=repo), \
         patch("app.api.routes_emails._find_email_in_list_cache", return_value=list_hit), \
         patch("app.providers.factory.get_pooled_provider", return_value=MagicMock()), \
         patch("app.api.routes_emails._get_email_by_id_for_detail", side_effect=Exception("invalid_grant: revoked")):
        response = client.get("/api/emails/msg-auth-body")

    assert response.status_code == 200
    data = response.get_json()
    assert data["subject"] == "Cached header"
    assert data["body_fetch_pending"] is True
    assert data["provider_unavailable"] is True
    assert data["needs_reauth"] is True


def test_detail_provider_backoff_serves_headers_with_retry_after(monkeypatch):
    """Quota backoff should not blank the detail modal when headers are cached."""
    from app.api.app import create_app

    monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "metadata_only")
    app = create_app(config={"TESTING": True})
    client = app.test_client()
    account_config = MagicMock(id="oauth-detail", email="detail@example.com")

    session_ctx = MagicMock()
    session_ctx.__enter__.return_value = MagicMock()
    session_ctx.__exit__.return_value = False
    repo = MagicMock()
    repo.get_by_email_id.return_value = None

    class FakeQuotaBackoff(Exception):
        code = "GMAIL_QUOTA_BACKOFF"
        retry_after = 23

    list_hit = {
        "id": "msg-quota-body",
        "sender": "sender@example.com",
        "subject": "Cached header",
        "snippet": "Cached preview",
        "is_read": False,
    }

    with patch("app.api.routes_emails._rh.require_owned_account_id", return_value=1), \
         patch("app.api.routes_emails._get_account_config_for_db_account_id", return_value=account_config), \
         patch("app.api.routes_emails._get_cached_email_detail", return_value=None), \
         patch("app.api.routes_emails._rh.get_db_session", return_value=session_ctx), \
         patch("app.api.routes_emails._rh.EmailRepository", return_value=repo), \
         patch("app.api.routes_emails._find_email_in_list_cache", return_value=list_hit), \
         patch("app.providers.factory.get_pooled_provider", return_value=MagicMock()), \
         patch("app.api.routes_emails._get_email_by_id_for_detail", side_effect=FakeQuotaBackoff()):
        response = client.get("/api/emails/msg-quota-body")

    assert response.status_code == 200
    data = response.get_json()
    assert data["subject"] == "Cached header"
    assert data["body_fetch_pending"] is True
    assert data["provider_unavailable"] is True
    assert data["provider_backoff"] is True
    assert data["retry_after"] == 23
