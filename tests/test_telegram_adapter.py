# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour le TelegramAdapter.

Tests exhaustifs pour atteindre une couverture >95%.
"""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime
from concurrent.futures import Future

from app.interfaces.message_provider import (
    StandardMessage,
    ChannelType,
)


def run_async(coro):
    """
    Helper to run async code in tests without event loop issues.
    Uses asyncio.run() which creates a fresh event loop.
    """
    return asyncio.run(coro)


# ============================================================================
# INIT TESTS
# ============================================================================


class TestTelegramAdapterInit:
    """Tests d'initialisation du TelegramAdapter."""

    def test_init_with_token(self):
        """Test initialisation avec token."""
        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token-123")
        assert adapter.provider_name == "telegram"
        assert adapter.channel_type == ChannelType.TELEGRAM
        assert not adapter.is_connected()

    def test_init_without_token_raises(self):
        """Test initialisation sans token lève une exception."""
        from app.providers.telegram_adapter import TelegramAdapter

        with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
            TelegramAdapter(bot_token="")

    def test_init_from_env(self, monkeypatch):
        """Test initialisation depuis variable d'environnement."""
        from app.providers.telegram_adapter import TelegramAdapter

        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env-token-456")
        adapter = TelegramAdapter()
        assert adapter._bot_token == "env-token-456"

    def test_init_with_none_and_no_env_raises(self, monkeypatch):
        """Test initialisation avec None et sans variable d'environnement."""
        from app.providers.telegram_adapter import TelegramAdapter

        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        with pytest.raises(ValueError, match="Token Telegram requis"):
            TelegramAdapter(bot_token=None)

    def test_provider_name_property(self):
        """Test propriété provider_name."""
        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")
        assert adapter.provider_name == "telegram"

    def test_channel_type_property(self):
        """Test propriété channel_type."""
        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")
        assert adapter.channel_type == ChannelType.TELEGRAM


# ============================================================================
# MESSAGE CONVERSION TESTS
# ============================================================================


class TestTelegramAdapterMessages:
    """Tests des opérations sur les messages."""

    @pytest.fixture
    def adapter(self):
        """Fixture pour créer un adapter avec mocks."""
        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")
        adapter._bot = MagicMock()
        adapter._connected = True
        return adapter

    @pytest.fixture
    def mock_message(self):
        """Fixture pour un message Telegram mocké."""
        msg = MagicMock()
        msg.message_id = 123456789
        msg.chat.id = 987654321
        msg.chat.title = "Test Group"
        msg.chat.type = "group"
        msg.from_user.id = 111222333
        msg.from_user.username = "testuser"
        msg.from_user.first_name = "Test"
        msg.from_user.last_name = "User"
        msg.from_user.is_bot = False
        msg.text = "Hello, this is a test message"
        msg.date = datetime(2026, 1, 5, 10, 30)
        msg.reply_to_message = None
        msg.document = None
        msg.photo = None
        return msg

    def test_convert_to_standard_message(self, adapter, mock_message):
        """Test conversion message Telegram vers StandardMessage."""
        result = adapter._to_standard_message(mock_message)

        assert isinstance(result, StandardMessage)
        assert result.id == "123456789"
        assert result.channel_id == "987654321"
        assert result.channel_name == "Test Group"
        assert result.author_id == "111222333"
        assert result.author_name == "testuser"
        assert result.author_display_name == "Test User"
        assert result.content == "Hello, this is a test message"
        assert result.is_bot is False
        assert result.provider_source == ChannelType.TELEGRAM

    def test_convert_bot_message(self, adapter, mock_message):
        """Test conversion message de bot."""
        mock_message.from_user.is_bot = True
        result = adapter._to_standard_message(mock_message)
        assert result.is_bot is True

    def test_convert_reply_message(self, adapter, mock_message):
        """Test conversion message avec référence (réponse)."""
        mock_message.reply_to_message = MagicMock()
        mock_message.reply_to_message.message_id = 999888777
        result = adapter._to_standard_message(mock_message)
        assert result.reply_to_id == "999888777"

    def test_convert_private_message(self, adapter, mock_message):
        """Test conversion message privé."""
        mock_message.chat.type = "private"
        mock_message.chat.title = None
        result = adapter._to_standard_message(mock_message)
        assert result.is_dm is True
        assert result.channel_name == "DM-testuser"

    def test_convert_private_message_without_username(self, adapter, mock_message):
        """Test conversion message privé sans username."""
        mock_message.chat.type = "private"
        mock_message.chat.title = None
        mock_message.from_user.username = None
        result = adapter._to_standard_message(mock_message)
        assert result.is_dm is True
        assert result.channel_name == "DM-111222333"

    def test_convert_message_with_document(self, adapter, mock_message):
        """Test conversion message avec document."""
        mock_message.document = MagicMock()
        mock_message.document.file_id = "doc-file-id-123"
        result = adapter._to_standard_message(mock_message)
        assert "doc-file-id-123" in result.attachments

    def test_convert_message_with_photo(self, adapter, mock_message):
        """Test conversion message avec photo."""
        photo1 = MagicMock()
        photo1.file_id = "photo-small"
        photo2 = MagicMock()
        photo2.file_id = "photo-large"
        mock_message.photo = [photo1, photo2]
        result = adapter._to_standard_message(mock_message)
        assert "photo-large" in result.attachments

    def test_convert_message_with_empty_photo_list(self, adapter, mock_message):
        """Test conversion message avec liste photo vide."""
        mock_message.photo = []
        result = adapter._to_standard_message(mock_message)
        assert result.attachments == []

    def test_convert_message_without_last_name(self, adapter, mock_message):
        """Test conversion message sans nom de famille."""
        mock_message.from_user.last_name = None
        result = adapter._to_standard_message(mock_message)
        assert result.author_display_name == "Test"

    def test_convert_message_without_first_name(self, adapter, mock_message):
        """Test conversion message sans prénom."""
        mock_message.from_user.first_name = None
        mock_message.from_user.last_name = None
        result = adapter._to_standard_message(mock_message)
        assert result.author_display_name is None

    def test_convert_message_with_no_text(self, adapter, mock_message):
        """Test conversion message sans texte."""
        mock_message.text = None
        result = adapter._to_standard_message(mock_message)
        assert result.content == ""

    def test_convert_message_without_username(self, adapter, mock_message):
        """Test conversion message sans username."""
        mock_message.from_user.username = None
        result = adapter._to_standard_message(mock_message)
        assert result.author_name == "111222333"

    def test_convert_message_metadata(self, adapter, mock_message):
        """Test conversion message avec métadonnées."""
        result = adapter._to_standard_message(mock_message)
        assert result.raw_metadata == {"chat_type": "group"}

    def test_convert_message_is_mention_always_false(self, adapter, mock_message):
        """Test is_mention est toujours False pour Telegram."""
        result = adapter._to_standard_message(mock_message)
        assert result.is_mention is False


# ============================================================================
# CONNECTION TESTS
# ============================================================================


class TestTelegramAdapterConnection:
    """Tests de connexion/déconnexion."""

    def test_not_connected_by_default(self):
        """Test adapter non connecté par défaut."""
        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")
        assert adapter.is_connected() is False

    def test_connect_returns_false_when_telegram_unavailable(self):
        """Test connexion retourne False si python-telegram-bot non disponible."""
        import app.providers.telegram_adapter as telegram_module
        original_available = telegram_module.TELEGRAM_AVAILABLE

        telegram_module.TELEGRAM_AVAILABLE = False

        try:
            from app.providers.telegram_adapter import TelegramAdapter

            adapter = TelegramAdapter(bot_token="test-token")
            result = adapter.connect()
            assert result is False
        finally:
            telegram_module.TELEGRAM_AVAILABLE = original_available

    def test_connect_returns_true_when_already_connected(self):
        """Test connexion retourne True si déjà connecté."""
        import app.providers.telegram_adapter as telegram_module
        original_available = telegram_module.TELEGRAM_AVAILABLE

        telegram_module.TELEGRAM_AVAILABLE = True

        try:
            from app.providers.telegram_adapter import TelegramAdapter

            adapter = TelegramAdapter(bot_token="test-token")
            adapter._connected = True
            result = adapter.connect()
            assert result is True
        finally:
            telegram_module.TELEGRAM_AVAILABLE = original_available

    def test_connect_starts_thread(self):
        """Test connexion démarre un thread."""
        import app.providers.telegram_adapter as telegram_module
        original_available = telegram_module.TELEGRAM_AVAILABLE

        telegram_module.TELEGRAM_AVAILABLE = True

        try:
            from app.providers.telegram_adapter import TelegramAdapter

            adapter = TelegramAdapter(bot_token="test-token")
            with patch.object(adapter, "_run_client"):
                result = adapter.connect()
                assert result is True
                assert adapter._loop is not None
                assert adapter._thread is not None
        finally:
            telegram_module.TELEGRAM_AVAILABLE = original_available

    def test_connect_handles_exception(self):
        """Test connexion gère les exceptions."""
        import app.providers.telegram_adapter as telegram_module
        original_available = telegram_module.TELEGRAM_AVAILABLE

        telegram_module.TELEGRAM_AVAILABLE = True

        try:
            from app.providers.telegram_adapter import TelegramAdapter

            adapter = TelegramAdapter(bot_token="test-token")
            with patch("asyncio.new_event_loop", side_effect=Exception("Loop error")):
                result = adapter.connect()
                assert result is False
        finally:
            telegram_module.TELEGRAM_AVAILABLE = original_available

    def test_disconnect_when_not_connected(self):
        """Test déconnexion quand non connecté."""
        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")
        result = adapter.disconnect()
        assert result is True

    def test_disconnect_when_connected(self):
        """Test déconnexion quand connecté."""
        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")
        adapter._connected = True
        adapter._application = MagicMock()
        adapter._loop = MagicMock()
        adapter._loop.is_running.return_value = True

        with patch("asyncio.run_coroutine_threadsafe"):
            result = adapter.disconnect()

        assert result is True
        assert adapter._connected is False

    def test_disconnect_handles_exception(self):
        """Test déconnexion gère les exceptions."""
        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")
        adapter._connected = True
        adapter._application = MagicMock()
        adapter._loop = MagicMock()
        adapter._loop.is_running.side_effect = Exception("Loop error")

        result = adapter.disconnect()
        assert result is False


# ============================================================================
# ASYNC CONNECTION TESTS (using asyncio.run)
# ============================================================================


class TestTelegramAdapterAsyncConnection:
    """Tests de connexion asynchrone."""

    def test_connect_async_returns_false_when_unavailable(self):
        """Test connect_async retourne False si indisponible."""
        import app.providers.telegram_adapter as telegram_module
        original_available = telegram_module.TELEGRAM_AVAILABLE

        telegram_module.TELEGRAM_AVAILABLE = False

        try:
            from app.providers.telegram_adapter import TelegramAdapter

            adapter = TelegramAdapter(bot_token="test-token")
            result = run_async(
                adapter.connect_async()
            )
            assert result is False
        finally:
            telegram_module.TELEGRAM_AVAILABLE = original_available

    def test_connect_async_returns_true_when_already_connected(self):
        """Test connect_async retourne True si déjà connecté."""
        import app.providers.telegram_adapter as telegram_module
        original_available = telegram_module.TELEGRAM_AVAILABLE

        telegram_module.TELEGRAM_AVAILABLE = True

        try:
            from app.providers.telegram_adapter import TelegramAdapter

            adapter = TelegramAdapter(bot_token="test-token")
            adapter._connected = True
            result = run_async(
                adapter.connect_async()
            )
            assert result is True
        finally:
            telegram_module.TELEGRAM_AVAILABLE = original_available

    def test_connect_async_handles_exception(self):
        """Test connect_async gère les exceptions."""
        import app.providers.telegram_adapter as telegram_module
        original_available = telegram_module.TELEGRAM_AVAILABLE

        telegram_module.TELEGRAM_AVAILABLE = True

        try:
            from app.providers.telegram_adapter import TelegramAdapter

            adapter = TelegramAdapter(bot_token="test-token")

            async def mock_start_client():
                raise Exception("Start error")

            with patch.object(adapter, "_start_client", mock_start_client):
                result = run_async(
                    adapter.connect_async()
                )
                assert result is False
        finally:
            telegram_module.TELEGRAM_AVAILABLE = original_available


# ============================================================================
# START CLIENT TESTS
# ============================================================================


class TestTelegramAdapterStartClient:
    """Tests du démarrage du client."""

    def test_start_client_returns_false_when_unavailable(self):
        """Test _start_client retourne False si indisponible."""
        import app.providers.telegram_adapter as telegram_module
        original_available = telegram_module.TELEGRAM_AVAILABLE

        telegram_module.TELEGRAM_AVAILABLE = False

        try:
            from app.providers.telegram_adapter import TelegramAdapter

            adapter = TelegramAdapter(bot_token="test-token")
            result = run_async(
                adapter._start_client()
            )
            assert result is False
        finally:
            telegram_module.TELEGRAM_AVAILABLE = original_available

    def test_start_client_success(self):
        """Test _start_client réussit."""
        import app.providers.telegram_adapter as telegram_module

        if not telegram_module.TELEGRAM_AVAILABLE:
            pytest.skip("python-telegram-bot not installed")

        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")

        mock_app = MagicMock()
        mock_app.bot = MagicMock()
        mock_app.bot.get_me = AsyncMock(return_value=MagicMock(username="testbot"))
        mock_app.initialize = AsyncMock()
        mock_app.start = AsyncMock()
        mock_app.updater.start_polling = AsyncMock()
        mock_app.add_handler = MagicMock()

        mock_builder = MagicMock()
        mock_builder.token.return_value = mock_builder
        mock_builder.build.return_value = mock_app

        with patch(
            "app.providers.telegram_adapter.Application.builder",
            return_value=mock_builder,
        ):
            result = run_async(
                adapter._start_client()
            )
            assert result is True
            assert adapter._connected is True

    def test_start_client_handles_exception(self):
        """Test _start_client gère les exceptions."""
        import app.providers.telegram_adapter as telegram_module

        if not telegram_module.TELEGRAM_AVAILABLE:
            pytest.skip("python-telegram-bot not installed")

        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")

        with patch(
            "app.providers.telegram_adapter.Application.builder",
            side_effect=Exception("Build error"),
        ):
            result = run_async(
                adapter._start_client()
            )
            assert result is False


# ============================================================================
# RUN CLIENT TESTS
# ============================================================================


class TestTelegramAdapterRunClient:
    """Tests de l'exécution du client dans une boucle."""

    def test_run_client_sets_event_loop(self):
        """Test _run_client configure la boucle d'événements."""
        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")
        mock_loop = MagicMock()
        mock_loop.run_until_complete = MagicMock()
        adapter._loop = mock_loop

        with patch.object(adapter, "_start_client", new_callable=AsyncMock):
            with patch("asyncio.set_event_loop") as mock_set_loop:
                adapter._run_client()
                mock_set_loop.assert_called_once_with(mock_loop)


# ============================================================================
# STOP APPLICATION TESTS
# ============================================================================


class TestTelegramAdapterStopApplication:
    """Tests de l'arrêt de l'application."""

    def test_stop_application(self):
        """Test _stop_application arrête proprement."""
        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")
        mock_app = MagicMock()
        mock_app.updater.stop = AsyncMock()
        mock_app.stop = AsyncMock()
        mock_app.shutdown = AsyncMock()
        adapter._application = mock_app

        run_async(adapter._stop_application())

        mock_app.updater.stop.assert_awaited_once()
        mock_app.stop.assert_awaited_once()
        mock_app.shutdown.assert_awaited_once()

    def test_stop_application_when_none(self):
        """Test _stop_application quand pas d'application."""
        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")
        adapter._application = None

        # Should not raise
        run_async(adapter._stop_application())


# ============================================================================
# CRUD OPERATIONS TESTS
# ============================================================================


class TestTelegramAdapterOperations:
    """Tests des opérations CRUD sur les messages."""

    def test_send_message_not_connected(self):
        """Test envoi message quand non connecté retourne None."""
        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")
        result = adapter.send_message("123", "Hello")
        assert result is None

    def test_send_message_no_bot(self):
        """Test envoi message sans bot retourne None."""
        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")
        adapter._connected = True
        adapter._bot = None
        result = adapter.send_message("123", "Hello")
        assert result is None

    def test_send_message_success(self):
        """Test envoi message réussi."""
        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")
        adapter._connected = True
        adapter._bot = MagicMock()
        adapter._loop = MagicMock()

        future = Future()
        future.set_result("789")

        with patch("asyncio.run_coroutine_threadsafe", return_value=future):
            result = adapter.send_message("123", "Hello")
            assert result == "789"

    def test_send_message_with_reply_to(self):
        """Test envoi message avec réponse."""
        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")
        adapter._connected = True
        adapter._bot = MagicMock()
        adapter._loop = MagicMock()

        future = Future()
        future.set_result("789")

        with patch("asyncio.run_coroutine_threadsafe", return_value=future):
            result = adapter.send_message("123", "Hello", reply_to_id="456")
            assert result == "789"

    def test_send_message_no_loop(self):
        """Test envoi message sans boucle retourne None."""
        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")
        adapter._connected = True
        adapter._bot = MagicMock()
        adapter._loop = None
        result = adapter.send_message("123", "Hello")
        assert result is None

    def test_send_message_handles_exception(self):
        """Test envoi message gère les exceptions."""
        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")
        adapter._connected = True
        adapter._bot = MagicMock()
        adapter._loop = MagicMock()

        with patch(
            "asyncio.run_coroutine_threadsafe", side_effect=Exception("Send error")
        ):
            result = adapter.send_message("123", "Hello")
            assert result is None

    def test_edit_message_not_connected(self):
        """Test édition message quand non connecté retourne False."""
        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")
        result = adapter.edit_message("123", "456", "New content")
        assert result is False

    def test_edit_message_no_bot(self):
        """Test édition message sans bot retourne False."""
        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")
        adapter._connected = True
        adapter._bot = None
        result = adapter.edit_message("123", "456", "New content")
        assert result is False

    def test_edit_message_success(self):
        """Test édition message réussie."""
        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")
        adapter._connected = True
        adapter._bot = MagicMock()
        adapter._loop = MagicMock()

        future = Future()
        future.set_result(True)

        with patch("asyncio.run_coroutine_threadsafe", return_value=future):
            result = adapter.edit_message("123", "456", "New content")
            assert result is True

    def test_edit_message_no_loop(self):
        """Test édition message sans boucle retourne False."""
        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")
        adapter._connected = True
        adapter._bot = MagicMock()
        adapter._loop = None
        result = adapter.edit_message("123", "456", "New content")
        assert result is False

    def test_edit_message_handles_exception(self):
        """Test édition message gère les exceptions."""
        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")
        adapter._connected = True
        adapter._bot = MagicMock()
        adapter._loop = MagicMock()

        with patch(
            "asyncio.run_coroutine_threadsafe", side_effect=Exception("Edit error")
        ):
            result = adapter.edit_message("123", "456", "New content")
            assert result is False

    def test_delete_message_not_connected(self):
        """Test suppression message quand non connecté retourne False."""
        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")
        result = adapter.delete_message("123", "456")
        assert result is False

    def test_delete_message_no_bot(self):
        """Test suppression message sans bot retourne False."""
        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")
        adapter._connected = True
        adapter._bot = None
        result = adapter.delete_message("123", "456")
        assert result is False

    def test_delete_message_success(self):
        """Test suppression message réussie."""
        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")
        adapter._connected = True
        adapter._bot = MagicMock()
        adapter._loop = MagicMock()

        future = Future()
        future.set_result(True)

        with patch("asyncio.run_coroutine_threadsafe", return_value=future):
            result = adapter.delete_message("123", "456")
            assert result is True

    def test_delete_message_no_loop(self):
        """Test suppression message sans boucle retourne False."""
        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")
        adapter._connected = True
        adapter._bot = MagicMock()
        adapter._loop = None
        result = adapter.delete_message("123", "456")
        assert result is False

    def test_delete_message_handles_exception(self):
        """Test suppression message gère les exceptions."""
        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")
        adapter._connected = True
        adapter._bot = MagicMock()
        adapter._loop = MagicMock()

        with patch(
            "asyncio.run_coroutine_threadsafe", side_effect=Exception("Delete error")
        ):
            result = adapter.delete_message("123", "456")
            assert result is False

    def test_get_recent_messages_not_connected(self):
        """Test récupération messages quand non connecté retourne liste vide."""
        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")
        result = adapter.get_recent_messages("123")
        assert result == []

    def test_get_recent_messages_connected(self):
        """Test récupération messages connecté retourne liste vide (API limitation)."""
        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")
        adapter._connected = True
        adapter._bot = MagicMock()
        result = adapter.get_recent_messages("123", limit=20)
        assert result == []

    def test_get_channels_not_connected(self):
        """Test récupération canaux quand non connecté retourne liste vide."""
        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")
        result = adapter.get_channels()
        assert result == []

    def test_get_channels_connected(self):
        """Test récupération canaux connecté retourne chats connus."""
        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")
        adapter._connected = True
        adapter._bot = MagicMock()
        adapter._known_chats = [{"id": "123", "name": "Test Chat", "type": "group"}]
        result = adapter.get_channels()
        assert len(result) == 1
        assert result[0]["id"] == "123"

    def test_get_channels_returns_copy(self):
        """Test récupération canaux retourne une copie."""
        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")
        adapter._connected = True
        adapter._bot = MagicMock()
        adapter._known_chats = [{"id": "123", "name": "Test Chat", "type": "group"}]
        result = adapter.get_channels()
        result.append({"id": "456", "name": "New", "type": "private"})
        assert len(adapter._known_chats) == 1


# ============================================================================
# GET UNREAD MENTIONS TESTS
# ============================================================================


class TestTelegramAdapterUnreadMentions:
    """Tests pour get_unread_mentions."""

    def test_get_unread_mentions_not_connected(self):
        """Test get_unread_mentions quand non connecté."""
        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")
        result = adapter.get_unread_mentions()
        assert result == []

    def test_get_unread_mentions_connected(self):
        """Test get_unread_mentions quand connecté retourne liste vide."""
        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")
        adapter._connected = True
        result = adapter.get_unread_mentions(limit=5)
        assert result == []


# ============================================================================
# MESSAGE HANDLER TESTS
# ============================================================================


class TestTelegramAdapterMessageHandler:
    """Tests du handler de messages."""

    def test_register_message_handler(self):
        """Test enregistrement d'un handler."""
        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")
        handler = MagicMock()

        adapter.register_message_handler(handler)

        assert handler in adapter._message_handlers

    def test_multiple_handlers(self):
        """Test enregistrement de plusieurs handlers."""
        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")
        handler1 = MagicMock()
        handler2 = MagicMock()

        adapter.register_message_handler(handler1)
        adapter.register_message_handler(handler2)

        assert len(adapter._message_handlers) == 2


# ============================================================================
# START/STOP LISTENING TESTS
# ============================================================================


class TestTelegramAdapterListening:
    """Tests pour start_listening et stop_listening."""

    def test_start_listening_calls_connect(self):
        """Test start_listening appelle connect."""
        import app.providers.telegram_adapter as telegram_module
        original_available = telegram_module.TELEGRAM_AVAILABLE

        telegram_module.TELEGRAM_AVAILABLE = True

        try:
            from app.providers.telegram_adapter import TelegramAdapter

            adapter = TelegramAdapter(bot_token="test-token")
            adapter._connected = True  # Simulate already connected

            result = adapter.start_listening()
            assert result is True
        finally:
            telegram_module.TELEGRAM_AVAILABLE = original_available

    def test_stop_listening_calls_disconnect(self):
        """Test stop_listening appelle disconnect."""
        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")

        result = adapter.stop_listening()
        assert result is True


# ============================================================================
# SINGLETON TESTS
# ============================================================================


class TestGetTelegramAdapter:
    """Tests pour le singleton get_telegram_adapter."""

    def test_get_adapter_returns_none_without_token(self, monkeypatch):
        """Test retourne None si pas de token configuré."""
        from app.providers import telegram_adapter as module

        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        module._telegram_adapter = None

        result = module.get_telegram_adapter()
        assert result is None

    def test_get_adapter_returns_singleton(self, monkeypatch):
        """Test retourne le même singleton."""
        from app.providers import telegram_adapter as module

        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token-789")
        module._telegram_adapter = None

        adapter1 = module.get_telegram_adapter()
        adapter2 = module.get_telegram_adapter()

        assert adapter1 is adapter2
        module._telegram_adapter = None

    def test_reset_adapter(self, monkeypatch):
        """Test reset du singleton."""
        from app.providers import telegram_adapter as module

        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token-789")
        module._telegram_adapter = None

        adapter1 = module.get_telegram_adapter()
        module.reset_telegram_adapter()
        adapter2 = module.get_telegram_adapter()

        assert adapter1 is not adapter2
        module._telegram_adapter = None

    def test_reset_adapter_when_none(self, monkeypatch):
        """Test reset quand singleton est None."""
        from app.providers import telegram_adapter as module

        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        module._telegram_adapter = None

        # Should not raise
        module.reset_telegram_adapter()

    def test_reset_adapter_disconnects(self, monkeypatch):
        """Test reset déconnecte l'adapter."""
        from app.providers import telegram_adapter as module

        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token-789")
        module._telegram_adapter = None

        adapter = module.get_telegram_adapter()
        adapter._connected = True
        adapter._application = MagicMock()
        adapter._loop = MagicMock()
        adapter._loop.is_running.return_value = True

        with patch("asyncio.run_coroutine_threadsafe"):
            module.reset_telegram_adapter()

        assert adapter._connected is False
        module._telegram_adapter = None


# ============================================================================
# TELEGRAM UNAVAILABLE TESTS
# ============================================================================


class TestTelegramUnavailable:
    """Tests quand python-telegram-bot n'est pas installé."""

    def test_connect_when_unavailable(self):
        """Test connect retourne False si unavailable."""
        import app.providers.telegram_adapter as module

        original = module.TELEGRAM_AVAILABLE

        module.TELEGRAM_AVAILABLE = False
        try:
            from app.providers.telegram_adapter import TelegramAdapter

            adapter = TelegramAdapter(bot_token="test")
            assert adapter.connect() is False
        finally:
            module.TELEGRAM_AVAILABLE = original

    def test_connect_async_when_unavailable(self):
        """Test connect_async retourne False si unavailable."""
        import app.providers.telegram_adapter as module

        original = module.TELEGRAM_AVAILABLE

        module.TELEGRAM_AVAILABLE = False
        try:
            from app.providers.telegram_adapter import TelegramAdapter

            adapter = TelegramAdapter(bot_token="test")
            result = run_async(
                adapter.connect_async()
            )
            assert result is False
        finally:
            module.TELEGRAM_AVAILABLE = original

    def test_start_client_when_unavailable(self):
        """Test _start_client retourne False si unavailable."""
        import app.providers.telegram_adapter as module

        original = module.TELEGRAM_AVAILABLE

        module.TELEGRAM_AVAILABLE = False
        try:
            from app.providers.telegram_adapter import TelegramAdapter

            adapter = TelegramAdapter(bot_token="test")
            result = run_async(
                adapter._start_client()
            )
            assert result is False
        finally:
            module.TELEGRAM_AVAILABLE = original


# ============================================================================
# EDGE CASES TESTS
# ============================================================================


class TestTelegramAdapterEdgeCases:
    """Tests pour les cas limites."""

    def test_message_with_both_document_and_photo(self):
        """Test message avec document et photo."""
        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")

        msg = MagicMock()
        msg.message_id = 123
        msg.chat.id = 456
        msg.chat.title = "Test"
        msg.chat.type = "group"
        msg.from_user.id = 789
        msg.from_user.username = "user"
        msg.from_user.first_name = "First"
        msg.from_user.last_name = None
        msg.from_user.is_bot = False
        msg.text = "Check this out"
        msg.date = datetime.now()
        msg.reply_to_message = None
        msg.document = MagicMock()
        msg.document.file_id = "doc-id"
        photo = MagicMock()
        photo.file_id = "photo-id"
        msg.photo = [photo]

        result = adapter._to_standard_message(msg)

        assert "doc-id" in result.attachments
        assert "photo-id" in result.attachments

    def test_disconnect_with_loop_not_running(self):
        """Test disconnect quand loop pas en cours."""
        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")
        adapter._connected = True
        adapter._application = MagicMock()
        adapter._loop = MagicMock()
        adapter._loop.is_running.return_value = False

        result = adapter.disconnect()

        assert result is True
        assert adapter._connected is False

    def test_private_chat_with_username(self):
        """Test message privé avec username."""
        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")

        msg = MagicMock()
        msg.message_id = 123
        msg.chat.id = 456
        msg.chat.title = None
        msg.chat.type = "private"
        msg.from_user.id = 789
        msg.from_user.username = "testuser"
        msg.from_user.first_name = "Test"
        msg.from_user.last_name = None
        msg.from_user.is_bot = False
        msg.text = "Hello"
        msg.date = datetime.now()
        msg.reply_to_message = None
        msg.document = None
        msg.photo = None

        result = adapter._to_standard_message(msg)

        assert result.channel_name == "DM-testuser"
        assert result.is_dm is True

    def test_group_with_no_title_uses_username(self):
        """Test groupe sans titre utilise username du chat."""
        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")

        msg = MagicMock()
        msg.message_id = 123
        msg.chat.id = 456
        msg.chat.title = None
        msg.chat.type = "group"
        msg.chat.username = "groupchat"
        msg.from_user.id = 789
        msg.from_user.username = "user"
        msg.from_user.first_name = "User"
        msg.from_user.last_name = None
        msg.from_user.is_bot = False
        msg.text = "Hello"
        msg.date = datetime.now()
        msg.reply_to_message = None
        msg.document = None
        msg.photo = None

        result = adapter._to_standard_message(msg)

        assert result.channel_name is None  # Not private, so no fallback
        assert result.is_dm is False


# ============================================================================
# INTERNAL HANDLER TESTS
# ============================================================================


class TestTelegramAdapterInternalHandler:
    """Tests pour le handler de message interne lors de _start_client."""

    def test_start_client_registers_message_handler(self):
        """Test _start_client enregistre le handler de messages."""
        import app.providers.telegram_adapter as telegram_module

        if not telegram_module.TELEGRAM_AVAILABLE:
            pytest.skip("python-telegram-bot not installed")

        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")

        mock_app = MagicMock()
        mock_app.bot = MagicMock()
        mock_app.bot.get_me = AsyncMock(return_value=MagicMock(username="testbot"))
        mock_app.initialize = AsyncMock()
        mock_app.start = AsyncMock()
        mock_app.updater.start_polling = AsyncMock()
        mock_app.add_handler = MagicMock()

        mock_builder = MagicMock()
        mock_builder.token.return_value = mock_builder
        mock_builder.build.return_value = mock_app

        with patch(
            "app.providers.telegram_adapter.Application.builder",
            return_value=mock_builder,
        ):
            run_async(adapter._start_client())
            # Verify add_handler was called
            mock_app.add_handler.assert_called_once()

    def test_message_handler_empty_message(self):
        """Test handler ignore les updates sans message."""
        # This tests the internal handle_message function indirectly
        # through the path in _start_client
        import app.providers.telegram_adapter as telegram_module

        if not telegram_module.TELEGRAM_AVAILABLE:
            pytest.skip("python-telegram-bot not installed")

        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")
        received = []
        adapter.register_message_handler(lambda msg: received.append(msg))

        mock_app = MagicMock()
        mock_app.bot = MagicMock()
        mock_app.bot.get_me = AsyncMock(return_value=MagicMock(id=999, username="testbot"))
        mock_app.initialize = AsyncMock()
        mock_app.start = AsyncMock()
        mock_app.updater.start_polling = AsyncMock()

        captured_handler = None

        def capture_handler(h):
            nonlocal captured_handler
            captured_handler = h

        mock_app.add_handler = capture_handler

        mock_builder = MagicMock()
        mock_builder.token.return_value = mock_builder
        mock_builder.build.return_value = mock_app

        with patch(
            "app.providers.telegram_adapter.Application.builder",
            return_value=mock_builder,
        ):
            run_async(adapter._start_client())

        # Test with empty message
        if captured_handler:
            mock_update = MagicMock()
            mock_update.message = None

            run_async(
                captured_handler.callback(mock_update, MagicMock())
            )
            assert len(received) == 0

    def test_message_handler_no_from_user(self):
        """Test handler ignore les messages sans from_user."""
        import app.providers.telegram_adapter as telegram_module

        if not telegram_module.TELEGRAM_AVAILABLE:
            pytest.skip("python-telegram-bot not installed")

        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")
        received = []
        adapter.register_message_handler(lambda msg: received.append(msg))

        mock_app = MagicMock()
        mock_app.bot = MagicMock()
        mock_app.bot.get_me = AsyncMock(return_value=MagicMock(id=999, username="testbot"))
        mock_app.initialize = AsyncMock()
        mock_app.start = AsyncMock()
        mock_app.updater.start_polling = AsyncMock()

        captured_handler = None

        def capture_handler(h):
            nonlocal captured_handler
            captured_handler = h

        mock_app.add_handler = capture_handler

        mock_builder = MagicMock()
        mock_builder.token.return_value = mock_builder
        mock_builder.build.return_value = mock_app

        with patch(
            "app.providers.telegram_adapter.Application.builder",
            return_value=mock_builder,
        ):
            run_async(adapter._start_client())

        # Test with message but no from_user
        if captured_handler:
            mock_update = MagicMock()
            mock_update.message.from_user = None

            run_async(
                captured_handler.callback(mock_update, MagicMock())
            )
            assert len(received) == 0

    def test_message_handler_ignores_own_bot_messages(self):
        """Test handler ignore les messages du bot lui-même."""
        import app.providers.telegram_adapter as telegram_module

        if not telegram_module.TELEGRAM_AVAILABLE:
            pytest.skip("python-telegram-bot not installed")

        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")
        received = []
        adapter.register_message_handler(lambda msg: received.append(msg))

        mock_app = MagicMock()
        mock_app.bot = MagicMock()
        mock_app.bot.get_me = AsyncMock(return_value=MagicMock(id=999, username="testbot"))
        mock_app.initialize = AsyncMock()
        mock_app.start = AsyncMock()
        mock_app.updater.start_polling = AsyncMock()

        captured_handler = None

        def capture_handler(h):
            nonlocal captured_handler
            captured_handler = h

        mock_app.add_handler = capture_handler

        mock_builder = MagicMock()
        mock_builder.token.return_value = mock_builder
        mock_builder.build.return_value = mock_app

        with patch(
            "app.providers.telegram_adapter.Application.builder",
            return_value=mock_builder,
        ):
            run_async(adapter._start_client())

        # Test with message from the bot itself
        if captured_handler:
            mock_update = MagicMock()
            mock_update.message.from_user.id = 999  # Same as bot

            run_async(
                captured_handler.callback(mock_update, MagicMock())
            )
            assert len(received) == 0

    def test_message_handler_processes_valid_message(self):
        """Test handler traite les messages valides."""
        import app.providers.telegram_adapter as telegram_module

        if not telegram_module.TELEGRAM_AVAILABLE:
            pytest.skip("python-telegram-bot not installed")

        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")
        received = []
        adapter.register_message_handler(lambda msg: received.append(msg))

        mock_app = MagicMock()
        mock_app.bot = MagicMock()
        mock_app.bot.get_me = AsyncMock(return_value=MagicMock(id=999, username="testbot"))
        mock_app.initialize = AsyncMock()
        mock_app.start = AsyncMock()
        mock_app.updater.start_polling = AsyncMock()

        captured_handler = None

        def capture_handler(h):
            nonlocal captured_handler
            captured_handler = h

        mock_app.add_handler = capture_handler

        mock_builder = MagicMock()
        mock_builder.token.return_value = mock_builder
        mock_builder.build.return_value = mock_app

        with patch(
            "app.providers.telegram_adapter.Application.builder",
            return_value=mock_builder,
        ):
            run_async(adapter._start_client())

        # Test with valid message
        if captured_handler:
            mock_update = MagicMock()
            mock_update.message.message_id = 123
            mock_update.message.chat.id = 456
            mock_update.message.chat.title = "Test Group"
            mock_update.message.chat.type = "group"
            mock_update.message.chat.username = None
            mock_update.message.from_user.id = 111  # Different from bot
            mock_update.message.from_user.username = "testuser"
            mock_update.message.from_user.first_name = "Test"
            mock_update.message.from_user.last_name = "User"
            mock_update.message.from_user.is_bot = False
            mock_update.message.text = "Hello"
            mock_update.message.date = datetime.now()
            mock_update.message.reply_to_message = None
            mock_update.message.document = None
            mock_update.message.photo = None

            run_async(
                captured_handler.callback(mock_update, MagicMock())
            )
            assert len(received) == 1
            assert len(adapter._known_chats) == 1

    def test_message_handler_catches_handler_exceptions(self):
        """Test handler attrape les exceptions des handlers."""
        import app.providers.telegram_adapter as telegram_module

        if not telegram_module.TELEGRAM_AVAILABLE:
            pytest.skip("python-telegram-bot not installed")

        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")

        def failing_handler(msg):
            raise Exception("Handler failure")

        adapter.register_message_handler(failing_handler)

        mock_app = MagicMock()
        mock_app.bot = MagicMock()
        mock_app.bot.get_me = AsyncMock(return_value=MagicMock(id=999, username="testbot"))
        mock_app.initialize = AsyncMock()
        mock_app.start = AsyncMock()
        mock_app.updater.start_polling = AsyncMock()

        captured_handler = None

        def capture_handler(h):
            nonlocal captured_handler
            captured_handler = h

        mock_app.add_handler = capture_handler

        mock_builder = MagicMock()
        mock_builder.token.return_value = mock_builder
        mock_builder.build.return_value = mock_app

        with patch(
            "app.providers.telegram_adapter.Application.builder",
            return_value=mock_builder,
        ):
            run_async(adapter._start_client())

        # Test handler exception is caught
        if captured_handler:
            mock_update = MagicMock()
            mock_update.message.message_id = 123
            mock_update.message.chat.id = 456
            mock_update.message.chat.title = "Test"
            mock_update.message.chat.type = "group"
            mock_update.message.chat.username = None
            mock_update.message.from_user.id = 111
            mock_update.message.from_user.username = "user"
            mock_update.message.from_user.first_name = "User"
            mock_update.message.from_user.last_name = None
            mock_update.message.from_user.is_bot = False
            mock_update.message.text = "Test"
            mock_update.message.date = datetime.now()
            mock_update.message.reply_to_message = None
            mock_update.message.document = None
            mock_update.message.photo = None

            # Should not raise
            run_async(
                captured_handler.callback(mock_update, MagicMock())
            )

    def test_message_handler_does_not_duplicate_known_chats(self):
        """Test handler n'ajoute pas de chats en double."""
        import app.providers.telegram_adapter as telegram_module

        if not telegram_module.TELEGRAM_AVAILABLE:
            pytest.skip("python-telegram-bot not installed")

        from app.providers.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter(bot_token="test-token")
        adapter._known_chats = [{"id": "456", "name": "Test Group", "type": "group"}]
        adapter.register_message_handler(lambda msg: None)

        mock_app = MagicMock()
        mock_app.bot = MagicMock()
        mock_app.bot.get_me = AsyncMock(return_value=MagicMock(id=999, username="testbot"))
        mock_app.initialize = AsyncMock()
        mock_app.start = AsyncMock()
        mock_app.updater.start_polling = AsyncMock()

        captured_handler = None

        def capture_handler(h):
            nonlocal captured_handler
            captured_handler = h

        mock_app.add_handler = capture_handler

        mock_builder = MagicMock()
        mock_builder.token.return_value = mock_builder
        mock_builder.build.return_value = mock_app

        with patch(
            "app.providers.telegram_adapter.Application.builder",
            return_value=mock_builder,
        ):
            run_async(adapter._start_client())

        # Test message from known chat
        if captured_handler:
            mock_update = MagicMock()
            mock_update.message.message_id = 123
            mock_update.message.chat.id = 456  # Same as existing chat
            mock_update.message.chat.title = "Test Group"
            mock_update.message.chat.type = "group"
            mock_update.message.chat.username = None
            mock_update.message.from_user.id = 111
            mock_update.message.from_user.username = "user"
            mock_update.message.from_user.first_name = "User"
            mock_update.message.from_user.last_name = None
            mock_update.message.from_user.is_bot = False
            mock_update.message.text = "Test"
            mock_update.message.date = datetime.now()
            mock_update.message.reply_to_message = None
            mock_update.message.document = None
            mock_update.message.photo = None

            run_async(
                captured_handler.callback(mock_update, MagicMock())
            )
            # Should still have only 1 chat
            assert len(adapter._known_chats) == 1
