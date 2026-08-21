# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests unitaires pour l'analyse de style via OAuth.

Couvre:
- _analyze_oauth_style() - analyse via provider OAuth configure
- analyze_style endpoint avec use_oauth=true
"""

import pytest
from unittest.mock import patch, MagicMock
from flask import Flask

from app.api.wizard import wizard_bp, _analyze_oauth_style


@pytest.fixture
def app():
    """Cree une application Flask de test."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(wizard_bp, url_prefix="/api/wizard")
    return app


@pytest.fixture
def client(app):
    """Client de test Flask."""
    return app.test_client()


class TestAnalyzeOAuthStyle:
    """Tests pour _analyze_oauth_style()."""

    def test_no_provider_configured(self):
        """Retourne erreur si aucun provider configure."""
        with patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=1), \
             patch("app.api.routes_helpers._resolve_oauth_account_id_for_db_account", return_value="oauth-1"), \
             patch("app.providers.factory.get_pooled_provider") as mock_get:
            mock_get.return_value = None

            result = _analyze_oauth_style(max_emails=10)

            assert result["success"] is False
            assert "not configured" in result["error"].lower()

    def test_provider_without_get_sent_emails(self):
        """Retourne erreur si le provider ne supporte pas get_sent_emails."""
        mock_provider = MagicMock()
        del mock_provider.get_sent_emails  # Remove the attribute

        with patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=1), \
             patch("app.api.routes_helpers._resolve_oauth_account_id_for_db_account", return_value="oauth-1"), \
             patch("app.providers.factory.get_pooled_provider") as mock_get:
            mock_get.return_value = mock_provider

            result = _analyze_oauth_style(max_emails=10)

            assert result["success"] is False
            assert "does not support" in result["error"].lower()

    def test_no_emails_found(self):
        """Retourne warning si aucun email trouve."""
        mock_provider = MagicMock()
        mock_provider.get_sent_emails.return_value = []

        with patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=1), \
             patch("app.api.routes_helpers._resolve_oauth_account_id_for_db_account", return_value="oauth-1"), \
             patch("app.providers.factory.get_pooled_provider") as mock_get:
            mock_get.return_value = mock_provider

            result = _analyze_oauth_style(max_emails=10)

            assert result["success"] is True
            assert result["emails_analyzed"] == 0
            assert "warning" in result
            assert result["profile"]["tone"] == "unknown"

    def test_analyzes_emails_successfully(self):
        """Analyse les emails avec succes."""
        mock_provider = MagicMock()
        mock_provider.get_sent_emails.return_value = [
            {"body": "Bonjour,\n\nMerci pour votre email.\n\nCordialement"},
            {"body": "Bonjour,\n\nVoici le document demande.\n\nCordialement"},
        ]

        with patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=1), \
             patch("app.api.routes_helpers._resolve_oauth_account_id_for_db_account", return_value="oauth-1"), \
             patch("app.providers.factory.get_pooled_provider") as mock_get:
            mock_get.return_value = mock_provider

            result = _analyze_oauth_style(max_emails=10)

            assert result["success"] is True
            assert result["emails_analyzed"] == 2
            assert "profile" in result

    def test_handles_exception(self):
        """Gere les exceptions gracieusement."""
        with patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=1), \
             patch("app.api.routes_helpers._resolve_oauth_account_id_for_db_account", return_value="oauth-1"), \
             patch("app.providers.factory.get_pooled_provider") as mock_get:
            mock_get.side_effect = Exception("Connection failed")

            result = _analyze_oauth_style(max_emails=10)

            assert result["success"] is False
            assert "error" in result


class TestAnalyzeStyleOAuthEndpoint:
    """Tests pour POST /api/wizard/analyze-style avec use_oauth."""

    def test_oauth_mode_calls_oauth_function(self, client):
        """Le mode OAuth appelle la fonction d'analyse OAuth."""
        with patch("app.api.wizard._analyze_oauth_style") as mock_analyze:
            mock_analyze.return_value = {
                "success": True,
                "emails_analyzed": 10,
                "profile": {
                    "signature": None,
                    "tone": "formal",
                    "formality_level": "vous",
                    "avg_response_length": 150,
                    "greeting_patterns": ["Bonjour"],
                    "closing_patterns": ["Cordialement"],
                },
            }

            response = client.post(
                "/api/wizard/analyze-style",
                json={"use_oauth": True, "max_emails": 10},
            )

            assert response.status_code == 200
            mock_analyze.assert_called_once_with(max_emails=10)

    def test_oauth_mode_returns_profile(self, client):
        """Le mode OAuth retourne le profil correctement."""
        with patch("app.api.wizard._analyze_oauth_style") as mock_analyze:
            mock_analyze.return_value = {
                "success": True,
                "emails_analyzed": 5,
                "profile": {
                    "signature": {"name": "Jean Dupont"},
                    "tone": "formal",
                    "formality_level": "vous",
                    "avg_response_length": 100,
                    "greeting_patterns": [],
                    "closing_patterns": [],
                },
            }

            response = client.post(
                "/api/wizard/analyze-style",
                json={"use_oauth": True},
            )

            data = response.json
            assert data["success"] is True
            assert data["emails_analyzed"] == 5
            assert data["profile"]["signature"]["name"] == "Jean Dupont"

    def test_oauth_mode_with_error(self, client):
        """Le mode OAuth retourne les erreurs."""
        with patch("app.api.wizard._analyze_oauth_style") as mock_analyze:
            mock_analyze.return_value = {
                "success": False,
                "error": "Provider non configure",
            }

            response = client.post(
                "/api/wizard/analyze-style",
                json={"use_oauth": True},
            )

            data = response.json
            assert data["success"] is False
            assert "error" in data

    def test_imap_mode_still_works(self, client):
        """Le mode IMAP fonctionne toujours."""
        with patch("app.api.wizard._analyze_sent_emails_style") as mock_analyze:
            mock_analyze.return_value = {
                "success": True,
                "emails_analyzed": 10,
                "profile": {
                    "signature": None,
                    "tone": "neutral",
                    "formality_level": "mixed",
                    "avg_response_length": 120,
                    "greeting_patterns": [],
                    "closing_patterns": [],
                },
            }

            response = client.post(
                "/api/wizard/analyze-style",
                json={
                    "imap_host": "imap.example.com",
                    "imap_port": 993,
                    "imap_username": "user@example.com",
                    "imap_password": "password123",
                },
            )

            assert response.status_code == 200
            mock_analyze.assert_called_once()

    def test_missing_imap_host_without_oauth(self, client):
        """Retourne erreur si imap_host manquant sans mode OAuth."""
        response = client.post(
            "/api/wizard/analyze-style",
            json={
                "imap_port": 993,
                "imap_username": "user@example.com",
                "imap_password": "password123",
            },
        )

        assert response.status_code == 400
        assert "imap_host" in response.json["error"]

    def test_missing_imap_username_without_oauth(self, client):
        """Retourne erreur si imap_username manquant sans mode OAuth."""
        response = client.post(
            "/api/wizard/analyze-style",
            json={
                "imap_host": "imap.example.com",
                "imap_password": "password123",
            },
        )

        assert response.status_code == 400
        assert "imap_username" in response.json["error"]

    def test_missing_imap_password_without_oauth(self, client):
        """Retourne erreur si imap_password manquant sans mode OAuth."""
        response = client.post(
            "/api/wizard/analyze-style",
            json={
                "imap_host": "imap.example.com",
                "imap_username": "user@example.com",
            },
        )

        assert response.status_code == 400
        assert "imap_password" in response.json["error"]
