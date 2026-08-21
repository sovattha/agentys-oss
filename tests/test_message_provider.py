# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests for the MessageProvider interface and StandardMessage dataclass.

These tests ensure complete coverage of the abstract interface
and the StandardMessage data class methods.
"""

import pytest
from datetime import datetime
from typing import Callable, List, Optional
from unittest.mock import MagicMock

from app.interfaces.message_provider import (
    ChannelType,
    StandardMessage,
    MessageProvider,
)


# =============================================================================
# Test Fixtures
# =============================================================================


class ConcreteMessageProvider(MessageProvider):
    """Concrete implementation of MessageProvider for testing."""

    def __init__(self):
        self._connected = False
        self._handlers: List[Callable[[StandardMessage], None]] = []
        self._listening = False

    @property
    def provider_name(self) -> str:
        return "test_provider"

    @property
    def channel_type(self) -> ChannelType:
        return ChannelType.DISCORD

    def connect(self) -> bool:
        self._connected = True
        return True

    def disconnect(self) -> bool:
        self._connected = False
        return True

    def is_connected(self) -> bool:
        return self._connected

    def get_recent_messages(
        self,
        channel_id: str,
        limit: int = 10
    ) -> List[StandardMessage]:
        return []

    def get_unread_mentions(self, limit: int = 10) -> List[StandardMessage]:
        return []

    def send_message(
        self,
        channel_id: str,
        content: str,
        reply_to_id: Optional[str] = None
    ) -> Optional[str]:
        return "msg_123"

    def edit_message(
        self,
        channel_id: str,
        message_id: str,
        content: str
    ) -> bool:
        return True

    def delete_message(
        self,
        channel_id: str,
        message_id: str
    ) -> bool:
        return True

    def get_channels(self) -> List[dict]:
        return [{"id": "ch_1", "name": "general", "type": "text"}]


@pytest.fixture
def message():
    """Create a standard message for testing."""
    return StandardMessage(
        id="msg_001",
        channel_id="ch_123",
        channel_name="general",
        author_id="user_456",
        author_name="testuser",
        author_display_name="Test User",
        content="Hello, this is a test message with some content that is longer than one hundred characters to trigger the preview truncation mechanism.",
        created_at=datetime(2025, 1, 18, 10, 30, 0),
        is_bot=False,
        is_mention=True,
        is_dm=False,
        reply_to_id=None,
        attachments=["image.png"],
        provider_source=ChannelType.DISCORD,
        raw_metadata={"guild_id": "guild_789"}
    )


@pytest.fixture
def message_no_display_name():
    """Create a message without display name."""
    return StandardMessage(
        id="msg_002",
        channel_id="ch_123",
        author_id="user_789",
        author_name="anotheruser",
        content="Short message",
        provider_source=ChannelType.TELEGRAM
    )


@pytest.fixture
def message_empty_content():
    """Create a message with empty content."""
    return StandardMessage(
        id="msg_003",
        channel_id="ch_456",
        author_id="user_101",
        author_name="emptyuser",
        content="",
        provider_source=ChannelType.SLACK
    )


@pytest.fixture
def provider():
    """Create a concrete message provider for testing."""
    return ConcreteMessageProvider()


# =============================================================================
# ChannelType Tests
# =============================================================================


class TestChannelType:
    """Tests for the ChannelType enum."""

    def test_discord_value(self):
        """ChannelType.DISCORD has correct value."""
        assert ChannelType.DISCORD.value == "discord"

    def test_telegram_value(self):
        """ChannelType.TELEGRAM has correct value."""
        assert ChannelType.TELEGRAM.value == "telegram"

    def test_slack_value(self):
        """ChannelType.SLACK has correct value."""
        assert ChannelType.SLACK.value == "slack"

    def test_channel_type_is_string_enum(self):
        """ChannelType inherits from str."""
        assert isinstance(ChannelType.DISCORD, str)
        assert ChannelType.DISCORD == "discord"

    def test_all_values(self):
        """All channel types are present."""
        values = [ct.value for ct in ChannelType]
        assert "discord" in values
        assert "telegram" in values
        assert "slack" in values
        assert len(values) == 3


# =============================================================================
# StandardMessage Tests
# =============================================================================


class TestStandardMessage:
    """Tests for StandardMessage dataclass."""

    def test_str_representation(self, message):
        """__str__ returns formatted string with provider, author, and content preview."""
        result = str(message)
        assert "[discord]" in result
        assert "Test User" in result
        # Content is truncated to 50 chars + "..."
        assert "Hello, this is a test message with some content th" in result
        assert result.endswith("...")

    def test_str_with_no_display_name(self, message_no_display_name):
        """__str__ uses author_name when display_name is None."""
        result = str(message_no_display_name)
        assert "[telegram]" in result
        assert "anotheruser" in result

    def test_author_display_property_with_display_name(self, message):
        """author_display returns display_name when available."""
        assert message.author_display == "Test User"

    def test_author_display_property_without_display_name(self, message_no_display_name):
        """author_display falls back to author_name."""
        assert message_no_display_name.author_display == "anotheruser"

    def test_preview_property_with_long_content(self, message):
        """preview truncates content longer than 100 chars."""
        preview = message.preview
        assert len(preview) <= 103  # 100 + "..."
        assert preview.endswith("...")

    def test_preview_property_with_short_content(self, message_no_display_name):
        """preview returns full content if under 100 chars."""
        preview = message_no_display_name.preview
        assert preview == "Short message"
        assert not preview.endswith("...")

    def test_preview_property_with_empty_content(self, message_empty_content):
        """preview returns empty string for empty content."""
        assert message_empty_content.preview == ""

    def test_preview_with_exactly_100_chars(self):
        """preview with exactly 100 chars does not add ellipsis."""
        msg = StandardMessage(
            id="x",
            channel_id="y",
            content="x" * 100,
        )
        assert msg.preview == "x" * 100

    def test_preview_with_101_chars(self):
        """preview with 101 chars adds ellipsis."""
        msg = StandardMessage(
            id="x",
            channel_id="y",
            content="x" * 101,
        )
        assert msg.preview == "x" * 100 + "..."

    def test_default_values(self):
        """StandardMessage has correct default values."""
        msg = StandardMessage(id="test", channel_id="ch")
        assert msg.channel_name is None
        assert msg.author_id == ""
        assert msg.author_name == ""
        assert msg.author_display_name is None
        assert msg.content == ""
        assert msg.created_at is None
        assert msg.is_bot is False
        assert msg.is_mention is False
        assert msg.is_dm is False
        assert msg.reply_to_id is None
        assert msg.attachments == []
        assert msg.provider_source == ChannelType.DISCORD
        assert msg.raw_metadata == {}

    def test_full_initialization(self, message):
        """StandardMessage initializes all fields correctly."""
        assert message.id == "msg_001"
        assert message.channel_id == "ch_123"
        assert message.channel_name == "general"
        assert message.author_id == "user_456"
        assert message.author_name == "testuser"
        assert message.author_display_name == "Test User"
        assert "Hello" in message.content
        assert message.created_at == datetime(2025, 1, 18, 10, 30, 0)
        assert message.is_bot is False
        assert message.is_mention is True
        assert message.is_dm is False
        assert message.reply_to_id is None
        assert message.attachments == ["image.png"]
        assert message.provider_source == ChannelType.DISCORD
        assert message.raw_metadata == {"guild_id": "guild_789"}


# =============================================================================
# MessageProvider Interface Tests
# =============================================================================


class TestMessageProviderInterface:
    """Tests for MessageProvider abstract interface."""

    def test_provider_name_property(self, provider):
        """provider_name returns implementation name."""
        assert provider.provider_name == "test_provider"

    def test_channel_type_property(self, provider):
        """channel_type returns correct ChannelType."""
        assert provider.channel_type == ChannelType.DISCORD

    def test_connect(self, provider):
        """connect() establishes connection."""
        assert provider.connect() is True
        assert provider.is_connected() is True

    def test_disconnect(self, provider):
        """disconnect() closes connection."""
        provider.connect()
        assert provider.disconnect() is True
        assert provider.is_connected() is False

    def test_is_connected_initial(self, provider):
        """is_connected() returns False initially."""
        assert provider.is_connected() is False

    def test_get_recent_messages(self, provider):
        """get_recent_messages() returns list."""
        messages = provider.get_recent_messages("ch_1", limit=5)
        assert isinstance(messages, list)

    def test_get_unread_mentions(self, provider):
        """get_unread_mentions() returns list."""
        mentions = provider.get_unread_mentions(limit=5)
        assert isinstance(mentions, list)

    def test_send_message(self, provider):
        """send_message() returns message ID."""
        msg_id = provider.send_message("ch_1", "Hello!")
        assert msg_id == "msg_123"

    def test_send_message_with_reply(self, provider):
        """send_message() accepts reply_to_id."""
        msg_id = provider.send_message("ch_1", "Reply", reply_to_id="orig_123")
        assert msg_id == "msg_123"

    def test_edit_message(self, provider):
        """edit_message() returns True on success."""
        result = provider.edit_message("ch_1", "msg_1", "Updated content")
        assert result is True

    def test_delete_message(self, provider):
        """delete_message() returns True on success."""
        result = provider.delete_message("ch_1", "msg_1")
        assert result is True

    def test_get_channels(self, provider):
        """get_channels() returns list of channel dicts."""
        channels = provider.get_channels()
        assert isinstance(channels, list)
        assert len(channels) == 1
        assert channels[0]["id"] == "ch_1"
        assert channels[0]["name"] == "general"


class TestMessageProviderDefaultMethods:
    """Tests for MessageProvider default method implementations."""

    def test_register_message_handler_default(self, provider):
        """register_message_handler has default no-op implementation."""
        handler = MagicMock()
        # Should not raise
        provider.register_message_handler(handler)

    def test_start_listening_default(self, provider):
        """start_listening returns False by default."""
        result = provider.start_listening()
        assert result is False

    def test_stop_listening_default(self, provider):
        """stop_listening returns False by default."""
        result = provider.stop_listening()
        assert result is False


class TestMessageProviderWithCustomListening:
    """Tests for custom listening implementation."""

    def test_custom_listening_implementation(self):
        """Provider can override listening methods."""

        class ListeningProvider(ConcreteMessageProvider):
            def __init__(self):
                super().__init__()
                self._handlers: List[Callable] = []
                self._listening = False

            def register_message_handler(self, handler):
                self._handlers.append(handler)

            def start_listening(self) -> bool:
                self._listening = True
                return True

            def stop_listening(self) -> bool:
                self._listening = False
                return True

        provider = ListeningProvider()

        # Register handler
        handler = MagicMock()
        provider.register_message_handler(handler)
        assert len(provider._handlers) == 1

        # Start listening
        assert provider.start_listening() is True
        assert provider._listening is True

        # Stop listening
        assert provider.stop_listening() is True
        assert provider._listening is False


# =============================================================================
# Abstract Method Coverage Tests
# =============================================================================


class TestAbstractMethodDefinitions:
    """
    Tests that verify abstract methods are properly defined.

    These tests create a minimal provider to exercise the abstract interface
    and ensure all methods are callable with proper signatures.
    """

    def test_all_abstract_methods_implemented(self, provider):
        """All abstract methods must be implemented in concrete class."""
        # These should not raise NotImplementedError
        provider.provider_name
        provider.channel_type
        provider.connect()
        provider.disconnect()
        provider.is_connected()
        provider.get_recent_messages("ch", 10)
        provider.get_unread_mentions(10)
        provider.send_message("ch", "msg")
        provider.edit_message("ch", "msg_id", "content")
        provider.delete_message("ch", "msg_id")
        provider.get_channels()

    def test_incomplete_implementation_fails(self):
        """Cannot instantiate MessageProvider without all abstract methods."""

        class IncompleteProvider(MessageProvider):
            @property
            def provider_name(self) -> str:
                return "incomplete"

        with pytest.raises(TypeError):
            IncompleteProvider()


# =============================================================================
# Edge Cases and Error Handling
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_message_with_unicode_content(self):
        """StandardMessage handles unicode content."""
        msg = StandardMessage(
            id="unicode",
            channel_id="ch",
            content="Hello! Bonjour! Hola! Привет! 你好! 🎉🚀",
        )
        assert "🎉" in str(msg)
        assert "🚀" in msg.preview

    def test_message_with_newlines(self):
        """StandardMessage handles newlines in content."""
        msg = StandardMessage(
            id="newlines",
            channel_id="ch",
            content="Line 1\nLine 2\nLine 3",
        )
        assert "\n" in msg.content
        assert "Line 1" in str(msg)

    def test_message_with_special_characters(self):
        """StandardMessage handles special characters."""
        msg = StandardMessage(
            id="special",
            channel_id="ch",
            content="Test <script>alert('xss')</script> & more",
        )
        assert "<script>" in msg.content

    def test_message_author_display_with_empty_strings(self):
        """author_display handles empty author_name."""
        msg = StandardMessage(
            id="x",
            channel_id="y",
            author_name="",
            author_display_name=None,
        )
        assert msg.author_display == ""

    def test_message_attachments_list(self):
        """Attachments default to empty list, not shared instance."""
        msg1 = StandardMessage(id="1", channel_id="ch")
        msg2 = StandardMessage(id="2", channel_id="ch")

        msg1.attachments.append("file1.txt")

        assert msg2.attachments == []
        assert msg1.attachments == ["file1.txt"]

    def test_raw_metadata_dict(self):
        """raw_metadata defaults to empty dict, not shared instance."""
        msg1 = StandardMessage(id="1", channel_id="ch")
        msg2 = StandardMessage(id="2", channel_id="ch")

        msg1.raw_metadata["key"] = "value"

        assert msg2.raw_metadata == {}
        assert msg1.raw_metadata == {"key": "value"}


# =============================================================================
# Integration-style Tests
# =============================================================================


class TestMessageProviderIntegration:
    """Integration-style tests for message flow."""

    def test_full_message_lifecycle(self, provider):
        """Test complete message lifecycle: connect, send, edit, delete."""
        # Connect
        assert provider.connect() is True
        assert provider.is_connected() is True

        # Send message
        msg_id = provider.send_message("ch_1", "Original message")
        assert msg_id is not None

        # Edit message
        assert provider.edit_message("ch_1", msg_id, "Updated message") is True

        # Delete message
        assert provider.delete_message("ch_1", msg_id) is True

        # Disconnect
        assert provider.disconnect() is True
        assert provider.is_connected() is False

    def test_message_conversion_round_trip(self, message):
        """StandardMessage preserves all data through serialization."""
        # Create dict representation
        data = {
            "id": message.id,
            "channel_id": message.channel_id,
            "channel_name": message.channel_name,
            "author_id": message.author_id,
            "author_name": message.author_name,
            "author_display_name": message.author_display_name,
            "content": message.content,
            "created_at": message.created_at,
            "is_bot": message.is_bot,
            "is_mention": message.is_mention,
            "is_dm": message.is_dm,
            "reply_to_id": message.reply_to_id,
            "attachments": message.attachments,
            "provider_source": message.provider_source,
            "raw_metadata": message.raw_metadata,
        }

        # Recreate message
        new_msg = StandardMessage(**data)

        # Verify all fields match
        assert new_msg.id == message.id
        assert new_msg.channel_id == message.channel_id
        assert new_msg.content == message.content
        assert new_msg.author_display == message.author_display
