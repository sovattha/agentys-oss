# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour l'API REST de gestion multi-comptes.
Coverage complète pour app/api/accounts.py (70% → 100%).
"""

import json
import pytest
from unittest.mock import MagicMock, patch
from app.api.app import create_app
from app.multi_accounts import (
    AccountConfig,
    AccountStats,
)


@pytest.fixture
def app():
    """Crée une instance de l'application Flask pour les tests."""
    app = create_app({"TESTING": True})
    return app


@pytest.fixture
def client(app):
    """Crée un client de test."""
    return app.test_client()


@pytest.fixture
def mock_account_manager():
    """Mock du gestionnaire de comptes."""
    with patch("app.api.accounts.get_account_manager") as mock:
        manager = MagicMock()
        manager.get_current_for_user.return_value = "acc1"
        manager.accounts = {}
        manager.stats = {}
        mock.return_value = manager
        yield manager


# =============================================================================
# HELPER FUNCTIONS TESTS
# =============================================================================


class TestValidateAccountId:
    """Tests pour _validate_account_id."""

    def test_validate_account_id_none(self, client):
        """Test avec account_id None via endpoint."""
        # L'endpoint gère le None avant d'appeler la fonction
        response = client.get("/api/accounts/")
        # Flask routing returns 308 redirect or 404
        assert response.status_code in [308, 404]

    def test_validate_account_id_empty_string(self, client):
        """Test avec account_id vide."""
        response = client.get("/api/accounts/")
        assert response.status_code in [308, 404]

    def test_validate_account_id_invalid_chars(self, client):
        """Test avec caractères invalides."""
        response = client.get("/api/accounts/invalid!@#$")
        assert response.status_code == 400
        assert "invalid" in response.get_json()["error"].lower()

    def test_validate_account_id_too_long(self, client):
        """Test avec ID trop long (>50 chars)."""
        long_id = "a" * 51
        response = client.get(f"/api/accounts/{long_id}")
        assert response.status_code == 400

    def test_validate_account_id_valid_underscore(self, client, mock_account_manager):
        """Test avec underscore valide."""
        mock_account_manager.get_account.return_value = None
        response = client.get("/api/accounts/valid_id")
        assert response.status_code == 404  # Valid ID, account not found

    def test_validate_account_id_valid_dash(self, client, mock_account_manager):
        """Test avec tiret valide."""
        mock_account_manager.get_account.return_value = None
        response = client.get("/api/accounts/valid-id")
        assert response.status_code == 404


class TestValidateEmail:
    """Tests pour _validate_email via les endpoints."""

    def test_validate_email_none(self, client):
        """Email None."""
        response = client.post(
            "/api/accounts",
            data=json.dumps({"name": "Test", "provider": "imap_smtp"}),
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "email" in response.get_json()["error"].lower()

    def test_validate_email_not_string(self, client):
        """Email non-string."""
        response = client.post(
            "/api/accounts",
            data=json.dumps({"name": "Test", "email": 12345, "provider": "imap_smtp"}),
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_validate_email_too_long(self, client):
        """Email trop long (>254 chars RFC 5321)."""
        long_email = "a" * 250 + "@example.com"
        response = client.post(
            "/api/accounts",
            data=json.dumps({"name": "Test", "email": long_email, "provider": "imap_smtp"}),
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_validate_email_invalid_format(self, client):
        """Email format invalide."""
        response = client.post(
            "/api/accounts",
            data=json.dumps({"name": "Test", "email": "not-valid", "provider": "imap_smtp"}),
            content_type="application/json",
        )
        assert response.status_code == 400


class TestValidateProvider:
    """Tests pour _validate_provider via les endpoints."""

    def test_validate_provider_gmail(self, client, mock_account_manager):
        """Provider gmail valide."""
        mock_account_manager.get_account_by_email.return_value = None
        account = AccountConfig(id="new", name="Test", email="t@e.com", provider="gmail")
        mock_account_manager.add_account.return_value = account

        response = client.post(
            "/api/accounts",
            data=json.dumps({"name": "Test", "email": "t@example.com", "provider": "gmail"}),
            content_type="application/json",
        )
        assert response.status_code == 201

    def test_validate_provider_outlook(self, client, mock_account_manager):
        """Provider outlook valide."""
        mock_account_manager.get_account_by_email.return_value = None
        account = AccountConfig(id="new", name="Test", email="t@e.com", provider="outlook")
        mock_account_manager.add_account.return_value = account

        response = client.post(
            "/api/accounts",
            data=json.dumps({"name": "Test", "email": "t@example.com", "provider": "outlook"}),
            content_type="application/json",
        )
        assert response.status_code == 201

    def test_validate_provider_invalid(self, client):
        """Provider invalide."""
        response = client.post(
            "/api/accounts",
            data=json.dumps({"name": "Test", "email": "t@example.com", "provider": "yahoo"}),
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "provider" in response.get_json()["error"].lower()


# =============================================================================
# LIST ACCOUNTS
# =============================================================================


class TestListAccounts:
    """Tests pour GET /api/accounts."""

    def test_list_accounts_empty(self, client, mock_account_manager):
        """Retourne une liste vide si aucun compte."""
        mock_account_manager.get_all_accounts.return_value = []
        mock_account_manager.get_current_for_user.return_value = None

        response = client.get("/api/accounts")

        assert response.status_code == 200
        data = response.get_json()
        assert data["count"] == 0
        assert data["accounts"] == []
        assert data["current_account_id"] is None

    def test_list_accounts_with_accounts(self, client, mock_account_manager):
        """Retourne la liste des comptes."""
        account1 = AccountConfig(
            id="acc1",
            name="Travail",
            email="work@example.com",
            provider="imap_smtp",
        )
        account2 = AccountConfig(
            id="acc2",
            name="Personnel",
            email="personal@example.com",
            provider="gmail",
        )
        mock_account_manager.get_all_accounts.return_value = [account1, account2]
        mock_account_manager.get_current_for_user.return_value = "acc1"

        response = client.get("/api/accounts")

        assert response.status_code == 200
        data = response.get_json()
        assert data["count"] == 2
        assert data["current_account_id"] == "acc1"
        assert len(data["accounts"]) == 2
        assert data["accounts"][0]["name"] == "Travail"
        assert data["accounts"][0]["is_current"] is True
        assert data["accounts"][1]["is_current"] is False

    def test_list_accounts_none_current(self, client, mock_account_manager):
        """Liste avec aucun compte courant — auto-selects first account."""
        account = AccountConfig(
            id="acc1", name="Test", email="t@e.com", provider="imap_smtp"
        )
        mock_account_manager.get_all_accounts.return_value = [account]
        mock_account_manager.get_current_for_user.return_value = None

        response = client.get("/api/accounts")

        assert response.status_code == 200
        data = response.get_json()
        # Auto-select: when no current account, the endpoint picks the first one
        assert data["current_account_id"] == "acc1"
        assert data["accounts"][0]["is_current"] is True


# =============================================================================
# GET ACCOUNT
# =============================================================================


class TestGetAccount:
    """Tests pour GET /api/accounts/<id>."""

    def test_get_account_success(self, client, mock_account_manager):
        """Retourne les détails d'un compte."""
        account = AccountConfig(
            id="acc1",
            name="Travail",
            email="work@example.com",
            provider="imap_smtp",
            signature="Cordialement",
        )
        stats = AccountStats(account_id="acc1", emails_processed=10)
        mock_account_manager.get_account.return_value = account
        mock_account_manager.stats = {"acc1": stats}

        response = client.get("/api/accounts/acc1")

        assert response.status_code == 200
        data = response.get_json()
        assert data["name"] == "Travail"
        assert data["email"] == "work@example.com"
        assert data["stats"]["emails_processed"] == 10

    def test_get_account_no_stats(self, client, mock_account_manager):
        """Retourne compte sans stats."""
        account = AccountConfig(
            id="acc1",
            name="Travail",
            email="work@example.com",
            provider="imap_smtp",
        )
        mock_account_manager.get_account.return_value = account
        mock_account_manager.stats = {}

        response = client.get("/api/accounts/acc1")

        assert response.status_code == 200
        data = response.get_json()
        assert "stats" not in data

    def test_get_account_not_found(self, client, mock_account_manager):
        """Retourne 404 si compte non trouvé."""
        mock_account_manager.get_account.return_value = None

        response = client.get("/api/accounts/unknown")

        assert response.status_code == 404
        assert "not found" in response.get_json()["error"].lower()

    def test_get_account_invalid_id(self, client):
        """Retourne 400 si ID invalide."""
        response = client.get("/api/accounts/invalid!id@")

        assert response.status_code == 400
        assert "invalid" in response.get_json()["error"].lower()

    def test_get_account_is_current_true(self, client, mock_account_manager):
        """Compte retourné avec is_current=True."""
        account = AccountConfig(
            id="acc1", name="Test", email="t@e.com", provider="imap_smtp"
        )
        mock_account_manager.get_account.return_value = account
        mock_account_manager.get_current_for_user.return_value = "acc1"
        mock_account_manager.stats = {}

        response = client.get("/api/accounts/acc1")

        assert response.status_code == 200
        assert response.get_json()["is_current"] is True

    def test_get_account_is_current_false(self, client, mock_account_manager):
        """Compte retourné avec is_current=False."""
        account = AccountConfig(
            id="acc1", name="Test", email="t@e.com", provider="imap_smtp"
        )
        mock_account_manager.get_account.return_value = account
        mock_account_manager.get_current_for_user.return_value = "acc2"
        mock_account_manager.stats = {}

        response = client.get("/api/accounts/acc1")

        assert response.status_code == 200
        assert response.get_json()["is_current"] is False


# =============================================================================
# CREATE ACCOUNT
# =============================================================================


class TestCreateAccount:
    """Tests pour POST /api/accounts."""

    def test_create_account_success(self, client, mock_account_manager):
        """Crée un compte avec succès."""
        new_account = AccountConfig(
            id="new1",
            name="Nouveau",
            email="new@example.com",
            provider="imap_smtp",
        )
        mock_account_manager.get_account_by_email.return_value = None
        mock_account_manager.add_account.return_value = new_account

        response = client.post(
            "/api/accounts",
            data=json.dumps({
                "name": "Nouveau",
                "email": "new@example.com",
                "provider": "imap_smtp",
            }),
            content_type="application/json",
        )

        assert response.status_code == 201
        data = response.get_json()
        assert data["success"] is True
        assert data["account"]["email"] == "new@example.com"

    def test_create_account_no_json(self, client):
        """Retourne 415 si pas de Content-Type JSON."""
        response = client.post("/api/accounts")
        # Flask returns 415 Unsupported Media Type when no JSON content-type
        assert response.status_code == 415

    def test_create_account_empty_json(self, client):
        """Retourne 400 si JSON vide."""
        response = client.post(
            "/api/accounts",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_create_account_missing_name(self, client):
        """Retourne 400 si nom manquant."""
        response = client.post(
            "/api/accounts",
            data=json.dumps({
                "email": "test@example.com",
                "provider": "imap_smtp",
            }),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "name" in response.get_json()["error"].lower()

    def test_create_account_empty_name(self, client):
        """Retourne 400 si nom vide."""
        response = client.post(
            "/api/accounts",
            data=json.dumps({
                "name": "   ",
                "email": "test@example.com",
                "provider": "imap_smtp",
            }),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "name" in response.get_json()["error"].lower()

    def test_create_account_name_too_long(self, client):
        """Retourne 400 si nom trop long."""
        response = client.post(
            "/api/accounts",
            data=json.dumps({
                "name": "a" * 101,
                "email": "test@example.com",
                "provider": "imap_smtp",
            }),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "max length" in response.get_json()["error"].lower()

    def test_create_account_missing_email(self, client):
        """Retourne 400 si email manquant."""
        response = client.post(
            "/api/accounts",
            data=json.dumps({
                "name": "Test",
                "provider": "imap_smtp",
            }),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "email" in response.get_json()["error"].lower()

    def test_create_account_invalid_email(self, client):
        """Retourne 400 si email invalide."""
        response = client.post(
            "/api/accounts",
            data=json.dumps({
                "name": "Test",
                "email": "not-an-email",
                "provider": "imap_smtp",
            }),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "email" in response.get_json()["error"].lower()

    def test_create_account_invalid_provider(self, client):
        """Retourne 400 si provider invalide."""
        response = client.post(
            "/api/accounts",
            data=json.dumps({
                "name": "Test",
                "email": "test@example.com",
                "provider": "invalid_provider",
            }),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "provider" in response.get_json()["error"].lower()

    def test_create_account_duplicate_email(self, client, mock_account_manager):
        """Retourne 400 si email déjà utilisé."""
        existing = AccountConfig(
            id="existing",
            name="Existant",
            email="test@example.com",
            provider="imap_smtp",
        )
        mock_account_manager.get_account_by_email.return_value = existing

        response = client.post(
            "/api/accounts",
            data=json.dumps({
                "name": "Test",
                "email": "test@example.com",
                "provider": "imap_smtp",
            }),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "already exists" in response.get_json()["error"].lower()

    # -------------------------------------------------------------------------
    # Optional fields - Coverage lines 279-312
    # -------------------------------------------------------------------------

    def test_create_account_with_credentials_path(self, client, mock_account_manager):
        """Crée compte avec credentials_path."""
        new_account = AccountConfig(
            id="new1", name="Test", email="t@e.com", provider="imap_smtp"
        )
        mock_account_manager.get_account_by_email.return_value = None
        mock_account_manager.add_account.return_value = new_account

        response = client.post(
            "/api/accounts",
            data=json.dumps({
                "name": "Test",
                "email": "test@example.com",
                "provider": "imap_smtp",
                "credentials_path": "/path/to/creds.json",
            }),
            content_type="application/json",
        )

        assert response.status_code == 201
        mock_account_manager.add_account.assert_called_once()
        call_kwargs = mock_account_manager.add_account.call_args[1]
        assert call_kwargs["credentials_path"] == "/path/to/creds.json"

    def test_create_account_credentials_path_too_long(self, client, mock_account_manager):
        """Retourne 400 si credentials_path trop long."""
        mock_account_manager.get_account_by_email.return_value = None

        response = client.post(
            "/api/accounts",
            data=json.dumps({
                "name": "Test",
                "email": "test@example.com",
                "provider": "imap_smtp",
                "credentials_path": "a" * 501,
            }),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "credentials_path" in response.get_json()["error"].lower()

    def test_create_account_with_check_interval(self, client, mock_account_manager):
        """Crée compte avec check_interval_minutes."""
        new_account = AccountConfig(
            id="new1", name="Test", email="t@e.com", provider="imap_smtp"
        )
        mock_account_manager.get_account_by_email.return_value = None
        mock_account_manager.add_account.return_value = new_account

        response = client.post(
            "/api/accounts",
            data=json.dumps({
                "name": "Test",
                "email": "test@example.com",
                "provider": "imap_smtp",
                "check_interval_minutes": 10,
            }),
            content_type="application/json",
        )

        assert response.status_code == 201

    def test_create_account_check_interval_invalid_low(self, client, mock_account_manager):
        """check_interval_minutes < 1."""
        mock_account_manager.get_account_by_email.return_value = None

        response = client.post(
            "/api/accounts",
            data=json.dumps({
                "name": "Test",
                "email": "test@example.com",
                "provider": "imap_smtp",
                "check_interval_minutes": 0,
            }),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "check_interval_minutes" in response.get_json()["error"].lower()

    def test_create_account_check_interval_invalid_high(self, client, mock_account_manager):
        """check_interval_minutes > 1440."""
        mock_account_manager.get_account_by_email.return_value = None

        response = client.post(
            "/api/accounts",
            data=json.dumps({
                "name": "Test",
                "email": "test@example.com",
                "provider": "imap_smtp",
                "check_interval_minutes": 1441,
            }),
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_create_account_check_interval_not_int(self, client, mock_account_manager):
        """check_interval_minutes not int."""
        mock_account_manager.get_account_by_email.return_value = None

        response = client.post(
            "/api/accounts",
            data=json.dumps({
                "name": "Test",
                "email": "test@example.com",
                "provider": "imap_smtp",
                "check_interval_minutes": "five",
            }),
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_create_account_with_max_emails_per_batch(self, client, mock_account_manager):
        """Crée compte avec max_emails_per_batch."""
        new_account = AccountConfig(
            id="new1", name="Test", email="t@e.com", provider="imap_smtp"
        )
        mock_account_manager.get_account_by_email.return_value = None
        mock_account_manager.add_account.return_value = new_account

        response = client.post(
            "/api/accounts",
            data=json.dumps({
                "name": "Test",
                "email": "test@example.com",
                "provider": "imap_smtp",
                "max_emails_per_batch": 50,
            }),
            content_type="application/json",
        )

        assert response.status_code == 201

    def test_create_account_max_emails_invalid_low(self, client, mock_account_manager):
        """max_emails_per_batch < 1."""
        mock_account_manager.get_account_by_email.return_value = None

        response = client.post(
            "/api/accounts",
            data=json.dumps({
                "name": "Test",
                "email": "test@example.com",
                "provider": "imap_smtp",
                "max_emails_per_batch": 0,
            }),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "max_emails_per_batch" in response.get_json()["error"].lower()

    def test_create_account_max_emails_invalid_high(self, client, mock_account_manager):
        """max_emails_per_batch > 100."""
        mock_account_manager.get_account_by_email.return_value = None

        response = client.post(
            "/api/accounts",
            data=json.dumps({
                "name": "Test",
                "email": "test@example.com",
                "provider": "imap_smtp",
                "max_emails_per_batch": 101,
            }),
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_create_account_max_emails_not_int(self, client, mock_account_manager):
        """max_emails_per_batch not int."""
        mock_account_manager.get_account_by_email.return_value = None

        response = client.post(
            "/api/accounts",
            data=json.dumps({
                "name": "Test",
                "email": "test@example.com",
                "provider": "imap_smtp",
                "max_emails_per_batch": "fifty",
            }),
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_create_account_with_auto_reply_enabled(self, client, mock_account_manager):
        """Crée compte avec auto_reply_enabled."""
        new_account = AccountConfig(
            id="new1", name="Test", email="t@e.com", provider="imap_smtp"
        )
        mock_account_manager.get_account_by_email.return_value = None
        mock_account_manager.add_account.return_value = new_account

        response = client.post(
            "/api/accounts",
            data=json.dumps({
                "name": "Test",
                "email": "test@example.com",
                "provider": "imap_smtp",
                "auto_reply_enabled": False,
            }),
            content_type="application/json",
        )

        assert response.status_code == 201

    def test_create_account_with_draft_only(self, client, mock_account_manager):
        """Crée compte avec draft_only."""
        new_account = AccountConfig(
            id="new1", name="Test", email="t@e.com", provider="imap_smtp"
        )
        mock_account_manager.get_account_by_email.return_value = None
        mock_account_manager.add_account.return_value = new_account

        response = client.post(
            "/api/accounts",
            data=json.dumps({
                "name": "Test",
                "email": "test@example.com",
                "provider": "imap_smtp",
                "draft_only": True,
            }),
            content_type="application/json",
        )

        assert response.status_code == 201

    def test_create_account_with_signature(self, client, mock_account_manager):
        """Crée compte avec signature."""
        new_account = AccountConfig(
            id="new1", name="Test", email="t@e.com", provider="imap_smtp"
        )
        mock_account_manager.get_account_by_email.return_value = None
        mock_account_manager.add_account.return_value = new_account

        response = client.post(
            "/api/accounts",
            data=json.dumps({
                "name": "Test",
                "email": "test@example.com",
                "provider": "imap_smtp",
                "signature": "Cordialement, Test",
            }),
            content_type="application/json",
        )

        assert response.status_code == 201

    def test_create_account_signature_too_long(self, client, mock_account_manager):
        """signature > 2000 chars."""
        mock_account_manager.get_account_by_email.return_value = None

        response = client.post(
            "/api/accounts",
            data=json.dumps({
                "name": "Test",
                "email": "test@example.com",
                "provider": "imap_smtp",
                "signature": "a" * 2001,
            }),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "signature" in response.get_json()["error"].lower()

    def test_create_account_with_default_language(self, client, mock_account_manager):
        """Crée compte avec default_language."""
        new_account = AccountConfig(
            id="new1", name="Test", email="t@e.com", provider="imap_smtp"
        )
        mock_account_manager.get_account_by_email.return_value = None
        mock_account_manager.add_account.return_value = new_account

        response = client.post(
            "/api/accounts",
            data=json.dumps({
                "name": "Test",
                "email": "test@example.com",
                "provider": "imap_smtp",
                "default_language": "fr",
            }),
            content_type="application/json",
        )

        assert response.status_code == 201

    def test_create_account_default_language_too_long(self, client, mock_account_manager):
        """default_language > 10 chars."""
        mock_account_manager.get_account_by_email.return_value = None

        response = client.post(
            "/api/accounts",
            data=json.dumps({
                "name": "Test",
                "email": "test@example.com",
                "provider": "imap_smtp",
                "default_language": "a" * 11,
            }),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "default_language" in response.get_json()["error"].lower()

    def test_create_account_exception_handling(self, client, mock_account_manager):
        """Gère les exceptions lors de la création."""
        mock_account_manager.get_account_by_email.return_value = None
        mock_account_manager.add_account.side_effect = Exception("Database error")

        response = client.post(
            "/api/accounts",
            data=json.dumps({
                "name": "Test",
                "email": "test@example.com",
                "provider": "imap_smtp",
            }),
            content_type="application/json",
        )

        assert response.status_code == 500
        assert "failed" in response.get_json()["error"].lower()

    def test_create_account_with_all_optional_fields(self, client, mock_account_manager):
        """Crée compte avec tous les champs optionnels."""
        new_account = AccountConfig(
            id="new1", name="Test", email="t@e.com", provider="imap_smtp"
        )
        mock_account_manager.get_account_by_email.return_value = None
        mock_account_manager.add_account.return_value = new_account

        response = client.post(
            "/api/accounts",
            data=json.dumps({
                "name": "Test",
                "email": "test@example.com",
                "provider": "imap_smtp",
                "credentials_path": "/path/creds.json",
                "check_interval_minutes": 10,
                "max_emails_per_batch": 25,
                "auto_reply_enabled": True,
                "draft_only": False,
                "signature": "Best regards",
                "default_language": "en",
            }),
            content_type="application/json",
        )

        assert response.status_code == 201


# =============================================================================
# UPDATE ACCOUNT
# =============================================================================


class TestUpdateAccount:
    """Tests pour PATCH /api/accounts/<id>."""

    def test_update_account_success(self, client, mock_account_manager):
        """Met à jour un compte avec succès."""
        account = AccountConfig(
            id="acc1",
            name="Ancien nom",
            email="test@example.com",
            provider="imap_smtp",
        )
        updated = AccountConfig(
            id="acc1",
            name="Nouveau nom",
            email="test@example.com",
            provider="imap_smtp",
        )
        mock_account_manager.get_account.return_value = account
        mock_account_manager.update_account.return_value = updated

        response = client.patch(
            "/api/accounts/acc1",
            data=json.dumps({"name": "Nouveau nom"}),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["account"]["name"] == "Nouveau nom"

    def test_update_account_invalid_id(self, client):
        """Retourne 400 si ID invalide."""
        response = client.patch(
            "/api/accounts/invalid!@#",
            data=json.dumps({"name": "Test"}),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "invalid" in response.get_json()["error"].lower()

    def test_update_account_no_json(self, client, mock_account_manager):
        """Retourne 415 si pas de Content-Type JSON."""
        response = client.patch("/api/accounts/acc1")
        # Flask returns 415 Unsupported Media Type when no JSON content-type
        assert response.status_code == 415

    def test_update_account_not_found(self, client, mock_account_manager):
        """Retourne 404 si compte non trouvé."""
        mock_account_manager.get_account.return_value = None

        response = client.patch(
            "/api/accounts/unknown",
            data=json.dumps({"name": "Test"}),
            content_type="application/json",
        )

        assert response.status_code == 404

    def test_update_account_empty_name(self, client, mock_account_manager):
        """Retourne 400 si nom vide."""
        account = AccountConfig(
            id="acc1", name="Test", email="t@e.com", provider="imap_smtp"
        )
        mock_account_manager.get_account.return_value = account

        response = client.patch(
            "/api/accounts/acc1",
            data=json.dumps({"name": ""}),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "name" in response.get_json()["error"].lower()

    def test_update_account_whitespace_name(self, client, mock_account_manager):
        """Retourne 400 si nom que des espaces."""
        account = AccountConfig(
            id="acc1", name="Test", email="t@e.com", provider="imap_smtp"
        )
        mock_account_manager.get_account.return_value = account

        response = client.patch(
            "/api/accounts/acc1",
            data=json.dumps({"name": "   "}),
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_update_account_name_too_long(self, client, mock_account_manager):
        """Retourne 400 si nom trop long."""
        account = AccountConfig(
            id="acc1", name="Test", email="t@e.com", provider="imap_smtp"
        )
        mock_account_manager.get_account.return_value = account

        response = client.patch(
            "/api/accounts/acc1",
            data=json.dumps({"name": "a" * 101}),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "max length" in response.get_json()["error"].lower()

    def test_update_account_check_interval(self, client, mock_account_manager):
        """Update check_interval_minutes."""
        account = AccountConfig(
            id="acc1", name="Test", email="t@e.com", provider="imap_smtp"
        )
        updated = AccountConfig(
            id="acc1", name="Test", email="t@e.com", provider="imap_smtp",
            check_interval_minutes=15
        )
        mock_account_manager.get_account.return_value = account
        mock_account_manager.update_account.return_value = updated

        response = client.patch(
            "/api/accounts/acc1",
            data=json.dumps({"check_interval_minutes": 15}),
            content_type="application/json",
        )

        assert response.status_code == 200

    def test_update_account_check_interval_invalid_low(self, client, mock_account_manager):
        """check_interval_minutes < 1."""
        account = AccountConfig(
            id="acc1", name="Test", email="t@e.com", provider="imap_smtp"
        )
        mock_account_manager.get_account.return_value = account

        response = client.patch(
            "/api/accounts/acc1",
            data=json.dumps({"check_interval_minutes": 0}),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "check_interval_minutes" in response.get_json()["error"].lower()

    def test_update_account_check_interval_invalid_high(self, client, mock_account_manager):
        """check_interval_minutes > 1440."""
        account = AccountConfig(
            id="acc1", name="Test", email="t@e.com", provider="imap_smtp"
        )
        mock_account_manager.get_account.return_value = account

        response = client.patch(
            "/api/accounts/acc1",
            data=json.dumps({"check_interval_minutes": 1441}),
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_update_account_check_interval_not_int(self, client, mock_account_manager):
        """check_interval_minutes not int."""
        account = AccountConfig(
            id="acc1", name="Test", email="t@e.com", provider="imap_smtp"
        )
        mock_account_manager.get_account.return_value = account

        response = client.patch(
            "/api/accounts/acc1",
            data=json.dumps({"check_interval_minutes": "five"}),
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_update_account_max_emails_per_batch(self, client, mock_account_manager):
        """Update max_emails_per_batch."""
        account = AccountConfig(
            id="acc1", name="Test", email="t@e.com", provider="imap_smtp"
        )
        updated = AccountConfig(
            id="acc1", name="Test", email="t@e.com", provider="imap_smtp",
            max_emails_per_batch=50
        )
        mock_account_manager.get_account.return_value = account
        mock_account_manager.update_account.return_value = updated

        response = client.patch(
            "/api/accounts/acc1",
            data=json.dumps({"max_emails_per_batch": 50}),
            content_type="application/json",
        )

        assert response.status_code == 200

    def test_update_account_max_emails_invalid_low(self, client, mock_account_manager):
        """max_emails_per_batch < 1."""
        account = AccountConfig(
            id="acc1", name="Test", email="t@e.com", provider="imap_smtp"
        )
        mock_account_manager.get_account.return_value = account

        response = client.patch(
            "/api/accounts/acc1",
            data=json.dumps({"max_emails_per_batch": 0}),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "max_emails_per_batch" in response.get_json()["error"].lower()

    def test_update_account_max_emails_invalid_high(self, client, mock_account_manager):
        """max_emails_per_batch > 100."""
        account = AccountConfig(
            id="acc1", name="Test", email="t@e.com", provider="imap_smtp"
        )
        mock_account_manager.get_account.return_value = account

        response = client.patch(
            "/api/accounts/acc1",
            data=json.dumps({"max_emails_per_batch": 101}),
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_update_account_max_emails_not_int(self, client, mock_account_manager):
        """max_emails_per_batch not int."""
        account = AccountConfig(
            id="acc1", name="Test", email="t@e.com", provider="imap_smtp"
        )
        mock_account_manager.get_account.return_value = account

        response = client.patch(
            "/api/accounts/acc1",
            data=json.dumps({"max_emails_per_batch": "fifty"}),
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_update_account_auto_reply_enabled(self, client, mock_account_manager):
        """Update auto_reply_enabled."""
        account = AccountConfig(
            id="acc1", name="Test", email="t@e.com", provider="imap_smtp"
        )
        updated = AccountConfig(
            id="acc1", name="Test", email="t@e.com", provider="imap_smtp",
            auto_reply_enabled=False
        )
        mock_account_manager.get_account.return_value = account
        mock_account_manager.update_account.return_value = updated

        response = client.patch(
            "/api/accounts/acc1",
            data=json.dumps({"auto_reply_enabled": False}),
            content_type="application/json",
        )

        assert response.status_code == 200

    def test_update_account_draft_only(self, client, mock_account_manager):
        """Update draft_only."""
        account = AccountConfig(
            id="acc1", name="Test", email="t@e.com", provider="imap_smtp"
        )
        updated = AccountConfig(
            id="acc1", name="Test", email="t@e.com", provider="imap_smtp",
            draft_only=True
        )
        mock_account_manager.get_account.return_value = account
        mock_account_manager.update_account.return_value = updated

        response = client.patch(
            "/api/accounts/acc1",
            data=json.dumps({"draft_only": True}),
            content_type="application/json",
        )

        assert response.status_code == 200

    def test_update_account_signature(self, client, mock_account_manager):
        """Update signature."""
        account = AccountConfig(
            id="acc1", name="Test", email="t@e.com", provider="imap_smtp"
        )
        updated = AccountConfig(
            id="acc1", name="Test", email="t@e.com", provider="imap_smtp",
            signature="New sig"
        )
        mock_account_manager.get_account.return_value = account
        mock_account_manager.update_account.return_value = updated

        response = client.patch(
            "/api/accounts/acc1",
            data=json.dumps({"signature": "New sig"}),
            content_type="application/json",
        )

        assert response.status_code == 200

    def test_update_account_signature_too_long(self, client, mock_account_manager):
        """signature > 2000 chars."""
        account = AccountConfig(
            id="acc1", name="Test", email="t@e.com", provider="imap_smtp"
        )
        mock_account_manager.get_account.return_value = account

        response = client.patch(
            "/api/accounts/acc1",
            data=json.dumps({"signature": "a" * 2001}),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "signature" in response.get_json()["error"].lower()

    def test_update_account_default_language(self, client, mock_account_manager):
        """Update default_language."""
        account = AccountConfig(
            id="acc1", name="Test", email="t@e.com", provider="imap_smtp"
        )
        updated = AccountConfig(
            id="acc1", name="Test", email="t@e.com", provider="imap_smtp",
            default_language="de"
        )
        mock_account_manager.get_account.return_value = account
        mock_account_manager.update_account.return_value = updated

        response = client.patch(
            "/api/accounts/acc1",
            data=json.dumps({"default_language": "de"}),
            content_type="application/json",
        )

        assert response.status_code == 200

    def test_update_account_default_language_too_long(self, client, mock_account_manager):
        """default_language > 10 chars."""
        account = AccountConfig(
            id="acc1", name="Test", email="t@e.com", provider="imap_smtp"
        )
        mock_account_manager.get_account.return_value = account

        response = client.patch(
            "/api/accounts/acc1",
            data=json.dumps({"default_language": "a" * 11}),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "default_language" in response.get_json()["error"].lower()

    def test_update_account_no_fields(self, client, mock_account_manager):
        """Retourne 400 si aucun champ valide fourni."""
        account = AccountConfig(
            id="acc1",
            name="Test",
            email="test@example.com",
            provider="imap_smtp",
        )
        mock_account_manager.get_account.return_value = account

        # Send a field that is not recognized as an update field
        response = client.patch(
            "/api/accounts/acc1",
            data=json.dumps({"unknown_field": "value"}),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "no valid fields" in response.get_json()["error"].lower()

    def test_update_account_update_fails(self, client, mock_account_manager):
        """Retourne 500 si update échoue."""
        account = AccountConfig(
            id="acc1", name="Test", email="t@e.com", provider="imap_smtp"
        )
        mock_account_manager.get_account.return_value = account
        mock_account_manager.update_account.return_value = None

        response = client.patch(
            "/api/accounts/acc1",
            data=json.dumps({"name": "New Name"}),
            content_type="application/json",
        )

        assert response.status_code == 500
        assert "failed" in response.get_json()["error"].lower()

    def test_update_account_multiple_fields(self, client, mock_account_manager):
        """Update plusieurs champs à la fois."""
        account = AccountConfig(
            id="acc1", name="Test", email="t@e.com", provider="imap_smtp"
        )
        updated = AccountConfig(
            id="acc1", name="New Name", email="t@e.com", provider="imap_smtp",
            check_interval_minutes=10, draft_only=True
        )
        mock_account_manager.get_account.return_value = account
        mock_account_manager.update_account.return_value = updated

        response = client.patch(
            "/api/accounts/acc1",
            data=json.dumps({
                "name": "New Name",
                "check_interval_minutes": 10,
                "draft_only": True,
            }),
            content_type="application/json",
        )

        assert response.status_code == 200


# =============================================================================
# DELETE ACCOUNT
# =============================================================================


class TestDeleteAccount:
    """Tests pour DELETE /api/accounts/<id>."""

    def test_delete_account_success(self, client, mock_account_manager):
        """Supprime un compte avec succès."""
        account = AccountConfig(
            id="acc1",
            name="Test",
            email="test@example.com",
            provider="imap_smtp",
        )
        mock_account_manager.get_account.return_value = account
        mock_account_manager.remove_account.return_value = True

        response = client.delete("/api/accounts/acc1")

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["account_id"] == "acc1"
        assert "deleted" in data["message"].lower()

    def test_delete_account_invalid_id(self, client):
        """Retourne 400 si ID invalide."""
        response = client.delete("/api/accounts/invalid!@#")

        assert response.status_code == 400
        assert "invalid" in response.get_json()["error"].lower()

    def test_delete_account_not_found(self, client, mock_account_manager):
        """Retourne 404 si compte non trouvé."""
        mock_account_manager.get_account.return_value = None

        response = client.delete("/api/accounts/unknown")

        assert response.status_code == 404

    def test_delete_account_remove_fails(self, client, mock_account_manager):
        """Retourne 500 si remove échoue."""
        account = AccountConfig(
            id="acc1", name="Test", email="t@e.com", provider="imap_smtp"
        )
        mock_account_manager.get_account.return_value = account
        mock_account_manager.remove_account.return_value = False

        response = client.delete("/api/accounts/acc1")

        assert response.status_code == 500
        assert "failed" in response.get_json()["error"].lower()

    def test_delete_account_concurrent_delete_returns_success(
        self, client, mock_account_manager
    ):
        """Race 2026-06-09 : un DELETE dupliqué pendant le cleanup lent doit
        renvoyer succès (compte déjà supprimé), pas 500."""
        account = AccountConfig(
            id="acc1", name="Test", email="t@e.com", provider="imap_smtp"
        )
        # 1er get_account (validation) : le compte existe. Recheck après
        # remove_account=False : il a disparu (la requête concurrente l'a
        # supprimé) → l'état final est celui demandé.
        calls = {"n": 0}

        def _get_account(_account_id):
            calls["n"] += 1
            return account if calls["n"] == 1 else None

        mock_account_manager.get_account.side_effect = _get_account
        mock_account_manager.remove_account.return_value = False

        response = client.delete("/api/accounts/acc1")

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert "already" in data["message"].lower()

    def test_purge_snippets_uses_existing_manager_api(
        self, tmp_path, monkeypatch, mock_account_manager
    ):
        """Régression : _purge_snippets_for_account appelait
        manager.list_accounts() (méthode inexistante → AttributeError,
        purge silencieusement sautée à chaque suppression de compte).

        Post-migration 040 la purge opère sur la table ``snippets`` ; le
        seed passe par le fichier legacy (absorbé par l'import one-shot) et
        la vérification lit la DB."""
        from contextlib import contextmanager

        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool

        import app.api.snippets as snippets_mod
        from app.api.accounts import _purge_snippets_for_account
        from app.db.models import Base
        from app.db.models.snippet import SnippetRow

        snip_file = tmp_path / "snippets.json"
        snip_file.write_text(
            json.dumps([
                {"id": "s1", "owner_email": "t@e.com", "account_id": 14},
                {"id": "s2", "owner_email": "other@e.com", "account_id": 99},
            ]),
            encoding="utf-8",
        )
        monkeypatch.setattr(snippets_mod, "SNIPPETS_FILE", str(snip_file))
        monkeypatch.setattr(
            snippets_mod, "SHARES_FILE", str(tmp_path / "shares.json")
        )
        monkeypatch.setattr(snippets_mod, "_legacy_import_done", False)

        engine = create_engine(
            "sqlite://", poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine, autoflush=False)

        @contextmanager
        def _cm():
            s = SessionLocal()
            try:
                yield s
            finally:
                s.close()

        monkeypatch.setattr("app.db.database.get_db_session", _cm)

        # Dernier compte de cet owner_email supprimé → tous ses snippets partent
        mock_account_manager.get_all_accounts.return_value = []

        _purge_snippets_for_account(14, "t@e.com")

        with _cm() as s:
            kept = [r.id for r in s.query(SnippetRow).all()]
        assert kept == ["s2"]


# =============================================================================
# ACTIVATE ACCOUNT
# =============================================================================


class TestActivateAccount:
    """Tests pour POST /api/accounts/<id>/activate."""

    def test_activate_account_success(self, client, mock_account_manager):
        """Active un compte avec succès."""
        account = AccountConfig(
            id="acc1",
            name="Test",
            email="test@example.com",
            provider="imap_smtp",
        )
        mock_account_manager.get_account.return_value = account
        mock_account_manager.switch_to.return_value = MagicMock()

        response = client.post("/api/accounts/acc1/activate")

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["account_id"] == "acc1"
        assert data["account_name"] == "Test"

    def test_activate_account_invalid_id(self, client, mock_account_manager):
        """Retourne 400 si ID invalide (caractères spéciaux tolérés par URL)."""
        # Use URL-safe but pattern-invalid characters
        mock_account_manager.switch_to.return_value = None  # Won't be called due to validation
        response = client.post("/api/accounts/invalid---too-long-id-that-exceeds-fifty-characters-limit/activate")

        assert response.status_code == 400
        assert "invalid" in response.get_json()["error"].lower()

    def test_activate_account_not_found(self, client, mock_account_manager):
        """Retourne 404 si compte non trouvé."""
        mock_account_manager.switch_to.return_value = None

        response = client.post("/api/accounts/unknown/activate")

        assert response.status_code == 404

    def test_activate_account_no_account_name(self, client, mock_account_manager):
        """Active mais get_account retourne None pour le nom."""
        mock_account_manager.switch_to.return_value = MagicMock()
        mock_account_manager.get_account.return_value = None

        response = client.post("/api/accounts/acc1/activate")

        assert response.status_code == 200
        data = response.get_json()
        assert data["account_name"] is None


# =============================================================================
# ACCOUNT STATS
# =============================================================================


class TestAccountStats:
    """Tests pour GET /api/accounts/<id>/stats."""

    def test_get_stats_success(self, client, mock_account_manager):
        """Retourne les statistiques d'un compte."""
        account = AccountConfig(
            id="acc1",
            name="Test",
            email="test@example.com",
            provider="imap_smtp",
        )
        mock_account_manager.get_account.return_value = account
        mock_account_manager.get_stats.return_value = {
            "emails_processed": 100,
            "drafts_created": 80,
        }

        response = client.get("/api/accounts/acc1/stats")

        assert response.status_code == 200
        data = response.get_json()
        assert data["account_id"] == "acc1"
        assert "stats" in data

    def test_get_stats_invalid_id(self, client):
        """Retourne 400 si ID invalide."""
        response = client.get("/api/accounts/invalid!@#/stats")

        assert response.status_code == 400
        assert "invalid" in response.get_json()["error"].lower()

    def test_get_stats_account_not_found(self, client, mock_account_manager):
        """Retourne 404 si compte non trouvé."""
        mock_account_manager.get_account.return_value = None

        response = client.get("/api/accounts/unknown/stats")

        assert response.status_code == 404


# =============================================================================
# TEST CONNECTION
# =============================================================================


class TestTestConnection:
    """Tests pour POST /api/accounts/<id>/test."""

    def test_test_connection_success(self, client, mock_account_manager):
        """Teste la connexion avec succès."""
        account = AccountConfig(
            id="acc1",
            name="Test",
            email="test@example.com",
            provider="imap_smtp",
        )
        mock_account_manager.get_account.return_value = account

        with patch("app.multi_accounts.create_provider_for_account") as mock_create:
            mock_provider = MagicMock()
            mock_provider.authenticate.return_value = True
            mock_create.return_value = mock_provider

            response = client.post("/api/accounts/acc1/test")

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["account_id"] == "acc1"
        assert "successful" in data["message"].lower()

    def test_test_connection_invalid_id(self, client, mock_account_manager):
        """Retourne 400 si ID invalide."""
        # Use URL-safe but pattern-invalid ID (too long)
        mock_account_manager.get_account.return_value = None  # Won't be called due to validation
        response = client.post("/api/accounts/invalid---too-long-id-that-exceeds-fifty-characters-limit/test")

        assert response.status_code == 400
        assert "invalid" in response.get_json()["error"].lower()

    def test_test_connection_account_not_found(self, client, mock_account_manager):
        """Retourne 404 si compte non trouvé."""
        mock_account_manager.get_account.return_value = None

        response = client.post("/api/accounts/unknown/test")

        assert response.status_code == 404

    def test_test_connection_auth_failure(self, client, mock_account_manager):
        """Retourne 401 si authentification échoue."""
        account = AccountConfig(
            id="acc1",
            name="Test",
            email="test@example.com",
            provider="imap_smtp",
        )
        mock_account_manager.get_account.return_value = account

        with patch("app.multi_accounts.create_provider_for_account") as mock_create:
            mock_provider = MagicMock()
            mock_provider.authenticate.return_value = False
            mock_create.return_value = mock_provider

            response = client.post("/api/accounts/acc1/test")

        assert response.status_code == 401
        data = response.get_json()
        assert data["success"] is False
        assert "failed" in data["message"].lower()

    def test_test_connection_exception(self, client, mock_account_manager):
        """Retourne 500 si exception."""
        account = AccountConfig(
            id="acc1",
            name="Test",
            email="test@example.com",
            provider="imap_smtp",
        )
        mock_account_manager.get_account.return_value = account

        with patch("app.multi_accounts.create_provider_for_account") as mock_create:
            mock_create.side_effect = Exception("Connection timeout")

            response = client.post("/api/accounts/acc1/test")

        assert response.status_code == 500
        data = response.get_json()
        assert data["success"] is False
        assert "Connection timeout" in data["message"]


# =============================================================================
# GLOBAL STATS
# =============================================================================


class TestGlobalStats:
    """Tests pour GET /api/accounts/stats."""

    def test_get_global_stats(self, client, mock_account_manager):
        """Retourne les statistiques globales."""
        mock_account_manager.get_stats.return_value = {
            "total_accounts": 2,
            "active_accounts": 2,
            "total_emails_processed": 200,
        }

        response = client.get("/api/accounts/stats")

        assert response.status_code == 200
        data = response.get_json()
        assert "total_accounts" in data

    def test_get_global_stats_empty(self, client, mock_account_manager):
        """Retourne stats vides si pas de comptes."""
        mock_account_manager.get_stats.return_value = {}

        response = client.get("/api/accounts/stats")

        assert response.status_code == 200
        data = response.get_json()
        assert data == {}


# =============================================================================
# EDGE CASES & INTEGRATION
# =============================================================================


class TestEdgeCases:
    """Tests pour cas limites."""

    def test_name_is_not_string(self, client):
        """name n'est pas une string."""
        response = client.post(
            "/api/accounts",
            data=json.dumps({
                "name": 12345,
                "email": "test@example.com",
                "provider": "imap_smtp",
            }),
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_name_none(self, client):
        """name est None."""
        response = client.post(
            "/api/accounts",
            data=json.dumps({
                "name": None,
                "email": "test@example.com",
                "provider": "imap_smtp",
            }),
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_update_name_not_string(self, client, mock_account_manager):
        """Update name non-string."""
        account = AccountConfig(
            id="acc1", name="Test", email="t@e.com", provider="imap_smtp"
        )
        mock_account_manager.get_account.return_value = account

        response = client.patch(
            "/api/accounts/acc1",
            data=json.dumps({"name": 12345}),
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_credentials_path_empty_string(self, client, mock_account_manager):
        """credentials_path string vide est valide."""
        new_account = AccountConfig(
            id="new1", name="Test", email="t@e.com", provider="imap_smtp"
        )
        mock_account_manager.get_account_by_email.return_value = None
        mock_account_manager.add_account.return_value = new_account

        response = client.post(
            "/api/accounts",
            data=json.dumps({
                "name": "Test",
                "email": "test@example.com",
                "provider": "imap_smtp",
                "credentials_path": "",
            }),
            content_type="application/json",
        )

        # Empty string is valid (falsy but allowed)
        assert response.status_code == 201

    def test_signature_empty_string(self, client, mock_account_manager):
        """signature string vide est valide."""
        account = AccountConfig(
            id="acc1", name="Test", email="t@e.com", provider="imap_smtp"
        )
        updated = AccountConfig(
            id="acc1", name="Test", email="t@e.com", provider="imap_smtp",
            signature=""
        )
        mock_account_manager.get_account.return_value = account
        mock_account_manager.update_account.return_value = updated

        response = client.patch(
            "/api/accounts/acc1",
            data=json.dumps({"signature": ""}),
            content_type="application/json",
        )

        assert response.status_code == 200

    def test_default_language_empty_string(self, client, mock_account_manager):
        """default_language string vide est valide."""
        account = AccountConfig(
            id="acc1", name="Test", email="t@e.com", provider="imap_smtp"
        )
        updated = AccountConfig(
            id="acc1", name="Test", email="t@e.com", provider="imap_smtp",
            default_language=""
        )
        mock_account_manager.get_account.return_value = account
        mock_account_manager.update_account.return_value = updated

        response = client.patch(
            "/api/accounts/acc1",
            data=json.dumps({"default_language": ""}),
            content_type="application/json",
        )

        assert response.status_code == 200


class TestAccountConversions:
    """Tests pour _account_to_dict et _account_to_summary_dict."""

    def test_account_to_dict_all_fields(self, client, mock_account_manager):
        """Vérifie que tous les champs sont retournés."""
        account = AccountConfig(
            id="acc1",
            name="Test Account",
            email="test@example.com",
            provider="imap_smtp",
            status="active",
            check_interval_minutes=10,
            max_emails_per_batch=25,
            auto_reply_enabled=True,
            draft_only=False,
            default_language="fr",
            signature="Best regards",
            created_at="2024-01-01T00:00:00",
            last_sync="2024-01-02T00:00:00",
            last_error=None,
            email_count=100,
        )
        mock_account_manager.get_account.return_value = account
        mock_account_manager.stats = {}
        mock_account_manager.get_current_for_user.return_value = "acc1"

        response = client.get("/api/accounts/acc1")

        assert response.status_code == 200
        data = response.get_json()
        assert data["id"] == "acc1"
        assert data["name"] == "Test Account"
        assert data["email"] == "test@example.com"
        assert data["provider"] == "imap_smtp"
        assert data["check_interval_minutes"] == 10
        assert data["max_emails_per_batch"] == 25
        assert data["auto_reply_enabled"] is True
        assert data["draft_only"] is False
        assert data["default_language"] == "fr"
        assert data["signature"] == "Best regards"
        assert data["email_count"] == 100
        assert data["is_current"] is True

    def test_account_summary_dict_fields(self, client, mock_account_manager):
        """Vérifie les champs du résumé."""
        account = AccountConfig(
            id="acc1",
            name="Test",
            email="test@example.com",
            provider="gmail",
            status="active",
            last_sync="2024-01-01T00:00:00",
        )
        mock_account_manager.get_all_accounts.return_value = [account]
        mock_account_manager.get_current_for_user.return_value = "other"

        response = client.get("/api/accounts")

        assert response.status_code == 200
        summary = response.get_json()["accounts"][0]
        assert summary["id"] == "acc1"
        assert summary["name"] == "Test"
        assert summary["email"] == "test@example.com"
        assert summary["provider"] == "gmail"
        assert summary["status"] == "active"
        assert summary["is_current"] is False
        assert summary["last_sync"] == "2024-01-01T00:00:00"
        # Full dict fields should NOT be in summary (except signature which is now included)
        assert "check_interval_minutes" not in summary
        # signature is now part of summary dict for display purposes
        assert "signature" in summary
