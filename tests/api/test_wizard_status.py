# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests unitaires pour l'endpoint de status de l'onboarding.

GET /api/wizard/status
- Vérifie si l'onboarding est complété
- Retourne le status de la configuration
"""

import pytest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
from flask import Flask, g

from app.api.wizard import wizard_bp


@pytest.fixture
def app():
    """Crée une application Flask de test."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(wizard_bp, url_prefix="/api/wizard")
    return app


@pytest.fixture
def client(app):
    """Client de test Flask."""
    return app.test_client()


class TestOnboardingStatusEndpoint:
    """Tests pour GET /api/wizard/status."""

    @patch("app.api.wizard._has_completed_account_onboarding", return_value=False)
    @patch("app.api.wizard.get_wizard_config_store")
    def test_onboarding_not_complete_when_no_config(self, mock_store, _mock_account_onboarding, client):
        """Retourne onboarding_complete=False si pas de configuration."""
        mock_store_instance = MagicMock()
        mock_store_instance.load.return_value = None
        mock_store.return_value = mock_store_instance

        response = client.get("/api/wizard/status")

        assert response.status_code == 200
        data = response.get_json()
        assert data["onboarding_complete"] is False
        assert data["has_config"] is False

    @patch("app.api.wizard._has_completed_account_onboarding", return_value=False)
    @patch("app.api.wizard.get_wizard_config_store")
    def test_onboarding_complete_when_config_exists(self, mock_store, _mock_account_onboarding, app):
        """Retourne onboarding_complete=True si une configuration existe."""
        from app.api.wizard import get_onboarding_status

        mock_config = MagicMock()
        mock_store_instance = MagicMock()
        mock_store_instance.load.return_value = mock_config
        mock_store.return_value = mock_store_instance

        with app.test_request_context("/api/wizard/status"):
            g.auth_user = None
            response = get_onboarding_status()

        assert response.status_code == 200
        data = response.get_json()
        assert data["onboarding_complete"] is True
        assert data["has_config"] is True

    @patch("app.api.wizard._has_completed_account_onboarding", return_value=False)
    @patch("app.api.wizard.get_wizard_config_store")
    def test_authenticated_user_not_completed_by_global_config(
        self, mock_store, _mock_account_onboarding, app
    ):
        """Un fichier wizard global ne termine pas l'onboarding d'un autre user web."""
        from app.api.wizard import get_onboarding_status

        mock_config = MagicMock()
        mock_store_instance = MagicMock()
        mock_store_instance.load.return_value = mock_config
        mock_store.return_value = mock_store_instance

        with app.test_request_context("/api/wizard/status"):
            g.auth_user = {"id": 42, "email": "new@example.com"}
            response = get_onboarding_status()

        assert response.status_code == 200
        data = response.get_json()
        assert data["onboarding_complete"] is False
        assert data["has_config"] is True

    @patch("app.api.wizard._has_completed_account_onboarding", return_value=True)
    @patch("app.api.wizard.get_wizard_config_store")
    def test_onboarding_complete_when_authenticated_account_has_completed_result(
        self, mock_store, _mock_account_onboarding, client
    ):
        """Machine neuve: pas de local wizard config, mais onboarding compte déjà terminé."""

        mock_store_instance = MagicMock()
        mock_store_instance.load.return_value = None
        mock_store.return_value = mock_store_instance

        response = client.get("/api/wizard/status")

        assert response.status_code == 200
        data = response.get_json()
        assert data["onboarding_complete"] is True
        assert data["has_config"] is False
        assert data["source"] == "account_onboarding"

    def test_completed_account_onboarding_uses_authenticated_accounts(self, app):
        """Le fallback DB vérifie les comptes actifs de l'utilisateur authentifié."""
        from flask import g
        from app.api.wizard import _has_completed_account_onboarding

        session_cm = MagicMock()
        session_cm.__enter__ = MagicMock(return_value=MagicMock())
        session_cm.__exit__ = MagicMock(return_value=False)

        account = SimpleNamespace(id=7, email="user@example.com")
        account_repo = MagicMock()
        account_repo.get_active_accounts_for_user.return_value = [account]

        onboarding_repo = MagicMock()
        onboarding_repo.get_completed_by_account.return_value = SimpleNamespace(id=3)

        with patch("app.db.database.get_db_session", return_value=session_cm), \
             patch("app.db.repositories.account_repository.AccountRepository", return_value=account_repo), \
             patch("app.db.repositories.onboarding_repository.OnboardingRepository", return_value=onboarding_repo):
            with app.test_request_context("/api/wizard/status", environ_base={"REMOTE_ADDR": "203.0.113.10"}):
                g.auth_user = {"id": 42, "email": "user@example.com"}
                assert _has_completed_account_onboarding() is True

        account_repo.get_active_accounts_for_user.assert_called_once_with(42)
        onboarding_repo.get_completed_by_account.assert_called_once_with(7)

    @patch("app.api.wizard._has_completed_account_onboarding", return_value=False)
    def test_status_endpoint_returns_json(self, _mock_account_onboarding, client):
        """Le status endpoint retourne du JSON."""
        with patch("app.api.wizard.get_wizard_config_store") as mock_store:
            mock_store_instance = MagicMock()
            mock_store_instance.load.return_value = None
            mock_store.return_value = mock_store_instance

            response = client.get("/api/wizard/status")

            assert response.content_type == "application/json"
