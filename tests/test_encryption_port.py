"""Tests pour EncryptionPort et FernetEncryptionAdapter."""
import pytest
from app.domain.ports.encryption_port import EncryptionPort
from app.infrastructure.adapters.encryption_adapter import FernetEncryptionAdapter


class TestEncryptionPort:
    def test_port_is_abstract(self):
        with pytest.raises(TypeError):
            EncryptionPort()


class TestFernetEncryptionAdapter:
    @pytest.fixture
    def adapter(self) -> FernetEncryptionAdapter:
        return FernetEncryptionAdapter()

    def test_implements_encryption_port(self, adapter):
        assert isinstance(adapter, EncryptionPort)

    def test_encrypt_mapping_returns_string(self, adapter):
        mapping = {"[REDACTED_1]": "secret123", "[REDACTED_2]": "password456"}

        encrypted = adapter.encrypt_mapping(mapping)

        assert isinstance(encrypted, str)
        assert len(encrypted) > 0
        assert "[REDACTED_1]" not in encrypted
        assert "secret123" not in encrypted

    def test_decrypt_mapping_returns_original(self, adapter):
        original = {"[REDACTED_1]": "secret123", "[REDACTED_2]": "password456"}
        encrypted = adapter.encrypt_mapping(original)

        decrypted = adapter.decrypt_mapping(encrypted)

        assert decrypted == original

    def test_encrypt_empty_mapping(self, adapter):
        encrypted = adapter.encrypt_mapping({})
        decrypted = adapter.decrypt_mapping(encrypted)

        assert decrypted == {}

    def test_encrypt_mapping_with_special_characters(self, adapter):
        mapping = {"[REDACTED_1]": "valeur avec accents éàü et symboles @#$%"}
        encrypted = adapter.encrypt_mapping(mapping)

        decrypted = adapter.decrypt_mapping(encrypted)

        assert decrypted == mapping

    def test_decrypt_invalid_token_raises(self, adapter):
        with pytest.raises(Exception):
            adapter.decrypt_mapping("invalid_token_data")

    def test_different_adapter_with_same_key_can_decrypt(self):
        adapter1 = FernetEncryptionAdapter()
        adapter2 = FernetEncryptionAdapter()

        mapping = {"key": "value"}
        encrypted = adapter1.encrypt_mapping(mapping)

        decrypted = adapter2.decrypt_mapping(encrypted)
        assert decrypted == mapping


class TestFernetEncryptionAdapterEdgeCases:
    """Tests des cas limites pour FernetEncryptionAdapter."""

    @pytest.fixture
    def adapter(self) -> FernetEncryptionAdapter:
        return FernetEncryptionAdapter()

    def test_encrypt_mapping_with_empty_string_values(self, adapter):
        """Mapping avec des valeurs vides."""
        mapping = {"[REDACTED_1]": "", "[REDACTED_2]": ""}
        encrypted = adapter.encrypt_mapping(mapping)

        decrypted = adapter.decrypt_mapping(encrypted)

        assert decrypted == mapping

    def test_encrypt_mapping_with_empty_string_keys(self, adapter):
        """Mapping avec des clés vides."""
        mapping = {"": "value1", "[REDACTED_2]": "value2"}
        encrypted = adapter.encrypt_mapping(mapping)

        decrypted = adapter.decrypt_mapping(encrypted)

        assert decrypted == mapping

    def test_encrypt_very_large_mapping(self, adapter):
        """Mapping avec beaucoup d'entrées."""
        mapping = {f"[REDACTED_{i}]": f"secret_{i}" for i in range(1000)}
        encrypted = adapter.encrypt_mapping(mapping)

        decrypted = adapter.decrypt_mapping(encrypted)

        assert decrypted == mapping
        assert len(decrypted) == 1000

    def test_encrypt_mapping_with_very_long_values(self, adapter):
        """Mapping avec des valeurs très longues."""
        long_value = "x" * 100000
        mapping = {"[REDACTED_1]": long_value}
        encrypted = adapter.encrypt_mapping(mapping)

        decrypted = adapter.decrypt_mapping(encrypted)

        assert decrypted == mapping
        assert len(decrypted["[REDACTED_1]"]) == 100000

    def test_encrypt_mapping_with_unicode_keys(self, adapter):
        """Mapping avec des clés unicode."""
        mapping = {"[REDACTED_été]": "summer", "[REDACTED_🎉]": "party"}
        encrypted = adapter.encrypt_mapping(mapping)

        decrypted = adapter.decrypt_mapping(encrypted)

        assert decrypted == mapping

    def test_encrypt_mapping_with_json_special_chars(self, adapter):
        """Mapping avec des caractères spéciaux JSON."""
        mapping = {
            "[REDACTED_1]": '{"key": "value"}',
            "[REDACTED_2]": 'tab\there\nand\nnewline',
            "[REDACTED_3]": 'quotes: "double" and \'single\''
        }
        encrypted = adapter.encrypt_mapping(mapping)

        decrypted = adapter.decrypt_mapping(encrypted)

        assert decrypted == mapping

    def test_decrypt_empty_string_raises(self, adapter):
        """Décryptage d'une chaîne vide lève une exception."""
        with pytest.raises(Exception):
            adapter.decrypt_mapping("")

    def test_decrypt_truncated_token_raises(self, adapter):
        """Décryptage d'un token tronqué lève une exception."""
        mapping = {"key": "value"}
        encrypted = adapter.encrypt_mapping(mapping)
        truncated = encrypted[:len(encrypted)//2]

        with pytest.raises(Exception):
            adapter.decrypt_mapping(truncated)

    def test_decrypt_modified_token_raises(self, adapter):
        """Décryptage d'un token modifié lève une exception."""
        mapping = {"key": "value"}
        encrypted = adapter.encrypt_mapping(mapping)
        # Modifier un caractère au milieu
        modified = encrypted[:10] + "X" + encrypted[11:]

        with pytest.raises(Exception):
            adapter.decrypt_mapping(modified)

    def test_decrypt_base64_like_but_invalid(self, adapter):
        """Décryptage d'une chaîne base64-like mais invalide."""
        with pytest.raises(Exception):
            adapter.decrypt_mapping("YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXo=")

    def test_encrypt_same_mapping_produces_different_tokens(self, adapter):
        """Chaque chiffrement produit un token différent (IV aléatoire)."""
        mapping = {"key": "value"}
        encrypted1 = adapter.encrypt_mapping(mapping)
        encrypted2 = adapter.encrypt_mapping(mapping)

        # Les tokens doivent être différents (IV différent)
        assert encrypted1 != encrypted2

        # Mais les deux doivent déchiffrer vers le même contenu
        assert adapter.decrypt_mapping(encrypted1) == mapping
        assert adapter.decrypt_mapping(encrypted2) == mapping

    def test_encrypt_mapping_with_nested_brackets(self, adapter):
        """Mapping avec des crochets imbriqués dans les valeurs."""
        mapping = {"[REDACTED_1]": "[some [nested] value]"}
        encrypted = adapter.encrypt_mapping(mapping)

        decrypted = adapter.decrypt_mapping(encrypted)

        assert decrypted == mapping

    def test_encrypt_mapping_with_null_byte(self, adapter):
        """Mapping avec des octets nuls dans les valeurs."""
        mapping = {"[REDACTED_1]": "before\x00after"}
        encrypted = adapter.encrypt_mapping(mapping)

        decrypted = adapter.decrypt_mapping(encrypted)

        assert decrypted == mapping
        assert "\x00" in decrypted["[REDACTED_1]"]

    def test_multiple_encrypt_decrypt_cycles(self, adapter):
        """Plusieurs cycles de chiffrement/déchiffrement."""
        mapping = {"key": "value"}

        for _ in range(100):
            encrypted = adapter.encrypt_mapping(mapping)
            decrypted = adapter.decrypt_mapping(encrypted)
            assert decrypted == mapping

    def test_encrypt_mapping_with_numeric_looking_values(self, adapter):
        """Mapping avec des valeurs qui ressemblent à des nombres."""
        mapping = {
            "[REDACTED_1]": "12345",
            "[REDACTED_2]": "123.456",
            "[REDACTED_3]": "-789",
            "[REDACTED_4]": "1e10"
        }
        encrypted = adapter.encrypt_mapping(mapping)

        decrypted = adapter.decrypt_mapping(encrypted)

        # Toutes les valeurs doivent rester des strings
        assert decrypted == mapping
        for value in decrypted.values():
            assert isinstance(value, str)
