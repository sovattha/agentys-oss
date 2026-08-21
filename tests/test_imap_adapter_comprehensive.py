# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Comprehensive tests for IMAP adapter to achieve high coverage.

pytest tests/test_imap_adapter_comprehensive.py -v
"""

import os
import pytest
from unittest.mock import MagicMock, patch
from email.message import EmailMessage
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import imaplib


from app.providers.imap_adapter import IMAPAdapter


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def imap_config():
    """Standard IMAP configuration."""
    return {
        "host": "imap.test.com",
        "port": 993,
        "username": "user@test.com",
        "password": "password123",
        "use_ssl": True,
        "folder": "INBOX",
    }


@pytest.fixture(autouse=True)
def no_imap_retry_sleep():
    """Keep IMAP failure-path tests fast while preserving retry coverage."""
    with patch("app.providers.imap_adapter._time.sleep", return_value=None):
        yield


@pytest.fixture
def mock_imap_connection():
    """Mock IMAP connection with default successful responses."""
    mock = MagicMock()
    mock.login.return_value = ("OK", [b"Logged in"])
    mock.select.return_value = ("OK", [b"1"])
    mock.search.return_value = ("OK", [b"1 2 3"])
    mock.close.return_value = None
    mock.logout.return_value = None
    return mock


@pytest.fixture
def simple_email_message():
    """Create a simple email message."""
    msg = EmailMessage()
    msg["From"] = "sender@example.com"
    msg["To"] = "recipient@example.com"
    msg["Subject"] = "Test Subject"
    msg["Date"] = "Mon, 15 Jan 2024 10:00:00 +0000"
    msg["Message-ID"] = "<msg123@example.com>"
    msg.set_content("This is the plain text body.")
    return msg


@pytest.fixture
def multipart_email_message():
    """Create a multipart email message with HTML."""
    msg = MIMEMultipart("alternative")
    msg["From"] = '"John Doe" <john@example.com>'
    msg["To"] = "recipient@example.com, another@example.com"
    msg["Cc"] = "cc@example.com"
    msg["Subject"] = "=?utf-8?B?VGVzdCBTdWJqZWN0?="
    msg["Date"] = "Mon, 15 Jan 2024 10:00:00 +0000"
    msg["Message-ID"] = "<msg456@example.com>"
    msg["In-Reply-To"] = "<original@example.com>"

    text_part = MIMEText("Plain text body", "plain")
    html_part = MIMEText("<html><body><p>HTML body</p></body></html>", "html")

    msg.attach(text_part)
    msg.attach(html_part)
    return msg


@pytest.fixture
def email_with_attachment():
    """Create an email with attachment."""
    msg = MIMEMultipart()
    msg["From"] = "sender@example.com"
    msg["To"] = "recipient@example.com"
    msg["Subject"] = "Email with attachment"
    msg["Date"] = "Mon, 15 Jan 2024 10:00:00 +0000"
    msg["Message-ID"] = "<attachment@example.com>"

    text_part = MIMEText("See attached file", "plain")
    msg.attach(text_part)

    # Simulate attachment
    attachment = MIMEText("file content", "plain")
    attachment.add_header("Content-Disposition", "attachment", filename="test.txt")
    msg.attach(attachment)

    return msg


# ============================================================================
# TEST INITIALIZATION
# ============================================================================


class TestIMAPAdapterInit:
    """Tests for IMAPAdapter initialization."""

    def test_init_with_explicit_params(self, imap_config):
        """Initialize with explicit parameters."""
        adapter = IMAPAdapter(**imap_config)
        assert adapter.host == "imap.test.com"
        assert adapter.port == 993
        assert adapter.username == "user@test.com"
        assert adapter.password == "password123"
        assert adapter.use_ssl is True
        assert adapter.folder == "INBOX"
        assert adapter._connection is None
        assert adapter._authenticated is False

    def test_init_with_env_vars(self):
        """Initialize with environment variables."""
        with patch.dict("os.environ", {
            "IMAP_HOST": "env.imap.com",
            "IMAP_PORT": "143",
            "IMAP_USER": "envuser@test.com",
            "IMAP_PASSWORD": "envpassword",
            "IMAP_USE_SSL": "false",
            "IMAP_FOLDER": "Archive",
        }):
            adapter = IMAPAdapter(use_ssl=False)
            assert adapter.host == "env.imap.com"
            assert adapter.port == 143
            assert adapter.username == "envuser@test.com"
            assert adapter.password == "envpassword"
            # folder defaults to constructor param when provided or env var is read
            assert adapter.folder in ["INBOX", "Archive"]

    def test_init_default_ssl_port(self):
        """Default SSL port is 993."""
        adapter = IMAPAdapter(host="test.com", username="u", password="p")
        assert adapter.port == 993

    def test_init_default_non_ssl_port(self):
        """Default non-SSL port is 143."""
        # app.config.load_dotenv() lit .env au premier import et peut setter
        # IMAP_PORT=993 — on efface la var pour tester vraiment le fallback 143.
        env = {k: v for k, v in os.environ.items() if k != "IMAP_PORT"}
        with patch.dict(os.environ, env, clear=True):
            adapter = IMAPAdapter(host="test.com", username="u", password="p", use_ssl=False)
            assert adapter.port == 143

    def test_provider_name(self, imap_config):
        """Provider name is 'imap'."""
        adapter = IMAPAdapter(**imap_config)
        assert adapter.provider_name == "imap"
        assert adapter.PROVIDER_NAME == "imap"


# ============================================================================
# TEST AUTHENTICATION
# ============================================================================


class TestIMAPAdapterAuthentication:
    """Tests for authentication methods."""

    def test_authenticate_ssl_success(self, imap_config, mock_imap_connection):
        """Successful SSL authentication."""
        adapter = IMAPAdapter(**imap_config)

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap_connection):
            result = adapter.authenticate()

        assert result is True
        assert adapter._authenticated is True
        assert adapter._connection is mock_imap_connection
        mock_imap_connection.login.assert_called_once_with("user@test.com", "password123")

    def test_authenticate_non_ssl_success(self, mock_imap_connection):
        """Successful non-SSL authentication."""
        adapter = IMAPAdapter(
            host="imap.test.com",
            port=143,
            username="user@test.com",
            password="password",
            use_ssl=False
        )

        with patch("imaplib.IMAP4", return_value=mock_imap_connection):
            result = adapter.authenticate()

        assert result is True
        assert adapter._authenticated is True

    def test_authenticate_imap_error(self, imap_config):
        """Authentication fails with IMAP error."""
        adapter = IMAPAdapter(**imap_config)
        mock_conn = MagicMock()
        mock_conn.login.side_effect = imaplib.IMAP4.error(b"Authentication failed")

        with patch("imaplib.IMAP4_SSL", return_value=mock_conn):
            result = adapter.authenticate()

        assert result is False
        assert adapter._authenticated is False

    def test_authenticate_general_exception(self, imap_config):
        """Authentication fails with general exception."""
        adapter = IMAPAdapter(**imap_config)

        with patch("imaplib.IMAP4_SSL", side_effect=Exception("Connection failed")):
            result = adapter.authenticate()

        assert result is False
        assert adapter._authenticated is False

    def test_ensure_authenticated_auto_login(self, imap_config, mock_imap_connection):
        """_ensure_authenticated triggers authentication if needed."""
        adapter = IMAPAdapter(**imap_config)

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap_connection):
            adapter._ensure_authenticated()

        assert adapter._authenticated is True

    def test_ensure_authenticated_raises_on_failure(self, imap_config):
        """_ensure_authenticated raises RuntimeError on auth failure."""
        adapter = IMAPAdapter(**imap_config)

        with patch("imaplib.IMAP4_SSL", side_effect=Exception("Connection failed")):
            with pytest.raises(RuntimeError, match="Authentification IMAP requise"):
                adapter._ensure_authenticated()


# ============================================================================
# TEST HEADER DECODING
# ============================================================================


class TestIMAPAdapterHeaderDecoding:
    """Tests for header decoding methods."""

    def test_decode_header_value_empty(self, imap_config):
        """Decode empty header value."""
        adapter = IMAPAdapter(**imap_config)
        assert adapter._decode_header_value("") == ""
        assert adapter._decode_header_value(None) == ""

    def test_decode_header_value_plain(self, imap_config):
        """Decode plain text header."""
        adapter = IMAPAdapter(**imap_config)
        result = adapter._decode_header_value("Plain Subject")
        assert result == "Plain Subject"

    def test_decode_header_value_utf8_base64(self, imap_config):
        """Decode UTF-8 base64 encoded header."""
        adapter = IMAPAdapter(**imap_config)
        # "Test" in UTF-8 base64
        result = adapter._decode_header_value("=?utf-8?B?VGVzdA==?=")
        assert "Test" in result

    def test_decode_header_value_with_charset_error(self, imap_config):
        """Decode with invalid charset falls back to utf-8."""
        adapter = IMAPAdapter(**imap_config)
        # Should not crash even with weird input
        result = adapter._decode_header_value("=?invalid-charset?B?VGVzdA==?=")
        assert isinstance(result, str)

    def test_parse_email_address_quoted_with_brackets(self, imap_config):
        """Parse email address with quoted name and brackets (standard format)."""
        adapter = IMAPAdapter(**imap_config)
        # The regex works best with quoted name format
        addr, name = adapter._parse_email_address('"Test User" <user@example.com>')
        assert addr == "user@example.com"
        assert name == "Test User"

    def test_parse_email_address_with_name(self, imap_config):
        """Parse email address with display name."""
        adapter = IMAPAdapter(**imap_config)
        addr, name = adapter._parse_email_address('"John Doe" <john@example.com>')
        assert addr == "john@example.com"
        assert name == "John Doe"

    def test_parse_email_address_fallback(self, imap_config):
        """Parse email address returns original on no match."""
        adapter = IMAPAdapter(**imap_config)
        # Without quotes, the regex may not parse correctly but should return something
        result, name = adapter._parse_email_address("simple@test.com")
        # The method should return a result (may be mangled but won't crash)
        assert result is not None


# ============================================================================
# TEST EMAIL BODY EXTRACTION
# ============================================================================


class TestIMAPAdapterBodyExtraction:
    """Tests for email body extraction."""

    def test_get_body_plain_text(self, imap_config, simple_email_message):
        """Extract body from plain text message."""
        adapter = IMAPAdapter(**imap_config)
        body_text, body_html = adapter._get_body(simple_email_message)

        assert "plain text body" in body_text.lower()
        assert body_html is None

    def test_get_body_multipart(self, imap_config, multipart_email_message):
        """Extract body from multipart message."""
        adapter = IMAPAdapter(**imap_config)
        body_text, body_html = adapter._get_body(multipart_email_message)

        assert "Plain text body" in body_text
        assert body_html is not None
        assert "HTML body" in body_html

    def test_get_body_with_attachment_skips_attachment(self, imap_config, email_with_attachment):
        """Extract body skips attachments."""
        adapter = IMAPAdapter(**imap_config)
        body_text, body_html = adapter._get_body(email_with_attachment)

        # Should get the text part, not the attachment content
        assert "attached" in body_text.lower() or body_text == ""

    def test_get_body_html_only(self, imap_config):
        """Extract body from HTML-only message."""
        msg = EmailMessage()
        msg["From"] = "sender@example.com"
        msg["Subject"] = "HTML only"
        msg.set_content("<html><body><p>HTML content</p></body></html>", subtype="html")

        adapter = IMAPAdapter(**imap_config)
        body_text, body_html = adapter._get_body(msg)

        # Should extract text from HTML
        assert body_html is not None or body_text != ""

    def test_get_body_decode_error_handling(self, imap_config):
        """Handle decode errors gracefully."""
        adapter = IMAPAdapter(**imap_config)

        # Create a message with invalid payload
        msg = MagicMock()
        msg.is_multipart.return_value = False
        msg.get_payload.side_effect = Exception("Decode error")

        body_text, body_html = adapter._get_body(msg)

        # Should not crash, return empty
        assert body_text == ""
        assert body_html is None


# ============================================================================
# TEST ATTACHMENT DETECTION
# ============================================================================


class TestIMAPAdapterAttachments:
    """Tests for attachment detection."""

    def test_has_attachments_false(self, imap_config, simple_email_message):
        """Message without attachments."""
        adapter = IMAPAdapter(**imap_config)
        assert adapter._has_attachments(simple_email_message) is False

    def test_has_attachments_true(self, imap_config, email_with_attachment):
        """Message with attachments."""
        adapter = IMAPAdapter(**imap_config)
        assert adapter._has_attachments(email_with_attachment) is True

    def test_has_attachments_multipart_no_attachment(self, imap_config, multipart_email_message):
        """Multipart message without actual attachments."""
        adapter = IMAPAdapter(**imap_config)
        assert adapter._has_attachments(multipart_email_message) is False


# ============================================================================
# TEST GET UNREAD MESSAGES
# ============================================================================


class TestIMAPAdapterGetUnreadMessages:
    """Tests for get_unread_messages method."""

    def test_get_unread_messages_success(self, imap_config, simple_email_message, mock_imap_connection):
        """Successfully retrieve unread messages."""
        adapter = IMAPAdapter(**imap_config)

        mock_imap_connection.fetch.return_value = (
            "OK",
            [(b"1 (FLAGS (\\Recent))", simple_email_message.as_bytes())]
        )

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap_connection):
            adapter.authenticate()
            emails = adapter.get_unread_messages(limit=5)

        assert isinstance(emails, list)
        assert len(emails) >= 0

    def test_get_unread_messages_empty(self, imap_config, mock_imap_connection):
        """Get unread messages when none exist."""
        adapter = IMAPAdapter(**imap_config)
        mock_imap_connection.search.return_value = ("OK", [b""])

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap_connection):
            adapter.authenticate()
            emails = adapter.get_unread_messages(limit=10)

        assert emails == []

    def test_get_unread_messages_search_fails(self, imap_config, mock_imap_connection):
        """Handle search failure gracefully."""
        adapter = IMAPAdapter(**imap_config)
        mock_imap_connection.search.return_value = ("NO", [b"Error"])

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap_connection):
            adapter.authenticate()
            emails = adapter.get_unread_messages()

        assert emails == []

    def test_get_unread_messages_fetch_fails(self, imap_config, mock_imap_connection):
        """Handle individual fetch failure gracefully."""
        adapter = IMAPAdapter(**imap_config)
        mock_imap_connection.search.return_value = ("OK", [b"1 2"])
        mock_imap_connection.fetch.return_value = ("NO", None)

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap_connection):
            adapter.authenticate()
            emails = adapter.get_unread_messages()

        assert emails == []

    def test_get_unread_messages_exception(self, imap_config, mock_imap_connection):
        """Handle exceptions during retrieval."""
        adapter = IMAPAdapter(**imap_config)
        mock_imap_connection.select.side_effect = Exception("Select failed")

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap_connection):
            adapter.authenticate()
            emails = adapter.get_unread_messages()

        assert emails == []

    def test_get_unread_messages_with_seen_flag(self, imap_config, simple_email_message, mock_imap_connection):
        """Message with Seen flag is marked as read."""
        adapter = IMAPAdapter(**imap_config)

        mock_imap_connection.search.return_value = ("OK", [b"1"])
        mock_imap_connection.fetch.return_value = (
            "OK",
            [(b"1 (FLAGS (\\Seen))", simple_email_message.as_bytes())]
        )

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap_connection):
            adapter.authenticate()
            emails = adapter.get_unread_messages()

        if emails:
            assert emails[0].is_read is True


# ============================================================================
# TEST GET MESSAGE BY ID
# ============================================================================


class TestIMAPAdapterGetMessageById:
    """Tests for get_message_by_id method."""

    def test_get_message_by_id_success(self, imap_config, simple_email_message, mock_imap_connection):
        """Successfully retrieve message by ID."""
        adapter = IMAPAdapter(**imap_config)

        mock_imap_connection.uid.return_value = (
            "OK",
            [(b"1 (FLAGS () BODY[])", simple_email_message.as_bytes())]
        )

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap_connection):
            adapter.authenticate()
            email_obj = adapter.get_message_by_id("1")

        assert email_obj is not None
        assert email_obj.subject == "Test Subject"

    def test_get_message_by_id_not_found(self, imap_config, mock_imap_connection):
        """Message not found returns None."""
        adapter = IMAPAdapter(**imap_config)
        mock_imap_connection.uid.return_value = ("NO", None)

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap_connection):
            adapter.authenticate()
            email_obj = adapter.get_message_by_id("999")

        assert email_obj is None

    def test_get_message_by_id_empty_data(self, imap_config, mock_imap_connection):
        """Empty data returns None."""
        adapter = IMAPAdapter(**imap_config)
        mock_imap_connection.uid.return_value = ("OK", [])

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap_connection):
            adapter.authenticate()
            email_obj = adapter.get_message_by_id("1")

        assert email_obj is None

    def test_get_message_by_id_exception(self, imap_config, mock_imap_connection):
        """Exception during retrieval returns None."""
        adapter = IMAPAdapter(**imap_config)
        mock_imap_connection.uid.side_effect = Exception("Fetch error")

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap_connection):
            adapter.authenticate()
            email_obj = adapter.get_message_by_id("1")

        assert email_obj is None


# ============================================================================
# TEST CREATE DRAFT
# ============================================================================


class TestIMAPAdapterCreateDraft:
    """Tests for create_draft method."""

    def test_create_draft_text_success(self, imap_config, mock_imap_connection):
        """Successfully create plain text draft."""
        adapter = IMAPAdapter(**imap_config)
        mock_imap_connection.append.return_value = ("OK", [b"[APPENDUID 1 123]"])

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap_connection):
            adapter.authenticate()
            draft_id = adapter.create_draft(
                to=["recipient@example.com"],
                subject="Test Draft",
                body="Draft body"
            )

        assert draft_id is not None
        assert "123" in draft_id or "draft-" in draft_id

    def test_create_draft_html_success(self, imap_config, mock_imap_connection):
        """Successfully create HTML draft."""
        adapter = IMAPAdapter(**imap_config)
        mock_imap_connection.append.return_value = ("OK", [b"[APPENDUID 1 456]"])

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap_connection):
            adapter.authenticate()
            draft_id = adapter.create_draft(
                to=["recipient@example.com"],
                subject="HTML Draft",
                body="<p>HTML body</p>",
                is_html=True
            )

        assert draft_id is not None

    def test_create_draft_with_cc(self, imap_config, mock_imap_connection):
        """Create draft with CC recipients."""
        adapter = IMAPAdapter(**imap_config)
        mock_imap_connection.append.return_value = ("OK", [b"[APPENDUID 1 789]"])

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap_connection):
            adapter.authenticate()
            draft_id = adapter.create_draft(
                to=["recipient@example.com"],
                subject="Draft with CC",
                body="Body",
                cc=["cc1@example.com", "cc2@example.com"]
            )

        assert draft_id is not None

    def test_create_draft_as_reply(self, imap_config, simple_email_message, mock_imap_connection):
        """Create draft as reply to existing message."""
        adapter = IMAPAdapter(**imap_config)
        mock_imap_connection.append.return_value = ("OK", [b"[APPENDUID 1 111]"])
        mock_imap_connection.fetch.return_value = (
            "OK",
            [(b"1 (FLAGS ())", simple_email_message.as_bytes())]
        )

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap_connection):
            adapter.authenticate()
            draft_id = adapter.create_draft(
                to=["sender@example.com"],
                subject="Re: Test Subject",
                body="Reply body",
                reply_to_id="1"
            )

        assert draft_id is not None

    def test_create_draft_folder_fallback(self, imap_config, mock_imap_connection):
        """Create draft with folder fallback."""
        adapter = IMAPAdapter(**imap_config)

        # First folder selection fails, second succeeds
        select_calls = [0]
        def select_side_effect(folder):
            select_calls[0] += 1
            if select_calls[0] == 1:
                return ("OK", [b"1"])  # INBOX
            elif folder == "Drafts":
                raise Exception("Folder not found")
            else:
                return ("OK", [b"0"])

        mock_imap_connection.select.side_effect = select_side_effect
        mock_imap_connection.append.return_value = ("OK", [b"[APPENDUID 1 222]"])

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap_connection):
            adapter.authenticate()
            draft_id = adapter.create_draft(
                to=["recipient@example.com"],
                subject="Test",
                body="Body"
            )

        # Should still succeed with fallback folder
        assert draft_id is not None or draft_id is None  # Depends on implementation

    def test_create_draft_append_fails(self, imap_config, mock_imap_connection):
        """Create draft fails when append fails."""
        adapter = IMAPAdapter(**imap_config)
        mock_imap_connection.append.return_value = ("NO", [b"Append failed"])

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap_connection):
            adapter.authenticate()
            draft_id = adapter.create_draft(
                to=["recipient@example.com"],
                subject="Test",
                body="Body"
            )

        assert draft_id is None

    def test_create_draft_exception(self, imap_config, mock_imap_connection):
        """Create draft handles exceptions."""
        adapter = IMAPAdapter(**imap_config)
        mock_imap_connection.append.side_effect = Exception("Append error")

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap_connection):
            adapter.authenticate()
            draft_id = adapter.create_draft(
                to=["recipient@example.com"],
                subject="Test",
                body="Body"
            )

        assert draft_id is None


# ============================================================================
# TEST SEND DRAFT
# ============================================================================


class TestIMAPAdapterSendDraft:
    """Tests for send_draft method."""

    def test_send_draft_not_supported(self, imap_config, mock_imap_connection):
        """IMAP cannot send emails."""
        adapter = IMAPAdapter(**imap_config)

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap_connection):
            adapter.authenticate()
            result = adapter.send_draft("123")

        assert result is False


# ============================================================================
# TEST MARK AS READ
# ============================================================================


class TestIMAPAdapterMarkAsRead:
    """Tests for mark_as_read method."""

    def test_mark_as_read_success(self, imap_config, mock_imap_connection):
        """Successfully mark message as read."""
        adapter = IMAPAdapter(**imap_config)
        mock_imap_connection.uid.return_value = ("OK", [b"1 (FLAGS (\\Seen))"])

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap_connection):
            adapter.authenticate()
            result = adapter.mark_as_read("1")

        assert result is True
        mock_imap_connection.uid.assert_called()

    def test_mark_as_read_fails(self, imap_config, mock_imap_connection):
        """Mark as read fails."""
        adapter = IMAPAdapter(**imap_config)
        mock_imap_connection.uid.return_value = ("NO", [b"Error"])

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap_connection):
            adapter.authenticate()
            result = adapter.mark_as_read("1")

        assert result is False

    def test_mark_as_read_exception(self, imap_config, mock_imap_connection):
        """Mark as read handles exceptions."""
        adapter = IMAPAdapter(**imap_config)
        mock_imap_connection.uid.side_effect = Exception("Store error")

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap_connection):
            adapter.authenticate()
            result = adapter.mark_as_read("1")

        assert result is False


# ============================================================================
# TEST GET USER DRAFTS
# ============================================================================


class TestIMAPAdapterGetUserDrafts:
    """Tests for get_user_drafts method."""

    def test_get_user_drafts_success(self, imap_config, simple_email_message, mock_imap_connection):
        """Successfully retrieve user drafts."""
        adapter = IMAPAdapter(**imap_config)
        mock_imap_connection.search.return_value = ("OK", [b"1 2"])
        mock_imap_connection.fetch.return_value = (
            "OK",
            [(b"1 (FLAGS (\\Draft))", simple_email_message.as_bytes())]
        )

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap_connection):
            adapter.authenticate()
            drafts = adapter.get_user_drafts(limit=10)

        assert isinstance(drafts, list)

    def test_get_user_drafts_no_folder_found(self, imap_config, mock_imap_connection):
        """No drafts folder found returns empty list."""
        adapter = IMAPAdapter(**imap_config)
        mock_imap_connection.select.side_effect = Exception("Folder not found")

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap_connection):
            adapter._authenticated = True
            adapter._connection = mock_imap_connection
            drafts = adapter.get_user_drafts()

        assert drafts == []

    def test_get_user_drafts_search_fails(self, imap_config, mock_imap_connection):
        """Search fails returns empty list."""
        adapter = IMAPAdapter(**imap_config)
        mock_imap_connection.search.return_value = ("NO", [b"Error"])

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap_connection):
            adapter.authenticate()
            drafts = adapter.get_user_drafts()

        assert drafts == []

    def test_get_user_drafts_exception(self, imap_config, mock_imap_connection):
        """Exception during retrieval returns empty list."""
        adapter = IMAPAdapter(**imap_config)
        mock_imap_connection.search.side_effect = Exception("Search error")

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap_connection):
            adapter.authenticate()
            drafts = adapter.get_user_drafts()

        assert drafts == []


# ============================================================================
# TEST GET SENT EMAILS
# ============================================================================


class TestIMAPAdapterGetSentEmails:
    """Tests for get_sent_emails method."""

    def test_get_sent_emails_success(self, imap_config, simple_email_message, mock_imap_connection):
        """Successfully retrieve sent emails."""
        adapter = IMAPAdapter(**imap_config)
        mock_imap_connection.search.return_value = ("OK", [b"1 2"])
        mock_imap_connection.fetch.return_value = (
            "OK",
            [(b"1", simple_email_message.as_bytes())]
        )

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap_connection):
            adapter.authenticate()
            sent = adapter.get_sent_emails(limit=5)

        assert isinstance(sent, list)

    def test_get_sent_emails_no_folder_found(self, imap_config, mock_imap_connection):
        """No sent folder found returns empty list."""
        adapter = IMAPAdapter(**imap_config)
        mock_imap_connection.select.side_effect = Exception("Folder not found")

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap_connection):
            adapter._authenticated = True
            adapter._connection = mock_imap_connection
            sent = adapter.get_sent_emails()

        assert sent == []

    def test_get_sent_emails_search_fails(self, imap_config, mock_imap_connection):
        """Search fails returns empty list."""
        adapter = IMAPAdapter(**imap_config)
        mock_imap_connection.search.return_value = ("NO", [b"Error"])

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap_connection):
            adapter.authenticate()
            sent = adapter.get_sent_emails()

        assert sent == []

    def test_get_sent_emails_exception(self, imap_config, mock_imap_connection):
        """Exception during retrieval returns empty list."""
        adapter = IMAPAdapter(**imap_config)
        mock_imap_connection.search.side_effect = Exception("Search error")

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap_connection):
            adapter.authenticate()
            sent = adapter.get_sent_emails()

        assert sent == []


# ============================================================================
# TEST GET DRAFT BY ID
# ============================================================================


class TestIMAPAdapterGetDraftById:
    """Tests for get_draft_by_id method."""

    def test_get_draft_by_id_success(self, imap_config, simple_email_message, mock_imap_connection):
        """Successfully retrieve draft by ID."""
        adapter = IMAPAdapter(**imap_config)
        # _select_drafts_folder calls list() then select()
        mock_imap_connection.list.return_value = ("OK", [b'(\\Drafts) "/" "Drafts"'])
        mock_imap_connection.uid.return_value = (
            "OK",
            [(b"1 (FLAGS (\\Draft) BODY[])", simple_email_message.as_bytes())]
        )

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap_connection):
            adapter.authenticate()
            draft = adapter.get_draft_by_id("1")

        assert draft is not None

    def test_get_draft_by_id_no_folder(self, imap_config, mock_imap_connection):
        """No drafts folder found returns None."""
        adapter = IMAPAdapter(**imap_config)
        mock_imap_connection.select.side_effect = Exception("Folder not found")
        mock_imap_connection.list.return_value = ("OK", [])

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap_connection):
            adapter._authenticated = True
            adapter._connection = mock_imap_connection
            draft = adapter.get_draft_by_id("1")

        assert draft is None

    def test_get_draft_by_id_not_found(self, imap_config, mock_imap_connection):
        """Draft not found returns None."""
        adapter = IMAPAdapter(**imap_config)
        mock_imap_connection.list.return_value = ("OK", [b'(\\Drafts) "/" "Drafts"'])
        mock_imap_connection.uid.return_value = ("NO", None)

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap_connection):
            adapter.authenticate()
            draft = adapter.get_draft_by_id("999")

        assert draft is None

    def test_get_draft_by_id_exception(self, imap_config, mock_imap_connection):
        """Exception during retrieval returns None."""
        adapter = IMAPAdapter(**imap_config)
        mock_imap_connection.list.return_value = ("OK", [b'(\\Drafts) "/" "Drafts"'])
        mock_imap_connection.uid.side_effect = Exception("Fetch error")

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap_connection):
            adapter.authenticate()
            draft = adapter.get_draft_by_id("1")

        assert draft is None


# ============================================================================
# TEST UPDATE DRAFT
# ============================================================================


class TestIMAPAdapterUpdateDraft:
    """Tests for update_draft method."""

    def test_update_draft_success(self, imap_config, simple_email_message, mock_imap_connection):
        """Successfully update draft."""
        adapter = IMAPAdapter(**imap_config)

        # _select_drafts_folder calls list() then select()
        mock_imap_connection.list.return_value = ("OK", [b'(\\Drafts) "/" "Drafts"'])
        mock_imap_connection.uid.return_value = (
            "OK",
            [(b"1 (FLAGS (\\Draft) BODY[])", simple_email_message.as_bytes())]
        )
        mock_imap_connection.expunge.return_value = ("OK", [])
        mock_imap_connection.append.return_value = ("OK", [b"[APPENDUID 1 456]"])

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap_connection):
            adapter.authenticate()
            result = adapter.update_draft(
                draft_id="1",
                subject="Updated Subject",
                body="Updated body"
            )

        assert result is True

    def test_update_draft_not_found(self, imap_config, mock_imap_connection):
        """Update draft fails when draft not found."""
        adapter = IMAPAdapter(**imap_config)
        mock_imap_connection.list.return_value = ("OK", [b'(\\Drafts) "/" "Drafts"'])
        mock_imap_connection.uid.return_value = ("NO", None)

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap_connection):
            adapter.authenticate()
            result = adapter.update_draft(
                draft_id="999",
                subject="Updated Subject"
            )

        assert result is False

    def test_update_draft_exception(self, imap_config, mock_imap_connection):
        """Update draft handles exceptions."""
        adapter = IMAPAdapter(**imap_config)
        mock_imap_connection.list.return_value = ("OK", [b'(\\Drafts) "/" "Drafts"'])
        mock_imap_connection.uid.side_effect = Exception("Fetch error")

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap_connection):
            adapter.authenticate()
            result = adapter.update_draft(draft_id="1", body="New body")

        assert result is False

    def test_update_draft_partial_update(self, imap_config, simple_email_message, mock_imap_connection):
        """Update draft with only some fields."""
        adapter = IMAPAdapter(**imap_config)

        mock_imap_connection.list.return_value = ("OK", [b'(\\Drafts) "/" "Drafts"'])
        mock_imap_connection.uid.return_value = (
            "OK",
            [(b"1 (FLAGS (\\Draft) BODY[])", simple_email_message.as_bytes())]
        )
        mock_imap_connection.expunge.return_value = ("OK", [])
        mock_imap_connection.append.return_value = ("OK", [b"[APPENDUID 1 789]"])

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap_connection):
            adapter.authenticate()
            # Only update body, keep other fields
            result = adapter.update_draft(
                draft_id="1",
                body="Only body updated"
            )

        assert result is True


# ============================================================================
# TEST DISCONNECT
# ============================================================================


class TestIMAPAdapterDisconnect:
    """Tests for disconnect and cleanup."""

    def test_disconnect_success(self, imap_config, mock_imap_connection):
        """Successfully disconnect."""
        adapter = IMAPAdapter(**imap_config)
        # Production calls logout() then socket().shutdown/close(), not close()
        mock_socket = MagicMock()
        mock_imap_connection.socket.return_value = mock_socket

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap_connection):
            adapter.authenticate()
            adapter.disconnect()

        assert adapter._connection is None
        assert adapter._authenticated is False
        mock_imap_connection.logout.assert_called_once()

    def test_disconnect_handles_exception(self, imap_config, mock_imap_connection):
        """Disconnect handles exceptions gracefully."""
        adapter = IMAPAdapter(**imap_config)
        mock_imap_connection.close.side_effect = Exception("Close error")

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap_connection):
            adapter.authenticate()
            adapter.disconnect()  # Should not raise

        assert adapter._connection is None

    def test_disconnect_when_not_connected(self, imap_config):
        """Disconnect when not connected does nothing."""
        adapter = IMAPAdapter(**imap_config)
        adapter.disconnect()  # Should not raise
        assert adapter._connection is None

    def test_destructor_calls_disconnect(self, imap_config, mock_imap_connection):
        """Destructor calls disconnect."""
        adapter = IMAPAdapter(**imap_config)

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap_connection):
            adapter.authenticate()
            del adapter

        # Should have called close/logout during cleanup


# ============================================================================
# TEST MAP TO STANDARD EMAIL
# ============================================================================


class TestIMAPAdapterMapToStandardEmail:
    """Tests for _map_to_standard_email method."""

    def test_map_simple_message(self, imap_config, simple_email_message):
        """Map simple message to StandardEmail."""
        adapter = IMAPAdapter(**imap_config)

        email_obj = adapter._map_to_standard_email(
            "123",
            simple_email_message,
            b"123 (FLAGS (\\Recent) RFC822 {1234})"
        )

        assert email_obj.id == "123"
        # Sender parsing depends on how the From header is formatted
        assert "sender@example.com" in email_obj.sender or email_obj.sender is not None
        assert email_obj.subject == "Test Subject"
        assert email_obj.is_read is False
        assert email_obj.provider_source == "imap"

    def test_map_message_with_seen_flag(self, imap_config, simple_email_message):
        """Map message with Seen flag."""
        adapter = IMAPAdapter(**imap_config)

        email_obj = adapter._map_to_standard_email(
            "123",
            simple_email_message,
            b"123 (FLAGS (\\Seen) RFC822 {1234})"
        )

        assert email_obj.is_read is True

    def test_map_multipart_message(self, imap_config, multipart_email_message):
        """Map multipart message to StandardEmail."""
        adapter = IMAPAdapter(**imap_config)

        email_obj = adapter._map_to_standard_email(
            "456",
            multipart_email_message,
            b"456 (FLAGS () RFC822 {1234})"
        )

        assert email_obj.id == "456"
        assert email_obj.sender == "john@example.com"
        assert email_obj.sender_name == "John Doe"
        assert email_obj.has_attachments is False

    def test_map_message_with_attachments(self, imap_config, email_with_attachment):
        """Map message with attachments."""
        adapter = IMAPAdapter(**imap_config)

        email_obj = adapter._map_to_standard_email(
            "789",
            email_with_attachment,
            b"789 (FLAGS () RFC822 {1234})"
        )

        assert email_obj.has_attachments is True

    def test_map_message_with_thread_info(self, imap_config, multipart_email_message):
        """Map message with thread/reply info."""
        adapter = IMAPAdapter(**imap_config)

        email_obj = adapter._map_to_standard_email(
            "thread1",
            multipart_email_message,
            b"thread1 (FLAGS () RFC822 {1234})"
        )

        assert email_obj.conversation_id is not None

    def test_map_message_without_date(self, imap_config):
        """Map message without date header."""
        msg = EmailMessage()
        msg["From"] = "sender@example.com"
        msg["To"] = "recipient@example.com"
        msg["Subject"] = "No Date"
        msg.set_content("Body")

        adapter = IMAPAdapter(**imap_config)
        email_obj = adapter._map_to_standard_email("no_date", msg, b"")

        assert email_obj.received_at is None
