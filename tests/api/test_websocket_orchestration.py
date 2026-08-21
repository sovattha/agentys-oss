# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests pour l'intégration WebSocket des événements d'orchestration.

Story 5-3: Draft Regeneration Loop - Task 4: WebSocket Events
"""

from unittest.mock import MagicMock, patch

import pytest

from app.api.websocket import (
    emit_orchestration_start,
    emit_orchestration_iteration_start,
    emit_orchestration_iteration_complete,
    emit_orchestration_complete,
    emit_orchestration_timeout,
    emit_orchestration_error,
)


@pytest.fixture(autouse=True)
def _stub_ws_room():
    """Stub `_resolve_ws_room` so emit_* helpers actually call socketio.emit.

    Background (ISO-06 / S-01, 2026-04-24): `_resolve_ws_room` now returns
    None when no JWT user is in the Flask request context. Every emit_*
    helper short-circuits in that case to avoid cross-user broadcasts.
    These tests don't carry a JWT, so without this stub the helpers
    return early and `mock_socketio.emit.assert_called_once()` fails.
    """
    with patch("app.api.websocket._resolve_ws_room", return_value="test-user@example.com"):
        yield


class TestEmitOrchestrationStart:
    """Tests pour emit_orchestration_start."""

    @patch("app.api.websocket.get_socketio")
    def test_emit_orchestration_start_sends_event(self, mock_get_socketio):
        """Vérifie que l'événement orchestration_start est émis."""
        mock_socketio = MagicMock()
        mock_get_socketio.return_value = mock_socketio

        emit_orchestration_start(
            email_id="email-123",
            max_iterations=2,
            quality_threshold=70,
        )

        mock_socketio.emit.assert_called_once()
        call_args = mock_socketio.emit.call_args
        assert call_args[0][0] == "orchestration_start"
        assert call_args[1]["namespace"] == "/daemon"

        payload = call_args[0][1]
        assert payload["email_id"] == "email-123"
        assert payload["max_iterations"] == 2
        assert payload["quality_threshold"] == 70
        assert payload["status"] == "started"

    @patch("app.api.websocket.get_socketio")
    def test_emit_orchestration_start_default_values(self, mock_get_socketio):
        """Vérifie les valeurs par défaut."""
        mock_socketio = MagicMock()
        mock_get_socketio.return_value = mock_socketio

        emit_orchestration_start(email_id="email-123")

        payload = mock_socketio.emit.call_args[0][1]
        assert payload["max_iterations"] == 2
        assert payload["quality_threshold"] == 70

    @patch("app.api.websocket.get_socketio")
    def test_emit_orchestration_start_handles_none_socketio(self, mock_get_socketio):
        """Vérifie que rien ne crash si socketio est None."""
        mock_get_socketio.return_value = None

        # Ne devrait pas lever d'exception
        emit_orchestration_start(email_id="email-123")


class TestEmitOrchestrationIterationStart:
    """Tests pour emit_orchestration_iteration_start."""

    @patch("app.api.websocket.get_socketio")
    def test_emit_iteration_start_initial_draft(self, mock_get_socketio):
        """Vérifie l'événement pour la génération initiale."""
        mock_socketio = MagicMock()
        mock_get_socketio.return_value = mock_socketio

        emit_orchestration_iteration_start(
            email_id="email-123",
            iteration_number=1,
            is_revision=False,
        )

        mock_socketio.emit.assert_called_once()
        call_args = mock_socketio.emit.call_args
        assert call_args[0][0] == "orchestration_iteration_start"
        assert call_args[1]["namespace"] == "/daemon"

        payload = call_args[0][1]
        assert payload["email_id"] == "email-123"
        assert payload["iteration_number"] == 1
        assert payload["is_revision"] is False
        assert payload["status"] == "drafting"

    @patch("app.api.websocket.get_socketio")
    def test_emit_iteration_start_revision(self, mock_get_socketio):
        """Vérifie l'événement pour une révision."""
        mock_socketio = MagicMock()
        mock_get_socketio.return_value = mock_socketio

        emit_orchestration_iteration_start(
            email_id="email-123",
            iteration_number=2,
            is_revision=True,
        )

        payload = mock_socketio.emit.call_args[0][1]
        assert payload["iteration_number"] == 2
        assert payload["is_revision"] is True
        assert payload["status"] == "revising"

    @patch("app.api.websocket.get_socketio")
    def test_emit_iteration_start_handles_none_socketio(self, mock_get_socketio):
        """Vérifie que rien ne crash si socketio est None."""
        mock_get_socketio.return_value = None

        emit_orchestration_iteration_start(email_id="email-123", iteration_number=1)


class TestEmitOrchestrationIterationComplete:
    """Tests pour emit_orchestration_iteration_complete."""

    @patch("app.api.websocket.get_socketio")
    def test_emit_iteration_complete_valid(self, mock_get_socketio):
        """Vérifie l'événement pour une itération validée."""
        mock_socketio = MagicMock()
        mock_get_socketio.return_value = mock_socketio

        emit_orchestration_iteration_complete(
            email_id="email-123",
            iteration_number=1,
            score=85,
            decision="valid",
            duration_ms=1500,
        )

        mock_socketio.emit.assert_called_once()
        call_args = mock_socketio.emit.call_args
        assert call_args[0][0] == "orchestration_iteration_complete"
        assert call_args[1]["namespace"] == "/daemon"

        payload = call_args[0][1]
        assert payload["email_id"] == "email-123"
        assert payload["iteration_number"] == 1
        assert payload["score"] == 85
        assert payload["decision"] == "valid"
        assert payload["duration_ms"] == 1500

    @patch("app.api.websocket.get_socketio")
    def test_emit_iteration_complete_reject(self, mock_get_socketio):
        """Vérifie l'événement pour une itération rejetée."""
        mock_socketio = MagicMock()
        mock_get_socketio.return_value = mock_socketio

        emit_orchestration_iteration_complete(
            email_id="email-123",
            iteration_number=1,
            score=55,
            decision="reject",
        )

        payload = mock_socketio.emit.call_args[0][1]
        assert payload["score"] == 55
        assert payload["decision"] == "reject"
        assert payload["duration_ms"] == 0  # Default value

    @patch("app.api.websocket.get_socketio")
    def test_emit_iteration_complete_handles_none_socketio(self, mock_get_socketio):
        """Vérifie que rien ne crash si socketio est None."""
        mock_get_socketio.return_value = None

        emit_orchestration_iteration_complete(
            email_id="email-123",
            iteration_number=1,
            score=70,
            decision="valid",
        )


class TestEmitOrchestrationComplete:
    """Tests pour emit_orchestration_complete."""

    @patch("app.api.websocket.get_socketio")
    def test_emit_orchestration_complete_validated(self, mock_get_socketio):
        """Vérifie l'événement pour un brouillon validé."""
        mock_socketio = MagicMock()
        mock_get_socketio.return_value = mock_socketio

        emit_orchestration_complete(
            email_id="email-123",
            final_draft="Bonjour,\n\nMerci pour votre message.",
            final_score=85,
            total_iterations=1,
            total_duration_ms=2500,
            was_validated=True,
        )

        mock_socketio.emit.assert_called_once()
        call_args = mock_socketio.emit.call_args
        assert call_args[0][0] == "orchestration_complete"
        assert call_args[1]["namespace"] == "/daemon"

        payload = call_args[0][1]
        assert payload["email_id"] == "email-123"
        assert payload["draft"] == "Bonjour,\n\nMerci pour votre message."
        assert payload["final_score"] == 85
        assert payload["total_iterations"] == 1
        assert payload["total_duration_ms"] == 2500
        assert payload["was_validated"] is True
        assert payload["status"] == "completed"

    @patch("app.api.websocket.get_socketio")
    def test_emit_orchestration_complete_max_iterations(self, mock_get_socketio):
        """Vérifie l'événement après max_iterations (best effort)."""
        mock_socketio = MagicMock()
        mock_get_socketio.return_value = mock_socketio

        emit_orchestration_complete(
            email_id="email-123",
            final_draft="Draft après 3 itérations",
            final_score=65,
            total_iterations=3,
            total_duration_ms=8000,
            was_validated=False,
        )

        payload = mock_socketio.emit.call_args[0][1]
        assert payload["total_iterations"] == 3
        assert payload["was_validated"] is False
        assert payload["status"] == "completed"

    @patch("app.api.websocket.get_socketio")
    def test_emit_orchestration_complete_handles_none_socketio(self, mock_get_socketio):
        """Vérifie que rien ne crash si socketio est None."""
        mock_get_socketio.return_value = None

        emit_orchestration_complete(
            email_id="email-123",
            final_draft="Test",
            final_score=70,
            total_iterations=1,
            total_duration_ms=1000,
            was_validated=True,
        )


class TestEmitOrchestrationTimeout:
    """Tests pour emit_orchestration_timeout."""

    @patch("app.api.websocket.get_socketio")
    def test_emit_orchestration_timeout_with_draft(self, mock_get_socketio):
        """Vérifie l'événement timeout avec un brouillon disponible."""
        mock_socketio = MagicMock()
        mock_get_socketio.return_value = mock_socketio

        emit_orchestration_timeout(
            email_id="email-123",
            best_draft="Brouillon partiel",
            best_score=55,
            completed_iterations=2,
            total_duration_ms=240000,
        )

        mock_socketio.emit.assert_called_once()
        call_args = mock_socketio.emit.call_args
        assert call_args[0][0] == "orchestration_timeout"
        assert call_args[1]["namespace"] == "/daemon"

        payload = call_args[0][1]
        assert payload["email_id"] == "email-123"
        assert payload["draft"] == "Brouillon partiel"
        assert payload["best_score"] == 55
        assert payload["completed_iterations"] == 2
        assert payload["total_duration_ms"] == 240000
        assert payload["status"] == "timeout"

    @patch("app.api.websocket.get_socketio")
    def test_emit_orchestration_timeout_no_draft(self, mock_get_socketio):
        """Vérifie l'événement timeout sans brouillon."""
        mock_socketio = MagicMock()
        mock_get_socketio.return_value = mock_socketio

        emit_orchestration_timeout(
            email_id="email-123",
            best_draft=None,
            best_score=0,
            completed_iterations=0,
            total_duration_ms=240000,
        )

        payload = mock_socketio.emit.call_args[0][1]
        assert payload["draft"] is None
        assert payload["best_score"] == 0
        assert payload["completed_iterations"] == 0

    @patch("app.api.websocket.get_socketio")
    def test_emit_orchestration_timeout_handles_none_socketio(self, mock_get_socketio):
        """Vérifie que rien ne crash si socketio est None."""
        mock_get_socketio.return_value = None

        emit_orchestration_timeout(
            email_id="email-123",
            best_draft=None,
            best_score=0,
            completed_iterations=0,
            total_duration_ms=240000,
        )


class TestEmitOrchestrationError:
    """Tests pour emit_orchestration_error."""

    @patch("app.api.websocket.get_socketio")
    def test_emit_orchestration_error_basic(self, mock_get_socketio):
        """Vérifie l'événement d'erreur basique."""
        mock_socketio = MagicMock()
        mock_get_socketio.return_value = mock_socketio

        emit_orchestration_error(
            email_id="email-123",
            error="Rate limit exceeded",
        )

        mock_socketio.emit.assert_called_once()
        call_args = mock_socketio.emit.call_args
        assert call_args[0][0] == "orchestration_error"
        assert call_args[1]["namespace"] == "/daemon"

        payload = call_args[0][1]
        assert payload["email_id"] == "email-123"
        assert payload["error"] == "Rate limit exceeded"
        assert payload["completed_iterations"] == 0
        assert payload["draft"] is None
        assert payload["best_score"] == 0
        assert payload["status"] == "error"

    @patch("app.api.websocket.get_socketio")
    def test_emit_orchestration_error_with_partial_results(self, mock_get_socketio):
        """Vérifie l'événement d'erreur avec résultats partiels."""
        mock_socketio = MagicMock()
        mock_get_socketio.return_value = mock_socketio

        emit_orchestration_error(
            email_id="email-123",
            error="Critic failed",
            completed_iterations=1,
            best_draft="Brouillon initial",
            best_score=60,
        )

        payload = mock_socketio.emit.call_args[0][1]
        assert payload["completed_iterations"] == 1
        assert payload["draft"] == "Brouillon initial"
        assert payload["best_score"] == 60

    @patch("app.api.websocket.get_socketio")
    def test_emit_orchestration_error_handles_none_socketio(self, mock_get_socketio):
        """Vérifie que rien ne crash si socketio est None."""
        mock_get_socketio.return_value = None

        emit_orchestration_error(
            email_id="email-123",
            error="Test error",
        )
