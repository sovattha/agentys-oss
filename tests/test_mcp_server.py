# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour le serveur MCP.
"""

import pytest

from app.interfaces.email_provider import StandardEmail

# Skip tous les tests si pytest-asyncio n'est pas installé
pytest_asyncio = pytest.importorskip("pytest_asyncio")


class TestMCPHandlers:
    """Tests pour les handlers MCP."""

    @pytest.fixture
    def mock_emails(self):
        """Emails de test pour les handlers."""
        return [
            StandardEmail(
                id="msg-100",
                sender="test@example.com",
                sender_name="Test User",
                to=["recipient@example.com"],
                subject="Test Subject",
                body="Test body content",
                provider_source="mock"
            )
        ]

    @pytest.mark.asyncio
    async def test_list_emails_handler(self, mock_provider, mock_emails):
        """Test handler list_emails."""
        # Ajouter les emails au provider
        for email in mock_emails:
            mock_provider._emails[email.id] = email

        # Importer le handler
        from agentys_mcp.server import _handle_list_emails

        result = await _handle_list_emails(mock_provider, {"limit": 10})

        assert len(result) == 1
        assert "email(s) non lu(s)" in result[0].text

    @pytest.mark.asyncio
    async def test_list_emails_empty(self, empty_provider):
        """Test handler list_emails sans emails."""
        from agentys_mcp.server import _handle_list_emails

        result = await _handle_list_emails(empty_provider, {"limit": 10})

        assert "Aucun email non lu" in result[0].text

    @pytest.mark.asyncio
    async def test_get_email_handler(self, mock_provider):
        """Test handler get_email."""
        from agentys_mcp.server import _handle_get_email

        result = await _handle_get_email(
            mock_provider,
            {"message_id": "msg-001"}
        )

        assert len(result) == 1
        assert "alice@example.com" in result[0].text

    @pytest.mark.asyncio
    async def test_get_email_not_found(self, mock_provider):
        """Test handler get_email avec ID inexistant."""
        from agentys_mcp.server import _handle_get_email

        result = await _handle_get_email(
            mock_provider,
            {"message_id": "non-existent"}
        )

        assert "non trouvé" in result[0].text

    @pytest.mark.asyncio
    async def test_draft_reply_handler(self, mock_provider):
        """Test handler draft_reply."""
        from agentys_mcp.server import _handle_draft_reply

        result = await _handle_draft_reply(
            mock_provider,
            {
                "reply_to_id": "msg-001",
                "body": "Thank you for your message!"
            }
        )

        assert "Brouillon créé" in result[0].text
        assert "Re:" in result[0].text

    @pytest.mark.asyncio
    async def test_draft_reply_original_not_found(self, mock_provider):
        """Test handler draft_reply avec email original inexistant."""
        from agentys_mcp.server import _handle_draft_reply

        result = await _handle_draft_reply(
            mock_provider,
            {
                "reply_to_id": "non-existent",
                "body": "Reply"
            }
        )

        assert "non trouvé" in result[0].text

    @pytest.mark.asyncio
    async def test_send_email_handler(self, mock_provider, monkeypatch):
        """Test handler send_email.

        Audit AUX-006 : le MCP stdio n'a pas d'auth per-caller, donc
        `_handle_send_email` refuse par défaut sauf si
        `AGENTYS_MCP_ALLOW_SEND=true`. Le test active le flag pour
        valider le happy path.
        """
        monkeypatch.setenv("AGENTYS_MCP_ALLOW_SEND", "true")
        from agentys_mcp.server import _handle_send_email

        result = await _handle_send_email(
            mock_provider,
            {
                "to": ["recipient@example.com"],
                "subject": "New Email",
                "body": "Email content"
            }
        )

        assert "envoyé avec succès" in result[0].text

    @pytest.mark.asyncio
    async def test_mark_read_handler(self, mock_provider):
        """Test handler mark_read."""
        from agentys_mcp.server import _handle_mark_read

        result = await _handle_mark_read(
            mock_provider,
            {"message_id": "msg-001"}
        )

        assert "marqué comme lu" in result[0].text

    @pytest.mark.asyncio
    async def test_mark_read_not_found(self, mock_provider):
        """Test handler mark_read avec ID inexistant."""
        from agentys_mcp.server import _handle_mark_read

        result = await _handle_mark_read(
            mock_provider,
            {"message_id": "non-existent"}
        )

        assert "Échec" in result[0].text


class TestMCPToolsDefinition:
    """Tests pour la définition des outils MCP."""

    @pytest.mark.asyncio
    async def test_list_tools_returns_all_tools(self):
        """Test que list_tools retourne tous les outils."""
        from agentys_mcp.server import list_tools

        tools = await list_tools()

        tool_names = [t.name for t in tools]
        assert "list_emails" in tool_names
        assert "get_email" in tool_names
        assert "draft_reply" in tool_names
        assert "send_email" in tool_names
        assert "mark_read" in tool_names

    @pytest.mark.asyncio
    async def test_tools_have_schemas(self):
        """Test que chaque outil a un schéma JSON valide."""
        from agentys_mcp.server import list_tools

        tools = await list_tools()

        for tool in tools:
            assert tool.inputSchema is not None
            assert "type" in tool.inputSchema
            assert tool.inputSchema["type"] == "object"
