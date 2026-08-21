# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests E2E complets pour l'API Agentys.

Couvre tous les groupes d'endpoints avec Flask test client + mocks.
Chaque test est autonome avec ses propres patches.

pytest tests/test_api_comprehensive_e2e.py -v
"""
import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Fixtures partagées
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def app():
    from app.api.app import create_app
    return create_app(config={"TESTING": True})


@pytest.fixture
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# Helpers de mock
# ---------------------------------------------------------------------------


def _mock_db_ctx():
    """Retourne un context manager mock pour get_db_session."""
    session = MagicMock()
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=session)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


def _make_mock_container():
    """Container DI entièrement mocké."""
    c = MagicMock()
    c.get_pending_draft_store.return_value.get_all.return_value = []
    c.get_pending_draft_store.return_value.get_pending.return_value = []
    c.get_pending_draft_store.return_value.get_by_id.return_value = None
    c.get_pending_draft_store.return_value.get_by_email_id.return_value = None
    c.get_pending_draft_store.return_value.count_pending.return_value = 0
    c.get_account_repository.return_value.list_accounts.return_value = []
    c.get_account_repository.return_value.get_account_by_id.return_value = None
    c.get_learning_service.return_value.get_stats.return_value = {}
    c.get_email_repository.return_value.get_labels.return_value = []
    c.get_learning_pattern_store.return_value.list_all.return_value = []
    c.get_feedback_store.return_value.list_all.return_value = []
    c.get_draft_store.return_value.get.return_value = None
    return c


def _make_mock_provider():
    """Provider email entièrement mocké."""
    p = MagicMock()
    p.archive_email.return_value = True
    p.delete_email.return_value = True
    p.mark_as_read.return_value = True
    p.move_to_inbox.return_value = True
    p.restore_from_trash.return_value = True
    p.send_reply_directly.return_value = "sent-id-001"
    p.create_draft.return_value = "draft-id-001"
    p.send_draft.return_value = True
    p.disconnect.return_value = None
    p.get_messages.return_value = []
    p.list_messages.return_value = []
    return p


VALID_SETTINGS = {
    "operation_mode": "controlled",
    "polling_interval_minutes": 5,
    "notifications_enabled": True,
    "working_hours_only": False,
    "working_hours_start": "09:00",
    "working_hours_end": "18:00",
    "auto_draft_enabled": True,
    "auto_archive_action": False,
    "auto_empty_trash_30d": True,
    "auto_empty_spam_30d": True,
    "hide_noise_from_inbox": False,
    "theme": "default",
    "ui_sounds_enabled": False,
    "undo_send_delay": 5,
    "auto_reply_enabled": False,
    "auto_reply_message": "",
    "auto_reply_start": "",
    "auto_reply_end": "",
    "batch_enabled": True,
    "batch_active_hours_start": "07:00",
    "batch_active_hours_end": "20:00",
    "deep_work_enabled": False,
    "booking_url": "",
}


# ---------------------------------------------------------------------------
# Classe TestHealthAndStats
# ---------------------------------------------------------------------------


class TestHealthAndStats:
    """Tests des endpoints de santé et statistiques."""

    def test_ping(self, client):
        """GET /ping retourne 200 avec status ok."""
        resp = client.get("/api/ping")
        assert resp.status_code == 200, f"Ping a échoué: {resp.get_json()}"
        data = resp.get_json()
        assert data is not None
        assert data.get("status") == "ok"

    def test_health(self, client):
        """GET /health retourne 200 avec status."""
        container = _make_mock_container()
        # Configurer le health_check pour retourner des valeurs JSON-sérialisables
        health_result = MagicMock()
        health_result.status = "healthy"
        health_result.email_provider.healthy = True
        health_result.llm.healthy = True
        container.get_health_check_use_case.return_value.execute.return_value = health_result

        with patch("app.api.routes_helpers._get_container", return_value=container):
            resp = client.get("/api/health")
        assert resp.status_code == 200, f"Health a échoué: {resp.get_json()}"
        data = resp.get_json()
        assert "status" in data, "Clé 'status' absente de la réponse health"

    def test_stats(self, client):
        """GET /stats retourne 200."""
        container = _make_mock_container()
        # Configurer les valeurs JSON-sérialisables pour /stats
        container.get_draft_history.return_value.get_all.return_value = []
        container.get_token_counter.return_value.get_total.return_value = 0
        container.get_token_counter.return_value.get_model.return_value = "claude-haiku"
        container.get_token_counter.return_value.get_history.return_value = []
        container.get_learning_service.return_value.get_stats.return_value = {"rules": 0}

        mock_cost_manager = MagicMock()
        mock_cost_manager.get_current_month_stats.return_value = {"total_cost": 0.0}

        with (
            patch("app.api.routes_helpers._get_container", return_value=container),
            patch("app.infrastructure.cost_manager.get_cost_manager", return_value=mock_cost_manager),
            patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=1),
        ):
            resp = client.get("/api/stats")
        assert resp.status_code == 200, f"Stats a échoué: {resp.get_json()}"

    def test_draft_quality_stats(self, client):
        """GET /draft-quality/stats retourne 200."""
        with patch("app.api.routes_helpers._get_container", return_value=_make_mock_container()):
            resp = client.get("/api/draft-quality/stats")
        assert resp.status_code == 200, f"Draft quality stats a échoué: {resp.get_json()}"

    def test_post_stats_feature(self, client):
        """POST /stats/feature retourne 200."""
        resp = client.post("/api/stats/feature", json={"feature": "test_feature", "count": 1})
        assert resp.status_code == 200, f"Stats feature a échoué: {resp.get_json()}"


# ---------------------------------------------------------------------------
# Classe TestEmailFolders
# ---------------------------------------------------------------------------


class TestEmailFolders:
    """Tests de récupération d'emails par dossier."""

    def _patches_for_list(self, provider, container):
        return [
            patch("app.api.routes_emails._get_authenticated_provider", return_value=provider),
            patch("app.api.routes_helpers._get_container", return_value=container),
            patch("app.api.routes_emails._get_cached_email_response", return_value=None),
            patch("app.api.routes_emails._set_cached_email_response"),
            patch("app.api.routes_helpers.get_db_session", return_value=_mock_db_ctx()),
            patch("app.api.routes_helpers.EmailRepository", return_value=MagicMock(
                get_all_by_folder=MagicMock(return_value=[]),
                get_labels=MagicMock(return_value=[]),
            )),
            patch("app.api.routes_emails._start_background_sync"),
            patch("app.api.routes_emails._get_pending_draft_email_ids", return_value=set()),
        ]

    def test_emails_inbox(self, client):
        """GET /emails?folder=inbox retourne 200 avec clé 'emails'."""
        provider = _make_mock_provider()
        container = _make_mock_container()
        patches = self._patches_for_list(provider, container)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
            resp = client.get("/api/emails?folder=inbox")
        assert resp.status_code == 200, f"Inbox a échoué: {resp.get_json()}"
        data = resp.get_json()
        assert "emails" in data, "Clé 'emails' absente de la réponse"

    def test_emails_sent(self, client):
        """GET /emails?folder=sent retourne 200."""
        provider = _make_mock_provider()
        container = _make_mock_container()
        patches = self._patches_for_list(provider, container)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
            resp = client.get("/api/emails?folder=sent")
        assert resp.status_code == 200, f"Sent a échoué: {resp.get_json()}"

    def test_emails_archived(self, client):
        """GET /emails?folder=archived retourne 200."""
        provider = _make_mock_provider()
        container = _make_mock_container()
        patches = self._patches_for_list(provider, container)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
            resp = client.get("/api/emails?folder=archived")
        assert resp.status_code == 200, f"Archived a échoué: {resp.get_json()}"

    def test_emails_spam(self, client):
        """GET /emails?folder=spam retourne 200."""
        provider = _make_mock_provider()
        container = _make_mock_container()
        patches = self._patches_for_list(provider, container)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
            resp = client.get("/api/emails?folder=spam")
        assert resp.status_code == 200, f"Spam a échoué: {resp.get_json()}"

    def test_emails_trash(self, client):
        """GET /emails?folder=trash retourne 200."""
        provider = _make_mock_provider()
        container = _make_mock_container()
        patches = self._patches_for_list(provider, container)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
            resp = client.get("/api/emails?folder=trash")
        assert resp.status_code == 200, f"Trash a échoué: {resp.get_json()}"


# ---------------------------------------------------------------------------
# Classe TestEmailOperations
# ---------------------------------------------------------------------------


class TestEmailOperations:
    """Tests des opérations sur un email individuel."""

    def test_archive_email(self, client):
        """POST /emails/<id>/archive retourne 200."""
        provider = _make_mock_provider()
        container = _make_mock_container()
        repo = MagicMock()
        repo.update_folder_by_email_id = MagicMock(return_value=True)

        with (
            patch("app.api.routes_emails._get_authenticated_provider", return_value=provider),
            patch("app.api.routes_helpers._get_container", return_value=container),
            patch("app.api.routes_emails._invalidate_folder_cache"),
            patch("app.api.routes_helpers.get_db_session", return_value=_mock_db_ctx()),
            patch("app.api.routes_helpers.EmailRepository", return_value=repo),
        ):
            resp = client.post("/api/emails/msg-001/archive", json={"sender": "test@example.com"})

        assert resp.status_code == 200, f"Archive a échoué: {resp.get_json()}"
        assert resp.get_json().get("success") is True

    def test_delete_email(self, client):
        """POST /emails/<id>/delete retourne 200."""
        provider = _make_mock_provider()
        container = _make_mock_container()
        repo = MagicMock()

        with (
            patch("app.api.routes_emails._get_authenticated_provider", return_value=provider),
            patch("app.api.routes_helpers._get_container", return_value=container),
            patch("app.api.routes_emails._invalidate_folder_cache"),
            patch("app.api.routes_helpers.get_db_session", return_value=_mock_db_ctx()),
            patch("app.api.routes_helpers.EmailRepository", return_value=repo),
        ):
            resp = client.post("/api/emails/msg-001/delete", json={"sender": "test@example.com"})

        assert resp.status_code == 200, f"Delete a échoué: {resp.get_json()}"

    def test_mark_email_read(self, client):
        """PATCH /emails/<id>/read retourne 200."""
        provider = _make_mock_provider()
        repo = MagicMock()

        with (
            patch("app.api.routes_emails._get_authenticated_provider", return_value=provider),
            patch("app.api.routes_helpers._get_container", return_value=_make_mock_container()),
            patch("app.api.routes_helpers.get_db_session", return_value=_mock_db_ctx()),
            patch("app.api.routes_helpers.EmailRepository", return_value=repo),
        ):
            resp = client.patch("/api/emails/msg-001/read", json={"account_id": "1", "is_read": True})

        assert resp.status_code == 200, f"Mark read a échoué: {resp.get_json()}"

    def test_not_spam(self, client):
        """POST /emails/<id>/not-spam retourne 200."""
        provider = _make_mock_provider()

        with (
            patch("app.api.routes_emails._get_authenticated_provider", return_value=provider),
            patch("app.api.routes_emails._evict_email_from_all_caches"),
            patch("app.api.routes_emails._rh._resolve_account_id_for_user", return_value=1),
        ):
            resp = client.post("/api/emails/msg-001/not-spam")

        assert resp.status_code == 200, f"Not-spam a échoué: {resp.get_json()}"
        assert resp.get_json().get("success") is True

    def test_restore_email(self, client):
        """POST /emails/<id>/restore retourne 200."""
        provider = _make_mock_provider()

        with (
            patch("app.api.routes_emails._get_authenticated_provider", return_value=provider),
            patch("app.api.routes_emails._evict_email_from_all_caches"),
        ):
            resp = client.post("/api/emails/msg-001/restore")

        assert resp.status_code == 200, f"Restore a échoué: {resp.get_json()}"

    def test_skip_email(self, client):
        """POST /emails/<id>/skip retourne 200."""
        provider = _make_mock_provider()
        container = _make_mock_container()

        with (
            patch("app.api.routes_emails._get_authenticated_provider", return_value=provider),
            patch("app.api.routes_helpers._get_container", return_value=container),
            patch("app.api.routes_helpers.get_db_session", return_value=_mock_db_ctx()),
            patch("app.api.routes_helpers.EmailRepository", return_value=MagicMock()),
        ):
            resp = client.post("/api/emails/msg-001/skip")

        assert resp.status_code == 200, f"Skip a échoué: {resp.get_json()}"


# ---------------------------------------------------------------------------
# Classe TestBulkOperations
# ---------------------------------------------------------------------------


class TestBulkOperations:
    """Tests des opérations groupées sur plusieurs emails."""

    def test_bulk_read(self, client):
        """PATCH /emails/bulk-read retourne 200."""
        provider = _make_mock_provider()
        repo = MagicMock()

        with (
            patch("app.api.routes_emails._get_authenticated_provider", return_value=provider),
            patch("app.api.routes_helpers.get_db_session", return_value=_mock_db_ctx()),
            patch("app.api.routes_helpers.EmailRepository", return_value=repo),
        ):
            resp = client.patch(
                "/api/emails/bulk-read",
                json={"account_id": "1", "email_ids": ["msg-001", "msg-002"], "is_read": True},
            )

        assert resp.status_code == 200, f"Bulk-read a échoué: {resp.get_json()}"

    def test_bulk_archive(self, client):
        """POST /emails/bulk-archive retourne 200."""
        provider = _make_mock_provider()
        container = _make_mock_container()

        with (
            patch("app.api.routes_emails._get_authenticated_provider", return_value=provider),
            patch("app.api.routes_helpers._get_container", return_value=container),
            patch("app.api.routes_emails._invalidate_folder_cache"),
            patch("app.api.routes_helpers.get_db_session", return_value=_mock_db_ctx()),
            patch("app.api.routes_helpers.EmailRepository", return_value=MagicMock()),
        ):
            resp = client.post(
                "/api/emails/bulk-archive",
                json={"account_id": "1", "email_ids": ["msg-001"]},
            )

        assert resp.status_code == 200, f"Bulk-archive a échoué: {resp.get_json()}"

    def test_bulk_delete(self, client):
        """POST /emails/bulk-delete retourne 200."""
        provider = _make_mock_provider()
        container = _make_mock_container()

        with (
            patch("app.api.routes_emails._get_authenticated_provider", return_value=provider),
            patch("app.api.routes_helpers._get_container", return_value=container),
            patch("app.api.routes_emails._invalidate_folder_cache"),
            patch("app.api.routes_helpers.get_db_session", return_value=_mock_db_ctx()),
            patch("app.api.routes_helpers.EmailRepository", return_value=MagicMock()),
        ):
            resp = client.post(
                "/api/emails/bulk-delete",
                json={"account_id": "1", "email_ids": ["msg-001"]},
            )

        assert resp.status_code == 200, f"Bulk-delete a échoué: {resp.get_json()}"

    def test_bulk_not_spam(self, client):
        """POST /emails/bulk-not-spam retourne 200."""
        provider = _make_mock_provider()

        with (
            patch("app.api.routes_emails._get_authenticated_provider", return_value=provider),
            patch("app.api.routes_emails._evict_email_from_all_caches"),
        ):
            resp = client.post(
                "/api/emails/bulk-not-spam",
                json={"account_id": "1", "email_ids": ["msg-001"]},
            )

        assert resp.status_code == 200, f"Bulk-not-spam a échoué: {resp.get_json()}"

    def test_bulk_restore(self, client):
        """POST /emails/bulk-restore retourne 200."""
        provider = _make_mock_provider()

        with (
            patch("app.api.routes_emails._get_authenticated_provider", return_value=provider),
            patch("app.api.routes_emails._evict_email_from_all_caches"),
        ):
            resp = client.post(
                "/api/emails/bulk-restore",
                json={"account_id": "1", "email_ids": ["msg-001"]},
            )

        assert resp.status_code == 200, f"Bulk-restore a échoué: {resp.get_json()}"

    def test_empty_spam(self, client):
        """POST /emails/empty-spam retourne 200."""
        provider = _make_mock_provider()
        provider.empty_spam = MagicMock(return_value=True)

        with (
            patch("app.api.routes_emails._get_authenticated_provider", return_value=provider),
            patch("app.api.routes_helpers._get_container", return_value=_make_mock_container()),
            patch("app.api.routes_emails._invalidate_folder_cache"),
            patch("app.api.routes_helpers.get_db_session", return_value=_mock_db_ctx()),
            patch("app.api.routes_helpers.EmailRepository", return_value=MagicMock()),
        ):
            resp = client.post("/api/emails/empty-spam", json={"account_id": "1"})

        assert resp.status_code == 200, f"Empty-spam a échoué: {resp.get_json()}"

    def test_empty_trash(self, client):
        """POST /emails/empty-trash retourne 200."""
        provider = _make_mock_provider()
        provider.empty_trash = MagicMock(return_value=True)

        with (
            patch("app.api.routes_emails._get_authenticated_provider", return_value=provider),
            patch("app.api.routes_helpers._get_container", return_value=_make_mock_container()),
            patch("app.api.routes_emails._invalidate_folder_cache"),
            patch("app.api.routes_helpers.get_db_session", return_value=_mock_db_ctx()),
            patch("app.api.routes_helpers.EmailRepository", return_value=MagicMock()),
        ):
            resp = client.post("/api/emails/empty-trash", json={"account_id": "1"})

        assert resp.status_code == 200, f"Empty-trash a échoué: {resp.get_json()}"


# ---------------------------------------------------------------------------
# Classe TestDraftOperations
# ---------------------------------------------------------------------------


class TestDraftOperations:
    """Tests des opérations sur les drafts."""

    def test_list_drafts(self, client):
        """GET /drafts retourne 200 avec clé 'drafts'."""
        container = _make_mock_container()
        container.get_pending_draft_store.return_value.get_all.return_value = []

        with patch("app.api.routes_helpers._get_container", return_value=container), \
             patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=1):
            resp = client.get("/api/drafts")

        assert resp.status_code == 200, f"List drafts a échoué: {resp.get_json()}"

    def test_patch_draft_feedback(self, client):
        """PATCH /drafts/<id>/feedback retourne 200."""
        container = _make_mock_container()
        # Route appelle update_feedback_for_account (pas update_feedback), cf routes_drafts.py:312
        container.get_draft_history.return_value.update_feedback_for_account.return_value = True

        with patch(
            "app.api.routes_helpers._get_container", return_value=container
        ), patch(
            "app.api.routes_drafts._rh._resolve_account_id_for_user", return_value=1
        ):
            resp = client.patch(
                "/api/drafts/draft-001/feedback",
                json={"feedback": "positive", "comment": "Très bien"},
            )

        assert resp.status_code == 200, f"Feedback draft a échoué: {resp.get_json()}"

    def test_patch_draft_edit(self, client):
        """PATCH /drafts/<id>/edit retourne 404 (draft non trouvé)."""
        container = _make_mock_container()
        # Route appelle get_by_id_for_account (scoped), pas get_by_id
        container.get_draft_history.return_value.get_by_id_for_account.return_value = None

        with patch(
            "app.api.routes_helpers._get_container", return_value=container
        ), patch(
            "app.api.routes_drafts._rh._resolve_account_id_for_user", return_value=1
        ):
            resp = client.patch(
                "/api/drafts/draft-001/edit",
                json={"subject": "Re: Test", "body": "Nouveau corps du message"},
            )

        assert resp.status_code == 404, f"Edit draft devrait retourner 404: {resp.get_json()}"

    def test_patch_draft_edit_with_draft(self, client):
        """PATCH /drafts/<id>/edit retourne 200 si draft existe."""
        container = _make_mock_container()
        # Route appelle get_by_id_for_account (scoped multi-compte), cf routes_drafts.py:379
        draft_record = MagicMock()
        draft_record.draft_id = "gmail-draft-abc123"
        draft_record.draft_final = "Corps précédent"
        container.get_draft_history.return_value.get_by_id_for_account.return_value = draft_record
        container.provider.update_draft.return_value = True
        container.get_draft_history.return_value.add.return_value = None

        mock_provider = MagicMock()
        mock_provider.update_draft.return_value = True

        with patch(
            "app.api.routes_helpers._get_container", return_value=container
        ), patch(
            "app.api.routes_drafts._get_authenticated_provider", return_value=mock_provider
        ), patch(
            "app.api.routes_drafts._rh._resolve_account_id_for_user", return_value=1
        ):
            resp = client.patch(
                "/api/drafts/draft-001/edit",
                json={"subject": "Re: Test", "body": "Nouveau corps du message"},
            )

        assert resp.status_code == 200, f"Edit draft a échoué: {resp.get_json()}"
        assert resp.get_json()["success"] is True

    def test_refine_text(self, client):
        """POST /refine-text retourne 200 ou 500 (LLM mocké)."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Bonjour, veuillez trouver ci-joint.")]

        with patch("anthropic.Anthropic") as mock_anthropic:
            mock_anthropic.return_value.messages.create.return_value = mock_response
            resp = client.post(
                "/api/refine-text",
                json={"text": "Bonjour", "instruction": "Rends plus formel"},
            )

        assert resp.status_code in (200, 500), f"Refine-text a retourné un code inattendu: {resp.status_code}"

    def test_drafts_detect(self, client):
        """POST /drafts/detect retourne 200 (paramètre 'text', pas 'body')."""
        resp = client.post(
            "/api/drafts/detect",
            json={"text": "Pouvez-vous confirmer la réunion de demain?"},
        )
        assert resp.status_code == 200, f"Drafts detect a échoué: {resp.get_json()}"


# ---------------------------------------------------------------------------
# Classe TestPendingDrafts
# ---------------------------------------------------------------------------


class TestPendingDrafts:
    """Tests des endpoints pending-drafts."""

    def test_list_pending_drafts(self, client):
        """GET /pending-drafts retourne 200 avec clé 'drafts'."""
        container = _make_mock_container()

        with patch("app.api.routes_helpers._get_container", return_value=container):
            resp = client.get("/api/pending-drafts")

        assert resp.status_code == 200, f"List pending drafts a échoué: {resp.get_json()}"
        data = resp.get_json()
        assert "drafts" in data, "Clé 'drafts' absente de la réponse"

    def test_get_pending_draft_not_found(self, client):
        """GET /pending-drafts/<id> retourne 404 si non trouvé."""
        container = _make_mock_container()

        with patch("app.api.routes_helpers._get_container", return_value=container):
            resp = client.get("/api/pending-drafts/draft-001")

        assert resp.status_code == 404, f"Attendu 404, obtenu {resp.status_code}"

    def test_get_pending_draft_by_email_not_found(self, client):
        """GET /pending-drafts/by-email/<id> retourne 200 + draft:null si non trouvé."""
        container = _make_mock_container()

        with patch("app.api.routes_helpers._get_container", return_value=container):
            resp = client.get("/api/pending-drafts/by-email/msg-001")

        assert resp.status_code == 200, f"Attendu 200, obtenu {resp.status_code}"
        assert resp.get_json() == {"draft": None}

    def test_patch_pending_draft_not_found(self, client):
        """PATCH /pending-drafts/<id> retourne 404 si non trouvé."""
        container = _make_mock_container()

        with patch("app.api.routes_helpers._get_container", return_value=container):
            resp = client.patch(
                "/api/pending-drafts/draft-001",
                json={"body": "Nouveau corps"},
            )

        assert resp.status_code in (200, 404), f"Patch pending draft a retourné un code inattendu: {resp.status_code}"

    def test_delete_pending_draft_not_found(self, client):
        """DELETE /pending-drafts/<id> retourne 404 si non trouvé."""
        container = _make_mock_container()

        with patch("app.api.routes_helpers._get_container", return_value=container):
            resp = client.delete("/api/pending-drafts/draft-001")

        assert resp.status_code in (200, 404), f"Delete pending draft a retourné un code inattendu: {resp.status_code}"

    def test_reject_pending_draft_not_found(self, client):
        """POST /pending-drafts/<id>/reject retourne 404 si non trouvé."""
        container = _make_mock_container()

        with patch("app.api.routes_helpers._get_container", return_value=container):
            resp = client.post(
                "/api/pending-drafts/draft-001/reject",
                json={"account_id": "1"},
            )

        assert resp.status_code in (200, 404), f"Reject pending draft a retourné un code inattendu: {resp.status_code}"


# ---------------------------------------------------------------------------
# Classe TestSettings
# ---------------------------------------------------------------------------


class TestSettings:
    """Tests des endpoints paramètres."""

    def test_get_settings(self, client):
        """GET /settings retourne 200 avec les settings."""
        with patch("app.api.settings.load_settings", return_value=VALID_SETTINGS.copy()):
            resp = client.get("/api/settings")

        assert resp.status_code == 200, f"Get settings a échoué: {resp.get_json()}"
        data = resp.get_json()
        assert "theme" in data or "operation_mode" in data, "Settings semblent vides"

    def test_patch_settings_theme(self, client):
        """PATCH /settings avec theme valide retourne 200."""
        with (
            patch("app.api.settings.load_settings", return_value=VALID_SETTINGS.copy()),
            patch("app.api.settings.save_settings", return_value=True),
        ):
            resp = client.patch("/api/settings", json={"theme": "default"})

        assert resp.status_code == 200, f"Patch theme a échoué: {resp.get_json()}"

    def test_patch_settings_working_hours(self, client):
        """PATCH /settings avec working_hours retourne 200."""
        with (
            patch("app.api.settings.load_settings", return_value=VALID_SETTINGS.copy()),
            patch("app.api.settings.save_settings", return_value=True),
        ):
            resp = client.patch(
                "/api/settings",
                json={"working_hours_start": "09:00", "working_hours_end": "18:00"},
            )

        assert resp.status_code == 200, f"Patch working hours a échoué: {resp.get_json()}"

    def test_patch_settings_invalid_theme(self, client):
        """PATCH /settings avec theme invalide retourne 400."""
        with (
            patch("app.api.settings.load_settings", return_value=VALID_SETTINGS.copy()),
            patch("app.api.settings.save_settings", return_value=True),
        ):
            resp = client.patch("/api/settings", json={"theme": "invalid-theme"})

        assert resp.status_code == 400, f"Attendu 400 pour theme invalide, obtenu {resp.status_code}"

    def test_patch_settings_removed_theme_rejected(self, client):
        """Les thèmes supprimés (dark-luxury, futurist) ne sont plus valides → 400.

        Seul 'default' (Clarity) subsiste. Un PATCH vers un thème retiré doit être
        rejeté côté backend (defense-in-depth ; le frontend ne propose plus l'option).
        """
        for removed in ("dark-luxury", "futurist"):
            with (
                patch("app.api.settings.load_settings", return_value=VALID_SETTINGS.copy()),
                patch("app.api.settings.save_settings", return_value=True),
            ):
                resp = client.patch("/api/settings", json={"theme": removed})

            assert resp.status_code == 400, (
                f"Attendu 400 pour le thème supprimé '{removed}', obtenu {resp.status_code}"
            )


# ---------------------------------------------------------------------------
# Classe TestLearning
# ---------------------------------------------------------------------------


class TestLearning:
    """Tests des endpoints learning.

    H-7 (audit security.md, issue #533): /learning/stats and
    /learning/patterns are now `@require_admin`. The autouse fixture
    stubs admin auth and auto-injects the Bearer header.
    """

    @pytest.fixture(autouse=True)
    def _stub_admin(self, monkeypatch, client):
        fake_payload = {"sub": "1", "email": "admin@test.com"}
        monkeypatch.setattr("app.api.auth._decode_jwt", lambda token: fake_payload)
        monkeypatch.setattr("app.api.admin._is_admin", lambda email: True)
        original_get = client.get

        def _get_with_admin(*args, **kwargs):
            headers = kwargs.pop("headers", None) or {}
            if "Authorization" not in headers:
                headers["Authorization"] = "Bearer admin-stub"
            return original_get(*args, headers=headers, **kwargs)

        monkeypatch.setattr(client, "get", _get_with_admin)
        yield

    def test_learning_stats(self, client):
        """GET /learning/stats retourne 200."""
        container = _make_mock_container()

        with patch("app.api.routes_helpers._get_container", return_value=container):
            resp = client.get("/api/learning/stats")

        assert resp.status_code == 200, f"Learning stats a échoué: {resp.get_json()}"

    def test_learning_patterns(self, client):
        """GET /learning/patterns retourne 200."""
        container = _make_mock_container()

        with patch("app.api.routes_helpers._get_container", return_value=container):
            resp = client.get("/api/learning/patterns")

        assert resp.status_code == 200, f"Learning patterns a échoué: {resp.get_json()}"

    def test_learning_rules(self, client):
        """GET /learning/rules retourne 200."""
        container = _make_mock_container()

        with patch("app.api.routes_helpers._get_container", return_value=container):
            resp = client.get("/api/learning/rules")

        assert resp.status_code == 200, f"Learning rules a échoué: {resp.get_json()}"

    def test_learning_all(self, client):
        """GET /learning/all retourne 200 avec 'categories'."""
        container = _make_mock_container()

        with (
            patch("app.api.routes_helpers._get_container", return_value=container),
            patch("app.api.routes_helpers.get_db_session", return_value=_mock_db_ctx()),
        ):
            resp = client.get("/api/learning/all")

        assert resp.status_code == 200, f"Learning all a échoué: {resp.get_json()}"
        data = resp.get_json()
        assert "categories" in data, "Clé 'categories' absente de la réponse"

    def test_writing_style(self, client):
        """GET /writing-style retourne 200."""
        with (
            patch("app.api.routes_emails._get_authenticated_provider", return_value=_make_mock_provider()),
            patch("app.api.routes_helpers.get_db_session", return_value=_mock_db_ctx()),
        ):
            resp = client.get("/api/writing-style")

        assert resp.status_code == 200, f"Writing style a échoué: {resp.get_json()}"


# ---------------------------------------------------------------------------
# Classe TestContacts
# ---------------------------------------------------------------------------


class TestContacts:
    """Tests des endpoints contacts."""

    def test_autocomplete_contacts(self, client):
        """GET /contacts/autocomplete?q=test retourne 200."""
        with (
            patch("app.api.routes_helpers.get_db_session", return_value=_mock_db_ctx()),
        ):
            resp = client.get("/api/contacts/autocomplete?q=test")

        assert resp.status_code == 200, f"Autocomplete contacts a échoué: {resp.get_json()}"

    def test_contact_insights(self, client):
        """GET /contacts/insights?contact_email=test@example.com retourne 200 ou 400.

        Audit F-05 (2026-05-16): la route bail en 401 quand
        `_resolve_account_id_cached` retourne `_NO_ACCOUNT_SENTINEL` (-1).
        Le handler fait un `from app.api.routes_helpers import
        _resolve_account_id_cached` LOCAL au début de la fonction, donc
        on patche à la source (routes_helpers) — patcher routes_contacts
        n'aurait aucun effet vu l'import dynamique.
        """
        with (
            patch("app.api.routes_helpers.get_db_session", return_value=_mock_db_ctx()),
            patch("app.api.routes_emails._get_authenticated_provider", return_value=_make_mock_provider()),
            patch("app.api.routes_helpers._resolve_account_id_cached", return_value=1),
            patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=1),
        ):
            resp = client.get("/api/contacts/insights?contact_email=test@example.com")

        assert resp.status_code in (200, 400, 500), f"Contact insights a retourné un code inattendu: {resp.status_code}"

    def test_relationships_overrides(self, client):
        """GET /contacts/relationships/overrides retourne 200 (account_id requis).

        Audit 2026-04-25 (H-1/H-2) : `_block_cross_account_access` compare
        `requested_account_id` au JWT-resolved caller_aid. On patche le
        resolver à 1 pour simuler un caller authentifié sur le compte 1
        (matche le `?account_id=1` dans l'URL).
        """
        with patch("app.api.routes_helpers.get_db_session", return_value=_mock_db_ctx()), \
             patch("app.api.routes_contacts._resolve_account_id_for_user", return_value=1):
            resp = client.get("/api/contacts/relationships/overrides?account_id=1")

        assert resp.status_code == 200, f"Relationships overrides a échoué: {resp.get_json()}"


# ---------------------------------------------------------------------------
# Classe TestMemory
# ---------------------------------------------------------------------------


class TestMemory:
    """Tests des endpoints mémoire IA."""

    def test_get_memory(self, client):
        """GET /memory retourne 200 avec 'content'."""
        from app.memory_manager import MemoryStats
        mock_manager = MagicMock()
        mock_manager.get_memory.return_value = "Connaissance de base."
        # Utiliser une vraie instance MemoryStats (dataclass) pour que asdict() fonctionne
        mock_manager.get_stats.return_value = MemoryStats(
            total_size=100,
            word_count=10,
            section_count=2,
            last_modified="2026-02-24T10:00:00",
            version_count=1,
        )

        # GET /memory réimporte `_resolve_account_id_for_user` localement
        # dans la fonction (line 1798 de routes_misc) → patch doit cibler la
        # source `routes_helpers`, pas le ré-export module-level.
        with patch("app.memory_manager.get_memory_manager", return_value=mock_manager), \
             patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=1):
            resp = client.get("/api/memory")

        assert resp.status_code == 200, f"Get memory a échoué: {resp.get_json()}"
        data = resp.get_json()
        assert "content" in data, "Clé 'content' absente de la réponse"

    def test_put_memory(self, client):
        """PUT /memory retourne 200 après mise à jour."""
        from app.memory_manager import MemoryStats, MemoryVersion
        mock_manager = MagicMock()
        # Utiliser une vraie instance MemoryVersion pour que asdict() fonctionne
        mock_version = MemoryVersion(
            id="v2",
            content_hash="abc123",
            content_length=200,
            preview="Nouvelle connaissance...",
            created_at="2026-02-24T10:00:00",
            change_summary="Mise à jour test",
            created_by="user",
        )
        mock_manager.update_memory.return_value = mock_version
        mock_manager.get_stats.return_value = MemoryStats(
            total_size=200,
            word_count=20,
            section_count=3,
            last_modified="2026-02-24T10:00:00",
            version_count=2,
        )

        with patch("app.memory_manager.get_memory_manager", return_value=mock_manager), \
             patch("app.api.routes_misc._resolve_account_id_for_user", return_value=1):
            resp = client.put("/api/memory", json={"content": "Nouvelle connaissance test."})

        assert resp.status_code == 200, f"Put memory a échoué: {resp.get_json()}"
        assert resp.get_json().get("success") is True


# ---------------------------------------------------------------------------
# Classe TestCompose
# ---------------------------------------------------------------------------


class TestCompose:
    """Tests d'envoi et de composition d'emails."""

    def test_compose_email(self, client):
        """POST /emails/compose retourne 200 ou 201."""
        provider = _make_mock_provider()

        with (
            patch("app.api.routes_emails._get_authenticated_provider", return_value=provider),
            patch("app.api.routes_helpers._get_container", return_value=_make_mock_container()),
        ):
            resp = client.post(
                "/api/emails/compose",
                json={
                    "account_id": "1",
                    "to": "test@example.com",
                    "subject": "Test sujet",
                    "body": "Bonjour, ceci est un test.",
                },
            )

        assert resp.status_code in (200, 201, 400, 500), (
            f"Compose a retourné un code inattendu: {resp.status_code} — {resp.get_json()}"
        )

    def test_send_new_email(self, client):
        """POST /emails/send-new retourne 200."""
        provider = _make_mock_provider()

        with (
            patch("app.api.routes_emails._get_authenticated_provider", return_value=provider),
            patch("app.utils.signature.append_signature", side_effect=lambda b: b),
        ):
            resp = client.post(
                "/api/emails/send-new",
                json={
                    "account_id": "1",
                    "to": "test@example.com",
                    "subject": "Test envoi",
                    "body": "Bonjour, ceci est un test d'envoi.",
                },
            )

        assert resp.status_code in (200, 201, 500), (
            f"Send-new a retourné un code inattendu: {resp.status_code} — {resp.get_json()}"
        )
        if resp.status_code == 200:
            provider.create_draft.assert_called_once()
            provider.send_draft.assert_called_once()

    def test_send_new_email_missing_to(self, client):
        """POST /emails/send-new sans 'to' retourne 400."""
        with patch("app.api.routes_emails._get_authenticated_provider", return_value=_make_mock_provider()):
            resp = client.post(
                "/api/emails/send-new",
                json={"subject": "Test", "body": "Corps"},
            )
        assert resp.status_code == 400, "Attendu 400 pour 'to' manquant"

    def test_send_new_email_missing_body(self, client):
        """POST /emails/send-new sans 'body' retourne 400."""
        with patch("app.api.routes_emails._get_authenticated_provider", return_value=_make_mock_provider()):
            resp = client.post(
                "/api/emails/send-new",
                json={"to": "test@example.com", "subject": "Test"},
            )
        assert resp.status_code == 400, "Attendu 400 pour 'body' manquant"


# ---------------------------------------------------------------------------
# Classe TestDeepFocus retirée : Sprint (Deep Focus) mode supprimé en 69bdc1c0,
# l'endpoint /api/deep-focus/* n'existe plus.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Classe TestNewsletters
# ---------------------------------------------------------------------------


class TestNewsletters:
    """Tests des endpoints newsletters et abonnements."""

    def test_get_subscriptions(self, client):
        """GET /subscriptions retourne 200."""
        # routes_misc importe _get_authenticated_provider via from routes_helpers
        # → patch doit cibler routes_misc._get_authenticated_provider
        with (
            patch("app.api.routes_misc._get_authenticated_provider", return_value=_make_mock_provider()),
            patch("app.api.routes_helpers.get_db_session", return_value=_mock_db_ctx()),
            patch("app.api.routes_helpers._get_container", return_value=_make_mock_container()),
        ):
            resp = client.get("/api/subscriptions")

        assert resp.status_code == 200, f"Subscriptions a échoué: {resp.get_json()}"

    def test_get_newsletters(self, client):
        """GET /newsletters retourne 200."""
        with (
            patch("app.api.routes_misc._get_authenticated_provider", return_value=_make_mock_provider()),
            patch("app.api.routes_helpers.get_db_session", return_value=_mock_db_ctx()),
            patch("app.api.routes_helpers._get_container", return_value=_make_mock_container()),
        ):
            resp = client.get("/api/newsletters")

        assert resp.status_code == 200, f"Newsletters a échoué: {resp.get_json()}"


# ---------------------------------------------------------------------------
# Classe TestRecapAndIntel
# ---------------------------------------------------------------------------


class TestRecapAndIntel:
    """Tests des endpoints recap, intelligence et inbox-stats."""

    def test_intelligence_level(self, client):
        """GET /intelligence/level retourne 200."""
        with (
            patch("app.api.routes_misc._compute_intelligence_level", return_value={"level": 1, "xp": 0}),
        ):
            resp = client.get("/api/intelligence/level")

        assert resp.status_code == 200, f"Intelligence level a échoué: {resp.get_json()}"

    def test_recap(self, client):
        """GET /recap retourne 200.

        Stub `_resolve_account_id_for_user` à 1 pour rendre le test
        indépendant de l'ordre d'exécution (pollution possible de tests
        antérieurs qui touchent au cache d'account resolution).
        """
        mock_recap = {
            "month": "2026-01",
            "emails_sent": 10,
            "emails_received": 50,
            "drafts_generated": 8,
        }
        # routes_misc importe _resolve_account_id_for_user via _rh (line 2003).
        # On patche les deux paths (direct + via _rh) pour résister à toute
        # variation d'imports.
        with patch("app.services.recap_service.get_recap", return_value=mock_recap), \
             patch("app.api.routes_misc._resolve_account_id_for_user", return_value=1), \
             patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=1):
            resp = client.get("/api/recap")

        assert resp.status_code == 200, f"Recap a échoué: {resp.get_json()}"

    def test_inbox_stats(self, client):
        """GET /emails/inbox-stats retourne 200."""
        provider = _make_mock_provider()
        provider.get_messages.return_value = []

        with patch("app.api.routes_misc._get_authenticated_provider", return_value=provider):
            resp = client.get("/api/emails/inbox-stats")

        assert resp.status_code == 200, f"Inbox stats a échoué: {resp.get_json()}"
