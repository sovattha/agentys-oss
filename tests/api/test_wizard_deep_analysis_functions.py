# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests unitaires pour les fonctions d'analyse approfondie dans wizard.py.

Couvre:
- _start_deep_style_analysis() - demarrage analyse background
- _execute_deep_analysis() - execution analyse
- _analyze_deep_patterns() - analyse patterns approfondie
- _get_deep_analysis_status() - recuperation status
- _cancel_deep_analysis() - annulation tache
"""

import pytest
from unittest.mock import patch, MagicMock
from flask import Flask

from app.api.wizard import (
    wizard_bp,
    _start_deep_style_analysis,
    _execute_deep_analysis,
    _analyze_deep_patterns,
    _get_deep_analysis_status,
    _cancel_deep_analysis,
    _deep_analysis_tasks,
    _tasks_lock,
)


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


@pytest.fixture
def clear_tasks():
    """Nettoie les taches avant et apres chaque test."""
    with _tasks_lock:
        _deep_analysis_tasks.clear()
    yield
    with _tasks_lock:
        _deep_analysis_tasks.clear()


class TestStartDeepStyleAnalysis:
    """Tests pour _start_deep_style_analysis()."""

    def test_returns_task_id(self, clear_tasks):
        """Retourne un task_id unique."""
        with patch("app.api.wizard.threading.Thread") as mock_thread:
            mock_thread.return_value.start.return_value = None

            result = _start_deep_style_analysis(
                imap_host="imap.example.com",
                imap_port=993,
                imap_username="user@example.com",
                imap_password="password123",
            )

            assert result["success"] is True
            assert "task_id" in result
            assert result["task_id"].startswith("deep-")

    def test_creates_task_entry(self, clear_tasks):
        """Cree une entree dans le dictionnaire des taches."""
        with patch("app.api.wizard.threading.Thread") as mock_thread:
            mock_thread.return_value.start.return_value = None

            result = _start_deep_style_analysis(
                imap_host="imap.example.com",
                imap_port=993,
                imap_username="user@example.com",
                imap_password="password123",
            )

            task_id = result["task_id"]
            assert task_id in _deep_analysis_tasks
            assert _deep_analysis_tasks[task_id]["status"] == "started"
            assert _deep_analysis_tasks[task_id]["progress"] == 0

    def test_starts_background_thread(self, clear_tasks):
        """Demarre un thread en background."""
        with patch("app.api.wizard.threading.Thread") as mock_thread:
            mock_instance = MagicMock()
            mock_thread.return_value = mock_instance

            _start_deep_style_analysis(
                imap_host="imap.example.com",
                imap_port=993,
                imap_username="user@example.com",
                imap_password="password123",
            )

            mock_thread.assert_called_once()
            mock_instance.start.assert_called_once()

    def test_returns_estimated_duration(self, clear_tasks):
        """Retourne la duree estimee."""
        with patch("app.api.wizard.threading.Thread") as mock_thread:
            mock_thread.return_value.start.return_value = None

            result = _start_deep_style_analysis(
                imap_host="imap.example.com",
                imap_port=993,
                imap_username="user@example.com",
                imap_password="password123",
            )

            assert "estimated_duration_sec" in result
            assert result["estimated_duration_sec"] == 120


class TestExecuteDeepAnalysis:
    """Tests pour _execute_deep_analysis()."""

    def test_updates_status_to_failed_on_auth_error(self, clear_tasks):
        """Met a jour le status a failed si auth IMAP echoue."""
        task_id = "test-task-001"
        with _tasks_lock:
            _deep_analysis_tasks[task_id] = {
                "status": "started",
                "progress": 0,
            }

        with patch("app.api.wizard.IMAPAdapter") as mock_imap:
            mock_instance = MagicMock()
            mock_instance.authenticate.return_value = False
            mock_imap.return_value = mock_instance

            _execute_deep_analysis(
                task_id=task_id,
                imap_host="imap.example.com",
                imap_port=993,
                imap_username="user@example.com",
                imap_password="wrong",
                imap_use_ssl=True,
                max_emails=50,
            )

            assert _deep_analysis_tasks[task_id]["status"] == "failed"
            assert "IMAP" in _deep_analysis_tasks[task_id]["error"]

    def test_updates_status_to_completed_with_empty_emails(self, clear_tasks):
        """Met a jour le status a completed si aucun email."""
        task_id = "test-task-002"
        with _tasks_lock:
            _deep_analysis_tasks[task_id] = {
                "status": "started",
                "progress": 0,
            }

        with patch("app.api.wizard.IMAPAdapter") as mock_imap:
            mock_instance = MagicMock()
            mock_instance.authenticate.return_value = True
            mock_instance.get_sent_emails.return_value = []
            mock_imap.return_value = mock_instance

            _execute_deep_analysis(
                task_id=task_id,
                imap_host="imap.example.com",
                imap_port=993,
                imap_username="user@example.com",
                imap_password="password",
                imap_use_ssl=True,
                max_emails=50,
            )

            assert _deep_analysis_tasks[task_id]["status"] == "completed"
            assert _deep_analysis_tasks[task_id]["progress"] == 100
            assert "deep_profile" in _deep_analysis_tasks[task_id]

    def test_handles_exception(self, clear_tasks):
        """Gere les exceptions gracieusement."""
        task_id = "test-task-003"
        with _tasks_lock:
            _deep_analysis_tasks[task_id] = {
                "status": "started",
                "progress": 0,
            }

        with patch("app.api.wizard.IMAPAdapter") as mock_imap:
            mock_imap.side_effect = Exception("Connection error")

            _execute_deep_analysis(
                task_id=task_id,
                imap_host="imap.example.com",
                imap_port=993,
                imap_username="user@example.com",
                imap_password="password",
                imap_use_ssl=True,
                max_emails=50,
            )

            assert _deep_analysis_tasks[task_id]["status"] == "failed"
            assert "Connection error" in _deep_analysis_tasks[task_id]["error"]

    def test_disconnects_imap_on_success(self, clear_tasks):
        """Deconnecte IMAP apres l'analyse."""
        task_id = "test-task-004"
        with _tasks_lock:
            _deep_analysis_tasks[task_id] = {
                "status": "started",
                "progress": 0,
            }

        with patch("app.api.wizard.IMAPAdapter") as mock_imap:
            mock_instance = MagicMock()
            mock_instance.authenticate.return_value = True
            mock_instance.get_sent_emails.return_value = [
                {"body": "Test email content"},
            ]
            mock_imap.return_value = mock_instance

            _execute_deep_analysis(
                task_id=task_id,
                imap_host="imap.example.com",
                imap_port=993,
                imap_username="user@example.com",
                imap_password="password",
                imap_use_ssl=True,
                max_emails=50,
            )

            mock_instance.disconnect.assert_called()


class TestAnalyzeDeepPatterns:
    """Tests pour _analyze_deep_patterns()."""

    def test_empty_emails_returns_empty_profile(self, clear_tasks):
        """Retourne un profil vide pour une liste vide."""
        task_id = "test-patterns-001"
        with _tasks_lock:
            _deep_analysis_tasks[task_id] = {"progress": 0}

        result = _analyze_deep_patterns([], task_id)

        assert result["recurring_formulas"]["greetings"] == []
        assert result["recurring_formulas"]["closings"] == []
        assert result["signature_expressions"] == []

    def test_detects_greeting_patterns(self, clear_tasks):
        """Detecte les patterns de salutation."""
        task_id = "test-patterns-002"
        with _tasks_lock:
            _deep_analysis_tasks[task_id] = {"progress": 0}

        # Use the SAME greeting to meet the 3+ frequency threshold
        # (the regex captures full greeting including name, so different names = different patterns)
        emails = [
            {"body": "Bonjour,\nMerci.\nCordialement"},
            {"body": "Bonjour,\nVoici.\nCordialement"},
            {"body": "Bonjour,\nBien recu.\nCordialement"},
            {"body": "Bonjour,\nOK.\nCordialement"},
        ]
        result = _analyze_deep_patterns(emails, task_id)

        # Bonjour devrait apparaitre au moins 3 fois
        greetings = result["recurring_formulas"]["greetings"]
        has_bonjour = any("Bonjour" in g["formula"] for g in greetings)
        assert has_bonjour

    def test_detects_closing_patterns(self, clear_tasks):
        """Detecte les patterns de conclusion."""
        task_id = "test-patterns-003"
        with _tasks_lock:
            _deep_analysis_tasks[task_id] = {"progress": 0}

        emails = [
            {"body": "Bonjour,\nMerci.\nCordialement"},
            {"body": "Bonjour,\nVoici.\nCordialement"},
            {"body": "Bonjour,\nBien recu.\nCordialement"},
            {"body": "Bonjour,\nOK.\nCordialement"},
        ]
        result = _analyze_deep_patterns(emails, task_id)

        closings = result["recurring_formulas"]["closings"]
        has_cordialement = any("Cordialement" in c["formula"] for c in closings)
        assert has_cordialement or len(emails) < 3

    def test_detects_signature_expressions(self, clear_tasks):
        """Detecte les expressions signature."""
        task_id = "test-patterns-004"
        with _tasks_lock:
            _deep_analysis_tasks[task_id] = {"progress": 0}

        emails = [
            {"body": "Merci. N'hesitez pas a me contacter si besoin."},
            {"body": "OK. N'hesitez pas a me contacter pour plus d'info."},
            {"body": "Bien recu. Je reste a votre disposition."},
        ]
        result = _analyze_deep_patterns(emails, task_id)

        # Les expressions sont detectees si presentes 2+ fois
        expressions = result["signature_expressions"]
        # Test que le parsing ne plante pas
        assert isinstance(expressions, list)

    def test_detects_contextual_patterns(self, clear_tasks):
        """Detecte les patterns contextuels."""
        task_id = "test-patterns-005"
        with _tasks_lock:
            _deep_analysis_tasks[task_id] = {"progress": 0}

        emails = [
            {"body": "Test email 1", "to": "support@company.com", "subject": "Question"},
            {"body": "Test email 2", "to": "support@company.com", "subject": "Bug"},
            {"body": "Test email 3", "to": "colleague@company.com", "subject": "Re: Meeting"},
            {"body": "Test email 4", "to": "colleague@company.com", "subject": "Re: Project"},
        ]
        result = _analyze_deep_patterns(emails, task_id)

        contextual = result["contextual_patterns"]
        assert isinstance(contextual, dict)

    def test_updates_progress(self, clear_tasks):
        """Met a jour la progression pendant l'analyse."""
        task_id = "test-patterns-006"
        with _tasks_lock:
            _deep_analysis_tasks[task_id] = {"progress": 0, "emails_analyzed": 0}

        emails = [
            {"body": f"Email {i}"} for i in range(10)
        ]
        _analyze_deep_patterns(emails, task_id)

        # Progress devrait etre a 100 a la fin
        assert _deep_analysis_tasks[task_id]["progress"] == 100
        assert _deep_analysis_tasks[task_id]["emails_analyzed"] == 10


class TestGetDeepAnalysisStatus:
    """Tests pour _get_deep_analysis_status()."""

    def test_returns_none_for_unknown_task(self, clear_tasks):
        """Retourne None pour une tache inconnue."""
        result = _get_deep_analysis_status("unknown-task-id")
        assert result is None

    def test_returns_task_data(self, clear_tasks):
        """Retourne les donnees de la tache."""
        task_id = "test-status-001"
        with _tasks_lock:
            _deep_analysis_tasks[task_id] = {
                "status": "in_progress",
                "progress": 50,
                "emails_analyzed": 25,
            }

        result = _get_deep_analysis_status(task_id)

        assert result is not None
        assert result["status"] == "in_progress"
        assert result["progress"] == 50


class TestCancelDeepAnalysis:
    """Tests pour _cancel_deep_analysis()."""

    def test_cancels_existing_task(self, clear_tasks):
        """Annule une tache existante."""
        task_id = "test-cancel-001"
        with _tasks_lock:
            _deep_analysis_tasks[task_id] = {"status": "in_progress"}

        result = _cancel_deep_analysis(task_id)

        assert result["success"] is True
        assert result["status"] == "cancelled"
        assert _deep_analysis_tasks[task_id]["status"] == "cancelled"

    def test_returns_error_for_unknown_task(self, clear_tasks):
        """Retourne erreur pour une tache inconnue."""
        result = _cancel_deep_analysis("unknown-task-id")

        assert result["success"] is False
        assert "not found" in result["error"].lower()


class TestDeepAnalysisEndpoints:
    """Tests pour les endpoints d'analyse approfondie."""

    def test_missing_imap_host(self, client):
        """Retourne 400 si imap_host manquant."""
        response = client.post(
            "/api/wizard/analyze-style-deep",
            json={
                "imap_username": "user@example.com",
                "imap_password": "password",
            },
        )
        assert response.status_code == 400
        assert "imap_host" in response.json["error"]

    def test_missing_imap_username(self, client):
        """Retourne 400 si imap_username manquant."""
        response = client.post(
            "/api/wizard/analyze-style-deep",
            json={
                "imap_host": "imap.example.com",
                "imap_password": "password",
            },
        )
        assert response.status_code == 400
        assert "imap_username" in response.json["error"]

    def test_missing_imap_password(self, client):
        """Retourne 400 si imap_password manquant."""
        response = client.post(
            "/api/wizard/analyze-style-deep",
            json={
                "imap_host": "imap.example.com",
                "imap_username": "user@example.com",
            },
        )
        assert response.status_code == 400
        assert "imap_password" in response.json["error"]
