"""
Tests for Discord API endpoints.
"""
import pytest
from unittest.mock import patch, MagicMock
from app.api.app import create_app
from app.discord_integration import DiscordMessage


@pytest.fixture
def client():
    """Create test client."""
    app = create_app({"TESTING": True})
    with app.test_client() as client:
        yield client


@pytest.fixture
def mock_discord_bot():
    """Mock the Discord bot.

    Mocke aussi _resolve_account_id_for_user (F-11 multi-tenant scoping
    ajouté 2026-04-29) — sans ça, en l'absence de multi_accounts.json,
    le route retourne early count=0 sans appeler get_discord_bot. Sur
    self-hosted runner Hetzner, le user gh-runner n'a pas de
    multi_accounts.json → bug. Le mock retourne un account_id stable
    pour découpler les tests de l'environnement.
    """
    with patch("app.api.discord.get_discord_bot") as mock_bot, \
         patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=1):
        bot = MagicMock()
        bot.history = []
        bot.is_configured.return_value = True
        bot.config.webhook_url = "https://discord.com/webhook"
        bot.config.bot_name = "Agentys Bot"
        bot.config.avatar_url = None
        # F-04 (audit 2026-04-29): respond_to_message routes via
        # _get_outbound_discord_adapter(bot), which selects a per-tenant
        # adapter when bot.config.bot_token is set. MagicMock auto-creates
        # this attribute as a truthy MagicMock (not None), forcing the code
        # into the tenant branch and trying to instantiate a real
        # DiscordAdapter — which fails (`discord.py non disponible`) and
        # makes the test fall through with sent=False. Pin to "" so the
        # function falls back to get_discord_adapter() which the tests patch.
        bot.config.bot_token = ""
        bot.get_stats.return_value = {
            "total_messages": 0,
            "pending_messages": 0,
            "responded_messages": 0,
            "open_tickets": 0,
        }
        mock_bot.return_value = bot
        yield bot


class TestListDiscordMessages:
    """Tests for GET /api/discord/messages."""

    def test_empty_list(self, client, mock_discord_bot):
        """Returns empty list when no messages."""
        response = client.get("/api/discord/messages")
        assert response.status_code == 200
        data = response.get_json()
        assert data["count"] == 0
        assert data["messages"] == []

    def test_list_with_messages(self, client, mock_discord_bot):
        """Returns messages when available."""
        msg = DiscordMessage(
            id="msg-1",
            channel_id="channel-1",
            author_id="user-1",
            author_name="TestUser",
            content="Hello world",
            metadata={"channel_name": "general", "guild_id": "guild-1"},
        )
        mock_discord_bot.history = [msg]

        response = client.get("/api/discord/messages")
        assert response.status_code == 200
        data = response.get_json()
        assert data["count"] == 1
        assert data["messages"][0]["id"] == "msg-1"
        assert data["messages"][0]["channel"] == "discord"
        assert data["messages"][0]["sender_name"] == "TestUser"
        assert data["messages"][0]["content"] == "Hello world"

    def test_filter_pending_only(self, client, mock_discord_bot):
        """Filters responded messages when pending_only=true."""
        msg1 = DiscordMessage(
            id="msg-1",
            channel_id="ch-1",
            author_id="u-1",
            author_name="User1",
            content="Pending",
            responded=False,
        )
        msg2 = DiscordMessage(
            id="msg-2",
            channel_id="ch-1",
            author_id="u-2",
            author_name="User2",
            content="Responded",
            responded=True,
        )
        mock_discord_bot.history = [msg1, msg2]

        response = client.get("/api/discord/messages?pending_only=true")
        assert response.status_code == 200
        data = response.get_json()
        assert data["count"] == 1
        assert data["messages"][0]["id"] == "msg-1"

    def test_include_all_messages(self, client, mock_discord_bot):
        """Returns all messages when pending_only=false."""
        msg1 = DiscordMessage(
            id="msg-1",
            channel_id="ch-1",
            author_id="u-1",
            author_name="User1",
            content="Pending",
            responded=False,
        )
        msg2 = DiscordMessage(
            id="msg-2",
            channel_id="ch-1",
            author_id="u-2",
            author_name="User2",
            content="Responded",
            responded=True,
        )
        mock_discord_bot.history = [msg1, msg2]

        response = client.get("/api/discord/messages?pending_only=false")
        assert response.status_code == 200
        data = response.get_json()
        assert data["count"] == 2


class TestGetDiscordMessage:
    """Tests for GET /api/discord/messages/<id>."""

    def test_message_found(self, client, mock_discord_bot):
        """Returns message when found."""
        msg = DiscordMessage(
            id="msg-123",
            channel_id="ch-1",
            author_id="u-1",
            author_name="TestUser",
            content="Test content",
        )
        mock_discord_bot.history = [msg]

        response = client.get("/api/discord/messages/msg-123")
        assert response.status_code == 200
        data = response.get_json()
        assert data["id"] == "msg-123"
        assert data["content"] == "Test content"

    def test_message_not_found(self, client, mock_discord_bot):
        """Returns 404 when message not found."""
        response = client.get("/api/discord/messages/nonexistent")
        assert response.status_code == 404
        data = response.get_json()
        assert "error" in data


class TestRespondToMessage:
    """Tests for POST /api/discord/messages/<id>/respond."""

    def test_respond_success(self, client, mock_discord_bot):
        """Successfully responds to a message."""
        msg = DiscordMessage(
            id="msg-1",
            channel_id="ch-1",
            author_id="u-1",
            author_name="User",
            content="Question",
            responded=False,
        )
        mock_discord_bot.history = [msg]

        response = client.post(
            "/api/discord/messages/msg-1/respond",
            json={"content": "Answer"},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["response_content"] == "Answer"

    def test_respond_message_not_found(self, client, mock_discord_bot):
        """Returns 404 for nonexistent message."""
        response = client.post(
            "/api/discord/messages/nonexistent/respond",
            json={"content": "Answer"},
        )
        assert response.status_code == 404

    def test_respond_missing_content(self, client, mock_discord_bot):
        """Returns 400 when content is missing."""
        msg = DiscordMessage(
            id="msg-1",
            channel_id="ch-1",
            author_id="u-1",
            author_name="User",
            content="Question",
        )
        mock_discord_bot.history = [msg]

        response = client.post(
            "/api/discord/messages/msg-1/respond",
            json={},
        )
        assert response.status_code == 400

    def test_respond_empty_content(self, client, mock_discord_bot):
        """Returns 400 when content is empty."""
        msg = DiscordMessage(
            id="msg-1",
            channel_id="ch-1",
            author_id="u-1",
            author_name="User",
            content="Question",
        )
        mock_discord_bot.history = [msg]

        response = client.post(
            "/api/discord/messages/msg-1/respond",
            json={"content": "   "},
        )
        assert response.status_code == 400


class TestRespondToMessageWithSend:
    """Tests for POST /api/discord/messages/<id>/respond with actual sending."""

    def test_respond_sends_via_adapter(self, client, mock_discord_bot):
        """Responds to a message and sends via Discord adapter."""
        msg = DiscordMessage(
            id="msg-1",
            channel_id="ch-123",
            author_id="u-1",
            author_name="User",
            content="Question",
            responded=False,
            metadata={"guild_id": "guild-1"},
        )
        mock_discord_bot.history = [msg]

        with patch("app.api.discord.get_discord_adapter") as mock_adapter:
            adapter = MagicMock()
            adapter.is_connected.return_value = True
            adapter.send_message.return_value = "sent-msg-id-123"
            mock_adapter.return_value = adapter

            response = client.post(
                "/api/discord/messages/msg-1/respond",
                json={"content": "My answer", "send": True},
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data["success"] is True
            assert data["sent"] is True
            assert data["sent_message_id"] == "sent-msg-id-123"
            adapter.send_message.assert_called_once_with(
                "ch-123", "My answer", reply_to_id="msg-1"
            )

    def test_respond_send_fails_gracefully(self, client, mock_discord_bot):
        """Handles send failure gracefully."""
        msg = DiscordMessage(
            id="msg-1",
            channel_id="ch-123",
            author_id="u-1",
            author_name="User",
            content="Question",
            responded=False,
        )
        mock_discord_bot.history = [msg]

        with patch("app.api.discord.get_discord_adapter") as mock_adapter:
            adapter = MagicMock()
            adapter.is_connected.return_value = True
            adapter.send_message.return_value = None  # Échec
            mock_adapter.return_value = adapter

            response = client.post(
                "/api/discord/messages/msg-1/respond",
                json={"content": "My answer", "send": True},
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data["success"] is True
            assert data["sent"] is False
            assert "error" in data

    def test_respond_without_send_flag(self, client, mock_discord_bot):
        """Does not send when send=False."""
        msg = DiscordMessage(
            id="msg-1",
            channel_id="ch-123",
            author_id="u-1",
            author_name="User",
            content="Question",
            responded=False,
        )
        mock_discord_bot.history = [msg]

        response = client.post(
            "/api/discord/messages/msg-1/respond",
            json={"content": "My answer", "send": False},
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data.get("sent") is False or "sent" not in data

    def test_respond_adapter_not_connected(self, client, mock_discord_bot):
        """Handles adapter not connected."""
        msg = DiscordMessage(
            id="msg-1",
            channel_id="ch-123",
            author_id="u-1",
            author_name="User",
            content="Question",
            responded=False,
        )
        mock_discord_bot.history = [msg]

        with patch("app.api.discord.get_discord_adapter") as mock_adapter:
            adapter = MagicMock()
            adapter.is_connected.return_value = False
            mock_adapter.return_value = adapter

            response = client.post(
                "/api/discord/messages/msg-1/respond",
                json={"content": "My answer", "send": True},
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data["success"] is True
            assert data["sent"] is False
            adapter.send_message.assert_not_called()


class TestSkipMessage:
    """Tests for POST /api/discord/messages/<id>/skip."""

    def test_skip_success(self, client, mock_discord_bot):
        """Successfully skips a message."""
        msg = DiscordMessage(
            id="msg-1",
            channel_id="ch-1",
            author_id="u-1",
            author_name="User",
            content="Question",
            responded=False,
        )
        mock_discord_bot.history = [msg]

        response = client.post("/api/discord/messages/msg-1/skip")
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True

    def test_skip_not_found(self, client, mock_discord_bot):
        """Returns 404 for nonexistent message."""
        response = client.post("/api/discord/messages/nonexistent/skip")
        assert response.status_code == 404


class TestDiscordConfig:
    """Tests for GET /api/discord/config."""

    def test_get_config(self, client, mock_discord_bot):
        """Returns bot configuration."""
        response = client.get("/api/discord/config")
        assert response.status_code == 200
        data = response.get_json()
        assert data["configured"] is True
        assert data["bot_name"] == "Agentys Bot"


class TestDiscordStats:
    """Tests for GET /api/discord/stats."""

    def test_get_stats(self, client, mock_discord_bot):
        """Returns statistics."""
        response = client.get("/api/discord/stats")
        assert response.status_code == 200
        data = response.get_json()
        assert "total_messages" in data
        assert "pending_messages" in data
