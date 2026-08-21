# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests for app/telegram_integration.py module.

Covers TelegramBot, TelegramConfig, TelegramMessage, TelegramSupportTicket,
and all notification/support ticket functionality.
"""

import asyncio
import json
import pytest
from datetime import datetime
from unittest.mock import Mock, patch

from app.telegram_integration import (
    TelegramBot,
    TelegramConfig,
    TelegramMessage,
    TelegramSupportTicket,
    TelegramMessageType,
    get_telegram_bot,
)


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def temp_data_dir(tmp_path):
    """Create a temporary data directory for tests."""
    return tmp_path / "telegram"


@pytest.fixture
def mock_telegram_data_dir(temp_data_dir, monkeypatch):
    """Mock TELEGRAM_DATA_DIR to use temp directory."""
    temp_data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("app.telegram_integration.TELEGRAM_DATA_DIR", temp_data_dir)
    return temp_data_dir


@pytest.fixture
def telegram_bot(mock_telegram_data_dir):
    """Create a TelegramBot instance with mocked data directory."""
    return TelegramBot()


@pytest.fixture
def configured_bot(telegram_bot):
    """Create a configured TelegramBot instance."""
    telegram_bot.config.bot_token = "test_token_123"
    telegram_bot.config.notifications_chat_id = "123456789"
    telegram_bot.config.support_chat_id = "987654321"
    telegram_bot._save()
    return telegram_bot


# ============================================================================
# TEST DATA CLASSES
# ============================================================================


class TestTelegramMessageType:
    """Tests for TelegramMessageType enum."""

    def test_notification_value(self):
        """Test NOTIFICATION enum value."""
        assert TelegramMessageType.NOTIFICATION.value == "notification"

    def test_support_request_value(self):
        """Test SUPPORT_REQUEST enum value."""
        assert TelegramMessageType.SUPPORT_REQUEST.value == "support_request"

    def test_support_response_value(self):
        """Test SUPPORT_RESPONSE enum value."""
        assert TelegramMessageType.SUPPORT_RESPONSE.value == "support_response"

    def test_alert_value(self):
        """Test ALERT enum value."""
        assert TelegramMessageType.ALERT.value == "alert"

    def test_status_value(self):
        """Test STATUS enum value."""
        assert TelegramMessageType.STATUS.value == "status"


class TestTelegramConfig:
    """Tests for TelegramConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = TelegramConfig()
        assert config.bot_token is None
        assert config.support_chat_id is None
        assert config.notifications_chat_id is None
        assert config.enabled is True
        assert config.language == "fr"
        assert config.bot_name is None
        assert config.avatar_url is None

    def test_custom_values(self):
        """Test custom configuration values."""
        config = TelegramConfig(
            bot_token="test_token",
            support_chat_id="support_123",
            notifications_chat_id="notif_456",
            enabled=False,
            language="en",
            bot_name="TestBot",
            avatar_url="https://example.com/avatar.png"
        )
        assert config.bot_token == "test_token"
        assert config.support_chat_id == "support_123"
        assert config.notifications_chat_id == "notif_456"
        assert config.enabled is False
        assert config.language == "en"
        assert config.bot_name == "TestBot"
        assert config.avatar_url == "https://example.com/avatar.png"


class TestTelegramMessage:
    """Tests for TelegramMessage dataclass."""

    def test_required_fields(self):
        """Test message with required fields."""
        msg = TelegramMessage(
            id="msg_001",
            chat_id="chat_123",
            author_id="user_456",
            author_name="John Doe",
            content="Test message"
        )
        assert msg.id == "msg_001"
        assert msg.chat_id == "chat_123"
        assert msg.author_id == "user_456"
        assert msg.author_name == "John Doe"
        assert msg.content == "Test message"
        assert msg.message_type == "notification"
        assert msg.responded is False
        assert msg.response_content is None
        assert msg.metadata == {}

    def test_custom_message_type(self):
        """Test message with custom type."""
        msg = TelegramMessage(
            id="msg_002",
            chat_id="chat_123",
            author_id="user_456",
            author_name="Jane Doe",
            content="Support request",
            message_type=TelegramMessageType.SUPPORT_REQUEST.value
        )
        assert msg.message_type == "support_request"

    def test_created_at_auto_generated(self):
        """Test that created_at is auto-generated."""
        msg = TelegramMessage(
            id="msg_003",
            chat_id="chat_123",
            author_id="user_456",
            author_name="Test User",
            content="Test"
        )
        assert msg.created_at is not None
        datetime.fromisoformat(msg.created_at)

    def test_metadata_field(self):
        """Test metadata field."""
        msg = TelegramMessage(
            id="msg_004",
            chat_id="chat_123",
            author_id="user_456",
            author_name="Test User",
            content="Test",
            metadata={"priority": "high", "tags": ["urgent"]}
        )
        assert msg.metadata["priority"] == "high"
        assert "urgent" in msg.metadata["tags"]


class TestTelegramSupportTicket:
    """Tests for TelegramSupportTicket dataclass."""

    def test_required_fields(self):
        """Test ticket with required fields."""
        ticket = TelegramSupportTicket(
            id="ticket_001",
            chat_id="chat_123",
            user_id="user_456",
            user_name="John Doe",
            subject="Test Subject"
        )
        assert ticket.id == "ticket_001"
        assert ticket.chat_id == "chat_123"
        assert ticket.user_id == "user_456"
        assert ticket.user_name == "John Doe"
        assert ticket.subject == "Test Subject"
        assert ticket.messages == []
        assert ticket.status == "open"
        assert ticket.priority == "normal"
        assert ticket.resolved_at is None
        assert ticket.assigned_to is None

    def test_ticket_with_messages(self):
        """Test ticket with messages."""
        msg = TelegramMessage(
            id="msg_001",
            chat_id="chat_123",
            author_id="user_456",
            author_name="John Doe",
            content="Initial message"
        )
        ticket = TelegramSupportTicket(
            id="ticket_001",
            chat_id="chat_123",
            user_id="user_456",
            user_name="John Doe",
            subject="Test",
            messages=[msg]
        )
        assert len(ticket.messages) == 1
        assert ticket.messages[0].content == "Initial message"

    def test_ticket_statuses(self):
        """Test different ticket statuses."""
        for status in ["open", "in_progress", "resolved", "closed"]:
            ticket = TelegramSupportTicket(
                id=f"ticket_{status}",
                chat_id="chat_123",
                user_id="user_456",
                user_name="Test User",
                subject="Test",
                status=status
            )
            assert ticket.status == status

    def test_ticket_priorities(self):
        """Test different ticket priorities."""
        for priority in ["low", "normal", "high", "urgent"]:
            ticket = TelegramSupportTicket(
                id=f"ticket_{priority}",
                chat_id="chat_123",
                user_id="user_456",
                user_name="Test User",
                subject="Test",
                priority=priority
            )
            assert ticket.priority == priority


# ============================================================================
# TEST TELEGRAM BOT
# ============================================================================


class TestTelegramBotInit:
    """Tests for TelegramBot initialization."""

    def test_init_default_config(self, mock_telegram_data_dir):
        """Test initialization with default config."""
        bot = TelegramBot()
        assert bot.config is not None
        assert bot.config.enabled is True
        assert bot.tickets == {}
        assert bot.history == []
        assert bot.message_handlers == []

    def test_init_custom_config(self, mock_telegram_data_dir):
        """Test initialization with custom config."""
        config = TelegramConfig(bot_token="custom_token", language="en")
        bot = TelegramBot(config=config)
        assert bot.config.bot_token == "custom_token"
        assert bot.config.language == "en"

    def test_init_file_paths(self, mock_telegram_data_dir):
        """Test that file paths are correctly set."""
        bot = TelegramBot()
        assert bot.config_file == mock_telegram_data_dir / "config.json"
        assert bot.tickets_file == mock_telegram_data_dir / "tickets.json"
        assert bot.history_file == mock_telegram_data_dir / "history.json"


class TestTelegramBotLoad:
    """Tests for TelegramBot _load method."""

    def test_load_existing_config(self, mock_telegram_data_dir):
        """Test loading existing config from file."""
        config_data = {
            "bot_token": "loaded_token",
            "support_chat_id": "support_123",
            "notifications_chat_id": "notif_456",
            "enabled": False,
            "language": "en",
            "bot_name": "LoadedBot",
            "avatar_url": None
        }
        config_file = mock_telegram_data_dir / "config.json"
        config_file.write_text(json.dumps(config_data), encoding="utf-8")

        bot = TelegramBot()
        assert bot.config.bot_token == "loaded_token"
        assert bot.config.support_chat_id == "support_123"
        assert bot.config.enabled is False
        assert bot.config.language == "en"

    def test_load_existing_tickets(self, mock_telegram_data_dir):
        """Test loading existing tickets from file."""
        tickets_data = {
            "ticket_001": {
                "id": "ticket_001",
                "chat_id": "chat_123",
                "user_id": "user_456",
                "user_name": "Test User",
                "subject": "Test Subject",
                "messages": [
                    {
                        "id": "msg_001",
                        "chat_id": "chat_123",
                        "author_id": "user_456",
                        "author_name": "Test User",
                        "content": "Initial message",
                        "message_type": "support_request",
                        "created_at": "2026-01-15T10:00:00",
                        "responded": False,
                        "response_content": None,
                        "metadata": {}
                    }
                ],
                "status": "open",
                "priority": "high",
                "created_at": "2026-01-15T10:00:00",
                "resolved_at": None,
                "assigned_to": None
            }
        }
        tickets_file = mock_telegram_data_dir / "tickets.json"
        tickets_file.write_text(json.dumps(tickets_data), encoding="utf-8")

        bot = TelegramBot()
        assert "ticket_001" in bot.tickets
        assert bot.tickets["ticket_001"].subject == "Test Subject"
        assert len(bot.tickets["ticket_001"].messages) == 1

    def test_load_existing_history(self, mock_telegram_data_dir):
        """Test loading existing history from file."""
        history_data = [
            {
                "id": "msg_001",
                "chat_id": "chat_123",
                "author_id": "bot",
                "author_name": "Agentys",
                "content": "Test notification",
                "message_type": "notification",
                "created_at": "2026-01-15T10:00:00",
                "responded": False,
                "response_content": None,
                "metadata": {}
            }
        ]
        history_file = mock_telegram_data_dir / "history.json"
        history_file.write_text(json.dumps(history_data), encoding="utf-8")

        bot = TelegramBot()
        assert len(bot.history) == 1
        assert bot.history[0].content == "Test notification"

    def test_load_corrupted_config(self, mock_telegram_data_dir):
        """Test loading handles corrupted config file."""
        config_file = mock_telegram_data_dir / "config.json"
        config_file.write_text("not valid json {{{", encoding="utf-8")

        bot = TelegramBot()
        assert bot.config is not None

    def test_load_corrupted_tickets(self, mock_telegram_data_dir):
        """Test loading handles corrupted tickets file."""
        tickets_file = mock_telegram_data_dir / "tickets.json"
        tickets_file.write_text("corrupted data", encoding="utf-8")

        bot = TelegramBot()
        assert bot.tickets == {}

    def test_load_corrupted_history(self, mock_telegram_data_dir):
        """Test loading handles corrupted history file."""
        history_file = mock_telegram_data_dir / "history.json"
        history_file.write_text("[invalid json", encoding="utf-8")

        bot = TelegramBot()
        assert bot.history == []


class TestTelegramBotSave:
    """Tests for TelegramBot _save method."""

    def test_save_config(self, telegram_bot, mock_telegram_data_dir):
        """Test saving config to file."""
        telegram_bot.config.bot_token = "saved_token"
        telegram_bot.config.language = "en"
        telegram_bot._save()

        config_file = mock_telegram_data_dir / "config.json"
        assert config_file.exists()
        data = json.loads(config_file.read_text(encoding="utf-8"))
        assert data["bot_token"] == "saved_token"
        assert data["language"] == "en"

    def test_save_tickets(self, telegram_bot, mock_telegram_data_dir):
        """Test saving tickets to file."""
        ticket = TelegramSupportTicket(
            id="ticket_save_001",
            chat_id="chat_123",
            user_id="user_456",
            user_name="Test User",
            subject="Test Subject"
        )
        telegram_bot.tickets["ticket_save_001"] = ticket
        telegram_bot._save()

        tickets_file = mock_telegram_data_dir / "tickets.json"
        assert tickets_file.exists()
        data = json.loads(tickets_file.read_text(encoding="utf-8"))
        assert "ticket_save_001" in data
        assert data["ticket_save_001"]["subject"] == "Test Subject"

    def test_save_history(self, telegram_bot, mock_telegram_data_dir):
        """Test saving history to file."""
        msg = TelegramMessage(
            id="msg_save_001",
            chat_id="chat_123",
            author_id="bot",
            author_name="Agentys",
            content="Test message"
        )
        telegram_bot.history.append(msg)
        telegram_bot._save()

        history_file = mock_telegram_data_dir / "history.json"
        assert history_file.exists()
        data = json.loads(history_file.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["content"] == "Test message"

    def test_save_limits_history_to_500(self, telegram_bot, mock_telegram_data_dir):
        """Test that save limits history to 500 messages."""
        for i in range(600):
            msg = TelegramMessage(
                id=f"msg_{i}",
                chat_id="chat_123",
                author_id="bot",
                author_name="Agentys",
                content=f"Message {i}"
            )
            telegram_bot.history.append(msg)

        telegram_bot._save()
        assert len(telegram_bot.history) == 500
        assert telegram_bot.history[0].content == "Message 100"
        assert telegram_bot.history[-1].content == "Message 599"


class TestTelegramBotConfigure:
    """Tests for TelegramBot configure method."""

    def test_configure_bot_token(self, telegram_bot):
        """Test configuring bot token."""
        telegram_bot.configure(bot_token="new_token")
        assert telegram_bot.config.bot_token == "new_token"

    def test_configure_multiple_params(self, telegram_bot):
        """Test configuring multiple parameters."""
        telegram_bot.configure(
            bot_token="token_123",
            support_chat_id="support_456",
            enabled=False,
            language="en"
        )
        assert telegram_bot.config.bot_token == "token_123"
        assert telegram_bot.config.support_chat_id == "support_456"
        assert telegram_bot.config.enabled is False
        assert telegram_bot.config.language == "en"

    def test_configure_ignores_unknown_params(self, telegram_bot):
        """Test that configure ignores unknown parameters."""
        telegram_bot.configure(unknown_param="value")
        assert not hasattr(telegram_bot.config, "unknown_param")

    def test_configure_saves_to_file(self, telegram_bot, mock_telegram_data_dir):
        """Test that configure saves changes to file."""
        telegram_bot.configure(bot_token="persisted_token")

        config_file = mock_telegram_data_dir / "config.json"
        data = json.loads(config_file.read_text(encoding="utf-8"))
        assert data["bot_token"] == "persisted_token"


class TestTelegramBotIsConfigured:
    """Tests for TelegramBot is_configured method."""

    def test_is_configured_false_when_no_token(self, telegram_bot):
        """Test is_configured returns False when no token."""
        assert telegram_bot.is_configured() is False

    def test_is_configured_true_when_token_set(self, telegram_bot):
        """Test is_configured returns True when token is set."""
        telegram_bot.config.bot_token = "some_token"
        assert telegram_bot.is_configured() is True

    def test_is_configured_false_when_empty_token(self, telegram_bot):
        """Test is_configured returns False when token is empty string."""
        telegram_bot.config.bot_token = ""
        assert telegram_bot.is_configured() is False


class TestTelegramBotSendNotification:
    """Tests for TelegramBot send_notification method."""

    def test_send_notification_returns_false_when_disabled(self, configured_bot):
        """Test send_notification returns False when bot is disabled."""
        configured_bot.config.enabled = False
        result = configured_bot.send_notification("Test message")
        assert result is False

    def test_send_notification_returns_false_when_not_configured(self, telegram_bot):
        """Test send_notification returns False when not configured."""
        result = telegram_bot.send_notification("Test message")
        assert result is False

    def test_send_notification_returns_false_when_no_chat_id(self, telegram_bot):
        """Test send_notification returns False when no chat_id available."""
        telegram_bot.config.bot_token = "token"
        telegram_bot.config.notifications_chat_id = None
        result = telegram_bot.send_notification("Test message")
        assert result is False

    @patch("app.providers.telegram_adapter.get_telegram_adapter")
    def test_send_notification_success(self, mock_get_adapter, configured_bot):
        """Test successful notification sending."""
        mock_adapter = Mock()
        mock_adapter.is_connected.return_value = True
        mock_adapter.send_message.return_value = {"message_id": 123}
        mock_get_adapter.return_value = mock_adapter

        result = configured_bot.send_notification("Test message")
        assert result is True
        mock_adapter.send_message.assert_called_once()

    @patch("app.providers.telegram_adapter.get_telegram_adapter")
    def test_send_notification_with_title(self, mock_get_adapter, configured_bot):
        """Test notification with title."""
        mock_adapter = Mock()
        mock_adapter.is_connected.return_value = True
        mock_adapter.send_message.return_value = {"message_id": 123}
        mock_get_adapter.return_value = mock_adapter

        configured_bot.send_notification("Test message", title="Test Title")
        call_args = mock_adapter.send_message.call_args
        assert "*Test Title*" in call_args[0][1]

    @patch("app.providers.telegram_adapter.get_telegram_adapter")
    def test_send_notification_custom_chat_id(self, mock_get_adapter, configured_bot):
        """Test notification to custom chat ID."""
        mock_adapter = Mock()
        mock_adapter.is_connected.return_value = True
        mock_adapter.send_message.return_value = {"message_id": 123}
        mock_get_adapter.return_value = mock_adapter

        configured_bot.send_notification("Test message", chat_id="custom_chat")
        call_args = mock_adapter.send_message.call_args
        assert call_args[0][0] == "custom_chat"

    @patch("app.providers.telegram_adapter.get_telegram_adapter")
    def test_send_notification_records_history(self, mock_get_adapter, configured_bot):
        """Test that notification is recorded in history."""
        mock_adapter = Mock()
        mock_adapter.is_connected.return_value = True
        mock_adapter.send_message.return_value = {"message_id": 123}
        mock_get_adapter.return_value = mock_adapter

        initial_history_len = len(configured_bot.history)
        configured_bot.send_notification("Test message")
        assert len(configured_bot.history) == initial_history_len + 1
        assert configured_bot.history[-1].content == "Test message"

    @patch("app.providers.telegram_adapter.get_telegram_adapter")
    def test_send_notification_adapter_not_connected(self, mock_get_adapter, configured_bot):
        """Test send_notification when adapter is not connected."""
        mock_adapter = Mock()
        mock_adapter.is_connected.return_value = False
        mock_get_adapter.return_value = mock_adapter

        result = configured_bot.send_notification("Test message")
        assert result is False

    @patch("app.providers.telegram_adapter.get_telegram_adapter")
    def test_send_notification_adapter_is_none(self, mock_get_adapter, configured_bot):
        """Test send_notification when adapter is None."""
        mock_get_adapter.return_value = None

        result = configured_bot.send_notification("Test message")
        assert result is False

    @patch("app.providers.telegram_adapter.get_telegram_adapter")
    def test_send_notification_handles_exception(self, mock_get_adapter, configured_bot):
        """Test send_notification handles exceptions gracefully."""
        mock_get_adapter.side_effect = Exception("Connection error")

        result = configured_bot.send_notification("Test message")
        assert result is False


class TestTelegramBotSendAlert:
    """Tests for TelegramBot send_alert method."""

    @patch.object(TelegramBot, "send_notification")
    def test_send_alert_warning(self, mock_send_notification, configured_bot):
        """Test send_alert with warning severity."""
        mock_send_notification.return_value = True
        result = configured_bot.send_alert("Warning message", severity="warning")
        assert result is True
        call_args = mock_send_notification.call_args
        assert "Avertissement" in call_args[1]["title"]

    @patch.object(TelegramBot, "send_notification")
    def test_send_alert_error(self, mock_send_notification, configured_bot):
        """Test send_alert with error severity."""
        mock_send_notification.return_value = True
        configured_bot.send_alert("Error message", severity="error")
        call_args = mock_send_notification.call_args
        assert "Erreur" in call_args[1]["title"]

    @patch.object(TelegramBot, "send_notification")
    def test_send_alert_critical(self, mock_send_notification, configured_bot):
        """Test send_alert with critical severity."""
        mock_send_notification.return_value = True
        configured_bot.send_alert("Critical message", severity="critical")
        call_args = mock_send_notification.call_args
        assert "Alerte Critique" in call_args[1]["title"]

    @patch.object(TelegramBot, "send_notification")
    def test_send_alert_unknown_severity(self, mock_send_notification, configured_bot):
        """Test send_alert with unknown severity defaults to warning."""
        mock_send_notification.return_value = True
        configured_bot.send_alert("Message", severity="unknown")
        call_args = mock_send_notification.call_args
        assert "Alerte" in call_args[1]["title"]


class TestTelegramBotSendDraftCreated:
    """Tests for TelegramBot send_draft_created method."""

    @patch.object(TelegramBot, "send_notification")
    def test_send_draft_created_basic(self, mock_send_notification, configured_bot):
        """Test send_draft_created with basic info."""
        mock_send_notification.return_value = True
        result = configured_bot.send_draft_created(
            subject="Test Subject",
            recipient="test@example.com"
        )
        assert result is True
        call_args = mock_send_notification.call_args
        assert "test@example.com" in call_args[1]["message"]
        assert "NORMAL" in call_args[1]["message"]

    @patch.object(TelegramBot, "send_notification")
    def test_send_draft_created_with_confidence(self, mock_send_notification, configured_bot):
        """Test send_draft_created with confidence score."""
        mock_send_notification.return_value = True
        configured_bot.send_draft_created(
            subject="Test Subject",
            recipient="test@example.com",
            confidence=0.85
        )
        call_args = mock_send_notification.call_args
        assert "85%" in call_args[1]["message"]

    @patch.object(TelegramBot, "send_notification")
    def test_send_draft_created_with_category(self, mock_send_notification, configured_bot):
        """Test send_draft_created with custom category."""
        mock_send_notification.return_value = True
        configured_bot.send_draft_created(
            subject="Test Subject",
            recipient="test@example.com",
            category="URGENT"
        )
        call_args = mock_send_notification.call_args
        assert "URGENT" in call_args[1]["message"]


class TestTelegramBotSendFollowupSent:
    """Tests for TelegramBot send_followup_sent method."""

    @patch.object(TelegramBot, "send_notification")
    def test_send_followup_sent(self, mock_send_notification, configured_bot):
        """Test send_followup_sent notification."""
        mock_send_notification.return_value = True
        result = configured_bot.send_followup_sent(
            subject="Follow-up Subject",
            recipient="test@example.com",
            days_since=7
        )
        assert result is True
        call_args = mock_send_notification.call_args
        assert "test@example.com" in call_args[1]["message"]
        assert "7 jours" in call_args[1]["message"]
        assert "Follow-up envoyé" in call_args[1]["title"]


class TestTelegramBotSendStatusUpdate:
    """Tests for TelegramBot send_status_update method."""

    @patch.object(TelegramBot, "send_notification")
    def test_send_status_update_basic(self, mock_send_notification, configured_bot):
        """Test send_status_update with basic status."""
        mock_send_notification.return_value = True
        result = configured_bot.send_status_update("System running normally")
        assert result is True
        call_args = mock_send_notification.call_args
        assert "System running normally" in call_args[1]["message"]

    @patch.object(TelegramBot, "send_notification")
    def test_send_status_update_with_details(self, mock_send_notification, configured_bot):
        """Test send_status_update with details."""
        mock_send_notification.return_value = True
        configured_bot.send_status_update(
            status="Processing complete",
            details="Processed 100 emails"
        )
        call_args = mock_send_notification.call_args
        assert "Processing complete" in call_args[1]["message"]
        assert "Processed 100 emails" in call_args[1]["message"]


class TestTelegramBotCreateSupportTicket:
    """Tests for TelegramBot create_support_ticket method."""

    @patch.object(TelegramBot, "send_notification")
    def test_create_support_ticket(self, mock_send_notification, telegram_bot):
        """Test creating a support ticket."""
        mock_send_notification.return_value = True

        ticket = telegram_bot.create_support_ticket(
            user_id="user_123",
            user_name="John Doe",
            subject="Test Subject",
            initial_message="I need help with...",
            chat_id="chat_456"
        )

        assert ticket is not None
        assert ticket.user_id == "user_123"
        assert ticket.user_name == "John Doe"
        assert ticket.subject == "Test Subject"
        assert ticket.status == "open"
        assert len(ticket.messages) == 1
        assert ticket.messages[0].content == "I need help with..."

    @patch.object(TelegramBot, "send_notification")
    def test_create_support_ticket_stores_in_tickets(self, mock_send_notification, telegram_bot):
        """Test that ticket is stored in tickets dict."""
        mock_send_notification.return_value = True

        ticket = telegram_bot.create_support_ticket(
            user_id="user_123",
            user_name="John Doe",
            subject="Test Subject",
            initial_message="Help needed"
        )

        assert ticket.id in telegram_bot.tickets
        assert telegram_bot.tickets[ticket.id] == ticket

    @patch.object(TelegramBot, "send_notification")
    def test_create_support_ticket_notifies(self, mock_send_notification, telegram_bot):
        """Test that creating ticket sends notification."""
        mock_send_notification.return_value = True

        telegram_bot.create_support_ticket(
            user_id="user_123",
            user_name="John Doe",
            subject="Test Subject",
            initial_message="Help needed"
        )

        mock_send_notification.assert_called_once()
        call_args = mock_send_notification.call_args
        assert "Nouveau ticket de support" in call_args[1]["title"]


class TestTelegramBotAddMessageToTicket:
    """Tests for TelegramBot add_message_to_ticket method."""

    @patch.object(TelegramBot, "send_notification")
    def test_add_message_to_ticket(self, mock_send_notification, telegram_bot):
        """Test adding a message to a ticket."""
        mock_send_notification.return_value = True
        ticket = telegram_bot.create_support_ticket(
            user_id="user_123",
            user_name="John Doe",
            subject="Test",
            initial_message="Initial"
        )

        msg = telegram_bot.add_message_to_ticket(
            ticket_id=ticket.id,
            author_id="user_123",
            author_name="John Doe",
            content="Follow-up message"
        )

        assert msg is not None
        assert msg.content == "Follow-up message"
        assert len(telegram_bot.tickets[ticket.id].messages) == 2

    def test_add_message_to_nonexistent_ticket(self, telegram_bot):
        """Test adding message to nonexistent ticket returns None."""
        result = telegram_bot.add_message_to_ticket(
            ticket_id="nonexistent",
            author_id="user_123",
            author_name="John Doe",
            content="Message"
        )
        assert result is None

    @patch.object(TelegramBot, "send_notification")
    def test_add_response_message(self, mock_send_notification, telegram_bot):
        """Test adding a response message to a ticket."""
        mock_send_notification.return_value = True
        ticket = telegram_bot.create_support_ticket(
            user_id="user_123",
            user_name="John Doe",
            subject="Test",
            initial_message="Initial"
        )

        msg = telegram_bot.add_message_to_ticket(
            ticket_id=ticket.id,
            author_id="support_agent",
            author_name="Support Agent",
            content="Response message",
            is_response=True
        )

        assert msg.message_type == TelegramMessageType.SUPPORT_RESPONSE.value


class TestTelegramBotResolveTicket:
    """Tests for TelegramBot resolve_ticket method."""

    @patch.object(TelegramBot, "send_notification")
    def test_resolve_ticket(self, mock_send_notification, telegram_bot):
        """Test resolving a ticket."""
        mock_send_notification.return_value = True
        ticket = telegram_bot.create_support_ticket(
            user_id="user_123",
            user_name="John Doe",
            subject="Test",
            initial_message="Initial"
        )

        result = telegram_bot.resolve_ticket(ticket.id)
        assert result is True
        assert telegram_bot.tickets[ticket.id].status == "resolved"
        assert telegram_bot.tickets[ticket.id].resolved_at is not None

    def test_resolve_nonexistent_ticket(self, telegram_bot):
        """Test resolving nonexistent ticket returns False."""
        result = telegram_bot.resolve_ticket("nonexistent")
        assert result is False

    @patch.object(TelegramBot, "send_notification")
    def test_resolve_ticket_with_message(self, mock_send_notification, telegram_bot):
        """Test resolving ticket with resolution message."""
        mock_send_notification.return_value = True
        ticket = telegram_bot.create_support_ticket(
            user_id="user_123",
            user_name="John Doe",
            subject="Test",
            initial_message="Initial"
        )

        telegram_bot.resolve_ticket(
            ticket.id,
            resolution_message="Issue has been resolved"
        )

        messages = telegram_bot.tickets[ticket.id].messages
        assert len(messages) == 2
        assert messages[-1].content == "Issue has been resolved"


class TestTelegramBotGetTicket:
    """Tests for TelegramBot get_ticket method."""

    @patch.object(TelegramBot, "send_notification")
    def test_get_ticket(self, mock_send_notification, telegram_bot):
        """Test getting a ticket by ID."""
        mock_send_notification.return_value = True
        ticket = telegram_bot.create_support_ticket(
            user_id="user_123",
            user_name="John Doe",
            subject="Test",
            initial_message="Initial"
        )

        retrieved = telegram_bot.get_ticket(ticket.id)
        assert retrieved is not None
        assert retrieved.id == ticket.id

    def test_get_nonexistent_ticket(self, telegram_bot):
        """Test getting nonexistent ticket returns None."""
        result = telegram_bot.get_ticket("nonexistent")
        assert result is None


class TestTelegramBotGetOpenTickets:
    """Tests for TelegramBot get_open_tickets method."""

    @patch.object(TelegramBot, "send_notification")
    def test_get_open_tickets(self, mock_send_notification, telegram_bot):
        """Test getting open tickets."""
        mock_send_notification.return_value = True

        ticket1 = telegram_bot.create_support_ticket(
            user_id="user_1", user_name="User 1",
            subject="Test 1", initial_message="Msg 1"
        )
        ticket2 = telegram_bot.create_support_ticket(
            user_id="user_2", user_name="User 2",
            subject="Test 2", initial_message="Msg 2"
        )
        telegram_bot.resolve_ticket(ticket2.id)

        open_tickets = telegram_bot.get_open_tickets()
        assert len(open_tickets) == 1
        assert open_tickets[0].id == ticket1.id

    @patch.object(TelegramBot, "send_notification")
    def test_get_open_tickets_includes_in_progress(self, mock_send_notification, telegram_bot):
        """Test that in_progress tickets are included in open tickets."""
        mock_send_notification.return_value = True

        ticket = telegram_bot.create_support_ticket(
            user_id="user_1", user_name="User 1",
            subject="Test", initial_message="Msg"
        )
        telegram_bot.tickets[ticket.id].status = "in_progress"

        open_tickets = telegram_bot.get_open_tickets()
        assert len(open_tickets) == 1


class TestTelegramBotGetUserTickets:
    """Tests for TelegramBot get_user_tickets method."""

    @patch.object(TelegramBot, "send_notification")
    def test_get_user_tickets(self, mock_send_notification, telegram_bot):
        """Test getting tickets for a specific user."""
        mock_send_notification.return_value = True

        telegram_bot.create_support_ticket(
            user_id="user_123", user_name="User 123",
            subject="Test 1", initial_message="Msg 1"
        )
        telegram_bot.create_support_ticket(
            user_id="user_123", user_name="User 123",
            subject="Test 2", initial_message="Msg 2"
        )
        telegram_bot.create_support_ticket(
            user_id="user_456", user_name="User 456",
            subject="Test 3", initial_message="Msg 3"
        )

        user_tickets = telegram_bot.get_user_tickets("user_123")
        assert len(user_tickets) == 2

    def test_get_user_tickets_empty(self, telegram_bot):
        """Test getting tickets for user with no tickets."""
        result = telegram_bot.get_user_tickets("nonexistent_user")
        assert result == []


class TestTelegramBotMessageHandlers:
    """Tests for TelegramBot message handler methods."""

    def test_register_message_handler(self, telegram_bot):
        """Test registering a message handler."""
        async def handler(msg):
            return "response"

        telegram_bot.register_message_handler(handler)
        assert len(telegram_bot.message_handlers) == 1
        assert telegram_bot.message_handlers[0] == handler

    def test_handle_incoming_message(self, telegram_bot):
        """Test handling incoming message."""
        msg = TelegramMessage(
            id="msg_001",
            chat_id="chat_123",
            author_id="user_456",
            author_name="Test User",
            content="Hello"
        )

        async def handler(m):
            return "Hello back!"

        telegram_bot.register_message_handler(handler)
        response = asyncio.run(telegram_bot.handle_incoming_message(msg))

        assert response == "Hello back!"
        assert len(telegram_bot.history) == 1

    def test_handle_incoming_message_no_handlers(self, telegram_bot):
        """Test handling message with no handlers returns None."""
        msg = TelegramMessage(
            id="msg_001",
            chat_id="chat_123",
            author_id="user_456",
            author_name="Test User",
            content="Hello"
        )

        response = asyncio.run(telegram_bot.handle_incoming_message(msg))
        assert response is None

    def test_handle_incoming_message_handler_exception(self, telegram_bot):
        """Test that handler exceptions are caught."""
        msg = TelegramMessage(
            id="msg_001",
            chat_id="chat_123",
            author_id="user_456",
            author_name="Test User",
            content="Hello"
        )

        async def failing_handler(m):
            raise Exception("Handler error")

        async def working_handler(m):
            return "Working response"

        telegram_bot.register_message_handler(failing_handler)
        telegram_bot.register_message_handler(working_handler)

        response = asyncio.run(telegram_bot.handle_incoming_message(msg))
        assert response == "Working response"


class TestTelegramBotGetStats:
    """Tests for TelegramBot get_stats method."""

    @patch.object(TelegramBot, "send_notification")
    def test_get_stats(self, mock_send_notification, configured_bot):
        """Test getting bot statistics."""
        mock_send_notification.return_value = True

        configured_bot.create_support_ticket(
            user_id="user_1", user_name="User 1",
            subject="Test 1", initial_message="Msg 1"
        )
        ticket2 = configured_bot.create_support_ticket(
            user_id="user_2", user_name="User 2",
            subject="Test 2", initial_message="Msg 2"
        )
        configured_bot.resolve_ticket(ticket2.id)

        stats = configured_bot.get_stats()
        assert stats["total_tickets"] == 2
        assert stats["open_tickets"] == 1
        assert stats["resolved_tickets"] == 1
        assert stats["configured"] is True
        assert stats["enabled"] is True

    def test_get_stats_empty(self, telegram_bot):
        """Test getting stats with no data."""
        stats = telegram_bot.get_stats()
        assert stats["total_tickets"] == 0
        assert stats["open_tickets"] == 0
        assert stats["resolved_tickets"] == 0
        assert stats["total_messages"] == 0
        assert stats["configured"] is False


# ============================================================================
# TEST SINGLETON
# ============================================================================


class TestGetTelegramBot:
    """Tests for get_telegram_bot singleton function."""

    @pytest.mark.skip(reason="Obsolète post audit F-11 (2026-04-29) — singleton _telegram_bot renommé _telegram_bots (dict per-tenant).")
    def test_get_telegram_bot_returns_instance(self, mock_telegram_data_dir, monkeypatch):
        """Test that get_telegram_bot returns a TelegramBot instance."""
        monkeypatch.setattr("app.telegram_integration._telegram_bot", None)
        bot = get_telegram_bot()
        assert isinstance(bot, TelegramBot)

    @pytest.mark.skip(reason="Obsolète post audit F-11 (2026-04-29) — singleton _telegram_bot renommé _telegram_bots (dict per-tenant).")
    def test_get_telegram_bot_returns_same_instance(self, mock_telegram_data_dir, monkeypatch):
        """Test that get_telegram_bot returns the same instance."""
        monkeypatch.setattr("app.telegram_integration._telegram_bot", None)
        bot1 = get_telegram_bot()
        bot2 = get_telegram_bot()
        assert bot1 is bot2
