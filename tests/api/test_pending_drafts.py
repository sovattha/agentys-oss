# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour les endpoints API de brouillons en attente.

Ces tests vérifient:
- GET /api/pending-drafts - Liste des brouillons en attente
- GET /api/pending-drafts/<id> - Récupération d'un brouillon
- POST /api/pending-drafts/<id>/validate - Validation d'un brouillon
- POST /api/pending-drafts/<id>/reject - Rejet d'un brouillon
- PATCH /api/pending-drafts/<id> - Mise à jour d'un brouillon

Coverage target: app/api/routes.py lines 2225-2383
"""

import pytest
from unittest.mock import Mock, patch
from datetime import datetime

pytest.importorskip("flask_cors")

from app.domain.entities.pending_draft import PendingDraftStatus


# ============================================================================
# FIXTURES
# ============================================================================


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


@pytest.fixture(autouse=True)
def mock_resolve_account():
    """Mock account resolution pour éviter les 403 dans les tests."""
    with patch("app.api.routes_pending._resolve_account_id_cached", return_value=1):
        yield


def _create_mock_pending_draft(
    draft_id="pending-123",
    email_id="email-123",
    email_subject="Test Subject",
    email_sender="sender@example.com",
    email_body="Original email body",
    draft_subject="Re: Test Subject",
    draft_body="Draft response body",
    status=PendingDraftStatus.PENDING,
    created_at=None,
    routing_tier="followup",
):
    """Factory pour créer un mock PendingDraft.

    routing_tier défaut à "followup" depuis 2026-05-13 : /api/pending-drafts
    filtre maintenant pour ne montrer que les drafts générés par les
    Quick Steps (cf. routes_pending.py:list_pending_drafts). Les tests qui
    veulent tester le filtrage passent un autre tier explicitement.
    """
    mock = Mock()
    mock.id = draft_id
    mock.email_id = email_id
    mock.email_subject = email_subject
    mock.email_sender = email_sender
    mock.email_body = email_body
    mock.draft_subject = draft_subject
    mock.draft_body = draft_body
    mock.routing_tier = routing_tier
    mock.status = status if isinstance(status, PendingDraftStatus) else PendingDraftStatus[status]
    mock.account_id = 1
    mock.created_at = created_at or datetime.now()
    # Mirror a real PendingDraft: `emoji_marker` defaults to None. Without
    # this, `Mock().emoji_marker` auto-returns a child Mock — which is truthy
    # and not JSON-serializable, so list_pending_drafts would 500 when it
    # copies the marker onto the summary (cf. routes_pending.py).
    mock.emoji_marker = None
    summary_dict = {
        "id": draft_id,
        "email_id": email_id,
        "email_subject": email_subject,
        "email_sender": email_sender,
        "draft_subject": draft_subject,
        "routing_tier": routing_tier,
        "status": mock.status.value,
        "created_at": mock.created_at.isoformat(),
        "emoji_marker": None,
    }
    full_dict = {
        **summary_dict,
        "email_body": email_body,
        "draft_body": draft_body,
    }
    mock.to_dict.return_value = full_dict
    mock.to_dict_summary.return_value = summary_dict
    return mock


def _setup_mock_pending_draft_store(mock_get_container, pending_drafts=None, count=0):
    """Configure le mock container avec un store de pending drafts."""
    mock_store = Mock()
    mock_store.get_pending.return_value = pending_drafts or []
    mock_store.count_pending.return_value = count if pending_drafts is None else len(pending_drafts)
    mock_store.get_by_id.return_value = None
    # routes_pending.py:797 / 958 / 998 utilisent `if (not) store.update_status(...)`
    # comme garde anti-double-action. None ferait toujours retomber sur 409.
    mock_store.update_status.return_value = True
    mock_store.update_content.return_value = None
    # `validate_pending_draft` (audit Reply-HIGH-4 "refine/send race") wraps
    # the send path in `with store.get_draft_lock(draft_id):` — give the
    # mock a real context manager so the test path doesn't TypeError.
    from contextlib import nullcontext
    mock_store.get_draft_lock.return_value = nullcontext()

    mock_container = Mock()
    mock_container.get_pending_draft_store.return_value = mock_store
    mock_get_container.return_value = mock_container

    return mock_store, mock_container


# ============================================================================
# TESTS - LIST PENDING DRAFTS
# ============================================================================


class TestListPendingDrafts:
    """Tests pour GET /api/pending-drafts."""

    @patch("app.api.routes_helpers._get_container")
    def test_list_pending_drafts_empty(self, mock_get_container, client):
        """Liste vide de brouillons en attente."""
        _setup_mock_pending_draft_store(mock_get_container, [], 0)

        response = client.get("/api/pending-drafts")
        data = response.get_json()

        assert response.status_code == 200
        assert data["count"] == 0
        assert data["pending_count"] == 0
        assert data["drafts"] == []

    @patch("app.services.reminder_service.list_draft_followups")
    @patch("app.api.routes_helpers._get_container")
    def test_snoozed_followup_draft_is_hidden_until_due(
        self, mock_get_container, mock_list_followups, client,
    ):
        """A follow-up draft whose snooze hasn't elapsed (reminder still
        notified=False) is HIDDEN from /api/pending-drafts — while snoozed
        it lives only in "Later" (/api/pending-drafts/snoozed).

        The wake-sweep flips the reminder to notified=True once delay_days
        passes with no reply, which is what surfaces the draft here (with its
        🔁 chip). A draft with no draft_followup reminder at all (the common
        non-followup case) is unaffected and still surfaces.

        This reverses the short-lived 2026-05-13 behavior that surfaced
        snoozed drafts here with a `snoozed_until` chip — see
        `_filter_snoozed_followup_drafts` in routes_pending.py.
        """
        drafts = [
            _create_mock_pending_draft("snoozed-1", "thread-1"),
            _create_mock_pending_draft("regular-2", "email-2"),
        ]
        _setup_mock_pending_draft_store(mock_get_container, drafts, 2)
        mock_list_followups.return_value = [
            {"email_id": "snoozed-1", "notified": False, "account_id": 1,
             "reminder_date": "2030-01-01T00:00:00+00:00", "type": "draft_followup"},
        ]

        response = client.get("/api/pending-drafts")
        data = response.get_json()

        assert response.status_code == 200
        ids = {d["id"] for d in data["drafts"]}
        # The still-snoozed draft is filtered out; the unrelated one stays.
        assert "snoozed-1" not in ids
        assert "regular-2" in ids

    @patch("app.services.reminder_service.list_draft_followups")
    @patch("app.api.routes_helpers._get_container")
    def test_promoted_draft_has_no_snoozed_until(
        self, mock_get_container, mock_list_followups, client,
    ):
        """Once the wake sweep flips notified=True the reminder is no
        longer "active" — the draft shows up without the `snoozed_until`
        chip enrichment (it's ready to send, not still snoozed)."""
        drafts = [_create_mock_pending_draft("promoted-1", "thread-1")]
        _setup_mock_pending_draft_store(mock_get_container, drafts, 1)
        mock_list_followups.return_value = [
            {"email_id": "promoted-1", "notified": True, "account_id": 1,
             "reminder_date": "2020-01-01T00:00:00+00:00", "type": "draft_followup"},
        ]

        response = client.get("/api/pending-drafts")
        data = response.get_json()

        assert response.status_code == 200
        assert len(data["drafts"]) == 1
        assert data["drafts"][0]["id"] == "promoted-1"
        # notified=True → no chip enrichment
        assert "snoozed_until" not in data["drafts"][0]

    @patch("app.services.reminder_service.list_draft_followups")
    @patch("app.api.routes_helpers._get_container")
    def test_non_followup_tier_drafts_are_filtered_out(
        self, mock_get_container, mock_list_followups, client,
    ):
        """User policy 2026-05-13: only routing_tier=followup drafts
        surface in /api/pending-drafts. The legacy AI reply-suggestion
        pipeline (simple/standard/complex tiers) generates context-bound
        drafts that should not pollute the global Drafts panel."""
        drafts = [
            _create_mock_pending_draft("followup-1", "t1", routing_tier="followup"),
            _create_mock_pending_draft("standard-2", "t2", routing_tier="standard"),
            _create_mock_pending_draft("complex-3", "t3", routing_tier="complex"),
        ]
        _setup_mock_pending_draft_store(mock_get_container, drafts, 3)
        mock_list_followups.return_value = []

        response = client.get("/api/pending-drafts")
        data = response.get_json()

        assert response.status_code == 200
        ids = {d["id"] for d in data["drafts"]}
        assert ids == {"followup-1"}

    @patch("app.api.routes_helpers._get_container")
    def test_list_pending_drafts_with_items(self, mock_get_container, client):
        """Liste avec des brouillons en attente."""
        drafts = [
            _create_mock_pending_draft("pending-1", "email-1"),
            _create_mock_pending_draft("pending-2", "email-2"),
        ]
        _setup_mock_pending_draft_store(mock_get_container, drafts, 2)

        response = client.get("/api/pending-drafts")
        data = response.get_json()

        assert response.status_code == 200
        assert data["count"] == 2
        assert data["pending_count"] == 2
        assert len(data["drafts"]) == 2

    @patch("app.api.routes_helpers._get_container")
    def test_list_pending_drafts_with_limit(self, mock_get_container, client):
        """Liste avec limite custom."""
        mock_store, _ = _setup_mock_pending_draft_store(mock_get_container, [], 0)

        response = client.get("/api/pending-drafts?limit=10")

        assert response.status_code == 200
        mock_store.get_pending.assert_called_once_with(limit=10, account_id="1")

    @patch("app.api.routes_helpers._get_container")
    def test_list_pending_drafts_limit_clamped_min(self, mock_get_container, client):
        """Limite minimale à 1."""
        mock_store, _ = _setup_mock_pending_draft_store(mock_get_container, [], 0)

        response = client.get("/api/pending-drafts?limit=0")

        assert response.status_code == 200
        mock_store.get_pending.assert_called_once_with(limit=1, account_id="1")

    @patch("app.api.routes_helpers._get_container")
    def test_list_pending_drafts_limit_clamped_max(self, mock_get_container, client):
        """Limite maximale à 100."""
        mock_store, _ = _setup_mock_pending_draft_store(mock_get_container, [], 0)

        response = client.get("/api/pending-drafts?limit=500")

        assert response.status_code == 200
        mock_store.get_pending.assert_called_once_with(limit=100, account_id="1")

    @patch("app.api.routes_helpers._get_container")
    def test_list_pending_drafts_default_limit(self, mock_get_container, client):
        """Limite par défaut à 50."""
        mock_store, _ = _setup_mock_pending_draft_store(mock_get_container, [], 0)

        response = client.get("/api/pending-drafts")

        assert response.status_code == 200
        mock_store.get_pending.assert_called_once_with(limit=50, account_id="1")

    @patch("app.api.routes_helpers._get_container")
    def test_list_pending_drafts_internal_error(self, mock_get_container, client):
        """Erreur interne lors de la liste."""
        mock_store, _ = _setup_mock_pending_draft_store(mock_get_container, [], 0)
        mock_store.get_pending.side_effect = Exception("Database error")

        response = client.get("/api/pending-drafts")
        data = response.get_json()

        assert response.status_code == 500
        assert "error" in data


# ============================================================================
# TESTS - GET PENDING DRAFT
# ============================================================================


class TestGetPendingDraft:
    """Tests pour GET /api/pending-drafts/<id>."""

    @patch("app.api.routes_helpers._get_container")
    def test_get_pending_draft_success(self, mock_get_container, client):
        """Récupération réussie d'un brouillon."""
        draft = _create_mock_pending_draft("pending-123")
        mock_store, _ = _setup_mock_pending_draft_store(mock_get_container)
        mock_store.get_by_id.return_value = draft

        response = client.get("/api/pending-drafts/pending-123")
        data = response.get_json()

        assert response.status_code == 200
        assert data["id"] == "pending-123"
        mock_store.get_by_id.assert_called_once_with("pending-123")

    @patch("app.api.routes_helpers._get_container")
    def test_get_pending_draft_not_found(self, mock_get_container, client):
        """Brouillon non trouvé."""
        mock_store, _ = _setup_mock_pending_draft_store(mock_get_container)
        mock_store.get_by_id.return_value = None

        response = client.get("/api/pending-drafts/nonexistent")
        data = response.get_json()

        assert response.status_code == 404
        assert "error" in data
        assert "not found" in data["error"].lower()

    def test_get_pending_draft_invalid_id(self, client):
        """ID de brouillon invalide - URL avec script tag retourne 404 (Flask routing)."""
        response = client.get("/api/pending-drafts/<script>alert(1)</script>")
        # Flask routing returns 404 for URL-encoded special chars
        assert response.status_code == 404

    @patch("app.api.routes_helpers._get_container")
    def test_get_pending_draft_internal_error(self, mock_get_container, client):
        """Erreur interne lors de la récupération."""
        mock_store, _ = _setup_mock_pending_draft_store(mock_get_container)
        mock_store.get_by_id.side_effect = Exception("Database error")

        response = client.get("/api/pending-drafts/pending-123")
        data = response.get_json()

        assert response.status_code == 500
        assert "error" in data


# ============================================================================
# TESTS - VALIDATE PENDING DRAFT
# ============================================================================


class TestValidatePendingDraft:
    """Tests pour POST /api/pending-drafts/<id>/validate.

    Story 6-7: validate endpoint now creates AND sends the draft.
    """

    @patch("app.api.routes_pending._get_authenticated_provider")
    @patch("app.api.routes_helpers._get_container")
    def test_validate_pending_draft_success(
        self, mock_get_container, mock_get_provider, client
    ):
        """Validation réussie d'un brouillon - Story 6-7: create AND send."""
        draft = _create_mock_pending_draft("pending-123")
        mock_store, _ = _setup_mock_pending_draft_store(mock_get_container)
        mock_store.get_by_id.return_value = draft

        mock_provider = Mock()
        mock_provider.send_reply_directly = Mock(return_value=False)
        mock_provider.create_draft.return_value = "gmail-draft-id-456"
        mock_provider.send_draft.return_value = True  # Story 6-7: send succeeds
        mock_provider.mark_as_read.return_value = True
        mock_get_provider.return_value = mock_provider

        response = client.post("/api/pending-drafts/pending-123/validate")
        data = response.get_json()

        assert response.status_code == 200
        assert data["success"] is True
        assert data["draft_id"] == "pending-123"
        assert data["gmail_draft_id"] == "gmail-draft-id-456"
        assert data["sent"] is True  # Story 6-7: AC1
        assert data["message"] == "Email sent successfully"  # Story 6-7: AC2 (English post-2026-05-18 i18n sweep)

        mock_provider.create_draft.assert_called_once()
        mock_provider.send_draft.assert_called_once_with("gmail-draft-id-456")  # Story 6-7
        # mark_as_read is called in background thread — not assertable synchronously
        mock_store.update_status.assert_called_once()

    @patch("app.api.routes_pending._get_authenticated_provider")
    @patch("app.api.routes_helpers._get_container")
    def test_validate_pending_draft_send_fails(
        self, mock_get_container, mock_get_provider, client
    ):
        """Story 6-7 AC3: Draft created but send fails returns error."""
        draft = _create_mock_pending_draft("pending-123")
        mock_store, _ = _setup_mock_pending_draft_store(mock_get_container)
        mock_store.get_by_id.return_value = draft

        mock_provider = Mock()
        mock_provider.send_reply_directly = Mock(return_value=False)
        mock_provider.create_draft.return_value = "gmail-draft-id-456"
        mock_provider.send_draft.return_value = False  # Send fails
        mock_get_provider.return_value = mock_provider

        response = client.post("/api/pending-drafts/pending-123/validate")
        data = response.get_json()

        assert response.status_code == 500
        assert "error" in data
        assert "failed to send" in data["error"].lower()
        assert data["gmail_draft_id"] == "gmail-draft-id-456"  # Draft was created
        mock_store.update_status.assert_called_once()  # Status set to VALIDATED (not SENT)

    @patch("app.api.routes_helpers._get_container")
    def test_validate_pending_draft_not_found(self, mock_get_container, client):
        """Brouillon à valider non trouvé."""
        mock_store, _ = _setup_mock_pending_draft_store(mock_get_container)
        mock_store.get_by_id.return_value = None

        response = client.post("/api/pending-drafts/nonexistent/validate")
        data = response.get_json()

        assert response.status_code == 404
        assert "error" in data

    def test_validate_pending_draft_invalid_id(self, client):
        """ID invalide pour validation."""
        response = client.post("/api/pending-drafts/invalid<id>/validate")
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    @patch("app.api.routes_pending._get_authenticated_provider")
    @patch("app.api.routes_helpers._get_container")
    def test_validate_pending_draft_create_fails(
        self, mock_get_container, mock_get_provider, client
    ):
        """Échec de création du brouillon Gmail."""
        draft = _create_mock_pending_draft("pending-123")
        mock_store, _ = _setup_mock_pending_draft_store(mock_get_container)
        mock_store.get_by_id.return_value = draft

        mock_provider = Mock()
        mock_provider.send_reply_directly = Mock(return_value=False)
        mock_provider.create_draft.return_value = None
        mock_provider._last_error = ""
        mock_get_provider.return_value = mock_provider

        response = client.post("/api/pending-drafts/pending-123/validate")
        data = response.get_json()

        assert response.status_code == 500
        assert "error" in data
        assert "failed" in data["error"].lower()

    @patch("app.api.routes_pending._get_authenticated_provider")
    @patch("app.api.routes_helpers._get_container")
    def test_validate_pending_draft_internal_error(
        self, mock_get_container, mock_get_provider, client
    ):
        """Erreur interne lors de la validation."""
        draft = _create_mock_pending_draft("pending-123")
        mock_store, _ = _setup_mock_pending_draft_store(mock_get_container)
        mock_store.get_by_id.return_value = draft

        mock_provider = Mock()
        mock_provider.send_reply_directly = Mock(return_value=False)
        mock_provider.create_draft.side_effect = Exception("API error")
        mock_get_provider.return_value = mock_provider

        response = client.post("/api/pending-drafts/pending-123/validate")
        data = response.get_json()

        assert response.status_code == 500
        assert "error" in data


# ============================================================================
# TESTS - REJECT PENDING DRAFT
# ============================================================================


class TestRejectPendingDraft:
    """Tests pour POST /api/pending-drafts/<id>/reject."""

    @patch("app.api.routes_helpers._get_container")
    def test_reject_pending_draft_success(self, mock_get_container, client):
        """Rejet réussi d'un brouillon."""
        draft = _create_mock_pending_draft("pending-123")
        mock_store, _ = _setup_mock_pending_draft_store(mock_get_container)
        mock_store.get_by_id.return_value = draft

        response = client.post("/api/pending-drafts/pending-123/reject")
        data = response.get_json()

        assert response.status_code == 200
        assert data["success"] is True
        assert data["draft_id"] == "pending-123"
        mock_store.update_status.assert_called_once()

    @patch("app.services.pinned_emails.remove_pinned_email_id")
    @patch("app.api.routes_helpers._get_container")
    def test_reject_unpins_followup_draft(self, mock_get_container, mock_unpin, client):
        """Rejeter un follow-up retire son pin (pin id == thread_id == email_id)."""
        draft = _create_mock_pending_draft(
            "pending-123", email_id="thread-9", routing_tier="followup",
        )
        mock_store, _ = _setup_mock_pending_draft_store(mock_get_container)
        mock_store.get_by_id.return_value = draft

        response = client.post("/api/pending-drafts/pending-123/reject")

        assert response.status_code == 200
        # account id resolves to 1 (autouse fixture); email_id is the thread id.
        mock_unpin.assert_called_once_with(1, "thread-9")

    @patch("app.services.pinned_emails.remove_pinned_email_id")
    @patch("app.api.routes_helpers._get_container")
    def test_reject_non_followup_does_not_unpin(self, mock_get_container, mock_unpin, client):
        """Un brouillon non-follow-up n'est jamais désépinglé."""
        draft = _create_mock_pending_draft("pending-123", routing_tier="standard")
        mock_store, _ = _setup_mock_pending_draft_store(mock_get_container)
        mock_store.get_by_id.return_value = draft

        response = client.post("/api/pending-drafts/pending-123/reject")

        assert response.status_code == 200
        mock_unpin.assert_not_called()

    @patch("app.api.routes_helpers._get_container")
    def test_reject_pending_draft_not_found(self, mock_get_container, client):
        """Brouillon à rejeter non trouvé."""
        mock_store, _ = _setup_mock_pending_draft_store(mock_get_container)
        mock_store.get_by_id.return_value = None

        response = client.post("/api/pending-drafts/nonexistent/reject")
        data = response.get_json()

        assert response.status_code == 404
        assert "error" in data

    def test_reject_pending_draft_invalid_id(self, client):
        """ID invalide pour rejet."""
        response = client.post("/api/pending-drafts/invalid<id>/reject")
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    @patch("app.api.routes_helpers._get_container")
    def test_reject_pending_draft_internal_error(self, mock_get_container, client):
        """Erreur interne lors du rejet."""
        draft = _create_mock_pending_draft("pending-123")
        mock_store, _ = _setup_mock_pending_draft_store(mock_get_container)
        mock_store.get_by_id.return_value = draft
        mock_store.update_status.side_effect = Exception("Database error")

        response = client.post("/api/pending-drafts/pending-123/reject")
        data = response.get_json()

        assert response.status_code == 500
        assert "error" in data


# ============================================================================
# TESTS - UPDATE PENDING DRAFT
# ============================================================================


class TestUpdatePendingDraft:
    """Tests pour PATCH /api/pending-drafts/<id>."""

    @patch("app.api.routes_helpers._get_container")
    def test_update_pending_draft_subject_only(self, mock_get_container, client):
        """Mise à jour du sujet uniquement."""
        draft = _create_mock_pending_draft("pending-123")
        mock_store, _ = _setup_mock_pending_draft_store(mock_get_container)
        mock_store.get_by_id.return_value = draft

        response = client.patch(
            "/api/pending-drafts/pending-123",
            json={"subject": "New Subject"}
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["success"] is True
        mock_store.update_content.assert_called_once_with(
            "pending-123", "New Subject", "Draft response body"
        )

    @patch("app.api.routes_helpers._get_container")
    def test_update_pending_draft_body_only(self, mock_get_container, client):
        """Mise à jour du corps uniquement."""
        draft = _create_mock_pending_draft("pending-123")
        mock_store, _ = _setup_mock_pending_draft_store(mock_get_container)
        mock_store.get_by_id.return_value = draft

        response = client.patch(
            "/api/pending-drafts/pending-123",
            json={"body": "New body content"}
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["success"] is True
        mock_store.update_content.assert_called_once_with(
            "pending-123", "Re: Test Subject", "New body content"
        )

    @patch("app.api.routes_helpers._get_container")
    def test_update_pending_draft_both_fields(self, mock_get_container, client):
        """Mise à jour du sujet et du corps."""
        draft = _create_mock_pending_draft("pending-123")
        mock_store, _ = _setup_mock_pending_draft_store(mock_get_container)
        mock_store.get_by_id.return_value = draft

        response = client.patch(
            "/api/pending-drafts/pending-123",
            json={"subject": "New Subject", "body": "New body"}
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["success"] is True
        mock_store.update_content.assert_called_once_with(
            "pending-123", "New Subject", "New body"
        )

    @patch("app.api.routes_helpers._get_container")
    def test_update_pending_draft_not_found(self, mock_get_container, client):
        """Brouillon à mettre à jour non trouvé."""
        mock_store, _ = _setup_mock_pending_draft_store(mock_get_container)
        mock_store.get_by_id.return_value = None

        response = client.patch(
            "/api/pending-drafts/nonexistent",
            json={"body": "New body"}
        )
        data = response.get_json()

        assert response.status_code == 404
        assert "error" in data

    def test_update_pending_draft_invalid_id(self, client):
        """ID invalide pour mise à jour."""
        response = client.patch(
            "/api/pending-drafts/invalid<id>",
            json={"body": "New body"}
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    def test_update_pending_draft_no_json(self, client):
        """Requête sans JSON retourne un 400 propre.

        Depuis le durcissement des gardes JSON (audit STAB-02), `require_json`
        utilise `get_json(silent=True)` et renvoie un 400 explicite plutôt que
        de laisser werkzeug lever un 415/BadRequest qui serait re-wrappé en 500.
        """
        response = client.patch(
            "/api/pending-drafts/pending-123",
            data="not json",
            content_type="text/plain"
        )
        assert response.status_code == 400

    def test_update_pending_draft_subject_not_string(self, client):
        """Sujet non-string."""
        response = client.patch(
            "/api/pending-drafts/pending-123",
            json={"subject": 123}
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "subject" in data["error"].lower()

    def test_update_pending_draft_body_not_string(self, client):
        """Corps non-string."""
        response = client.patch(
            "/api/pending-drafts/pending-123",
            json={"body": ["not", "a", "string"]}
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "body" in data["error"].lower()

    @patch("app.api.routes_helpers._get_container")
    def test_update_pending_draft_internal_error(self, mock_get_container, client):
        """Erreur interne lors de la mise à jour."""
        draft = _create_mock_pending_draft("pending-123")
        mock_store, _ = _setup_mock_pending_draft_store(mock_get_container)
        mock_store.get_by_id.return_value = draft
        mock_store.update_content.side_effect = Exception("Database error")

        response = client.patch(
            "/api/pending-drafts/pending-123",
            json={"body": "New body"}
        )
        data = response.get_json()

        assert response.status_code == 500
        assert "error" in data


# ============================================================================
# TESTS - ID VALIDATION EDGE CASES
# ============================================================================


class TestPendingDraftIdValidation:
    """Tests pour la validation des IDs de brouillons en attente."""

    def test_id_with_special_chars(self, client):
        """ID avec caractères spéciaux - validation rejects them as 400."""
        response = client.get("/api/pending-drafts/id@%23$%25")
        # The API validates the ID and rejects special chars as 400
        assert response.status_code == 400

    def test_id_too_long(self, client):
        """ID trop long."""
        long_id = "a" * 300
        response = client.get(f"/api/pending-drafts/{long_id}")
        assert response.status_code == 400

    def test_id_with_path_traversal(self, client):
        """ID avec tentative de path traversal - Flask routing handles this."""
        response = client.get("/api/pending-drafts/../../../etc/passwd")
        # Flask URL routing treats this as a different route, returns 404
        assert response.status_code == 404

    @patch("app.api.routes_helpers._get_container")
    def test_valid_uuid_format(self, mock_get_container, client):
        """ID au format UUID valide."""
        mock_store, _ = _setup_mock_pending_draft_store(mock_get_container)
        mock_store.get_by_id.return_value = None

        response = client.get("/api/pending-drafts/550e8400-e29b-41d4-a716-446655440000")
        # Should reach the store (valid ID format), then 404 (not found)
        assert response.status_code == 404

    @patch("app.api.routes_helpers._get_container")
    def test_valid_alphanumeric_id(self, mock_get_container, client):
        """ID alphanumérique valide."""
        mock_store, _ = _setup_mock_pending_draft_store(mock_get_container)
        mock_store.get_by_id.return_value = None

        response = client.get("/api/pending-drafts/pending123abc")
        assert response.status_code == 404


# ============================================================================
# TESTS - EMPTY/NULL VALUES
# ============================================================================


class TestPendingDraftEmptyValues:
    """Tests pour les valeurs vides ou nulles."""

    @patch("app.api.routes_helpers._get_container")
    def test_update_with_empty_string_subject(self, mock_get_container, client):
        """Mise à jour avec sujet vide."""
        draft = _create_mock_pending_draft("pending-123")
        mock_store, _ = _setup_mock_pending_draft_store(mock_get_container)
        mock_store.get_by_id.return_value = draft

        response = client.patch(
            "/api/pending-drafts/pending-123",
            json={"subject": ""}
        )
        response.get_json()

        # Empty string is a valid string, should be accepted
        assert response.status_code == 200

    @patch("app.api.routes_helpers._get_container")
    def test_update_with_null_subject(self, mock_get_container, client):
        """Mise à jour avec sujet null (garde l'ancien)."""
        draft = _create_mock_pending_draft("pending-123")
        mock_store, _ = _setup_mock_pending_draft_store(mock_get_container)
        mock_store.get_by_id.return_value = draft

        response = client.patch(
            "/api/pending-drafts/pending-123",
            json={"subject": None, "body": "New body"}
        )
        response.get_json()

        assert response.status_code == 200
        mock_store.update_content.assert_called_once_with(
            "pending-123", "Re: Test Subject", "New body"
        )

    @patch("app.api.routes_helpers._get_container")
    def test_update_with_whitespace_only_body(self, mock_get_container, client):
        """Mise à jour avec corps composé uniquement d'espaces."""
        draft = _create_mock_pending_draft("pending-123")
        mock_store, _ = _setup_mock_pending_draft_store(mock_get_container)
        mock_store.get_by_id.return_value = draft

        response = client.patch(
            "/api/pending-drafts/pending-123",
            json={"body": "   "}
        )
        response.get_json()

        # Whitespace-only is a valid string
        assert response.status_code == 200


# ============================================================================
# TESTS - HTTP EXCEPTION HANDLING
# ============================================================================


class TestPendingDraftHttpExceptions:
    """Tests pour la gestion des exceptions HTTP."""

    @patch("app.api.routes_pending._get_authenticated_provider")
    @patch("app.api.routes_helpers._get_container")
    def test_validate_reraises_http_exception(
        self, mock_get_container, mock_get_provider, client
    ):
        """HTTPException est relancée lors de la validation."""
        from werkzeug.exceptions import Unauthorized

        draft = _create_mock_pending_draft("pending-123")
        mock_store, _ = _setup_mock_pending_draft_store(mock_get_container)
        mock_store.get_by_id.return_value = draft

        mock_get_provider.side_effect = Unauthorized("Not authenticated")

        response = client.post("/api/pending-drafts/pending-123/validate")

        assert response.status_code == 401


# ============================================================================
# TESTS - UNICODE AND SPECIAL CONTENT
# ============================================================================


class TestPendingDraftUnicodeContent:
    """Tests pour le contenu Unicode et spécial."""

    @patch("app.api.routes_helpers._get_container")
    def test_update_with_unicode_content(self, mock_get_container, client):
        """Mise à jour avec contenu Unicode."""
        draft = _create_mock_pending_draft("pending-123")
        mock_store, _ = _setup_mock_pending_draft_store(mock_get_container)
        mock_store.get_by_id.return_value = draft

        response = client.patch(
            "/api/pending-drafts/pending-123",
            json={
                "subject": "日本語の件名 🎉",
                "body": "Contenu avec émojis 👋 et caractères spéciaux: ñ ü ß"
            }
        )
        response.get_json()

        assert response.status_code == 200

    @patch("app.api.routes_helpers._get_container")
    def test_update_with_html_content(self, mock_get_container, client):
        """Mise à jour avec contenu HTML (non échappé au niveau API)."""
        draft = _create_mock_pending_draft("pending-123")
        mock_store, _ = _setup_mock_pending_draft_store(mock_get_container)
        mock_store.get_by_id.return_value = draft

        response = client.patch(
            "/api/pending-drafts/pending-123",
            json={"body": "<p>Hello <b>World</b></p>"}
        )
        response.get_json()

        assert response.status_code == 200

    @patch("app.api.routes_helpers._get_container")
    def test_update_with_newlines(self, mock_get_container, client):
        """Mise à jour avec retours à la ligne."""
        draft = _create_mock_pending_draft("pending-123")
        mock_store, _ = _setup_mock_pending_draft_store(mock_get_container)
        mock_store.get_by_id.return_value = draft

        response = client.patch(
            "/api/pending-drafts/pending-123",
            json={"body": "Line 1\nLine 2\r\nLine 3\n\nParagraph 2"}
        )
        response.get_json()

        assert response.status_code == 200
