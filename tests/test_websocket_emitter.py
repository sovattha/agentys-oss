# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests TDD pour WebSocketEventEmitter.

Implémente le push des événements daemon vers l'app Tauri via WebSocket.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch


class TestWebSocketEventEmitter:
    """Tests pour l'émetteur WebSocket."""

    def test_emit_new_email_includes_incremental_list_payload(self):
        """new_email doit transporter assez de données pour éviter un refetch HTTP."""
        from app.api.websocket import emit_new_email

        with patch("app.api.websocket.emit_to_account") as emit_to_account:
            emit_new_email({
                "email_id": "msg-1",
                "sender": "alice@example.com",
                "sender_name": "Alice",
                "subject": "Bonjour",
                "received_at": "2026-05-13T10:00:00Z",
                "is_read": False,
                "has_attachments": True,
                "conversation_id": "thread-1",
                "body_preview": "Aperçu",
            }, account_id=7)

        emit_to_account.assert_called_once()
        event, payload, account_id = emit_to_account.call_args.args
        assert event == "daemon_event"
        assert account_id == 7
        assert payload["type"] == "new_email"
        assert payload["email_id"] == "msg-1"
        assert payload["payload"]["sender_name"] == "Alice"
        assert payload["payload"]["received_at"] == "2026-05-13T10:00:00Z"
        assert payload["payload"]["has_attachments"] is True
        assert payload["payload"]["conversation_id"] == "thread-1"
        assert payload["payload"]["body_preview"] == "Aperçu"
        assert payload["payload"]["account_id"] == 7

    def test_websocket_emitter_implements_event_emitter(self):
        """WebSocketEventEmitter doit implémenter l'interface EventEmitter."""
        from app.daemon import EventEmitter
        from app.api.websocket import WebSocketEventEmitter

        emitter = WebSocketEventEmitter()
        assert isinstance(emitter, EventEmitter)

    def test_websocket_emitter_emit_calls_socketio(self):
        """emit() doit appeler socketio.emit() avec le bon format."""
        from app.daemon import DaemonEvent, DaemonEventType
        from app.api.websocket import WebSocketEventEmitter

        mock_socketio = MagicMock()
        emitter = WebSocketEventEmitter(socketio=mock_socketio)

        event = DaemonEvent(
            event_type=DaemonEventType.DRAFT_READY,
            email_id="test-123",
            timestamp=datetime.now().isoformat(),
            payload={"draft_content": "Hello", "subject": "Re: Test"},
        )

        emitter.emit(event)

        mock_socketio.emit.assert_called_once()
        call_args = mock_socketio.emit.call_args
        assert call_args[0][0] == "daemon_event"
        data = call_args[0][1]
        assert data["type"] == "draft_ready"
        assert data["email_id"] == "test-123"
        assert data["payload"]["draft_content"] == "Hello"

    def test_websocket_emitter_uses_namespace(self):
        """L'émetteur doit émettre dans le namespace /daemon."""
        from app.daemon import DaemonEvent, DaemonEventType
        from app.api.websocket import WebSocketEventEmitter

        mock_socketio = MagicMock()
        emitter = WebSocketEventEmitter(socketio=mock_socketio)

        event = DaemonEvent(
            event_type=DaemonEventType.EMAIL_RECEIVED,
            email_id="test-456",
            timestamp=datetime.now().isoformat(),
        )

        emitter.emit(event)

        call_kwargs = mock_socketio.emit.call_args[1]
        assert call_kwargs.get("namespace") == "/daemon"

    def test_websocket_emitter_event_serialization(self):
        """Les événements doivent être sérialisés en JSON-compatible."""
        from app.daemon import DaemonEvent, DaemonEventType
        from app.api.websocket import WebSocketEventEmitter

        mock_socketio = MagicMock()
        emitter = WebSocketEventEmitter(socketio=mock_socketio)

        timestamp = datetime.now().isoformat()
        event = DaemonEvent(
            event_type=DaemonEventType.PROCESSING_STARTED,
            email_id="test-789",
            timestamp=timestamp,
            payload={"status": "processing"},
        )

        emitter.emit(event)

        data = mock_socketio.emit.call_args[0][1]
        assert isinstance(data, dict)
        assert data["type"] == "processing_started"
        assert data["timestamp"] == timestamp
        assert isinstance(data["payload"], dict)

    def test_websocket_emitter_handles_missing_socketio(self):
        """L'émetteur doit gérer gracieusement l'absence de socketio."""
        from app.daemon import DaemonEvent, DaemonEventType
        from app.api.websocket import WebSocketEventEmitter

        emitter = WebSocketEventEmitter(socketio=None)

        event = DaemonEvent(
            event_type=DaemonEventType.DRAFT_READY,
            email_id="test-123",
            timestamp=datetime.now().isoformat(),
        )

        emitter.emit(event)


class TestWebSocketNamespaceHandlers:
    """Tests pour les handlers du namespace WebSocket."""

    def test_connect_handler_logs_connection(self):
        """Le handler connect doit logger la connexion."""
        from app.api.websocket import on_daemon_connect
        from flask import Flask, request as flask_req

        app = Flask(__name__)
        with app.test_request_context("/"):
            # Add sid attribute to the Flask request proxy (normally set by Socket.IO)
            flask_req.sid = "test-sid-123"
            with patch("app.api.websocket.logger") as mock_logger, \
                 patch("app.api.auth._is_loopback", return_value=True), \
                 patch("flask_socketio.join_room"):
                on_daemon_connect()

                mock_logger.info.assert_called()
                assert "connect" in str(mock_logger.info.call_args).lower()

    def test_disconnect_handler_logs_disconnection(self):
        """Le handler disconnect doit logger la déconnexion."""
        from app.api.websocket import on_daemon_disconnect

        with patch("app.api.websocket.logger") as mock_logger:
            on_daemon_disconnect()

            mock_logger.info.assert_called()
            assert "déconnecté" in str(mock_logger.info.call_args)


class TestWebSocketIntegration:
    """Tests d'intégration WebSocket avec Flask-SocketIO."""

    def test_socketio_initialization(self):
        """get_socketio() doit retourner une instance SocketIO après init_socketio."""
        from flask import Flask
        from app.api.websocket import init_socketio, get_socketio

        app = Flask(__name__)
        init_socketio(app)
        socketio = get_socketio()
        assert socketio is not None

    def test_threading_mode_allows_websocket_upgrade(self, monkeypatch):
        """Threading reste le runtime prod, mais doit annoncer l'upgrade WS."""
        from flask import Flask
        from app.api.websocket import init_socketio

        monkeypatch.setenv("AGENTYS_ASYNC_MODE", "threading")
        app = Flask(__name__)

        socketio = init_socketio(app)

        assert socketio.server.eio.async_mode == "threading"
        assert socketio.server.eio.allow_upgrades is True
        assert "websocket" in socketio.server.eio.transports

    def test_socketio_cors_defaults_include_prod_frontend(self, monkeypatch):
        """Socket.IO a son propre CORS et doit couvrir la prod sans env var."""
        from flask import Flask
        from app.api.websocket import init_socketio

        monkeypatch.delenv("API_CORS_ORIGINS", raising=False)
        app = Flask(__name__)

        socketio = init_socketio(app)

        assert "https://app.agentys.io" in socketio.server.eio.cors_allowed_origins
        assert "https://agentys.io" in socketio.server.eio.cors_allowed_origins

    def test_websocket_emitter_factory(self):
        """get_websocket_emitter() doit retourner un émetteur configuré."""
        from app.api.websocket import get_websocket_emitter, WebSocketEventEmitter

        emitter = get_websocket_emitter()
        assert isinstance(emitter, WebSocketEventEmitter)

    def test_daemon_can_use_websocket_emitter(self):
        """Le daemon doit pouvoir utiliser WebSocketEventEmitter."""
        from app.daemon import EmailDaemon
        from app.api.websocket import WebSocketEventEmitter

        mock_socketio = MagicMock()
        emitter = WebSocketEventEmitter(socketio=mock_socketio)

        with patch("app.daemon.get_container") as mock_container, \
             patch("app.daemon.get_email_provider") as mock_provider, \
             patch("app.daemon.get_message_router") as mock_router, \
             patch("app.daemon.get_correction_manager") as mock_correction, \
             patch("app.daemon.notify"):

            mock_container.return_value = MagicMock()
            mock_provider.return_value = MagicMock()
            mock_router.return_value = MagicMock()
            mock_correction.return_value = MagicMock()

            daemon = EmailDaemon(
                api_mode=True,
                event_emitter=emitter,
            )

            assert daemon.event_emitter is emitter
            assert daemon.api_mode is True
