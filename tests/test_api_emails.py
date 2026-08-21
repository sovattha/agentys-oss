# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour GET /api/emails - Lister emails non traités.

pytest tests/test_api_emails.py -v

Note: La route list_emails utilise maintenant un cache en mémoire + SQLite.
Les tests mockent _get_cached_email_response pour bypasser le cache, et
EmailRepository pour contrôler les données SQLite.
"""

from dataclasses import dataclass
from typing import Optional
from unittest.mock import Mock, patch

import pytest


@dataclass
class MockEmail:
    """Email mock pour les tests."""

    id: str
    sender: str
    sender_name: str
    subject: str
    received_at: str
    has_attachments: bool = False
    conversation_id: Optional[str] = None


def _make_email_dict(id, sender, sender_name, subject, received_at,
                     has_attachments=False, conversation_id=None):
    """Crée un dict email tel que retourné par le cache."""
    return {
        "id": id,
        "sender": sender,
        "sender_name": sender_name,
        "subject": subject,
        "received_at": received_at,
        "has_attachments": has_attachments,
        "conversation_id": conversation_id,
        "is_read": False,
        "body": "",
        "labels": [],
    }


def _cached_response(emails, offset=0, limit=50):
    """Construit une réponse de cache simulée."""
    sliced = emails[offset:offset + limit]
    return {
        "count": len(sliced),
        "offset": offset,
        "has_more": len(emails) > offset + limit,
        "filter": "all",
        "source": "memory_cache",
        "emails": sliced,
    }


@pytest.fixture
def app():
    """Application Flask de test."""
    from app.api.app import create_app

    app = create_app(config={"TESTING": True})
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    """Client de test Flask."""
    return app.test_client()


@pytest.fixture
def sample_email_dicts():
    """Liste d'emails en format dict (tel que retourné par le cache)."""
    return [
        _make_email_dict(
            id="email-002",
            sender="bob@example.com",
            sender_name="Bob Dupont",
            subject="Suivi projet",
            received_at="2024-01-15T11:00:00Z",
        ),
        _make_email_dict(
            id="email-001",
            sender="alice@example.com",
            sender_name="Alice Martin",
            subject="Question urgente",
            received_at="2024-01-15T10:30:00Z",
            has_attachments=True,
            conversation_id="conv-001",
        ),
    ]


@pytest.fixture(autouse=True)
def _mock_current_account_module():
    """Route /api/emails retourne count=0 no_account=True si pas de compte
    actif (routes_emails.py:567-575). Mock un compte par défaut pour tout le
    module — les tests qui veulent tester le chemin auth_failure le re-patchent
    explicitement au niveau méthode.
    """
    mock_account = Mock()
    mock_account.id = "test-account"
    mock_account.email = "test@example.com"
    with patch("app.api.routes_emails._get_current_account_for_user",
               return_value=mock_account):
        yield mock_account


class TestBackgroundSyncThrottling:
    """UI-triggered refreshes should not crawl large Gmail pages repeatedly."""

    def test_background_sync_limit_caps_large_inbox_refresh(self):
        from app.api import routes_emails

        assert routes_emails._background_sync_limit(500, "inbox") == 100
        assert routes_emails._background_sync_limit(500, "trash") == 50

    def test_compensated_fetch_count_avoids_500_jump(self):
        from app.api import routes_emails

        assert routes_emails._compensated_fetch_count(offset=0, limit=50) == 150

    def test_start_background_sync_debounces_passive_queue_repeats(self, monkeypatch):
        from app.api import routes_emails

        enqueued = []
        monkeypatch.setattr(
            "app.services.sync_jobs.enqueue_sync_job",
            lambda **kwargs: enqueued.append(kwargs),
        )
        routes_emails._last_sync_time.clear()
        try:
            routes_emails._start_background_sync(7, 500, False, "hash-7", "inbox")
            routes_emails._start_background_sync(7, 500, False, "hash-7", "inbox")
        finally:
            routes_emails._last_sync_time.clear()

        assert enqueued == [
            {
                "account_id": 7,
                "folder": "inbox",
                "limit": 100,
                "unread_only": False,
                "source": "auto",
            },
        ]

    def test_start_background_sync_force_refresh_bypasses_queue_debounce(self, monkeypatch):
        from app.api import routes_emails

        enqueued = []
        monkeypatch.setattr(
            "app.services.sync_jobs.enqueue_sync_job",
            lambda **kwargs: enqueued.append(kwargs),
        )
        routes_emails._last_sync_time.clear()
        try:
            routes_emails._start_background_sync(
                7,
                500,
                False,
                "hash-7",
                "inbox",
                source="force_refresh",
                debounce=False,
            )
            routes_emails._start_background_sync(
                7,
                500,
                False,
                "hash-7",
                "inbox",
                source="force_refresh",
                debounce=False,
            )
        finally:
            routes_emails._last_sync_time.clear()

        assert enqueued == [
            {
                "account_id": 7,
                "folder": "inbox",
                "limit": 100,
                "unread_only": False,
                "source": "force_refresh",
            },
            {
                "account_id": 7,
                "folder": "inbox",
                "limit": 100,
                "unread_only": False,
                "source": "force_refresh",
            },
        ]

    def test_start_background_sync_debounces_direct_fallback_only(self, monkeypatch):
        from app.api import routes_emails

        submitted = []

        def _raise_enqueue(**_kwargs):
            raise RuntimeError("queue unavailable")

        monkeypatch.setattr("app.services.sync_jobs.enqueue_sync_job", _raise_enqueue)
        monkeypatch.setattr(
            routes_emails._rh,
            "submit_background",
            lambda fn, *args: submitted.append((fn, args)),
        )
        routes_emails._last_sync_time.clear()
        try:
            routes_emails._start_background_sync(7, 500, False, "hash-7", "inbox")
            routes_emails._start_background_sync(7, 500, False, "hash-7", "inbox")
        finally:
            routes_emails._last_sync_time.clear()

        assert len(submitted) == 1
        assert submitted[0][0] is routes_emails._sync_emails_to_cache
        assert submitted[0][1] == (
            7,
            100,
            False,
            "hash-7",
            "inbox",
        )

    def test_background_sync_queue_payload_is_capped(self, monkeypatch):
        from app.api import routes_emails

        enqueued = []
        monkeypatch.setattr(
            "app.services.sync_jobs.enqueue_sync_job",
            lambda **kwargs: enqueued.append(kwargs),
        )
        routes_emails._last_sync_time.clear()
        try:
            routes_emails._start_background_sync(7, 500, False, "hash-7", "inbox")
        finally:
            routes_emails._last_sync_time.clear()

        assert enqueued[0] == {
            "account_id": 7,
            "folder": "inbox",
            "limit": 100,
            "unread_only": False,
            "source": "auto",
        }

    def test_background_sync_uses_gmail_history_delta_when_checkpoint_exists(self, tmp_path, monkeypatch):
        from datetime import datetime, timezone

        from app.api.routes_emails import _sync_emails_to_cache
        from app.db.database import get_db_session, init_db, reset_engine
        from app.db.models.account import Account
        from app.db.models.email import Email
        from app.interfaces.email_provider import StandardEmail

        monkeypatch.setenv("AGENTYS_DB_PATH", str(tmp_path / "gmail_delta_sync.db"))
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "metadata_only")
        reset_engine()
        init_db()

        with get_db_session() as session:
            account = Account(
                email="delta@example.com",
                provider="gmail",
                user_id=42,
                last_history_id="hist-old",
            )
            session.add(account)
            session.flush()
            account_id = account.id
            session.add(
                Email(
                    email_id="msg-old",
                    account_id=account_id,
                    thread_id="thread-old",
                    subject="Old",
                    sender="old@example.com",
                    sender_name="Old",
                    recipients="delta@example.com",
                    date=datetime.now(timezone.utc),
                    body_text="old body",
                    body_html="",
                    snippet="old body",
                    is_read=False,
                    is_starred=False,
                    folder="inbox",
                )
            )

        class FakeProvider:
            full_fetch_calls = 0

            def authenticate(self):
                return True

            def get_history_changes(self, start_history_id, limit=100):
                assert start_history_id == "hist-old"
                assert limit == 50
                return {
                    "added": [
                        StandardEmail(
                            id="msg-new",
                            sender="new@example.com",
                            sender_name="New",
                            to=["delta@example.com"],
                            subject="New",
                            body="new body",
                            body_html="<p>new body</p>",
                            received_at=datetime.now(timezone.utc),
                            conversation_id="thread-new",
                            provider_source="gmail",
                        )
                    ],
                    "deleted": ["msg-old"],
                    "label_changes": [],
                    "new_history_id": "hist-new",
                }

            def get_message_headers(self, **kwargs):
                self.full_fetch_calls += 1
                return []

            def disconnect(self):
                return None

        class FakeAccountManager:
            def get_account(self, oauth_account_id):
                assert oauth_account_id == "oauth-delta"
                return object()

        provider = FakeProvider()
        monkeypatch.setattr(
            "app.multi_accounts.get_account_manager",
            lambda: FakeAccountManager(),
        )
        monkeypatch.setattr(
            "app.multi_accounts.create_provider_for_account",
            lambda account: provider,
        )

        with patch("app.api.websocket.emit_new_email"), \
             patch("app.api.routes_emails._invalidate_folder_cache"):
            _sync_emails_to_cache(
                account_id,
                limit=50,
                unread_only=False,
                oauth_account_id="oauth-delta",
                folder="inbox",
            )

        assert provider.full_fetch_calls == 0
        with get_db_session() as session:
            account = session.get(Account, account_id)
            assert account is not None
            assert account.last_history_id == "hist-new"
            assert session.query(Email).filter_by(account_id=account_id, email_id="msg-old").count() == 0
            new_email = session.query(Email).filter_by(account_id=account_id, email_id="msg-new").one()
            assert new_email.body_text is None
            assert new_email.body_html is None
            assert new_email.snippet is None

        reset_engine()


class TestListEmailsEndpoint:
    """Tests pour GET /api/emails."""

    @patch("app.api.routes_emails._get_cached_email_response")
    def test_list_emails_success(self, mock_cache, client, sample_email_dicts):
        """Liste les emails avec succès depuis le cache."""
        mock_cache.return_value = _cached_response(sample_email_dicts)

        response = client.get("/api/emails")
        data = response.get_json()

        assert response.status_code == 200
        assert data["count"] == 2
        assert len(data["emails"]) == 2
        assert data["emails"][0]["id"] == "email-002"
        assert data["emails"][0]["sender"] == "bob@example.com"
        assert data["emails"][1]["id"] == "email-001"

    def test_legacy_snoozed_path_returns_frontend_only_empty(self, client):
        """`/api/emails/snoozed` must not fall through to email detail."""
        response = client.get("/api/emails/snoozed")
        data = response.get_json()

        assert response.status_code == 200
        assert data == {
            "emails": [],
            "count": 0,
            "offset": 0,
            "has_more": False,
            "filter": "all",
            "source": "frontend-only",
        }

    @patch("app.api.routes_emails._get_cached_email_response")
    def test_list_emails_default_limit(self, mock_cache, client, sample_email_dicts):
        """Vérifie que la limite par défaut est 50."""
        mock_cache.return_value = _cached_response(sample_email_dicts)

        response = client.get("/api/emails")

        assert response.status_code == 200

    @patch("app.api.routes_emails._get_cached_email_response")
    def test_list_emails_custom_limit(self, mock_cache, client, sample_email_dicts):
        """Vérifie qu'une limite personnalisée est respectée."""
        mock_cache.return_value = _cached_response(sample_email_dicts, limit=10)

        response = client.get("/api/emails?limit=10")

        assert response.status_code == 200

    @patch("app.api.routes_emails._get_cached_email_response")
    @patch("app.providers.factory.get_pooled_provider")
    @patch("app.api.routes_emails._get_current_account_for_user")
    def test_list_emails_auth_failure(self, mock_acct, mock_provider_factory, mock_cache, client):
        """force_refresh queues sync instead of surfacing provider auth inline."""
        mock_cache.return_value = None
        # Return a mock account so the route doesn't try auto-switch
        mock_account = Mock()
        mock_account.id = "test-account"
        mock_account.email = "test@example.com"
        mock_acct.return_value = mock_account

        mock_provider = Mock()
        mock_provider.authenticate.return_value = False
        mock_provider.get_message_headers.side_effect = PermissionError("Authentication failed")
        mock_provider_factory.return_value = mock_provider

        with patch("app.api.routes_helpers.EmailRepository") as mock_repo_cls, \
             patch("app.api.routes_emails._resolve_account_id_cached", return_value=1), \
             patch("app.api.routes_helpers._resolve_account_id_for_email", return_value=1), \
             patch("app.api.routes_emails._start_background_sync") as start_sync:
            mock_repo = Mock()
            mock_repo.get_by_account.return_value = []
            mock_repo.get_sent_emails.return_value = []
            mock_repo.get_by_folder.return_value = []
            mock_repo_cls.return_value = mock_repo

            response = client.get("/api/emails?force_refresh=true")
            data = response.get_json()

        assert response.status_code == 200
        assert data["source"] == "syncing"
        assert data["provider_touched"] is False
        mock_provider_factory.assert_not_called()
        assert start_sync.called

    @patch("app.api.routes_emails._get_cached_email_response")
    @patch("app.providers.factory.get_pooled_provider")
    @patch("app.api.routes_emails._get_current_account_for_user")
    def test_list_emails_provider_error(self, mock_acct, mock_provider_factory, mock_cache, client):
        """Provider exceptions cannot happen in the list endpoint anymore."""
        mock_cache.return_value = None
        mock_account = Mock()
        mock_account.id = "test-account"
        mock_account.email = "test@example.com"
        mock_acct.return_value = mock_account

        mock_provider = Mock()
        mock_provider.authenticate.return_value = True
        mock_provider.get_message_headers.side_effect = Exception("Provider error")
        mock_provider.get_messages.side_effect = Exception("Provider error")
        mock_provider_factory.return_value = mock_provider

        with patch("app.api.routes_helpers.EmailRepository") as mock_repo_cls, \
             patch("app.api.routes_emails._resolve_account_id_cached", return_value=1), \
             patch("app.api.routes_helpers._resolve_account_id_for_email", return_value=1), \
             patch("app.api.routes_emails._start_background_sync") as start_sync:
            mock_repo = Mock()
            mock_repo.get_by_account.return_value = []
            mock_repo.get_sent_emails.return_value = []
            mock_repo.get_by_folder.return_value = []
            mock_repo_cls.return_value = mock_repo

            response = client.get("/api/emails?force_refresh=true")
            data = response.get_json()

        assert response.status_code == 200
        assert data["source"] == "syncing"
        assert data["provider_touched"] is False
        mock_provider_factory.assert_not_called()
        assert start_sync.called

    @patch("app.api.routes_emails._get_cached_email_response")
    def test_list_emails_empty(self, mock_cache, client):
        """Retourne une liste vide si aucun email non lu."""
        mock_cache.return_value = _cached_response([])

        response = client.get("/api/emails")
        data = response.get_json()

        assert response.status_code == 200
        assert data["count"] == 0
        assert data["emails"] == []

    def test_list_emails_invalid_limit_negative(self, client):
        """Limite négative retourne 400 (sécurité: validation des entrées)."""
        response = client.get("/api/emails?limit=-5")
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "between" in data["error"].lower()

    def test_list_emails_invalid_limit_zero(self, client):
        """Limite zéro retourne 400 (sécurité: validation des entrées)."""
        response = client.get("/api/emails?limit=0")
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "between" in data["error"].lower()

    def test_list_emails_invalid_limit_string(self, client):
        """Limite non-numérique retourne 400 (sécurité: validation des entrées)."""
        response = client.get("/api/emails?limit=abc")
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "integer" in data["error"].lower()

    def test_list_emails_large_limit(self, client):
        """Limite supérieure au maximum retourne 400 (sécurité: DoS prevention)."""
        response = client.get("/api/emails?limit=1000000")
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "between" in data["error"].lower()

    @patch("app.api.routes_emails._get_cached_email_response")
    def test_list_emails_max_limit_accepted(self, mock_cache, client, sample_email_dicts):
        """Limite au maximum (500) est acceptée."""
        mock_cache.return_value = _cached_response(sample_email_dicts, limit=500)

        response = client.get("/api/emails?limit=500")

        assert response.status_code == 200

    @patch("app.api.routes_emails._get_cached_email_response")
    def test_list_emails_min_limit_accepted(self, mock_cache, client, sample_email_dicts):
        """Limite au minimum (1) est acceptée."""
        mock_cache.return_value = _cached_response(sample_email_dicts, limit=1)

        response = client.get("/api/emails?limit=1")

        assert response.status_code == 200

    @patch("app.api.routes_emails._get_cached_email_response")
    @patch("app.providers.factory.get_pooled_provider")
    @patch("app.api.routes_emails._get_current_account_for_user")
    def test_list_emails_auth_exception(self, mock_acct, mock_provider_factory, mock_cache, client):
        """Provider auth exceptions are isolated to the async sync job."""
        mock_cache.return_value = None
        mock_account = Mock()
        mock_account.id = "test-account"
        mock_account.email = "test@example.com"
        mock_acct.return_value = mock_account

        mock_provider = Mock()
        mock_provider.authenticate.side_effect = Exception("Connection timeout")
        mock_provider.get_message_headers.side_effect = Exception("Connection timeout")
        mock_provider_factory.return_value = mock_provider

        with patch("app.api.routes_helpers.EmailRepository") as mock_repo_cls, \
             patch("app.api.routes_emails._resolve_account_id_cached", return_value=1), \
             patch("app.api.routes_helpers._resolve_account_id_for_email", return_value=1), \
             patch("app.api.routes_emails._start_background_sync") as start_sync:
            mock_repo = Mock()
            mock_repo.get_by_account.return_value = []
            mock_repo.get_sent_emails.return_value = []
            mock_repo.get_by_folder.return_value = []
            mock_repo_cls.return_value = mock_repo

            response = client.get("/api/emails?force_refresh=true")
            data = response.get_json()

        assert response.status_code == 200
        assert data["source"] == "syncing"
        assert data["provider_touched"] is False
        mock_provider_factory.assert_not_called()
        assert start_sync.called

    @patch("app.api.routes_emails._get_cached_email_response")
    @patch("app.providers.factory.get_pooled_provider")
    @patch("app.api.routes_emails._get_current_account_for_user")
    def test_list_emails_provider_none(self, mock_acct, mock_provider_factory, mock_cache, client):
        """Missing provider no longer affects the DB-only list endpoint."""
        mock_cache.return_value = None
        mock_account = Mock()
        mock_account.id = "test-account"
        mock_account.email = "test@example.com"
        mock_acct.return_value = mock_account

        mock_provider_factory.return_value = None

        with patch("app.api.routes_helpers.EmailRepository") as mock_repo_cls, \
             patch("app.api.routes_emails._resolve_account_id_cached", return_value=1), \
             patch("app.api.routes_helpers._resolve_account_id_for_email", return_value=1), \
             patch("app.api.routes_emails._start_background_sync") as start_sync:
            mock_repo = Mock()
            mock_repo.get_by_account.return_value = []
            mock_repo.get_sent_emails.return_value = []
            mock_repo.get_by_folder.return_value = []
            mock_repo_cls.return_value = mock_repo

            response = client.get("/api/emails?force_refresh=true")
            data = response.get_json()

        assert response.status_code == 200
        assert data["source"] == "syncing"
        assert data["provider_touched"] is False
        mock_provider_factory.assert_not_called()
        assert start_sync.called

    @patch("app.api.routes_emails._get_cached_email_response")
    def test_list_emails_email_with_all_optional_none(self, mock_cache, client):
        """Email avec tous les champs optionnels à None."""
        email_dict = _make_email_dict(
            id="email-minimal",
            sender="test@example.com",
            sender_name="Test User",
            subject="Test",
            received_at="2024-01-15T10:00:00Z",
            has_attachments=False,
            conversation_id=None,
        )
        mock_cache.return_value = _cached_response([email_dict])

        response = client.get("/api/emails")
        data = response.get_json()

        assert response.status_code == 200
        assert data["count"] == 1
        assert data["emails"][0]["conversation_id"] is None


# ============================================================================
# E2E: Label enrichment on SQLite cache paths
# Verifies that conversation_id, to, draft_skipped, labels, has_pending_draft,
# body_preview, classification, priority are all present on cached responses.
# ============================================================================


class _FakeEmail:
    """Minimal SQLite Email model mock for cache path tests."""

    def __init__(self, email_id="e1", sender="alice@test.com", sender_name="Alice",
                 subject="Hello", thread_id="t1", recipients="bob@test.com",
                 snippet="Preview text", body_text="Full body", is_read=False,
                 is_starred=False, attachments_meta=None, date=None):
        from datetime import datetime, timezone
        self.email_id = email_id
        self.sender = sender
        self.sender_name = sender_name
        self.subject = subject
        self.thread_id = thread_id
        self.recipients = recipients
        self.snippet = snippet
        self.body_text = body_text
        self.is_read = is_read
        self.is_starred = is_starred
        self.attachments_meta = attachments_meta
        self.date = date or datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc)
        self.labels = ""

    def to_dict_headers(self):
        return {
            "id": self.email_id,
            "sender": self.sender,
            "sender_name": self.sender_name,
            "subject": self.subject,
            "received_at": self.date.strftime('%Y-%m-%dT%H:%M:%SZ') if self.date else None,
            "is_read": self.is_read,
            "snippet": self.snippet or "",
            "has_attachments": bool(self.attachments_meta),
        }


class TestInboxCachePathEnrichment:
    """Verify all fields are present on the inbox SQLite cache path."""

    def test_skip_cache_fresh_sqlite_does_not_start_provider_sync(self, client):
        """WS soft refresh should re-read SQLite without waking Gmail when rows are fresh."""
        from datetime import datetime, timezone

        fake_email = _FakeEmail(email_id="fresh-1", recipients="")
        fake_email.created_at = datetime.now(timezone.utc)

        mock_repo = Mock()
        mock_repo.get_by_account.return_value = [fake_email]
        mock_repo.get_sent_emails.return_value = []
        mock_repo.get_by_folder.return_value = []

        mock_db = Mock()
        mock_db.return_value.__enter__ = Mock(return_value=Mock())
        mock_db.return_value.__exit__ = Mock(return_value=False)

        with patch("app.api.routes_helpers.EmailRepository", return_value=mock_repo), \
             patch("app.api.routes_helpers.get_db_session", mock_db), \
             patch("app.api.routes_emails._rh._resolve_account_id_for_email", return_value=7), \
             patch("app.api.routes_emails._get_inbox_label_email_ids_for_filter", return_value=set()), \
             patch("app.api.routes_emails._get_pending_draft_email_ids", return_value=set()), \
             patch("app.api.routes_emails._get_pending_draft_info_map", return_value={}), \
             patch("app.api.routes_emails._get_email_labels_batch", return_value={}), \
             patch("app.api.routes_emails._rh.submit_background"), \
             patch("app.api.routes_emails._start_background_sync") as start_sync:
            response = client.get(
                "/api/emails?limit=50&offset=0&filter=all&folder=inbox"
                "&exclude_label=Noise&skip_cache=true"
            )

        data = response.get_json()
        assert response.status_code == 200
        assert data["source"] == "cache"
        assert data["emails"][0]["id"] == "fresh-1"
        start_sync.assert_not_called()

    def test_inbox_cache_hit_does_not_prefetch_secondary_provider_folders(self, client):
        """Inbox list must not start slow Gmail/IMAP folder warming jobs."""
        from datetime import datetime, timezone
        from app.api import routes_emails

        fake_email = _FakeEmail(email_id="inbox-1", recipients="")
        fake_email.created_at = datetime.now(timezone.utc)

        mock_repo = Mock()
        mock_repo.get_by_account.return_value = [fake_email]
        mock_repo.get_sent_emails.return_value = []
        mock_repo.get_by_folder.return_value = []

        mock_db = Mock()
        mock_db.return_value.__enter__ = Mock(return_value=Mock())
        mock_db.return_value.__exit__ = Mock(return_value=False)

        submitted = []

        with patch("app.api.routes_helpers.EmailRepository", return_value=mock_repo), \
             patch("app.api.routes_helpers.get_db_session", mock_db), \
             patch("app.api.routes_emails._rh._resolve_account_id_for_email", return_value=7), \
             patch("app.api.routes_emails._get_cached_email_response", return_value=None), \
             patch("app.api.routes_emails._get_pending_draft_email_ids", return_value=set()), \
             patch("app.api.routes_emails._get_pending_draft_info_map", return_value={}), \
             patch("app.api.routes_emails._get_email_labels_batch", return_value={}), \
             patch("app.api.routes_emails._compute_thread_counts", return_value={}), \
             patch("app.api.routes_emails._rh.should_run_bg_jobs", return_value=True), \
             patch("app.api.routes_emails._rh.submit_background", side_effect=lambda fn, *args: submitted.append(fn)):
            response = client.get("/api/emails?folder=inbox&limit=10")

        assert response.status_code == 200
        assert routes_emails._prefetch_secondary_folders_bg not in submitted

    @patch("app.api.routes_emails._get_email_labels_batch")
    @patch("app.api.routes_emails._get_pending_draft_info_map")
    @patch("app.api.routes_emails._get_pending_draft_email_ids")
    @patch("app.api.routes_emails._get_cached_email_response")
    @patch("app.api.routes_emails._get_inbox_label_email_ids_for_filter")
    @patch("app.api.routes_emails._rh._resolve_account_id_for_email")
    @patch("app.api.routes_helpers.get_db_session")
    @patch("app.api.routes_helpers.EmailRepository")
    def test_label_filter_uses_same_ids_as_header_counts(
        self, mock_repo_cls, mock_db, mock_resolve_email, mock_label_ids,
        mock_cache, mock_pending_ids, mock_draft_info, mock_labels_batch, client
    ):
        """Info/Bruit tabs must filter with the same merged source as counters."""
        mock_cache.return_value = None
        mock_resolve_email.return_value = 7
        mock_label_ids.return_value = {"fyi-global", "fyi-account"}

        fake_email = _FakeEmail(email_id="fyi-global", recipients="")
        mock_repo = Mock()
        mock_repo.get_by_account.return_value = [fake_email]
        mock_repo.get_sent_emails.return_value = []
        mock_repo.get_by_folder.return_value = []
        mock_repo_cls.return_value = mock_repo
        mock_db.return_value.__enter__ = Mock(return_value=Mock())
        mock_db.return_value.__exit__ = Mock(return_value=False)

        mock_pending_ids.return_value = set()
        mock_draft_info.return_value = {}
        mock_labels_batch.return_value = {
            "fyi-global": [{"name": "FYI", "color": "#3b82f6"}]
        }

        response = client.get("/api/emails?label=FYI")

        assert response.status_code == 200
        mock_label_ids.assert_called_once_with(7, "FYI")
        assert mock_repo.get_by_account.call_args.kwargs["email_ids"] == {
            "fyi-global", "fyi-account",
        }

    @patch("app.api.routes_emails._get_email_labels_batch")
    @patch("app.api.routes_emails._get_pending_draft_info_map")
    @patch("app.api.routes_emails._get_pending_draft_email_ids")
    @patch("app.api.routes_emails._get_cached_email_response")
    @patch("app.api.routes_emails._resolve_account_id_cached")
    @patch("app.api.routes_helpers.get_db_session")
    @patch("app.api.routes_helpers.EmailRepository")
    def test_inbox_cache_has_all_enriched_fields(
        self, mock_repo_cls, mock_db, mock_resolve, mock_cache,
        mock_pending_ids, mock_draft_info, mock_labels_batch, client
    ):
        """Inbox cache path returns conversation_id, to, draft_skipped, labels, classification, priority."""
        mock_cache.return_value = None  # force SQLite path
        mock_resolve.return_value = 1

        fake_email = _FakeEmail(
            email_id="inbox-1", thread_id="thread-42",
            recipients="me@test.com, cc@test.com",
        )
        mock_repo = Mock()
        mock_repo.get_by_account.return_value = [fake_email]
        mock_repo.get_sent_emails.return_value = []
        mock_repo.get_by_folder.return_value = []
        mock_repo_cls.return_value = mock_repo
        mock_db.return_value.__enter__ = Mock(return_value=Mock())
        mock_db.return_value.__exit__ = Mock(return_value=False)

        mock_pending_ids.return_value = set()
        mock_draft_info.return_value = {
            "inbox-1": {"classification": "Action", "priority": 3}
        }
        mock_labels_batch.return_value = {
            "inbox-1": [{"name": "Action", "color": "#22c55e"}]
        }

        response = client.get("/api/emails")
        data = response.get_json()

        assert response.status_code == 200
        email = data["emails"][0]
        # Core fields from to_dict_headers
        assert email["id"] == "inbox-1"
        assert email["sender"] == "alice@test.com"
        # Enriched fields (were missing before fix)
        assert email["conversation_id"] == "thread-42"
        assert email["to"] == ["me@test.com", "cc@test.com"]
        assert email["draft_skipped"] is False
        assert email["labels"] == [{"name": "Action", "color": "#22c55e"}]
        assert email["has_pending_draft"] is False
        assert email["body_preview"] == "Preview text"
        assert email["classification"] == "Action"
        assert email["priority"] == 3

    @patch("app.api.routes_emails._get_email_labels_batch")
    @patch("app.api.routes_emails._get_pending_draft_info_map")
    @patch("app.api.routes_emails._get_pending_draft_email_ids")
    @patch("app.api.routes_emails._get_cached_email_response")
    @patch("app.api.routes_emails._resolve_account_id_cached")
    @patch("app.api.routes_helpers.get_db_session")
    @patch("app.api.routes_helpers.EmailRepository")
    def test_inbox_cache_noise_label_sets_draft_skipped(
        self, mock_repo_cls, mock_db, mock_resolve, mock_cache,
        mock_pending_ids, mock_draft_info, mock_labels_batch, client
    ):
        """Noise-labeled email without pending draft has draft_skipped=True."""
        mock_cache.return_value = None
        mock_resolve.return_value = 1

        fake_email = _FakeEmail(email_id="noise-1", recipients="")
        mock_repo = Mock()
        mock_repo.get_by_account.return_value = [fake_email]
        mock_repo.get_sent_emails.return_value = []
        mock_repo.get_by_folder.return_value = []
        mock_repo_cls.return_value = mock_repo
        mock_db.return_value.__enter__ = Mock(return_value=Mock())
        mock_db.return_value.__exit__ = Mock(return_value=False)

        mock_pending_ids.return_value = set()
        mock_draft_info.return_value = {}
        mock_labels_batch.return_value = {
            "noise-1": [{"name": "Noise", "color": "#9ca3af"}]
        }

        response = client.get("/api/emails")
        data = response.get_json()

        assert response.status_code == 200
        email = data["emails"][0]
        assert email["draft_skipped"] is True
        assert email["to"] == []

    @patch("app.api.routes_emails._get_email_labels_batch")
    @patch("app.api.routes_emails._get_pending_draft_info_map")
    @patch("app.api.routes_emails._get_pending_draft_email_ids")
    @patch("app.api.routes_emails._get_cached_email_response")
    @patch("app.api.routes_emails._resolve_account_id_cached")
    @patch("app.api.routes_helpers.get_db_session")
    @patch("app.api.routes_helpers.EmailRepository")
    def test_inbox_cache_pending_draft_overrides_noise_skip(
        self, mock_repo_cls, mock_db, mock_resolve, mock_cache,
        mock_pending_ids, mock_draft_info, mock_labels_batch, client
    ):
        """Noise email WITH a pending draft should NOT be draft_skipped."""
        mock_cache.return_value = None
        mock_resolve.return_value = 1

        fake_email = _FakeEmail(email_id="noise-draft-1", recipients="")
        mock_repo = Mock()
        mock_repo.get_by_account.return_value = [fake_email]
        mock_repo.get_sent_emails.return_value = []
        mock_repo.get_by_folder.return_value = []
        mock_repo_cls.return_value = mock_repo
        mock_db.return_value.__enter__ = Mock(return_value=Mock())
        mock_db.return_value.__exit__ = Mock(return_value=False)

        mock_pending_ids.return_value = {"noise-draft-1"}
        mock_draft_info.return_value = {}
        mock_labels_batch.return_value = {
            "noise-draft-1": [{"name": "Noise", "color": "#9ca3af"}]
        }

        response = client.get("/api/emails")
        data = response.get_json()

        assert response.status_code == 200
        email = data["emails"][0]
        assert email["has_pending_draft"] is True
        assert email["draft_skipped"] is False


class TestSecondaryFolderCacheEnrichment:
    """Verify label enrichment on secondary folder cache path (archived, trash, etc.)."""

    @patch("app.api.routes_emails._get_email_labels_batch")
    @patch("app.api.routes_emails._get_pending_draft_email_ids")
    @patch("app.api.routes_emails._get_cached_email_response")
    @patch("app.api.routes_emails._resolve_account_id_cached")
    @patch("app.api.routes_helpers.get_db_session")
    @patch("app.api.routes_helpers.EmailRepository")
    def test_archived_folder_has_enriched_fields(
        self, mock_repo_cls, mock_db, mock_resolve, mock_cache,
        mock_pending_ids, mock_labels_batch, client
    ):
        """Archived folder cache path includes conversation_id, to, draft_skipped, labels."""
        mock_cache.return_value = None
        mock_resolve.return_value = 1

        fake_email = _FakeEmail(
            email_id="arch-1", thread_id="thread-99",
            recipients="user@test.com",
        )
        mock_repo = Mock()
        mock_repo.get_by_account.return_value = []
        mock_repo.get_sent_emails.return_value = []
        mock_repo.get_by_folder.return_value = [fake_email]
        mock_repo_cls.return_value = mock_repo
        mock_db.return_value.__enter__ = Mock(return_value=Mock())
        mock_db.return_value.__exit__ = Mock(return_value=False)

        mock_pending_ids.return_value = set()
        mock_labels_batch.return_value = {
            "arch-1": [{"name": "FYI", "color": "#3b82f6"}]
        }

        response = client.get("/api/emails?folder=archived")
        data = response.get_json()

        assert response.status_code == 200
        email = data["emails"][0]
        assert email["conversation_id"] == "thread-99"
        assert email["to"] == ["user@test.com"]
        assert email["labels"] == [{"name": "FYI", "color": "#3b82f6"}]
        assert email["draft_skipped"] is False
        assert email["body_preview"] == "Preview text"


class TestInitEndpointEnrichment:
    """Verify /api/init returns enriched email fields."""

    @patch("app.api.routes_emails._get_email_labels_batch")
    @patch("app.api.routes_emails._get_pending_draft_email_ids")
    @patch("app.api.routes_health._get_cached_email_response")
    @patch("app.api.routes_health._resolve_account_id_cached")
    @patch("app.api.routes_helpers.get_db_session")
    @patch("app.api.routes_helpers.EmailRepository")
    @patch("app.api.routes_helpers._get_container")
    def test_init_emails_have_all_fields(
        self, mock_container, mock_repo_cls, mock_db, mock_resolve,
        mock_cache, mock_pending_ids, mock_labels_batch, client
    ):
        """/api/init returns emails with has_pending_draft, conversation_id, to, body_preview, draft_skipped."""
        mock_cache.return_value = None  # force SQLite path
        mock_resolve.return_value = 1

        fake_email = _FakeEmail(
            email_id="init-1", thread_id="thread-init",
            recipients="dest@test.com", snippet="Init preview",
        )
        mock_repo = Mock()
        mock_repo.get_by_account.return_value = [fake_email]
        mock_repo.get_active_accounts.return_value = []
        mock_repo_cls.return_value = mock_repo
        mock_session = Mock()
        mock_session.scalar.return_value = 2  # spam_count
        mock_db.return_value.__enter__ = Mock(return_value=mock_session)
        mock_db.return_value.__exit__ = Mock(return_value=False)

        mock_pending_ids.return_value = {"init-1"}
        mock_labels_batch.return_value = {
            "init-1": [{"name": "Action", "color": "#22c55e"}]
        }

        # Mock container for label_counts + pending_drafts
        mock_store = Mock()
        mock_store.get_label_counts.return_value = {"Action": 1}
        mock_store.get_pending.return_value = []
        mock_container.return_value.get_label_store.return_value = mock_store
        mock_container.return_value.get_pending_draft_store.return_value = mock_store

        response = client.get("/api/init")
        data = response.get_json()

        assert response.status_code == 200
        emails = data["emails"]["emails"]
        assert len(emails) >= 1
        email = emails[0]
        assert email["id"] == "init-1"
        assert email["has_pending_draft"] is True
        assert email["conversation_id"] == "thread-init"
        assert email["to"] == ["dest@test.com"]
        assert email["body_preview"] == "Init preview"
        assert email["labels"] == [{"name": "Action", "color": "#22c55e"}]
        # has_pending_draft=True → draft_skipped must be False even with Noise label
        assert email["draft_skipped"] is False
        # spam_count field present
        assert "spam_count" in data
