"""
Tests TDD pour FernetCryptographerAdapter.

Ce module teste:
1. Implementation du port CryptographerPort
2. Chiffrement/dechiffrement de strings
3. Chiffrement/dechiffrement de dictionnaires
4. Hachage SHA-256 pour anonymisation emails
5. Gestion des cles (generation, injection)
6. Edge cases et gestion des erreurs

TDD: Tests ecrits AVANT l'implementation.
Clean Architecture: Infrastructure layer (Adapters).
"""

import hashlib
import importlib.util
import json

import pytest

from app.domain.ports.cryptographer_port import CryptographerPort


# =============================================================================
# MODULE LOADING HELPER
# =============================================================================


def _load_cryptographer_adapter_class():
    """
    Charge FernetCryptographerAdapter sans passer par app.infrastructure.__init__.py.

    Cela evite les effets de bord (chargement du container, config, etc.)
    qui requierent des variables d'environnement.
    """
    spec = importlib.util.spec_from_file_location(
        "cryptographer_adapter",
        "app/infrastructure/adapters/cryptographer_adapter.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.FernetCryptographerAdapter


FernetCryptographerAdapter = _load_cryptographer_adapter_class()


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def adapter():
    """Cree un adapter avec cle auto-generee."""
    return FernetCryptographerAdapter()


@pytest.fixture
def known_key():
    """Cle Fernet connue pour tests deterministes."""
    from cryptography.fernet import Fernet
    return Fernet.generate_key()


@pytest.fixture
def adapter_with_key(known_key):
    """Adapter avec cle specifique."""
    return FernetCryptographerAdapter(key=known_key)


# =============================================================================
# TESTS - IMPLEMENTS PORT
# =============================================================================


class TestImplementsPort:
    """Tests pour verifier l'implementation du port."""

    def test_implements_cryptographer_port(self, adapter):
        """FernetCryptographerAdapter implemente CryptographerPort."""
        assert isinstance(adapter, CryptographerPort)

    def test_has_all_required_methods(self, adapter):
        """A toutes les methodes abstraites requises."""
        assert hasattr(adapter, "encrypt")
        assert hasattr(adapter, "decrypt")
        assert hasattr(adapter, "encrypt_dict")
        assert hasattr(adapter, "decrypt_dict")
        assert hasattr(adapter, "hash_email")


# =============================================================================
# TESTS - ENCRYPT
# =============================================================================


class TestEncrypt:
    """Tests pour encrypt."""

    def test_encrypt_returns_string(self, adapter):
        """encrypt retourne une string."""
        result = adapter.encrypt("hello")
        assert isinstance(result, str)

    def test_encrypt_returns_different_from_input(self, adapter):
        """encrypt retourne quelque chose de different de l'input."""
        data = "secret data"
        result = adapter.encrypt(data)
        assert result != data

    def test_encrypt_empty_string(self, adapter):
        """encrypt fonctionne avec une chaine vide."""
        result = adapter.encrypt("")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_encrypt_same_input_different_output(self, adapter):
        """encrypt genere des outputs differents pour le meme input (IV aleatoire)."""
        data = "same data"
        result1 = adapter.encrypt(data)
        result2 = adapter.encrypt(data)
        assert result1 != result2

    def test_encrypt_unicode(self, adapter):
        """encrypt supporte l'unicode."""
        data = "Répondre à 日本語 émoji 🎉"
        result = adapter.encrypt(data)
        assert isinstance(result, str)


# =============================================================================
# TESTS - DECRYPT
# =============================================================================


class TestDecrypt:
    """Tests pour decrypt."""

    def test_decrypt_returns_original(self, adapter):
        """decrypt retourne les donnees originales."""
        original = "secret message"
        encrypted = adapter.encrypt(original)
        decrypted = adapter.decrypt(encrypted)
        assert decrypted == original

    def test_decrypt_empty_string(self, adapter):
        """decrypt fonctionne avec une chaine vide chiffree."""
        encrypted = adapter.encrypt("")
        decrypted = adapter.decrypt(encrypted)
        assert decrypted == ""

    def test_decrypt_unicode(self, adapter):
        """decrypt preserve l'unicode."""
        original = "Répondre à 日本語 émoji 🎉"
        encrypted = adapter.encrypt(original)
        decrypted = adapter.decrypt(encrypted)
        assert decrypted == original

    def test_decrypt_invalid_data_raises_value_error(self, adapter):
        """decrypt leve ValueError pour des donnees invalides."""
        with pytest.raises(ValueError):
            adapter.decrypt("invalid-not-encrypted-data")

    def test_decrypt_wrong_key_raises_value_error(self, known_key):
        """decrypt avec mauvaise cle leve ValueError."""
        adapter1 = FernetCryptographerAdapter(key=known_key)
        adapter2 = FernetCryptographerAdapter()

        encrypted = adapter1.encrypt("secret")
        with pytest.raises(ValueError):
            adapter2.decrypt(encrypted)

    def test_decrypt_tampered_data_raises_value_error(self, adapter):
        """decrypt avec donnees alterees leve ValueError."""
        encrypted = adapter.encrypt("secret")
        tampered = encrypted[:-5] + "XXXXX"
        with pytest.raises(ValueError):
            adapter.decrypt(tampered)


# =============================================================================
# TESTS - ENCRYPT DICT
# =============================================================================


class TestEncryptDict:
    """Tests pour encrypt_dict."""

    def test_encrypt_dict_returns_string(self, adapter):
        """encrypt_dict retourne une string."""
        data = {"key": "value"}
        result = adapter.encrypt_dict(data)
        assert isinstance(result, str)

    def test_encrypt_dict_simple(self, adapter):
        """encrypt_dict fonctionne avec un dictionnaire simple."""
        data = {"name": "John", "age": 30}
        result = adapter.encrypt_dict(data)
        assert result != json.dumps(data)

    def test_encrypt_dict_empty(self, adapter):
        """encrypt_dict fonctionne avec un dictionnaire vide."""
        result = adapter.encrypt_dict({})
        assert isinstance(result, str)

    def test_encrypt_dict_nested(self, adapter):
        """encrypt_dict fonctionne avec un dictionnaire imbrique."""
        data = {
            "user": {"name": "Alice", "email": "alice@example.com"},
            "items": [1, 2, 3],
            "active": True,
        }
        result = adapter.encrypt_dict(data)
        assert isinstance(result, str)

    def test_encrypt_dict_unicode(self, adapter):
        """encrypt_dict supporte l'unicode."""
        data = {"message": "日本語 テスト", "emoji": "🎉"}
        result = adapter.encrypt_dict(data)
        assert isinstance(result, str)


# =============================================================================
# TESTS - DECRYPT DICT
# =============================================================================


class TestDecryptDict:
    """Tests pour decrypt_dict."""

    def test_decrypt_dict_returns_original(self, adapter):
        """decrypt_dict retourne le dictionnaire original."""
        original = {"key": "value", "number": 42}
        encrypted = adapter.encrypt_dict(original)
        decrypted = adapter.decrypt_dict(encrypted)
        assert decrypted == original

    def test_decrypt_dict_empty(self, adapter):
        """decrypt_dict fonctionne avec un dictionnaire vide."""
        encrypted = adapter.encrypt_dict({})
        decrypted = adapter.decrypt_dict(encrypted)
        assert decrypted == {}

    def test_decrypt_dict_nested(self, adapter):
        """decrypt_dict preserve les structures imbriquees."""
        original = {
            "user": {"name": "Alice", "roles": ["admin", "user"]},
            "settings": {"theme": "dark", "notifications": True},
        }
        encrypted = adapter.encrypt_dict(original)
        decrypted = adapter.decrypt_dict(encrypted)
        assert decrypted == original

    def test_decrypt_dict_unicode(self, adapter):
        """decrypt_dict preserve l'unicode."""
        original = {"message": "日本語 テスト", "emoji": "🎉"}
        encrypted = adapter.encrypt_dict(original)
        decrypted = adapter.decrypt_dict(encrypted)
        assert decrypted == original

    def test_decrypt_dict_invalid_data_raises_value_error(self, adapter):
        """decrypt_dict leve ValueError pour des donnees invalides."""
        with pytest.raises(ValueError):
            adapter.decrypt_dict("not-encrypted-data")

    def test_decrypt_dict_invalid_json_raises_value_error(self, adapter):
        """decrypt_dict leve ValueError si le JSON dechiffre est invalide."""
        encrypted = adapter.encrypt("not valid json {{{")
        with pytest.raises(ValueError):
            adapter.decrypt_dict(encrypted)

    def test_decrypt_dict_wrong_key_raises_value_error(self, known_key):
        """decrypt_dict avec mauvaise cle leve ValueError."""
        adapter1 = FernetCryptographerAdapter(key=known_key)
        adapter2 = FernetCryptographerAdapter()

        encrypted = adapter1.encrypt_dict({"secret": "data"})
        with pytest.raises(ValueError):
            adapter2.decrypt_dict(encrypted)


# =============================================================================
# TESTS - HASH EMAIL
# =============================================================================


class TestHashEmail:
    """Tests pour hash_email."""

    def test_hash_email_returns_string(self, adapter):
        """hash_email retourne une string."""
        result = adapter.hash_email("test@example.com")
        assert isinstance(result, str)

    def test_hash_email_returns_hex_digest(self, adapter):
        """hash_email retourne un digest hexadecimal SHA-256 (64 caracteres)."""
        result = adapter.hash_email("test@example.com")
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_hash_email_deterministic(self, adapter):
        """hash_email est deterministe."""
        email = "user@domain.com"
        hash1 = adapter.hash_email(email)
        hash2 = adapter.hash_email(email)
        assert hash1 == hash2

    def test_hash_email_normalizes_lowercase(self, adapter):
        """hash_email normalise en lowercase."""
        hash_lower = adapter.hash_email("user@example.com")
        hash_upper = adapter.hash_email("USER@EXAMPLE.COM")
        hash_mixed = adapter.hash_email("User@Example.COM")
        assert hash_lower == hash_upper == hash_mixed

    def test_hash_email_strips_whitespace(self, adapter):
        """hash_email supprime les espaces."""
        hash_clean = adapter.hash_email("user@example.com")
        hash_spaces = adapter.hash_email("  user@example.com  ")
        hash_tabs = adapter.hash_email("\tuser@example.com\n")
        assert hash_clean == hash_spaces == hash_tabs

    def test_hash_email_different_emails_different_hashes(self, adapter):
        """hash_email genere des hashes differents pour des emails differents."""
        hash1 = adapter.hash_email("user1@example.com")
        hash2 = adapter.hash_email("user2@example.com")
        assert hash1 != hash2

    def test_hash_email_matches_direct_sha256(self, adapter):
        """hash_email correspond a SHA-256 direct sur email normalise."""
        email = "Test@Example.COM  "
        normalized = email.strip().lower()
        expected = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        result = adapter.hash_email(email)
        assert result == expected

    def test_hash_email_empty_string(self, adapter):
        """hash_email fonctionne avec une chaine vide."""
        result = adapter.hash_email("")
        expected = hashlib.sha256(b"").hexdigest()
        assert result == expected


# =============================================================================
# TESTS - KEY MANAGEMENT
# =============================================================================


class TestKeyManagement:
    """Tests pour la gestion des cles."""

    def test_adapter_generates_key_if_none(self):
        """L'adapter genere une cle si aucune n'est fournie."""
        adapter = FernetCryptographerAdapter()
        encrypted = adapter.encrypt("test")
        decrypted = adapter.decrypt(encrypted)
        assert decrypted == "test"

    def test_adapter_accepts_bytes_key(self, known_key):
        """L'adapter accepte une cle bytes."""
        adapter = FernetCryptographerAdapter(key=known_key)
        encrypted = adapter.encrypt("test")
        decrypted = adapter.decrypt(encrypted)
        assert decrypted == "test"

    def test_adapter_accepts_string_key(self, known_key):
        """L'adapter accepte une cle string (base64)."""
        key_str = known_key.decode("utf-8")
        adapter = FernetCryptographerAdapter(key=key_str)
        encrypted = adapter.encrypt("test")
        decrypted = adapter.decrypt(encrypted)
        assert decrypted == "test"

    def test_same_key_can_decrypt(self, known_key):
        """Deux adapters avec la meme cle peuvent se dechiffrer mutuellement."""
        adapter1 = FernetCryptographerAdapter(key=known_key)
        adapter2 = FernetCryptographerAdapter(key=known_key)

        encrypted = adapter1.encrypt("shared secret")
        decrypted = adapter2.decrypt(encrypted)
        assert decrypted == "shared secret"

    def test_different_adapters_generate_different_keys(self):
        """Deux adapters sans cle generent des cles differentes."""
        adapter1 = FernetCryptographerAdapter()
        adapter2 = FernetCryptographerAdapter()

        encrypted = adapter1.encrypt("test")
        with pytest.raises(ValueError):
            adapter2.decrypt(encrypted)


# =============================================================================
# TESTS - EDGE CASES
# =============================================================================


class TestEdgeCases:
    """Tests des cas limites."""

    def test_encrypt_very_long_string(self, adapter):
        """encrypt fonctionne avec une tres longue chaine."""
        long_string = "A" * 100000
        encrypted = adapter.encrypt(long_string)
        decrypted = adapter.decrypt(encrypted)
        assert decrypted == long_string

    def test_encrypt_special_characters(self, adapter):
        """encrypt supporte les caracteres speciaux."""
        special = "!@#$%^&*()_+-=[]{}|;':\",./<>?\n\t\r"
        encrypted = adapter.encrypt(special)
        decrypted = adapter.decrypt(encrypted)
        assert decrypted == special

    def test_encrypt_newlines(self, adapter):
        """encrypt preserve les sauts de ligne."""
        text = "Line 1\nLine 2\r\nLine 3"
        encrypted = adapter.encrypt(text)
        decrypted = adapter.decrypt(encrypted)
        assert decrypted == text

    def test_encrypt_dict_with_special_json_values(self, adapter):
        """encrypt_dict gere les valeurs JSON speciales."""
        data = {
            "null_value": None,
            "bool_true": True,
            "bool_false": False,
            "float_val": 3.14159,
            "int_val": 42,
            "list_val": [1, "two", None],
        }
        encrypted = adapter.encrypt_dict(data)
        decrypted = adapter.decrypt_dict(encrypted)
        assert decrypted == data

    def test_hash_email_with_unicode(self, adapter):
        """hash_email fonctionne avec des emails unicode (theoriquement)."""
        email = "tëst@éxàmple.com"
        result = adapter.hash_email(email)
        assert len(result) == 64

    def test_hash_email_only_whitespace(self, adapter):
        """hash_email avec que des espaces retourne hash de chaine vide."""
        result = adapter.hash_email("   \t\n  ")
        expected = hashlib.sha256(b"").hexdigest()
        assert result == expected

    def test_roundtrip_complex_data(self, adapter):
        """Roundtrip complet avec donnees complexes."""
        original = {
            "user": {
                "name": "Jean-Pierre L'écuyer",
                "email": "jp@example.com",
                "roles": ["admin", "développeur"],
            },
            "metadata": {
                "créé_le": "2024-01-15T10:30:00",
                "valide": True,
                "score": 98.5,
            },
            "tags": ["urgent", "à faire", "日本語"],
        }
        encrypted = adapter.encrypt_dict(original)
        decrypted = adapter.decrypt_dict(encrypted)
        assert decrypted == original

    def test_encrypt_binary_like_string(self, adapter):
        """encrypt fonctionne avec des chaines ressemblant a du binaire."""
        data = "\\x00\\x01\\x02\\xff"
        encrypted = adapter.encrypt(data)
        decrypted = adapter.decrypt(encrypted)
        assert decrypted == data


# =============================================================================
# TESTS - INVALID KEY FORMATS
# =============================================================================


class TestInvalidKeyFormats:
    """Tests pour les formats de cle invalides."""

    def test_invalid_key_too_short_raises_error(self):
        """Une cle trop courte leve une erreur."""
        with pytest.raises(Exception):  # Fernet leve ValueError
            FernetCryptographerAdapter(key=b"tooshort")

    def test_invalid_key_not_base64_raises_error(self):
        """Une cle non-base64 valide leve une erreur."""
        with pytest.raises(Exception):
            FernetCryptographerAdapter(key="not-valid-base64-key!!!")

    def test_invalid_key_wrong_length_base64_raises_error(self):
        """Une cle base64 de mauvaise longueur leve une erreur."""
        import base64
        # Cle de 16 bytes au lieu de 32 requis par Fernet
        short_key = base64.urlsafe_b64encode(b"0123456789abcdef")
        with pytest.raises(Exception):
            FernetCryptographerAdapter(key=short_key)


# =============================================================================
# TESTS - DICT EDGE CASES
# =============================================================================


class TestDictEdgeCases:
    """Tests pour les cas limites avec les dictionnaires."""

    def test_encrypt_dict_with_none_key(self, adapter):
        """encrypt_dict fonctionne avec None comme cle est invalide en JSON."""
        # En JSON, les cles doivent etre des strings, donc on teste
        # que les valeurs None dans les valeurs fonctionnent
        data = {"key": None, "nested": {"also": None}}
        encrypted = adapter.encrypt_dict(data)
        decrypted = adapter.decrypt_dict(encrypted)
        assert decrypted == data

    def test_encrypt_dict_with_numeric_string_keys(self, adapter):
        """encrypt_dict fonctionne avec des cles numeriques en string."""
        data = {"1": "one", "2": "two", "999": "many"}
        encrypted = adapter.encrypt_dict(data)
        decrypted = adapter.decrypt_dict(encrypted)
        assert decrypted == data

    def test_encrypt_dict_with_empty_string_key(self, adapter):
        """encrypt_dict fonctionne avec une cle vide."""
        data = {"": "empty key value", "normal": "value"}
        encrypted = adapter.encrypt_dict(data)
        decrypted = adapter.decrypt_dict(encrypted)
        assert decrypted == data

    def test_encrypt_dict_with_deeply_nested_structure(self, adapter):
        """encrypt_dict fonctionne avec une structure tres imbriquee."""
        data = {"level1": {"level2": {"level3": {"level4": {"level5": "deep"}}}}}
        encrypted = adapter.encrypt_dict(data)
        decrypted = adapter.decrypt_dict(encrypted)
        assert decrypted == data

    def test_encrypt_dict_with_large_list(self, adapter):
        """encrypt_dict fonctionne avec une grande liste."""
        data = {"items": list(range(1000))}
        encrypted = adapter.encrypt_dict(data)
        decrypted = adapter.decrypt_dict(encrypted)
        assert decrypted == data

    def test_encrypt_dict_with_mixed_types_in_list(self, adapter):
        """encrypt_dict fonctionne avec des types mixtes dans une liste."""
        data = {"mixed": [1, "two", 3.0, True, None, {"nested": "dict"}, [1, 2, 3]]}
        encrypted = adapter.encrypt_dict(data)
        decrypted = adapter.decrypt_dict(encrypted)
        assert decrypted == data


# =============================================================================
# TESTS - NON SERIALIZABLE VALUES
# =============================================================================


class TestNonSerializableValues:
    """Tests pour les valeurs non-serialisables JSON."""

    def test_encrypt_dict_with_set_raises_type_error(self, adapter):
        """encrypt_dict avec un set leve TypeError (non JSON-serializable)."""
        data = {"items": {1, 2, 3}}  # Set n'est pas JSON serializable
        with pytest.raises(TypeError):
            adapter.encrypt_dict(data)

    def test_encrypt_dict_with_bytes_raises_type_error(self, adapter):
        """encrypt_dict avec bytes leve TypeError."""
        data = {"binary": b"bytes data"}
        with pytest.raises(TypeError):
            adapter.encrypt_dict(data)

    def test_encrypt_dict_with_datetime_raises_type_error(self, adapter):
        """encrypt_dict avec datetime leve TypeError."""
        from datetime import datetime
        data = {"timestamp": datetime.now()}
        with pytest.raises(TypeError):
            adapter.encrypt_dict(data)

    def test_encrypt_dict_with_custom_object_raises_type_error(self, adapter):
        """encrypt_dict avec un objet custom leve TypeError."""
        class CustomClass:
            pass
        data = {"obj": CustomClass()}
        with pytest.raises(TypeError):
            adapter.encrypt_dict(data)


# =============================================================================
# TESTS - DECRYPT EDGE CASES
# =============================================================================


class TestDecryptEdgeCases:
    """Tests pour les cas limites de dechiffrement."""

    def test_decrypt_empty_string_raises_value_error(self, adapter):
        """decrypt avec une chaine vide leve ValueError."""
        with pytest.raises(ValueError):
            adapter.decrypt("")

    def test_decrypt_whitespace_only_raises_value_error(self, adapter):
        """decrypt avec que des espaces leve ValueError."""
        with pytest.raises(ValueError):
            adapter.decrypt("   ")

    def test_decrypt_valid_base64_but_not_fernet_raises_value_error(self, adapter):
        """decrypt avec base64 valide mais pas Fernet leve ValueError."""
        import base64
        fake_encrypted = base64.urlsafe_b64encode(b"not a fernet token").decode()
        with pytest.raises(ValueError):
            adapter.decrypt(fake_encrypted)

    def test_decrypt_dict_with_list_result_raises_value_error(self, adapter):
        """decrypt_dict retournant une liste leve ValueError."""
        # Chiffrer une liste au lieu d'un dict
        encrypted = adapter.encrypt("[1, 2, 3]")
        with pytest.raises(ValueError):
            adapter.decrypt_dict(encrypted)

    def test_decrypt_dict_with_primitive_result_raises_value_error(self, adapter):
        """decrypt_dict retournant un primitif leve ValueError."""
        encrypted = adapter.encrypt("42")
        with pytest.raises(ValueError):
            adapter.decrypt_dict(encrypted)


# =============================================================================
# TESTS - HASH EMAIL EDGE CASES
# =============================================================================


class TestHashEmailEdgeCases:
    """Tests pour les cas limites de hash_email."""

    def test_hash_email_with_plus_addressing(self, adapter):
        """hash_email fonctionne avec l'adressage plus."""
        # Note: la normalisation actuelle ne gere pas le +, on teste juste que ca fonctionne
        result = adapter.hash_email("user+tag@example.com")
        assert len(result) == 64

    def test_hash_email_with_subdomain(self, adapter):
        """hash_email fonctionne avec des sous-domaines."""
        result = adapter.hash_email("user@mail.subdomain.example.com")
        assert len(result) == 64

    def test_hash_email_very_long(self, adapter):
        """hash_email fonctionne avec un email tres long."""
        long_local = "a" * 64
        long_domain = "b" * 63 + ".com"
        email = f"{long_local}@{long_domain}"
        result = adapter.hash_email(email)
        assert len(result) == 64

    def test_hash_email_with_dots_in_local_part(self, adapter):
        """hash_email fonctionne avec des points dans la partie locale."""
        result = adapter.hash_email("first.middle.last@example.com")
        assert len(result) == 64

    def test_hash_email_international_domain(self, adapter):
        """hash_email fonctionne avec des domaines internationaux."""
        result = adapter.hash_email("user@exemple.fr")
        assert len(result) == 64


# =============================================================================
# TESTS - CONCURRENT USAGE
# =============================================================================


# =============================================================================
# TESTS - ADDITIONAL DECRYPT DICT EDGE CASES
# =============================================================================


class TestDecryptDictAdditionalEdgeCases:
    """Tests supplementaires pour decrypt_dict avec JSON valides mais non-dict."""

    @pytest.fixture
    def adapter(self):
        return FernetCryptographerAdapter()

    def test_decrypt_dict_with_null_json_raises_value_error(self, adapter):
        """decrypt_dict avec null JSON leve ValueError."""
        encrypted = adapter.encrypt("null")
        with pytest.raises(ValueError) as exc_info:
            adapter.decrypt_dict(encrypted)
        assert "expected dict" in str(exc_info.value)

    def test_decrypt_dict_with_string_json_raises_value_error(self, adapter):
        """decrypt_dict avec string JSON leve ValueError."""
        encrypted = adapter.encrypt('"just a string"')
        with pytest.raises(ValueError) as exc_info:
            adapter.decrypt_dict(encrypted)
        assert "expected dict" in str(exc_info.value)

    def test_decrypt_dict_with_boolean_true_json_raises_value_error(self, adapter):
        """decrypt_dict avec true JSON leve ValueError."""
        encrypted = adapter.encrypt("true")
        with pytest.raises(ValueError) as exc_info:
            adapter.decrypt_dict(encrypted)
        assert "expected dict" in str(exc_info.value)

    def test_decrypt_dict_with_boolean_false_json_raises_value_error(self, adapter):
        """decrypt_dict avec false JSON leve ValueError."""
        encrypted = adapter.encrypt("false")
        with pytest.raises(ValueError) as exc_info:
            adapter.decrypt_dict(encrypted)
        assert "expected dict" in str(exc_info.value)

    def test_decrypt_dict_with_number_json_raises_value_error(self, adapter):
        """decrypt_dict avec number JSON leve ValueError."""
        encrypted = adapter.encrypt("3.14159")
        with pytest.raises(ValueError) as exc_info:
            adapter.decrypt_dict(encrypted)
        assert "expected dict" in str(exc_info.value)


# =============================================================================
# TESTS - EMPTY KEY STRING
# =============================================================================


class TestEmptyKeyString:
    """Tests pour une cle vide ou invalide."""

    def test_empty_string_key_raises_error(self):
        """Une cle string vide leve une erreur."""
        with pytest.raises(Exception):
            FernetCryptographerAdapter(key="")

    def test_whitespace_only_key_raises_error(self):
        """Une cle avec seulement des espaces leve une erreur."""
        with pytest.raises(Exception):
            FernetCryptographerAdapter(key="   ")


# =============================================================================
# TESTS - CONCURRENT USAGE
# =============================================================================


class TestConcurrentUsage:
    """Tests pour l'utilisation concurrente."""

    def test_adapter_is_thread_safe_for_encrypt(self, adapter):
        """L'adapter peut etre utilise de maniere concurrente pour encrypt."""
        import threading
        results = []
        errors = []

        def encrypt_task(data, index):
            try:
                encrypted = adapter.encrypt(data)
                decrypted = adapter.decrypt(encrypted)
                results.append((index, decrypted == data))
            except Exception as e:
                errors.append((index, e))

        threads = []
        for i in range(10):
            t = threading.Thread(target=encrypt_task, args=(f"data_{i}", i))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        assert len(errors) == 0
        assert all(success for _, success in results)

    def test_adapter_is_thread_safe_for_hash(self, adapter):
        """L'adapter peut etre utilise de maniere concurrente pour hash."""
        import threading
        results = {}
        errors = []

        def hash_task(email, index):
            try:
                h = adapter.hash_email(email)
                results[index] = h
            except Exception as e:
                errors.append((index, e))

        threads = []
        for i in range(10):
            t = threading.Thread(
                target=hash_task,
                args=(f"user{i}@example.com", i)
            )
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results) == 10
        # Tous les hashes devraient etre differents
        assert len(set(results.values())) == 10
