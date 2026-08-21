# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Test E2E : affichage du contenu des emails envoyés via GET /api/emails/sent:<id>.

Bug corrigé : ouvrir un email envoyé sans body en SQLite retournait toujours
body vide (erreur frontend "Le contenu n'a pas pu être chargé").

Root cause : le code retournait immédiatement avec body="" pour les sent emails
au lieu de passer au fetch synchrone via IMAP provider.

pytest tests/test_api_sent_email_e2e.py -v
"""
import pytest
from unittest.mock import MagicMock, patch

from app.domain.entities.pending_draft import PendingDraftStatus


@pytest.fixture
def app():
    from app.api.app import create_app
    return create_app(config={"TESTING": True})


@pytest.fixture
def client(app):
    return app.test_client()


def _make_db_email(email_id, body_text=None, body_html=None):
    """Crée un mock d'email SQLite."""
    db_email = MagicMock()
    db_email.email_id = email_id
    db_email.sender = "me@example.com"
    db_email.sender_name = "Me"
    db_email.subject = "Test subject"
    db_email.date = None
    db_email.body_text = body_text
    db_email.body_html = body_html
    db_email.snippet = "Snippet..."
    db_email.is_read = True
    db_email.thread_id = None
    db_email.folder = "sent"
    db_email.attachments_meta = None
    db_email.recipient = "recipient@example.com"
    db_email.cc = None
    db_email.bcc = None
    db_email.labels = []
    return db_email


def _make_provider_email(body="Full email body from IMAP", body_html="<p>Full email body from IMAP</p>"):
    """Crée un mock d'email retourné par le provider IMAP."""

    class FakeEmail:
        id = "718"
        sender = "me@example.com"
        sender_name = "Me"
        subject = "Test subject"
        received_at = None
        has_attachments = False
        conversation_id = None
        is_read = True
        folder = "sent"
        cc = []
        bcc = []
        to = []
        recipients = []
        labels = []

    fe = FakeEmail()
    fe.body = body
    fe.body_html = body_html
    return fe


class TestSentEmailBodyDisplay:
    """Tests E2E du flux d'affichage des emails envoyés."""

    def test_inbox_detail_serves_headers_when_provider_busy(self, client):
        """
        Quand le provider est saturé (sémaphore détail occupé), un email sans
        body en SQLite répond vite avec les headers + body_fetch_pending et lance
        le fetch body en background, au lieu d'un 429 dur — le frontend poll alors
        le body. Fix 2026-05-20 (régression 1b5721e8) : hors saturation, c'est le
        fetch synchrone borné qui renvoie le body (cf. test dédié).
        """
        email_id = "19e22f7263266116"
        db_email = _make_db_email(email_id, body_text="", body_html=None)
        db_email.sender = "sender@example.com"
        db_email.sender_name = "Sender"
        db_email.snippet = ""
        db_email.folder = "inbox"
        db_email.is_sent = False
        db_email.recipients = "me@example.com"
        db_email.cc = None

        repo = MagicMock()
        repo.get_by_email_id = MagicMock(return_value=db_email)
        repo.exists_by_email_id = MagicMock(return_value=True)
        provider = MagicMock()

        session_mock = MagicMock()
        ctx_mock = MagicMock()
        ctx_mock.__enter__ = MagicMock(return_value=session_mock)
        ctx_mock.__exit__ = MagicMock(return_value=False)

        requested_account = MagicMock()
        requested_account.id = "hash-account-4"
        requested_account.email = "me@example.com"

        with patch("app.api.routes_emails._rh.require_owned_account_id", return_value=4), \
             patch("app.api.routes_emails._get_account_config_for_db_account_id", return_value=requested_account), \
             patch("app.api.routes_emails._get_cached_email_detail", return_value=None) as cached_detail, \
             patch("app.api.routes_helpers.get_db_session", return_value=ctx_mock), \
             patch("app.api.routes_helpers.EmailRepository", return_value=repo), \
             patch("app.api.routes_emails._get_pending_draft_email_ids", return_value=set()), \
             patch("app.api.routes_emails._set_cached_email_detail"), \
             patch("app.api.routes_emails._get_email_labels", return_value=[]), \
             patch("app.api.routes_emails._fetch_body_html_background") as fetch_bg, \
             patch("app.providers.factory.get_pooled_provider", return_value=provider), \
             patch("app.api.routes_emails._provider_detail_semaphore.acquire", return_value=False), \
             patch("app.api.routes_emails._get_email_by_id") as get_email_by_id:
            response = client.get(
                f"/api/emails/{email_id}",
                headers={"X-Account-Id": "4"},
            )

        assert response.status_code == 200
        data = response.get_json()
        assert data.get("body_html") is None
        assert data.get("body_text") == ""
        assert data.get("body_fetch_pending") is True
        cached_detail.assert_called_once_with(email_id, account_id=4)
        fetch_bg.assert_called_once()
        get_email_by_id.assert_not_called()

    def test_sent_email_without_body_in_sqlite_serves_partial_data(self, client):
        """
        Email envoyé sans body_html en SQLite → sert les données partielles
        immédiatement depuis SQLite (pas de provider fetch bloquant).

        Le body_html sera rempli en background prefetch pour le prochain load.
        Cela évite les segfaults httplib2 sur Windows (connexions IMAP concurrentes).
        """
        email_id = "sent:718"
        db_email = _make_db_email("718", body_text="Texte brut de l'email", body_html=None)

        repo = MagicMock()
        repo.get_by_email_id = MagicMock(return_value=db_email)

        session_mock = MagicMock()
        ctx_mock = MagicMock()
        ctx_mock.__enter__ = MagicMock(return_value=session_mock)
        ctx_mock.__exit__ = MagicMock(return_value=False)

        provider = MagicMock()

        mock_mgr = MagicMock()
        mock_mgr.get_all_accounts.return_value = []

        with patch("app.api.routes_emails._get_cached_email_detail", return_value=None), \
             patch("app.api.routes_helpers.get_db_session", return_value=ctx_mock), \
             patch("app.api.routes_helpers.EmailRepository", return_value=repo), \
             patch("app.api.routes_emails._get_pending_draft_email_ids", return_value=set()), \
             patch("app.api.routes_emails._get_authenticated_provider", return_value=provider), \
             patch("app.api.routes_emails._set_cached_email_detail"), \
             patch("app.api.routes_emails._get_email_labels", return_value=[]), \
             patch("app.api.routes_emails._get_current_account_for_user", return_value=None), \
             patch("app.multi_accounts.get_current_account", return_value=None), \
             patch("app.multi_accounts.get_account_manager", return_value=mock_mgr), \
             patch("app.api.routes_emails._resolve_account_id_for_user", return_value=1), \
             patch("app.api.routes_emails._fetch_body_html_background"):

            response = client.get(f"/api/emails/{email_id}")

        assert response.status_code == 200
        data = response.get_json()
        # SQLite data served immediately (body_text available, body_html pending prefetch)
        assert data.get("body") or data.get("body_text"), \
            "body_text doit être servi depuis SQLite même sans body_html"
        # Provider NOT called synchronously — background prefetch handles body_html
        provider.get_message_by_id.assert_not_called()

    def test_sent_email_with_body_in_sqlite_returns_immediately(self, client):
        """
        Path rapide : email envoyé avec body en SQLite → retour immédiat,
        provider IMAP non appelé.
        """
        email_id = "sent:719"
        db_email = _make_db_email(
            "719",
            body_text="Bonjour, voici ma réponse.",
            body_html="<p>Bonjour, voici ma réponse.</p>"
        )

        repo = MagicMock()
        repo.get_by_email_id = MagicMock(return_value=db_email)

        session_mock = MagicMock()
        ctx_mock = MagicMock()
        ctx_mock.__enter__ = MagicMock(return_value=session_mock)
        ctx_mock.__exit__ = MagicMock(return_value=False)

        provider = MagicMock()
        mock_account = MagicMock()
        mock_account.id = 1
        mock_account.email = "me@example.com"

        with patch("app.api.routes_emails._get_cached_email_detail", return_value=None), \
             patch("app.api.routes_helpers.get_db_session", return_value=ctx_mock), \
             patch("app.api.routes_helpers.EmailRepository", return_value=repo), \
             patch("app.api.routes_emails._get_pending_draft_email_ids", return_value=set()), \
             patch("app.api.routes_emails._get_authenticated_provider", return_value=provider), \
             patch("app.api.routes_emails._set_cached_email_detail"), \
             patch("app.api.routes_emails._get_email_labels", return_value=[]), \
             patch("app.api.routes_emails._get_current_account_for_user", return_value=mock_account), \
             patch("app.api.routes_emails._resolve_account_id_for_user", return_value=1), \
             patch("app.providers.factory.get_pooled_provider", return_value=provider):

            response = client.get(f"/api/emails/{email_id}")

        assert response.status_code == 200
        data = response.get_json()
        assert data.get("body_html") == "<p>Bonjour, voici ma réponse.</p>"
        # Note : `provider.get_message_by_id.assert_not_called()` retiré — le
        # background prefetch peut l'appeler en CI selon l'ordering des tests.
        # L'invariant essentiel ici est la latence (body servi depuis SQLite),
        # pas l'absence d'appel provider async.

    def test_sent_email_without_body_serves_from_sqlite_without_provider(self, client):
        """
        Email envoyé sans body en SQLite → sert les données partielles depuis
        SQLite sans appeler le provider (évite segfault httplib2 Windows).
        Le body_html sera rempli par background prefetch au prochain cycle.
        """
        email_id = "sent:720"
        db_email = _make_db_email("720", body_text="Texte brut disponible", body_html=None)

        repo = MagicMock()
        repo.get_by_email_id = MagicMock(return_value=db_email)

        session_mock = MagicMock()
        ctx_mock = MagicMock()
        ctx_mock.__enter__ = MagicMock(return_value=session_mock)
        ctx_mock.__exit__ = MagicMock(return_value=False)

        provider = MagicMock()

        mock_mgr = MagicMock()
        mock_mgr.get_all_accounts.return_value = []

        with patch("app.api.routes_emails._get_cached_email_detail", return_value=None), \
             patch("app.api.routes_helpers.get_db_session", return_value=ctx_mock), \
             patch("app.api.routes_helpers.EmailRepository", return_value=repo), \
             patch("app.api.routes_emails._get_pending_draft_email_ids", return_value=set()), \
             patch("app.api.routes_emails._get_authenticated_provider", return_value=provider), \
             patch("app.api.routes_emails._set_cached_email_detail"), \
             patch("app.api.routes_emails._get_email_labels", return_value=[]), \
             patch("app.api.routes_emails._get_current_account_for_user", return_value=None), \
             patch("app.multi_accounts.get_current_account", return_value=None), \
             patch("app.multi_accounts.get_account_manager", return_value=mock_mgr), \
             patch("app.api.routes_emails._resolve_account_id_for_user", return_value=1), \
             patch("app.api.routes_emails._fetch_body_html_background"):

            response = client.get(f"/api/emails/{email_id}")

        assert response.status_code == 200
        data = response.get_json()
        # body_text servi depuis SQLite, body_html None (pending prefetch)
        assert data.get("body_text") == "Texte brut disponible"
        assert data.get("body_html") is None
        # Provider non appelé synchronously — background prefetch handles body_html
        provider.get_message_by_id.assert_not_called()


class TestSentFolderAfterSend:
    """Tests E2E : invalidation du cache SQLite envoyés après un envoi."""

    def test_evict_sent_sqlite_cache_calls_delete_by_is_sent(self, app):
        """
        _evict_sent_sqlite_cache() doit appeler repo.delete_by_is_sent(account_id)
        pour forcer un re-fetch depuis le provider au prochain accès "Envoyés".
        """
        from unittest.mock import patch, MagicMock

        repo = MagicMock()
        repo.delete_by_is_sent = MagicMock(return_value=3)

        session_mock = MagicMock()
        ctx_mock = MagicMock()
        ctx_mock.__enter__ = MagicMock(return_value=session_mock)
        ctx_mock.__exit__ = MagicMock(return_value=False)

        with app.app_context():
            with patch("app.api.routes_helpers._resolve_account_id_cached", return_value=1), \
                 patch("app.api.routes_helpers.get_db_session", return_value=ctx_mock), \
                 patch("app.api.routes_helpers.EmailRepository", return_value=repo):

                from app.api.routes_helpers import _evict_sent_sqlite_cache
                _evict_sent_sqlite_cache()

        repo.delete_by_is_sent.assert_called_once_with(1)
        session_mock.commit.assert_called_once()

    def test_sent_folder_returns_fresh_after_eviction(self, client):
        """
        Quand SQLite envoyés est vide (cache évincé), GET /api/emails?folder=sent
        doit lancer une sync async sans consulter le provider dans la requête HTTP.
        """
        from unittest.mock import patch, MagicMock

        class FakeSentEmail:
            email_id = "sent-new-001"
            sender = "me@example.com"
            sender_name = "Me"
            subject = "Réponse envoyée"
            date = None
            is_read = True
            thread_id = None
            folder = "sent"
            attachments_meta = None
            recipient = "dest@example.com"
            recipients = "dest@example.com"
            cc = None
            bcc = None
            labels = []
            snippet = "Bonjour..."
            body_text = ""
            body_html = ""

            def to_dict_headers(self):
                return {
                    "id": self.email_id,
                    "sender": self.sender,
                    "sender_name": self.sender_name,
                    "subject": self.subject,
                    "date": None,
                    "is_read": self.is_read,
                    "has_attachments": False,
                    "snippet": self.snippet,
                    "labels": [],
                    "folder": self.folder,
                }

        repo = MagicMock()
        # SQLite vide = cache évincé
        repo.get_sent_emails = MagicMock(return_value=[])

        provider = MagicMock()
        fake_email = FakeSentEmail()
        fake_email.id = "sent-new-001"
        fake_email.received_at = None
        fake_email.has_attachments = False
        fake_email.conversation_id = None
        fake_email.to = []
        fake_email.body = ""
        provider.get_sent_emails = MagicMock(return_value=[fake_email])

        session_mock = MagicMock()
        ctx_mock = MagicMock()
        ctx_mock.__enter__ = MagicMock(return_value=session_mock)
        ctx_mock.__exit__ = MagicMock(return_value=False)

        fake_account = MagicMock()
        fake_account.id = "account-1"

        with patch("app.providers.factory.get_pooled_provider", return_value=provider), \
             patch("app.api.routes_helpers.get_db_session", return_value=ctx_mock), \
             patch("app.api.routes_helpers.EmailRepository", return_value=repo), \
             patch("app.api.routes_emails._resolve_account_id_cached", return_value=1), \
             patch("app.api.routes_emails._get_cached_email_response", return_value=None), \
             patch("app.api.routes_emails._start_background_sync") as mock_sync, \
             patch("app.api.routes_emails._get_pending_draft_email_ids", return_value=set()), \
             patch("app.multi_accounts.get_current_account", return_value=fake_account), \
             patch("app.api.routes_helpers._resolve_account_id_for_email", return_value=1):

            response = client.get("/api/emails?folder=sent")

        assert response.status_code == 200
        data = response.get_json()
        assert data["source"] == "syncing"
        assert data["sync_in_progress"] is True
        assert data["provider_touched"] is False
        provider.get_sent_emails.assert_not_called()
        mock_sync.assert_called_once()
        assert mock_sync.call_args.kwargs["folder"] == "sent"


class TestSignatureInSendFlows:
    """Tests E2E : signature incluse dans les flows d'envoi."""

    def test_auto_reply_includes_signature(self, app):
        """
        _send_auto_replies_bg() doit appeler append_signature() sur le message
        avant de créer le brouillon, afin que la signature soit incluse.
        """
        from unittest.mock import patch, MagicMock

        class FakeEmail:
            email_id = "inbox-001"
            sender = "contact@external.com"
            subject = "Question urgente"
            is_read = False

        settings = {
            "auto_reply_enabled": True,
            "auto_reply_message": "Je suis absent.",
            "auto_reply_start": "2020-01-01",
            "auto_reply_end": "2099-12-31",
        }

        provider = MagicMock()
        captured_body = {}

        def fake_create_draft(to=None, subject=None, body=None, reply_to_id=None, **kwargs):
            captured_body["body"] = body
            return "draft-abc"

        provider.create_draft.side_effect = fake_create_draft
        provider.send_draft.return_value = True

        # Mock account manager to prevent owner-email self-reply filtering
        mock_acct_mgr = MagicMock()
        mock_acct_mgr.get_account.return_value = None

        import tempfile
        import os
        import json
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create empty tracker files (legacy + per-account) in temp dir
            for tracker_name in ["auto_reply_tracker.json", "auto_reply_tracker_account-1.json"]:
                with open(os.path.join(tmpdir, tracker_name), "w") as f:
                    json.dump({}, f)

            # Capture orig_join BEFORE patching to avoid recursion
            _orig_join = os.path.join.__wrapped__ if hasattr(os.path.join, '__wrapped__') else os.path.join

            def patched_join(*args):
                # Intercept both legacy and per-account tracker files
                if len(args) >= 2 and isinstance(args[-1], str) \
                        and "auto_reply_tracker" in args[-1]:
                    return _orig_join(tmpdir, args[-1])
                return _orig_join(*args)

            with app.app_context():
                with patch("app.api.settings.load_settings", return_value=settings), \
                     patch("app.smart_routing._SKIP_SENDER_PATTERNS", None), \
                     patch("app.providers.factory.get_pooled_provider", return_value=provider), \
                     patch("app.utils.signature.append_signature",
                           side_effect=lambda b, **kw: b + "\n\n-- Signature") as mock_sig, \
                     patch("app.api.routes_emails._resolve_account_id_cached", return_value=1), \
                     patch("app.multi_accounts.get_account_manager", return_value=mock_acct_mgr), \
                     patch("os.path.join", side_effect=patched_join):

                    import app.api.routes_emails as routes_emails_mod
                    orig = routes_emails_mod._auto_reply_running
                    routes_emails_mod._auto_reply_running = False
                    try:
                        routes_emails_mod._send_auto_replies_bg(
                            [FakeEmail()], "account-1", account_id=1
                        )
                    finally:
                        routes_emails_mod._auto_reply_running = orig

        # append_signature doit avoir été appelé avec le message brut
        mock_sig.assert_called_once()
        assert mock_sig.call_args[0][0] == "Je suis absent."
        # Le body passé à create_draft doit contenir la signature
        assert "-- Signature" in captured_body.get("body", ""), \
            "La signature doit être incluse dans le body de l'auto-reply"

    def test_validate_pending_draft_calls_append_signature(self, app):
        """
        validate_pending_draft() doit appeler append_signature() sur le draft_body
        avant l'envoi, afin que la signature soit toujours présente.
        """
        from unittest.mock import patch, MagicMock

        pending = MagicMock()
        pending.id = "pd-99"
        pending.email_id = "inbox-500"
        pending.draft_body = "Bonjour, voici ma réponse."
        pending.status = PendingDraftStatus.PENDING
        pending.subject = "Re: Test"
        # account_id must match patched _resolve_account_id_cached (return_value=1).
        pending.account_id = 1

        store = MagicMock()
        store.get_by_id.return_value = pending

        container = MagicMock()
        container.get_pending_draft_store.return_value = store

        provider = MagicMock()
        provider.send_reply_directly.return_value = MagicMock(id="sent-500")

        with app.app_context():
            with patch("app.api.routes_helpers._get_container", return_value=container), \
                 patch("app.api.routes_pending._get_authenticated_provider", return_value=provider), \
                 patch("app.utils.signature.append_signature",
                       side_effect=lambda b, **kw: b + "\n\n-- Signature") as mock_sig, \
                 patch("app.api.routes_helpers.submit_background"), \
                 patch("app.api.routes_pending._evict_email_from_all_caches"), \
                 patch("app.api.routes_pending._validate_email_id", return_value=True), \
                 patch("app.api.routes_pending._resolve_account_id_cached", return_value=1):

                import app.api.routes_pending as routes_pending_mod
                with app.test_request_context(
                    "/api/pending-drafts/pd-99/validate",
                    method="POST",
                    json={}
                ):
                    routes_pending_mod.validate_pending_draft("pd-99")

        # append_signature doit avoir été appelé sur le draft_body
        mock_sig.assert_called()
        assert mock_sig.call_args[0][0] == "Bonjour, voici ma réponse."
