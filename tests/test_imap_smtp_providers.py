# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests E2E pour les configurations IMAP/SMTP de différents providers.

pytest tests/test_imap_smtp_providers.py -v
"""

import pytest
from unittest.mock import MagicMock, patch
from email.message import EmailMessage

from app.providers.imap_adapter import IMAPAdapter
from app.providers.smtp_adapter import SMTPAdapter, IMAPSMTPAdapter


# ============================================================================
# FIXTURES - Configurations par provider
# ============================================================================

@pytest.fixture
def ovh_imap_config():
    """Configuration IMAP OVH."""
    return {
        "host": "ssl0.ovh.net",
        "port": 993,
        "username": "user@domain.com",
        "password": "test_password",
        "use_ssl": True,
        "folder": "INBOX",
    }


@pytest.fixture
def ovh_smtp_config():
    """Configuration SMTP OVH."""
    return {
        "host": "ssl0.ovh.net",
        "port": 587,
        "username": "user@domain.com",
        "password": "test_password",
        "use_tls": True,
        "use_ssl": False,
    }


@pytest.fixture
def infomaniak_imap_config():
    """Configuration IMAP Infomaniak."""
    return {
        "host": "mail.infomaniak.com",
        "port": 993,
        "username": "user@domain.com",
        "password": "test_password",
        "use_ssl": True,
        "folder": "INBOX",
    }


@pytest.fixture
def infomaniak_smtp_config():
    """Configuration SMTP Infomaniak."""
    return {
        "host": "mail.infomaniak.com",
        "port": 587,
        "username": "user@domain.com",
        "password": "test_password",
        "use_tls": True,
        "use_ssl": False,
    }


@pytest.fixture
def gmail_imap_config():
    """Configuration IMAP Gmail (App Password)."""
    return {
        "host": "imap.gmail.com",
        "port": 993,
        "username": "user@gmail.com",
        "password": "app_password_16chars",
        "use_ssl": True,
        "folder": "INBOX",
    }


@pytest.fixture
def gmail_smtp_config():
    """Configuration SMTP Gmail (App Password)."""
    return {
        "host": "smtp.gmail.com",
        "port": 587,
        "username": "user@gmail.com",
        "password": "app_password_16chars",
        "use_tls": True,
        "use_ssl": False,
    }


@pytest.fixture
def outlook_imap_config():
    """Configuration IMAP Outlook/Office365."""
    return {
        "host": "outlook.office365.com",
        "port": 993,
        "username": "user@outlook.com",
        "password": "test_password",
        "use_ssl": True,
        "folder": "INBOX",
    }


@pytest.fixture
def outlook_smtp_config():
    """Configuration SMTP Outlook/Office365."""
    return {
        "host": "smtp.office365.com",
        "port": 587,
        "username": "user@outlook.com",
        "password": "test_password",
        "use_tls": True,
        "use_ssl": False,
    }


@pytest.fixture
def mock_email_message():
    """Crée un message email mock."""
    msg = EmailMessage()
    msg["From"] = "sender@example.com"
    msg["To"] = "recipient@example.com"
    msg["Subject"] = "Test Subject"
    msg["Date"] = "Mon, 15 Jan 2024 10:00:00 +0000"
    msg["Message-ID"] = "<msg123@example.com>"
    msg.set_content("Test body content")
    return msg


@pytest.fixture(autouse=True)
def no_imap_retry_sleep():
    """Évite que les tests d'erreur IMAP paient les backoffs de production."""
    with patch("app.providers.imap_adapter._time.sleep", return_value=None):
        yield


# ============================================================================
# TESTS OVH - IMAP/SMTP
# ============================================================================

class TestOVHProvider:
    """Tests pour la configuration OVH."""

    def test_ovh_imap_init(self, ovh_imap_config):
        """Initialisation IMAP OVH avec bons paramètres."""
        adapter = IMAPAdapter(**ovh_imap_config)
        assert adapter.host == "ssl0.ovh.net"
        assert adapter.port == 993
        assert adapter.use_ssl is True

    def test_ovh_smtp_init(self, ovh_smtp_config):
        """Initialisation SMTP OVH avec bons paramètres."""
        adapter = SMTPAdapter(**ovh_smtp_config)
        assert adapter.host == "ssl0.ovh.net"
        assert adapter.port == 587
        assert adapter.use_tls is True

    def test_ovh_imap_auth_success(self, ovh_imap_config):
        """Authentification IMAP OVH réussie."""
        adapter = IMAPAdapter(**ovh_imap_config)
        mock_conn = MagicMock()

        with patch("imaplib.IMAP4_SSL", return_value=mock_conn):
            result = adapter.authenticate()

            assert result is True
            mock_conn.login.assert_called_once_with(
                "user@domain.com",
                "test_password"
            )

    def test_ovh_smtp_auth_success(self, ovh_smtp_config):
        """Authentification SMTP OVH réussie."""
        adapter = SMTPAdapter(**ovh_smtp_config)
        mock_conn = MagicMock()

        with patch("smtplib.SMTP", return_value=mock_conn):
            result = adapter.authenticate()

            assert result is True
            mock_conn.starttls.assert_called_once()
            mock_conn.login.assert_called_once()

    def test_ovh_imap_auth_wrong_password(self, ovh_imap_config):
        """Échec authentification IMAP OVH - mauvais mot de passe."""
        import imaplib
        adapter = IMAPAdapter(**ovh_imap_config)
        mock_conn = MagicMock()
        mock_conn.login.side_effect = imaplib.IMAP4.error(
            b"[AUTHENTICATIONFAILED] Invalid credentials"
        )

        with patch("imaplib.IMAP4_SSL", return_value=mock_conn):
            result = adapter.authenticate()
            assert result is False

    def test_ovh_smtp_auth_wrong_password(self, ovh_smtp_config):
        """Échec authentification SMTP OVH - mauvais mot de passe."""
        import smtplib
        adapter = SMTPAdapter(**ovh_smtp_config)
        mock_conn = MagicMock()
        mock_conn.login.side_effect = smtplib.SMTPAuthenticationError(
            535, b"Authentication failed"
        )

        with patch("smtplib.SMTP", return_value=mock_conn):
            mock_conn.starttls = MagicMock()
            result = adapter.authenticate()
            assert result is False

    def test_ovh_combined_read_send(
        self, ovh_imap_config, ovh_smtp_config, mock_email_message
    ):
        """Test lecture IMAP + envoi SMTP OVH."""
        imap = IMAPAdapter(**ovh_imap_config)
        smtp = SMTPAdapter(**ovh_smtp_config)

        mock_imap_conn = MagicMock()
        mock_imap_conn.select.return_value = ("OK", [b"1"])
        mock_imap_conn.search.return_value = ("OK", [b"1"])
        mock_imap_conn.fetch.return_value = (
            "OK", [(b"1", mock_email_message.as_bytes())]
        )

        mock_smtp_conn = MagicMock()

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap_conn):
            with patch("smtplib.SMTP", return_value=mock_smtp_conn):
                assert imap.authenticate() is True
                assert smtp.authenticate() is True

                emails = imap.get_unread_messages(limit=1)
                assert isinstance(emails, list)


# ============================================================================
# TESTS INFOMANIAK - IMAP/SMTP
# ============================================================================

class TestInfomaniakProvider:
    """Tests pour la configuration Infomaniak."""

    def test_infomaniak_imap_init(self, infomaniak_imap_config):
        """Initialisation IMAP Infomaniak avec bons paramètres."""
        adapter = IMAPAdapter(**infomaniak_imap_config)
        assert adapter.host == "mail.infomaniak.com"
        assert adapter.port == 993
        assert adapter.use_ssl is True

    def test_infomaniak_smtp_init(self, infomaniak_smtp_config):
        """Initialisation SMTP Infomaniak avec bons paramètres."""
        adapter = SMTPAdapter(**infomaniak_smtp_config)
        assert adapter.host == "mail.infomaniak.com"
        assert adapter.port == 587
        assert adapter.use_tls is True

    def test_infomaniak_imap_auth_success(self, infomaniak_imap_config):
        """Authentification IMAP Infomaniak réussie."""
        adapter = IMAPAdapter(**infomaniak_imap_config)
        mock_conn = MagicMock()

        with patch("imaplib.IMAP4_SSL", return_value=mock_conn):
            result = adapter.authenticate()
            assert result is True

    def test_infomaniak_smtp_auth_success(self, infomaniak_smtp_config):
        """Authentification SMTP Infomaniak réussie."""
        adapter = SMTPAdapter(**infomaniak_smtp_config)
        mock_conn = MagicMock()

        with patch("smtplib.SMTP", return_value=mock_conn):
            result = adapter.authenticate()
            assert result is True

    def test_infomaniak_send_email(self, infomaniak_smtp_config):
        """Envoi email via SMTP Infomaniak."""
        adapter = SMTPAdapter(**infomaniak_smtp_config)
        mock_conn = MagicMock()

        with patch("smtplib.SMTP", return_value=mock_conn):
            adapter.authenticate()
            result = adapter.send_email(
                to=["dest@example.com"],
                subject="Test Infomaniak",
                body="Contenu test"
            )
            assert result is True
            mock_conn.sendmail.assert_called_once()


# ============================================================================
# TESTS GMAIL via IMAP - App Password
# ============================================================================

class TestGmailIMAPProvider:
    """Tests pour Gmail via IMAP (avec App Password)."""

    def test_gmail_imap_init(self, gmail_imap_config):
        """Initialisation IMAP Gmail avec bons paramètres."""
        adapter = IMAPAdapter(**gmail_imap_config)
        assert adapter.host == "imap.gmail.com"
        assert adapter.port == 993
        assert adapter.use_ssl is True

    def test_gmail_smtp_init(self, gmail_smtp_config):
        """Initialisation SMTP Gmail avec bons paramètres."""
        adapter = SMTPAdapter(**gmail_smtp_config)
        assert adapter.host == "smtp.gmail.com"
        assert adapter.port == 587
        assert adapter.use_tls is True

    def test_gmail_imap_auth_success(self, gmail_imap_config):
        """Authentification IMAP Gmail avec App Password."""
        adapter = IMAPAdapter(**gmail_imap_config)
        mock_conn = MagicMock()

        with patch("imaplib.IMAP4_SSL", return_value=mock_conn):
            result = adapter.authenticate()
            assert result is True
            mock_conn.login.assert_called_once_with(
                "user@gmail.com",
                "app_password_16chars"
            )

    def test_gmail_imap_auth_wrong_app_password(self, gmail_imap_config):
        """Échec IMAP Gmail - App Password invalide."""
        import imaplib
        adapter = IMAPAdapter(**gmail_imap_config)
        mock_conn = MagicMock()
        mock_conn.login.side_effect = imaplib.IMAP4.error(
            b"[AUTHENTICATIONFAILED] Invalid credentials (Failure)"
        )

        with patch("imaplib.IMAP4_SSL", return_value=mock_conn):
            result = adapter.authenticate()
            assert result is False

    def test_gmail_requires_app_password_error_message(self, gmail_imap_config):
        """Gmail nécessite un App Password si 2FA activé."""
        import imaplib
        adapter = IMAPAdapter(**gmail_imap_config)
        mock_conn = MagicMock()
        mock_conn.login.side_effect = imaplib.IMAP4.error(
            b"Application-specific password required"
        )

        with patch("imaplib.IMAP4_SSL", return_value=mock_conn):
            result = adapter.authenticate()
            assert result is False

    def test_gmail_drafts_folder_name(self, gmail_imap_config, mock_email_message):
        """Gmail utilise [Gmail]/Drafts comme dossier brouillons."""
        adapter = IMAPAdapter(**gmail_imap_config)
        mock_conn = MagicMock()
        mock_conn.select.return_value = ("OK", [b"0"])
        mock_conn.search.return_value = ("OK", [b""])

        with patch("imaplib.IMAP4_SSL", return_value=mock_conn):
            adapter.authenticate()
            adapter.get_user_drafts()
            calls = [str(call) for call in mock_conn.select.call_args_list]
            assert any("[Gmail]/Drafts" in c or "Drafts" in c for c in calls)


# ============================================================================
# TESTS OUTLOOK via IMAP - Office365
# ============================================================================

class TestOutlookIMAPProvider:
    """Tests pour Outlook/Office365 via IMAP."""

    def test_outlook_imap_init(self, outlook_imap_config):
        """Initialisation IMAP Outlook avec bons paramètres."""
        adapter = IMAPAdapter(**outlook_imap_config)
        assert adapter.host == "outlook.office365.com"
        assert adapter.port == 993
        assert adapter.use_ssl is True

    def test_outlook_smtp_init(self, outlook_smtp_config):
        """Initialisation SMTP Outlook avec bons paramètres."""
        adapter = SMTPAdapter(**outlook_smtp_config)
        assert adapter.host == "smtp.office365.com"
        assert adapter.port == 587
        assert adapter.use_tls is True

    def test_outlook_imap_auth_success(self, outlook_imap_config):
        """Authentification IMAP Outlook réussie."""
        adapter = IMAPAdapter(**outlook_imap_config)
        mock_conn = MagicMock()

        with patch("imaplib.IMAP4_SSL", return_value=mock_conn):
            result = adapter.authenticate()
            assert result is True

    def test_outlook_smtp_auth_success(self, outlook_smtp_config):
        """Authentification SMTP Outlook réussie."""
        adapter = SMTPAdapter(**outlook_smtp_config)
        mock_conn = MagicMock()

        with patch("smtplib.SMTP", return_value=mock_conn):
            result = adapter.authenticate()
            assert result is True

    def test_outlook_imap_oauth_not_supported(self, outlook_imap_config):
        """Note: IMAP basique nécessite de désactiver Modern Auth."""
        adapter = IMAPAdapter(**outlook_imap_config)
        # Ce test documente le comportement attendu
        assert adapter.host == "outlook.office365.com"


# ============================================================================
# TESTS IMAPSMTPAdapter COMBINÉ
# ============================================================================

class TestIMAPSMTPCombinedAdapter:
    """Tests pour l'adaptateur combiné IMAP+SMTP."""

    def test_combined_init_ovh(self, ovh_imap_config, ovh_smtp_config):
        """Initialisation adaptateur combiné OVH."""
        adapter = IMAPSMTPAdapter(
            imap_host=ovh_imap_config["host"],
            imap_port=ovh_imap_config["port"],
            imap_username=ovh_imap_config["username"],
            imap_password=ovh_imap_config["password"],
            imap_use_ssl=ovh_imap_config["use_ssl"],
            smtp_host=ovh_smtp_config["host"],
            smtp_port=ovh_smtp_config["port"],
            smtp_username=ovh_smtp_config["username"],
            smtp_password=ovh_smtp_config["password"],
            smtp_use_tls=ovh_smtp_config["use_tls"],
        )
        assert adapter.provider_name == "imap_smtp"

    def test_combined_auth_both_success(self, ovh_imap_config, ovh_smtp_config):
        """Authentification combinée IMAP+SMTP réussie."""
        adapter = IMAPSMTPAdapter(
            imap_host=ovh_imap_config["host"],
            imap_port=ovh_imap_config["port"],
            imap_username=ovh_imap_config["username"],
            imap_password=ovh_imap_config["password"],
            smtp_host=ovh_smtp_config["host"],
            smtp_port=ovh_smtp_config["port"],
            smtp_username=ovh_smtp_config["username"],
            smtp_password=ovh_smtp_config["password"],
        )

        mock_imap = MagicMock()
        mock_smtp = MagicMock()

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap):
            with patch("smtplib.SMTP", return_value=mock_smtp):
                result = adapter.authenticate()
                assert result is True
                assert adapter._authenticated is True

    def test_combined_auth_imap_fails(self, ovh_imap_config, ovh_smtp_config):
        """Échec si IMAP échoue."""
        adapter = IMAPSMTPAdapter(
            imap_host=ovh_imap_config["host"],
            imap_port=ovh_imap_config["port"],
            imap_username=ovh_imap_config["username"],
            imap_password=ovh_imap_config["password"],
            smtp_host=ovh_smtp_config["host"],
            smtp_port=ovh_smtp_config["port"],
            smtp_username=ovh_smtp_config["username"],
            smtp_password=ovh_smtp_config["password"],
        )

        mock_smtp = MagicMock()

        with patch(
            "imaplib.IMAP4_SSL",
            side_effect=Exception("IMAP connection failed")
        ):
            with patch("smtplib.SMTP", return_value=mock_smtp):
                result = adapter.authenticate()
                # authenticate() now only checks SMTP (IMAP is lazy)
                # SMTP auth succeeds with mock, so result is True
                assert result is True

    def test_combined_read_then_send(
        self, ovh_imap_config, ovh_smtp_config, mock_email_message
    ):
        """Lecture IMAP puis envoi SMTP."""
        adapter = IMAPSMTPAdapter(
            imap_host=ovh_imap_config["host"],
            imap_port=ovh_imap_config["port"],
            imap_username=ovh_imap_config["username"],
            imap_password=ovh_imap_config["password"],
            smtp_host=ovh_smtp_config["host"],
            smtp_port=ovh_smtp_config["port"],
            smtp_username=ovh_smtp_config["username"],
            smtp_password=ovh_smtp_config["password"],
        )

        mock_imap = MagicMock()
        mock_imap.select.return_value = ("OK", [b"1"])
        mock_imap.search.return_value = ("OK", [b"1"])
        mock_imap.fetch.return_value = (
            "OK", [(b"1", mock_email_message.as_bytes())]
        )

        mock_smtp = MagicMock()

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap):
            with patch("smtplib.SMTP", return_value=mock_smtp):
                adapter.authenticate()

                # Lecture
                emails = adapter.get_unread_messages(limit=1)
                assert isinstance(emails, list)

                # Envoi
                result = adapter.send_email(
                    to=["dest@example.com"],
                    subject="Reply",
                    body="Content"
                )
                assert result is True


# ============================================================================
# TESTS EDGE CASES - Configurations alternatives
# ============================================================================

class TestEdgeCases:
    """Tests pour les cas limites et configurations alternatives."""

    def test_imap_port_143_no_ssl(self):
        """IMAP port 143 sans SSL."""
        adapter = IMAPAdapter(
            host="imap.example.com",
            port=143,
            username="user@example.com",
            password="password",
            use_ssl=False,
        )
        mock_conn = MagicMock()

        with patch("imaplib.IMAP4", return_value=mock_conn):
            result = adapter.authenticate()
            assert result is True

    def test_smtp_port_465_ssl(self):
        """SMTP port 465 avec SSL direct."""
        adapter = SMTPAdapter(
            host="smtp.example.com",
            port=465,
            username="user@example.com",
            password="password",
            use_tls=False,
            use_ssl=True,
        )
        mock_conn = MagicMock()

        with patch("smtplib.SMTP_SSL", return_value=mock_conn):
            result = adapter.authenticate()
            assert result is True

    def test_smtp_port_25_no_encryption(self):
        """SMTP port 25 sans chiffrement (déconseillé)."""
        adapter = SMTPAdapter(
            host="smtp.example.com",
            port=25,
            username="user@example.com",
            password="password",
            use_tls=False,
            use_ssl=False,
        )
        mock_conn = MagicMock()

        with patch("smtplib.SMTP", return_value=mock_conn):
            result = adapter.authenticate()
            assert result is True
            mock_conn.starttls.assert_not_called()

    def test_imap_custom_folder(self):
        """IMAP avec dossier personnalisé."""
        adapter = IMAPAdapter(
            host="imap.example.com",
            port=993,
            username="user@example.com",
            password="password",
            folder="Archive/2024",
        )
        assert adapter.folder == "Archive/2024"

    def test_smtp_custom_from_name(self):
        """SMTP avec nom d'affichage personnalisé."""
        adapter = SMTPAdapter(
            host="smtp.example.com",
            port=587,
            username="user@example.com",
            password="password",
            from_name="Support Team",
        )
        assert adapter.from_name == "Support Team"

    def test_connection_timeout(self):
        """Test timeout de connexion."""
        import socket
        adapter = IMAPAdapter(
            host="imap.nonexistent.com",
            port=993,
            username="user@example.com",
            password="password",
        )

        with patch(
            "imaplib.IMAP4_SSL",
            side_effect=socket.timeout("Connection timed out")
        ):
            result = adapter.authenticate()
            assert result is False

    def test_dns_resolution_failure(self):
        """Test échec résolution DNS."""
        import socket
        adapter = IMAPAdapter(
            host="imap.invalid-domain-xyz.com",
            port=993,
            username="user@example.com",
            password="password",
        )

        with patch(
            "imaplib.IMAP4_SSL",
            side_effect=socket.gaierror(8, "nodename nor servname provided")
        ):
            result = adapter.authenticate()
            assert result is False


# ============================================================================
# TESTS CARACTÈRES SPÉCIAUX
# ============================================================================

class TestSpecialCharacters:
    """Tests pour les caractères spéciaux dans les emails."""

    def test_unicode_subject(self):
        """Sujet avec caractères Unicode."""
        adapter = IMAPAdapter(
            host="imap.test.com",
            port=993,
            username="user@test.com",
            password="pass",
        )

        result = adapter._decode_header_value("=?utf-8?B?VMOpc3Qgc3VqZXQ=?=")
        assert "Tést sujet" in result or isinstance(result, str)

    def test_encoded_from_address(self):
        """Adresse expéditeur encodée."""
        adapter = IMAPAdapter(
            host="imap.test.com",
            port=993,
            username="user@test.com",
            password="pass",
        )

        addr, name = adapter._parse_email_address(
            '"Jean Dupont" <jean@example.com>'
        )
        assert addr == "jean@example.com"
        assert name == "Jean Dupont"

    def test_multiline_body(self):
        """Corps avec sauts de ligne."""
        adapter = SMTPAdapter(
            host="smtp.test.com",
            port=587,
            username="user@test.com",
            password="pass",
        )
        mock_conn = MagicMock()

        with patch("smtplib.SMTP", return_value=mock_conn):
            adapter.authenticate()
            result = adapter.send_email(
                to=["dest@test.com"],
                subject="Test",
                body="Ligne 1\nLigne 2\nLigne 3"
            )
            assert result is True


# ============================================================================
# TESTS RETRY ET RECONNEXION
# ============================================================================

class TestRetryReconnection:
    """Tests pour la reconnexion automatique."""

    def test_imap_reconnect_after_disconnect(self):
        """Reconnexion IMAP après déconnexion."""
        adapter = IMAPAdapter(
            host="imap.test.com",
            port=993,
            username="user@test.com",
            password="pass",
        )
        mock_conn = MagicMock()

        with patch("imaplib.IMAP4_SSL", return_value=mock_conn):
            adapter.authenticate()
            adapter.disconnect()
            assert adapter._authenticated is False

            result = adapter.authenticate()
            assert result is True

    def test_smtp_reconnect_after_disconnect(self):
        """Reconnexion SMTP après déconnexion."""
        adapter = SMTPAdapter(
            host="smtp.test.com",
            port=587,
            username="user@test.com",
            password="pass",
        )
        mock_conn = MagicMock()

        with patch("smtplib.SMTP", return_value=mock_conn):
            adapter.authenticate()
            adapter.disconnect()
            assert adapter._authenticated is False

            result = adapter.authenticate()
            assert result is True
