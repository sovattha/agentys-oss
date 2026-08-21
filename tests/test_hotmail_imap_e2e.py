# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests E2E IMAP Hotmail/Outlook.com.

Couvre :
- Connexion à imap-mail.outlook.com et outlook.office365.com
- Détection des dossiers Hotmail : "Sent Items", "Deleted Items", "Junk", "Drafts"
- Opérations sur dossiers : archive, spam, restauration, envoyés
- SMTP : smtp.office365.com:587 + STARTTLS

pytest tests/test_hotmail_imap_e2e.py -v
"""

import imaplib
import os
import time
import pytest
from unittest.mock import MagicMock, patch

from app.providers.imap_adapter import (
    IMAPAdapter,
    _ARCHIVE_FOLDER_GLOBAL_CACHE,
    _DRAFTS_FOLDER_GLOBAL_CACHE,
    _SENT_FOLDER_GLOBAL_CACHE,
    _SPAM_FOLDER_GLOBAL_CACHE,
    _TRASH_FOLDER_GLOBAL_CACHE,
)
from app.providers.smtp_adapter import SMTPAdapter


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture(autouse=True)
def clear_folder_caches():
    """Vide les caches de dossiers IMAP globaux avant et après chaque test."""
    for cache in (
        _SENT_FOLDER_GLOBAL_CACHE,
        _SPAM_FOLDER_GLOBAL_CACHE,
        _TRASH_FOLDER_GLOBAL_CACHE,
        _DRAFTS_FOLDER_GLOBAL_CACHE,
        _ARCHIVE_FOLDER_GLOBAL_CACHE,
    ):
        cache.clear()
    yield
    for cache in (
        _SENT_FOLDER_GLOBAL_CACHE,
        _SPAM_FOLDER_GLOBAL_CACHE,
        _TRASH_FOLDER_GLOBAL_CACHE,
        _DRAFTS_FOLDER_GLOBAL_CACHE,
        _ARCHIVE_FOLDER_GLOBAL_CACHE,
    ):
        cache.clear()


@pytest.fixture
def hotmail_config():
    return {
        "host": "imap-mail.outlook.com",
        "port": 993,
        "username": "user@hotmail.com",
        "password": "password123",
        "use_ssl": True,
        "folder": "INBOX",
    }


@pytest.fixture
def mock_hotmail_imap():
    """Mock IMAP4_SSL avec la structure de dossiers Hotmail/Outlook.com."""
    mock = MagicMock()
    mock.login.return_value = ("OK", [b"Logged in"])
    mock.select.return_value = ("OK", [b"10"])
    mock.uid.return_value = ("OK", [b""])
    mock.expunge.return_value = ("OK", [b""])
    mock.list.return_value = ("OK", [
        b'(\\HasNoChildren \\Sent) "/" "Sent Items"',
        b'(\\Trash \\HasNoChildren) "/" "Deleted Items"',
        b'(\\Junk \\HasNoChildren) "/" "Junk"',
        b'(\\Drafts \\HasNoChildren) "/" "Drafts"',
        b'(\\HasNoChildren) "/" "INBOX"',
    ])
    return mock


@pytest.fixture
def mock_hotmail_imap_archive():
    """Mock avec 'Deleted Items' configuré comme dossier d'archive (\\Archive flag)."""
    mock = MagicMock()
    mock.login.return_value = ("OK", [b"Logged in"])
    mock.select.return_value = ("OK", [b"5"])
    mock.uid.return_value = ("OK", [b""])
    mock.expunge.return_value = ("OK", [b""])
    mock.list.return_value = ("OK", [
        b'(\\HasNoChildren \\Archive) "/" "Deleted Items"',
        b'(\\HasNoChildren) "/" "INBOX"',
    ])
    return mock


def make_hotmail_adapter(config, mock_conn):
    """Crée un IMAPAdapter avec une connexion Hotmail mockée."""
    with patch("imaplib.IMAP4_SSL", return_value=mock_conn):
        adapter = IMAPAdapter(**config)
        adapter._connection = mock_conn
        adapter._authenticated = True
        adapter._auth_time = time.time()
    return adapter


# ============================================================================
# Tests : Connexion Hotmail
# ============================================================================


class TestHotmailConnection:
    def test_connects_to_imap_mail_outlook_com(self):
        """IMAPAdapter s'instancie sans erreur pour imap-mail.outlook.com."""
        adapter = IMAPAdapter(
            host="imap-mail.outlook.com",
            port=993,
            username="test@hotmail.com",
            password="pwd",
        )
        assert adapter.host == "imap-mail.outlook.com"
        assert adapter.port == 993
        assert adapter.use_ssl is True

    def test_connects_to_outlook_office365_com(self):
        """Preset alternatif outlook.office365.com s'instancie sans erreur."""
        adapter = IMAPAdapter(
            host="outlook.office365.com",
            port=993,
            username="test@company.com",
            password="pwd",
        )
        assert adapter.host == "outlook.office365.com"
        assert adapter.port == 993

    def test_auth_failure_raises_clear_error(self, hotmail_config):
        """Échec LOGIN IMAP → authenticate() retourne False (pas d'exception)."""
        mock_conn = MagicMock()
        mock_conn.login.side_effect = imaplib.IMAP4.error("[AUTHENTICATIONFAILED] Invalid credentials")
        with patch("imaplib.IMAP4_SSL", return_value=mock_conn):
            adapter = IMAPAdapter(**hotmail_config)
            result = adapter.authenticate()
        assert result is False
        assert adapter._authenticated is False


# ============================================================================
# Tests : Détection des dossiers Hotmail
# ============================================================================


class TestHotmailFolderDetection:
    def test_sent_folder_resolves_to_sent_items(self, hotmail_config, mock_hotmail_imap):
        """_select_sent_folder() détecte 'Sent Items' via le flag \\Sent."""
        adapter = make_hotmail_adapter(hotmail_config, mock_hotmail_imap)

        adapter._select_sent_folder()

        # Le dossier mis en cache doit être "Sent Items", pas "Sent"
        assert adapter._sent_folder_name == "Sent Items"

    def test_trash_folder_resolves_to_deleted_items(self, hotmail_config, mock_hotmail_imap):
        """_select_trash_folder() détecte 'Deleted Items' via le flag \\Trash."""
        adapter = make_hotmail_adapter(hotmail_config, mock_hotmail_imap)

        result = adapter._select_trash_folder()

        assert result == "Deleted Items"
        assert adapter._trash_folder_name == "Deleted Items"

    def test_spam_folder_resolves_to_junk(self, hotmail_config, mock_hotmail_imap):
        """_select_spam_folder() détecte 'Junk' via le flag \\Junk."""
        adapter = make_hotmail_adapter(hotmail_config, mock_hotmail_imap)

        result = adapter._select_spam_folder()

        assert result == "Junk"
        assert adapter._spam_folder_name == "Junk"

    def test_drafts_folder_resolves_to_drafts(self, hotmail_config, mock_hotmail_imap):
        """_select_drafts_folder() détecte 'Drafts' via le flag \\Drafts."""
        adapter = make_hotmail_adapter(hotmail_config, mock_hotmail_imap)

        result = adapter._select_drafts_folder()

        assert result == "Drafts"
        assert adapter._drafts_folder_name == "Drafts"

    def test_folder_detection_uses_imap_flags_first(self, hotmail_config, mock_hotmail_imap):
        """\\Trash flag sur 'Deleted Items' → détecté par flag avant les noms hardcodés."""
        # Mock LIST avec flag \Trash sur "Deleted Items" uniquement
        mock_hotmail_imap.list.return_value = ("OK", [
            b'(\\Trash \\HasNoChildren) "/" "Deleted Items"',
            b'(\\HasNoChildren) "/" "Trash"',  # "Trash" existe aussi mais sans flag
            b'(\\HasNoChildren) "/" "INBOX"',
        ])
        adapter = make_hotmail_adapter(hotmail_config, mock_hotmail_imap)

        result = adapter._select_trash_folder()

        # Doit retourner "Deleted Items" (via flag), pas "Trash" (via nom)
        assert result == "Deleted Items"

    def test_folder_fallback_when_no_flags(self, hotmail_config):
        """Sans flags IMAP, le fallback par nom trouve 'Sent Items'."""
        mock_conn = MagicMock()
        mock_conn.login.return_value = ("OK", [b"Logged in"])
        mock_conn.expunge.return_value = ("OK", [b""])
        # LIST sans flags IMAP
        mock_conn.list.return_value = ("OK", [
            b'(\\HasNoChildren) "/" "Sent Items"',
            b'(\\HasNoChildren) "/" "INBOX"',
        ])

        def select_side_effect(folder_name, **kwargs):
            clean = folder_name.strip('"')
            # Seul "Sent Items" existe sur ce serveur fictif
            if clean == "Sent Items":
                return ("OK", [b"5"])
            return ("NO", [b"[NONEXISTENT] Folder not found"])

        mock_conn.select.side_effect = select_side_effect

        adapter = make_hotmail_adapter(hotmail_config, mock_conn)

        adapter._select_sent_folder()

        # Sans flag \Sent, le fallback par nom trouve "Sent Items"
        assert adapter._sent_folder_name == "Sent Items"


# ============================================================================
# Tests : Opérations sur dossiers Hotmail
# ============================================================================


class TestHotmailFolderOperations:
    def test_archive_copies_to_deleted_items(self, hotmail_config, mock_hotmail_imap_archive):
        """archive_email() copie vers 'Deleted Items' quand il porte le flag \\Archive."""
        adapter = make_hotmail_adapter(hotmail_config, mock_hotmail_imap_archive)

        result = adapter.archive_email("42")

        assert result is True
        uid_calls = mock_hotmail_imap_archive.uid.call_args_list
        copy_calls = [c for c in uid_calls if c[0][0] == "copy"]
        assert len(copy_calls) == 1
        assert copy_calls[0][0][2] == "Deleted Items"

    def test_archive_never_targets_trash(self, hotmail_config, mock_hotmail_imap_archive):
        """archive_email() ne copie jamais vers un dossier nommé 'Trash'."""
        adapter = make_hotmail_adapter(hotmail_config, mock_hotmail_imap_archive)

        adapter.archive_email("42")

        uid_calls = mock_hotmail_imap_archive.uid.call_args_list
        copy_to_trash = [
            c for c in uid_calls
            if c[0][0] == "copy" and c[0][2] == "Trash"
        ]
        assert len(copy_to_trash) == 0

    def test_move_to_spam_copies_to_junk(self, hotmail_config, mock_hotmail_imap):
        """move_to_spam() copie vers 'Junk' (pas 'Spam') sur Hotmail."""
        adapter = make_hotmail_adapter(hotmail_config, mock_hotmail_imap)

        result = adapter.move_to_spam("42")

        assert result is True
        uid_calls = mock_hotmail_imap.uid.call_args_list
        copy_calls = [c for c in uid_calls if c[0][0] == "copy"]
        assert len(copy_calls) == 1
        assert copy_calls[0][0][2] == "Junk"

    def test_move_to_spam_never_targets_spam_folder(self, hotmail_config, mock_hotmail_imap):
        """move_to_spam() ne copie jamais vers un dossier nommé 'Spam'."""
        adapter = make_hotmail_adapter(hotmail_config, mock_hotmail_imap)

        adapter.move_to_spam("42")

        uid_calls = mock_hotmail_imap.uid.call_args_list
        copy_to_spam = [
            c for c in uid_calls
            if c[0][0] == "copy" and c[0][2] == "Spam"
        ]
        assert len(copy_to_spam) == 0

    def test_restore_from_deleted_items_to_inbox(self, hotmail_config, mock_hotmail_imap):
        """restore_from_trash() identifie 'Deleted Items' et copie vers INBOX."""
        adapter = make_hotmail_adapter(hotmail_config, mock_hotmail_imap)

        result = adapter.restore_from_trash("42")

        assert result is True
        # Le dossier trash détecté doit être "Deleted Items"
        assert adapter._trash_folder_name == "Deleted Items"
        # COPY vers INBOX
        uid_calls = mock_hotmail_imap.uid.call_args_list
        copy_calls = [c for c in uid_calls if c[0][0] == "copy"]
        assert len(copy_calls) == 1
        assert copy_calls[0][0][2] == "INBOX"

    def test_restore_from_junk_to_inbox(self, hotmail_config, mock_hotmail_imap):
        """move_to_inbox() sélectionne 'Junk' et copie vers INBOX."""
        adapter = make_hotmail_adapter(hotmail_config, mock_hotmail_imap)

        result = adapter.move_to_inbox("42")

        assert result is True
        assert adapter._spam_folder_name == "Junk"
        uid_calls = mock_hotmail_imap.uid.call_args_list
        copy_calls = [c for c in uid_calls if c[0][0] == "copy"]
        assert len(copy_calls) == 1
        assert copy_calls[0][0][2] == "INBOX"

    def test_sent_list_selects_sent_items(self, hotmail_config, mock_hotmail_imap):
        """get_sent_emails() sélectionne le dossier 'Sent Items' via flag \\Sent."""
        mock_hotmail_imap.fetch.return_value = ("NO", [b""])
        adapter = make_hotmail_adapter(hotmail_config, mock_hotmail_imap)

        adapter.get_sent_emails()

        # "Sent Items" doit être mis en cache après la détection
        assert adapter._sent_folder_name == "Sent Items"
        # SELECT doit avoir été appelé avec "Sent Items"
        select_calls = [str(c) for c in mock_hotmail_imap.select.call_args_list]
        assert any("Sent Items" in c for c in select_calls)

    def test_returns_false_when_deleted_items_not_found(self, hotmail_config):
        """restore_from_trash() retourne False si aucun dossier trash trouvé."""
        mock_conn = MagicMock()
        mock_conn.login.return_value = ("OK", [b"Logged in"])
        mock_conn.list.return_value = ("OK", [])  # Aucun dossier
        mock_conn.select.return_value = ("NO", [b"[NONEXISTENT]"])

        adapter = make_hotmail_adapter(hotmail_config, mock_conn)

        result = adapter.restore_from_trash("42")

        assert result is False


# ============================================================================
# Tests : SMTP Hotmail/Outlook
# ============================================================================


class TestHotmailSMTP:
    def test_smtp_connects_to_office365_port_587(self):
        """SMTPAdapter s'instancie correctement pour smtp.office365.com:587."""
        adapter = SMTPAdapter(
            host="smtp.office365.com",
            port=587,
            username="user@hotmail.com",
            password="password",
            use_tls=True,
            use_ssl=False,
        )
        assert adapter.host == "smtp.office365.com"
        assert adapter.port == 587
        assert adapter.use_tls is True
        assert adapter.use_ssl is False

    def test_smtp_auth_failure_propagates(self):
        """Échec AUTH SMTP → authenticate() retourne False (pas d'exception levée)."""
        import smtplib

        adapter = SMTPAdapter(
            host="smtp.office365.com",
            port=587,
            username="user@hotmail.com",
            password="bad_password",
            use_tls=True,
        )

        with patch("smtplib.SMTP") as mock_smtp_cls:
            mock_smtp = MagicMock()
            mock_smtp_cls.return_value = mock_smtp
            mock_smtp.login.side_effect = smtplib.SMTPAuthenticationError(
                535, b"Authentication credentials invalid"
            )
            result = adapter.authenticate()

        assert result is False
        assert adapter._authenticated is False


# ============================================================================
# Tests : E2E réel Hotmail (skippés sans credentials)
# ============================================================================


HOTMAIL_USER = os.getenv("HOTMAIL_USER")
HOTMAIL_PASSWORD = os.getenv("HOTMAIL_PASSWORD")
_skip_real = pytest.mark.skipif(
    not (HOTMAIL_USER and HOTMAIL_PASSWORD),
    reason="HOTMAIL_USER et HOTMAIL_PASSWORD requis pour les tests réels",
)


class TestHotmailRealE2E:
    @_skip_real
    def test_real_imap_login(self):
        """Connexion réelle à imap-mail.outlook.com:993."""
        adapter = IMAPAdapter(
            host="imap-mail.outlook.com",
            port=993,
            username=HOTMAIL_USER,
            password=HOTMAIL_PASSWORD,
        )
        result = adapter.authenticate()
        assert result is True, "Échec authentification IMAP Hotmail réelle"

    @_skip_real
    def test_real_folder_detection(self):
        """Détection réelle des dossiers Hotmail (Sent Items, Deleted Items, Junk)."""
        adapter = IMAPAdapter(
            host="imap-mail.outlook.com",
            port=993,
            username=HOTMAIL_USER,
            password=HOTMAIL_PASSWORD,
        )
        adapter.authenticate()

        trash = adapter._select_trash_folder()
        spam = adapter._select_spam_folder()

        assert trash in ("Deleted Items", "Trash"), f"Dossier trash inattendu : {trash}"
        assert spam in ("Junk", "Spam"), f"Dossier spam inattendu : {spam}"

    @_skip_real
    def test_real_smtp_starttls(self):
        """Connexion SMTP réelle à smtp.office365.com:587 avec STARTTLS."""
        adapter = SMTPAdapter(
            host="smtp.office365.com",
            port=587,
            username=HOTMAIL_USER,
            password=HOTMAIL_PASSWORD,
            use_tls=True,
        )
        result = adapter.authenticate()
        assert result is True, "Échec authentification SMTP Hotmail réelle"
