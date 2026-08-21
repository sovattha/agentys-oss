# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Unit tests for database encryption module.

Tests key management, keychain integration, and error handling.
"""

import os
import pytest
from unittest.mock import MagicMock, patch

from app.db.encryption import (
    KEYRING_SERVICE,
    KEYRING_KEY_NAME,
    ENV_ENCRYPTION_KEY,
    ENV_ENCRYPTION_ENABLED,
    EncryptionError,
    WrongKeyError,
    KeyNotFoundError,
    KeychainAccessError,
    EncryptionConfig,
    is_encryption_enabled,
    get_encryption_key,
    store_encryption_key,
    delete_encryption_key,
    get_or_create_encryption_key,
    get_encryption_config,
    get_sqlcipher_pragmas,
)


class TestEncryptionConfig:
    """Tests for EncryptionConfig dataclass."""

    def test_encryption_config_defaults(self):
        """Test default values."""
        config = EncryptionConfig(enabled=True, key="test_key")
        assert config.enabled is True
        assert config.key == "test_key"
        assert config.cipher_page_size == 4096
        assert config.kdf_iter == 256000
        assert config.cipher_hmac_algorithm == "HMAC_SHA512"
        assert config.cipher_kdf_algorithm == "PBKDF2_HMAC_SHA512"

    def test_encryption_config_repr_secure(self):
        """Test repr doesn't leak key material."""
        config = EncryptionConfig(enabled=True, key="secret_key_12345")
        repr_str = repr(config)
        assert "secret_key_12345" not in repr_str
        assert "has_key=True" in repr_str

    def test_encryption_config_disabled(self):
        """Test disabled configuration."""
        config = EncryptionConfig(enabled=False, key=None)
        assert config.enabled is False
        assert config.key is None


class TestIsEncryptionEnabled:
    """Tests for is_encryption_enabled function."""

    def test_default_enabled(self):
        """Test encryption is enabled by default."""
        with patch.dict(os.environ, {}, clear=True):
            assert is_encryption_enabled() is True

    def test_disabled_via_env_false(self):
        """Test disabling via 'false' environment variable."""
        with patch.dict(os.environ, {ENV_ENCRYPTION_ENABLED: "false"}):
            assert is_encryption_enabled() is False

    def test_disabled_via_env_0(self):
        """Test disabling via '0' environment variable."""
        with patch.dict(os.environ, {ENV_ENCRYPTION_ENABLED: "0"}):
            assert is_encryption_enabled() is False

    def test_disabled_via_env_no(self):
        """Test disabling via 'no' environment variable."""
        with patch.dict(os.environ, {ENV_ENCRYPTION_ENABLED: "no"}):
            assert is_encryption_enabled() is False

    def test_disabled_via_env_off(self):
        """Test disabling via 'off' environment variable."""
        with patch.dict(os.environ, {ENV_ENCRYPTION_ENABLED: "off"}):
            assert is_encryption_enabled() is False

    def test_enabled_via_env_true(self):
        """Test explicit enable via environment variable."""
        with patch.dict(os.environ, {ENV_ENCRYPTION_ENABLED: "true"}):
            assert is_encryption_enabled() is True


class TestGetEncryptionKey:
    """Tests for get_encryption_key function."""

    def test_get_key_from_environment(self):
        """Test retrieving key from environment variable."""
        test_key = "a" * 64
        with patch.dict(os.environ, {ENV_ENCRYPTION_KEY: test_key}):
            key = get_encryption_key()
            assert key == test_key

    @patch("app.db.encryption._get_keyring")
    def test_get_key_from_keyring(self, mock_get_keyring):
        """Test retrieving key from keyring."""
        test_key = "b" * 64
        mock_keyring = MagicMock()
        mock_keyring.get_password.return_value = test_key
        mock_get_keyring.return_value = mock_keyring

        with patch.dict(os.environ, {}, clear=True):
            # Clear env var
            os.environ.pop(ENV_ENCRYPTION_KEY, None)
            key = get_encryption_key()
            assert key == test_key
            mock_keyring.get_password.assert_called_once_with(
                KEYRING_SERVICE, KEYRING_KEY_NAME
            )

    @patch("app.db.encryption._get_keyring")
    def test_get_key_keyring_not_installed(self, mock_get_keyring):
        """Test handling when keyring not installed."""
        mock_get_keyring.return_value = None

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop(ENV_ENCRYPTION_KEY, None)
            key = get_encryption_key()
            assert key is None

    @patch("app.db.encryption._get_keyring")
    def test_get_key_keyring_error(self, mock_get_keyring):
        """Test handling keychain access error."""
        mock_keyring = MagicMock()
        mock_keyring.get_password.side_effect = Exception("Keychain locked")
        mock_get_keyring.return_value = mock_keyring

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop(ENV_ENCRYPTION_KEY, None)
            with pytest.raises(KeychainAccessError):
                get_encryption_key()


class TestStoreEncryptionKey:
    """Tests for store_encryption_key function."""

    @patch("app.db.encryption._get_keyring")
    def test_store_key_valid(self, mock_get_keyring):
        """Test storing a valid key."""
        mock_keyring = MagicMock()
        mock_get_keyring.return_value = mock_keyring

        valid_key = "a" * 64
        store_encryption_key(valid_key)

        mock_keyring.set_password.assert_called_once_with(
            KEYRING_SERVICE, KEYRING_KEY_NAME, valid_key
        )

    def test_store_key_invalid_format(self):
        """Test storing invalid key raises error."""
        with pytest.raises(ValueError, match="Invalid encryption key"):
            store_encryption_key("short_key")

    @patch("app.db.encryption._get_keyring")
    def test_store_key_keyring_not_installed(self, mock_get_keyring):
        """Test storing when keyring not installed."""
        mock_get_keyring.return_value = None
        valid_key = "a" * 64
        # Should not raise, just log warning
        store_encryption_key(valid_key)

    @patch("app.db.encryption._get_keyring")
    def test_store_key_keyring_error(self, mock_get_keyring):
        """Test handling keychain store error."""
        mock_keyring = MagicMock()
        mock_keyring.set_password.side_effect = Exception("Permission denied")
        mock_get_keyring.return_value = mock_keyring

        valid_key = "a" * 64
        with pytest.raises(KeychainAccessError):
            store_encryption_key(valid_key)


class TestDeleteEncryptionKey:
    """Tests for delete_encryption_key function."""

    @patch("app.db.encryption._get_keyring")
    def test_delete_key_success(self, mock_get_keyring):
        """Test deleting key successfully."""
        mock_keyring = MagicMock()
        mock_get_keyring.return_value = mock_keyring

        delete_encryption_key()

        mock_keyring.delete_password.assert_called_once_with(
            KEYRING_SERVICE, KEYRING_KEY_NAME
        )

    @patch("app.db.encryption._get_keyring")
    def test_delete_key_not_found(self, mock_get_keyring):
        """Test deleting non-existent key doesn't raise."""
        mock_keyring = MagicMock()
        mock_keyring.delete_password.side_effect = Exception("Key not found")
        mock_get_keyring.return_value = mock_keyring

        # Should not raise
        delete_encryption_key()

    @patch("app.db.encryption._get_keyring")
    def test_delete_key_keyring_not_installed(self, mock_get_keyring):
        """Test deleting when keyring not installed."""
        mock_get_keyring.return_value = None
        # Should not raise
        delete_encryption_key()


class TestGetOrCreateEncryptionKey:
    """Tests for get_or_create_encryption_key function."""

    @patch("app.db.encryption.store_encryption_key")
    @patch("app.db.encryption.get_encryption_key")
    def test_get_existing_key(self, mock_get_key, mock_store_key):
        """Test returns existing key without creating new one."""
        existing_key = "b" * 64
        mock_get_key.return_value = existing_key

        key = get_or_create_encryption_key()

        assert key == existing_key
        mock_store_key.assert_not_called()

    @patch("app.db.encryption.store_encryption_key")
    @patch("app.db.encryption.get_encryption_key")
    def test_create_new_key(self, mock_get_key, mock_store_key):
        """Test creates and stores new key when none exists."""
        mock_get_key.return_value = None

        key = get_or_create_encryption_key()

        assert key is not None
        assert len(key) == 64  # 32 bytes hex = 64 chars
        mock_store_key.assert_called_once_with(key)


class TestGetEncryptionConfig:
    """Tests for get_encryption_config function."""

    @patch("app.db.encryption.get_encryption_key")
    @patch("app.db.encryption.is_encryption_enabled")
    def test_config_when_enabled_with_key(self, mock_enabled, mock_get_key):
        """Test config when encryption enabled and key exists."""
        mock_enabled.return_value = True
        mock_get_key.return_value = "c" * 64

        config = get_encryption_config()

        assert config.enabled is True
        assert config.key == "c" * 64

    @patch("app.db.encryption.is_encryption_enabled")
    def test_config_when_disabled(self, mock_enabled):
        """Test config when encryption disabled."""
        mock_enabled.return_value = False

        config = get_encryption_config()

        assert config.enabled is False
        assert config.key is None

    @patch("app.db.encryption.get_encryption_key")
    @patch("app.db.encryption.is_encryption_enabled")
    def test_config_when_enabled_no_key(self, mock_enabled, mock_get_key):
        """Test config when enabled but no key available."""
        mock_enabled.return_value = True
        mock_get_key.return_value = None

        config = get_encryption_config()

        assert config.enabled is True
        assert config.key is None

    @patch("app.db.encryption.get_encryption_key")
    @patch("app.db.encryption.is_encryption_enabled")
    def test_config_when_keychain_error(self, mock_enabled, mock_get_key):
        """Test config when keychain access fails."""
        mock_enabled.return_value = True
        mock_get_key.side_effect = KeychainAccessError("Locked")

        config = get_encryption_config()

        assert config.enabled is True
        assert config.key is None


class TestGetSqlcipherPragmas:
    """Tests for get_sqlcipher_pragmas function."""

    def test_pragmas_with_valid_config(self):
        """Test pragmas are generated for valid config."""
        config = EncryptionConfig(
            enabled=True,
            key="d" * 64,
            cipher_page_size=4096,
            kdf_iter=256000,
        )

        pragmas = get_sqlcipher_pragmas(config)

        assert len(pragmas) == 5
        assert any("PRAGMA key" in p for p in pragmas)
        assert any("cipher_page_size" in p for p in pragmas)
        assert any("kdf_iter" in p for p in pragmas)

    def test_pragmas_with_disabled_config(self):
        """Test no pragmas for disabled config."""
        config = EncryptionConfig(enabled=False, key=None)
        pragmas = get_sqlcipher_pragmas(config)
        assert pragmas == []

    def test_pragmas_with_no_key(self):
        """Test no pragmas when key is missing."""
        config = EncryptionConfig(enabled=True, key=None)
        pragmas = get_sqlcipher_pragmas(config)
        assert pragmas == []


class TestExceptions:
    """Tests for exception classes."""

    def test_encryption_error_base(self):
        """Test EncryptionError is base class."""
        error = EncryptionError("Test error")
        assert str(error) == "Test error"

    def test_wrong_key_error(self):
        """Test WrongKeyError."""
        error = WrongKeyError("Invalid key")
        assert isinstance(error, EncryptionError)

    def test_key_not_found_error(self):
        """Test KeyNotFoundError."""
        error = KeyNotFoundError("Key missing")
        assert isinstance(error, EncryptionError)

    def test_keychain_access_error(self):
        """Test KeychainAccessError."""
        error = KeychainAccessError("Access denied")
        assert isinstance(error, EncryptionError)
