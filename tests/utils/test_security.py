# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Unit tests for security utilities.

Tests key derivation, random generation, and validation functions.
"""

import pytest

from app.utils.security import (
    PBKDF2_ITERATIONS,
    KEY_LENGTH_BYTES,
    SALT_LENGTH_BYTES,
    DerivedKey,
    generate_random_key,
    generate_random_key_hex,
    generate_salt,
    derive_key,
    derive_key_from_hex_salt,
    constant_time_compare,
    secure_delete,
    validate_key_format,
    mask_key,
)


class TestRandomGeneration:
    """Tests for random key and salt generation."""

    def test_generate_random_key_default_length(self):
        """Test generating random key with default length."""
        key = generate_random_key()
        assert len(key) == KEY_LENGTH_BYTES
        assert isinstance(key, bytes)

    def test_generate_random_key_custom_length(self):
        """Test generating random key with custom length."""
        key = generate_random_key(16)
        assert len(key) == 16

    def test_generate_random_key_uniqueness(self):
        """Test that generated keys are unique."""
        keys = [generate_random_key() for _ in range(100)]
        assert len(set(keys)) == 100  # All unique

    def test_generate_random_key_hex_length(self):
        """Test hex key has correct length (2 chars per byte)."""
        key = generate_random_key_hex()
        assert len(key) == KEY_LENGTH_BYTES * 2

    def test_generate_random_key_hex_is_valid_hex(self):
        """Test hex key contains only hex characters."""
        key = generate_random_key_hex()
        assert all(c in "0123456789abcdef" for c in key)

    def test_generate_salt_default_length(self):
        """Test generating salt with default length."""
        salt = generate_salt()
        assert len(salt) == SALT_LENGTH_BYTES

    def test_generate_salt_custom_length(self):
        """Test generating salt with custom length."""
        salt = generate_salt(64)
        assert len(salt) == 64


class TestKeyDerivation:
    """Tests for PBKDF2 key derivation."""

    def test_derive_key_returns_derived_key(self):
        """Test derive_key returns DerivedKey object."""
        result = derive_key("test_password")
        assert isinstance(result, DerivedKey)
        assert result.key is not None
        assert result.key_hex is not None
        assert result.salt is not None
        assert result.salt_hex is not None
        assert result.iterations == PBKDF2_ITERATIONS

    def test_derive_key_correct_length(self):
        """Test derived key has correct length."""
        result = derive_key("test_password")
        assert len(result.key) == KEY_LENGTH_BYTES
        assert len(result.key_hex) == KEY_LENGTH_BYTES * 2

    def test_derive_key_salt_generated_if_none(self):
        """Test salt is generated when not provided."""
        result = derive_key("test_password")
        assert result.salt is not None
        assert len(result.salt) == SALT_LENGTH_BYTES

    def test_derive_key_uses_provided_salt(self):
        """Test derive_key uses provided salt."""
        salt = b"0" * 32
        result = derive_key("test_password", salt=salt)
        assert result.salt == salt

    def test_derive_key_deterministic_with_same_salt(self):
        """Test same password + salt gives same key."""
        salt = generate_salt()
        result1 = derive_key("test_password", salt=salt)
        result2 = derive_key("test_password", salt=salt)
        assert result1.key == result2.key
        assert result1.key_hex == result2.key_hex

    def test_derive_key_different_with_different_salt(self):
        """Test same password with different salt gives different key."""
        result1 = derive_key("test_password")
        result2 = derive_key("test_password")
        assert result1.key != result2.key  # Different salts

    def test_derive_key_different_passwords(self):
        """Test different passwords give different keys."""
        salt = generate_salt()
        result1 = derive_key("password1", salt=salt)
        result2 = derive_key("password2", salt=salt)
        assert result1.key != result2.key

    def test_derive_key_empty_password_raises(self):
        """Test empty password raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            derive_key("")

    def test_derive_key_custom_iterations(self):
        """Test custom iteration count."""
        result = derive_key("test_password", iterations=1000)
        assert result.iterations == 1000

    def test_derive_key_custom_key_length(self):
        """Test custom key length."""
        result = derive_key("test_password", key_length=16)
        assert len(result.key) == 16

    def test_derive_key_from_hex_salt(self):
        """Test derive_key_from_hex_salt produces same result."""
        result1 = derive_key("test_password")
        result2 = derive_key_from_hex_salt("test_password", result1.salt_hex)
        assert result1.key == result2.key

    def test_derived_key_repr_secure(self):
        """Test DerivedKey repr doesn't leak key material."""
        result = derive_key("test_password")
        repr_str = repr(result)
        assert result.key_hex not in repr_str
        assert "key_length" in repr_str


class TestConstantTimeCompare:
    """Tests for constant-time comparison."""

    def test_constant_time_compare_equal(self):
        """Test equal bytes return True."""
        a = b"test_data"
        b = b"test_data"
        assert constant_time_compare(a, b) is True

    def test_constant_time_compare_not_equal(self):
        """Test different bytes return False."""
        a = b"test_data"
        b = b"different"
        assert constant_time_compare(a, b) is False

    def test_constant_time_compare_empty(self):
        """Test empty bytes are equal."""
        assert constant_time_compare(b"", b"") is True

    def test_constant_time_compare_different_length(self):
        """Test different length bytes return False."""
        a = b"short"
        b = b"longer"
        assert constant_time_compare(a, b) is False


class TestSecureDelete:
    """Tests for secure memory deletion."""

    def test_secure_delete_zeros_data(self):
        """Test secure_delete zeros out data."""
        data = bytearray(b"sensitive_data")
        secure_delete(data)
        assert all(b == 0 for b in data)

    def test_secure_delete_handles_none(self):
        """Test secure_delete handles None gracefully."""
        secure_delete(None)  # Should not raise


class TestValidateKeyFormat:
    """Tests for key format validation."""

    def test_validate_key_format_valid(self):
        """Test valid 256-bit hex key."""
        key = generate_random_key_hex()
        assert validate_key_format(key) is True

    def test_validate_key_format_too_short(self):
        """Test key too short is invalid."""
        assert validate_key_format("abcd") is False

    def test_validate_key_format_too_long(self):
        """Test key too long is invalid."""
        key = "a" * 128
        assert validate_key_format(key) is False

    def test_validate_key_format_invalid_hex(self):
        """Test non-hex characters are invalid."""
        key = "z" * 64
        assert validate_key_format(key) is False

    def test_validate_key_format_empty(self):
        """Test empty string is invalid."""
        assert validate_key_format("") is False

    def test_validate_key_format_none(self):
        """Test None is invalid."""
        assert validate_key_format(None) is False


class TestMaskKey:
    """Tests for key masking."""

    def test_mask_key_default(self):
        """Test key masking with default visible chars."""
        key = "abcdef1234567890abcdef1234567890"
        masked = mask_key(key)
        assert masked == "abcd...7890"
        assert key not in masked

    def test_mask_key_custom_visible(self):
        """Test key masking with custom visible chars."""
        key = "abcdef1234567890"
        masked = mask_key(key, visible_chars=2)
        assert masked == "ab...90"

    def test_mask_key_short_input(self):
        """Test masking very short input."""
        assert mask_key("ab") == "***"

    def test_mask_key_empty(self):
        """Test masking empty string."""
        assert mask_key("") == "***"

    def test_mask_key_none(self):
        """Test masking None."""
        assert mask_key(None) == "***"
