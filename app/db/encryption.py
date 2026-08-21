# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Database encryption key management using OS Keychain.

Manages encryption keys for SQLCipher database encryption.
Keys are stored securely in the OS Keychain (macOS Keychain,
Windows Credential Manager, or Linux Secret Service).

Meets NFR11: OS secure storage for secrets.
"""

import logging
import os
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Keyring service identifiers
KEYRING_SERVICE = "agentys"
KEYRING_KEY_NAME = "db_encryption_key"
KEYRING_SALT_NAME = "db_encryption_salt"

# Environment variable overrides for testing
ENV_ENCRYPTION_KEY = "AGENTYS_ENCRYPTION_KEY"
ENV_ENCRYPTION_ENABLED = "AGENTYS_ENCRYPTION_ENABLED"


class EncryptionError(Exception):
    """Base class for encryption-related errors."""

    pass


class WrongKeyError(EncryptionError):
    """Raised when database decryption fails due to wrong key."""

    pass


class KeyNotFoundError(EncryptionError):
    """Raised when encryption key is not found in keychain."""

    pass


class KeychainAccessError(EncryptionError):
    """Raised when keychain access fails."""

    pass


# Strict hex validation to prevent PRAGMA injection
_HEX_KEY_RE = re.compile(r"^[0-9a-fA-F]+$")

# Whitelists for SQLCipher algorithm PRAGMA values — prevents string injection
_VALID_HMAC_ALGORITHMS = frozenset({"HMAC_SHA1", "HMAC_SHA256", "HMAC_SHA512"})
_VALID_KDF_ALGORITHMS = frozenset({"PBKDF2_HMAC_SHA1", "PBKDF2_HMAC_SHA256", "PBKDF2_HMAC_SHA512"})


def _validate_hex_key(key: str) -> str:
    """
    Validate that key is hex-encoded only.

    Prevents SQL/PRAGMA injection via malicious key values.
    Raises ValueError if key contains non-hex characters.
    """
    if not key or not _HEX_KEY_RE.match(key):
        raise ValueError("Encryption key must be a non-empty hex string")
    return key


@dataclass
class EncryptionConfig:
    """Configuration for database encryption."""

    enabled: bool
    key: Optional[str]
    cipher_page_size: int = 4096
    kdf_iter: int = 256000
    cipher_hmac_algorithm: str = "HMAC_SHA512"
    cipher_kdf_algorithm: str = "PBKDF2_HMAC_SHA512"

    def __repr__(self) -> str:
        """Secure repr that doesn't leak key material."""
        return (
            f"EncryptionConfig(enabled={self.enabled}, "
            f"has_key={self.key is not None}, "
            f"kdf_iter={self.kdf_iter})"
        )


def is_encryption_enabled() -> bool:
    """
    Check if database encryption is enabled.

    Encryption can be disabled via environment variable for testing.

    Returns:
        True if encryption should be used.
    """
    env_value = os.environ.get(ENV_ENCRYPTION_ENABLED, "true").lower()
    return env_value not in ("false", "0", "no", "off")


def _get_keyring():
    """Lazy import keyring to avoid import errors if not installed."""
    try:
        import keyring

        return keyring
    except ImportError:
        logger.warning("keyring not installed, falling back to environment variable")
        return None


def get_encryption_key() -> Optional[str]:
    """
    Get the database encryption key.

    Retrieval order:
    1. Environment variable (for testing/dev)
    2. OS Keychain

    Returns:
        Hex-encoded encryption key, or None if not found.

    Raises:
        KeychainAccessError: If keychain access fails.
    """
    # Check environment variable first (for testing)
    env_key = os.environ.get(ENV_ENCRYPTION_KEY)
    if env_key:
        logger.debug("Using encryption key from environment variable")
        return env_key

    # Try keyring
    keyring = _get_keyring()
    if keyring is None:
        return None

    try:
        key = keyring.get_password(KEYRING_SERVICE, KEYRING_KEY_NAME)
        if key:
            logger.debug("Retrieved encryption key from keychain")
        return key
    except Exception as e:
        # Keychain unavailable (e.g. Linux container without `keyrings.alt`,
        # CI runners, Railway). The caller in `app/db/database.py` catches
        # this and falls back to an unencrypted DB — graceful degradation,
        # not a hard error. Logged at WARNING to keep Sentry/Railway logs
        # quiet on platforms where keychain is intentionally absent.
        logger.warning(f"Keychain unavailable, falling back to unencrypted DB: {e}")
        raise KeychainAccessError(f"Cannot access OS keychain: {e}") from e


def store_encryption_key(key: str) -> None:
    """
    Store the encryption key in OS Keychain.

    Args:
        key: Hex-encoded encryption key.

    Raises:
        KeychainAccessError: If storing fails.
    """
    from app.utils.security import validate_key_format

    if not validate_key_format(key):
        raise ValueError("Invalid encryption key format")

    keyring = _get_keyring()
    if keyring is None:
        logger.warning("keyring not available, key not stored")
        return

    try:
        keyring.set_password(KEYRING_SERVICE, KEYRING_KEY_NAME, key)
        logger.info("Encryption key stored in keychain")
    except Exception as e:
        logger.error(f"Failed to store key in keychain: {e}")
        raise KeychainAccessError(f"Cannot store key in keychain: {e}") from e


def delete_encryption_key() -> None:
    """
    Delete the encryption key from OS Keychain.

    Use with caution - this will make encrypted databases inaccessible.

    Raises:
        KeychainAccessError: If deletion fails.
    """
    keyring = _get_keyring()
    if keyring is None:
        return

    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_KEY_NAME)
        logger.info("Encryption key deleted from keychain")
    except Exception as e:
        # Ignore if key doesn't exist
        if "not found" not in str(e).lower():
            logger.error(f"Failed to delete key from keychain: {e}")
            raise KeychainAccessError(f"Cannot delete key from keychain: {e}") from e


def get_or_create_encryption_key() -> str:
    """
    Get existing encryption key or create a new one.

    Creates and stores a new random key if none exists.

    Returns:
        Hex-encoded encryption key.

    Raises:
        KeychainAccessError: If keychain operations fail.
    """
    from app.utils.security import generate_random_key_hex

    # Try to get existing key
    key = get_encryption_key()
    if key:
        return key

    # Generate new random key
    key = generate_random_key_hex()
    logger.info("Generated new encryption key")

    # Store in keychain
    store_encryption_key(key)

    return key


def get_encryption_config() -> EncryptionConfig:
    """
    Get the complete encryption configuration.

    Returns:
        EncryptionConfig with current settings.
    """
    enabled = is_encryption_enabled()

    if not enabled:
        return EncryptionConfig(enabled=False, key=None)

    try:
        key = get_encryption_key()
        return EncryptionConfig(enabled=True, key=key)
    except KeychainAccessError:
        # Encryption enabled but can't get key
        return EncryptionConfig(enabled=True, key=None)


def verify_encryption_key(db_path: str, key: str) -> bool:
    """
    Verify that an encryption key works with a database.

    Args:
        db_path: Path to encrypted database.
        key: Hex-encoded encryption key to test.

    Returns:
        True if key is valid, False otherwise.
    """
    try:
        from sqlcipher3 import dbapi2 as sqlite

        _validate_hex_key(key)
        conn = sqlite.connect(db_path)
        conn.execute(f"PRAGMA key = \"x'{key}'\"")
        # Try to read something to verify key
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        conn.close()
        return True
    except Exception as e:
        if "file is not a database" in str(e).lower():
            return False
        # Other errors might be connection issues, not key issues
        logger.warning(f"Key verification error: {e}")
        return False


def get_sqlcipher_pragmas(config: EncryptionConfig) -> list[str]:
    """
    Get SQLCipher PRAGMA statements for the given config.

    Args:
        config: Encryption configuration.

    Returns:
        List of PRAGMA statements to execute.
    """
    if not config.enabled or not config.key:
        return []

    _validate_hex_key(config.key)

    if config.cipher_hmac_algorithm not in _VALID_HMAC_ALGORITHMS:
        raise ValueError(f"Invalid cipher_hmac_algorithm: {config.cipher_hmac_algorithm!r}")
    if config.cipher_kdf_algorithm not in _VALID_KDF_ALGORITHMS:
        raise ValueError(f"Invalid cipher_kdf_algorithm: {config.cipher_kdf_algorithm!r}")

    return [
        f"PRAGMA key = \"x'{config.key}'\"",
        f"PRAGMA cipher_page_size = {config.cipher_page_size}",
        f"PRAGMA kdf_iter = {config.kdf_iter}",
        f"PRAGMA cipher_hmac_algorithm = {config.cipher_hmac_algorithm}",
        f"PRAGMA cipher_kdf_algorithm = {config.cipher_kdf_algorithm}",
    ]
