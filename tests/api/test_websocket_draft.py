"""Tests pour l'intégration WebSocket du draft streaming.

TDD Tests - Story 5-1 Task 4
"""

from unittest.mock import MagicMock, patch

import pytest

from app.api.websocket import (
    emit_draft_chunk,
    emit_draft_complete,
    emit_draft_error,
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


class TestEmitDraftChunk:
    """Tests pour emit_draft_chunk."""

    @patch("app.api.websocket.get_socketio")
    def test_emit_draft_chunk_sends_event(self, mock_get_socketio):
        """Vérifie que l'événement draft_chunk est émis (delta-only, sans accumulated_text)."""
        mock_socketio = MagicMock()
        mock_get_socketio.return_value = mock_socketio

        emit_draft_chunk(
            email_id="email-123",
            chunk="Hello ",
            chunk_index=0,
            accumulated_text="Hello ",
            progress_percent=25.0,
            is_final=False,
        )

        mock_socketio.emit.assert_called_once()
        call_args = mock_socketio.emit.call_args
        assert call_args[0][0] == "draft_chunk"
        assert call_args[1]["namespace"] == "/daemon"

        payload = call_args[0][1]
        assert payload["email_id"] == "email-123"
        assert payload["chunk"] == "Hello "
        assert payload["chunk_index"] == 0
        # Delta streaming: accumulated_text NOT sent for non-final chunks
        assert "accumulated_text" not in payload
        assert payload["progress_percent"] == 25.0
        assert payload["is_final"] is False

    @patch("app.api.websocket.get_socketio")
    def test_emit_draft_chunk_final_includes_accumulated_text(self, mock_get_socketio):
        """Vérifie que le chunk final inclut accumulated_text."""
        mock_socketio = MagicMock()
        mock_get_socketio.return_value = mock_socketio

        emit_draft_chunk(
            email_id="email-123",
            chunk="world!",
            chunk_index=5,
            accumulated_text="Hello world!",
            progress_percent=100.0,
            is_final=True,
        )

        mock_socketio.emit.assert_called_once()
        payload = mock_socketio.emit.call_args[0][1]
        assert payload["chunk"] == "world!"
        assert payload["accumulated_text"] == "Hello world!"
        assert payload["is_final"] is True

    @patch("app.api.websocket.get_socketio")
    def test_emit_draft_chunk_handles_none_socketio(self, mock_get_socketio):
        """Vérifie que rien ne crash si socketio est None."""
        mock_get_socketio.return_value = None

        # Ne devrait pas lever d'exception
        emit_draft_chunk(
            email_id="email-123",
            chunk="Test",
            chunk_index=0,
            accumulated_text="Test",
            progress_percent=0.0,
        )


class TestEmitDraftComplete:
    """Tests pour emit_draft_complete."""

    @patch("app.api.websocket.get_socketio")
    def test_emit_draft_complete_sends_event(self, mock_get_socketio):
        """Vérifie que l'événement draft_complete est émis."""
        mock_socketio = MagicMock()
        mock_get_socketio.return_value = mock_socketio

        emit_draft_complete(
            email_id="email-123",
            draft_content="Full draft content here.",
            confidence=0.85,
            generation_time_ms=1500,
            tokens_used=600,
            tone_detected="professional",
        )

        mock_socketio.emit.assert_called_once()
        call_args = mock_socketio.emit.call_args
        assert call_args[0][0] == "draft_complete"
        assert call_args[1]["namespace"] == "/daemon"

        payload = call_args[0][1]
        assert payload["email_id"] == "email-123"
        assert payload["draft"] == "Full draft content here."
        assert payload["confidence"] == 0.85
        assert payload["generation_time_ms"] == 1500
        assert payload["tokens_used"] == 600
        assert payload["tone_detected"] == "professional"

    @patch("app.api.websocket.get_socketio")
    def test_emit_draft_complete_handles_none_socketio(self, mock_get_socketio):
        """Vérifie que rien ne crash si socketio est None."""
        mock_get_socketio.return_value = None

        emit_draft_complete(
            email_id="email-123",
            draft_content="Test",
            confidence=0.5,
            generation_time_ms=100,
            tokens_used=50,
        )


class TestEmitDraftError:
    """Tests pour emit_draft_error."""

    @patch("app.api.websocket.get_socketio")
    def test_emit_draft_error_sends_event(self, mock_get_socketio):
        """Vérifie que l'événement draft_error est émis."""
        mock_socketio = MagicMock()
        mock_get_socketio.return_value = mock_socketio

        emit_draft_error(
            email_id="email-123",
            error="Rate limit exceeded",
            retry_count=3,
        )

        mock_socketio.emit.assert_called_once()
        call_args = mock_socketio.emit.call_args
        assert call_args[0][0] == "draft_error"
        assert call_args[1]["namespace"] == "/daemon"

        payload = call_args[0][1]
        assert payload["email_id"] == "email-123"
        assert payload["error"] == "Rate limit exceeded"
        assert payload["retry_count"] == 3

    @patch("app.api.websocket.get_socketio")
    def test_emit_draft_error_handles_none_socketio(self, mock_get_socketio):
        """Vérifie que rien ne crash si socketio est None."""
        mock_get_socketio.return_value = None

        emit_draft_error(
            email_id="email-123",
            error="Test error",
        )

    @patch("app.api.websocket.get_socketio")
    def test_emit_draft_error_default_retry_count(self, mock_get_socketio):
        """Vérifie la valeur par défaut de retry_count."""
        mock_socketio = MagicMock()
        mock_get_socketio.return_value = mock_socketio

        emit_draft_error(
            email_id="email-123",
            error="Error",
        )

        payload = mock_socketio.emit.call_args[0][1]
        assert payload["retry_count"] == 0
