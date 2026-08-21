# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests unitaires pour l'API des paramètres utilisateur.

GET /api/settings - Récupérer les paramètres actuels
PATCH /api/settings - Mettre à jour les paramètres
"""

import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from flask import Flask

from app.api.settings import settings_bp


@pytest.fixture
def temp_settings_file():
    """Crée un fichier de settings temporaire."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump({}, f)
        return Path(f.name)


@pytest.fixture
def app(temp_settings_file):
    """Crée une application Flask de test."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(settings_bp, url_prefix="/api")

    with patch("app.api.settings.SETTINGS_FILE", temp_settings_file):
        yield app


@pytest.fixture
def client(app, temp_settings_file):
    """Client de test Flask."""
    with patch("app.api.settings.SETTINGS_FILE", temp_settings_file):
        yield app.test_client()


class TestGetSettings:
    """Tests pour GET /api/settings."""

    def test_returns_default_settings(self, client, temp_settings_file):
        """Retourne les paramètres par défaut si aucune config."""
        with patch("app.api.settings.SETTINGS_FILE", temp_settings_file), \
             patch("app.api.settings._get_current_account_id", return_value=None):
            response = client.get("/api/settings")

        assert response.status_code == 200
        data = response.get_json()
        assert data["operation_mode"] == "controlled"
        assert data["polling_interval_minutes"] == 5
        assert data["notifications_enabled"] is True
        assert data["working_hours_only"] is False

    def test_returns_saved_settings(self, client, temp_settings_file):
        """Retourne les paramètres sauvegardés."""
        saved_settings = {
            "operation_mode": "magic",
            "polling_interval_minutes": 10,
        }
        temp_settings_file.write_text(json.dumps(saved_settings))

        with patch("app.api.settings.SETTINGS_FILE", temp_settings_file):
            response = client.get("/api/settings")

        assert response.status_code == 200
        data = response.get_json()
        assert data["operation_mode"] == "magic"
        assert data["polling_interval_minutes"] == 10


class TestUpdateSettings:
    """Tests pour PATCH /api/settings."""

    def test_missing_json_body(self, client):
        """Retourne 400 si pas de body JSON."""
        response = client.patch("/api/settings")
        assert response.status_code in (400, 415)

    def test_update_operation_mode_magic(self, client, temp_settings_file):
        """Met à jour le mode vers magique."""
        with patch("app.api.settings.SETTINGS_FILE", temp_settings_file):
            response = client.patch(
                "/api/settings",
                json={"operation_mode": "magic"}
            )

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True

        with patch("app.api.settings.SETTINGS_FILE", temp_settings_file):
            get_response = client.get("/api/settings")
        assert get_response.get_json()["operation_mode"] == "magic"

    def test_update_operation_mode_manual(self, client, temp_settings_file):
        """Met à jour le mode vers manuel."""
        with patch("app.api.settings.SETTINGS_FILE", temp_settings_file):
            response = client.patch(
                "/api/settings",
                json={"operation_mode": "manual"}
            )

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True

    def test_update_operation_mode_controlled(self, client, temp_settings_file):
        """Met à jour le mode vers contrôlé."""
        with patch("app.api.settings.SETTINGS_FILE", temp_settings_file):
            response = client.patch(
                "/api/settings",
                json={"operation_mode": "controlled"}
            )

        assert response.status_code == 200

    def test_invalid_operation_mode(self, client, temp_settings_file):
        """Retourne 400 pour un mode invalide."""
        with patch("app.api.settings.SETTINGS_FILE", temp_settings_file):
            response = client.patch(
                "/api/settings",
                json={"operation_mode": "invalid_mode"}
            )

        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data
        assert "Invalid operation_mode" in data["error"]

    def test_update_polling_interval(self, client, temp_settings_file):
        """Met à jour l'intervalle de polling."""
        with patch("app.api.settings.SETTINGS_FILE", temp_settings_file):
            response = client.patch(
                "/api/settings",
                json={"polling_interval_minutes": 15}
            )

        assert response.status_code == 200

        with patch("app.api.settings.SETTINGS_FILE", temp_settings_file):
            get_response = client.get("/api/settings")
        assert get_response.get_json()["polling_interval_minutes"] == 15

    def test_invalid_polling_interval_too_low(self, client, temp_settings_file):
        """Retourne 400 pour intervalle trop bas."""
        with patch("app.api.settings.SETTINGS_FILE", temp_settings_file):
            response = client.patch(
                "/api/settings",
                json={"polling_interval_minutes": 0}
            )

        assert response.status_code == 400

    def test_invalid_polling_interval_too_high(self, client, temp_settings_file):
        """Retourne 400 pour intervalle trop haut."""
        with patch("app.api.settings.SETTINGS_FILE", temp_settings_file):
            response = client.patch(
                "/api/settings",
                json={"polling_interval_minutes": 100}
            )

        assert response.status_code == 400

    def test_update_notifications(self, client, temp_settings_file):
        """Met à jour les notifications."""
        with patch("app.api.settings.SETTINGS_FILE", temp_settings_file):
            response = client.patch(
                "/api/settings",
                json={"notifications_enabled": False}
            )

        assert response.status_code == 200

        with patch("app.api.settings.SETTINGS_FILE", temp_settings_file):
            get_response = client.get("/api/settings")
        assert get_response.get_json()["notifications_enabled"] is False

    def test_update_working_hours(self, client, temp_settings_file):
        """Met à jour les heures de travail."""
        with patch("app.api.settings.SETTINGS_FILE", temp_settings_file):
            response = client.patch(
                "/api/settings",
                json={
                    "working_hours_only": True,
                    "working_hours_start": "08:00",
                    "working_hours_end": "20:00"
                }
            )

        assert response.status_code == 200

        with patch("app.api.settings.SETTINGS_FILE", temp_settings_file):
            get_response = client.get("/api/settings")
        data = get_response.get_json()
        assert data["working_hours_only"] is True
        assert data["working_hours_start"] == "08:00"
        assert data["working_hours_end"] == "20:00"

    def test_update_multiple_settings(self, client, temp_settings_file):
        """Met à jour plusieurs paramètres à la fois."""
        with patch("app.api.settings.SETTINGS_FILE", temp_settings_file):
            response = client.patch(
                "/api/settings",
                json={
                    "operation_mode": "magic",
                    "polling_interval_minutes": 10,
                    "notifications_enabled": False
                }
            )

        assert response.status_code == 200

        with patch("app.api.settings.SETTINGS_FILE", temp_settings_file):
            get_response = client.get("/api/settings")
        data = get_response.get_json()
        assert data["operation_mode"] == "magic"
        assert data["polling_interval_minutes"] == 10
        assert data["notifications_enabled"] is False


class TestAutoReminderOnCommitment:
    """Toggle Settings > Inbox > Auto-reminder when commitment detected.

    Default OFF — user opts in. Coercé en bool comme les autres toggles inbox.
    """

    def test_default_is_false(self, client, temp_settings_file):
        with patch("app.api.settings.SETTINGS_FILE", temp_settings_file), \
             patch("app.api.settings._get_current_account_id", return_value=None):
            response = client.get("/api/settings")
        assert response.status_code == 200
        assert response.get_json()["auto_reminder_on_commitment"] is False

    def test_patch_true_persists(self, client, temp_settings_file):
        with patch("app.api.settings.SETTINGS_FILE", temp_settings_file):
            response = client.patch(
                "/api/settings",
                json={"auto_reminder_on_commitment": True},
            )
        assert response.status_code == 200

        with patch("app.api.settings.SETTINGS_FILE", temp_settings_file):
            get_response = client.get("/api/settings")
        assert get_response.get_json()["auto_reminder_on_commitment"] is True

    def test_patch_truthy_value_coerced_to_bool(self, client, temp_settings_file):
        """Une valeur non-bool (truthy) est coercée — comme les autres toggles."""
        with patch("app.api.settings.SETTINGS_FILE", temp_settings_file):
            response = client.patch(
                "/api/settings",
                json={"auto_reminder_on_commitment": "yes"},
            )
        assert response.status_code == 200

        with patch("app.api.settings.SETTINGS_FILE", temp_settings_file):
            get_response = client.get("/api/settings")
        assert get_response.get_json()["auto_reminder_on_commitment"] is True
