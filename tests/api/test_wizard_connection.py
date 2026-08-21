# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests unitaires pour l'endpoint de test de connexion email.

POST /api/wizard/test-connection
- Valide les credentials IMAP et SMTP sans sauvegarder de configuration
- Retourne un status détaillé pour chaque protocole
"""

import pytest
from unittest.mock import patch, MagicMock
from flask import Flask

from app.api.wizard import wizard_bp


@pytest.fixture
def app():
    """Crée une application Flask de test."""
    from app.api import admin as _admin_module
    _original_admins = _admin_module.ADMIN_EMAILS.copy()
    _admin_module.ADMIN_EMAILS.add("admin@test.com")
    try:
        app = Flask(__name__)
        app.config["TESTING"] = True
        app.register_blueprint(wizard_bp, url_prefix="/api/wizard")
        yield app
    finally:
        _admin_module.ADMIN_EMAILS.clear()
        _admin_module.ADMIN_EMAILS.update(_original_admins)


@pytest.fixture
def client(app):
    """Client de test Flask."""
    raw_client = app.test_client()
    original_open = raw_client.open

    def open_with_admin(*args, **kwargs):
        headers = dict(kwargs.get("headers") or {})
        headers.setdefault("Authorization", _admin_auth_headers()["Authorization"])
        kwargs["headers"] = headers
        return original_open(*args, **kwargs)

    raw_client.open = open_with_admin
    return raw_client


def _admin_auth_headers() -> dict:
    """Crée un JWT admin pour les endpoints wizard protégés."""
    import time
    import jwt as _pyjwt
    from app.api.auth import JWT_SECRET, JWT_ALGORITHM

    token = _pyjwt.encode(
        {
            "sub": "99999",
            "email": "admin@test.com",
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


class TestConnectionEndpoint:
    """Tests pour POST /api/wizard/test-connection."""

    def test_missing_json_body(self, client):
        """Retourne 400 si pas de body JSON."""
        response = client.post("/api/wizard/test-connection")
        # Flask retourne 415 si Content-Type n'est pas application/json
        # ou 400 si body JSON vide
        assert response.status_code in (400, 415)

    def test_missing_imap_host(self, client):
        """Retourne 400 si IMAP host manquant."""
        response = client.post(
            "/api/wizard/test-connection",
            json={
                "smtp_host": "smtp.example.com",
                "smtp_username": "user@example.com",
            },
        )
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data
        assert "imap_host" in data["error"].lower()

    def test_missing_smtp_host(self, client):
        """Retourne 400 si SMTP host manquant."""
        response = client.post(
            "/api/wizard/test-connection",
            json={
                "imap_host": "imap.example.com",
                "imap_username": "user@example.com",
            },
        )
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data
        assert "smtp_host" in data["error"].lower()

    @patch("app.api.wizard._test_imap_connection")
    @patch("app.api.wizard._test_smtp_connection")
    def test_both_connections_successful(self, mock_smtp, mock_imap, client):
        """Retourne success si IMAP et SMTP réussissent."""
        mock_imap.return_value = {"success": True, "response_time_ms": 50.0}
        mock_smtp.return_value = {"success": True, "response_time_ms": 30.0}

        response = client.post(
            "/api/wizard/test-connection",
            json={
                "imap_host": "imap.example.com",
                "imap_port": 993,
                "imap_username": "user@example.com",
                "imap_password": "secret",
                "smtp_host": "smtp.example.com",
                "smtp_port": 587,
                "smtp_username": "user@example.com",
                "smtp_password": "secret",
            },
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["imap"]["success"] is True
        assert data["smtp"]["success"] is True

    @patch("app.api.wizard._test_imap_connection")
    @patch("app.api.wizard._test_smtp_connection")
    def test_imap_fails_smtp_succeeds(self, mock_smtp, mock_imap, client):
        """Retourne partial success si IMAP échoue mais SMTP réussit."""
        mock_imap.return_value = {"success": False, "response_time_ms": 50.0}
        mock_smtp.return_value = {"success": True, "response_time_ms": 30.0}

        response = client.post(
            "/api/wizard/test-connection",
            json={
                "imap_host": "imap.example.com",
                "imap_port": 993,
                "imap_username": "user@example.com",
                "imap_password": "wrong",
                "smtp_host": "smtp.example.com",
                "smtp_port": 587,
                "smtp_username": "user@example.com",
                "smtp_password": "secret",
            },
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is False
        assert data["imap"]["success"] is False
        assert data["smtp"]["success"] is True

    @patch("app.api.wizard._test_imap_connection")
    @patch("app.api.wizard._test_smtp_connection")
    def test_both_connections_fail(self, mock_smtp, mock_imap, client):
        """Retourne échec si IMAP et SMTP échouent."""
        mock_imap.return_value = {"success": False, "response_time_ms": 50.0}
        mock_smtp.return_value = {"success": False, "response_time_ms": 30.0}

        response = client.post(
            "/api/wizard/test-connection",
            json={
                "imap_host": "imap.example.com",
                "imap_username": "user@example.com",
                "imap_password": "wrong",
                "smtp_host": "smtp.example.com",
                "smtp_username": "user@example.com",
                "smtp_password": "wrong",
            },
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is False
        assert data["imap"]["success"] is False
        assert data["smtp"]["success"] is False

    @patch("app.api.wizard._test_imap_connection")
    @patch("app.api.wizard._test_smtp_connection")
    def test_imap_exception_handled(self, mock_smtp, mock_imap, client):
        """Gère les exceptions IMAP proprement."""
        mock_imap.return_value = {
            "success": False,
            "error": "Connection refused",
            "response_time_ms": 10.0,
        }
        mock_smtp.return_value = {"success": True, "response_time_ms": 30.0}

        response = client.post(
            "/api/wizard/test-connection",
            json={
                "imap_host": "invalid.host.com",
                "imap_username": "user@example.com",
                "imap_password": "secret",
                "smtp_host": "smtp.example.com",
                "smtp_username": "user@example.com",
                "smtp_password": "secret",
            },
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is False
        assert data["imap"]["success"] is False
        assert "error" in data["imap"]
        assert data["smtp"]["success"] is True

    @patch("app.api.wizard.IMAPAdapter")
    @patch("app.api.wizard.SMTPAdapter")
    def test_cleanup_connections_after_test(self, mock_smtp_class, mock_imap_class, client):
        """Vérifie que les connexions sont fermées après le test."""
        mock_imap_instance = MagicMock()
        mock_imap_instance.authenticate.return_value = True
        mock_imap_class.return_value = mock_imap_instance

        mock_smtp_instance = MagicMock()
        mock_smtp_instance.authenticate.return_value = True
        mock_smtp_class.return_value = mock_smtp_instance

        client.post(
            "/api/wizard/test-connection",
            json={
                "imap_host": "imap.example.com",
                "imap_username": "user@example.com",
                "imap_password": "secret",
                "smtp_host": "smtp.example.com",
                "smtp_username": "user@example.com",
                "smtp_password": "secret",
            },
        )

        mock_imap_instance.disconnect.assert_called_once()
        mock_smtp_instance.disconnect.assert_called_once()

    @patch("app.api.wizard.IMAPAdapter")
    @patch("app.api.wizard.SMTPAdapter")
    def test_uses_default_ports_when_not_specified(self, mock_smtp_class, mock_imap_class, client):
        """Utilise les ports par défaut si non spécifiés."""
        mock_imap_instance = MagicMock()
        mock_imap_instance.authenticate.return_value = True
        mock_imap_class.return_value = mock_imap_instance

        mock_smtp_instance = MagicMock()
        mock_smtp_instance.authenticate.return_value = True
        mock_smtp_class.return_value = mock_smtp_instance

        client.post(
            "/api/wizard/test-connection",
            json={
                "imap_host": "imap.example.com",
                "imap_username": "user@example.com",
                "imap_password": "secret",
                "smtp_host": "smtp.example.com",
                "smtp_username": "user@example.com",
                "smtp_password": "secret",
            },
        )

        # Vérifie que IMAPAdapter est appelé avec le port par défaut 993
        imap_call_kwargs = mock_imap_class.call_args.kwargs
        assert imap_call_kwargs.get("port") == 993

        # Vérifie que SMTPAdapter est appelé avec le port par défaut 587
        smtp_call_kwargs = mock_smtp_class.call_args.kwargs
        assert smtp_call_kwargs.get("port") == 587

    @patch("app.api.wizard._test_imap_connection")
    @patch("app.api.wizard._test_smtp_connection")
    def test_returns_response_time(self, mock_smtp, mock_imap, client):
        """Retourne le temps de réponse pour chaque connexion."""
        mock_imap.return_value = {"success": True, "response_time_ms": 123.45}
        mock_smtp.return_value = {"success": True, "response_time_ms": 67.89}

        response = client.post(
            "/api/wizard/test-connection",
            json={
                "imap_host": "imap.example.com",
                "imap_username": "user@example.com",
                "imap_password": "secret",
                "smtp_host": "smtp.example.com",
                "smtp_username": "user@example.com",
                "smtp_password": "secret",
            },
        )

        data = response.get_json()
        assert "response_time_ms" in data["imap"]
        assert "response_time_ms" in data["smtp"]
        assert isinstance(data["imap"]["response_time_ms"], (int, float))
        assert isinstance(data["smtp"]["response_time_ms"], (int, float))


class TestConnectionEndpointValidation:
    """Tests de validation des paramètres."""

    def test_validates_port_range(self, client):
        """Rejette les ports hors plage valide."""
        response = client.post(
            "/api/wizard/test-connection",
            json={
                "imap_host": "imap.example.com",
                "imap_port": 70000,  # Port invalide
                "imap_username": "user@example.com",
                "imap_password": "secret",
                "smtp_host": "smtp.example.com",
                "smtp_username": "user@example.com",
                "smtp_password": "secret",
            },
        )

        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data
        assert "port" in data["error"].lower()

    def test_validates_username_required(self, client):
        """Rejette les usernames vides."""
        response = client.post(
            "/api/wizard/test-connection",
            json={
                "imap_host": "imap.example.com",
                "imap_username": "",
                "imap_password": "secret",
                "smtp_host": "smtp.example.com",
                "smtp_username": "",
                "smtp_password": "secret",
            },
        )

        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data


class TestHelperFunctions:
    """Tests pour les fonctions helper."""

    @patch("app.api.wizard.IMAPAdapter")
    def test_test_imap_connection_success(self, mock_imap_class):
        """Test _test_imap_connection avec succès."""
        from app.api.wizard import _test_imap_connection

        mock_instance = MagicMock()
        mock_instance.authenticate.return_value = True
        mock_imap_class.return_value = mock_instance

        result = _test_imap_connection({
            "imap_host": "imap.example.com",
            "imap_port": 993,
            "imap_username": "user@example.com",
            "imap_password": "secret",
        })

        assert result["success"] is True
        assert "response_time_ms" in result
        mock_instance.disconnect.assert_called_once()

    @patch("app.api.wizard.IMAPAdapter")
    def test_test_imap_connection_failure(self, mock_imap_class):
        """Test _test_imap_connection avec échec."""
        from app.api.wizard import _test_imap_connection

        mock_instance = MagicMock()
        mock_instance.authenticate.return_value = False
        mock_imap_class.return_value = mock_instance

        result = _test_imap_connection({
            "imap_host": "imap.example.com",
            "imap_username": "user@example.com",
            "imap_password": "wrong",
        })

        assert result["success"] is False
        assert "response_time_ms" in result

    @patch("app.api.wizard.IMAPAdapter")
    def test_test_imap_connection_exception(self, mock_imap_class):
        """Test _test_imap_connection avec exception."""
        from app.api.wizard import _test_imap_connection

        mock_imap_class.side_effect = Exception("Connection refused")

        result = _test_imap_connection({
            "imap_host": "invalid.host",
            "imap_username": "user@example.com",
            "imap_password": "secret",
        })

        assert result["success"] is False
        assert "error" in result
        assert "Connection refused" in result["error"]

    @patch("app.api.wizard.SMTPAdapter")
    def test_test_smtp_connection_success(self, mock_smtp_class):
        """Test _test_smtp_connection avec succès."""
        from app.api.wizard import _test_smtp_connection

        mock_instance = MagicMock()
        mock_instance.authenticate.return_value = True
        mock_smtp_class.return_value = mock_instance

        result = _test_smtp_connection({
            "smtp_host": "smtp.example.com",
            "smtp_port": 587,
            "smtp_username": "user@example.com",
            "smtp_password": "secret",
        })

        assert result["success"] is True
        assert "response_time_ms" in result
        mock_instance.disconnect.assert_called_once()
