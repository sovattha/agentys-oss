# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour l'interface EmailProvider et le MockProvider.
"""

import pytest
from app.interfaces.email_provider import EmailProvider, StandardEmail


class TestMockProvider:
    """Tests pour le MockEmailProvider (via conftest)."""

    def test_provider_name(self, mock_provider):
        """Test nom du provider."""
        assert mock_provider.provider_name == "mock"

    def test_authenticate(self, mock_provider):
        """Test authentification."""
        assert mock_provider.authenticate() is True
        assert mock_provider._authenticated is True

    def test_get_unread_messages(self, mock_provider):
        """Test récupération messages non lus."""
        emails = mock_provider.get_unread_messages()

        assert len(emails) == 3
        assert all(isinstance(e, StandardEmail) for e in emails)

    def test_get_unread_messages_with_limit(self, mock_provider):
        """Test limit sur get_unread_messages."""
        emails = mock_provider.get_unread_messages(limit=2)
        assert len(emails) == 2

    def test_get_unread_messages_empty(self, empty_provider):
        """Test get_unread_messages sans emails."""
        emails = empty_provider.get_unread_messages()
        assert len(emails) == 0

    def test_get_message_by_id(self, mock_provider):
        """Test récupération message par ID."""
        email = mock_provider.get_message_by_id("msg-001")

        assert email is not None
        assert email.id == "msg-001"
        assert email.sender == "alice@example.com"

    def test_get_message_by_id_not_found(self, mock_provider):
        """Test message non trouvé retourne None."""
        email = mock_provider.get_message_by_id("non-existent")
        assert email is None

    def test_create_draft(self, mock_provider):
        """Test création brouillon."""
        draft_id = mock_provider.create_draft(
            to=["recipient@example.com"],
            subject="Test Subject",
            body="Test body content"
        )

        assert draft_id is not None
        assert draft_id.startswith("draft-")
        assert draft_id in mock_provider._drafts

    def test_create_draft_with_reply(self, mock_provider):
        """Test création brouillon en réponse."""
        draft_id = mock_provider.create_draft(
            to=["sender@example.com"],
            subject="Re: Original",
            body="My reply",
            reply_to_id="msg-001"
        )

        assert draft_id is not None
        draft = mock_provider._drafts[draft_id]
        assert draft["reply_to_id"] == "msg-001"

    def test_create_draft_with_cc(self, mock_provider):
        """Test création brouillon avec CC."""
        draft_id = mock_provider.create_draft(
            to=["main@example.com"],
            subject="Test",
            body="Body",
            cc=["cc1@example.com", "cc2@example.com"]
        )

        draft = mock_provider._drafts[draft_id]
        assert draft["cc"] == ["cc1@example.com", "cc2@example.com"]

    def test_send_draft(self, mock_provider):
        """Test envoi brouillon."""
        draft_id = mock_provider.create_draft(
            to=["test@example.com"],
            subject="Test",
            body="Body"
        )

        assert draft_id in mock_provider._drafts
        result = mock_provider.send_draft(draft_id)

        assert result is True
        assert draft_id not in mock_provider._drafts

    def test_send_draft_not_found(self, mock_provider):
        """Test envoi brouillon inexistant."""
        result = mock_provider.send_draft("non-existent-draft")
        assert result is False

    def test_send_email_convenience(self, mock_provider):
        """Test méthode send_email (create + send)."""
        result = mock_provider.send_email(
            to=["test@example.com"],
            subject="Direct Send",
            body="This is sent directly"
        )

        assert result is True
        # Vérifier que le brouillon a été supprimé après envoi
        assert len(mock_provider._drafts) == 0

    def test_mark_as_read(self, mock_provider):
        """Test marquer comme lu."""
        # Vérifier état initial
        email = mock_provider.get_message_by_id("msg-001")
        assert email.is_read is False

        # Marquer comme lu
        result = mock_provider.mark_as_read("msg-001")
        assert result is True

        # Vérifier nouvel état
        email = mock_provider.get_message_by_id("msg-001")
        assert email.is_read is True

    def test_mark_as_read_not_found(self, mock_provider):
        """Test marquer inexistant."""
        result = mock_provider.mark_as_read("non-existent")
        assert result is False

    def test_mark_as_read_affects_unread_count(self, mock_provider):
        """Test que mark_as_read affecte get_unread_messages."""
        initial_unread = len(mock_provider.get_unread_messages())

        mock_provider.mark_as_read("msg-001")

        new_unread = len(mock_provider.get_unread_messages())
        assert new_unread == initial_unread - 1


class TestEmailProviderInterface:
    """Tests pour vérifier que l'interface est correctement définie."""

    def test_is_abstract(self):
        """Test que EmailProvider est abstraite."""
        with pytest.raises(TypeError):
            EmailProvider()

    def test_mock_implements_interface(self, mock_provider):
        """Test que MockProvider implémente toutes les méthodes."""
        assert hasattr(mock_provider, 'provider_name')
        assert hasattr(mock_provider, 'authenticate')
        assert hasattr(mock_provider, 'get_unread_messages')
        assert hasattr(mock_provider, 'get_message_by_id')
        assert hasattr(mock_provider, 'create_draft')
        assert hasattr(mock_provider, 'send_draft')
        assert hasattr(mock_provider, 'mark_as_read')
        assert hasattr(mock_provider, 'send_email')
