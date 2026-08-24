# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests pour l'intégration WebSocket des événements critique.

TDD Tests - Story 5-2 Task 3
"""

from unittest.mock import MagicMock, patch

import pytest

from app.api.websocket import (
    emit_critique_start,
    emit_critique_complete,
    emit_critique_error,
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


class TestEmitCritiqueStart:
    """Tests pour emit_critique_start."""

    @patch("app.api.websocket.get_socketio")
    def test_emit_critique_start_sends_event(self, mock_get_socketio):
        """Vérifie que l'événement critique_start est émis."""
        mock_socketio = MagicMock()
        mock_get_socketio.return_value = mock_socketio

        emit_critique_start(
            email_id="email-123",
            draft_id="draft-456",
        )

        mock_socketio.emit.assert_called_once()
        call_args = mock_socketio.emit.call_args
        assert call_args[0][0] == "critique_start"
        assert call_args[1]["namespace"] == "/daemon"

        payload = call_args[0][1]
        assert payload["email_id"] == "email-123"
        assert payload["draft_id"] == "draft-456"
        assert payload["status"] == "evaluating"

    @patch("app.api.websocket.get_socketio")
    def test_emit_critique_start_without_draft_id(self, mock_get_socketio):
        """Vérifie que draft_id est optionnel."""
        mock_socketio = MagicMock()
        mock_get_socketio.return_value = mock_socketio

        emit_critique_start(email_id="email-123")

        mock_socketio.emit.assert_called_once()
        payload = mock_socketio.emit.call_args[0][1]
        assert payload["email_id"] == "email-123"
        assert payload["draft_id"] is None

    @patch("app.api.websocket.get_socketio")
    def test_emit_critique_start_handles_none_socketio(self, mock_get_socketio):
        """Vérifie que rien ne crash si socketio est None."""
        mock_get_socketio.return_value = None

        # Ne devrait pas lever d'exception
        emit_critique_start(email_id="email-123")


class TestEmitCritiqueComplete:
    """Tests pour emit_critique_complete."""

    @patch("app.api.websocket.get_socketio")
    def test_emit_critique_complete_sends_event(self, mock_get_socketio):
        """Vérifie que l'événement critique_complete est émis."""
        mock_socketio = MagicMock()
        mock_get_socketio.return_value = mock_socketio

        emit_critique_complete(
            email_id="email-123",
            decision="valid",
            overall_score=85,
            scores={
                "coherence": 90,
                "tone": 85,
                "completeness": 80,
                "errors": 85,
            },
            suggestions=[],
            explanation="Le brouillon est de bonne qualité.",
            evaluation_time_ms=1200,
            tokens_used=350,
            draft_id="draft-456",
        )

        mock_socketio.emit.assert_called_once()
        call_args = mock_socketio.emit.call_args
        assert call_args[0][0] == "critique_complete"
        assert call_args[1]["namespace"] == "/daemon"

        payload = call_args[0][1]
        assert payload["email_id"] == "email-123"
        assert payload["draft_id"] == "draft-456"
        assert payload["decision"] == "valid"
        assert payload["overall_score"] == 85
        assert payload["scores"]["coherence"] == 90
        assert payload["scores"]["tone"] == 85
        assert payload["scores"]["completeness"] == 80
        assert payload["scores"]["errors"] == 85
        assert payload["suggestions"] == []
        assert payload["explanation"] == "Le brouillon est de bonne qualité."
        assert payload["evaluation_time_ms"] == 1200
        assert payload["tokens_used"] == 350

    @patch("app.api.websocket.get_socketio")
    def test_emit_critique_complete_with_reject(self, mock_get_socketio):
        """Vérifie l'émission pour une décision REJECT avec suggestions."""
        mock_socketio = MagicMock()
        mock_get_socketio.return_value = mock_socketio

        emit_critique_complete(
            email_id="email-123",
            decision="reject",
            overall_score=55,
            scores={
                "coherence": 60,
                "tone": 50,
                "completeness": 55,
                "errors": 55,
            },
            suggestions=[
                "Améliorer le ton professionnel",
                "Répondre à toutes les questions posées",
            ],
            explanation="Le brouillon manque de complétude.",
            evaluation_time_ms=1000,
            tokens_used=300,
        )

        mock_socketio.emit.assert_called_once()
        payload = mock_socketio.emit.call_args[0][1]
        assert payload["decision"] == "reject"
        assert payload["overall_score"] == 55
        assert len(payload["suggestions"]) == 2
        assert "Améliorer le ton professionnel" in payload["suggestions"]

    @patch("app.api.websocket.get_socketio")
    def test_emit_critique_complete_without_draft_id(self, mock_get_socketio):
        """Vérifie que draft_id est optionnel."""
        mock_socketio = MagicMock()
        mock_get_socketio.return_value = mock_socketio

        emit_critique_complete(
            email_id="email-123",
            decision="valid",
            overall_score=80,
            scores={"coherence": 80, "tone": 80, "completeness": 80, "errors": 80},
            suggestions=[],
            explanation="OK",
            evaluation_time_ms=500,
            tokens_used=200,
        )

        payload = mock_socketio.emit.call_args[0][1]
        assert payload["draft_id"] is None

    @patch("app.api.websocket.get_socketio")
    def test_emit_critique_complete_handles_none_socketio(self, mock_get_socketio):
        """Vérifie que rien ne crash si socketio est None."""
        mock_get_socketio.return_value = None

        # Ne devrait pas lever d'exception
        emit_critique_complete(
            email_id="email-123",
            decision="valid",
            overall_score=80,
            scores={},
            suggestions=[],
            explanation="",
            evaluation_time_ms=500,
            tokens_used=200,
        )


class TestEmitCritiqueError:
    """Tests pour emit_critique_error."""

    @patch("app.api.websocket.get_socketio")
    def test_emit_critique_error_sends_event(self, mock_get_socketio):
        """Vérifie que l'événement critique_error est émis."""
        mock_socketio = MagicMock()
        mock_get_socketio.return_value = mock_socketio

        emit_critique_error(
            email_id="email-123",
            error="Rate limit exceeded",
            retry_count=2,
            draft_id="draft-456",
        )

        mock_socketio.emit.assert_called_once()
        call_args = mock_socketio.emit.call_args
        assert call_args[0][0] == "critique_error"
        assert call_args[1]["namespace"] == "/daemon"

        payload = call_args[0][1]
        assert payload["email_id"] == "email-123"
        assert payload["draft_id"] == "draft-456"
        assert payload["error"] == "Rate limit exceeded"
        assert payload["retry_count"] == 2

    @patch("app.api.websocket.get_socketio")
    def test_emit_critique_error_default_retry_count(self, mock_get_socketio):
        """Vérifie que retry_count a une valeur par défaut de 0."""
        mock_socketio = MagicMock()
        mock_get_socketio.return_value = mock_socketio

        emit_critique_error(
            email_id="email-123",
            error="Unknown error",
        )

        payload = mock_socketio.emit.call_args[0][1]
        assert payload["retry_count"] == 0
        assert payload["draft_id"] is None

    @patch("app.api.websocket.get_socketio")
    def test_emit_critique_error_handles_none_socketio(self, mock_get_socketio):
        """Vérifie que rien ne crash si socketio est None."""
        mock_get_socketio.return_value = None

        # Ne devrait pas lever d'exception
        emit_critique_error(
            email_id="email-123",
            error="Test error",
        )

    @patch("app.api.websocket.get_socketio")
    def test_emit_critique_error_with_rate_limit(self, mock_get_socketio):
        """Vérifie l'émission pour une erreur de rate limit."""
        mock_socketio = MagicMock()
        mock_get_socketio.return_value = mock_socketio

        emit_critique_error(
            email_id="email-123",
            error="Rate limit exceeded. Retry after 30 seconds.",
            retry_count=3,
        )

        payload = mock_socketio.emit.call_args[0][1]
        assert "Rate limit" in payload["error"]
        assert payload["retry_count"] == 3
