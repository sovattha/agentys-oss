# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests TDD pour le mode API du daemon.

Le mode API permet au daemon de fonctionner comme un worker
qui émet des événements au lieu de créer les brouillons directement.
Cela permet à l'app Tauri de recevoir les événements et de les afficher
à l'utilisateur pour validation avant création du brouillon.

Couvre:
- DaemonEventType enum
- DaemonEvent dataclass
- EventEmitter interface et implémentations
- EmailDaemon.api_mode flag
- Émission d'événements au lieu de création de brouillons
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

from app.interfaces.email_provider import StandardEmail


class TestDaemonEventType:
    """Tests pour les types d'événements du daemon."""

    def test_event_types_exist(self):
        """Les types d'événements principaux doivent exister."""
        from app.daemon import DaemonEventType

        assert hasattr(DaemonEventType, "EMAIL_RECEIVED")
        assert hasattr(DaemonEventType, "DRAFT_READY")
        assert hasattr(DaemonEventType, "PROCESSING_STARTED")
        assert hasattr(DaemonEventType, "PROCESSING_FAILED")
        assert hasattr(DaemonEventType, "EMAIL_SKIPPED")

    def test_event_type_values(self):
        """Les valeurs des événements doivent être des strings."""
        from app.daemon import DaemonEventType

        assert DaemonEventType.EMAIL_RECEIVED.value == "email_received"
        assert DaemonEventType.DRAFT_READY.value == "draft_ready"


class TestDaemonEvent:
    """Tests pour la structure d'un événement daemon."""

    def test_event_creation(self):
        """Un événement doit pouvoir être créé avec les champs requis."""
        from app.daemon import DaemonEvent, DaemonEventType

        event = DaemonEvent(
            event_type=DaemonEventType.DRAFT_READY,
            email_id="test-123",
            timestamp=datetime.now().isoformat(),
        )

        assert event.event_type == DaemonEventType.DRAFT_READY
        assert event.email_id == "test-123"
        assert event.timestamp is not None

    def test_event_with_payload(self):
        """Un événement peut contenir des données supplémentaires."""
        from app.daemon import DaemonEvent, DaemonEventType

        event = DaemonEvent(
            event_type=DaemonEventType.DRAFT_READY,
            email_id="test-123",
            timestamp=datetime.now().isoformat(),
            payload={
                "draft_content": "Hello, this is a response.",
                "subject": "Re: Test",
                "recipient": "sender@example.com",
                "classification": "NORMAL",
                "priority_score": 75,
            }
        )

        assert event.payload["draft_content"] == "Hello, this is a response."
        assert event.payload["priority_score"] == 75


class TestEventEmitter:
    """Tests pour l'interface d'émission d'événements."""

    def test_in_memory_emitter(self):
        """Un émetteur en mémoire doit stocker les événements."""
        from app.daemon import InMemoryEventEmitter, DaemonEvent, DaemonEventType

        emitter = InMemoryEventEmitter()
        event = DaemonEvent(
            event_type=DaemonEventType.EMAIL_RECEIVED,
            email_id="test-123",
            timestamp=datetime.now().isoformat(),
        )

        emitter.emit(event)

        assert len(emitter.events) == 1
        assert emitter.events[0].email_id == "test-123"

    def test_emitter_with_callback(self):
        """Un émetteur peut appeler un callback lors de l'émission."""
        from app.daemon import InMemoryEventEmitter, DaemonEvent, DaemonEventType

        received_events = []
        def callback(event: DaemonEvent):
            received_events.append(event)

        emitter = InMemoryEventEmitter(callback=callback)
        event = DaemonEvent(
            event_type=DaemonEventType.DRAFT_READY,
            email_id="test-456",
            timestamp=datetime.now().isoformat(),
        )

        emitter.emit(event)

        assert len(received_events) == 1
        assert received_events[0].email_id == "test-456"


class TestDaemonApiMode:
    """Tests pour le mode API du daemon."""

    @pytest.fixture
    def mock_email(self):
        """Email de test."""
        return StandardEmail(
            id="test-email-123",
            sender="sender@example.com",
            sender_name="John Doe",
            to=["recipient@example.com"],
            cc=[],
            subject="Test Subject",
            body="Hello, please respond to this email.",
            body_html="<p>Hello</p>",
            received_at=datetime.now().isoformat(),
            is_read=False,
            has_attachments=False,
            conversation_id="thread-123",
            provider_source="test",
        )

    @pytest.fixture
    def mock_provider(self, mock_email):
        """Provider mock qui retourne l'email de test."""
        provider = MagicMock()
        provider.authenticate.return_value = True
        provider.get_unread_messages.return_value = [mock_email]
        provider.create_draft.return_value = "draft-456"
        provider.mark_as_read.return_value = True
        provider.apply_label.return_value = True
        return provider

    @pytest.fixture
    def mock_agents(self):
        """Agents IA mockés."""
        drafter = MagicMock()
        drafter.draft.return_value = "Generated response content."
        drafter.revise.return_value = "Revised response content."

        critic = MagicMock()
        critic.evaluate.return_value = "VALID: Good response."
        critic.is_valid.return_value = True

        prioritizer = MagicMock()
        prioritizer.analyze.return_value = {"priority_score": 80}

        classifier = MagicMock()
        classifier.classify.return_value = {"category": "NORMAL"}
        classifier.should_skip.return_value = False

        return drafter, critic, prioritizer, classifier

    @pytest.fixture
    def mock_trackers(self):
        """Trackers mockés."""
        tracker = MagicMock()
        tracker.is_processed.return_value = False
        tracker.mark_processed.return_value = None
        tracker.count.return_value = 0

        drafts_tracker = MagicMock()
        drafts_tracker.is_processed.return_value = False

        return tracker, drafts_tracker

    @patch("app.daemon.notify")
    @patch("app.daemon.get_container")
    @patch("app.daemon.get_email_provider")
    @patch("app.daemon.get_message_router")
    @patch("app.daemon.get_correction_manager")
    def test_api_mode_flag_exists(
        self,
        mock_correction_manager,
        mock_router,
        mock_get_provider,
        mock_container,
        mock_notify,
        mock_provider,
    ):
        """Le daemon doit avoir un flag api_mode."""
        from app.daemon import EmailDaemon

        mock_get_provider.return_value = mock_provider
        mock_container.return_value = MagicMock()
        mock_router.return_value = MagicMock()
        mock_correction_manager.return_value = MagicMock()

        daemon = EmailDaemon(api_mode=True)

        assert daemon.api_mode is True

    @patch("app.daemon.notify")
    @patch("app.daemon.get_container")
    @patch("app.daemon.get_email_provider")
    @patch("app.daemon.get_message_router")
    @patch("app.daemon.get_correction_manager")
    def test_api_mode_default_false(
        self,
        mock_correction_manager,
        mock_router,
        mock_get_provider,
        mock_container,
        mock_notify,
        mock_provider,
    ):
        """Le mode API doit être désactivé par défaut."""
        from app.daemon import EmailDaemon

        mock_get_provider.return_value = mock_provider
        mock_container.return_value = MagicMock()
        mock_router.return_value = MagicMock()
        mock_correction_manager.return_value = MagicMock()

        daemon = EmailDaemon()

        assert daemon.api_mode is False
