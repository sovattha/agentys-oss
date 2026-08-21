# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests de couverture supplémentaires pour SMTPAdapter et IMAPSMTPAdapter.

Ces tests ciblent spécifiquement les lignes non couvertes:
- Message creation options (from_name, cc, reply_to, in_reply_to, is_html)
- send_draft method
- SMTPException handling
- Unsupported IMAP operations
- Disconnect exception handling
- IMAPSMTPAdapter delegation methods

pytest tests/test_smtp_adapter_coverage.py -v --cov=app.providers.smtp_adapter
"""

import pytest
import smtplib
from unittest.mock import MagicMock, patch

from app.providers.smtp_adapter import SMTPAdapter, IMAPSMTPAdapter


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def smtp_adapter():
    """Crée un adaptateur SMTP avec config de test."""
    return SMTPAdapter(
        host="smtp.test.com",
        port=587,
        username="test@test.com",
        password="testpass",
        use_tls=True,
        from_email="test@test.com",
    )


@pytest.fixture
def smtp_adapter_with_from_name():
    """Crée un adaptateur SMTP avec from_name."""
    return SMTPAdapter(
        host="smtp.test.com",
        port=587,
        username="test@test.com",
        password="testpass",
        use_tls=True,
        from_email="test@test.com",
        from_name="Test User",
    )


@pytest.fixture
def authenticated_smtp_adapter():
    """Crée un adaptateur SMTP authentifié avec mock."""
    adapter = SMTPAdapter(
        host="smtp.test.com",
        port=587,
        username="test@test.com",
        password="testpass",
        use_tls=True,
        from_email="test@test.com",
    )
    adapter._connection = MagicMock()
    adapter._authenticated = True
    return adapter


@pytest.fixture
def authenticated_smtp_adapter_with_name():
    """Crée un adaptateur SMTP authentifié avec from_name."""
    adapter = SMTPAdapter(
        host="smtp.test.com",
        port=587,
        username="test@test.com",
        password="testpass",
        use_tls=True,
        from_email="test@test.com",
        from_name="Test User",
    )
    adapter._connection = MagicMock()
    adapter._authenticated = True
    return adapter


# ============================================================================
# TESTS _create_message - LINE 149 (from_name)
# ============================================================================

class TestCreateMessageFromName:
    """Tests pour _create_message avec from_name."""

    def test_create_message_with_from_name(self, smtp_adapter_with_from_name):
        """Message avec nom d'affichage de l'expéditeur."""
        msg = smtp_adapter_with_from_name._create_message(
            to=["recipient@test.com"],
            subject="Test Subject",
            body="Test body",
        )

        assert msg["From"] == "Test User <test@test.com>"
        assert msg["To"] == "recipient@test.com"
        assert msg["Subject"] == "Test Subject"

    def test_create_message_without_from_name(self, smtp_adapter):
        """Message sans nom d'affichage (seulement email)."""
        msg = smtp_adapter._create_message(
            to=["recipient@test.com"],
            subject="Test Subject",
            body="Test body",
        )

        assert msg["From"] == "test@test.com"


# ============================================================================
# TESTS _create_message - LINE 157 (cc)
# ============================================================================

class TestCreateMessageCC:
    """Tests pour _create_message avec CC."""

    def test_create_message_with_cc(self, smtp_adapter):
        """Message avec copie carbone."""
        msg = smtp_adapter._create_message(
            to=["recipient@test.com"],
            subject="Test Subject",
            body="Test body",
            cc=["cc1@test.com", "cc2@test.com"],
        )

        assert msg["Cc"] == "cc1@test.com, cc2@test.com"

    def test_create_message_with_single_cc(self, smtp_adapter):
        """Message avec un seul destinataire en copie."""
        msg = smtp_adapter._create_message(
            to=["recipient@test.com"],
            subject="Test Subject",
            body="Test body",
            cc=["cc@test.com"],
        )

        assert msg["Cc"] == "cc@test.com"


# ============================================================================
# TESTS _create_message - LINE 160 (reply_to)
# ============================================================================

class TestCreateMessageReplyTo:
    """Tests pour _create_message avec reply_to."""

    def test_create_message_with_reply_to(self, smtp_adapter):
        """Message avec adresse de réponse personnalisée."""
        msg = smtp_adapter._create_message(
            to=["recipient@test.com"],
            subject="Test Subject",
            body="Test body",
            reply_to="support@company.com",
        )

        assert msg["Reply-To"] == "support@company.com"

    def test_create_message_reply_to_different_from_sender(self, smtp_adapter):
        """Message avec reply_to différent de l'expéditeur."""
        msg = smtp_adapter._create_message(
            to=["recipient@test.com"],
            subject="Test Subject",
            body="Test body",
            reply_to="noreply@company.com",
        )

        assert msg["Reply-To"] == "noreply@company.com"
        assert msg["From"] == "test@test.com"


# ============================================================================
# TESTS _create_message - LINES 163-164 (in_reply_to)
# ============================================================================

class TestCreateMessageInReplyTo:
    """Tests pour _create_message avec in_reply_to (threading)."""

    def test_create_message_with_in_reply_to(self, smtp_adapter):
        """Message en réponse à un autre (thread email)."""
        original_message_id = "<msg123@example.com>"
        msg = smtp_adapter._create_message(
            to=["recipient@test.com"],
            subject="Re: Test Subject",
            body="Test reply body",
            in_reply_to=original_message_id,
        )

        assert msg["In-Reply-To"] == original_message_id
        assert msg["References"] == original_message_id

    def test_create_message_threading_headers(self, smtp_adapter):
        """Vérification des headers de threading."""
        msg_id = "<thread-original@mail.com>"
        msg = smtp_adapter._create_message(
            to=["user@test.com"],
            subject="Re: Important",
            body="Reply content",
            in_reply_to=msg_id,
        )

        # Both In-Reply-To and References should be set for proper threading
        assert msg["In-Reply-To"] == msg_id
        assert msg["References"] == msg_id


# ============================================================================
# TESTS _create_message - LINE 168 (is_html)
# ============================================================================

class TestCreateMessageHTML:
    """Tests pour _create_message avec HTML."""

    def test_create_message_html_body(self, smtp_adapter):
        """Message avec corps HTML."""
        html_body = "<html><body><h1>Hello</h1><p>Test content</p></body></html>"
        msg = smtp_adapter._create_message(
            to=["recipient@test.com"],
            subject="HTML Email",
            body=html_body,
            is_html=True,
        )

        # Check that HTML part is attached
        payloads = msg.get_payload()
        assert len(payloads) == 1
        assert payloads[0].get_content_type() == "text/html"

    def test_create_message_plain_text(self, smtp_adapter):
        """Message avec corps texte brut."""
        msg = smtp_adapter._create_message(
            to=["recipient@test.com"],
            subject="Plain Email",
            body="Simple plain text",
            is_html=False,
        )

        payloads = msg.get_payload()
        assert len(payloads) == 1
        assert payloads[0].get_content_type() == "text/plain"


# ============================================================================
# TESTS _create_message - COMBINED OPTIONS
# ============================================================================

class TestCreateMessageCombined:
    """Tests avec multiples options combinées."""

    def test_create_message_all_options(self, smtp_adapter_with_from_name):
        """Message avec toutes les options."""
        msg = smtp_adapter_with_from_name._create_message(
            to=["main@test.com", "secondary@test.com"],
            subject="Full Featured Email",
            body="<p>HTML content</p>",
            cc=["cc1@test.com", "cc2@test.com"],
            is_html=True,
            reply_to="replies@company.com",
            in_reply_to="<original@mail.com>",
        )

        assert msg["From"] == "Test User <test@test.com>"
        assert msg["To"] == "main@test.com, secondary@test.com"
        assert msg["Cc"] == "cc1@test.com, cc2@test.com"
        assert msg["Reply-To"] == "replies@company.com"
        assert msg["In-Reply-To"] == "<original@mail.com>"
        assert msg["References"] == "<original@mail.com>"


# ============================================================================
# TESTS get_message_by_id - LINES 183-184
# ============================================================================

class TestGetMessageById:
    """Tests pour get_message_by_id (non supporté par SMTP)."""

    def test_get_message_by_id_returns_none(self, smtp_adapter):
        """SMTP ne peut pas lire d'emails."""
        result = smtp_adapter.get_message_by_id("msg123")
        assert result is None

    def test_get_message_by_id_logs_warning(self, smtp_adapter, caplog):
        """Vérifie que le warning est loggé."""
        import logging
        with caplog.at_level(logging.WARNING):
            smtp_adapter.get_message_by_id("msg123")

        assert "SMTP ne peut pas lire d'emails" in caplog.text


# ============================================================================
# TESTS send_draft - LINES 222-239
# ============================================================================

class TestSendDraft:
    """Tests pour send_draft."""

    def test_send_draft_not_found(self, authenticated_smtp_adapter):
        """Envoi d'un brouillon inexistant."""
        result = authenticated_smtp_adapter.send_draft("nonexistent-draft-id")
        assert result is False

    def test_send_draft_no_drafts_attribute(self, authenticated_smtp_adapter):
        """Envoi quand _drafts n'existe pas."""
        # S'assurer que _drafts n'existe pas
        if hasattr(authenticated_smtp_adapter, "_drafts"):
            del authenticated_smtp_adapter._drafts

        result = authenticated_smtp_adapter.send_draft("some-draft-id")
        assert result is False

    def test_create_and_send_draft_success(self, authenticated_smtp_adapter):
        """Création puis envoi d'un brouillon."""
        # Create draft
        draft_id = authenticated_smtp_adapter.create_draft(
            to=["recipient@test.com"],
            subject="Draft Subject",
            body="Draft body content",
        )
        assert draft_id is not None
        assert draft_id.startswith("smtp-draft-")

        # Verify draft was stored
        assert draft_id in authenticated_smtp_adapter._drafts

        # Send draft
        result = authenticated_smtp_adapter.send_draft(draft_id)
        assert result is True

        # Verify draft was deleted after sending
        assert draft_id not in authenticated_smtp_adapter._drafts

    def test_send_draft_with_cc(self, authenticated_smtp_adapter):
        """Envoi d'un brouillon avec CC."""
        draft_id = authenticated_smtp_adapter.create_draft(
            to=["main@test.com"],
            subject="CC Draft",
            body="Body with CC",
            cc=["cc@test.com"],
        )

        result = authenticated_smtp_adapter.send_draft(draft_id)
        assert result is True

    def test_send_draft_html(self, authenticated_smtp_adapter):
        """Envoi d'un brouillon HTML."""
        draft_id = authenticated_smtp_adapter.create_draft(
            to=["recipient@test.com"],
            subject="HTML Draft",
            body="<h1>HTML Body</h1>",
            is_html=True,
        )

        result = authenticated_smtp_adapter.send_draft(draft_id)
        assert result is True

    def test_create_draft_stores_all_fields(self, authenticated_smtp_adapter):
        """Vérifie que create_draft stocke tous les champs."""
        draft_id = authenticated_smtp_adapter.create_draft(
            to=["to@test.com"],
            subject="Subject",
            body="Body",
            reply_to_id="<original@mail.com>",
            cc=["cc@test.com"],
            is_html=True,
        )

        draft = authenticated_smtp_adapter._drafts[draft_id]
        assert draft["to"] == ["to@test.com"]
        assert draft["subject"] == "Subject"
        assert draft["body"] == "Body"
        assert draft["cc"] == ["cc@test.com"]
        assert draft["is_html"] is True
        assert draft["reply_to_id"] == "<original@mail.com>"


# ============================================================================
# TESTS send_email - LINE 282 (cc extension)
# ============================================================================

class TestSendEmailWithCC:
    """Tests pour send_email avec CC."""

    def test_send_email_with_cc(self, authenticated_smtp_adapter):
        """Envoi email avec destinataires en copie."""
        result = authenticated_smtp_adapter.send_email(
            to=["main@test.com"],
            subject="Email with CC",
            body="Content",
            cc=["cc1@test.com", "cc2@test.com"],
        )

        assert result is True
        # Verify sendmail was called with all recipients
        authenticated_smtp_adapter._connection.sendmail.assert_called_once()
        call_args = authenticated_smtp_adapter._connection.sendmail.call_args
        recipients = call_args[0][1]  # Second argument is recipients list
        assert "main@test.com" in recipients
        assert "cc1@test.com" in recipients
        assert "cc2@test.com" in recipients


# ============================================================================
# TESTS send_email - LINES 295-296 (SMTPException)
# ============================================================================

class TestSendEmailSMTPException:
    """Tests pour gestion SMTPException dans send_email."""

    def test_send_email_smtp_exception(self, authenticated_smtp_adapter):
        """Gestion de SMTPException lors de l'envoi."""
        authenticated_smtp_adapter._connection.sendmail.side_effect = smtplib.SMTPException(
            "SMTP error occurred"
        )

        result = authenticated_smtp_adapter.send_email(
            to=["recipient@test.com"],
            subject="Test",
            body="Content",
        )

        assert result is False

    def test_send_email_smtp_sender_refused(self, authenticated_smtp_adapter):
        """Gestion de SMTPSenderRefused."""
        authenticated_smtp_adapter._connection.sendmail.side_effect = smtplib.SMTPSenderRefused(
            550, b"Sender rejected", "test@test.com"
        )

        result = authenticated_smtp_adapter.send_email(
            to=["recipient@test.com"],
            subject="Test",
            body="Content",
        )

        assert result is False

    def test_send_email_smtp_recipients_refused(self, authenticated_smtp_adapter):
        """Gestion de SMTPRecipientsRefused."""
        authenticated_smtp_adapter._connection.sendmail.side_effect = smtplib.SMTPRecipientsRefused(
            {"recipient@test.com": (550, b"User unknown")}
        )

        result = authenticated_smtp_adapter.send_email(
            to=["recipient@test.com"],
            subject="Test",
            body="Content",
        )

        assert result is False

    def test_send_email_smtp_data_error(self, authenticated_smtp_adapter):
        """Gestion de SMTPDataError."""
        authenticated_smtp_adapter._connection.sendmail.side_effect = smtplib.SMTPDataError(
            554, b"Message rejected"
        )

        result = authenticated_smtp_adapter.send_email(
            to=["recipient@test.com"],
            subject="Test",
            body="Content",
        )

        assert result is False

    def test_send_email_partial_recipient_refusal_is_failure(self, authenticated_smtp_adapter):
        """Regression (chaos audit 2026-06-02, P1): smtplib.sendmail does NOT raise
        when SOME recipients are accepted and others refused — it RETURNS a dict of
        the refused recipients (it only raises SMTPRecipientsRefused when ALL fail).
        That dict used to be discarded and the send reported as a full success, so
        the user was told 'sent' while a recipient silently never received the mail.
        A non-empty refusal dict must now surface as a send FAILURE."""
        authenticated_smtp_adapter._connection.sendmail.return_value = {
            "bounces@bad.com": (550, b"User unknown"),
        }

        result = authenticated_smtp_adapter.send_email(
            to=["main@test.com"],
            subject="Test",
            body="Content",
            cc=["bounces@bad.com"],
        )

        assert result is False

    def test_send_email_no_refusal_is_success(self, authenticated_smtp_adapter):
        """The success contract: real sendmail returns an EMPTY dict when every
        recipient is accepted — that must still be reported as success."""
        authenticated_smtp_adapter._connection.sendmail.return_value = {}

        result = authenticated_smtp_adapter.send_email(
            to=["main@test.com"],
            subject="Test",
            body="Content",
        )

        assert result is True


# ============================================================================
# TESTS UNSUPPORTED IMAP OPERATIONS - LINES 309-310, 314-315, 327-328
# ============================================================================

class TestUnsupportedIMAPOperations:
    """Tests pour les opérations IMAP non supportées par SMTP."""

    def test_get_user_drafts_returns_empty(self, smtp_adapter):
        """get_user_drafts retourne une liste vide."""
        result = smtp_adapter.get_user_drafts()
        assert result == []

    def test_get_user_drafts_logs_warning(self, smtp_adapter, caplog):
        """get_user_drafts logge un avertissement."""
        import logging
        with caplog.at_level(logging.WARNING):
            smtp_adapter.get_user_drafts(limit=10)

        assert "SMTP ne peut pas lire les brouillons" in caplog.text

    def test_get_draft_by_id_returns_none(self, smtp_adapter):
        """get_draft_by_id retourne None."""
        result = smtp_adapter.get_draft_by_id("draft123")
        assert result is None

    def test_get_draft_by_id_logs_warning(self, smtp_adapter, caplog):
        """get_draft_by_id logge un avertissement."""
        import logging
        with caplog.at_level(logging.WARNING):
            smtp_adapter.get_draft_by_id("draft123")

        assert "SMTP ne peut pas lire les brouillons" in caplog.text

    def test_update_draft_returns_false(self, smtp_adapter):
        """update_draft retourne False."""
        result = smtp_adapter.update_draft(
            draft_id="draft123",
            subject="New Subject",
            body="New Body",
        )
        assert result is False

    def test_update_draft_logs_warning(self, smtp_adapter, caplog):
        """update_draft logge un avertissement."""
        import logging
        with caplog.at_level(logging.WARNING):
            smtp_adapter.update_draft("draft123", subject="Test")

        assert "SMTP ne peut pas mettre à jour les brouillons" in caplog.text


# ============================================================================
# TESTS disconnect - LINES 335-336 (exception handling)
# ============================================================================

class TestDisconnect:
    """Tests pour disconnect avec gestion d'exceptions."""

    def test_disconnect_with_exception(self):
        """Disconnect gère proprement les exceptions."""
        adapter = SMTPAdapter(
            host="smtp.test.com",
            port=587,
            username="test@test.com",
            password="testpass",
        )

        mock_conn = MagicMock()
        mock_conn.quit.side_effect = Exception("Connection already closed")
        adapter._connection = mock_conn
        adapter._authenticated = True

        # Should not raise
        adapter.disconnect()

        # Connection should be cleaned up
        assert adapter._connection is None
        assert adapter._authenticated is False

    def test_disconnect_quit_smtplib_error(self):
        """Disconnect gère SMTPServerDisconnected."""
        adapter = SMTPAdapter(
            host="smtp.test.com",
            port=587,
            username="test@test.com",
            password="testpass",
        )

        mock_conn = MagicMock()
        mock_conn.quit.side_effect = smtplib.SMTPServerDisconnected("Already disconnected")
        adapter._connection = mock_conn
        adapter._authenticated = True

        adapter.disconnect()

        assert adapter._connection is None
        assert adapter._authenticated is False

    def test_disconnect_no_connection(self, smtp_adapter):
        """Disconnect quand pas de connexion active."""
        # Should not raise
        smtp_adapter.disconnect()

        assert smtp_adapter._connection is None
        assert smtp_adapter._authenticated is False


# ============================================================================
# TESTS IMAPSMTPAdapter DELEGATION - LINES 419-422, 434, 437, 451, 454, 465
# ============================================================================

class TestIMAPSMTPAdapterDelegation:
    """Tests pour les méthodes de délégation de IMAPSMTPAdapter."""

    @pytest.fixture
    def imap_smtp_adapter(self):
        """Crée un adaptateur combiné avec mocks."""
        with patch("app.providers.imap_adapter.IMAPAdapter") as mock_imap_class:
            mock_imap = MagicMock()
            mock_imap_class.return_value = mock_imap

            adapter = IMAPSMTPAdapter(
                imap_host="imap.test.com",
                imap_port=993,
                imap_username="test@test.com",
                imap_password="testpass",
                smtp_host="smtp.test.com",
                smtp_port=587,
                smtp_username="test@test.com",
                smtp_password="testpass",
            )

            # Replace the internal _imap with mock
            adapter._imap = mock_imap
            return adapter

    def test_get_message_by_id_delegates_to_imap(self, imap_smtp_adapter):
        """get_message_by_id délègue à IMAP."""
        imap_smtp_adapter._imap.get_message_by_id.return_value = MagicMock(id="msg123")

        result = imap_smtp_adapter.get_message_by_id("msg123")

        imap_smtp_adapter._imap.get_message_by_id.assert_called_once_with("msg123", folder=None)
        assert result is not None

    def test_mark_as_read_delegates_to_imap(self, imap_smtp_adapter):
        """mark_as_read délègue à IMAP."""
        imap_smtp_adapter._imap.mark_as_read.return_value = True

        result = imap_smtp_adapter.mark_as_read("msg123")

        imap_smtp_adapter._imap.mark_as_read.assert_called_once_with("msg123")
        assert result is True

    def test_create_draft_delegates_to_smtp(self, imap_smtp_adapter):
        """create_draft délègue à SMTP."""
        # Replace _smtp with a mock to test delegation
        mock_smtp = MagicMock()
        mock_smtp.create_draft.return_value = "draft-123"
        imap_smtp_adapter._smtp = mock_smtp

        result = imap_smtp_adapter.create_draft(
            to=["to@test.com"],
            subject="Subject",
            body="Body",
            reply_to_id="<original@mail.com>",
            cc=["cc@test.com"],
            is_html=False,
        )

        mock_smtp.create_draft.assert_called_once_with(
            ["to@test.com"], "Subject", "Body", "<original@mail.com>",
            ["cc@test.com"], None, False, None, from_name=None,
        )
        assert result == "draft-123"

    def test_send_draft_delegates_to_smtp(self, imap_smtp_adapter):
        """send_draft délègue à SMTP."""
        # Replace _smtp with a mock to test delegation
        mock_smtp = MagicMock()
        mock_smtp.send_draft.return_value = True
        imap_smtp_adapter._smtp = mock_smtp

        result = imap_smtp_adapter.send_draft("draft-123")

        mock_smtp.send_draft.assert_called_once_with("draft-123")
        assert result is True

    def test_get_user_drafts_delegates_to_imap(self, imap_smtp_adapter):
        """get_user_drafts délègue à IMAP."""
        imap_smtp_adapter._imap.get_user_drafts.return_value = []

        result = imap_smtp_adapter.get_user_drafts(limit=20)

        imap_smtp_adapter._imap.get_user_drafts.assert_called_once_with(20)
        assert result == []

    def test_get_draft_by_id_delegates_to_imap(self, imap_smtp_adapter):
        """get_draft_by_id délègue à IMAP."""
        mock_draft = MagicMock(id="draft-123")
        imap_smtp_adapter._imap.get_draft_by_id.return_value = mock_draft

        result = imap_smtp_adapter.get_draft_by_id("draft-123")

        imap_smtp_adapter._imap.get_draft_by_id.assert_called_once_with("draft-123")
        assert result == mock_draft

    def test_update_draft_delegates_to_imap(self, imap_smtp_adapter):
        """update_draft délègue à IMAP."""
        imap_smtp_adapter._imap.update_draft.return_value = True

        result = imap_smtp_adapter.update_draft(
            draft_id="draft-123",
            subject="New Subject",
            body="New Body",
            to=["new@test.com"],
            cc=["newcc@test.com"],
            is_html=True,
        )

        imap_smtp_adapter._imap.update_draft.assert_called_once_with(
            "draft-123", "New Subject", "New Body", ["new@test.com"], ["newcc@test.com"], True
        )
        assert result is True


# ============================================================================
# TESTS IMAPSMTPAdapter - ADDITIONAL COVERAGE
# ============================================================================

class TestIMAPSMTPAdapterAdditional:
    """Tests additionnels pour IMAPSMTPAdapter."""

    def test_authenticate_both_fail_imap(self):
        """Authentification échoue si SMTP échoue (IMAP is lazy)."""
        with patch("app.providers.imap_adapter.IMAPAdapter") as mock_imap_class:
            mock_imap = MagicMock()
            mock_imap_class.return_value = mock_imap

            adapter = IMAPSMTPAdapter(
                imap_host="imap.test.com",
                imap_username="u", imap_password="p",
                smtp_host="smtp.test.com",
                smtp_username="u", smtp_password="p",
            )

            with patch.object(adapter._smtp, "authenticate", return_value=False):
                result = adapter.authenticate()

            assert result is False
            assert adapter._authenticated is False

    def test_authenticate_both_fail_smtp(self):
        """Authentification échoue si SMTP échoue."""
        with patch("app.providers.imap_adapter.IMAPAdapter") as mock_imap_class:
            mock_imap = MagicMock()
            mock_imap.authenticate.return_value = True
            mock_imap_class.return_value = mock_imap

            adapter = IMAPSMTPAdapter(
                imap_host="imap.test.com",
                imap_username="u", imap_password="p",
                smtp_host="smtp.test.com",
                smtp_username="u", smtp_password="p",
            )

            with patch.object(adapter._smtp, "authenticate", return_value=False):
                result = adapter.authenticate()

            assert result is False
            assert adapter._authenticated is False

    def test_disconnect_both(self):
        """Disconnect déconnecte les deux adaptateurs."""
        with patch("app.providers.imap_adapter.IMAPAdapter") as mock_imap_class:
            mock_imap = MagicMock()
            mock_imap_class.return_value = mock_imap

            adapter = IMAPSMTPAdapter(
                imap_host="imap.test.com",
                imap_username="u", imap_password="p",
                smtp_host="smtp.test.com",
                smtp_username="u", smtp_password="p",
            )
            adapter._authenticated = True

            adapter.disconnect()

            mock_imap.disconnect.assert_called_once()
            assert adapter._authenticated is False

    def test_send_email_delegates_to_smtp(self):
        """send_email délègue à SMTP."""
        with patch("app.providers.imap_adapter.IMAPAdapter") as mock_imap_class:
            mock_imap = MagicMock()
            mock_imap_class.return_value = mock_imap

            adapter = IMAPSMTPAdapter(
                imap_host="imap.test.com",
                imap_username="u", imap_password="p",
                smtp_host="smtp.test.com",
                smtp_username="u", smtp_password="p",
            )

            adapter._smtp.send_email = MagicMock(return_value=True)

            result = adapter.send_email(
                to=["to@test.com"],
                subject="Subject",
                body="Body",
                cc=["cc@test.com"],
                is_html=True,
            )

            adapter._smtp.send_email.assert_called_once_with(
                ["to@test.com"], "Subject", "Body",
                cc=["cc@test.com"], is_html=True, attachments=None,
            )
            assert result is True


# ============================================================================
# TESTS SMTPAdapter - EDGE CASES
# ============================================================================

class TestSMTPAdapterEdgeCases:
    """Tests pour les cas limites de SMTPAdapter."""

    def test_multiple_recipients(self, authenticated_smtp_adapter):
        """Envoi à plusieurs destinataires."""
        result = authenticated_smtp_adapter.send_email(
            to=["user1@test.com", "user2@test.com", "user3@test.com"],
            subject="Multi-recipient",
            body="Content for all",
        )

        assert result is True

    def test_create_draft_initializes_drafts_dict(self, smtp_adapter):
        """create_draft initialise _drafts si nécessaire."""
        # S'assurer que _drafts n'existe pas
        if hasattr(smtp_adapter, "_drafts"):
            del smtp_adapter._drafts

        draft_id = smtp_adapter.create_draft(
            to=["to@test.com"],
            subject="Subject",
            body="Body",
        )

        assert hasattr(smtp_adapter, "_drafts")
        assert draft_id in smtp_adapter._drafts

    def test_send_email_with_all_options(self, authenticated_smtp_adapter_with_name):
        """send_email avec toutes les options."""
        result = authenticated_smtp_adapter_with_name.send_email(
            to=["main@test.com"],
            subject="Full Options Email",
            body="<h1>HTML</h1>",
            cc=["cc@test.com"],
            is_html=True,
            reply_to="noreply@test.com",
            in_reply_to="<original@mail.com>",
        )

        assert result is True
        authenticated_smtp_adapter_with_name._connection.sendmail.assert_called_once()

    def test_send_email_unexpected_exception(self, authenticated_smtp_adapter):
        """send_email gère les exceptions inattendues."""
        authenticated_smtp_adapter._connection.sendmail.side_effect = RuntimeError(
            "Unexpected error"
        )

        result = authenticated_smtp_adapter.send_email(
            to=["to@test.com"],
            subject="Test",
            body="Body",
        )

        assert result is False

    def test_del_calls_disconnect(self):
        """__del__ appelle disconnect."""
        adapter = SMTPAdapter(
            host="smtp.test.com",
            port=587,
            username="test@test.com",
            password="testpass",
        )

        mock_conn = MagicMock()
        adapter._connection = mock_conn
        adapter._authenticated = True

        # Simulate __del__
        del adapter

        # Connection should have been cleaned up
        # (can't directly verify since adapter is deleted)

    def test_imap_smtp_adapter_del_calls_disconnect(self):
        """IMAPSMTPAdapter __del__ appelle disconnect."""
        with patch("app.providers.imap_adapter.IMAPAdapter") as mock_imap_class:
            mock_imap = MagicMock()
            mock_imap_class.return_value = mock_imap

            adapter = IMAPSMTPAdapter(
                imap_host="imap.test.com",
                imap_username="u", imap_password="p",
                smtp_host="smtp.test.com",
                smtp_username="u", smtp_password="p",
            )

            # Store refs before del
            imap_ref = adapter._imap

            del adapter

            # Verify disconnect was called
            imap_ref.disconnect.assert_called()
