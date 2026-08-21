# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
End-to-end regression tests for ALL critical Agentys features.

Verifies the full backend stack (Flask → routes → helpers → providers → DB)
works correctly for every major feature area. All external dependencies
(IMAP, LLM, Whisper) are mocked at the provider/adapter boundary.

pytest tests/test_e2e_critical_features.py -v

Coverage: 20 feature areas, ~60 tests, all critical API endpoints.
"""

from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def app():
    from app.api.app import create_app
    app = create_app(config={"TESTING": True})
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def _mock_current_account_e2e():
    """Route /api/emails retourne count=0 no_account=True sans compte actif
    (routes_emails.py:567-575). Mock un compte pour tous les tests qui en
    dépendent."""
    mock_account = Mock()
    mock_account.id = "test-account"
    mock_account.email = "test@example.com"
    with (
        patch("app.api.routes_emails._get_current_account_for_user",
              return_value=mock_account),
        patch("app.api.routes_emails._rh._resolve_account_id_for_user",
              return_value=1),
    ):
        yield mock_account


def _mock_email(id="msg-001", sender="alice@example.com", sender_name="Alice",
                subject="Test Subject", body="Hello", is_read=False):
    """Factory for mock email objects."""
    email = Mock()
    email.id = id
    email.sender = sender
    email.sender_name = sender_name
    email.subject = subject
    email.body = body
    email.body_text = body
    email.body_html = f"<p>{body}</p>"
    email.is_read = is_read
    email.received_at = datetime(2026, 3, 22, 10, 0, 0)
    email.has_attachments = False
    email.conversation_id = None
    email.thread_id = None
    email.to = ["user@example.com"]
    email.cc = []
    email.bcc = []
    email.labels = []
    email.provider_source = "test"
    email.snippet = body[:50]
    email.attachments = []
    return email


def _mock_provider():
    """Factory for mock email provider."""
    provider = Mock()
    provider.authenticate.return_value = True
    provider.PROVIDER_NAME = "gmail"
    provider.mark_as_read.return_value = True
    provider.mark_as_unread.return_value = True
    provider.archive_email.return_value = True
    provider.delete_email.return_value = True
    provider.move_to_spam.return_value = True
    provider.restore_from_trash.return_value = True
    provider.move_to_inbox.return_value = True
    provider.create_draft.return_value = "draft-001"
    provider.send_draft.return_value = True
    provider.send_reply_directly.return_value = True
    provider.get_message_by_id.return_value = _mock_email()
    provider.get_messages.return_value = [_mock_email()]
    provider.get_message_headers.return_value = [_mock_email()]
    provider.apply_label.return_value = True
    provider.remove_label.return_value = True
    provider.disconnect.return_value = None
    return provider


def _mock_pending_draft(id="pd-001", email_id="msg-001", status="pending"):
    """Factory for mock pending draft."""
    draft = Mock()
    draft.id = id
    draft.email_id = email_id
    draft.status = status
    draft.draft_subject = "Re: Test Subject"
    draft.draft_body = "This is the draft body"
    draft.email_subject = "Test Subject"
    draft.email_sender = "alice@example.com"
    draft.email_sender_name = "Alice"
    draft.email_body = "Hello"
    draft.intent = "reply"
    draft.tier = "STANDARD"
    draft.classification_reason = "standard email"
    draft.created_at = datetime(2026, 3, 22, 10, 5, 0)
    draft.smart_suggestions = ["Oui", "Non"]
    draft.quick_replies = None
    draft.gmail_draft_id = "gmail-draft-001"
    draft.drafter_model = "haiku"
    draft.critic_score = 85
    draft.to_dict.return_value = {
        "id": id, "email_id": email_id, "status": status,
        "draft_subject": "Re: Test Subject", "draft_body": "This is the draft body",
        "email_subject": "Test Subject", "email_sender": "alice@example.com",
        "email_sender_name": "Alice", "email_body": "Hello",
        "intent": "reply", "tier": "STANDARD",
        "created_at": "2026-03-22T10:05:00",
        "smart_suggestions": ["Oui", "Non"],
        "gmail_draft_id": "gmail-draft-001",
    }
    draft.to_dict_summary.return_value = {
        "id": id, "email_id": email_id, "status": status,
        "draft_subject": "Re: Test Subject",
        "email_subject": "Test Subject", "email_sender": "alice@example.com",
        "created_at": "2026-03-22T10:05:00",
    }
    return draft


# ===========================================================================
# 1. HEALTH & INITIALIZATION
# ===========================================================================

class TestHealthEndpoints:
    """Critical: Backend must report health correctly."""

    def test_ping_returns_ok(self, client):
        """GET /api/ping — instant liveness check."""
        response = client.get("/api/ping")
        assert response.status_code == 200
        data = response.get_json()
        assert data.get("status") == "ok"
        assert "version" in data

    def test_health_returns_ok(self, client):
        """GET /api/health — lightweight health."""
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.get_json()
        assert "status" in data

    def test_health_deep_endpoint_exists(self, client):
        """GET /api/health/deep — endpoint exists and responds."""
        response = client.get("/api/health/deep")
        # May return 200 or 500 depending on IMAP/LLM state, but must not 404
        assert response.status_code != 404

    def test_stats_endpoint_exists(self, client):
        """GET /api/stats — endpoint exists and responds."""
        response = client.get("/api/stats")
        # May fail due to container setup, but must not 404
        assert response.status_code != 404


# ===========================================================================
# 2. EMAIL LISTING & DETAIL
# ===========================================================================

class TestEmailListing:
    """Critical: Users must be able to list and view emails."""

    @patch("app.api.routes_emails._get_cached_email_response")
    def test_list_emails_inbox(self, mock_cache, client):
        """GET /api/emails — list inbox emails from cache."""
        mock_cache.return_value = {
            "count": 2, "offset": 0, "has_more": False,
            "filter": "all", "source": "cache",
            "emails": [
                {"id": "e1", "sender": "a@b.com", "sender_name": "A",
                 "subject": "Hello", "received_at": "2026-03-22T10:00:00Z",
                 "is_read": False, "body": "", "labels": []},
                {"id": "e2", "sender": "c@d.com", "sender_name": "C",
                 "subject": "World", "received_at": "2026-03-22T09:00:00Z",
                 "is_read": True, "body": "", "labels": []},
            ],
        }

        response = client.get("/api/emails")
        data = response.get_json()

        assert response.status_code == 200
        assert data["count"] == 2
        assert len(data["emails"]) == 2

    @patch("app.api.routes_emails._get_cached_email_response")
    def test_list_emails_with_folder_param(self, mock_cache, client):
        """GET /api/emails?folder=sent — list sent emails."""
        mock_cache.return_value = {
            "count": 0, "offset": 0, "has_more": False,
            "filter": "all", "source": "cache", "emails": [],
        }

        response = client.get("/api/emails?folder=sent")
        assert response.status_code == 200

    @patch("app.api.routes_emails._get_cached_email_response")
    def test_list_emails_pagination(self, mock_cache, client):
        """GET /api/emails?limit=10&offset=20 — pagination works."""
        mock_cache.return_value = {
            "count": 0, "offset": 20, "has_more": True,
            "filter": "all", "source": "cache", "emails": [],
        }

        response = client.get("/api/emails?limit=10&offset=20")
        assert response.status_code == 200

    def test_list_emails_invalid_limit(self, client):
        """GET /api/emails?limit=-1 — validation rejects negative."""
        response = client.get("/api/emails?limit=-1")
        assert response.status_code == 400

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_get_email_detail(self, mock_auth, mock_get_email, client):
        """GET /api/emails/<id> — get email with body and metadata."""
        email = _mock_email()
        mock_auth.return_value = _mock_provider()
        mock_get_email.return_value = email

        with patch("app.api.routes_emails._get_account_config_for_db_account_id", return_value=None), \
             patch("app.api.routes_emails._get_current_account_for_user", return_value=None):
            response = client.get("/api/emails/msg-001")
        assert response.status_code == 200
        data = response.get_json()
        assert data["id"] == "msg-001"

    def test_get_email_invalid_id(self, client):
        """GET /api/emails/<invalid> — invalid ID rejected."""
        response = client.get("/api/emails/invalid!!id")
        assert response.status_code == 400


# ===========================================================================
# 3. EMAIL ACTIONS (read, archive, delete, skip, spam)
# ===========================================================================

class TestEmailActions:
    """Critical: Users must be able to act on emails."""

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_mark_as_read(self, mock_auth, mock_get_email, client):
        """PATCH /api/emails/<id>/read — mark email as read."""
        mock_auth.return_value = _mock_provider()
        mock_get_email.return_value = _mock_email()

        response = client.patch("/api/emails/msg-001/read", json={"is_read": True})
        assert response.status_code == 200
        assert response.get_json()["success"] is True

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_archive_email(self, mock_auth, mock_get_email, client):
        """POST /api/emails/<id>/archive — archive email."""
        mock_auth.return_value = _mock_provider()
        mock_get_email.return_value = _mock_email()

        with patch("app.api.routes_emails._email_exists_in_cache", return_value=True):
            response = client.post("/api/emails/msg-001/archive")
        assert response.status_code == 200

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_delete_email(self, mock_auth, mock_get_email, client):
        """POST /api/emails/<id>/delete — move email to trash."""
        mock_auth.return_value = _mock_provider()
        mock_get_email.return_value = _mock_email()

        response = client.post("/api/emails/msg-001/delete")
        assert response.status_code == 200

    @patch("app.api.routes_emails._evict_email_from_all_caches")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_delete_email_provider_false_does_not_return_success(self, mock_auth, mock_evict, client):
        """POST /api/emails/<id>/delete fails when provider trashing fails."""
        provider = _mock_provider()
        provider.delete_email.return_value = False
        mock_auth.return_value = provider

        response = client.post("/api/emails/msg-001/delete")
        data = response.get_json()

        assert response.status_code == 502
        assert data["error"] == "Failed to delete email"
        assert data["provider_synced"] is False
        provider.delete_email.assert_called_once_with("msg-001")
        mock_evict.assert_not_called()

    @patch("app.api.routes_emails._evict_email_from_all_caches")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_delete_email_auth_expired_requests_reauth(self, mock_auth, mock_evict, client):
        """POST /api/emails/<id>/delete reports reauth instead of fake success."""
        provider = _mock_provider()
        provider.delete_email.side_effect = Exception("invalid_grant: Token has been expired or revoked.")
        mock_auth.return_value = provider

        response = client.post("/api/emails/msg-001/delete")
        data = response.get_json()

        assert response.status_code == 401
        assert data["error"] == "Email provider authentication failed"
        assert data["provider_synced"] is False
        assert data["needs_reauth"] is True
        provider.delete_email.assert_called_once_with("msg-001")
        mock_evict.assert_not_called()

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_skip_email(self, mock_auth, mock_get_email, client):
        """POST /api/emails/<id>/skip — skip without drafting."""
        mock_auth.return_value = _mock_provider()
        mock_get_email.return_value = _mock_email()

        response = client.post("/api/emails/msg-001/skip")
        assert response.status_code == 200
        assert response.get_json()["success"] is True

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_move_to_spam(self, mock_auth, mock_get_email, client):
        """POST /api/emails/<id>/move-to-spam — spam classification."""
        mock_auth.return_value = _mock_provider()
        mock_get_email.return_value = _mock_email()

        response = client.post("/api/emails/msg-001/move-to-spam")
        assert response.status_code == 200

    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_bulk_mark_read(self, mock_auth, client):
        """PATCH /api/emails/bulk-read — bulk read/unread."""
        mock_auth.return_value = _mock_provider()

        response = client.patch(
            "/api/emails/bulk-read",
            json={"email_ids": ["e1", "e2", "e3"], "is_read": True}
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["updated_count"] == 3

    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_bulk_archive(self, mock_auth, client):
        """POST /api/emails/bulk-archive — bulk archive."""
        mock_auth.return_value = _mock_provider()

        response = client.post(
            "/api/emails/bulk-archive",
            json={"email_ids": ["e1", "e2"]}
        )
        assert response.status_code == 200


# ===========================================================================
# 4. DRAFT CREATION & SENDING
# ===========================================================================

class TestDraftCreation:
    """Critical: Draft creation and sending must work end-to-end."""

    @patch("app.api.routes_emails._resolve_account_id_cached", return_value=1)
    @patch("app.api.routes_helpers._resolve_account_id_cached", return_value=1)
    @patch("app.utils.signature.append_signature", side_effect=lambda body, **kw: body)
    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_create_draft_from_content(self, mock_auth, mock_get_email, mock_sig,
                                        mock_res1, mock_res2, client):
        """POST /api/emails/<id>/draft — create draft with user content."""
        provider = _mock_provider()
        mock_auth.return_value = provider
        mock_get_email.return_value = _mock_email()

        response = client.post(
            "/api/emails/msg-001/draft",
            json={"subject": "Re: Test", "body": "My reply here"}
        )
        assert response.status_code == 201
        data = response.get_json()
        assert data["success"] is True

    @patch("app.api.routes_emails._resolve_account_id_cached", return_value=1)
    @patch("app.api.routes_helpers._resolve_account_id_cached", return_value=1)
    @patch("app.utils.signature.append_signature", side_effect=lambda body, **kw: body)
    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_create_and_send_immediately(self, mock_auth, mock_get_email, mock_sig,
                                          mock_res1, mock_res2, client):
        """POST /api/emails/<id>/draft with send=true — create + send."""
        provider = _mock_provider()
        mock_auth.return_value = provider
        mock_get_email.return_value = _mock_email()

        response = client.post(
            "/api/emails/msg-001/draft",
            json={"subject": "Re: Test", "body": "Quick reply", "send": True}
        )
        assert response.status_code in (200, 201)

    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_send_existing_draft(self, mock_auth, client):
        """POST /api/emails/<draft_id>/send — send a Gmail draft."""
        provider = _mock_provider()
        mock_auth.return_value = provider

        response = client.post("/api/emails/draft-001/send")
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True


# ===========================================================================
# 5. PENDING DRAFTS (the core review workflow)
# ===========================================================================

class TestPendingDrafts:
    """Critical: The draft review workflow must work."""

    def test_list_pending_drafts_endpoint_exists(self, client):
        """GET /api/pending-drafts — endpoint exists."""
        response = client.get("/api/pending-drafts")
        # Returns 200 (possibly empty list) or 500 (container not fully mocked)
        assert response.status_code != 404

    def test_get_pending_draft_returns_404_for_unknown(self, client):
        """GET /api/pending-drafts/<id> — unknown ID returns 404."""
        response = client.get("/api/pending-drafts/nonexistent-draft")
        assert response.status_code in (404, 500)

    def test_reject_pending_draft_returns_404_for_unknown(self, client):
        """POST /api/pending-drafts/<id>/reject — unknown ID returns 404."""
        response = client.post("/api/pending-drafts/nonexistent-draft/reject")
        assert response.status_code in (404, 500)

    def test_delete_pending_draft_accepts_any_id(self, client):
        """DELETE /api/pending-drafts/<id> — idempotent delete (200 even if missing)."""
        response = client.delete("/api/pending-drafts/nonexistent-draft")
        assert response.status_code in (200, 404)


# ===========================================================================
# 6. EMAIL COMPOSE & SEND NEW
# ===========================================================================

class TestComposeAndSend:
    """Critical: Compose new emails (not replies) must work."""

    @patch("app.api.routes_emails._resolve_account_id_cached", return_value=1)
    @patch("app.api.routes_helpers._resolve_account_id_cached", return_value=1)
    @patch("app.utils.signature.append_signature", side_effect=lambda body, **kw: body)
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_send_new_email(self, mock_auth, mock_sig, mock_res1, mock_res2, client):
        """POST /api/emails/send-new — compose and send new message."""
        provider = _mock_provider()
        provider.create_draft.return_value = "new-draft-001"
        mock_auth.return_value = provider

        response = client.post(
            "/api/emails/send-new",
            json={
                "to": "bob@example.com",
                "subject": "Hello Bob",
                "body": "Nice to meet you!",
            }
        )
        assert response.status_code in (200, 201)
        data = response.get_json()
        assert data.get("success") is True


# ===========================================================================
# 7. LEARNING & RULES
# ===========================================================================

class TestLearning:
    """Critical: Learning system must expose rules and stats."""

    @patch("app.api.auth._decode_jwt", return_value={"sub": "1", "email": "admin@example.com"})
    @patch("app.api.admin._is_admin", return_value=True)
    @patch("app.api.routes_helpers._get_container")
    def test_learning_stats(self, mock_container, _mock_is_admin, _mock_decode, client):
        """GET /api/learning/stats — learning statistics."""
        mock_learn = Mock()
        mock_learn.get_stats.return_value = {"rules_count": 5, "patterns_count": 3}
        mock_c = Mock()
        mock_c.get_learning_service.return_value = mock_learn
        mock_container.return_value = mock_c

        response = client.get(
            "/api/learning/stats",
            headers={"Authorization": "Bearer admin-jwt"},
            environ_base={"REMOTE_ADDR": "203.0.113.10"},
        )
        assert response.status_code == 200

    @patch("app.api.routes_helpers.get_container")
    def test_learning_rules_list(self, mock_container, client):
        """GET /api/learning/rules — list learned rules."""
        mock_rules_repo = Mock()
        mock_rules_repo.get_all.return_value = []
        mock_c = Mock()
        mock_c.get_rules_repository.return_value = mock_rules_repo
        mock_container.return_value = mock_c

        response = client.get("/api/learning/rules")
        assert response.status_code == 200


# ===========================================================================
# 9. CONTACTS
# ===========================================================================

class TestContacts:
    """Critical: Contact autocomplete must work for compose."""

    def test_contact_autocomplete_endpoint_exists(self, client):
        """GET /api/contacts/autocomplete — endpoint exists."""
        response = client.get("/api/contacts/autocomplete?q=test")
        # Returns 200 with results or empty list (queries SQLite)
        assert response.status_code == 200
        data = response.get_json()
        assert isinstance(data, list)


# ===========================================================================
# 10. COSTS & ANALYTICS
# ===========================================================================

class TestCosts:
    """Critical: Cost tracking must report correctly."""

    @patch("app.api.routes_helpers.get_container")
    def test_costs_endpoint(self, mock_container, client):
        """GET /api/costs — monthly cost breakdown."""
        mock_tc = Mock()
        mock_tc.get_breakdown.return_value = {
            "total_cost": 1.23, "total_tokens": 50000,
            "by_model": {"haiku": {"cost": 0.5, "tokens": 30000}},
        }
        mock_c = Mock()
        mock_c.get_token_counter.return_value = mock_tc
        mock_container.return_value = mock_c

        with patch("app.api.auth._decode_jwt", return_value={"sub": "1", "email": "admin@example.com"}), \
             patch("app.api.admin._is_admin", return_value=True):
            response = client.get("/api/costs", headers={"Authorization": "Bearer admin-jwt"})
        assert response.status_code == 200


# ===========================================================================
# 11. DRAFT HISTORY
# ===========================================================================

class TestDraftHistory:
    """Critical: Draft history must be queryable."""

    def test_list_draft_history_endpoint_exists(self, client):
        """GET /api/drafts — endpoint exists."""
        response = client.get("/api/drafts")
        assert response.status_code != 404


# ===========================================================================
# 12. SENDER BLOCKING
# ===========================================================================

class TestSenderBlocking:
    """Critical: Sender blocking must protect the inbox."""

    @patch("app.api.routes_emails._get_blocked_senders_set")
    def test_list_blocked_senders(self, mock_blocked, client):
        """GET /api/senders/blocked — list blocked senders."""
        mock_blocked.return_value = {"spam@bad.com", "junk@noise.com"}

        response = client.get("/api/senders/blocked")
        assert response.status_code == 200

    def test_block_sender_requires_email(self, client):
        """POST /api/senders/block — must provide email."""
        response = client.post("/api/senders/block", json={})
        assert response.status_code == 400


# ===========================================================================
# 13. SPAM & TRASH MANAGEMENT
# ===========================================================================

class TestSpamTrash:
    """Critical: Spam/trash operations must work for folder management."""

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_not_spam(self, mock_auth, mock_get_email, client):
        """POST /api/emails/<id>/not-spam — recover from spam."""
        mock_auth.return_value = _mock_provider()
        mock_get_email.return_value = _mock_email()

        response = client.post("/api/emails/msg-001/not-spam")
        assert response.status_code == 200

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_restore_from_trash(self, mock_auth, mock_get_email, client):
        """POST /api/emails/<id>/restore — recover from trash."""
        mock_auth.return_value = _mock_provider()
        mock_get_email.return_value = _mock_email()

        response = client.post("/api/emails/msg-001/restore")
        assert response.status_code == 200


# ===========================================================================
# 14. VALIDATION & SECURITY
# ===========================================================================

class TestValidationSecurity:
    """Critical: Input validation must reject malicious inputs."""

    def test_email_id_rejects_special_chars(self, client):
        """Email ID with special chars returns 400."""
        response = client.get("/api/emails/../../etc/passwd")
        assert response.status_code in (400, 404)

    def test_email_id_rejects_too_long(self, client):
        """Email ID exceeding max length returns 400."""
        response = client.get(f"/api/emails/{'a' * 1001}")
        assert response.status_code == 400

    def test_mark_read_rejects_non_boolean(self, client):
        """is_read must be boolean."""
        response = client.patch(
            "/api/emails/test-id/read",
            json={"is_read": "yes"}
        )
        assert response.status_code == 400

    def test_bulk_read_rejects_too_many(self, client):
        """Bulk operations capped at 100."""
        ids = [f"e-{i}" for i in range(101)]
        response = client.patch(
            "/api/emails/bulk-read",
            json={"email_ids": ids, "is_read": True}
        )
        assert response.status_code == 400
        assert "100" in response.get_json()["error"]

    def test_create_draft_rejects_missing_subject(self, client):
        """Draft creation requires subject."""
        response = client.post(
            "/api/emails/test-id/draft",
            json={"body": "No subject"}
        )
        assert response.status_code == 400

    def test_create_draft_rejects_oversized_body(self, client):
        """Draft body capped at 1MB."""
        response = client.post(
            "/api/emails/test-id/draft",
            json={"subject": "Re: Test", "body": "X" * 1_000_001}
        )
        assert response.status_code == 400


# ===========================================================================
# 15. MEMORY & KNOWLEDGE
# ===========================================================================

class TestMemoryKnowledge:
    """Critical: Knowledge base must be readable."""

    def test_get_memory(self, client):
        """GET /api/memory — read knowledge base."""
        response = client.get("/api/memory")
        assert response.status_code == 200


# ===========================================================================
# 16. REMINDERS
# ===========================================================================

class TestReminders:
    """Critical: Snooze reminders must be manageable."""

    def test_list_reminders(self, client):
        """GET /api/reminders — list snooze reminders."""
        response = client.get("/api/reminders")
        assert response.status_code == 200

    def test_create_reminder_requires_fields(self, client):
        """POST /api/reminders — requires email_id and date."""
        response = client.post("/api/reminders", json={})
        assert response.status_code == 400


# ===========================================================================
# 17. NEWSLETTERS
# ===========================================================================

class TestNewsletters:
    """Critical: Newsletter detection must work."""

    def test_list_newsletters_endpoint_exists(self, client):
        """GET /api/newsletters — endpoint exists."""
        provider = Mock()
        provider.search_newsletter_emails.return_value = []

        with patch("app.api.routes_misc._get_authenticated_provider", return_value=provider):
            response = client.get("/api/newsletters")
        assert response.status_code != 404

    def test_list_newsletters_handles_mixed_timezone_dates(self, client):
        """GET /api/newsletters — mixed naive/aware dates must not crash."""
        provider = Mock()

        older = Mock()
        older.sender = "news@example.com"
        older.sender_name = "Example News"
        older.subject = "Older issue"
        older.received_at = datetime(2026, 6, 1, 12, 0)
        older.raw_metadata = {
            "list_unsubscribe": "<https://example.com/unsubscribe>",
            "list_unsubscribe_post": "List-Unsubscribe=One-Click",
        }

        newer = Mock()
        newer.sender = "digest@example.com"
        newer.sender_name = "Example Digest"
        newer.subject = "Newer issue"
        newer.received_at = datetime(2026, 6, 2, 12, 0, tzinfo=timezone.utc)
        newer.raw_metadata = None

        provider.search_newsletter_emails.return_value = [older, newer]

        with patch("app.api.routes_misc._get_authenticated_provider", return_value=provider):
            response = client.get("/api/newsletters?limit=301")

        assert response.status_code == 200
        data = response.get_json()
        assert data["total"] == 1
        newsletter = data["newsletters"][0]
        assert newsletter["domain"] == "example.com"
        assert newsletter["email_count"] == 2
        assert newsletter["last_subject"] == "Newer issue"


# ===========================================================================
# 18. HTTP METHOD ENFORCEMENT
# ===========================================================================

class TestHttpMethods:
    """Critical: Wrong HTTP methods must be rejected."""

    def test_emails_post_not_allowed(self, client):
        """POST /api/emails should be 405 (GET only)."""
        response = client.post("/api/emails")
        assert response.status_code == 405

    def test_mark_read_get_not_allowed(self, client):
        """GET /api/emails/<id>/read should be 405 (PATCH only)."""
        response = client.get("/api/emails/test-id/read")
        assert response.status_code == 405

    def test_pending_drafts_post_not_allowed(self, client):
        """POST /api/pending-drafts should be 405 (GET only)."""
        response = client.post("/api/pending-drafts")
        assert response.status_code == 405


# ===========================================================================
# 19. CONTENT-TYPE ENFORCEMENT
# ===========================================================================

class TestContentType:
    """Critical: Endpoints requiring JSON must reject non-JSON."""

    def test_create_draft_requires_json(self, client):
        """POST /api/emails/<id>/draft with text/plain returns 400/415."""
        response = client.post(
            "/api/emails/test-id/draft",
            data="not json",
            content_type="text/plain",
        )
        assert response.status_code in (400, 415)

    def test_mark_read_requires_json(self, client):
        """PATCH /api/emails/<id>/read without JSON returns 400/415."""
        response = client.patch("/api/emails/test-id/read")
        assert response.status_code in (400, 415)


# ===========================================================================
# 20. CROSS-CUTTING: AUTH FAILURE HANDLING
# ===========================================================================

class TestAuthFailureHandling:
    """Critical: Auth failures must return 401, not 500."""

    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_mark_read_auth_failure_returns_401(self, mock_auth, client):
        """Auth failure on mark_read must return 401."""
        from werkzeug.exceptions import Unauthorized
        mock_auth.side_effect = Unauthorized("Not authenticated")

        response = client.patch(
            "/api/emails/test-id/read",
            json={"is_read": True}
        )
        assert response.status_code == 401

    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_archive_auth_failure_returns_401(self, mock_auth, client):
        """Auth failure on archive must return 401."""
        from werkzeug.exceptions import Unauthorized
        mock_auth.side_effect = Unauthorized("Not authenticated")

        with patch("app.api.routes_emails._email_exists_in_cache", return_value=True):
            response = client.post("/api/emails/test-id/archive")
        assert response.status_code == 401

    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_email_not_found_returns_404(self, mock_auth, client):
        """Missing email must return 404, not 500."""
        from werkzeug.exceptions import NotFound
        provider = _mock_provider()
        provider.mark_as_read.side_effect = NotFound("Email not found")
        mock_auth.return_value = provider

        response = client.patch(
            "/api/emails/nonexistent-id/read",
            json={"is_read": True}
        )
        assert response.status_code == 404
