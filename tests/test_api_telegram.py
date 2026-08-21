"""
Tests for Telegram API endpoints (app/api/telegram.py).

Coverage goal: 23% -> 80%+
Tested endpoints:
- GET /api/telegram/messages
- GET /api/telegram/messages/<id>
- POST /api/telegram/messages/<id>/suggest
- POST /api/telegram/messages/<id>/respond
- POST /api/telegram/messages/<id>/skip
- GET /api/telegram/config
- GET /api/telegram/stats
"""
import pytest
from unittest.mock import patch, MagicMock
from app.api.app import create_app
from app.telegram_integration import TelegramMessage


@pytest.fixture
def client():
    """Create test client."""
    app = create_app({"TESTING": True})
    with app.test_client() as client:
        yield client


@pytest.fixture
def mock_telegram_bot():
    """Mock the Telegram bot.

    Mocke aussi _resolve_account_id_for_user (F-11 multi-tenant scoping)
    — sans ça, en l'absence de multi_accounts.json, le route retourne
    early count=0 sans appeler get_telegram_bot. Sur self-hosted runner
    Hetzner le user gh-runner n'a pas ce fichier → bug. Le mock retourne
    un account_id stable pour découpler les tests de l'environnement.
    """
    with patch("app.api.telegram.get_telegram_bot") as mock_bot, \
         patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=1):
        bot = MagicMock()
        bot.history = []
        bot.is_configured.return_value = True
        bot.config.bot_token = "test-token-123"
        bot.config.bot_name = "AgentysTestBot"
        bot.config.notifications_chat_id = "chat-notify-1"
        bot.config.support_chat_id = "chat-support-1"
        bot.get_stats.return_value = {
            "total_messages": 0,
            "pending_messages": 0,
            "responded_messages": 0,
            "configured": True,
        }
        mock_bot.return_value = bot
        yield bot


def create_telegram_message(
    id: str = "msg-1",
    chat_id: str = "chat-1",
    author_id: str = "user-1",
    author_name: str = "TestUser",
    content: str = "Test message",
    responded: bool = False,
    response_content: str | None = None,
    metadata: dict | None = None,
) -> TelegramMessage:
    """Helper to create TelegramMessage instances."""
    return TelegramMessage(
        id=id,
        chat_id=chat_id,
        author_id=author_id,
        author_name=author_name,
        content=content,
        responded=responded,
        response_content=response_content,
        metadata=metadata or {},
    )


class TestListTelegramMessages:
    """Tests for GET /api/telegram/messages."""

    def test_empty_list(self, client, mock_telegram_bot):
        """Returns empty list when no messages."""
        response = client.get("/api/telegram/messages")
        assert response.status_code == 200
        data = response.get_json()
        assert data["count"] == 0
        assert data["messages"] == []

    def test_list_with_messages(self, client, mock_telegram_bot):
        """Returns messages when available."""
        msg = create_telegram_message(
            id="msg-1",
            chat_id="chat-1",
            author_id="user-1",
            author_name="TestUser",
            content="Hello from Telegram",
            metadata={"chat_type": "private"},
        )
        mock_telegram_bot.history = [msg]

        response = client.get("/api/telegram/messages")
        assert response.status_code == 200
        data = response.get_json()
        assert data["count"] == 1
        assert data["messages"][0]["id"] == "msg-1"
        assert data["messages"][0]["channel"] == "telegram"
        assert data["messages"][0]["sender_name"] == "TestUser"
        assert data["messages"][0]["content"] == "Hello from Telegram"
        assert data["messages"][0]["chat_id"] == "chat-1"
        assert data["messages"][0]["chat_type"] == "private"

    def test_filter_pending_only(self, client, mock_telegram_bot):
        """Filters responded messages when pending_only=true."""
        msg1 = create_telegram_message(
            id="msg-1",
            content="Pending message",
            responded=False,
        )
        msg2 = create_telegram_message(
            id="msg-2",
            content="Responded message",
            responded=True,
            response_content="Response",
        )
        mock_telegram_bot.history = [msg1, msg2]

        response = client.get("/api/telegram/messages?pending_only=true")
        assert response.status_code == 200
        data = response.get_json()
        assert data["count"] == 1
        assert data["messages"][0]["id"] == "msg-1"

    def test_include_all_messages(self, client, mock_telegram_bot):
        """Returns all messages when pending_only=false."""
        msg1 = create_telegram_message(id="msg-1", responded=False)
        msg2 = create_telegram_message(id="msg-2", responded=True)
        mock_telegram_bot.history = [msg1, msg2]

        response = client.get("/api/telegram/messages?pending_only=false")
        assert response.status_code == 200
        data = response.get_json()
        assert data["count"] == 2

    def test_limit_param(self, client, mock_telegram_bot):
        """Respects limit parameter."""
        messages = [create_telegram_message(id=f"msg-{i}") for i in range(10)]
        mock_telegram_bot.history = messages

        response = client.get("/api/telegram/messages?limit=5")
        assert response.status_code == 200
        data = response.get_json()
        assert data["count"] == 5

    def test_limit_clamped_to_minimum(self, client, mock_telegram_bot):
        """Limit is clamped to minimum of 1."""
        messages = [create_telegram_message(id=f"msg-{i}") for i in range(5)]
        mock_telegram_bot.history = messages

        response = client.get("/api/telegram/messages?limit=0")
        assert response.status_code == 200
        data = response.get_json()
        assert data["count"] == 1

    def test_limit_clamped_to_maximum(self, client, mock_telegram_bot):
        """Limit is clamped to maximum of 100."""
        messages = [create_telegram_message(id=f"msg-{i}") for i in range(150)]
        mock_telegram_bot.history = messages

        response = client.get("/api/telegram/messages?limit=200")
        assert response.status_code == 200
        data = response.get_json()
        assert data["count"] == 100


class TestGetTelegramMessage:
    """Tests for GET /api/telegram/messages/<id>."""

    def test_message_found(self, client, mock_telegram_bot):
        """Returns message when found."""
        msg = create_telegram_message(
            id="msg-123",
            chat_id="chat-42",
            author_name="JohnDoe",
            content="Find this message",
            metadata={"chat_type": "group"},
        )
        mock_telegram_bot.history = [msg]

        response = client.get("/api/telegram/messages/msg-123")
        assert response.status_code == 200
        data = response.get_json()
        assert data["id"] == "msg-123"
        assert data["channel"] == "telegram"
        assert data["sender_name"] == "JohnDoe"
        assert data["content"] == "Find this message"
        assert data["conversation_id"] == "chat-42"
        assert data["chat_type"] == "group"

    def test_message_not_found(self, client, mock_telegram_bot):
        """Returns 404 when message not found."""
        mock_telegram_bot.history = []

        response = client.get("/api/telegram/messages/nonexistent")
        assert response.status_code == 404
        data = response.get_json()
        assert "error" in data
        assert "not found" in data["error"].lower()

    def test_message_with_response(self, client, mock_telegram_bot):
        """Returns message with response details."""
        msg = create_telegram_message(
            id="msg-resp",
            responded=True,
            response_content="This is my response",
        )
        mock_telegram_bot.history = [msg]

        response = client.get("/api/telegram/messages/msg-resp")
        assert response.status_code == 200
        data = response.get_json()
        assert data["responded"] is True
        assert data["response_content"] == "This is my response"


class TestSuggestResponse:
    """Tests for POST /api/telegram/messages/<id>/suggest."""

    def test_suggest_message_not_found(self, client, mock_telegram_bot):
        """Returns 404 when message not found."""
        mock_telegram_bot.history = []

        response = client.post("/api/telegram/messages/nonexistent/suggest")
        assert response.status_code == 404
        data = response.get_json()
        assert "error" in data

    @patch("app.api.telegram.get_message_router")
    @patch("app.api.telegram.create_incoming_message")
    def test_suggest_success(
        self,
        mock_create_incoming,
        mock_get_router,
        client,
        mock_telegram_bot,
    ):
        """Returns suggestion for valid message."""
        msg = create_telegram_message(
            id="msg-suggest",
            content="Question about product",
            metadata={"chat_type": "private"},
        )
        mock_telegram_bot.history = [msg]

        mock_context = MagicMock()
        mock_context.final_decision = MagicMock()
        mock_context.final_decision.confidence = 0.95
        mock_context.final_decision.target_agent = "support"
        mock_context.final_decision.category = MagicMock()
        mock_context.final_decision.category.value = "support"

        mock_router = MagicMock()
        mock_router.route.return_value = mock_context
        mock_get_router.return_value = mock_router

        response = client.post("/api/telegram/messages/msg-suggest/suggest")
        assert response.status_code == 200
        data = response.get_json()
        assert data["message_id"] == "msg-suggest"
        assert "suggestion" in data
        assert data["suggestion"]["confidence"] == 0.95
        assert data["suggestion"]["agent_id"] == "support"
        assert data["suggestion"]["category"] == "support"

    @patch("app.api.telegram.get_message_router")
    @patch("app.api.telegram.create_incoming_message")
    def test_suggest_with_exception(
        self,
        mock_create_incoming,
        mock_get_router,
        client,
        mock_telegram_bot,
    ):
        """Returns 500 with error when router fails."""
        msg = create_telegram_message(id="msg-err", content="Error case")
        mock_telegram_bot.history = [msg]

        mock_router = MagicMock()
        mock_router.route.side_effect = Exception("Router failed")
        mock_get_router.return_value = mock_router

        response = client.post("/api/telegram/messages/msg-err/suggest")
        assert response.status_code == 500
        data = response.get_json()
        assert "error" in data
        assert data["suggestion"]["confidence"] == 0

    @patch("app.api.telegram.get_message_router")
    @patch("app.api.telegram.create_incoming_message")
    def test_suggest_without_final_decision(
        self,
        mock_create_incoming,
        mock_get_router,
        client,
        mock_telegram_bot,
    ):
        """Returns default values when no final decision."""
        msg = create_telegram_message(id="msg-no-decision", content="Test")
        mock_telegram_bot.history = [msg]

        mock_context = MagicMock()
        mock_context.final_decision = None

        mock_router = MagicMock()
        mock_router.route.return_value = mock_context
        mock_get_router.return_value = mock_router

        response = client.post("/api/telegram/messages/msg-no-decision/suggest")
        assert response.status_code == 200
        data = response.get_json()
        assert data["suggestion"]["confidence"] == 0.8
        assert data["suggestion"]["agent_id"] == "general"
        assert data["suggestion"]["category"] == "general"


class TestRespondToMessage:
    """Tests for POST /api/telegram/messages/<id>/respond."""

    def test_respond_missing_body(self, client, mock_telegram_bot):
        """Returns 400 when body is missing."""
        msg = create_telegram_message(id="msg-1")
        mock_telegram_bot.history = [msg]

        response = client.post(
            "/api/telegram/messages/msg-1/respond",
            content_type="application/json",
        )
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data

    def test_respond_missing_content(self, client, mock_telegram_bot):
        """Returns 400 when content is missing."""
        msg = create_telegram_message(id="msg-1")
        mock_telegram_bot.history = [msg]

        response = client.post(
            "/api/telegram/messages/msg-1/respond",
            json={"other_field": "value"},
        )
        assert response.status_code == 400
        data = response.get_json()
        assert "content" in data["error"]

    def test_respond_empty_content(self, client, mock_telegram_bot):
        """Returns 400 when content is empty."""
        msg = create_telegram_message(id="msg-1")
        mock_telegram_bot.history = [msg]

        response = client.post(
            "/api/telegram/messages/msg-1/respond",
            json={"content": "   "},
        )
        assert response.status_code == 400
        data = response.get_json()
        assert "empty" in data["error"].lower()

    def test_respond_message_not_found(self, client, mock_telegram_bot):
        """Returns 404 when message not found."""
        mock_telegram_bot.history = []

        response = client.post(
            "/api/telegram/messages/nonexistent/respond",
            json={"content": "Response text"},
        )
        assert response.status_code == 404
        data = response.get_json()
        assert "not found" in data["error"].lower()

    def test_respond_success_without_send(self, client, mock_telegram_bot):
        """Records response without sending when send=false."""
        msg = create_telegram_message(id="msg-resp", content="Original question")
        mock_telegram_bot.history = [msg]

        response = client.post(
            "/api/telegram/messages/msg-resp/respond",
            json={"content": "This is my response", "send": False},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["message_id"] == "msg-resp"
        assert data["response_content"] == "This is my response"
        assert "sent" not in data

        # Verify message was updated
        assert mock_telegram_bot.history[0].responded is True
        assert mock_telegram_bot.history[0].response_content == "This is my response"
        mock_telegram_bot._save.assert_called_once()

    @patch("app.api.telegram._get_outbound_telegram_adapter")
    def test_respond_with_send_success(
        self, mock_get_adapter, client, mock_telegram_bot
    ):
        """Sends response via Telegram when send=true."""
        msg = create_telegram_message(id="msg-send", chat_id="chat-123")
        mock_telegram_bot.history = [msg]

        mock_adapter = MagicMock()
        mock_adapter.is_connected.return_value = True
        mock_adapter.send_message.return_value = "sent-msg-456"
        mock_get_adapter.return_value = mock_adapter

        response = client.post(
            "/api/telegram/messages/msg-send/respond",
            json={"content": "Response to send", "send": True},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["sent"] is True
        assert data["sent_message_id"] == "sent-msg-456"

        mock_adapter.send_message.assert_called_once_with(
            "chat-123", "Response to send", reply_to_id="msg-send"
        )

    @patch("app.api.telegram._get_outbound_telegram_adapter")
    def test_respond_send_fails(self, mock_get_adapter, client, mock_telegram_bot):
        """Handles send failure gracefully."""
        msg = create_telegram_message(id="msg-fail", chat_id="chat-1")
        mock_telegram_bot.history = [msg]

        mock_adapter = MagicMock()
        mock_adapter.is_connected.return_value = True
        mock_adapter.send_message.return_value = None
        mock_get_adapter.return_value = mock_adapter

        response = client.post(
            "/api/telegram/messages/msg-fail/respond",
            json={"content": "Response", "send": True},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["sent"] is False
        assert "error" in data

    @patch("app.api.telegram._get_outbound_telegram_adapter")
    def test_respond_adapter_not_connected(
        self, mock_get_adapter, client, mock_telegram_bot
    ):
        """Handles adapter not connected."""
        msg = create_telegram_message(id="msg-nc", chat_id="chat-1")
        mock_telegram_bot.history = [msg]

        mock_adapter = MagicMock()
        mock_adapter.is_connected.return_value = False
        mock_get_adapter.return_value = mock_adapter

        response = client.post(
            "/api/telegram/messages/msg-nc/respond",
            json={"content": "Response", "send": True},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["sent"] is False
        assert "not connected" in data["error"].lower()

    @patch("app.api.telegram._get_outbound_telegram_adapter")
    def test_respond_adapter_none(self, mock_get_adapter, client, mock_telegram_bot):
        """Handles adapter being None."""
        msg = create_telegram_message(id="msg-none", chat_id="chat-1")
        mock_telegram_bot.history = [msg]

        mock_get_adapter.return_value = None

        response = client.post(
            "/api/telegram/messages/msg-none/respond",
            json={"content": "Response", "send": True},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["sent"] is False
        assert "not connected" in data["error"].lower()


class TestSkipMessage:
    """Tests for POST /api/telegram/messages/<id>/skip."""

    def test_skip_success(self, client, mock_telegram_bot):
        """Marks message as skipped."""
        msg = create_telegram_message(id="msg-skip")
        mock_telegram_bot.history = [msg]

        response = client.post("/api/telegram/messages/msg-skip/skip")
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["message_id"] == "msg-skip"

        # Verify message was updated
        assert mock_telegram_bot.history[0].responded is True
        assert mock_telegram_bot.history[0].response_content == "[SKIPPED]"
        mock_telegram_bot._save.assert_called_once()

    def test_skip_not_found(self, client, mock_telegram_bot):
        """Returns 404 when message not found."""
        mock_telegram_bot.history = []

        response = client.post("/api/telegram/messages/nonexistent/skip")
        assert response.status_code == 404
        data = response.get_json()
        assert "error" in data
        assert "not found" in data["error"].lower()

    def test_skip_updates_correct_message(self, client, mock_telegram_bot):
        """Skips only the targeted message."""
        msg1 = create_telegram_message(id="msg-1", content="First")
        msg2 = create_telegram_message(id="msg-2", content="Second")
        msg3 = create_telegram_message(id="msg-3", content="Third")
        mock_telegram_bot.history = [msg1, msg2, msg3]

        response = client.post("/api/telegram/messages/msg-2/skip")
        assert response.status_code == 200

        assert mock_telegram_bot.history[0].responded is False
        assert mock_telegram_bot.history[1].responded is True
        assert mock_telegram_bot.history[1].response_content == "[SKIPPED]"
        assert mock_telegram_bot.history[2].responded is False


class TestTelegramConfig:
    """Tests for GET /api/telegram/config."""

    def test_get_config_full(self, client, mock_telegram_bot):
        """Returns full config when all values set."""
        response = client.get("/api/telegram/config")
        assert response.status_code == 200
        data = response.get_json()
        assert data["configured"] is True
        assert data["bot_token_set"] is True
        assert data["bot_name"] == "AgentysTestBot"
        assert data["notifications_chat_id_set"] is True
        assert data["support_chat_id_set"] is True

    def test_get_config_minimal(self, client, mock_telegram_bot):
        """Returns config with minimal values."""
        mock_telegram_bot.is_configured.return_value = False
        mock_telegram_bot.config.bot_token = None
        mock_telegram_bot.config.bot_name = None
        mock_telegram_bot.config.notifications_chat_id = None
        mock_telegram_bot.config.support_chat_id = None

        response = client.get("/api/telegram/config")
        assert response.status_code == 200
        data = response.get_json()
        assert data["configured"] is False
        assert data["bot_token_set"] is False
        assert data["bot_name"] is None
        assert data["notifications_chat_id_set"] is False
        assert data["support_chat_id_set"] is False

    def test_get_config_partial(self, client, mock_telegram_bot):
        """Returns config with partial values."""
        mock_telegram_bot.is_configured.return_value = True
        mock_telegram_bot.config.bot_token = "token-123"
        mock_telegram_bot.config.bot_name = "PartialBot"
        mock_telegram_bot.config.notifications_chat_id = None
        mock_telegram_bot.config.support_chat_id = "support-chat"

        response = client.get("/api/telegram/config")
        assert response.status_code == 200
        data = response.get_json()
        assert data["configured"] is True
        assert data["bot_token_set"] is True
        assert data["bot_name"] == "PartialBot"
        assert data["notifications_chat_id_set"] is False
        assert data["support_chat_id_set"] is True


class TestTelegramStats:
    """Tests for GET /api/telegram/stats."""

    def test_get_stats(self, client, mock_telegram_bot):
        """Returns stats from bot."""
        mock_telegram_bot.get_stats.return_value = {
            "total_messages": 150,
            "pending_messages": 25,
            "responded_messages": 120,
            "skipped_messages": 5,
            "configured": True,
        }

        response = client.get("/api/telegram/stats")
        assert response.status_code == 200
        data = response.get_json()
        assert data["total_messages"] == 150
        assert data["pending_messages"] == 25
        assert data["responded_messages"] == 120
        assert data["skipped_messages"] == 5
        assert data["configured"] is True

    def test_get_stats_empty(self, client, mock_telegram_bot):
        """Returns empty stats when no messages."""
        mock_telegram_bot.get_stats.return_value = {
            "total_messages": 0,
            "pending_messages": 0,
            "responded_messages": 0,
        }

        response = client.get("/api/telegram/stats")
        assert response.status_code == 200
        data = response.get_json()
        assert data["total_messages"] == 0
        assert data["pending_messages"] == 0
        assert data["responded_messages"] == 0


class TestMessageToDict:
    """Tests for _message_to_dict helper function."""

    def test_basic_conversion(self, client, mock_telegram_bot):
        """Converts basic message fields correctly."""
        msg = create_telegram_message(
            id="convert-1",
            chat_id="chat-conv",
            author_id="author-conv",
            author_name="ConvertUser",
            content="Content to convert",
        )
        mock_telegram_bot.history = [msg]

        response = client.get("/api/telegram/messages/convert-1")
        assert response.status_code == 200
        data = response.get_json()
        assert data["id"] == "convert-1"
        assert data["channel"] == "telegram"
        assert data["sender_id"] == "author-conv"
        assert data["sender_name"] == "ConvertUser"
        assert data["content"] == "Content to convert"
        assert data["conversation_id"] == "chat-conv"
        assert data["has_attachments"] is False

    def test_conversion_with_metadata(self, client, mock_telegram_bot):
        """Converts message with metadata."""
        msg = create_telegram_message(
            id="meta-1",
            metadata={"chat_type": "supergroup", "extra": "data"},
        )
        mock_telegram_bot.history = [msg]

        response = client.get("/api/telegram/messages/meta-1")
        assert response.status_code == 200
        data = response.get_json()
        assert data["chat_type"] == "supergroup"

    def test_conversion_without_chat_type(self, client, mock_telegram_bot):
        """Handles message without chat_type in metadata."""
        msg = create_telegram_message(
            id="no-type",
            metadata={},
        )
        mock_telegram_bot.history = [msg]

        response = client.get("/api/telegram/messages/no-type")
        assert response.status_code == 200
        data = response.get_json()
        assert data["chat_type"] is None

    def test_conversion_with_response(self, client, mock_telegram_bot):
        """Converts responded message correctly."""
        msg = create_telegram_message(
            id="resp-msg",
            responded=True,
            response_content="My response text",
        )
        mock_telegram_bot.history = [msg]

        response = client.get("/api/telegram/messages/resp-msg")
        assert response.status_code == 200
        data = response.get_json()
        assert data["responded"] is True
        assert data["response_content"] == "My response text"
