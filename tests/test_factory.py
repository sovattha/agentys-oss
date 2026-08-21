# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour la factory de providers.
"""

import os
import pytest
from unittest.mock import patch

from app.providers.factory import (
    get_email_provider,
    list_available_providers,
    validate_provider_config,
    ProviderConfigurationError,
    PROVIDER_OUTLOOK,
    PROVIDER_GMAIL,
    PROVIDER_IMAP,
    PROVIDER_SMTP,
    PROVIDER_IMAP_SMTP,
)


class TestFactory:
    """Tests pour get_email_provider."""

    @pytest.mark.skipif(
        not os.path.exists("/dev/null"),  # Always skip if azure not installed
        reason="Azure SDK non installé"
    )
    @patch.dict(os.environ, {
        "AZURE_TENANT_ID": "test-tenant",
        "AZURE_CLIENT_ID": "test-client",
        "AZURE_CLIENT_SECRET": "test-secret",
        "OUTLOOK_USER_ID": "test@example.com"
    })
    def test_get_outlook_provider(self):
        """Test création provider Outlook."""
        try:
            provider = get_email_provider("OUTLOOK")
            assert provider.provider_name == "outlook"
        except ModuleNotFoundError:
            pytest.skip("Azure SDK non installé")

    @pytest.mark.skipif(
        not os.path.exists("/dev/null"),
        reason="Azure SDK non installé"
    )
    @patch.dict(os.environ, {
        "EMAIL_PROVIDER_TYPE": "OUTLOOK",
        "AZURE_TENANT_ID": "test-tenant",
        "AZURE_CLIENT_ID": "test-client",
        "AZURE_CLIENT_SECRET": "test-secret",
        "OUTLOOK_USER_ID": "test@example.com"
    })
    def test_get_provider_from_env(self):
        """Test sélection provider via variable d'environnement."""
        try:
            provider = get_email_provider()
            assert provider.provider_name == "outlook"
        except ModuleNotFoundError:
            pytest.skip("Azure SDK non installé")

    def test_get_gmail_provider(self):
        """Test création provider Gmail."""
        try:
            provider = get_email_provider("GMAIL")
            assert provider.provider_name == "gmail"
        except ModuleNotFoundError:
            pytest.skip("Google SDK non installé")

    @patch.dict(os.environ, {
        "IMAP_HOST": "imap.example.com",
        "IMAP_USER": "test@example.com",
        "IMAP_PASSWORD": "secret",
    })
    def test_get_imap_provider(self):
        """Test création provider IMAP."""
        provider = get_email_provider("IMAP")
        assert provider.provider_name == "imap"

    @patch.dict(os.environ, {
        "SMTP_HOST": "smtp.example.com",
        "SMTP_USER": "test@example.com",
        "SMTP_PASSWORD": "secret",
    })
    def test_get_smtp_provider(self):
        """Test création provider SMTP."""
        provider = get_email_provider("SMTP")
        assert provider.provider_name == "smtp"

    def test_unknown_provider(self):
        """Test provider inconnu lève ProviderConfigurationError."""
        with pytest.raises(ProviderConfigurationError) as exc_info:
            get_email_provider("UNKNOWN")

        assert "UNKNOWN" in str(exc_info.value)

    def test_provider_type_case_insensitive(self):
        """Test que le type de provider est insensible à la casse."""
        with patch.dict(os.environ, {
            "AZURE_TENANT_ID": "test",
            "AZURE_CLIENT_ID": "test",
            "AZURE_CLIENT_SECRET": "test",
        }):
            try:
                # Ces trois doivent fonctionner
                for provider_type in ["outlook", "OUTLOOK", "Outlook"]:
                    provider = get_email_provider(provider_type)
                    assert provider.provider_name == "outlook"
            except ModuleNotFoundError:
                pytest.skip("Azure SDK non installé")

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_config_raises_error(self):
        """Test config manquante lève ProviderConfigurationError."""
        try:
            with pytest.raises(ProviderConfigurationError):
                get_email_provider("OUTLOOK")
        except ModuleNotFoundError:
            pytest.skip("Azure SDK non installé")


class TestListProviders:
    """Tests pour list_available_providers."""

    def test_list_providers(self):
        """Test liste des providers."""
        providers = list_available_providers()

        assert PROVIDER_OUTLOOK in providers
        assert PROVIDER_GMAIL in providers
        assert PROVIDER_IMAP in providers
        assert PROVIDER_SMTP in providers
        assert PROVIDER_IMAP_SMTP in providers
        assert providers[PROVIDER_OUTLOOK] == "disponible"
        assert providers[PROVIDER_GMAIL] == "disponible"


class TestValidateConfig:
    """Tests pour validate_provider_config."""

    @patch.dict(os.environ, {
        "AZURE_TENANT_ID": "test",
        "AZURE_CLIENT_ID": "test",
    }, clear=True)
    def test_validate_outlook_partial(self):
        """Test validation config Outlook partielle."""
        result = validate_provider_config("OUTLOOK")

        assert result["AZURE_TENANT_ID"] is True
        assert result["AZURE_CLIENT_ID"] is True
        assert result["AZURE_CLIENT_SECRET"] is False
        assert result["OUTLOOK_USER_ID"] is False

    @patch.dict(os.environ, {
        "AZURE_TENANT_ID": "test",
        "AZURE_CLIENT_ID": "test",
        "AZURE_CLIENT_SECRET": "test",
        "OUTLOOK_USER_ID": "test@example.com",
    })
    def test_validate_outlook_complete(self):
        """Test validation config Outlook complète."""
        result = validate_provider_config("OUTLOOK")

        assert all(result.values())

    @patch.dict(os.environ, {
        "GOOGLE_CLIENT_ID": "test",
    }, clear=True)
    def test_validate_gmail_partial(self):
        """Test validation config Gmail partielle."""
        result = validate_provider_config("GMAIL")

        assert result["GOOGLE_CLIENT_ID"] is True
        assert result["GOOGLE_CLIENT_SECRET"] is False
        assert result["GOOGLE_REFRESH_TOKEN"] is False

    @patch.dict(os.environ, {
        "IMAP_HOST": "imap.example.com",
        "IMAP_USER": "test@example.com",
    }, clear=True)
    def test_validate_imap_partial(self):
        """Test validation config IMAP partielle."""
        result = validate_provider_config("IMAP")

        assert result["IMAP_HOST"] is True
        assert result["IMAP_USER"] is True
        assert result["IMAP_PASSWORD"] is False

    @patch.dict(os.environ, {
        "SMTP_HOST": "smtp.example.com",
    }, clear=True)
    def test_validate_smtp_partial(self):
        """Test validation config SMTP partielle."""
        result = validate_provider_config("SMTP")

        assert result["SMTP_HOST"] is True
        assert result["SMTP_USER"] is False
        assert result["SMTP_PASSWORD"] is False

    def test_validate_unknown_provider(self):
        """Test validation provider inconnu retourne dict vide."""
        result = validate_provider_config("UNKNOWN")
        assert result == {}
