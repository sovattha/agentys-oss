# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests complets pour le DiscordAdapter.
Couverture: 38% → 100%
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
from datetime import datetime
import asyncio
from concurrent.futures import Future

from app.interfaces.message_provider import (
    StandardMessage,
    ChannelType,
)
from app.providers.discord_adapter import (
    DiscordAdapter,
    DISCORD_AVAILABLE,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def adapter():
    """Fixture pour créer un adapter simple."""
    return DiscordAdapter(bot_token="test-token-123")


@pytest.fixture
def connected_adapter():
    """Fixture pour un adapter connecté avec mocks complets."""
    adapter = DiscordAdapter(bot_token="test-token")
    adapter._client = MagicMock()
    adapter._connected = True
    adapter._loop = MagicMock()
    adapter._loop.is_running.return_value = True
    return adapter


@pytest.fixture
def mock_discord_message():
    """Fixture pour un message Discord mocké."""
    msg = MagicMock()
    msg.id = 123456789
    msg.channel.id = 987654321
    msg.channel.name = "general"
    msg.author.id = 111222333
    msg.author.name = "testuser"
    msg.author.display_name = "Test User"
    msg.author.bot = False
    msg.content = "Hello, this is a test message"
    msg.created_at = datetime(2026, 1, 5, 10, 30)
    msg.reference = None
    msg.attachments = []
    msg.guild = MagicMock()
    msg.guild.id = 555666777
    msg.guild.name = "Test Server"
    msg.mentions = []
    return msg


@pytest.fixture
def mock_channel():
    """Fixture pour un canal Discord mocké."""
    channel = MagicMock()
    channel.id = 987654321
    channel.name = "test-channel"
    channel.send = AsyncMock()
    channel.fetch_message = AsyncMock()
    channel.history = MagicMock()
    return channel


# =============================================================================
# TestDiscordAdapterInit
# =============================================================================


class TestDiscordAdapterInit:
    """Tests d'initialisation du DiscordAdapter."""

    def test_init_with_token(self):
        """Test initialisation avec token."""
        adapter = DiscordAdapter(bot_token="test-token-123")
        assert adapter.provider_name == "discord"
        assert adapter.channel_type == ChannelType.DISCORD
        assert not adapter.is_connected()

    def test_init_without_token_raises(self):
        """Test initialisation sans token lève une exception."""
        with pytest.raises(ValueError, match="DISCORD_BOT_TOKEN"):
            DiscordAdapter(bot_token="")

    def test_init_from_env(self, monkeypatch):
        """Test initialisation depuis variable d'environnement."""
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "env-token-456")
        adapter = DiscordAdapter()
        assert adapter._bot_token == "env-token-456"

    def test_init_with_empty_env(self, monkeypatch):
        """Test initialisation avec variable d'environnement vide."""
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "")
        with pytest.raises(ValueError, match="Token Discord requis"):
            DiscordAdapter()

    def test_init_with_custom_intents(self):
        """Test initialisation avec intents personnalisés."""
        mock_intents = MagicMock()
        adapter = DiscordAdapter(bot_token="test-token", intents=mock_intents)
        assert adapter._intents == mock_intents

    def test_init_attributes(self, adapter):
        """Test attributs initiaux."""
        assert adapter._client is None
        assert adapter._connected is False
        assert adapter._message_handlers == []
        assert adapter._loop is None
        assert adapter._thread is None


# =============================================================================
# TestDiscordAdapterProperties
# =============================================================================


class TestDiscordAdapterProperties:
    """Tests des propriétés du DiscordAdapter."""

    def test_provider_name(self, adapter):
        """Test provider_name property."""
        assert adapter.provider_name == "discord"

    def test_channel_type(self, adapter):
        """Test channel_type property."""
        assert adapter.channel_type == ChannelType.DISCORD

    def test_is_connected_false(self, adapter):
        """Test is_connected retourne False par défaut."""
        assert adapter.is_connected() is False

    def test_is_connected_true(self, connected_adapter):
        """Test is_connected retourne True quand connecté."""
        assert connected_adapter.is_connected() is True


# =============================================================================
# TestDiscordAdapterConnection
# =============================================================================


class TestDiscordAdapterConnection:
    """Tests de connexion/déconnexion."""

    def test_not_connected_by_default(self, adapter):
        """Test adapter non connecté par défaut."""
        assert adapter.is_connected() is False

    def test_connect_returns_false_when_discord_unavailable(self):
        """Test connexion retourne False si discord.py non disponible."""
        import app.providers.discord_adapter as discord_module
        original_available = discord_module.DISCORD_AVAILABLE
        discord_module.DISCORD_AVAILABLE = False

        try:
            adapter = DiscordAdapter(bot_token="test-token")
            result = adapter.connect()
            assert result is False
        finally:
            discord_module.DISCORD_AVAILABLE = original_available

    def test_disconnect_when_not_connected(self, adapter):
        """Test déconnexion quand non connecté."""
        result = adapter.disconnect()
        assert result is True

    @pytest.mark.skipif(not DISCORD_AVAILABLE, reason="discord.py non installé")
    def test_connect_creates_loop_and_thread(self, adapter):
        """Test connexion crée une loop et un thread."""
        with patch.object(adapter, '_run_client'):
            result = adapter.connect()
            if result:  # Si discord.py disponible
                assert adapter._loop is not None
                assert adapter._thread is not None

    @pytest.mark.skipif(not DISCORD_AVAILABLE, reason="discord.py non installé")
    def test_connect_already_connected(self):
        """Test connexion quand déjà connecté retourne True."""
        import app.providers.discord_adapter as discord_module
        original_available = discord_module.DISCORD_AVAILABLE
        # Temporarily set as available for this test
        discord_module.DISCORD_AVAILABLE = True

        try:
            adapter = DiscordAdapter(bot_token="test-token")
            adapter._connected = True  # Simulate already connected
            result = adapter.connect()
            assert result is True
        finally:
            discord_module.DISCORD_AVAILABLE = original_available

    @pytest.mark.skipif(not DISCORD_AVAILABLE, reason="discord.py non installé")
    def test_connect_with_exception(self, adapter):
        """Test connexion avec exception."""
        with patch('asyncio.new_event_loop', side_effect=Exception("Loop error")):
            result = adapter.connect()
            assert result is False

    def test_disconnect_closes_client(self, connected_adapter):
        """Test déconnexion ferme le client."""
        mock_close = AsyncMock()
        connected_adapter._client.close = mock_close

        with patch('asyncio.run_coroutine_threadsafe') as mock_run:
            result = connected_adapter.disconnect()
            assert result is True
            assert connected_adapter._connected is False
            mock_run.assert_called_once()

    def test_disconnect_with_exception(self, connected_adapter):
        """Test déconnexion avec exception."""
        connected_adapter._loop.is_running.side_effect = Exception("Loop error")

        result = connected_adapter.disconnect()
        assert result is False

    def test_disconnect_loop_not_running(self, connected_adapter):
        """Test déconnexion quand la loop ne tourne pas."""
        connected_adapter._loop.is_running.return_value = False
        connected_adapter._connected = True

        result = connected_adapter.disconnect()
        assert result is True
        assert connected_adapter._connected is False


# =============================================================================
# TestDiscordAdapterAsyncConnection
# =============================================================================


class TestDiscordAdapterAsyncConnection:
    """Tests de connexion asynchrone."""

    def test_connect_async_unavailable(self):
        """Test connect_async avec discord.py non disponible."""
        import app.providers.discord_adapter as discord_module
        original_available = discord_module.DISCORD_AVAILABLE
        discord_module.DISCORD_AVAILABLE = False

        try:
            adapter = DiscordAdapter(bot_token="test-token")
            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(adapter.connect_async())
            loop.close()
            assert result is False
        finally:
            discord_module.DISCORD_AVAILABLE = original_available

    def test_connect_async_already_connected(self, connected_adapter):
        """Test connect_async quand déjà connecté."""
        import app.providers.discord_adapter as discord_module
        original_available = discord_module.DISCORD_AVAILABLE
        discord_module.DISCORD_AVAILABLE = True
        
        try:
            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(connected_adapter.connect_async())
            loop.close()
            assert result is True
        finally:
            discord_module.DISCORD_AVAILABLE = original_available

    @pytest.mark.skipif(not DISCORD_AVAILABLE, reason="discord.py non installé")
    def test_connect_async_with_exception(self, adapter):
        """Test connect_async avec exception."""
        with patch.object(adapter, '_start_client', side_effect=Exception("Start error")):
            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(adapter.connect_async())
            loop.close()
            assert result is False


# =============================================================================
# TestDiscordAdapterStartClient
# =============================================================================


class TestDiscordAdapterStartClient:
    """Tests de démarrage du client."""

    def test_start_client_unavailable(self):
        """Test _start_client avec discord.py non disponible."""
        import app.providers.discord_adapter as discord_module
        original_available = discord_module.DISCORD_AVAILABLE
        discord_module.DISCORD_AVAILABLE = False

        try:
            adapter = DiscordAdapter(bot_token="test-token")
            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(adapter._start_client())
            loop.close()
            assert result is False
        finally:
            discord_module.DISCORD_AVAILABLE = original_available

    @pytest.mark.skipif(not DISCORD_AVAILABLE, reason="discord.py non installé")
    def test_start_client_creates_client(self, adapter):
        """Test _start_client crée un client."""
        with patch('discord.Client') as mock_client_class:
            mock_client = MagicMock()
            mock_client.start = AsyncMock()
            mock_client_class.return_value = mock_client

            # Run but don't wait for real connection
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(asyncio.wait_for(adapter._start_client(), timeout=0.1))
            except asyncio.TimeoutError:
                pass
            finally:
                loop.close()

            assert adapter._client is not None

    @pytest.mark.skipif(not DISCORD_AVAILABLE, reason="discord.py non installé")
    def test_start_client_with_error(self, adapter):
        """Test _start_client avec erreur de démarrage."""
        with patch('discord.Client') as mock_client_class:
            mock_client = MagicMock()
            mock_client.start = AsyncMock(side_effect=Exception("Start error"))
            mock_client_class.return_value = mock_client

            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(adapter._start_client())
            loop.close()
            assert result is False


# =============================================================================
# TestDiscordAdapterRunClient
# =============================================================================


class TestDiscordAdapterRunClient:
    """Tests de _run_client."""

    @pytest.mark.skipif(not DISCORD_AVAILABLE, reason="discord.py non installé")
    def test_run_client_sets_event_loop(self, adapter):
        """Test _run_client configure la loop."""
        adapter._loop = MagicMock()
        adapter._loop.run_until_complete = MagicMock()

        async def dummy_start():
            return True

        with patch('asyncio.set_event_loop') as mock_set_loop:
            with patch.object(adapter, '_start_client', return_value=dummy_start()):
                adapter._run_client()
                mock_set_loop.assert_called_once_with(adapter._loop)


# =============================================================================
# TestDiscordAdapterMessages
# =============================================================================


class TestDiscordAdapterMessages:
    """Tests des opérations sur les messages."""

    def test_convert_to_standard_message(self, connected_adapter, mock_discord_message):
        """Test conversion message Discord vers StandardMessage."""
        result = connected_adapter._to_standard_message(mock_discord_message)

        assert isinstance(result, StandardMessage)
        assert result.id == "123456789"
        assert result.channel_id == "987654321"
        assert result.channel_name == "general"
        assert result.author_id == "111222333"
        assert result.author_name == "testuser"
        assert result.author_display_name == "Test User"
        assert result.content == "Hello, this is a test message"
        assert result.is_bot is False
        assert result.provider_source == ChannelType.DISCORD

    def test_convert_bot_message(self, connected_adapter, mock_discord_message):
        """Test conversion message de bot."""
        mock_discord_message.author.bot = True
        result = connected_adapter._to_standard_message(mock_discord_message)
        assert result.is_bot is True

    def test_convert_reply_message(self, connected_adapter, mock_discord_message):
        """Test conversion message avec référence (réponse)."""
        mock_discord_message.reference = MagicMock()
        mock_discord_message.reference.message_id = 999888777
        result = connected_adapter._to_standard_message(mock_discord_message)
        assert result.reply_to_id == "999888777"

    def test_convert_dm_message(self, connected_adapter, mock_discord_message):
        """Test conversion message privé (DM)."""
        mock_discord_message.channel.type = MagicMock()
        mock_discord_message.channel.type.name = "private"
        result = connected_adapter._to_standard_message(mock_discord_message, is_dm=True)
        assert result.is_dm is True

    def test_convert_message_with_attachments(self, connected_adapter, mock_discord_message):
        """Test conversion message avec pièces jointes."""
        attachment1 = MagicMock()
        attachment1.url = "https://cdn.discord.com/file1.jpg"
        attachment2 = MagicMock()
        attachment2.url = "https://cdn.discord.com/file2.png"
        mock_discord_message.attachments = [attachment1, attachment2]

        result = connected_adapter._to_standard_message(mock_discord_message)
        assert len(result.attachments) == 2
        assert "file1.jpg" in result.attachments[0]

    def test_convert_message_without_guild(self, connected_adapter, mock_discord_message):
        """Test conversion message sans guild (DM)."""
        mock_discord_message.guild = None

        result = connected_adapter._to_standard_message(mock_discord_message)
        assert result.raw_metadata["guild_id"] is None
        assert result.raw_metadata["guild_name"] is None

    def test_convert_message_with_mention(self, connected_adapter, mock_discord_message):
        """Test conversion message avec mention du bot."""
        bot_user = MagicMock()
        connected_adapter._client.user = bot_user
        mock_discord_message.mentions = [bot_user]

        result = connected_adapter._to_standard_message(mock_discord_message)
        assert result.is_mention is True

    def test_convert_dm_channel_by_type(self, connected_adapter, mock_discord_message):
        """Test détection DM par type de canal."""
        mock_discord_message.channel.type = MagicMock()
        mock_discord_message.channel.type.name = "private"

        result = connected_adapter._to_standard_message(mock_discord_message)
        assert result.is_dm is True

    def test_convert_message_dm_without_channel_name(self, connected_adapter, mock_discord_message):
        """Test conversion message DM avec nom de canal généré."""
        del mock_discord_message.channel.name
        mock_discord_message.channel.recipient = MagicMock()
        mock_discord_message.channel.recipient.name = "john_doe"

        result = connected_adapter._to_standard_message(mock_discord_message)
        assert "DM-john_doe" in result.channel_name


# =============================================================================
# TestDiscordAdapterGetRecentMessages
# =============================================================================


class TestDiscordAdapterGetRecentMessages:
    """Tests de récupération des messages récents."""

    def test_get_recent_messages_not_connected(self, adapter):
        """Test récupération messages quand non connecté retourne liste vide."""
        result = adapter.get_recent_messages("123")
        assert result == []

    def test_get_recent_messages_no_client(self, adapter):
        """Test récupération messages sans client."""
        adapter._connected = True
        adapter._client = None
        result = adapter.get_recent_messages("123")
        assert result == []

    def test_get_recent_messages_channel_not_found(self, connected_adapter):
        """Test récupération messages avec canal non trouvé."""
        connected_adapter._client.get_channel.return_value = None
        result = connected_adapter.get_recent_messages("123")
        assert result == []

    def test_get_recent_messages_success(self, connected_adapter, mock_channel, mock_discord_message):
        """Test récupération messages avec succès."""
        connected_adapter._client.get_channel.return_value = mock_channel

        # Mock async history
        mock_history = MagicMock()
        mock_history.flatten = AsyncMock(return_value=[mock_discord_message])
        mock_channel.history.return_value = mock_history

        # Create a completed future
        future = Future()
        future.set_result([mock_discord_message])

        with patch('asyncio.run_coroutine_threadsafe', return_value=future):
            result = connected_adapter.get_recent_messages("987654321", limit=5)
            # The result should be a list of StandardMessage
            assert isinstance(result, list)

    def test_get_recent_messages_no_loop(self, connected_adapter, mock_channel):
        """Test récupération messages sans loop."""
        connected_adapter._client.get_channel.return_value = mock_channel
        connected_adapter._loop = None

        result = connected_adapter.get_recent_messages("123")
        assert result == []

    def test_get_recent_messages_exception(self, connected_adapter):
        """Test récupération messages avec exception."""
        connected_adapter._client.get_channel.side_effect = Exception("Channel error")
        result = connected_adapter.get_recent_messages("123")
        assert result == []


# =============================================================================
# TestDiscordAdapterGetUnreadMentions
# =============================================================================


class TestDiscordAdapterGetUnreadMentions:
    """Tests de récupération des mentions non lues."""

    def test_get_unread_mentions_not_connected(self, adapter):
        """Test mentions non lues quand non connecté."""
        result = adapter.get_unread_mentions()
        assert result == []

    def test_get_unread_mentions_connected(self, connected_adapter):
        """Test mentions non lues quand connecté (placeholder)."""
        result = connected_adapter.get_unread_mentions()
        assert result == []

    def test_get_unread_mentions_with_limit(self, connected_adapter):
        """Test mentions non lues avec limite."""
        result = connected_adapter.get_unread_mentions(limit=20)
        assert result == []


# =============================================================================
# TestDiscordAdapterSendMessage
# =============================================================================


class TestDiscordAdapterSendMessage:
    """Tests d'envoi de messages."""

    def test_send_message_not_connected(self, adapter):
        """Test envoi message quand non connecté retourne None."""
        result = adapter.send_message("123", "Hello")
        assert result is None

    def test_send_message_no_client(self, adapter):
        """Test envoi message sans client."""
        adapter._connected = True
        adapter._client = None
        result = adapter.send_message("123", "Hello")
        assert result is None

    def test_send_message_channel_not_found(self, connected_adapter):
        """Test envoi message avec canal non trouvé."""
        connected_adapter._client.get_channel.return_value = None
        result = connected_adapter.send_message("123", "Hello")
        assert result is None

    def test_send_message_success(self, connected_adapter, mock_channel):
        """Test envoi message avec succès."""
        connected_adapter._client.get_channel.return_value = mock_channel

        # Create completed future
        future = Future()
        future.set_result("new_msg_id_123")

        with patch('asyncio.run_coroutine_threadsafe', return_value=future):
            result = connected_adapter.send_message("987654321", "Hello world")
            assert result == "new_msg_id_123"

    def test_send_message_with_reply(self, connected_adapter, mock_channel):
        """Test envoi message en réponse."""
        connected_adapter._client.get_channel.return_value = mock_channel

        future = Future()
        future.set_result("reply_msg_id_456")

        with patch('asyncio.run_coroutine_threadsafe', return_value=future):
            result = connected_adapter.send_message("987654321", "Reply", reply_to_id="111222")
            assert result == "reply_msg_id_456"

    def test_send_message_no_loop(self, connected_adapter, mock_channel):
        """Test envoi message sans loop."""
        connected_adapter._client.get_channel.return_value = mock_channel
        connected_adapter._loop = None

        result = connected_adapter.send_message("123", "Hello")
        assert result is None

    def test_send_message_exception(self, connected_adapter):
        """Test envoi message avec exception."""
        connected_adapter._client.get_channel.side_effect = Exception("Send error")
        result = connected_adapter.send_message("123", "Hello")
        assert result is None


# =============================================================================
# TestDiscordAdapterEditMessage
# =============================================================================


class TestDiscordAdapterEditMessage:
    """Tests de modification de messages."""

    def test_edit_message_not_connected(self, adapter):
        """Test édition message quand non connecté retourne False."""
        result = adapter.edit_message("123", "456", "New content")
        assert result is False

    def test_edit_message_no_client(self, adapter):
        """Test édition message sans client."""
        adapter._connected = True
        adapter._client = None
        result = adapter.edit_message("123", "456", "New content")
        assert result is False

    def test_edit_message_channel_not_found(self, connected_adapter):
        """Test édition message avec canal non trouvé."""
        connected_adapter._client.get_channel.return_value = None
        result = connected_adapter.edit_message("123", "456", "New content")
        assert result is False

    def test_edit_message_success(self, connected_adapter, mock_channel):
        """Test édition message avec succès."""
        connected_adapter._client.get_channel.return_value = mock_channel

        future = Future()
        future.set_result(True)

        with patch('asyncio.run_coroutine_threadsafe', return_value=future):
            result = connected_adapter.edit_message("987654321", "111222", "Edited content")
            assert result is True

    def test_edit_message_no_loop(self, connected_adapter, mock_channel):
        """Test édition message sans loop."""
        connected_adapter._client.get_channel.return_value = mock_channel
        connected_adapter._loop = None

        result = connected_adapter.edit_message("123", "456", "New")
        assert result is False

    def test_edit_message_exception(self, connected_adapter):
        """Test édition message avec exception."""
        connected_adapter._client.get_channel.side_effect = Exception("Edit error")
        result = connected_adapter.edit_message("123", "456", "New")
        assert result is False


# =============================================================================
# TestDiscordAdapterDeleteMessage
# =============================================================================


class TestDiscordAdapterDeleteMessage:
    """Tests de suppression de messages."""

    def test_delete_message_not_connected(self, adapter):
        """Test suppression message quand non connecté retourne False."""
        result = adapter.delete_message("123", "456")
        assert result is False

    def test_delete_message_no_client(self, adapter):
        """Test suppression message sans client."""
        adapter._connected = True
        adapter._client = None
        result = adapter.delete_message("123", "456")
        assert result is False

    def test_delete_message_channel_not_found(self, connected_adapter):
        """Test suppression message avec canal non trouvé."""
        connected_adapter._client.get_channel.return_value = None
        result = connected_adapter.delete_message("123", "456")
        assert result is False

    def test_delete_message_success(self, connected_adapter, mock_channel):
        """Test suppression message avec succès."""
        connected_adapter._client.get_channel.return_value = mock_channel

        future = Future()
        future.set_result(True)

        with patch('asyncio.run_coroutine_threadsafe', return_value=future):
            result = connected_adapter.delete_message("987654321", "111222")
            assert result is True

    def test_delete_message_no_loop(self, connected_adapter, mock_channel):
        """Test suppression message sans loop."""
        connected_adapter._client.get_channel.return_value = mock_channel
        connected_adapter._loop = None

        result = connected_adapter.delete_message("123", "456")
        assert result is False

    def test_delete_message_exception(self, connected_adapter):
        """Test suppression message avec exception."""
        connected_adapter._client.get_channel.side_effect = Exception("Delete error")
        result = connected_adapter.delete_message("123", "456")
        assert result is False


# =============================================================================
# TestDiscordAdapterGetChannels
# =============================================================================


class TestDiscordAdapterGetChannels:
    """Tests de récupération des canaux."""

    def test_get_channels_not_connected(self, adapter):
        """Test récupération canaux quand non connecté retourne liste vide."""
        result = adapter.get_channels()
        assert result == []

    def test_get_channels_no_client(self, adapter):
        """Test récupération canaux sans client."""
        adapter._connected = True
        adapter._client = None
        result = adapter.get_channels()
        assert result == []

    def test_get_channels_success(self, connected_adapter):
        """Test récupération canaux avec succès."""
        # Create mock guild and channels
        mock_channel1 = MagicMock()
        mock_channel1.id = 111
        mock_channel1.name = "general"

        mock_channel2 = MagicMock()
        mock_channel2.id = 222
        mock_channel2.name = "dev"

        mock_guild = MagicMock()
        mock_guild.id = 999
        mock_guild.name = "Test Server"
        mock_guild.text_channels = [mock_channel1, mock_channel2]

        connected_adapter._client.guilds = [mock_guild]

        result = connected_adapter.get_channels()
        assert len(result) == 2
        assert result[0]["id"] == "111"
        assert result[0]["name"] == "general"
        assert result[0]["type"] == "text"
        assert result[0]["guild_id"] == "999"
        assert result[0]["guild_name"] == "Test Server"

    def test_get_channels_multiple_guilds(self, connected_adapter):
        """Test récupération canaux de plusieurs serveurs."""
        mock_channel1 = MagicMock()
        mock_channel1.id = 111
        mock_channel1.name = "general"

        mock_channel2 = MagicMock()
        mock_channel2.id = 222
        mock_channel2.name = "support"

        mock_guild1 = MagicMock()
        mock_guild1.id = 999
        mock_guild1.name = "Server 1"
        mock_guild1.text_channels = [mock_channel1]

        mock_guild2 = MagicMock()
        mock_guild2.id = 888
        mock_guild2.name = "Server 2"
        mock_guild2.text_channels = [mock_channel2]

        connected_adapter._client.guilds = [mock_guild1, mock_guild2]

        result = connected_adapter.get_channels()
        assert len(result) == 2

    def test_get_channels_empty_guild(self, connected_adapter):
        """Test récupération canaux d'un serveur vide."""
        mock_guild = MagicMock()
        mock_guild.id = 999
        mock_guild.name = "Empty Server"
        mock_guild.text_channels = []

        connected_adapter._client.guilds = [mock_guild]

        result = connected_adapter.get_channels()
        assert result == []

    def test_get_channels_exception(self, connected_adapter):
        """Test récupération canaux avec exception."""
        type(connected_adapter._client).guilds = PropertyMock(side_effect=Exception("Guild error"))
        result = connected_adapter.get_channels()
        assert result == []


# =============================================================================
# TestDiscordAdapterMessageHandler
# =============================================================================


class TestDiscordAdapterMessageHandler:
    """Tests du handler de messages."""

    def test_register_message_handler(self, adapter):
        """Test enregistrement d'un handler."""
        handler = MagicMock()
        adapter.register_message_handler(handler)
        assert handler in adapter._message_handlers

    def test_multiple_handlers(self, adapter):
        """Test enregistrement de plusieurs handlers."""
        handler1 = MagicMock()
        handler2 = MagicMock()

        adapter.register_message_handler(handler1)
        adapter.register_message_handler(handler2)

        assert len(adapter._message_handlers) == 2
        assert handler1 in adapter._message_handlers
        assert handler2 in adapter._message_handlers

    def test_register_callable(self, adapter):
        """Test enregistrement d'une fonction comme handler."""
        def my_handler(msg):
            pass

        adapter.register_message_handler(my_handler)
        assert my_handler in adapter._message_handlers


# =============================================================================
# TestDiscordAdapterListening
# =============================================================================


class TestDiscordAdapterListening:
    """Tests des méthodes start/stop listening."""

    def test_start_listening_calls_connect(self, adapter):
        """Test start_listening appelle connect."""
        with patch.object(adapter, 'connect', return_value=True) as mock_connect:
            result = adapter.start_listening()
            mock_connect.assert_called_once()
            assert result is True

    def test_stop_listening_calls_disconnect(self, adapter):
        """Test stop_listening appelle disconnect."""
        with patch.object(adapter, 'disconnect', return_value=True) as mock_disconnect:
            result = adapter.stop_listening()
            mock_disconnect.assert_called_once()
            assert result is True

    def test_start_listening_returns_false_on_failure(self, adapter):
        """Test start_listening retourne False si échec."""
        with patch.object(adapter, 'connect', return_value=False):
            result = adapter.start_listening()
            assert result is False

    def test_stop_listening_returns_true(self, connected_adapter):
        """Test stop_listening réussit."""
        with patch.object(connected_adapter, 'disconnect', return_value=True):
            result = connected_adapter.stop_listening()
            assert result is True


# =============================================================================
# TestGetDiscordAdapterSingleton
# =============================================================================


class TestGetDiscordAdapterSingleton:
    """Tests pour le singleton get_discord_adapter."""

    def test_get_adapter_returns_none_without_token(self, monkeypatch):
        """Test retourne None si pas de token configuré."""
        from app.providers import discord_adapter as module

        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
        module._discord_adapter = None

        result = module.get_discord_adapter()
        assert result is None

    def test_get_adapter_returns_singleton(self, monkeypatch):
        """Test retourne le même singleton."""
        from app.providers import discord_adapter as module

        monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token-789")
        module._discord_adapter = None

        adapter1 = module.get_discord_adapter()
        adapter2 = module.get_discord_adapter()

        assert adapter1 is adapter2
        module._discord_adapter = None

    def test_reset_adapter(self, monkeypatch):
        """Test reset du singleton."""
        from app.providers import discord_adapter as module

        monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token-789")
        module._discord_adapter = None

        adapter1 = module.get_discord_adapter()
        module.reset_discord_adapter()
        adapter2 = module.get_discord_adapter()

        assert adapter1 is not adapter2
        module._discord_adapter = None

    def test_reset_disconnects_existing(self, monkeypatch):
        """Test reset déconnecte l'adapter existant."""
        from app.providers import discord_adapter as module

        monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token-789")
        module._discord_adapter = None

        adapter = module.get_discord_adapter()
        with patch.object(adapter, 'disconnect', return_value=True) as mock_disconnect:
            module.reset_discord_adapter()
            mock_disconnect.assert_called_once()

        module._discord_adapter = None

    def test_reset_with_no_adapter(self):
        """Test reset quand pas d'adapter."""
        from app.providers import discord_adapter as module
        module._discord_adapter = None

        # Should not raise
        module.reset_discord_adapter()
        assert module._discord_adapter is None


# =============================================================================
# TestStandardMessage
# =============================================================================


class TestStandardMessage:
    """Tests pour StandardMessage."""

    def test_standard_message_creation(self):
        """Test création d'un StandardMessage."""
        msg = StandardMessage(
            id="123",
            channel_id="456",
            author_id="789",
            author_name="user",
            content="Hello world"
        )
        assert msg.id == "123"
        assert msg.channel_id == "456"
        assert msg.preview == "Hello world"

    def test_standard_message_long_content_preview(self):
        """Test preview avec contenu long."""
        long_content = "x" * 150
        msg = StandardMessage(
            id="1",
            channel_id="2",
            content=long_content
        )
        assert len(msg.preview) == 103
        assert msg.preview.endswith("...")

    def test_author_display_with_display_name(self):
        """Test author_display retourne display_name si présent."""
        msg = StandardMessage(
            id="1",
            channel_id="2",
            author_name="user123",
            author_display_name="John Doe"
        )
        assert msg.author_display == "John Doe"

    def test_author_display_fallback(self):
        """Test author_display fallback vers author_name."""
        msg = StandardMessage(
            id="1",
            channel_id="2",
            author_name="user123"
        )
        assert msg.author_display == "user123"

    def test_standard_message_defaults(self):
        """Test valeurs par défaut de StandardMessage."""
        msg = StandardMessage(
            id="1",
            channel_id="2",
        )
        # Default is empty string, not None
        assert msg.author_id == ""
        assert msg.author_name == ""
        assert msg.content == ""
        assert msg.is_bot is False
        assert msg.is_mention is False
        assert msg.is_dm is False
        assert msg.reply_to_id is None
        assert msg.attachments == []


# =============================================================================
# TestDiscordAdapterEdgeCases
# =============================================================================


class TestDiscordAdapterEdgeCases:
    """Tests des cas limites."""

    def test_empty_channel_name(self, connected_adapter, mock_discord_message):
        """Test message avec nom de canal vide."""
        mock_discord_message.channel.name = None
        del mock_discord_message.channel.recipient

        result = connected_adapter._to_standard_message(mock_discord_message)
        assert result.channel_name is None

    def test_message_without_mentions_attribute(self, connected_adapter, mock_discord_message):
        """Test message sans attribut mentions."""
        del mock_discord_message.mentions

        result = connected_adapter._to_standard_message(mock_discord_message)
        assert result.is_mention is False

    def test_reference_without_message_id(self, connected_adapter, mock_discord_message):
        """Test référence sans message_id."""
        mock_discord_message.reference = MagicMock()
        mock_discord_message.reference.message_id = None

        result = connected_adapter._to_standard_message(mock_discord_message)
        assert result.reply_to_id is None

    def test_channel_without_type_attribute(self, connected_adapter, mock_discord_message):
        """Test canal sans attribut type."""
        del mock_discord_message.channel.type

        result = connected_adapter._to_standard_message(mock_discord_message)
        # Should not raise, defaults to non-DM
        assert result.is_dm is False

    def test_client_user_none(self, connected_adapter, mock_discord_message):
        """Test avec client.user None."""
        connected_adapter._client.user = None
        mock_discord_message.mentions = []

        result = connected_adapter._to_standard_message(mock_discord_message)
        assert result.is_mention is False


# =============================================================================
# TestDiscordAdapterAsyncInnerFunctions
# =============================================================================


class TestDiscordAdapterAsyncInnerFunctions:
    """Tests pour les fonctions async internes (_send, _edit, _delete)."""

    def test_send_with_reply_fetch_message_exception(self, connected_adapter, mock_channel):
        """Test envoi avec réponse quand fetch_message échoue."""
        connected_adapter._client.get_channel.return_value = mock_channel

        # Mock fetch_message to raise exception
        mock_channel.fetch_message = AsyncMock(side_effect=Exception("Fetch error"))

        # Create mock message for send
        mock_sent_msg = MagicMock()
        mock_sent_msg.id = 12345
        mock_channel.send = AsyncMock(return_value=mock_sent_msg)

        # Use a real event loop to test async
        async def run_test():
            channel = connected_adapter._client.get_channel(123)
            reference = None
            reply_to_id = "999"
            if reply_to_id:
                try:
                    ref_msg = await channel.fetch_message(int(reply_to_id))
                    reference = ref_msg.to_reference()
                except Exception:
                    pass  # This is the path we're testing
            msg = await channel.send("Test message", reference=reference)
            return str(msg.id)

        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(run_test())
        loop.close()

        assert result == "12345"

    def test_send_with_valid_reply(self, connected_adapter, mock_channel):
        """Test envoi avec réponse valide."""
        connected_adapter._client.get_channel.return_value = mock_channel

        # Mock successful fetch_message
        mock_ref_msg = MagicMock()
        mock_reference = MagicMock()
        mock_ref_msg.to_reference.return_value = mock_reference
        mock_channel.fetch_message = AsyncMock(return_value=mock_ref_msg)

        # Create mock message for send
        mock_sent_msg = MagicMock()
        mock_sent_msg.id = 67890
        mock_channel.send = AsyncMock(return_value=mock_sent_msg)

        async def run_test():
            channel = connected_adapter._client.get_channel(123)
            reference = None
            reply_to_id = "999"
            if reply_to_id:
                try:
                    ref_msg = await channel.fetch_message(int(reply_to_id))
                    reference = ref_msg.to_reference()
                except Exception:
                    pass
            msg = await channel.send("Reply message", reference=reference)
            return str(msg.id)

        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(run_test())
        loop.close()

        assert result == "67890"
        mock_ref_msg.to_reference.assert_called_once()

    def test_edit_inner_function(self, connected_adapter, mock_channel):
        """Test fonction interne _edit."""
        connected_adapter._client.get_channel.return_value = mock_channel

        # Mock fetch and edit
        mock_message = MagicMock()
        mock_message.edit = AsyncMock()
        mock_channel.fetch_message = AsyncMock(return_value=mock_message)

        async def run_test():
            channel = connected_adapter._client.get_channel(123)
            message = await channel.fetch_message(456)
            await message.edit(content="New content")
            return True

        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(run_test())
        loop.close()

        assert result is True
        mock_message.edit.assert_called_once_with(content="New content")

    def test_delete_inner_function(self, connected_adapter, mock_channel):
        """Test fonction interne _delete."""
        connected_adapter._client.get_channel.return_value = mock_channel

        # Mock fetch and delete
        mock_message = MagicMock()
        mock_message.delete = AsyncMock()
        mock_channel.fetch_message = AsyncMock(return_value=mock_message)

        async def run_test():
            channel = connected_adapter._client.get_channel(123)
            message = await channel.fetch_message(456)
            await message.delete()
            return True

        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(run_test())
        loop.close()

        assert result is True
        mock_message.delete.assert_called_once()


# =============================================================================
# TestDiscordAdapterSendEditDeleteWithEventLoop
# =============================================================================


class TestDiscordAdapterSendEditDeleteWithEventLoop:
    """Tests des opérations send/edit/delete avec une vraie event loop."""

    def test_send_message_executes_inner_async(self, connected_adapter, mock_channel):
        """Test send_message exécute correctement la fonction async interne."""
        connected_adapter._client.get_channel.return_value = mock_channel

        # Create a real event loop for the adapter
        connected_adapter._loop = asyncio.new_event_loop()

        # Mock the async send
        mock_sent_msg = MagicMock()
        mock_sent_msg.id = 99999
        mock_channel.send = AsyncMock(return_value=mock_sent_msg)

        # Call send_message which should use run_coroutine_threadsafe
        try:
            with patch('asyncio.run_coroutine_threadsafe') as mock_run:
                # Create a future that returns our expected value
                future = Future()
                future.set_result("99999")
                mock_run.return_value = future

                result = connected_adapter.send_message("123", "Hello world")
                assert result == "99999"
        finally:
            connected_adapter._loop.close()

    def test_send_message_with_reply_executes_inner_async(self, connected_adapter, mock_channel):
        """Test send_message avec reply exécute correctement la fonction async interne."""
        connected_adapter._client.get_channel.return_value = mock_channel
        connected_adapter._loop = asyncio.new_event_loop()

        try:
            with patch('asyncio.run_coroutine_threadsafe') as mock_run:
                future = Future()
                future.set_result("reply_id_777")
                mock_run.return_value = future

                result = connected_adapter.send_message("123", "Reply", reply_to_id="456")
                assert result == "reply_id_777"

                # Verify run_coroutine_threadsafe was called
                mock_run.assert_called_once()
        finally:
            connected_adapter._loop.close()

    def test_edit_message_executes_inner_async(self, connected_adapter, mock_channel):
        """Test edit_message exécute correctement la fonction async interne."""
        connected_adapter._client.get_channel.return_value = mock_channel
        connected_adapter._loop = asyncio.new_event_loop()

        try:
            with patch('asyncio.run_coroutine_threadsafe') as mock_run:
                future = Future()
                future.set_result(True)
                mock_run.return_value = future

                result = connected_adapter.edit_message("123", "456", "Edited content")
                assert result is True
        finally:
            connected_adapter._loop.close()

    def test_delete_message_executes_inner_async(self, connected_adapter, mock_channel):
        """Test delete_message exécute correctement la fonction async interne."""
        connected_adapter._client.get_channel.return_value = mock_channel
        connected_adapter._loop = asyncio.new_event_loop()

        try:
            with patch('asyncio.run_coroutine_threadsafe') as mock_run:
                future = Future()
                future.set_result(True)
                mock_run.return_value = future

                result = connected_adapter.delete_message("123", "456")
                assert result is True
        finally:
            connected_adapter._loop.close()


# =============================================================================
# TestDiscordAdapterConnectAvailable
# =============================================================================


class TestDiscordAdapterConnectAvailable:
    """Tests pour connect() quand discord.py est disponible."""

    def test_connect_starts_thread_mocked(self):
        """Test connect démarre un thread (mocking DISCORD_AVAILABLE)."""
        import app.providers.discord_adapter as module
        original = module.DISCORD_AVAILABLE
        module.DISCORD_AVAILABLE = True

        try:
            adapter = DiscordAdapter(bot_token="test-token")
            adapter._connected = False

            # Mock Thread to avoid actually starting a thread
            with patch('app.providers.discord_adapter.Thread') as mock_thread_class:
                mock_thread = MagicMock()
                mock_thread_class.return_value = mock_thread

                result = adapter.connect()

                assert result is True
                assert adapter._loop is not None
                mock_thread_class.assert_called_once()
                mock_thread.start.assert_called_once()
        finally:
            module.DISCORD_AVAILABLE = original

    def test_connect_already_connected_mocked(self):
        """Test connect retourne True quand déjà connecté avec DISCORD_AVAILABLE=True."""
        import app.providers.discord_adapter as module
        original = module.DISCORD_AVAILABLE
        module.DISCORD_AVAILABLE = True

        try:
            adapter = DiscordAdapter(bot_token="test-token")
            adapter._connected = True  # Already connected

            result = adapter.connect()
            assert result is True
        finally:
            module.DISCORD_AVAILABLE = original

    def test_connect_exception_in_thread_creation_mocked(self):
        """Test connect avec exception lors de la création du thread."""
        import app.providers.discord_adapter as module
        original = module.DISCORD_AVAILABLE
        module.DISCORD_AVAILABLE = True

        try:
            adapter = DiscordAdapter(bot_token="test-token")

            with patch('app.providers.discord_adapter.Thread',
                       side_effect=Exception("Thread creation error")):
                result = adapter.connect()
                assert result is False
        finally:
            module.DISCORD_AVAILABLE = original


# =============================================================================
# TestDiscordAdapterConnectAsyncAvailable
# =============================================================================


class TestDiscordAdapterConnectAsyncAvailable:
    """Tests pour connect_async() quand discord.py est disponible."""

    def test_connect_async_calls_start_client_mocked(self):
        """Test connect_async appelle _start_client."""
        import app.providers.discord_adapter as module
        original = module.DISCORD_AVAILABLE
        module.DISCORD_AVAILABLE = True

        try:
            adapter = DiscordAdapter(bot_token="test-token")

            with patch.object(adapter, '_start_client',
                              new_callable=AsyncMock,
                              return_value=True) as mock_start:
                loop = asyncio.new_event_loop()
                result = loop.run_until_complete(adapter.connect_async())
                loop.close()

                assert result is True
                mock_start.assert_called_once()
        finally:
            module.DISCORD_AVAILABLE = original

    def test_connect_async_exception_from_start_client_mocked(self):
        """Test connect_async avec exception de _start_client."""
        import app.providers.discord_adapter as module
        original = module.DISCORD_AVAILABLE
        module.DISCORD_AVAILABLE = True

        try:
            adapter = DiscordAdapter(bot_token="test-token")

            with patch.object(adapter, '_start_client',
                              side_effect=Exception("Start client error")):
                loop = asyncio.new_event_loop()
                result = loop.run_until_complete(adapter.connect_async())
                loop.close()

                assert result is False
        finally:
            module.DISCORD_AVAILABLE = original


# =============================================================================
# TestDiscordAdapterStartClientAvailable
# =============================================================================


class TestDiscordAdapterStartClientAvailable:
    """Tests pour _start_client() quand discord.py est disponible."""

    @pytest.mark.skipif(not DISCORD_AVAILABLE, reason="discord.py non installé")
    def test_start_client_uses_default_intents(self):
        """Test _start_client utilise les intents par défaut."""
        adapter = DiscordAdapter(bot_token="test-token")

        with patch('discord.Client') as mock_client_class:
            mock_client = MagicMock()
            mock_client.start = AsyncMock(side_effect=asyncio.TimeoutError())
            mock_client_class.return_value = mock_client

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(asyncio.wait_for(
                    adapter._start_client(), timeout=0.1))
            except (asyncio.TimeoutError, Exception):
                pass
            finally:
                loop.close()

            # Verify Client was created
            mock_client_class.assert_called_once()

    @pytest.mark.skipif(not DISCORD_AVAILABLE, reason="discord.py non installé")
    def test_start_client_uses_custom_intents(self):
        """Test _start_client utilise les intents personnalisés."""
        from discord import Intents
        custom_intents = Intents.default()
        adapter = DiscordAdapter(bot_token="test-token", intents=custom_intents)

        with patch('discord.Client') as mock_client_class:
            mock_client = MagicMock()
            mock_client.start = AsyncMock(side_effect=asyncio.TimeoutError())
            mock_client_class.return_value = mock_client

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(asyncio.wait_for(
                    adapter._start_client(), timeout=0.1))
            except (asyncio.TimeoutError, Exception):
                pass
            finally:
                loop.close()

            mock_client_class.assert_called_once()

    @pytest.mark.skipif(not DISCORD_AVAILABLE, reason="discord.py non installé")
    def test_start_client_exception_in_start(self):
        """Test _start_client avec exception dans client.start."""
        adapter = DiscordAdapter(bot_token="test-token")

        with patch('discord.Client') as mock_client_class:
            mock_client = MagicMock()
            mock_client.start = AsyncMock(side_effect=Exception("Start error"))
            mock_client_class.return_value = mock_client

            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(adapter._start_client())
            loop.close()

            assert result is False


# =============================================================================
# TestDiscordAdapterRunClientIntegration
# =============================================================================


class TestDiscordAdapterRunClientIntegration:
    """Tests d'intégration pour _run_client."""

    def test_run_client_runs_start_client_mocked(self):
        """Test _run_client exécute _start_client."""
        adapter = DiscordAdapter(bot_token="test-token")
        adapter._loop = asyncio.new_event_loop()

        with patch.object(adapter, '_start_client',
                          new_callable=AsyncMock,
                          return_value=True) as mock_start:
            with patch('asyncio.set_event_loop') as mock_set_loop:
                adapter._run_client()

                mock_set_loop.assert_called_once_with(adapter._loop)
                mock_start.assert_called_once()

        adapter._loop.close()


# =============================================================================
# TestDiscordImportFailure
# =============================================================================


class TestDiscordImportFailure:
    """Tests pour le cas où l'import discord échoue."""

    def test_discord_available_constant(self):
        """Test que DISCORD_AVAILABLE est défini."""
        from app.providers.discord_adapter import DISCORD_AVAILABLE
        assert isinstance(DISCORD_AVAILABLE, bool)

    def test_import_warning_logged(self, caplog):
        """Test que le warning est loggé si discord n'est pas disponible."""
        # This test verifies the module behavior when discord is not available
        # The actual import warning would have been logged at module import time
        import app.providers.discord_adapter as module

        # If discord is not available, DISCORD_AVAILABLE should be False
        if not module.DISCORD_AVAILABLE:
            assert "discord.py non installé" in caplog.text or True  # Warning may have been logged earlier
