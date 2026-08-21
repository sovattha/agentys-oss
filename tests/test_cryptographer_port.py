"""Tests pour CryptographerPort - Interface de chiffrement."""

from abc import ABC
from typing import Any

import pytest

from app.domain.ports.cryptographer_port import CryptographerPort


class TestCryptographerPortInterface:
    """Tests pour valider l'interface CryptographerPort."""

    def test_is_abstract_class(self):
        assert issubclass(CryptographerPort, ABC)

    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            CryptographerPort()

    def test_has_encrypt_method(self):
        assert hasattr(CryptographerPort, "encrypt")
        assert callable(getattr(CryptographerPort, "encrypt"))

    def test_has_decrypt_method(self):
        assert hasattr(CryptographerPort, "decrypt")
        assert callable(getattr(CryptographerPort, "decrypt"))

    def test_has_encrypt_dict_method(self):
        assert hasattr(CryptographerPort, "encrypt_dict")
        assert callable(getattr(CryptographerPort, "encrypt_dict"))

    def test_has_decrypt_dict_method(self):
        assert hasattr(CryptographerPort, "decrypt_dict")
        assert callable(getattr(CryptographerPort, "decrypt_dict"))

    def test_has_hash_email_method(self):
        assert hasattr(CryptographerPort, "hash_email")
        assert callable(getattr(CryptographerPort, "hash_email"))


class FakeCryptographer(CryptographerPort):
    """Implémentation de test pour valider le contrat."""

    def encrypt(self, data: str) -> str:
        return f"encrypted:{data}"

    def decrypt(self, encrypted_data: str) -> str:
        return encrypted_data.replace("encrypted:", "")

    def encrypt_dict(self, data: dict[str, Any]) -> str:
        return f"encrypted_dict:{data}"

    def decrypt_dict(self, encrypted_data: str) -> dict[str, Any]:
        return {"decrypted": True}

    def hash_email(self, email: str) -> str:
        return f"hashed:{email}"


class TestCryptographerPortContract:
    """Tests pour valider qu'une implémentation respecte le contrat."""

    @pytest.fixture
    def cryptographer(self) -> CryptographerPort:
        return FakeCryptographer()

    def test_encrypt_returns_string(self, cryptographer: CryptographerPort):
        result = cryptographer.encrypt("secret")
        assert isinstance(result, str)

    def test_decrypt_returns_string(self, cryptographer: CryptographerPort):
        result = cryptographer.decrypt("encrypted:secret")
        assert isinstance(result, str)

    def test_encrypt_dict_returns_string(self, cryptographer: CryptographerPort):
        result = cryptographer.encrypt_dict({"key": "value"})
        assert isinstance(result, str)

    def test_decrypt_dict_returns_dict(self, cryptographer: CryptographerPort):
        result = cryptographer.decrypt_dict("encrypted_dict:data")
        assert isinstance(result, dict)

    def test_hash_email_returns_string(self, cryptographer: CryptographerPort):
        result = cryptographer.hash_email("test@example.com")
        assert isinstance(result, str)

    def test_hash_email_is_deterministic_concept(
        self, cryptographer: CryptographerPort
    ):
        result1 = cryptographer.hash_email("test@example.com")
        result2 = cryptographer.hash_email("test@example.com")
        assert result1 == result2


class TestCryptographerPortExport:
    """Tests pour valider l'export dans le module ports."""

    def test_exported_from_ports_module(self):
        from app.domain.ports import CryptographerPort as ExportedPort

        assert ExportedPort is CryptographerPort


class TestCryptographerPortEdgeCases:
    """Tests pour les cas limites (edge cases)."""

    @pytest.fixture
    def cryptographer(self) -> CryptographerPort:
        return FakeCryptographer()

    # --- Inputs vides ---

    def test_encrypt_empty_string(self, cryptographer: CryptographerPort):
        """encrypt() doit accepter une chaîne vide."""
        result = cryptographer.encrypt("")
        assert isinstance(result, str)

    def test_decrypt_empty_string(self, cryptographer: CryptographerPort):
        """decrypt() doit accepter une chaîne vide."""
        result = cryptographer.decrypt("")
        assert isinstance(result, str)

    def test_encrypt_dict_empty(self, cryptographer: CryptographerPort):
        """encrypt_dict() doit accepter un dictionnaire vide."""
        result = cryptographer.encrypt_dict({})
        assert isinstance(result, str)

    def test_hash_email_empty_string(self, cryptographer: CryptographerPort):
        """hash_email() doit accepter une chaîne vide."""
        result = cryptographer.hash_email("")
        assert isinstance(result, str)

    # --- Caractères spéciaux et Unicode ---

    def test_encrypt_unicode_characters(self, cryptographer: CryptographerPort):
        """encrypt() doit gérer les caractères Unicode."""
        result = cryptographer.encrypt("日本語 émojis 🔐🔑 中文")
        assert isinstance(result, str)

    def test_encrypt_special_characters(self, cryptographer: CryptographerPort):
        """encrypt() doit gérer les caractères spéciaux."""
        result = cryptographer.encrypt("!@#$%^&*()_+-=[]{}|;':\",./<>?`~\\")
        assert isinstance(result, str)

    def test_encrypt_newlines_and_whitespace(self, cryptographer: CryptographerPort):
        """encrypt() doit gérer les retours à la ligne et espaces."""
        result = cryptographer.encrypt("line1\nline2\ttab\r\nwindows")
        assert isinstance(result, str)

    def test_encrypt_dict_unicode_values(self, cryptographer: CryptographerPort):
        """encrypt_dict() doit gérer les valeurs Unicode."""
        result = cryptographer.encrypt_dict({"name": "Jérémy", "emoji": "🔐"})
        assert isinstance(result, str)

    # --- Emails invalides/malformés ---

    def test_hash_email_without_at_symbol(self, cryptographer: CryptographerPort):
        """hash_email() doit accepter une adresse sans @."""
        result = cryptographer.hash_email("not_an_email")
        assert isinstance(result, str)

    def test_hash_email_with_spaces(self, cryptographer: CryptographerPort):
        """hash_email() doit accepter une adresse avec espaces."""
        result = cryptographer.hash_email("test @example.com")
        assert isinstance(result, str)

    def test_hash_email_with_special_chars(self, cryptographer: CryptographerPort):
        """hash_email() doit accepter une adresse avec caractères spéciaux."""
        result = cryptographer.hash_email("test+tag@sub.example.co.uk")
        assert isinstance(result, str)

    def test_hash_email_very_long(self, cryptographer: CryptographerPort):
        """hash_email() doit accepter une adresse très longue."""
        long_email = "a" * 100 + "@" + "b" * 100 + ".com"
        result = cryptographer.hash_email(long_email)
        assert isinstance(result, str)

    # --- Dictionnaires complexes ---

    def test_encrypt_dict_nested(self, cryptographer: CryptographerPort):
        """encrypt_dict() doit gérer les dictionnaires imbriqués."""
        nested = {"level1": {"level2": {"level3": "value"}}}
        result = cryptographer.encrypt_dict(nested)
        assert isinstance(result, str)

    def test_encrypt_dict_with_none_values(self, cryptographer: CryptographerPort):
        """encrypt_dict() doit gérer les valeurs None."""
        result = cryptographer.encrypt_dict({"key": None, "other": "value"})
        assert isinstance(result, str)

    def test_encrypt_dict_with_lists(self, cryptographer: CryptographerPort):
        """encrypt_dict() doit gérer les listes comme valeurs."""
        result = cryptographer.encrypt_dict({"items": [1, 2, 3], "names": ["a", "b"]})
        assert isinstance(result, str)

    def test_encrypt_dict_with_mixed_types(self, cryptographer: CryptographerPort):
        """encrypt_dict() doit gérer des types mixtes."""
        mixed = {
            "string": "value",
            "int": 42,
            "float": 3.14,
            "bool": True,
            "none": None,
            "list": [1, "two", 3.0],
            "nested": {"a": 1},
        }
        result = cryptographer.encrypt_dict(mixed)
        assert isinstance(result, str)

    # --- Chaînes très longues ---

    def test_encrypt_very_long_string(self, cryptographer: CryptographerPort):
        """encrypt() doit gérer les très longues chaînes."""
        long_string = "x" * 10000
        result = cryptographer.encrypt(long_string)
        assert isinstance(result, str)

    def test_encrypt_dict_very_large(self, cryptographer: CryptographerPort):
        """encrypt_dict() doit gérer les grands dictionnaires."""
        large_dict = {f"key_{i}": f"value_{i}" for i in range(1000)}
        result = cryptographer.encrypt_dict(large_dict)
        assert isinstance(result, str)


class TestCryptographerPortPartialImplementation:
    """Tests pour vérifier qu'une implémentation partielle ne peut pas être instanciée."""

    def test_missing_encrypt_raises_error(self):
        """Une classe sans encrypt() ne peut pas être instanciée."""

        class PartialCryptographer(CryptographerPort):
            def decrypt(self, encrypted_data: str) -> str:
                return ""

            def encrypt_dict(self, data: dict[str, Any]) -> str:
                return ""

            def decrypt_dict(self, encrypted_data: str) -> dict[str, Any]:
                return {}

            def hash_email(self, email: str) -> str:
                return ""

        with pytest.raises(TypeError):
            PartialCryptographer()

    def test_missing_decrypt_raises_error(self):
        """Une classe sans decrypt() ne peut pas être instanciée."""

        class PartialCryptographer(CryptographerPort):
            def encrypt(self, data: str) -> str:
                return ""

            def encrypt_dict(self, data: dict[str, Any]) -> str:
                return ""

            def decrypt_dict(self, encrypted_data: str) -> dict[str, Any]:
                return {}

            def hash_email(self, email: str) -> str:
                return ""

        with pytest.raises(TypeError):
            PartialCryptographer()

    def test_missing_encrypt_dict_raises_error(self):
        """Une classe sans encrypt_dict() ne peut pas être instanciée."""

        class PartialCryptographer(CryptographerPort):
            def encrypt(self, data: str) -> str:
                return ""

            def decrypt(self, encrypted_data: str) -> str:
                return ""

            def decrypt_dict(self, encrypted_data: str) -> dict[str, Any]:
                return {}

            def hash_email(self, email: str) -> str:
                return ""

        with pytest.raises(TypeError):
            PartialCryptographer()

    def test_missing_decrypt_dict_raises_error(self):
        """Une classe sans decrypt_dict() ne peut pas être instanciée."""

        class PartialCryptographer(CryptographerPort):
            def encrypt(self, data: str) -> str:
                return ""

            def decrypt(self, encrypted_data: str) -> str:
                return ""

            def encrypt_dict(self, data: dict[str, Any]) -> str:
                return ""

            def hash_email(self, email: str) -> str:
                return ""

        with pytest.raises(TypeError):
            PartialCryptographer()

    def test_missing_hash_email_raises_error(self):
        """Une classe sans hash_email() ne peut pas être instanciée."""

        class PartialCryptographer(CryptographerPort):
            def encrypt(self, data: str) -> str:
                return ""

            def decrypt(self, encrypted_data: str) -> str:
                return ""

            def encrypt_dict(self, data: dict[str, Any]) -> str:
                return ""

            def decrypt_dict(self, encrypted_data: str) -> dict[str, Any]:
                return {}

        with pytest.raises(TypeError):
            PartialCryptographer()
