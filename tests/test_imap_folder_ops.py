# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests unitaires pour les nouvelles opérations de dossiers IMAP.

pytest tests/test_imap_folder_ops.py -v
"""

import time
import pytest
from unittest.mock import MagicMock, patch


from app.providers.imap_adapter import IMAPAdapter


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def imap_config():
    return {
        "host": "imap.test.com",
        "port": 993,
        "username": "user@test.com",
        "password": "password123",
        "use_ssl": True,
        "folder": "INBOX",
    }


@pytest.fixture
def gmail_config():
    return {
        "host": "imap.gmail.com",
        "port": 993,
        "username": "user@gmail.com",
        "password": "password123",
        "use_ssl": True,
        "folder": "INBOX",
    }


@pytest.fixture
def mock_imap_connection():
    mock = MagicMock()
    mock.login.return_value = ("OK", [b"Logged in"])
    mock.select.return_value = ("OK", [b"5"])
    mock.uid.return_value = ("OK", [b""])
    mock.expunge.return_value = ("OK", [b""])
    mock.list.return_value = ("OK", [
        b'(\\HasNoChildren \\Archive) "/" "Archive"',
        b'(\\HasNoChildren \\Trash) "/" "Trash"',
        b'(\\HasNoChildren \\Junk) "/" "Spam"',
        b'(\\HasNoChildren) "/" "INBOX"',
    ])
    return mock


def make_adapter(config, mock_conn):
    """Helper: create adapter with mocked IMAP connection."""
    with patch("imaplib.IMAP4_SSL", return_value=mock_conn):
        adapter = IMAPAdapter(**config)
        adapter._connection = mock_conn
        adapter._authenticated = True
        adapter._auth_time = time.time()  # éviter le NOOP check dans _ensure_authenticated
    return adapter


# ============================================================================
# Tests: restore_from_trash
# ============================================================================


class TestRestoreFromTrash:
    def test_restore_copies_to_inbox_then_deletes(self, imap_config, mock_imap_connection):
        adapter = make_adapter(imap_config, mock_imap_connection)
        adapter._trash_folder_name = "Trash"

        # _select_trash_folder selects "Trash"; then copy + delete
        mock_imap_connection.select.return_value = ("OK", [b"3"])
        mock_imap_connection.uid.return_value = ("OK", [b""])

        result = adapter.restore_from_trash("42")

        assert result is True
        # Should call uid copy to INBOX
        uid_calls = mock_imap_connection.uid.call_args_list
        copy_calls = [c for c in uid_calls if c[0][0] == 'copy']
        assert len(copy_calls) == 1
        assert copy_calls[0][0][2] == 'INBOX'

    def test_restore_returns_false_when_trash_folder_not_found(self, imap_config, mock_imap_connection):
        adapter = make_adapter(imap_config, mock_imap_connection)
        # Make folder detection fail
        mock_imap_connection.list.return_value = ("OK", [])
        mock_imap_connection.select.return_value = ("NO", [b"No folder"])

        result = adapter.restore_from_trash("42")

        assert result is False

    def test_restore_returns_false_when_copy_fails(self, imap_config, mock_imap_connection):
        adapter = make_adapter(imap_config, mock_imap_connection)
        adapter._trash_folder_name = "Trash"

        def uid_side_effect(cmd, *args):
            if cmd == 'copy':
                return ("NO", [b"Copy failed"])
            return ("OK", [b""])

        mock_imap_connection.uid.side_effect = uid_side_effect

        result = adapter.restore_from_trash("42")

        assert result is False

    def test_restore_handles_exception(self, imap_config, mock_imap_connection):
        adapter = make_adapter(imap_config, mock_imap_connection)
        adapter._trash_folder_name = "Trash"
        # Simuler une exception réseau lors de uid('copy')
        mock_imap_connection.uid.side_effect = Exception("Connection error")

        result = adapter.restore_from_trash("42")

        assert result is False


# ============================================================================
# Tests: move_to_spam
# ============================================================================


class TestMoveToSpam:
    def test_move_to_spam_copies_and_deletes(self, imap_config, mock_imap_connection):
        adapter = make_adapter(imap_config, mock_imap_connection)
        adapter._spam_folder_name = "Spam"

        mock_imap_connection.uid.return_value = ("OK", [b""])

        result = adapter.move_to_spam("42")

        assert result is True
        uid_calls = mock_imap_connection.uid.call_args_list
        copy_calls = [c for c in uid_calls if c[0][0] == 'copy']
        assert len(copy_calls) == 1
        assert copy_calls[0][0][2] == "Spam"

    def test_move_to_spam_returns_false_when_spam_folder_not_found(self, imap_config, mock_imap_connection):
        adapter = make_adapter(imap_config, mock_imap_connection)
        mock_imap_connection.list.return_value = ("OK", [])
        mock_imap_connection.select.return_value = ("NO", [b"No folder"])

        result = adapter.move_to_spam("42")

        assert result is False

    def test_move_to_spam_returns_false_when_copy_fails(self, imap_config, mock_imap_connection):
        adapter = make_adapter(imap_config, mock_imap_connection)
        adapter._spam_folder_name = "Spam"

        def uid_side_effect(cmd, *args):
            if cmd == 'copy':
                return ("NO", [b"Copy failed"])
            return ("OK", [b""])

        mock_imap_connection.uid.side_effect = uid_side_effect

        result = adapter.move_to_spam("42")

        assert result is False

    def test_move_to_spam_handles_exception(self, imap_config, mock_imap_connection):
        adapter = make_adapter(imap_config, mock_imap_connection)
        adapter._spam_folder_name = "Spam"
        # Simuler une exception réseau lors de uid('copy')
        mock_imap_connection.uid.side_effect = Exception("Connection error")

        result = adapter.move_to_spam("42")

        assert result is False


# ============================================================================
# Tests: unarchive_email
# ============================================================================


class TestUnarchiveEmail:
    def test_unarchive_standard_imap_copies_and_deletes(self, imap_config, mock_imap_connection):
        """Standard IMAP: unarchive = COPY to INBOX + DELETE from archive."""
        adapter = make_adapter(imap_config, mock_imap_connection)
        adapter._archived_folder_name = "Archive"

        mock_imap_connection.uid.return_value = ("OK", [b""])

        result = adapter.unarchive_email("42")

        assert result is True
        uid_calls = mock_imap_connection.uid.call_args_list
        copy_calls = [c for c in uid_calls if c[0][0] == 'copy']
        store_calls = [c for c in uid_calls if c[0][0] == 'store']
        assert len(copy_calls) == 1
        assert copy_calls[0][0][2] == 'INBOX'
        # Should also delete from archive
        assert len(store_calls) == 1
        assert "\\Deleted" in str(store_calls[0])

    def test_unarchive_gmail_imap_copies_only(self, gmail_config, mock_imap_connection):
        """Gmail IMAP: unarchive = COPY to INBOX only (no delete from All Mail)."""
        # Update list to include Gmail All Mail with \All flag
        mock_imap_connection.list.return_value = ("OK", [
            b'(\\HasNoChildren \\All) "/" "[Gmail]/All Mail"',
        ])
        adapter = make_adapter(gmail_config, mock_imap_connection)
        adapter._archived_folder_name = "[Gmail]/All Mail"

        mock_imap_connection.uid.return_value = ("OK", [b""])

        result = adapter.unarchive_email("42")

        assert result is True
        uid_calls = mock_imap_connection.uid.call_args_list
        copy_calls = [c for c in uid_calls if c[0][0] == 'copy']
        store_calls = [c for c in uid_calls if c[0][0] == 'store']
        assert len(copy_calls) == 1
        assert copy_calls[0][0][2] == 'INBOX'
        # Gmail: should NOT delete from All Mail
        assert len(store_calls) == 0

    def test_unarchive_returns_false_when_archive_folder_not_found(self, imap_config, mock_imap_connection):
        adapter = make_adapter(imap_config, mock_imap_connection)
        mock_imap_connection.list.return_value = ("OK", [])
        mock_imap_connection.select.return_value = ("NO", [b"No folder"])

        result = adapter.unarchive_email("42")

        assert result is False

    def test_unarchive_returns_false_when_copy_fails(self, imap_config, mock_imap_connection):
        adapter = make_adapter(imap_config, mock_imap_connection)
        adapter._archived_folder_name = "Archive"

        def uid_side_effect(cmd, *args):
            if cmd == 'copy':
                return ("NO", [b"Copy failed"])
            return ("OK", [b""])

        mock_imap_connection.uid.side_effect = uid_side_effect

        result = adapter.unarchive_email("42")

        assert result is False


# ============================================================================
# Tests: archive_email (fix for non-Gmail)
# ============================================================================


class TestArchiveEmail:
    def test_archive_standard_imap_copies_to_archive_then_deletes(self, imap_config, mock_imap_connection):
        """Non-Gmail IMAP: archive = COPY to Archive folder + DELETE from INBOX."""
        adapter = make_adapter(imap_config, mock_imap_connection)
        adapter._archived_folder_name = "Archive"

        mock_imap_connection.uid.return_value = ("OK", [b""])

        result = adapter.archive_email("42")

        assert result is True
        uid_calls = mock_imap_connection.uid.call_args_list
        copy_calls = [c for c in uid_calls if c[0][0] == 'copy']
        assert len(copy_calls) == 1
        assert copy_calls[0][0][2] == "Archive"

    def test_archive_gmail_imap_uses_expunge(self, gmail_config, mock_imap_connection):
        """Gmail IMAP: archive = mark Deleted + expunge (removes INBOX label)."""
        adapter = make_adapter(gmail_config, mock_imap_connection)

        mock_imap_connection.uid.return_value = ("OK", [b""])

        result = adapter.archive_email("42")

        assert result is True
        # Gmail path should NOT use COPY
        uid_calls = mock_imap_connection.uid.call_args_list
        copy_calls = [c for c in uid_calls if c[0][0] == 'copy']
        assert len(copy_calls) == 0
        # Should call expunge
        mock_imap_connection.expunge.assert_called()

    def test_archive_standard_imap_returns_false_when_archive_folder_not_found(self, imap_config, mock_imap_connection):
        adapter = make_adapter(imap_config, mock_imap_connection)
        mock_imap_connection.list.return_value = ("OK", [])
        mock_imap_connection.select.return_value = ("NO", [b"No folder"])

        result = adapter.archive_email("42")

        assert result is False

    def test_archive_standard_imap_returns_false_when_copy_fails(self, imap_config, mock_imap_connection):
        adapter = make_adapter(imap_config, mock_imap_connection)
        adapter._archived_folder_name = "Archive"

        def uid_side_effect(cmd, *args):
            if cmd == 'copy':
                return ("NO", [b"Copy failed"])
            return ("OK", [b""])

        mock_imap_connection.uid.side_effect = uid_side_effect

        result = adapter.archive_email("42")

        assert result is False


# ============================================================================
# Tests: _select_archive_folder
# ============================================================================


class TestSelectArchiveFolder:
    def test_detect_archive_folder_via_flag(self, imap_config, mock_imap_connection):
        """Standard IMAP: detect Archive via \\Archive flag."""
        mock_imap_connection.list.return_value = ("OK", [
            b'(\\HasNoChildren \\Archive) "/" "Archive"',
            b'(\\HasNoChildren) "/" "INBOX"',
        ])
        adapter = make_adapter(imap_config, mock_imap_connection)

        result = adapter._select_archive_folder()

        assert result == "Archive"

    def test_detect_all_mail_on_gmail(self, gmail_config, mock_imap_connection):
        """Gmail IMAP: detect All Mail via \\All flag."""
        mock_imap_connection.list.return_value = ("OK", [
            b'(\\HasNoChildren \\All) "/" "[Gmail]/All Mail"',
            b'(\\HasNoChildren) "/" "INBOX"',
        ])
        adapter = make_adapter(gmail_config, mock_imap_connection)

        result = adapter._select_archive_folder()

        assert result == "[Gmail]/All Mail"

    def test_fallback_to_archive_name(self, imap_config, mock_imap_connection):
        """Fallback to hardcoded 'Archive' folder name if no flag detected."""
        # No flags in list
        mock_imap_connection.list.return_value = ("OK", [
            b'(\\HasNoChildren) "/" "Archive"',
            b'(\\HasNoChildren) "/" "INBOX"',
        ])
        adapter = make_adapter(imap_config, mock_imap_connection)

        result = adapter._select_archive_folder()

        assert result == "Archive"

    def test_returns_empty_string_when_not_found(self, imap_config, mock_imap_connection):
        """Returns '' when archive folder cannot be found."""
        mock_imap_connection.list.return_value = ("OK", [
            b'(\\HasNoChildren) "/" "INBOX"',
        ])
        mock_imap_connection.select.return_value = ("NO", [b"No such mailbox"])

        adapter = make_adapter(imap_config, mock_imap_connection)

        result = adapter._select_archive_folder()

        assert result == ""
