import pytest

from app.domain.entities.anonymization import (
    AnonymizedResult,
    AnonymizedToken,
    SecureAnonymizedData,
    SecureTokenMapping,
)
from app.domain.entities.sensitive_data import (
    SensitiveDataDetection,
    SensitiveDataItem,
    SensitiveDataType,
)
from app.domain.services.anonymizer_service import (
    DataAnonymizer,
    InvalidCredentialsError,
    generate_encryption_key,
)


@pytest.fixture
def encryption_key() -> bytes:
    """Clé de test stable pour les tests déterministes."""
    return b"0123456789abcdef0123456789abcdef"  # Exactement 32 bytes


@pytest.fixture
def wrong_key() -> bytes:
    """Clé incorrecte pour tester les erreurs d'authentification."""
    return b"fedcba9876543210fedcba9876543210"  # Exactement 32 bytes


class TestDataAnonymizerAnonymize:
    def test_anonymize_text_with_email(self, encryption_key):
        anonymizer = DataAnonymizer()
        text = "Contactez-moi à john.doe@example.com pour plus d'infos."
        detection = SensitiveDataDetection(
            is_sensitive=True,
            confidence=0.9,
            detected_items=[
                SensitiveDataItem(
                    data_type=SensitiveDataType.PERSONAL,
                    description="Email address",
                    snippet="john.doe@example.com",
                )
            ],
            analysis_summary="Email detected",
        )

        secure_data = anonymizer.anonymize(text, detection, encryption_key)

        assert "john.doe@example.com" not in secure_data.result.anonymized_text
        assert "[ANON:PERSONAL:" in secure_data.result.anonymized_text
        assert len(secure_data.result.tokens) == 1
        assert len(secure_data.secure_mappings) == 1
        assert secure_data.result.tokens[0].data_type == SensitiveDataType.PERSONAL

    def test_anonymize_text_with_iban(self, encryption_key):
        anonymizer = DataAnonymizer()
        text = "Mon IBAN est FR7630006000011234567890189"
        detection = SensitiveDataDetection(
            is_sensitive=True,
            confidence=0.95,
            detected_items=[
                SensitiveDataItem(
                    data_type=SensitiveDataType.FINANCIAL,
                    description="IBAN",
                    snippet="FR7630006000011234567890189",
                )
            ],
            analysis_summary="IBAN detected",
        )

        secure_data = anonymizer.anonymize(text, detection, encryption_key)

        assert "FR7630006000011234567890189" not in secure_data.result.anonymized_text
        assert "[ANON:FINANCIAL:" in secure_data.result.anonymized_text
        assert secure_data.result.tokens[0].data_type == SensitiveDataType.FINANCIAL

    def test_anonymize_text_with_phone(self, encryption_key):
        anonymizer = DataAnonymizer()
        text = "Appelez-moi au 06 12 34 56 78"
        detection = SensitiveDataDetection(
            is_sensitive=True,
            confidence=0.85,
            detected_items=[
                SensitiveDataItem(
                    data_type=SensitiveDataType.PERSONAL,
                    description="Phone number",
                    snippet="06 12 34 56 78",
                )
            ],
            analysis_summary="Phone detected",
        )

        secure_data = anonymizer.anonymize(text, detection, encryption_key)

        assert "06 12 34 56 78" not in secure_data.result.anonymized_text
        assert "[ANON:PERSONAL:" in secure_data.result.anonymized_text

    def test_anonymize_multiple_sensitive_items(self, encryption_key):
        anonymizer = DataAnonymizer()
        text = "Email: test@mail.com, IBAN: DE89370400440532013000"
        detection = SensitiveDataDetection(
            is_sensitive=True,
            confidence=0.9,
            detected_items=[
                SensitiveDataItem(
                    data_type=SensitiveDataType.PERSONAL,
                    description="Email",
                    snippet="test@mail.com",
                ),
                SensitiveDataItem(
                    data_type=SensitiveDataType.FINANCIAL,
                    description="IBAN",
                    snippet="DE89370400440532013000",
                ),
            ],
            analysis_summary="Multiple items detected",
        )

        secure_data = anonymizer.anonymize(text, detection, encryption_key)

        assert "test@mail.com" not in secure_data.result.anonymized_text
        assert "DE89370400440532013000" not in secure_data.result.anonymized_text
        assert len(secure_data.result.tokens) == 2
        assert len(secure_data.secure_mappings) == 2

    def test_anonymize_text_without_sensitive_data(self, encryption_key):
        anonymizer = DataAnonymizer()
        text = "Bonjour, comment allez-vous ?"
        detection = SensitiveDataDetection(
            is_sensitive=False,
            confidence=0.0,
            detected_items=[],
            analysis_summary="No sensitive data",
        )

        secure_data = anonymizer.anonymize(text, detection, encryption_key)

        assert secure_data.result.anonymized_text == text
        assert len(secure_data.result.tokens) == 0
        assert len(secure_data.secure_mappings) == 0

    def test_anonymize_empty_text(self, encryption_key):
        anonymizer = DataAnonymizer()
        text = ""
        detection = SensitiveDataDetection.default()

        secure_data = anonymizer.anonymize(text, detection, encryption_key)

        assert secure_data.result.anonymized_text == ""
        assert len(secure_data.result.tokens) == 0

    def test_anonymize_generates_unique_token_ids(self, encryption_key):
        anonymizer = DataAnonymizer()
        text = "Emails: a@b.com et c@d.com"
        detection = SensitiveDataDetection(
            is_sensitive=True,
            confidence=0.9,
            detected_items=[
                SensitiveDataItem(
                    data_type=SensitiveDataType.PERSONAL,
                    description="Email 1",
                    snippet="a@b.com",
                ),
                SensitiveDataItem(
                    data_type=SensitiveDataType.PERSONAL,
                    description="Email 2",
                    snippet="c@d.com",
                ),
            ],
            analysis_summary="Two emails",
        )

        secure_data = anonymizer.anonymize(text, detection, encryption_key)

        token_ids = [t.token_id for t in secure_data.result.tokens]
        assert len(token_ids) == len(set(token_ids))

    def test_anonymize_stores_original_text_hash(self, encryption_key):
        anonymizer = DataAnonymizer()
        text = "Mon email: test@example.com"
        detection = SensitiveDataDetection(
            is_sensitive=True,
            confidence=0.9,
            detected_items=[
                SensitiveDataItem(
                    data_type=SensitiveDataType.PERSONAL,
                    description="Email",
                    snippet="test@example.com",
                )
            ],
            analysis_summary="Email detected",
        )

        secure_data = anonymizer.anonymize(text, detection, encryption_key)

        assert secure_data.result.original_text_hash != ""
        assert len(secure_data.result.original_text_hash) == 64

    def test_anonymize_same_snippet_multiple_occurrences(self, encryption_key):
        anonymizer = DataAnonymizer()
        text = "Email: test@mail.com, confirmation: test@mail.com"
        detection = SensitiveDataDetection(
            is_sensitive=True,
            confidence=0.9,
            detected_items=[
                SensitiveDataItem(
                    data_type=SensitiveDataType.PERSONAL,
                    description="Email",
                    snippet="test@mail.com",
                )
            ],
            analysis_summary="Email detected",
        )

        secure_data = anonymizer.anonymize(text, detection, encryption_key)

        assert "test@mail.com" not in secure_data.result.anonymized_text
        assert secure_data.result.anonymized_text.count("[ANON:PERSONAL:") == 2

    def test_anonymize_snippet_not_found_in_text(self, encryption_key):
        """Edge case: detection contient un snippet qui n'est plus dans le texte."""
        anonymizer = DataAnonymizer()
        text = "Texte normal sans données sensibles"
        detection = SensitiveDataDetection(
            is_sensitive=True,
            confidence=0.9,
            detected_items=[
                SensitiveDataItem(
                    data_type=SensitiveDataType.PERSONAL,
                    description="Email inexistant",
                    snippet="ghost@email.com",
                )
            ],
            analysis_summary="False positive",
        )

        secure_data = anonymizer.anonymize(text, detection, encryption_key)

        assert secure_data.result.anonymized_text == text
        assert len(secure_data.result.tokens) == 0

    def test_anonymize_is_sensitive_true_but_empty_items(self, encryption_key):
        """Edge case: is_sensitive=True mais detected_items est vide."""
        anonymizer = DataAnonymizer()
        text = "Texte potentiellement sensible"
        detection = SensitiveDataDetection(
            is_sensitive=True,
            confidence=0.5,
            detected_items=[],
            analysis_summary="Ambiguous detection",
        )

        secure_data = anonymizer.anonymize(text, detection, encryption_key)

        assert secure_data.result.anonymized_text == text
        assert len(secure_data.result.tokens) == 0

    def test_anonymize_with_credential_type(self, encryption_key):
        """Teste le type CREDENTIAL qui n'était pas testé."""
        anonymizer = DataAnonymizer()
        text = "Mot de passe: SuperSecret123!"
        detection = SensitiveDataDetection(
            is_sensitive=True,
            confidence=0.95,
            detected_items=[
                SensitiveDataItem(
                    data_type=SensitiveDataType.CREDENTIAL,
                    description="Password",
                    snippet="SuperSecret123!",
                )
            ],
            analysis_summary="Credential detected",
        )

        secure_data = anonymizer.anonymize(text, detection, encryption_key)

        assert "SuperSecret123!" not in secure_data.result.anonymized_text
        assert "[ANON:CREDENTIAL:" in secure_data.result.anonymized_text
        assert secure_data.result.tokens[0].data_type == SensitiveDataType.CREDENTIAL

    def test_anonymize_with_commercial_secret_type(self, encryption_key):
        """Teste le type COMMERCIAL_SECRET qui n'était pas testé."""
        anonymizer = DataAnonymizer()
        text = "Notre marge est de 45% sur ce produit"
        detection = SensitiveDataDetection(
            is_sensitive=True,
            confidence=0.9,
            detected_items=[
                SensitiveDataItem(
                    data_type=SensitiveDataType.COMMERCIAL_SECRET,
                    description="Profit margin",
                    snippet="45%",
                )
            ],
            analysis_summary="Commercial secret detected",
        )

        secure_data = anonymizer.anonymize(text, detection, encryption_key)

        assert "45%" not in secure_data.result.anonymized_text
        assert "[ANON:COMMERCIAL:" in secure_data.result.anonymized_text

    def test_anonymize_snippet_with_regex_special_chars(self, encryption_key):
        """Edge case: snippet contient des caractères spéciaux regex."""
        anonymizer = DataAnonymizer()
        text = "Email avec plus: user+tag@domain.com"
        detection = SensitiveDataDetection(
            is_sensitive=True,
            confidence=0.9,
            detected_items=[
                SensitiveDataItem(
                    data_type=SensitiveDataType.PERSONAL,
                    description="Email with plus",
                    snippet="user+tag@domain.com",
                )
            ],
            analysis_summary="Email detected",
        )

        secure_data = anonymizer.anonymize(text, detection, encryption_key)

        assert "user+tag@domain.com" not in secure_data.result.anonymized_text
        assert "[ANON:PERSONAL:" in secure_data.result.anonymized_text

    def test_anonymize_unicode_text(self, encryption_key):
        """Edge case: texte avec caractères Unicode et emojis."""
        anonymizer = DataAnonymizer()
        text = "Contactez 日本語@example.com 📧"
        detection = SensitiveDataDetection(
            is_sensitive=True,
            confidence=0.9,
            detected_items=[
                SensitiveDataItem(
                    data_type=SensitiveDataType.PERSONAL,
                    description="Email unicode",
                    snippet="日本語@example.com",
                )
            ],
            analysis_summary="Unicode email detected",
        )

        secure_data = anonymizer.anonymize(text, detection, encryption_key)

        assert "日本語@example.com" not in secure_data.result.anonymized_text
        assert "📧" in secure_data.result.anonymized_text
        revealed = anonymizer.reveal(secure_data, encryption_key)
        assert revealed == text

    def test_anonymize_token_id_length(self, encryption_key):
        """Vérifie que le token_id fait exactement 8 caractères."""
        anonymizer = DataAnonymizer()
        text = "Email: test@example.com"
        detection = SensitiveDataDetection(
            is_sensitive=True,
            confidence=0.9,
            detected_items=[
                SensitiveDataItem(
                    data_type=SensitiveDataType.PERSONAL,
                    description="Email",
                    snippet="test@example.com",
                )
            ],
            analysis_summary="Email detected",
        )

        secure_data = anonymizer.anonymize(text, detection, encryption_key)

        assert len(secure_data.result.tokens[0].token_id) == 8

    def test_anonymize_hash_is_deterministic(self, encryption_key):
        """Vérifie que le même texte produit le même hash."""
        anonymizer = DataAnonymizer()
        text = "Texte de test pour hash"
        detection = SensitiveDataDetection.default()

        result1 = anonymizer.anonymize(text, detection, encryption_key)
        result2 = anonymizer.anonymize(text, detection, encryption_key)

        assert result1.result.original_text_hash == result2.result.original_text_hash

    def test_anonymize_overlapping_snippets(self, encryption_key):
        """Edge case: données sensibles qui se chevauchent partiellement."""
        anonymizer = DataAnonymizer()
        text = "Contact: john.doe@example.com"
        detection = SensitiveDataDetection(
            is_sensitive=True,
            confidence=0.9,
            detected_items=[
                SensitiveDataItem(
                    data_type=SensitiveDataType.PERSONAL,
                    description="Full email",
                    snippet="john.doe@example.com",
                ),
                SensitiveDataItem(
                    data_type=SensitiveDataType.PERSONAL,
                    description="Name part",
                    snippet="john.doe",
                ),
            ],
            analysis_summary="Overlapping items detected",
        )

        secure_data = anonymizer.anonymize(text, detection, encryption_key)

        # Le premier snippet remplace l'email complet
        assert "john.doe@example.com" not in secure_data.result.anonymized_text
        # Le second snippet ne devrait plus être trouvé car déjà remplacé
        assert len(secure_data.result.tokens) == 1
        revealed = anonymizer.reveal(secure_data, encryption_key)
        assert revealed == text

    def test_anonymize_requires_32_byte_key(self):
        """Vérifie qu'une clé de mauvaise taille lève une exception."""
        anonymizer = DataAnonymizer()
        text = "Email: test@example.com"
        detection = SensitiveDataDetection.default()
        short_key = b"too_short"

        with pytest.raises(ValueError, match="32 bytes"):
            anonymizer.anonymize(text, detection, short_key)

    def test_anonymize_stores_key_id(self, encryption_key):
        """Vérifie que le key_id est stocké pour vérification ultérieure."""
        anonymizer = DataAnonymizer()
        text = "Email: test@example.com"
        detection = SensitiveDataDetection(
            is_sensitive=True,
            confidence=0.9,
            detected_items=[
                SensitiveDataItem(
                    data_type=SensitiveDataType.PERSONAL,
                    description="Email",
                    snippet="test@example.com",
                )
            ],
            analysis_summary="Email detected",
        )

        secure_data = anonymizer.anonymize(text, detection, encryption_key)

        assert secure_data.key_id != ""
        assert len(secure_data.key_id) == 16


class TestDataAnonymizerReveal:
    def test_reveal_restores_original_text(self, encryption_key):
        anonymizer = DataAnonymizer()
        original_text = "Contactez john.doe@example.com"
        detection = SensitiveDataDetection(
            is_sensitive=True,
            confidence=0.9,
            detected_items=[
                SensitiveDataItem(
                    data_type=SensitiveDataType.PERSONAL,
                    description="Email",
                    snippet="john.doe@example.com",
                )
            ],
            analysis_summary="Email detected",
        )

        secure_data = anonymizer.anonymize(original_text, detection, encryption_key)
        revealed = anonymizer.reveal(secure_data, encryption_key)

        assert revealed == original_text

    def test_reveal_multiple_tokens(self, encryption_key):
        anonymizer = DataAnonymizer()
        original_text = "Email: a@b.com, IBAN: FR7612345678901234567890123"
        detection = SensitiveDataDetection(
            is_sensitive=True,
            confidence=0.9,
            detected_items=[
                SensitiveDataItem(
                    data_type=SensitiveDataType.PERSONAL,
                    description="Email",
                    snippet="a@b.com",
                ),
                SensitiveDataItem(
                    data_type=SensitiveDataType.FINANCIAL,
                    description="IBAN",
                    snippet="FR7612345678901234567890123",
                ),
            ],
            analysis_summary="Multiple items",
        )

        secure_data = anonymizer.anonymize(original_text, detection, encryption_key)
        revealed = anonymizer.reveal(secure_data, encryption_key)

        assert revealed == original_text

    def test_reveal_text_without_tokens(self, encryption_key):
        anonymizer = DataAnonymizer()
        text = "Bonjour, tout va bien."
        detection = SensitiveDataDetection.default()

        secure_data = anonymizer.anonymize(text, detection, encryption_key)
        revealed = anonymizer.reveal(secure_data, encryption_key)

        assert revealed == text

    def test_reveal_empty_text(self, encryption_key):
        anonymizer = DataAnonymizer()
        detection = SensitiveDataDetection.default()

        secure_data = anonymizer.anonymize("", detection, encryption_key)
        revealed = anonymizer.reveal(secure_data, encryption_key)

        assert revealed == ""

    def test_reveal_with_duplicate_snippets(self, encryption_key):
        anonymizer = DataAnonymizer()
        original_text = "Contact: test@mail.com et aussi test@mail.com"
        detection = SensitiveDataDetection(
            is_sensitive=True,
            confidence=0.9,
            detected_items=[
                SensitiveDataItem(
                    data_type=SensitiveDataType.PERSONAL,
                    description="Email",
                    snippet="test@mail.com",
                )
            ],
            analysis_summary="Email detected",
        )

        secure_data = anonymizer.anonymize(original_text, detection, encryption_key)
        revealed = anonymizer.reveal(secure_data, encryption_key)

        assert revealed == original_text

    def test_reveal_preserves_non_token_brackets(self, encryption_key):
        """Vérifie que reveal ne modifie pas les crochets normaux."""
        anonymizer = DataAnonymizer()
        text = "Array[0] et [note] avec email@test.com"
        detection = SensitiveDataDetection(
            is_sensitive=True,
            confidence=0.9,
            detected_items=[
                SensitiveDataItem(
                    data_type=SensitiveDataType.PERSONAL,
                    description="Email",
                    snippet="email@test.com",
                )
            ],
            analysis_summary="Email detected",
        )

        secure_data = anonymizer.anonymize(text, detection, encryption_key)
        revealed = anonymizer.reveal(secure_data, encryption_key)

        assert revealed == text
        assert "Array[0]" in revealed
        assert "[note]" in revealed

    def test_reveal_with_wrong_key_raises_error(self, encryption_key, wrong_key):
        """Vérifie que reveal avec une mauvaise clé lève une exception."""
        anonymizer = DataAnonymizer()
        text = "Email: test@example.com"
        detection = SensitiveDataDetection(
            is_sensitive=True,
            confidence=0.9,
            detected_items=[
                SensitiveDataItem(
                    data_type=SensitiveDataType.PERSONAL,
                    description="Email",
                    snippet="test@example.com",
                )
            ],
            analysis_summary="Email detected",
        )

        secure_data = anonymizer.anonymize(text, detection, encryption_key)

        with pytest.raises(InvalidCredentialsError, match="Invalid decryption key"):
            anonymizer.reveal(secure_data, wrong_key)

    def test_reveal_with_short_key_raises_error(self, encryption_key):
        """Vérifie que reveal avec une clé trop courte lève une exception."""
        anonymizer = DataAnonymizer()
        text = "Email: test@example.com"
        detection = SensitiveDataDetection(
            is_sensitive=True,
            confidence=0.9,
            detected_items=[
                SensitiveDataItem(
                    data_type=SensitiveDataType.PERSONAL,
                    description="Email",
                    snippet="test@example.com",
                )
            ],
            analysis_summary="Email detected",
        )

        secure_data = anonymizer.anonymize(text, detection, encryption_key)
        short_key = b"short"

        with pytest.raises(InvalidCredentialsError, match="32 bytes"):
            anonymizer.reveal(secure_data, short_key)


class TestAnonymizedToken:
    def test_token_placeholder_format(self):
        token = AnonymizedToken(
            token_id="abc12345",
            data_type=SensitiveDataType.PERSONAL,
        )

        assert token.placeholder == "[ANON:PERSONAL:abc12345]"

    def test_token_is_immutable(self):
        token = AnonymizedToken(
            token_id="abc12345",
            data_type=SensitiveDataType.FINANCIAL,
        )

        with pytest.raises(AttributeError):
            token.token_id = "new_id"

    def test_token_placeholder_for_all_types(self):
        """Vérifie le format placeholder pour tous les types de données."""
        types_and_expected = [
            (SensitiveDataType.PERSONAL, "[ANON:PERSONAL:testid01]"),
            (SensitiveDataType.FINANCIAL, "[ANON:FINANCIAL:testid01]"),
            (SensitiveDataType.CREDENTIAL, "[ANON:CREDENTIAL:testid01]"),
            (SensitiveDataType.COMMERCIAL_SECRET, "[ANON:COMMERCIAL:testid01]"),
        ]

        for data_type, expected_placeholder in types_and_expected:
            token = AnonymizedToken(
                token_id="testid01",
                data_type=data_type,
            )
            assert token.placeholder == expected_placeholder

    def test_token_equality(self):
        """Vérifie l'égalité entre tokens identiques (frozen dataclass)."""
        token1 = AnonymizedToken(
            token_id="abc12345",
            data_type=SensitiveDataType.PERSONAL,
        )
        token2 = AnonymizedToken(
            token_id="abc12345",
            data_type=SensitiveDataType.PERSONAL,
        )

        assert token1 == token2

    def test_token_hashable(self):
        """Vérifie que les tokens sont hashables (frozen=True)."""
        token = AnonymizedToken(
            token_id="abc12345",
            data_type=SensitiveDataType.PERSONAL,
        )

        # Si hashable, on peut l'ajouter dans un set
        token_set = {token}
        assert token in token_set


class TestAnonymizedResult:
    def test_result_is_immutable(self):
        result = AnonymizedResult(
            anonymized_text="test",
            tokens=(),
            original_text_hash="abc123",
        )

        with pytest.raises(AttributeError):
            result.anonymized_text = "modified"

    def test_create_factory_method(self):
        tokens = [
            AnonymizedToken(
                token_id="id1",
                data_type=SensitiveDataType.PERSONAL,
            )
        ]
        result = AnonymizedResult.create(
            anonymized_text="anonymized",
            tokens=tokens,
            original_text_hash="hash123",
        )

        assert result.anonymized_text == "anonymized"
        assert len(result.tokens) == 1
        assert result.original_text_hash == "hash123"

    def test_empty_factory_method(self):
        result = AnonymizedResult.empty(
            original_text="no sensitive data",
            original_text_hash="hash456",
        )

        assert result.anonymized_text == "no sensitive data"
        assert len(result.tokens) == 0
        assert result.original_text_hash == "hash456"

    def test_result_tokens_is_tuple(self):
        """Vérifie que tokens est un tuple immutable, pas une liste."""
        tokens = [
            AnonymizedToken(
                token_id="id1",
                data_type=SensitiveDataType.PERSONAL,
            )
        ]
        result = AnonymizedResult.create(
            anonymized_text="anonymized",
            tokens=tokens,
            original_text_hash="hash123",
        )

        assert isinstance(result.tokens, tuple)

    def test_result_hashable(self):
        """Vérifie que AnonymizedResult est hashable (frozen=True)."""
        result = AnonymizedResult(
            anonymized_text="test",
            tokens=(),
            original_text_hash="abc123",
        )

        # Si hashable, on peut l'ajouter dans un set
        result_set = {result}
        assert result in result_set

    def test_result_equality(self):
        """Vérifie l'égalité entre résultats identiques."""
        result1 = AnonymizedResult(
            anonymized_text="test",
            tokens=(),
            original_text_hash="abc123",
        )
        result2 = AnonymizedResult(
            anonymized_text="test",
            tokens=(),
            original_text_hash="abc123",
        )

        assert result1 == result2


class TestSecureAnonymizedData:
    def test_secure_data_is_immutable(self):
        result = AnonymizedResult(
            anonymized_text="test",
            tokens=(),
            original_text_hash="abc123",
        )
        secure_data = SecureAnonymizedData(
            result=result,
            secure_mappings=(),
            key_id="keyid123",
        )

        with pytest.raises(AttributeError):
            secure_data.key_id = "new_id"

    def test_create_factory_method(self):
        result = AnonymizedResult(
            anonymized_text="anonymized",
            tokens=(),
            original_text_hash="hash123",
        )
        mappings = [
            SecureTokenMapping(
                token_id="id1",
                encrypted_value=b"encrypted",
                salt=b"salt",
            )
        ]
        secure_data = SecureAnonymizedData.create(
            result=result,
            secure_mappings=mappings,
            key_id="keyid123",
        )

        assert secure_data.result == result
        assert len(secure_data.secure_mappings) == 1
        assert secure_data.key_id == "keyid123"


class TestSecureTokenMapping:
    def test_mapping_is_immutable(self):
        mapping = SecureTokenMapping(
            token_id="abc12345",
            encrypted_value=b"encrypted_data",
            salt=b"random_salt",
        )

        with pytest.raises(AttributeError):
            mapping.token_id = "new_id"

    def test_mapping_stores_bytes(self):
        mapping = SecureTokenMapping(
            token_id="abc12345",
            encrypted_value=b"encrypted_data",
            salt=b"random_salt",
        )

        assert isinstance(mapping.encrypted_value, bytes)
        assert isinstance(mapping.salt, bytes)


class TestGenerateEncryptionKey:
    def test_generates_32_bytes(self):
        key = generate_encryption_key()
        assert len(key) == 32

    def test_generates_unique_keys(self):
        keys = [generate_encryption_key() for _ in range(10)]
        assert len(set(keys)) == 10  # Tous uniques

    def test_key_is_bytes(self):
        key = generate_encryption_key()
        assert isinstance(key, bytes)
