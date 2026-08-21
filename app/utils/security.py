# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Security utilities for key derivation and cryptographic operations.

Provides secure key derivation using PBKDF2 with SHA-256.
Meets NFR10 requirements for AES-256 encryption key generation.
"""

import hashlib
import hmac
import logging
import os
import secrets
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Key derivation parameters (OWASP recommended)
PBKDF2_ITERATIONS = 100_000
KEY_LENGTH_BYTES = 32  # 256 bits for AES-256
SALT_LENGTH_BYTES = 32


@dataclass
class DerivedKey:
    """Container for derived key and associated metadata."""

    key: bytes
    key_hex: str
    salt: bytes
    salt_hex: str
    iterations: int

    def __repr__(self) -> str:
        """Secure repr that doesn't leak key material."""
        return f"DerivedKey(key_length={len(self.key)}, iterations={self.iterations})"


def generate_random_key(length: int = KEY_LENGTH_BYTES) -> bytes:
    """
    Generate a cryptographically secure random key.

    Args:
        length: Key length in bytes (default 32 for AES-256).

    Returns:
        Random bytes suitable for encryption key.
    """
    return secrets.token_bytes(length)


def generate_random_key_hex(length: int = KEY_LENGTH_BYTES) -> str:
    """
    Generate a cryptographically secure random key as hex string.

    Args:
        length: Key length in bytes (default 32 for AES-256).

    Returns:
        Random hex string suitable for encryption key.
    """
    return secrets.token_hex(length)


def generate_salt(length: int = SALT_LENGTH_BYTES) -> bytes:
    """
    Generate a cryptographically secure random salt.

    Args:
        length: Salt length in bytes (default 32).

    Returns:
        Random bytes for use as salt in key derivation.
    """
    return os.urandom(length)


def derive_key(
    password: str,
    salt: Optional[bytes] = None,
    iterations: int = PBKDF2_ITERATIONS,
    key_length: int = KEY_LENGTH_BYTES,
) -> DerivedKey:
    """
    Derive an encryption key from a password using PBKDF2-HMAC-SHA256.

    This provides secure key derivation meeting OWASP recommendations:
    - Uses PBKDF2 with HMAC-SHA256
    - 100,000+ iterations to resist brute force
    - 32-byte (256-bit) salt for uniqueness

    Args:
        password: User password or secret to derive key from.
        salt: Optional salt bytes. If None, generates new random salt.
        iterations: PBKDF2 iteration count (default 100,000).
        key_length: Output key length in bytes (default 32 for AES-256).

    Returns:
        DerivedKey containing the derived key, salt, and metadata.

    Example:
        >>> result = derive_key("my_password")
        >>> print(result.key_hex)  # Use this as encryption key
        >>> # Store result.salt_hex alongside encrypted data
    """
    if not password:
        raise ValueError("Password cannot be empty")

    if salt is None:
        salt = generate_salt()

    # Use PBKDF2-HMAC-SHA256 for key derivation
    key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
        dklen=key_length,
    )

    return DerivedKey(
        key=key,
        key_hex=key.hex(),
        salt=salt,
        salt_hex=salt.hex(),
        iterations=iterations,
    )


def derive_key_from_hex_salt(
    password: str,
    salt_hex: str,
    iterations: int = PBKDF2_ITERATIONS,
    key_length: int = KEY_LENGTH_BYTES,
) -> DerivedKey:
    """
    Derive key from password using existing hex-encoded salt.

    Use this when re-deriving a key with a stored salt.

    Args:
        password: User password or secret.
        salt_hex: Hex-encoded salt string.
        iterations: PBKDF2 iteration count.
        key_length: Output key length in bytes.

    Returns:
        DerivedKey with the derived key.
    """
    salt = bytes.fromhex(salt_hex)
    return derive_key(password, salt, iterations, key_length)


def constant_time_compare(a: bytes, b: bytes) -> bool:
    """
    Compare two byte strings in constant time.

    Prevents timing attacks by ensuring comparison time
    is independent of where strings differ.

    Args:
        a: First byte string.
        b: Second byte string.

    Returns:
        True if strings are equal, False otherwise.
    """
    return hmac.compare_digest(a, b)


def secure_delete(data: bytearray) -> None:
    """
    Attempt to securely delete sensitive data from memory.

    Note: Python doesn't guarantee this will work due to GC,
    but it's better than leaving data in memory.

    Args:
        data: Mutable bytearray to clear.
    """
    if data is None:
        return

    # Overwrite with zeros
    for i in range(len(data)):
        data[i] = 0


def validate_key_format(key_hex: str) -> bool:
    """
    Validate that a hex string is a valid AES-256 key.

    Args:
        key_hex: Hex-encoded key string to validate.

    Returns:
        True if valid 256-bit hex key, False otherwise.
    """
    if not key_hex:
        return False

    try:
        key_bytes = bytes.fromhex(key_hex)
        return len(key_bytes) == KEY_LENGTH_BYTES
    except ValueError:
        return False


def mask_key(key_hex: str, visible_chars: int = 4) -> str:
    """
    Mask a key for safe logging.

    Args:
        key_hex: Hex key to mask.
        visible_chars: Number of chars to show at start/end.

    Returns:
        Masked key string like "abcd...efgh".
    """
    if not key_hex or len(key_hex) <= visible_chars * 2:
        return "***"

    return f"{key_hex[:visible_chars]}...{key_hex[-visible_chars:]}"
