# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests unitaires pour l'endpoint d'analyse de style.

POST /api/wizard/analyze-style
- Analyse les emails envoyes pour extraire le style de l'utilisateur
- Retourne signature, ton, formules detectees
"""

import pytest
from unittest.mock import patch
from flask import Flask

from app.api.wizard import wizard_bp


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


class TestAnalyzeStyleEndpoint:
    """Tests pour POST /api/wizard/analyze-style."""

    def test_missing_json_body(self, client):
        """Retourne 400 si pas de body JSON."""
        response = client.post("/api/wizard/analyze-style")
        assert response.status_code in (400, 415)

    def test_missing_email_config(self, client):
        """Retourne 400 si config email manquante."""
        response = client.post(
            "/api/wizard/analyze-style",
            json={"max_emails": 10},
        )
        assert response.status_code == 400
        assert "email" in response.json.get("error", "").lower()

    @patch("app.api.wizard._analyze_sent_emails_style")
    def test_success_with_style_detected(self, mock_analyze, client):
        """Retourne le profil de style si analyse reussie."""
        mock_analyze.return_value = {
            "success": True,
            "emails_analyzed": 10,
            "profile": {
                "signature": {
                    "name": "Jean Dupont",
                    "title": "Directeur Commercial",
                    "company": "Acme Corp",
                },
                "tone": "formal",
                "formality_level": "vous",
                "avg_response_length": 150,
                "greeting_patterns": ["Bonjour", "Cher"],
                "closing_patterns": ["Cordialement", "Bien a vous"],
            },
        }

        response = client.post(
            "/api/wizard/analyze-style",
            json={
                "imap_host": "imap.example.com",
                "imap_port": 993,
                "imap_username": "user@example.com",
                "imap_password": "password123",
                "imap_use_ssl": True,
                "max_emails": 10,
            },
        )

        assert response.status_code == 200
        data = response.json
        assert data["success"] is True
        assert data["emails_analyzed"] == 10
        assert "profile" in data
        assert data["profile"]["signature"]["name"] == "Jean Dupont"
        assert data["profile"]["tone"] == "formal"

    @patch("app.api.wizard._analyze_sent_emails_style")
    def test_not_enough_emails(self, mock_analyze, client):
        """Retourne warning si pas assez d'emails."""
        mock_analyze.return_value = {
            "success": True,
            "emails_analyzed": 2,
            "warning": "Seulement 2 emails trouves. Analyse partielle.",
            "profile": {
                "signature": None,
                "tone": "unknown",
                "formality_level": "unknown",
                "avg_response_length": 0,
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
                "max_emails": 10,
            },
        )

        assert response.status_code == 200
        data = response.json
        assert data["success"] is True
        assert "warning" in data
        assert data["emails_analyzed"] == 2

    @patch("app.api.wizard._analyze_sent_emails_style")
    def test_connection_failure(self, mock_analyze, client):
        """Retourne erreur si connexion IMAP echoue."""
        mock_analyze.return_value = {
            "success": False,
            "error": "Impossible de se connecter au serveur IMAP",
        }

        response = client.post(
            "/api/wizard/analyze-style",
            json={
                "imap_host": "invalid.example.com",
                "imap_port": 993,
                "imap_username": "user@example.com",
                "imap_password": "wrong",
            },
        )

        assert response.status_code == 200
        data = response.json
        assert data["success"] is False
        assert "error" in data

    @patch("app.api.wizard._analyze_sent_emails_style")
    def test_timeout(self, mock_analyze, client):
        """Respecte le timeout de 15 secondes."""
        mock_analyze.return_value = {
            "success": False,
            "error": "Timeout: analyse trop longue",
        }

        response = client.post(
            "/api/wizard/analyze-style",
            json={
                "imap_host": "slow.example.com",
                "imap_port": 993,
                "imap_username": "user@example.com",
                "imap_password": "password",
                "timeout_sec": 15,
            },
        )

        assert response.status_code == 200
        data = response.json
        assert data["success"] is False
        assert "timeout" in data.get("error", "").lower()


class TestSaveStyleProfile:
    """Tests pour POST /api/wizard/save-style."""

    def test_save_style_profile(self, client):
        """Sauvegarde le profil de style valide."""
        with patch("app.api.wizard._save_style_profile") as mock_save:
            mock_save.return_value = {"success": True}

            response = client.post(
                "/api/wizard/save-style",
                json={
                    "profile": {
                        "signature": {
                            "name": "Jean Dupont",
                            "title": "Directeur",
                        },
                        "tone": "formal",
                        "formality_level": "vous",
                    },
                    "confirmed": True,
                },
            )

            assert response.status_code == 200
            assert response.json["success"] is True

    def test_save_requires_confirmation(self, client):
        """Refuse de sauvegarder sans confirmation."""
        response = client.post(
            "/api/wizard/save-style",
            json={
                "profile": {"tone": "formal"},
                "confirmed": False,
            },
        )

        assert response.status_code == 400
        assert "confirm" in response.json.get("error", "").lower()
