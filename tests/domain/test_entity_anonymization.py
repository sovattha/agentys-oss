# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour app.domain.entities.anonymization."""

import pytest
from app.domain.entities.anonymization import (
    AnonymizedToken,
    SecureTokenMapping,
    AnonymizedResult,
    SecureAnonymizedData,
)
from app.domain.entities.sensitive_data import SensitiveDataType


# ============================================================================
# AnonymizedToken
# ============================================================================

class TestAnonymizedToken:
    def test_create_token(self):
        token = AnonymizedToken(token_id="tok_1", data_type=SensitiveDataType.FINANCIAL)
        assert token.token_id == "tok_1"
        assert token.data_type == SensitiveDataType.FINANCIAL

    def test_placeholder_format(self):
        token = AnonymizedToken(token_id="abc", data_type=SensitiveDataType.PERSONAL)
        assert token.placeholder == "[ANON:PERSONAL:abc]"

    def test_placeholder_credential(self):
        token = AnonymizedToken(token_id="x", data_type=SensitiveDataType.CREDENTIAL)
        assert token.placeholder == "[ANON:CREDENTIAL:x]"

    def test_to_dict(self):
        token = AnonymizedToken(token_id="t1", data_type=SensitiveDataType.COMMERCIAL_SECRET)
        d = token.to_dict()
        assert d == {"token_id": "t1", "data_type": "commercial"}

    def test_from_dict_roundtrip(self):
        token = AnonymizedToken(token_id="t1", data_type=SensitiveDataType.FINANCIAL)
        d = token.to_dict()
        restored = AnonymizedToken.from_dict(d)
        assert restored == token

    def test_frozen_immutability(self):
        token = AnonymizedToken(token_id="t1", data_type=SensitiveDataType.PERSONAL)
        with pytest.raises(AttributeError):
            token.token_id = "changed"


# ============================================================================
# SecureTokenMapping
# ============================================================================

class TestSecureTokenMapping:
    def test_create_mapping(self):
        mapping = SecureTokenMapping(
            token_id="t1",
            encrypted_value=b"\x01\x02\x03",
            salt=b"\xaa\xbb",
        )
        assert mapping.token_id == "t1"
        assert mapping.encrypted_value == b"\x01\x02\x03"

    def test_to_dict_hex(self):
        mapping = SecureTokenMapping(
            token_id="t1",
            encrypted_value=b"\xff\x00",
            salt=b"\x01\x02",
        )
        d = mapping.to_dict()
        assert d["encrypted_value"] == "ff00"
        assert d["salt"] == "0102"

    def test_from_dict_roundtrip(self):
        mapping = SecureTokenMapping(
            token_id="t1",
            encrypted_value=b"secret",
            salt=b"salty",
        )
        d = mapping.to_dict()
        restored = SecureTokenMapping.from_dict(d)
        assert restored == mapping


# ============================================================================
# AnonymizedResult
# ============================================================================

class TestAnonymizedResult:
    def test_create_with_tokens(self):
        tokens = [
            AnonymizedToken(token_id="t1", data_type=SensitiveDataType.FINANCIAL),
            AnonymizedToken(token_id="t2", data_type=SensitiveDataType.PERSONAL),
        ]
        result = AnonymizedResult.create(
            anonymized_text="Le compte [ANON:FINANCIAL:t1] de [ANON:PERSONAL:t2]",
            tokens=tokens,
            original_text_hash="abc123",
        )
        assert len(result.tokens) == 2
        assert result.original_text_hash == "abc123"

    def test_empty_factory(self):
        result = AnonymizedResult.empty("original text", "hash123")
        assert result.anonymized_text == "original text"
        assert result.tokens == ()
        assert result.original_text_hash == "hash123"

    def test_to_dict(self):
        token = AnonymizedToken(token_id="t1", data_type=SensitiveDataType.CREDENTIAL)
        result = AnonymizedResult.create("text [ANON]", [token], "h1")
        d = result.to_dict()
        assert d["anonymized_text"] == "text [ANON]"
        assert len(d["tokens"]) == 1
        assert d["original_text_hash"] == "h1"

    def test_from_dict_roundtrip(self):
        token = AnonymizedToken(token_id="t1", data_type=SensitiveDataType.FINANCIAL)
        original = AnonymizedResult.create("anon text", [token], "hash")
        d = original.to_dict()
        restored = AnonymizedResult.from_dict(d)
        assert restored == original

    def test_frozen_immutability(self):
        result = AnonymizedResult.empty("text", "hash")
        with pytest.raises(AttributeError):
            result.anonymized_text = "changed"


# ============================================================================
# SecureAnonymizedData
# ============================================================================

class TestSecureAnonymizedData:
    def test_create_full_data(self):
        token = AnonymizedToken(token_id="t1", data_type=SensitiveDataType.PERSONAL)
        result = AnonymizedResult.create("anon", [token], "h1")
        mapping = SecureTokenMapping(token_id="t1", encrypted_value=b"enc", salt=b"s")
        data = SecureAnonymizedData.create(result, [mapping], "key-1")
        assert data.key_id == "key-1"
        assert len(data.secure_mappings) == 1

    def test_to_dict_roundtrip(self):
        token = AnonymizedToken(token_id="t1", data_type=SensitiveDataType.FINANCIAL)
        result = AnonymizedResult.create("text", [token], "h")
        mapping = SecureTokenMapping(token_id="t1", encrypted_value=b"\x01", salt=b"\x02")
        original = SecureAnonymizedData.create(result, [mapping], "k1")
        d = original.to_dict()
        restored = SecureAnonymizedData.from_dict(d)
        assert restored == original
