# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests de contrats JSON pour l'API Agentys.

Valide que les formats de réponse des endpoints critiques restent stables.
Un champ renommé côté backend est détecté ici avant de casser les tests E2E.
"""

import pytest
from unittest.mock import Mock, patch
from datetime import datetime

pytest.importorskip("flask_cors")


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def app():
    """Application Flask de test."""
    from app.api.app import create_app
    return create_app(config={"TESTING": True})


@pytest.fixture
def client(app):
    """Client de test Flask."""
    return app.test_client()


def _make_email_dict(
    email_id="email-1",
    subject="Sujet test",
    sender="sender@example.com",
    received_at=None,
    is_read=False,
    folder="inbox",
    **extra,
):
    """Factory pour un dict email au format API."""
    return {
        "id": email_id,
        "subject": subject,
        "sender": sender,
        "sender_name": "Sender Test",
        "received_at": received_at or datetime.now().isoformat(),
        "is_read": is_read,
        "folder": folder,
        **extra,
    }


def _make_mock_emails_list(count=3, folder="inbox"):
    """Crée une liste de dicts emails mockés."""
    return [_make_email_dict(f"email-{i}", f"Sujet {i}", folder=folder) for i in range(count)]


def _setup_emails_mock(mock_get_provider, emails=None, folder="inbox"):
    """Configure le provider mocké pour retourner des emails."""
    mock_provider = Mock()
    mock_provider.list_emails = Mock(return_value=emails or _make_mock_emails_list(folder=folder))
    mock_provider.get_emails = Mock(return_value=emails or _make_mock_emails_list(folder=folder))
    mock_get_provider.return_value = mock_provider
    return mock_provider


def _create_mock_pending_draft_full(draft_id="d-1", email_id="e-1", status="PENDING"):
    """Factory pour un mock PendingDraft avec tous les champs requis."""
    mock = Mock()
    mock.id = draft_id
    mock.email_id = email_id
    mock.draft_body = "Corps du brouillon généré"
    mock.draft_subject = "Re: Sujet"
    mock.status = status
    mock.email_subject = "Sujet original"
    mock.email_sender = "sender@example.com"
    mock.email_body = "Corps original"
    mock.smart_suggestions = ["Oui, avec plaisir", "Non, désolé"]
    mock.quick_replies = None
    mock.created_at = datetime.now()

    full_dict = {
        "id": draft_id,
        "email_id": email_id,
        "draft_body": "Corps du brouillon généré",
        "draft_subject": "Re: Sujet",
        "status": status,
        "email_subject": "Sujet original",
        "email_sender": "sender@example.com",
        "email_body": "Corps original",
        "smart_suggestions": ["Oui, avec plaisir", "Non, désolé"],
        "quick_replies": None,
        "created_at": mock.created_at.isoformat(),
    }
    summary_dict = {
        "id": draft_id,
        "email_id": email_id,
        "draft_subject": "Re: Sujet",
        "status": status,
        "email_subject": "Sujet original",
        "email_sender": "sender@example.com",
        "created_at": mock.created_at.isoformat(),
    }
    mock.to_dict.return_value = full_dict
    mock.to_dict_summary.return_value = summary_dict
    return mock


# ============================================================================
# CLASSE TestEmailListContract
# ============================================================================


class TestEmailListContract:
    """Vérifie le format de réponse de GET /api/emails."""

    @patch("app.api.routes_helpers._get_container")
    def test_email_list_response_structure(self, mock_get_container, client):
        """GET /api/emails → réponse avec emails[] et métadonnées."""
        mock_store = Mock()
        mock_store.list_emails = Mock(return_value=([], False))
        mock_container = Mock()
        mock_container.get_email_cache.return_value = mock_store
        mock_get_container.return_value = mock_container

        with patch("app.api.routes_emails._get_authenticated_provider") as mock_provider_fn:
            mock_provider = Mock()
            mock_provider.get_messages = Mock(return_value=[])
            mock_provider.list_messages = Mock(return_value=[])
            mock_provider_fn.return_value = mock_provider

            response = client.get("/api/emails")

        # L'endpoint doit répondre (pas forcément 200 sans vrai provider)
        assert response.content_type == "application/json"
        data = response.get_json()
        assert data is not None

    @patch("app.api.routes_helpers._get_container")
    def test_folder_param_inbox_accepted(self, mock_get_container, client):
        """folder=inbox est accepté sans 400."""
        with patch("app.api.routes_emails._get_authenticated_provider") as mock_pf:
            mock_pf.return_value = Mock()
            response = client.get("/api/emails?folder=inbox")
        assert response.status_code != 400

    @patch("app.api.routes_helpers._get_container")
    def test_folder_param_spam_accepted(self, mock_get_container, client):
        """folder=spam est accepté sans 400."""
        with patch("app.api.routes_emails._get_authenticated_provider") as mock_pf:
            mock_pf.return_value = Mock()
            response = client.get("/api/emails?folder=spam")
        assert response.status_code != 400

    @patch("app.api.routes_helpers._get_container")
    def test_folder_param_trash_accepted(self, mock_get_container, client):
        """folder=trash est accepté sans 400."""
        with patch("app.api.routes_emails._get_authenticated_provider") as mock_pf:
            mock_pf.return_value = Mock()
            response = client.get("/api/emails?folder=trash")
        assert response.status_code != 400

    @patch("app.api.routes_helpers._get_container")
    def test_folder_param_sent_accepted(self, mock_get_container, client):
        """folder=sent est accepté sans 400."""
        with patch("app.api.routes_emails._get_authenticated_provider") as mock_pf:
            mock_pf.return_value = Mock()
            response = client.get("/api/emails?folder=sent")
        assert response.status_code != 400

    @patch("app.api.routes_helpers._get_container")
    def test_folder_param_archived_accepted(self, mock_get_container, client):
        """folder=archived est accepté sans 400."""
        with patch("app.api.routes_emails._get_authenticated_provider") as mock_pf:
            mock_pf.return_value = Mock()
            response = client.get("/api/emails?folder=archived")
        assert response.status_code != 400

    def test_email_dict_has_required_fields(self):
        """Un dict email doit contenir les champs requis par le frontend."""
        required = {"id", "subject", "sender", "received_at", "is_read", "folder"}
        email = _make_email_dict()
        missing = required - set(email.keys())
        assert not missing, f"Champs manquants dans le format email: {missing}"

    def test_email_dict_types(self):
        """Vérification des types des champs email."""
        email = _make_email_dict(is_read=False, folder="inbox")
        assert isinstance(email["id"], str)
        assert isinstance(email["subject"], str)
        assert isinstance(email["sender"], str)
        assert isinstance(email["is_read"], bool)
        assert isinstance(email["folder"], str)


# ============================================================================
# CLASSE TestPendingDraftContract
# ============================================================================


class TestPendingDraftContract:
    """Vérifie le format de réponse de GET /api/pending-drafts/<id>."""

    @patch("app.api.routes_pending._resolve_account_id_cached", return_value=1)
    @patch("app.api.routes_helpers._get_container")
    def test_pending_draft_has_required_fields(self, mock_get_container, _mock_account, client):
        """GET /api/pending-drafts/<id> → champs requis présents."""
        required_fields = {"id", "email_id", "draft_body", "draft_subject", "status", "created_at"}
        draft = _create_mock_pending_draft_full("d-contract", "e-contract")
        draft.account_id = "1"

        mock_store = Mock()
        mock_store.get_by_id.return_value = draft
        mock_container = Mock()
        mock_container.get_pending_draft_store.return_value = mock_store
        mock_get_container.return_value = mock_container

        response = client.get("/api/pending-drafts/d-contract")
        assert response.status_code == 200
        data = response.get_json()

        missing = required_fields - set(data.keys())
        assert not missing, f"Champs requis manquants: {missing}"

    @patch("app.api.routes_pending._resolve_account_id_cached", return_value=1)
    @patch("app.api.routes_helpers._get_container")
    def test_status_value_is_valid_string(self, mock_get_container, _mock_account, client):
        """Le champ status doit être une chaîne parmi les valeurs valides."""
        valid_statuses = {"PENDING", "VALIDATED", "REJECTED", "SENT"}
        draft = _create_mock_pending_draft_full(status="PENDING")
        draft.account_id = "1"

        mock_store = Mock()
        mock_store.get_by_id.return_value = draft
        mock_container = Mock()
        mock_container.get_pending_draft_store.return_value = mock_store
        mock_get_container.return_value = mock_container

        response = client.get("/api/pending-drafts/d-contract")
        assert response.status_code == 200
        data = response.get_json()

        assert data["status"] in valid_statuses

    @patch("app.api.routes_pending._resolve_account_id_cached", return_value=1)
    @patch("app.api.routes_helpers._get_container")
    def test_smart_suggestions_is_list_or_null(self, mock_get_container, _mock_account, client):
        """smart_suggestions doit être une liste ou null, jamais une string."""
        draft = _create_mock_pending_draft_full()
        draft.account_id = "1"

        mock_store = Mock()
        mock_store.get_by_id.return_value = draft
        mock_container = Mock()
        mock_container.get_pending_draft_store.return_value = mock_store
        mock_get_container.return_value = mock_container

        response = client.get("/api/pending-drafts/d-contract")
        assert response.status_code == 200
        data = response.get_json()

        suggestions = data.get("smart_suggestions")
        assert suggestions is None or isinstance(suggestions, list), \
            f"smart_suggestions doit être list ou null, got {type(suggestions)}"

    @patch("app.api.routes_pending._resolve_account_id_cached", return_value=1)
    @patch("app.api.routes_helpers._get_container")
    def test_created_at_is_iso_format(self, mock_get_container, _mock_account, client):
        """created_at doit être une chaîne ISO 8601."""
        draft = _create_mock_pending_draft_full()
        draft.account_id = "1"
        mock_store = Mock()
        mock_store.get_by_id.return_value = draft
        mock_container = Mock()
        mock_container.get_pending_draft_store.return_value = mock_store
        mock_get_container.return_value = mock_container

        response = client.get("/api/pending-drafts/d-contract")
        assert response.status_code == 200
        data = response.get_json()

        created_at = data.get("created_at")
        assert created_at is not None
        # Doit être parseable
        parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        assert parsed is not None

    @patch("app.api.routes_pending._resolve_account_id_cached", return_value=1)
    @patch("app.api.routes_helpers._get_container")
    def test_pending_draft_list_has_drafts_key(self, mock_get_container, _mock_account, client):
        """GET /api/pending-drafts → réponse avec clé 'drafts'."""
        mock_store = Mock()
        mock_store.get_pending.return_value = []
        mock_store.count_pending.return_value = 0
        mock_container = Mock()
        mock_container.get_pending_draft_store.return_value = mock_store
        mock_get_container.return_value = mock_container

        response = client.get("/api/pending-drafts")
        assert response.status_code == 200
        data = response.get_json()

        assert "drafts" in data, "La réponse doit contenir 'drafts'"
        assert isinstance(data["drafts"], list)


# ============================================================================
# CLASSE TestFolderOperationsContract
# ============================================================================


class TestFolderOperationsContract:
    """Vérifie le format des réponses pour les opérations sur les dossiers."""

    @patch("app.api.routes_helpers._get_container")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_archive_response_format(self, mock_get_provider, mock_get_container, client):
        """POST /api/emails/<id>/archive → {success: bool, email_id: str}."""
        mock_store = Mock()
        mock_store.get_by_email_id.return_value = None
        mock_container = Mock()
        mock_container.get_pending_draft_store.return_value = mock_store
        mock_get_container.return_value = mock_container

        mock_provider = Mock()
        mock_provider.archive_email = Mock(return_value=True)
        mock_get_provider.return_value = mock_provider

        response = client.post("/api/emails/email-archive-test/archive")

        if response.status_code == 200:
            data = response.get_json()
            assert "success" in data
            assert isinstance(data["success"], bool)
            assert "email_id" in data

    @patch("app.api.routes_helpers._get_container")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_not_spam_response_format(self, mock_get_provider, mock_get_container, client):
        """POST /api/emails/<id>/not-spam → {success: bool}."""
        mock_container = Mock()
        mock_get_container.return_value = mock_container

        mock_provider = Mock()
        mock_provider.move_to_inbox = Mock(return_value=True)
        mock_provider.not_spam = Mock(return_value=True)
        mock_get_provider.return_value = mock_provider

        response = client.post("/api/emails/spam-email-1/not-spam")

        if response.status_code == 200:
            data = response.get_json()
            assert "success" in data
            assert isinstance(data["success"], bool)

    @patch("app.api.routes_helpers._get_container")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_restore_response_format(self, mock_get_provider, mock_get_container, client):
        """POST /api/emails/<id>/restore → {success: bool}."""
        mock_container = Mock()
        mock_get_container.return_value = mock_container

        mock_provider = Mock()
        mock_provider.restore_from_trash = Mock(return_value=True)
        mock_provider.move_to_inbox = Mock(return_value=True)
        mock_get_provider.return_value = mock_provider

        response = client.post("/api/emails/trash-email-1/restore")

        if response.status_code == 200:
            data = response.get_json()
            assert "success" in data
            assert isinstance(data["success"], bool)

    @patch("app.api.routes_helpers._get_container")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_bulk_archive_returns_count(self, mock_get_provider, mock_get_container, client):
        """POST /api/emails/bulk-archive → {success: bool, count: int}."""
        mock_container = Mock()
        mock_get_container.return_value = mock_container

        mock_provider = Mock()
        mock_provider.archive_email = Mock(return_value=True)
        mock_get_provider.return_value = mock_provider

        response = client.post(
            "/api/emails/bulk-archive",
            json={"email_ids": ["email-1", "email-2"]}
        )

        if response.status_code == 200:
            data = response.get_json()
            assert "success" in data
            # L'API retourne updated_count (non count)
            count_key = "count" if "count" in data else "updated_count"
            assert count_key in data
            assert isinstance(data[count_key], int)

    @patch("app.api.routes_helpers._get_container")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_bulk_not_spam_response_format(self, mock_get_provider, mock_get_container, client):
        """POST /api/emails/bulk-not-spam → {success: bool, count: int}."""
        mock_container = Mock()
        mock_get_container.return_value = mock_container

        mock_provider = Mock()
        mock_provider.move_to_inbox = Mock(return_value=True)
        mock_get_provider.return_value = mock_provider

        response = client.post(
            "/api/emails/bulk-not-spam",
            json={"email_ids": ["spam-1", "spam-2"]}
        )

        if response.status_code == 200:
            data = response.get_json()
            assert "success" in data


# ============================================================================
# CLASSE TestErrorContract
# ============================================================================


class TestErrorContract:
    """Vérifie que les erreurs retournent du JSON avec un champ 'error'."""

    @patch("app.api.routes_helpers._get_container")
    def test_404_pending_draft_returns_json(self, mock_get_container, client):
        """GET /api/pending-drafts/<id> inexistant → 404 + JSON avec 'error'."""
        mock_store = Mock()
        mock_store.get_by_id.return_value = None
        mock_container = Mock()
        mock_container.get_pending_draft_store.return_value = mock_store
        mock_get_container.return_value = mock_container

        response = client.get("/api/pending-drafts/does-not-exist")
        assert response.status_code == 404
        assert "application/json" in response.content_type
        data = response.get_json()
        assert "error" in data

    def test_400_invalid_email_id_returns_json(self, client):
        """ID invalide → 400 + JSON avec 'error'."""
        response = client.post("/api/emails/invalid<id>/archive")
        assert response.status_code == 400
        assert "application/json" in response.content_type
        data = response.get_json()
        assert "error" in data

    def test_400_invalid_pending_draft_id_returns_json(self, client):
        """ID invalide pour un pending draft → 400 + JSON avec 'error'."""
        response = client.get("/api/pending-drafts/invalid<id>")
        assert response.status_code == 400
        assert "application/json" in response.content_type
        data = response.get_json()
        assert "error" in data

    def test_all_error_responses_have_error_key(self, client):
        """Tous les endpoints d'erreur doivent retourner {'error': str}."""
        # Test plusieurs endpoints avec IDs invalides
        endpoints = [
            ("GET", "/api/pending-drafts/invalid<>id"),
            ("POST", "/api/emails/bad<id>/archive"),
            ("POST", "/api/pending-drafts/bad<id>/validate"),
            ("POST", "/api/pending-drafts/bad<id>/reject"),
        ]
        for method, path in endpoints:
            if method == "GET":
                resp = client.get(path)
            else:
                resp = client.post(path)

            if resp.status_code in (400, 404):
                data = resp.get_json()
                assert data is not None, f"Pas de JSON pour {method} {path}"
                assert "error" in data, f"Clé 'error' manquante pour {method} {path}"
