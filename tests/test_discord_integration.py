# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour l'intégration Discord.

pytest tests/test_discord_integration.py -v
"""

import pytest
import tempfile
import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.discord_integration import (
    MessageType,
    EmbedColor,
    DiscordConfig,
    DiscordMessage,
    DiscordEmbed,
    SupportTicket,
    DiscordBot,
    get_discord_bot
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def temp_discord_dir():
    """Crée un répertoire temporaire pour les tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        # Patch le répertoire de données
        with patch("app.discord_integration.DISCORD_DATA_DIR", tmpdir):
            yield tmpdir


@pytest.fixture
def discord_bot(temp_discord_dir):
    """Crée un bot avec un répertoire temporaire."""
    bot = DiscordBot()
    bot.config_file = temp_discord_dir / "config.json"
    bot.tickets_file = temp_discord_dir / "tickets.json"
    bot.history_file = temp_discord_dir / "history.json"
    return bot


@pytest.fixture
def configured_bot(discord_bot):
    """Bot configuré avec un webhook."""
    discord_bot.configure(webhook_url="https://discord.com/api/webhooks/test")
    return discord_bot


@pytest.fixture
def sample_message():
    """Exemple de message Discord."""
    return DiscordMessage(
        id="msg_001",
        channel_id="channel_123",
        author_id="user_456",
        author_name="Test User",
        content="Hello, I need help!"
    )


# ============================================================================
# TESTS ENUMS
# ============================================================================

class TestEnums:
    """Tests pour les enums."""

    def test_message_type_values(self):
        """Test les valeurs des types de message."""
        assert MessageType.NOTIFICATION.value == "notification"
        assert MessageType.SUPPORT_REQUEST.value == "support_request"
        assert MessageType.ALERT.value == "alert"

    def test_embed_color_values(self):
        """Test les couleurs d'embed."""
        assert EmbedColor.SUCCESS.value == 0x00FF00
        assert EmbedColor.ERROR.value == 0xFF0000
        assert EmbedColor.DEFAULT.value == 0x7289DA


# ============================================================================
# TESTS DATA CLASSES
# ============================================================================

class TestDataClasses:
    """Tests pour les dataclasses."""

    def test_discord_config_defaults(self):
        """Test config par défaut."""
        config = DiscordConfig()
        assert config.webhook_url is None
        assert config.bot_token is None
        assert config.enabled is True
        assert config.language == "fr"

    def test_discord_message_creation(self, sample_message):
        """Test création d'un message."""
        assert sample_message.id == "msg_001"
        assert sample_message.author_name == "Test User"
        assert sample_message.responded is False

    def test_discord_embed_to_dict(self):
        """Test conversion embed en dict."""
        embed = DiscordEmbed(
            title="Test Title",
            description="Test description",
            color=EmbedColor.SUCCESS.value,
            fields=[{"name": "Field1", "value": "Value1"}]
        )
        d = embed.to_dict()
        assert d["title"] == "Test Title"
        assert d["description"] == "Test description"
        assert d["color"] == EmbedColor.SUCCESS.value
        assert len(d["fields"]) == 1

    def test_support_ticket_defaults(self):
        """Test valeurs par défaut d'un ticket."""
        ticket = SupportTicket(
            id="ticket_001",
            channel_id="channel_123",
            user_id="user_456",
            user_name="Test User",
            subject="Help needed"
        )
        assert ticket.status == "open"
        assert ticket.priority == "normal"
        assert ticket.messages == []


# ============================================================================
# TESTS DISCORD BOT - CONFIGURATION
# ============================================================================

class TestDiscordBotConfiguration:
    """Tests pour la configuration du bot."""

    def test_bot_creation(self, discord_bot):
        """Test création du bot."""
        assert discord_bot is not None
        assert discord_bot.config is not None

    def test_is_not_configured_initially(self, discord_bot):
        """Test que le bot n'est pas configuré initialement."""
        assert not discord_bot.is_configured()

    def test_configure_webhook(self, discord_bot):
        """Test configuration du webhook."""
        discord_bot.configure(
            webhook_url="https://discord.com/api/webhooks/test"
        )
        assert discord_bot.config.webhook_url == "https://discord.com/api/webhooks/test"
        assert discord_bot.is_configured()

    def test_configure_multiple_options(self, discord_bot):
        """Test configuration de plusieurs options."""
        discord_bot.configure(
            webhook_url="https://test.webhook",
            guild_id="guild_123",
            support_channel_id="channel_456",
            enabled=True
        )
        assert discord_bot.config.guild_id == "guild_123"
        assert discord_bot.config.support_channel_id == "channel_456"

    def test_configuration_persistence(self, temp_discord_dir):
        """Test persistance de la configuration."""
        # Créer et configurer un bot
        bot1 = DiscordBot()
        bot1.config_file = temp_discord_dir / "config.json"
        bot1.configure(webhook_url="https://test.webhook")

        # Créer un nouveau bot
        bot2 = DiscordBot()
        bot2.config_file = temp_discord_dir / "config.json"
        bot2._load()

        assert bot2.config.webhook_url == "https://test.webhook"


# ============================================================================
# TESTS NOTIFICATIONS
# ============================================================================

class TestNotifications:
    """Tests pour les notifications."""

    def test_send_notification_not_configured(self, discord_bot):
        """Test envoi notification sans configuration."""
        result = discord_bot.send_notification("Test message")
        assert result is False

    def test_send_notification_disabled(self, configured_bot):
        """Test envoi notification désactivé."""
        configured_bot.config.enabled = False
        result = configured_bot.send_notification("Test message")
        assert result is False
        configured_bot.config.enabled = True

    @patch("urllib.request.urlopen")
    def test_send_notification_success(self, mock_urlopen, configured_bot):
        """Test envoi notification avec succès."""
        mock_response = MagicMock()
        mock_response.status = 204
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        result = configured_bot.send_notification(
            message="Test notification",
            title="Test Title"
        )

        assert result is True
        assert len(configured_bot.history) == 1

    @patch("urllib.request.urlopen")
    def test_send_notification_with_fields(self, mock_urlopen, configured_bot):
        """Test envoi notification avec champs."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        result = configured_bot.send_notification(
            message="Test",
            fields=[{"name": "Field1", "value": "Value1"}]
        )

        assert result is True

    @patch("urllib.request.urlopen")
    def test_send_alert(self, mock_urlopen, configured_bot):
        """Test envoi d'alerte."""
        mock_response = MagicMock()
        mock_response.status = 204
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        result = configured_bot.send_alert("Critical error!", severity="critical")

        assert result is True

    @patch("urllib.request.urlopen")
    def test_send_draft_created(self, mock_urlopen, configured_bot):
        """Test notification de création de brouillon."""
        mock_response = MagicMock()
        mock_response.status = 204
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        result = configured_bot.send_draft_created(
            subject="Re: Question",
            recipient="client@example.com",
            category="NORMAL",
            confidence=0.85
        )

        assert result is True

    @patch("urllib.request.urlopen")
    def test_send_followup_sent(self, mock_urlopen, configured_bot):
        """Test notification de follow-up."""
        mock_response = MagicMock()
        mock_response.status = 204
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        result = configured_bot.send_followup_sent(
            subject="Re: Relance",
            recipient="client@example.com",
            days_since=3
        )

        assert result is True


# ============================================================================
# TESTS SUPPORT TICKETS
# ============================================================================

class TestSupportTickets:
    """Tests pour les tickets de support."""

    @patch("urllib.request.urlopen")
    def test_create_support_ticket(self, mock_urlopen, configured_bot):
        """Test création d'un ticket."""
        mock_response = MagicMock()
        mock_response.status = 204
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        ticket = configured_bot.create_support_ticket(
            user_id="user_123",
            user_name="Test User",
            subject="Need help",
            initial_message="I have a problem..."
        )

        assert ticket is not None
        assert ticket.id.startswith("ticket_")
        assert ticket.status == "open"
        assert len(ticket.messages) == 1

    def test_add_message_to_ticket(self, discord_bot):
        """Test ajout de message à un ticket."""
        # Créer un ticket manuellement
        ticket = SupportTicket(
            id="ticket_001",
            channel_id="channel_123",
            user_id="user_456",
            user_name="Test User",
            subject="Help"
        )
        discord_bot.tickets["ticket_001"] = ticket

        message = discord_bot.add_message_to_ticket(
            ticket_id="ticket_001",
            author_id="user_456",
            author_name="Test User",
            content="Additional info..."
        )

        assert message is not None
        assert len(discord_bot.tickets["ticket_001"].messages) == 1

    def test_add_message_ticket_not_found(self, discord_bot):
        """Test ajout message à ticket inexistant."""
        message = discord_bot.add_message_to_ticket(
            ticket_id="nonexistent",
            author_id="user_123",
            author_name="User",
            content="Test"
        )

        assert message is None

    def test_resolve_ticket(self, discord_bot):
        """Test résolution d'un ticket."""
        # Créer un ticket
        ticket = SupportTicket(
            id="ticket_001",
            channel_id="channel_123",
            user_id="user_456",
            user_name="Test User",
            subject="Help"
        )
        discord_bot.tickets["ticket_001"] = ticket

        result = discord_bot.resolve_ticket("ticket_001", "Issue resolved!")

        assert result is True
        assert discord_bot.tickets["ticket_001"].status == "resolved"
        assert discord_bot.tickets["ticket_001"].resolved_at is not None

    def test_resolve_ticket_not_found(self, discord_bot):
        """Test résolution ticket inexistant."""
        result = discord_bot.resolve_ticket("nonexistent")
        assert result is False

    def test_get_ticket(self, discord_bot):
        """Test récupération d'un ticket."""
        ticket = SupportTicket(
            id="ticket_001",
            channel_id="channel_123",
            user_id="user_456",
            user_name="Test User",
            subject="Help"
        )
        discord_bot.tickets["ticket_001"] = ticket

        retrieved = discord_bot.get_ticket("ticket_001")
        assert retrieved is not None
        assert retrieved.id == "ticket_001"

    def test_get_ticket_not_found(self, discord_bot):
        """Test récupération ticket inexistant."""
        retrieved = discord_bot.get_ticket("nonexistent")
        assert retrieved is None

    def test_get_open_tickets(self, discord_bot):
        """Test récupération des tickets ouverts."""
        discord_bot.tickets["t1"] = SupportTicket(
            id="t1", channel_id="c1", user_id="u1",
            user_name="User1", subject="S1", status="open"
        )
        discord_bot.tickets["t2"] = SupportTicket(
            id="t2", channel_id="c2", user_id="u2",
            user_name="User2", subject="S2", status="resolved"
        )
        discord_bot.tickets["t3"] = SupportTicket(
            id="t3", channel_id="c3", user_id="u3",
            user_name="User3", subject="S3", status="in_progress"
        )

        open_tickets = discord_bot.get_open_tickets()
        assert len(open_tickets) == 2

    def test_get_user_tickets(self, discord_bot):
        """Test récupération des tickets d'un utilisateur."""
        discord_bot.tickets["t1"] = SupportTicket(
            id="t1", channel_id="c1", user_id="user_123",
            user_name="User", subject="S1"
        )
        discord_bot.tickets["t2"] = SupportTicket(
            id="t2", channel_id="c2", user_id="user_123",
            user_name="User", subject="S2"
        )
        discord_bot.tickets["t3"] = SupportTicket(
            id="t3", channel_id="c3", user_id="other_user",
            user_name="Other", subject="S3"
        )

        user_tickets = discord_bot.get_user_tickets("user_123")
        assert len(user_tickets) == 2


# ============================================================================
# TESTS MESSAGE HANDLERS
# ============================================================================

class TestMessageHandlers:
    """Tests pour les handlers de messages."""

    def test_register_message_handler(self, discord_bot):
        """Test enregistrement d'un handler."""
        async def handler(msg):
            return "Response"

        discord_bot.register_message_handler(handler)
        assert len(discord_bot.message_handlers) == 1

    def test_handle_incoming_message(self, discord_bot, sample_message):
        """Test gestion d'un message entrant."""
        async def handler(msg):
            return f"Reply to: {msg.content}"

        discord_bot.register_message_handler(handler)

        response = asyncio.run(
            discord_bot.handle_incoming_message(sample_message)
        )

        assert response == "Reply to: Hello, I need help!"
        assert len(discord_bot.history) == 1

    def test_handle_message_no_handlers(self, discord_bot, sample_message):
        """Test gestion message sans handlers."""
        response = asyncio.run(
            discord_bot.handle_incoming_message(sample_message)
        )
        assert response is None

    def test_handle_message_handler_returns_none(self, discord_bot, sample_message):
        """Test handler qui retourne None."""
        async def handler(msg):
            return None

        discord_bot.register_message_handler(handler)

        response = asyncio.run(
            discord_bot.handle_incoming_message(sample_message)
        )
        assert response is None


# ============================================================================
# TESTS STATS
# ============================================================================

class TestStats:
    """Tests pour les statistiques."""

    def test_stats_empty(self, discord_bot):
        """Test stats sur bot vide."""
        stats = discord_bot.get_stats()

        assert stats["total_tickets"] == 0
        assert stats["open_tickets"] == 0
        assert stats["total_messages"] == 0
        assert stats["configured"] is False

    def test_stats_with_data(self, discord_bot):
        """Test stats avec données."""
        discord_bot.configure(webhook_url="https://test.webhook")

        discord_bot.tickets["t1"] = SupportTicket(
            id="t1", channel_id="c1", user_id="u1",
            user_name="User1", subject="S1", status="open"
        )
        discord_bot.tickets["t2"] = SupportTicket(
            id="t2", channel_id="c2", user_id="u2",
            user_name="User2", subject="S2", status="resolved"
        )

        discord_bot.history.append(DiscordMessage(
            id="m1", channel_id="c1", author_id="u1",
            author_name="User1", content="Test"
        ))

        stats = discord_bot.get_stats()

        assert stats["total_tickets"] == 2
        assert stats["open_tickets"] == 1
        assert stats["resolved_tickets"] == 1
        assert stats["total_messages"] == 1
        assert stats["configured"] is True
        assert stats["enabled"] is True


# ============================================================================
# TESTS SINGLETON
# ============================================================================

class TestSingleton:
    """Tests pour le singleton."""

    def test_get_discord_bot_singleton(self):
        """Test que get_discord_bot retourne un singleton."""
        bot1 = get_discord_bot()
        bot2 = get_discord_bot()

        assert bot1 is bot2

    def test_discord_bot_type(self):
        """Test le type du bot."""
        bot = get_discord_bot()
        assert isinstance(bot, DiscordBot)


# ============================================================================
# TESTS EDGE CASES
# ============================================================================

class TestEdgeCases:
    """Tests pour les cas limites."""

    def test_unicode_in_message(self, discord_bot):
        """Test message avec Unicode."""
        message = DiscordMessage(
            id="msg_001",
            channel_id="channel_123",
            author_id="user_456",
            author_name="用户",
            content="测试消息 🎉"
        )

        discord_bot.history.append(message)
        discord_bot._save()

        assert len(discord_bot.history) == 1

    def test_very_long_message(self, discord_bot):
        """Test message très long."""
        long_content = "Lorem ipsum " * 1000
        message = DiscordMessage(
            id="msg_001",
            channel_id="channel_123",
            author_id="user_456",
            author_name="User",
            content=long_content
        )

        discord_bot.history.append(message)
        assert discord_bot.history[0].content == long_content

    @patch("urllib.request.urlopen")
    def test_webhook_error_handling(self, mock_urlopen, configured_bot):
        """Test gestion erreur webhook."""
        mock_urlopen.side_effect = Exception("Network error")

        result = configured_bot.send_notification("Test")
        assert result is False

    def test_empty_ticket_subject(self, discord_bot):
        """Test ticket avec sujet vide."""
        ticket = SupportTicket(
            id="ticket_001",
            channel_id="channel_123",
            user_id="user_456",
            user_name="User",
            subject=""
        )
        discord_bot.tickets["ticket_001"] = ticket

        assert discord_bot.tickets["ticket_001"].subject == ""


# ============================================================================
# TESTS PERSISTENCE
# ============================================================================

class TestPersistence:
    """Tests pour la persistance."""

    def test_tickets_persistence(self, temp_discord_dir):
        """Test persistance des tickets."""
        bot1 = DiscordBot()
        bot1.tickets_file = temp_discord_dir / "tickets.json"
        bot1.tickets["t1"] = SupportTicket(
            id="t1", channel_id="c1", user_id="u1",
            user_name="User1", subject="S1"
        )
        bot1._save()

        bot2 = DiscordBot()
        bot2.tickets_file = temp_discord_dir / "tickets.json"
        bot2._load()

        assert "t1" in bot2.tickets
        assert bot2.tickets["t1"].subject == "S1"

    def test_history_limit(self, discord_bot):
        """Test limite de l'historique."""
        for i in range(600):
            discord_bot.history.append(DiscordMessage(
                id=f"msg_{i}",
                channel_id="c1",
                author_id="u1",
                author_name="User",
                content=f"Message {i}"
            ))

        discord_bot._save()

        # L'historique devrait être limité à 500
        assert len(discord_bot.history) <= 500
