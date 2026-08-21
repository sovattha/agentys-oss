# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests unitaires pour l'endpoint d'analyse de style approfondie (Phase 2).

POST /api/wizard/analyze-style-deep
- Lance l'analyse en background (40 emails supplementaires)
- Detecte formules recurrentes, patterns contextuels, expressions signature
- Retourne immediatement un task_id pour suivre la progression
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


class TestAnalyzeStyleDeepEndpoint:
    """Tests pour POST /api/wizard/analyze-style-deep."""

    def test_missing_json_body(self, client):
        """Retourne 400 si pas de body JSON."""
        response = client.post("/api/wizard/analyze-style-deep")
        assert response.status_code in (400, 415)

    def test_missing_email_config(self, client):
        """Retourne 400 si config email manquante."""
        response = client.post(
            "/api/wizard/analyze-style-deep",
            json={"max_emails": 50},
        )
        assert response.status_code == 400
        assert "email" in response.json.get("error", "").lower()

    @patch("app.api.wizard._start_deep_style_analysis")
    def test_starts_background_task(self, mock_start, client):
        """Demarre l'analyse en background et retourne task_id."""
        mock_start.return_value = {
            "success": True,
            "task_id": "task-12345",
            "status": "started",
            "estimated_duration_sec": 120,
        }

        response = client.post(
            "/api/wizard/analyze-style-deep",
            json={
                "imap_host": "imap.example.com",
                "imap_port": 993,
                "imap_username": "user@example.com",
                "imap_password": "password123",
                "imap_use_ssl": True,
                "max_emails": 50,
            },
        )

        assert response.status_code == 202  # Accepted
        data = response.json
        assert data["success"] is True
        assert "task_id" in data
        assert data["status"] == "started"

    @patch("app.api.wizard._start_deep_style_analysis")
    def test_connection_failure(self, mock_start, client):
        """Retourne erreur si connexion IMAP echoue."""
        mock_start.return_value = {
            "success": False,
            "error": "Impossible de se connecter au serveur IMAP",
        }

        response = client.post(
            "/api/wizard/analyze-style-deep",
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


class TestDeepStyleTaskStatus:
    """Tests pour GET /api/wizard/analyze-style-deep/<task_id>."""

    @patch("app.api.wizard._get_deep_analysis_status")
    def test_get_task_in_progress(self, mock_status, client):
        """Retourne le status d'une tache en cours."""
        mock_status.return_value = {
            "success": True,
            "task_id": "task-12345",
            "status": "in_progress",
            "progress": 60,
            "emails_analyzed": 30,
            "patterns_found": 5,
        }

        response = client.get("/api/wizard/analyze-style-deep/task-12345")

        assert response.status_code == 200
        data = response.json
        assert data["status"] == "in_progress"
        assert data["progress"] == 60

    @patch("app.api.wizard._get_deep_analysis_status")
    def test_get_task_completed(self, mock_status, client):
        """Retourne le resultat complet quand termine."""
        mock_status.return_value = {
            "success": True,
            "task_id": "task-12345",
            "status": "completed",
            "progress": 100,
            "emails_analyzed": 50,
            "deep_profile": {
                "recurring_formulas": {
                    "greetings": [
                        {"formula": "Bonjour", "frequency": 45, "contexts": ["professional"]},
                    ],
                    "closings": [
                        {"formula": "Cordialement", "frequency": 40, "contexts": ["professional"]},
                        {"formula": "Bien a vous", "frequency": 8, "contexts": ["formal"]},
                    ],
                },
                "contextual_patterns": {
                    "client": {"tone": "formal", "avg_length": 200},
                    "colleague": {"tone": "informal", "avg_length": 80},
                },
                "signature_expressions": [
                    "N'hesitez pas a me contacter",
                    "Je reste a votre disposition",
                ],
                "response_rhythm": {
                    "urgent": {"avg_delay_hours": 1},
                    "normal": {"avg_delay_hours": 24},
                },
            },
        }

        response = client.get("/api/wizard/analyze-style-deep/task-12345")

        assert response.status_code == 200
        data = response.json
        assert data["status"] == "completed"
        assert "deep_profile" in data
        assert "recurring_formulas" in data["deep_profile"]
        assert "contextual_patterns" in data["deep_profile"]

    @patch("app.api.wizard._get_deep_analysis_status")
    def test_task_not_found(self, mock_status, client):
        """Retourne 404 si task_id inconnu."""
        mock_status.return_value = None

        response = client.get("/api/wizard/analyze-style-deep/unknown-task")

        assert response.status_code == 404


class TestDeepStyleCancel:
    """Tests pour DELETE /api/wizard/analyze-style-deep/<task_id>."""

    @patch("app.api.wizard._cancel_deep_analysis")
    def test_cancel_task(self, mock_cancel, client):
        """Annule une tache en cours."""
        mock_cancel.return_value = {"success": True, "status": "cancelled"}

        response = client.delete("/api/wizard/analyze-style-deep/task-12345")

        assert response.status_code == 200
        data = response.json
        assert data["success"] is True
        assert data["status"] == "cancelled"


class TestDeepProfileIntegration:
    """Tests d'integration du profil approfondi."""

    @patch("app.api.wizard._get_deep_analysis_status")
    @patch("app.api.wizard._save_style_profile")
    def test_save_deep_profile(self, mock_save, mock_status, client):
        """Sauvegarde le profil approfondi avec confirmation."""
        mock_save.return_value = {"success": True}

        response = client.post(
            "/api/wizard/save-style",
            json={
                "profile": {
                    "signature": {"name": "Jean Dupont"},
                    "tone": "formal",
                    "formality_level": "vous",
                    "recurring_formulas": {
                        "closings": [
                            {"formula": "Cordialement", "frequency": 40},
                        ],
                    },
                },
                "confirmed": True,
            },
        )

        assert response.status_code == 200
        assert response.json["success"] is True
