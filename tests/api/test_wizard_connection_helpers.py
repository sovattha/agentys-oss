# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests unitaires pour les helpers de connexion dans wizard.py.

Couvre:
- _validate_connection_params() - validation parametres connexion
- _test_imap_connection() - test connexion IMAP
- _test_smtp_connection() - test connexion SMTP
"""

from unittest.mock import patch, MagicMock

from app.api.wizard import (
    _validate_connection_params,
    _test_imap_connection,
    _test_smtp_connection,
    DEFAULT_IMAP_PORT,
    DEFAULT_SMTP_PORT,
)


class TestValidateConnectionParams:
    """Tests pour _validate_connection_params()."""

    def test_missing_imap_host(self):
        """Retourne erreur si imap_host manquant."""
        data = {
            "smtp_host": "smtp.example.com",
            "imap_username": "user",
            "smtp_username": "user",
        }
        valid, error = _validate_connection_params(data)
        assert valid is False
        assert "imap_host" in error

    def test_missing_smtp_host(self):
        """Retourne erreur si smtp_host manquant."""
        data = {
            "imap_host": "imap.example.com",
            "imap_username": "user",
            "smtp_username": "user",
        }
        valid, error = _validate_connection_params(data)
        assert valid is False
        assert "smtp_host" in error

    def test_missing_imap_username(self):
        """Retourne erreur si imap_username manquant."""
        data = {
            "imap_host": "imap.example.com",
            "smtp_host": "smtp.example.com",
            "smtp_username": "user",
        }
        valid, error = _validate_connection_params(data)
        assert valid is False
        assert "imap_username" in error

    def test_missing_smtp_username(self):
        """Retourne erreur si smtp_username manquant."""
        data = {
            "imap_host": "imap.example.com",
            "smtp_host": "smtp.example.com",
            "imap_username": "user",
        }
        valid, error = _validate_connection_params(data)
        assert valid is False
        assert "smtp_username" in error

    def test_invalid_imap_port_too_low(self):
        """Retourne erreur si imap_port trop bas."""
        data = {
            "imap_host": "imap.example.com",
            "smtp_host": "smtp.example.com",
            "imap_username": "user",
            "smtp_username": "user",
            "imap_port": 0,
        }
        valid, error = _validate_connection_params(data)
        assert valid is False
        assert "imap_port" in error

    def test_invalid_imap_port_too_high(self):
        """Retourne erreur si imap_port trop haut."""
        data = {
            "imap_host": "imap.example.com",
            "smtp_host": "smtp.example.com",
            "imap_username": "user",
            "smtp_username": "user",
            "imap_port": 70000,
        }
        valid, error = _validate_connection_params(data)
        assert valid is False
        assert "imap_port" in error

    def test_invalid_smtp_port_too_low(self):
        """Retourne erreur si smtp_port trop bas."""
        data = {
            "imap_host": "imap.example.com",
            "smtp_host": "smtp.example.com",
            "imap_username": "user",
            "smtp_username": "user",
            "smtp_port": 0,
        }
        valid, error = _validate_connection_params(data)
        assert valid is False
        assert "smtp_port" in error

    def test_invalid_smtp_port_too_high(self):
        """Retourne erreur si smtp_port trop haut."""
        data = {
            "imap_host": "imap.example.com",
            "smtp_host": "smtp.example.com",
            "imap_username": "user",
            "smtp_username": "user",
            "smtp_port": 70000,
        }
        valid, error = _validate_connection_params(data)
        assert valid is False
        assert "smtp_port" in error

    def test_valid_params_minimal(self):
        """Valide les parametres minimaux."""
        data = {
            "imap_host": "imap.example.com",
            "smtp_host": "smtp.example.com",
            "imap_username": "user",
            "smtp_username": "user",
        }
        valid, error = _validate_connection_params(data)
        assert valid is True
        assert error is None

    def test_valid_params_with_ports(self):
        """Valide les parametres avec ports."""
        data = {
            "imap_host": "imap.example.com",
            "smtp_host": "smtp.example.com",
            "imap_username": "user",
            "smtp_username": "user",
            "imap_port": 993,
            "smtp_port": 587,
        }
        valid, error = _validate_connection_params(data)
        assert valid is True
        assert error is None

    def test_uses_default_ports(self):
        """Utilise les ports par defaut si non specifies."""
        data = {
            "imap_host": "imap.example.com",
            "smtp_host": "smtp.example.com",
            "imap_username": "user",
            "smtp_username": "user",
        }
        valid, _ = _validate_connection_params(data)
        assert valid is True


class TestTestImapConnection:
    """Tests pour _test_imap_connection()."""

    def test_successful_connection(self):
        """Retourne succes si connexion reussie."""
        with patch("app.api.wizard.IMAPAdapter") as mock_imap:
            mock_instance = MagicMock()
            mock_instance.authenticate.return_value = True
            mock_imap.return_value = mock_instance

            result = _test_imap_connection({
                "imap_host": "imap.example.com",
                "imap_port": 993,
                "imap_username": "user",
                "imap_password": "password",
                "imap_use_ssl": True,
            })

            assert result["success"] is True
            assert "response_time_ms" in result

    def test_failed_authentication(self):
        """Retourne échec si authentification échoue."""
        with patch("app.api.wizard.IMAPAdapter") as mock_imap:
            mock_instance = MagicMock()
            mock_instance.authenticate.return_value = False
            mock_imap.return_value = mock_instance

            result = _test_imap_connection({
                "imap_host": "imap.example.com",
                "imap_username": "user",
                "imap_password": "wrong",
            })

            assert result["success"] is False

    def test_connection_exception(self):
        """Retourne erreur si exception lors de la connexion."""
        with patch("app.api.wizard.IMAPAdapter") as mock_imap:
            mock_imap.side_effect = Exception("Connection refused")

            result = _test_imap_connection({
                "imap_host": "invalid.example.com",
                "imap_username": "user",
                "imap_password": "password",
            })

            assert result["success"] is False
            assert "error" in result
            assert "Connection refused" in result["error"]

    def test_uses_default_port(self):
        """Utilise le port par defaut si non specifie."""
        with patch("app.api.wizard.IMAPAdapter") as mock_imap:
            mock_instance = MagicMock()
            mock_instance.authenticate.return_value = True
            mock_imap.return_value = mock_instance

            _test_imap_connection({
                "imap_host": "imap.example.com",
                "imap_username": "user",
            })

            mock_imap.assert_called_once()
            call_kwargs = mock_imap.call_args[1]
            assert call_kwargs["port"] == DEFAULT_IMAP_PORT

    def test_uses_default_ssl(self):
        """Utilise SSL par defaut."""
        with patch("app.api.wizard.IMAPAdapter") as mock_imap:
            mock_instance = MagicMock()
            mock_instance.authenticate.return_value = True
            mock_imap.return_value = mock_instance

            _test_imap_connection({
                "imap_host": "imap.example.com",
                "imap_username": "user",
            })

            call_kwargs = mock_imap.call_args[1]
            assert call_kwargs["use_ssl"] is True

    def test_disconnects_after_test(self):
        """Deconnecte apres le test."""
        with patch("app.api.wizard.IMAPAdapter") as mock_imap:
            mock_instance = MagicMock()
            mock_instance.authenticate.return_value = True
            mock_imap.return_value = mock_instance

            _test_imap_connection({
                "imap_host": "imap.example.com",
                "imap_username": "user",
            })

            mock_instance.disconnect.assert_called()

    def test_disconnect_exception_ignored(self):
        """Ignore les exceptions lors de la deconnexion."""
        with patch("app.api.wizard.IMAPAdapter") as mock_imap:
            mock_instance = MagicMock()
            mock_instance.authenticate.return_value = True
            mock_instance.disconnect.side_effect = Exception("Disconnect error")
            mock_imap.return_value = mock_instance

            result = _test_imap_connection({
                "imap_host": "imap.example.com",
                "imap_username": "user",
            })

            # Should still succeed despite disconnect error
            assert result["success"] is True


class TestTestSmtpConnection:
    """Tests pour _test_smtp_connection()."""

    def test_successful_connection(self):
        """Retourne succes si connexion reussie."""
        with patch("app.api.wizard.SMTPAdapter") as mock_smtp:
            mock_instance = MagicMock()
            mock_instance.authenticate.return_value = True
            mock_smtp.return_value = mock_instance

            result = _test_smtp_connection({
                "smtp_host": "smtp.example.com",
                "smtp_port": 587,
                "smtp_username": "user",
                "smtp_password": "password",
                "smtp_use_tls": True,
            })

            assert result["success"] is True
            assert "response_time_ms" in result

    def test_failed_authentication(self):
        """Retourne échec si authentification échoue."""
        with patch("app.api.wizard.SMTPAdapter") as mock_smtp:
            mock_instance = MagicMock()
            mock_instance.authenticate.return_value = False
            mock_smtp.return_value = mock_instance

            result = _test_smtp_connection({
                "smtp_host": "smtp.example.com",
                "smtp_username": "user",
                "smtp_password": "wrong",
            })

            assert result["success"] is False

    def test_connection_exception(self):
        """Retourne erreur si exception lors de la connexion."""
        with patch("app.api.wizard.SMTPAdapter") as mock_smtp:
            mock_smtp.side_effect = Exception("Connection refused")

            result = _test_smtp_connection({
                "smtp_host": "invalid.example.com",
                "smtp_username": "user",
                "smtp_password": "password",
            })

            assert result["success"] is False
            assert "error" in result
            assert "Connection refused" in result["error"]

    def test_uses_default_port(self):
        """Utilise le port par defaut si non specifie."""
        with patch("app.api.wizard.SMTPAdapter") as mock_smtp:
            mock_instance = MagicMock()
            mock_instance.authenticate.return_value = True
            mock_smtp.return_value = mock_instance

            _test_smtp_connection({
                "smtp_host": "smtp.example.com",
                "smtp_username": "user",
            })

            mock_smtp.assert_called_once()
            call_kwargs = mock_smtp.call_args[1]
            assert call_kwargs["port"] == DEFAULT_SMTP_PORT

    def test_uses_default_tls(self):
        """Utilise TLS par defaut."""
        with patch("app.api.wizard.SMTPAdapter") as mock_smtp:
            mock_instance = MagicMock()
            mock_instance.authenticate.return_value = True
            mock_smtp.return_value = mock_instance

            _test_smtp_connection({
                "smtp_host": "smtp.example.com",
                "smtp_username": "user",
            })

            call_kwargs = mock_smtp.call_args[1]
            assert call_kwargs["use_tls"] is True

    def test_uses_default_ssl_false(self):
        """SSL est False par defaut."""
        with patch("app.api.wizard.SMTPAdapter") as mock_smtp:
            mock_instance = MagicMock()
            mock_instance.authenticate.return_value = True
            mock_smtp.return_value = mock_instance

            _test_smtp_connection({
                "smtp_host": "smtp.example.com",
                "smtp_username": "user",
            })

            call_kwargs = mock_smtp.call_args[1]
            assert call_kwargs["use_ssl"] is False

    def test_disconnects_after_test(self):
        """Deconnecte apres le test."""
        with patch("app.api.wizard.SMTPAdapter") as mock_smtp:
            mock_instance = MagicMock()
            mock_instance.authenticate.return_value = True
            mock_smtp.return_value = mock_instance

            _test_smtp_connection({
                "smtp_host": "smtp.example.com",
                "smtp_username": "user",
            })

            mock_instance.disconnect.assert_called()

    def test_disconnect_exception_ignored(self):
        """Ignore les exceptions lors de la deconnexion."""
        with patch("app.api.wizard.SMTPAdapter") as mock_smtp:
            mock_instance = MagicMock()
            mock_instance.authenticate.return_value = True
            mock_instance.disconnect.side_effect = Exception("Disconnect error")
            mock_smtp.return_value = mock_instance

            result = _test_smtp_connection({
                "smtp_host": "smtp.example.com",
                "smtp_username": "user",
            })

            # Should still succeed despite disconnect error
            assert result["success"] is True
