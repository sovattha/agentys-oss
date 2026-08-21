# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Regression tests for the 2026-05-13 deep regression audit (last 2 days,
55 commits). Nine P1 findings — each test fails against the pre-fix code
and passes after.

  F-01/F-02 — _EmailSnapshot.of must read body/id correctly whether the
              caller hands a provider StandardEmail (.id/.body) or a
              SQLAlchemy Email row (.email_id/.body_text). The post-reply
              re-eval and the daemon re-eval both pass a SQL row.
  F-03      — validate-and-send must stamp the sent reply row with the
              original thread_id (was hardcoded None → thread_has_user_reply
              re-eval could never match the just-sent reply).
  F-04      — mark_not_spam / move_to_spam must reject a JWT user with no
              DB account up front (account_id == _NO_ACCOUNT_SENTINEL)
              instead of silently UPDATE-ing zero rows.
  F-05      — auto_reply dedup key must use the bare addr@host, not the
              full "Name <addr@host>" envelope (envelope shape changes
              bypassed the once-per-window dedupe).
  F-06      — daemon._handle_auto_reply must plumb own_account_emails so
              the cross-account OOO loop guard works on the IMAP path.
  F-07      — move-to-spam must move the cached row to folder='spam', not
              delete it (no-folder _evict → BG delete_by_email_id).
  F-08      — archiving a Sent email must move the row to folder='archived',
              not delete it.
  F-09      — mark_not_spam must not race a BG DELETE against a sync
              UPDATE — the _evict call now targets folder='inbox'.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("flask_cors")

from app.quicksteps import auto_trigger


# ============================================================================
# Shared fakes
# ============================================================================


class _FakeQuery:
    def __init__(self, result):
        self._result = result

    def filter(self, *a, **kw):
        return self

    def first(self):
        return self._result


class _FakeSession:
    """Context-manager session whose .query(...).filter(...).first() returns
    a preset row, and whose mutating methods are no-ops."""

    def __init__(self, query_result=None):
        self._query_result = query_result

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def query(self, *a, **kw):
        return _FakeQuery(self._query_result)

    def expunge(self, obj):
        pass

    def commit(self):
        pass


# ============================================================================
# F-01 / F-02 — _EmailSnapshot.of shape robustness
# ============================================================================


class TestF01F02SnapshotShapeRobustness:
    """A SQL Email row exposes the provider id in ``.email_id`` and the text
    in ``.body_text``; ``.id`` is the int PK. A provider StandardEmail
    exposes ``.id`` (provider id) and ``.body``. The snapshot must read the
    right attribute for each shape — the old getattr(email, "body") /
    getattr(email, "id") returned "" and the int PK for SQL rows, silently
    breaking content_keyword / has_label / subject_or_body_keyword."""

    @staticmethod
    def _sql_row():
        # deadline_at + emoji_marker_json pre-set so the SQL backfill branch
        # short-circuits — this test isolates the shape-mapping behaviour.
        return SimpleNamespace(
            id=42,  # int PK — the trap; must NOT become snapshot.id
            email_id="msg-provider-abc",  # the real provider message id
            body_text="invoice 12345 attached",
            body=None,  # SQLA Email row has no .body column
            body_html="",
            sender="billing@stripe.com",
            subject="Facture",
            recipients="",
            attachments_meta="",
            thread_id="thread-xyz",
            is_read=False,
            date=None,
            deadline_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
            emoji_marker_json='{"emoji": "x"}',
        )

    def test_sql_row_maps_email_id_and_body_text(self, monkeypatch):
        monkeypatch.setattr(
            auto_trigger, "_get_email_label_names", lambda eid, aid: []
        )
        snap = auto_trigger._EmailSnapshot.of(self._sql_row(), account_id=42)

        assert snap.id == "msg-provider-abc", (
            "snapshot.id must be the provider message id from .email_id, "
            "not the int PK from .id"
        )
        assert snap.body == "invoice 12345 attached", (
            "snapshot.body must come from the SQL row's .body_text column"
        )

    def test_provider_standardemail_still_uses_id_and_body(self, monkeypatch):
        monkeypatch.setattr(
            auto_trigger, "_get_email_label_names", lambda eid, aid: []
        )
        from app.interfaces.email_provider import StandardEmail

        se = StandardEmail(
            id="gmail-hex-1",
            sender="a@b.com",
            subject="hi",
            body="hello world",
        )
        snap = auto_trigger._EmailSnapshot.of(se, account_id=42)

        assert snap.id == "gmail-hex-1"
        assert snap.body == "hello world"

    def test_content_keyword_matches_sql_row_body(self, monkeypatch):
        """End-to-end: a content_keyword trigger fires against a SQL row's
        body_text — the exact post-reply / daemon re-eval scenario."""
        monkeypatch.setattr(
            auto_trigger, "_get_email_label_names", lambda eid, aid: []
        )
        snap = auto_trigger._EmailSnapshot.of(self._sql_row(), account_id=42)

        assert (
            auto_trigger._match_condition(
                {"type": "content_keyword", "value": "invoice"},
                snap,
                account_id=42,
                email_id="msg-provider-abc",
            )
            is True
        )


# ============================================================================
# F-03 — validate-and-send stamps thread_id on the sent reply row
# ============================================================================


class TestF03ValidateStampsThreadId:
    """The sent reply row inserted by POST /api/pending-drafts/<id>/validate
    must carry the original inbox email's thread_id. It was hardcoded to
    None, so the immediately-following thread_has_user_reply re-eval (which
    queries Email.thread_id == <orig thread>) could never see the reply."""

    @pytest.fixture
    def client(self):
        from app.api.app import create_app

        app = create_app(config={"TESTING": True})
        app.config["TESTING"] = True
        return app.test_client()

    def test_sent_reply_row_inherits_original_thread_id(
        self, client, monkeypatch
    ):
        from app.domain.entities.pending_draft import PendingDraftStatus
        from contextlib import nullcontext

        # --- pending draft + store ------------------------------------
        draft = MagicMock()
        draft.id = "pending-123"
        draft.email_id = "email-orig-123"
        draft.account_id = 1  # must match _resolve_account_id_cached() below
        draft.draft_subject = "Re: Test"
        draft.draft_body = "Reply body"
        draft.email_sender = "client@example.com"
        draft.email_received_at = ""
        draft.status = PendingDraftStatus.PENDING

        mock_store = MagicMock()
        mock_store.get_by_id.return_value = draft
        mock_store.update_status.return_value = True
        mock_store.get_draft_lock.return_value = nullcontext()
        mock_container = MagicMock()
        mock_container.get_pending_draft_store.return_value = mock_store

        # --- provider (create + send succeed) -------------------------
        provider = MagicMock()
        provider.send_reply_directly = MagicMock(return_value=False)
        provider.create_draft.return_value = "gmail-draft-456"
        provider.send_draft.return_value = True
        provider._email = "me@example.com"

        # --- DB layer: orig row carries a known thread_id; capture the
        #     inserted sent reply row ------------------------------------
        orig_row = SimpleNamespace(
            email_id="email-orig-123",
            account_id=1,
            thread_id="thread-original-abc",
        )
        created = []

        class _CapturingRepo:
            def __init__(self, session):
                pass

            def create(self, email):
                created.append(email)

            def dedupe_sent_by_content(self, account_id):
                pass

        monkeypatch.setattr(
            "app.api.routes_helpers._get_container", lambda: mock_container
        )
        monkeypatch.setattr(
            "app.api.routes_pending._get_authenticated_provider",
            lambda: provider,
        )
        monkeypatch.setattr(
            "app.api.routes_pending._resolve_account_id_cached", lambda: 1
        )
        monkeypatch.setattr(
            "app.api.routes_pending._evict_email_from_all_caches",
            lambda *a, **kw: None,
        )
        monkeypatch.setattr(
            "app.api.routes_pending._invalidate_folder_cache",
            lambda *a, **kw: None,
        )
        # Both get_db_session() calls (orig-row load + insert) return a
        # fake session; the orig-row query resolves to our known row.
        monkeypatch.setattr(
            "app.api.routes_helpers.get_db_session",
            lambda: _FakeSession(query_result=orig_row),
        )
        monkeypatch.setattr(
            "app.api.routes_helpers.EmailRepository", _CapturingRepo
        )
        # The re-eval is fire-and-forget — stub it so the test stays sync.
        reeval_calls = []
        monkeypatch.setattr(
            "app.quicksteps.auto_trigger.run_auto_triggers_async",
            lambda aid, eid, email: reeval_calls.append((aid, eid, email)),
        )

        resp = client.post("/api/pending-drafts/pending-123/validate")
        assert resp.status_code == 200, resp.get_json()

        provider.send_reply_directly.assert_called_once()
        assert (
            provider.send_reply_directly.call_args.kwargs["thread_id"]
            == "thread-original-abc"
        )
        assert len(created) == 1, "exactly one sent reply row must be inserted"
        assert created[0].thread_id == "thread-original-abc", (
            "F-03: the sent reply row must inherit the original inbox "
            "email's thread_id, not None — otherwise thread_has_user_reply "
            "can never match the just-sent reply"
        )
        # F-01 corollary: the re-eval must receive the original SQL row so
        # the (now shape-robust) snapshot can read it.
        assert reeval_calls and reeval_calls[0][2] is orig_row


# ============================================================================
# F-04 / F-07 / F-08 / F-09 — routes_emails spam / archive handlers
# ============================================================================


class TestF04F07F08F09EmailHandlers:
    @pytest.fixture
    def client(self):
        from app.api.app import create_app

        app = create_app(config={"TESTING": True})
        app.config["TESTING"] = True
        return app.test_client()

    # ----- F-04: sentinel account → 4xx, no silent zero-row write --------

    def test_not_spam_rejects_no_account_sentinel(self, client, monkeypatch):
        import app.api.routes_helpers as _rh

        monkeypatch.setattr(
            _rh, "_resolve_account_id_for_user", lambda: _rh._NO_ACCOUNT_SENTINEL
        )
        # The provider must never be reached — the guard is before it.
        provider = MagicMock()
        monkeypatch.setattr(
            "app.api.routes_emails._get_authenticated_provider", lambda: provider
        )

        resp = client.post("/api/emails/msg-abc/not-spam")

        assert resp.status_code == 403, (
            "F-04: a JWT user with no DB account must get 403, not a "
            "200-with-silent-zero-row-update"
        )
        provider.move_to_inbox.assert_not_called()

    def test_move_to_spam_rejects_no_account_sentinel(self, client, monkeypatch):
        import app.api.routes_helpers as _rh

        monkeypatch.setattr(
            _rh, "_resolve_account_id_for_user", lambda: _rh._NO_ACCOUNT_SENTINEL
        )
        provider = MagicMock()
        monkeypatch.setattr(
            "app.api.routes_emails._get_authenticated_provider", lambda: provider
        )

        resp = client.post("/api/emails/msg-abc/move-to-spam")

        assert resp.status_code == 403
        provider.move_to_spam.assert_not_called()

    # ----- F-07: move-to-spam moves the row, never deletes it -----------

    def test_move_to_spam_moves_row_not_deletes(self, client, monkeypatch):
        import app.api.routes_helpers as _rh

        monkeypatch.setattr(_rh, "_resolve_account_id_for_user", lambda: 1)
        monkeypatch.setattr(
            _rh, "get_db_session", lambda: _FakeSession(query_result=None)
        )
        provider = MagicMock()
        provider.move_to_spam.return_value = True
        monkeypatch.setattr(
            "app.api.routes_emails._get_authenticated_provider", lambda: provider
        )

        evict_calls = []
        monkeypatch.setattr(
            "app.api.routes_emails._evict_email_from_all_caches",
            lambda email_id, **kw: evict_calls.append((email_id, kw)),
        )

        resp = client.post("/api/emails/msg-abc/move-to-spam")
        assert resp.status_code == 200, resp.get_json()

        assert evict_calls, "the handler must invalidate caches"
        assert all(
            kw.get("move_to_folder") == "spam" for _eid, kw in evict_calls
        ), (
            "F-07: every _evict call must pass move_to_folder='spam' — a "
            "no-folder call takes the BG delete_by_email_id branch and "
            "wipes the row"
        )

    # ----- F-08: archiving a Sent email moves the row, never deletes it --

    def test_archive_sent_email_moves_row_not_deletes(
        self, client, monkeypatch
    ):
        monkeypatch.setattr(
            "app.api.routes_emails._resolve_account_id_cached", lambda: 1
        )
        monkeypatch.setattr(
            "app.api.routes_emails._email_exists_in_cache",
            lambda *a, **kw: True,
        )
        provider = MagicMock()
        monkeypatch.setattr(
            "app.api.routes_emails._get_authenticated_provider", lambda: provider
        )
        monkeypatch.setattr(
            "app.api.websocket.emit_email_archived", lambda *a, **kw: None
        )

        evict_calls = []
        monkeypatch.setattr(
            "app.api.routes_emails._evict_email_from_all_caches",
            lambda email_id, **kw: evict_calls.append((email_id, kw)),
        )

        resp = client.post("/api/emails/sent:msg-abc/archive")
        assert resp.status_code == 200, resp.get_json()

        assert evict_calls, "the sent-archive branch must invalidate caches"
        assert all(
            kw.get("move_to_folder") == "archived" for _eid, kw in evict_calls
        ), (
            "F-08: the is_sent_email branch must pass "
            "move_to_folder='archived' so the row moves instead of being "
            "deleted from both Sent and Archives"
        )

    # ----- F-09: not-spam moves the row to inbox, no racing DELETE ------

    def test_not_spam_moves_row_to_inbox_no_delete(self, client, monkeypatch):
        import app.api.routes_helpers as _rh

        monkeypatch.setattr(_rh, "_resolve_account_id_for_user", lambda: 1)
        monkeypatch.setattr(
            _rh, "get_db_session", lambda: _FakeSession(query_result=None)
        )
        provider = MagicMock()
        provider.move_to_inbox.return_value = True
        monkeypatch.setattr(
            "app.api.routes_emails._get_authenticated_provider", lambda: provider
        )

        evict_calls = []
        monkeypatch.setattr(
            "app.api.routes_emails._evict_email_from_all_caches",
            lambda email_id, **kw: evict_calls.append((email_id, kw)),
        )

        resp = client.post("/api/emails/msg-abc/not-spam")
        assert resp.status_code == 200, resp.get_json()

        assert evict_calls, "not-spam must invalidate caches"
        assert all(
            kw.get("move_to_folder") == "inbox" for _eid, kw in evict_calls
        ), (
            "F-09: the _evict call must pass move_to_folder='inbox' — the "
            "old no-folder call scheduled a BG DELETE that raced the sync "
            "UPDATE and usually won, wiping the row"
        )


# ============================================================================
# F-05 — auto_reply dedup key uses the bare address, not the envelope
# ============================================================================


class TestF05AutoReplyDedupeEnvelope:
    @pytest.fixture(autouse=True)
    def _clear_state(self):
        from app.services import auto_reply as _mod

        _mod.reset_replied_senders()
        yield
        _mod.reset_replied_senders()

    @staticmethod
    def _enabled_settings():
        today = datetime.now()
        return {
            "auto_reply_enabled": True,
            "auto_reply_message": "Out of office",
            "auto_reply_start": (today - timedelta(days=7)).strftime("%Y-%m-%d"),
            "auto_reply_end": (today + timedelta(days=7)).strftime("%Y-%m-%d"),
        }

    @staticmethod
    def _email(sender):
        e = MagicMock()
        e.id = "msg-1"
        e.sender = sender
        e.subject = "Question"
        e.body = "Hello"
        return e

    def test_envelope_shape_change_does_not_bypass_dedupe(self):
        from app.services.auto_reply import send_auto_reply_if_needed

        provider = MagicMock()
        provider.create_draft.return_value = "draft-1"
        provider.send_draft.return_value = True

        with patch(
            "app.api.settings.load_settings", return_value=self._enabled_settings()
        ):
            first = send_auto_reply_if_needed(
                provider, 1, self._email("alice@acme.com")
            )
            # Same human, client now adds a display name to the envelope.
            second = send_auto_reply_if_needed(
                provider, 1, self._email("Alice Doe <alice@acme.com>")
            )

        assert first is True
        assert second is False, (
            "F-05: the second send must be deduped — the dedup key is the "
            "bare addr@host, not the full 'Name <addr>' envelope"
        )
        assert provider.create_draft.call_count == 1


# ============================================================================
# F-06 — daemon._handle_auto_reply plumbs own_account_emails
# ============================================================================


class TestF06DaemonPlumbsOwnAccountEmails:
    def test_handle_auto_reply_passes_own_account_emails(
        self, mocked_daemon, monkeypatch
    ):
        """The daemon path must collect every connected account's address
        and pass it as own_account_emails — without it the cross-account
        OOO loop guard falls back to the single account_email and the
        Gmail → Hotmail → Gmail loop is not broken."""
        mocked_daemon.account = SimpleNamespace(id=1, email="me@gmail.com")

        active_accounts = [
            SimpleNamespace(email="me@gmail.com"),
            SimpleNamespace(email="me@hotmail.com"),
        ]

        class _AcctRepo:
            def __init__(self, session):
                pass

            def get_active_accounts(self):
                return active_accounts

        monkeypatch.setattr(
            "app.db.repositories.AccountRepository", _AcctRepo
        )
        monkeypatch.setattr(
            "app.db.database.get_db_session", lambda: _FakeSession()
        )

        sent_calls = []

        def _fake_send(**kwargs):
            sent_calls.append(kwargs)
            return False

        monkeypatch.setattr(
            "app.services.auto_reply.send_auto_reply_if_needed", _fake_send
        )

        email = SimpleNamespace(sender="external@somewhere.com")
        mocked_daemon._handle_auto_reply(email, is_auto_reply=False)

        assert len(sent_calls) == 1
        own = sent_calls[0].get("own_account_emails")
        assert own is not None, (
            "F-06: daemon._handle_auto_reply must pass own_account_emails"
        )
        assert set(own) == {"me@gmail.com", "me@hotmail.com"}, (
            "own_account_emails must contain every connected account so the "
            "cross-account loop guard sees the user's other inboxes"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
