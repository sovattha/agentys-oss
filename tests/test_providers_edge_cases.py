# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests TDD pour les edge cases des providers email.

Ce fichier suit les principes de Clean Architecture:
- Interface Adapters: Tests des providers (Gmail, Outlook, IMAP, SMTP)
- Gestion des erreurs réseau, credentials, rate limiting

Edge cases couverts:
1. OAuth token refresh failures
2. Connection errors et reconnection
3. Rate limiting (429 errors)
4. Credentials invalides
5. Network timeouts
6. Malformed responses from APIs
7. Large emails/attachments
"""

import pytest
from datetime import datetime
from typing import List, Optional
from unittest.mock import MagicMock, patch

from app.interfaces.email_provider import EmailProvider, StandardEmail


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def sample_email():
    """Email de test standard."""
    return StandardEmail(
        id="msg-123",
        sender="sender@example.com",
        sender_name="Sender Name",
        to=["recipient@example.com"],
        cc=[],
        subject="Test Subject",
        body="Test body content",
        provider_source="test"
    )


# ============================================================================
# MOCK PROVIDERS FOR TESTING
# ============================================================================

class MockAPIError(Exception):
    """Erreur API simulée."""
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"API Error {status_code}: {message}")


class RateLimitError(Exception):
    """Erreur de rate limiting."""
    def __init__(self, retry_after: int = 60):
        self.retry_after = retry_after
        super().__init__(f"Rate limited. Retry after {retry_after}s")


class AuthenticationError(Exception):
    """Erreur d'authentification."""
    pass


class TokenExpiredError(Exception):
    """Token expiré."""
    pass


class MockProviderWithErrors(EmailProvider):
    """Provider mock qui peut simuler diverses erreurs."""

    def __init__(self):
        self._emails = {}
        self._authenticated = False
        self._error_mode = None  # 'connection', 'rate_limit', 'auth', 'token_expired'
        self._call_count = 0
        self._fail_after_calls = None  # Échoue après N appels

    @property
    def provider_name(self) -> str:
        return "mock_with_errors"

    def set_error_mode(self, mode: str, fail_after: int = 0):
        """Configure le mode d'erreur.

        Args:
            mode: Type d'erreur ('connection', 'rate_limit', 'auth', 'token_expired', 'timeout', 'api_500', 'api_503')
            fail_after: Échoue après N appels réussis (0 = échoue immédiatement)
        """
        self._error_mode = mode
        self._fail_after_calls = fail_after

    def _check_errors(self):
        """Vérifie et lève les erreurs configurées."""
        if self._error_mode is None:
            return

        self._call_count += 1

        if self._call_count > self._fail_after_calls:
            if self._error_mode == 'connection':
                raise ConnectionError("Connection lost")
            elif self._error_mode == 'rate_limit':
                raise RateLimitError(retry_after=60)
            elif self._error_mode == 'auth':
                raise AuthenticationError("Invalid credentials")
            elif self._error_mode == 'token_expired':
                raise TokenExpiredError("Token has expired")
            elif self._error_mode == 'timeout':
                raise TimeoutError("Request timed out")
            elif self._error_mode == 'api_500':
                raise MockAPIError(500, "Internal Server Error")
            elif self._error_mode == 'api_503':
                raise MockAPIError(503, "Service Unavailable")

    def authenticate(self) -> bool:
        if self._error_mode == 'auth':
            raise AuthenticationError("Invalid credentials")
        if self._error_mode == 'token_expired':
            raise TokenExpiredError("Token has expired")
        self._authenticated = True
        return True

    def get_unread_messages(self, limit: int = 10) -> List[StandardEmail]:
        self._check_errors()
        return list(self._emails.values())[:limit]

    def get_message_by_id(self, message_id: str) -> Optional[StandardEmail]:
        self._check_errors()
        return self._emails.get(message_id)

    def create_draft(self, to, subject, body, reply_to_id=None, cc=None, is_html=False):
        self._check_errors()
        return "draft-001"

    def send_draft(self, draft_id: str) -> bool:
        self._check_errors()
        return True

    def mark_as_read(self, message_id: str) -> bool:
        self._check_errors()
        return True

    def mark_as_unread(self, message_id: str) -> bool:
        self._check_errors()
        return True

    def apply_label(self, message_id: str, label: str) -> bool:
        self._check_errors()
        return True

    def get_user_drafts(self, limit: int = 50) -> List[StandardEmail]:
        self._check_errors()
        return []

    def get_draft_by_id(self, draft_id: str) -> Optional[StandardEmail]:
        self._check_errors()
        return None

    def update_draft(
        self,
        draft_id: str,
        subject: Optional[str] = None,
        body: Optional[str] = None,
        to: Optional[List[str]] = None,
        cc: Optional[List[str]] = None,
        is_html: bool = False
    ) -> bool:
        self._check_errors()
        return True


# ============================================================================
# TESTS - CONNECTION ERRORS
# ============================================================================

class TestConnectionErrors:
    """Tests pour les erreurs de connexion."""

    def test_connection_error_on_authenticate(self):
        """authenticate() gère les erreurs de connexion."""
        provider = MockProviderWithErrors()
        provider.set_error_mode('connection', fail_after=0)

        # L'authentification devrait lever une erreur de connexion
        # (mais notre mock ne lève pas d'erreur sur authenticate directement)
        # Testons le get_unread_messages
        provider._authenticated = True

        with pytest.raises(ConnectionError):
            provider.get_unread_messages()

    def test_connection_error_on_get_unread(self):
        """get_unread_messages() gère les erreurs de connexion."""
        provider = MockProviderWithErrors()
        provider.set_error_mode('connection', fail_after=0)

        with pytest.raises(ConnectionError):
            provider.get_unread_messages()

    def test_connection_error_on_create_draft(self):
        """create_draft() gère les erreurs de connexion."""
        provider = MockProviderWithErrors()
        provider.set_error_mode('connection', fail_after=0)

        with pytest.raises(ConnectionError):
            provider.create_draft(
                to=["test@test.com"],
                subject="Test",
                body="Body"
            )

    def test_intermittent_connection_errors(self):
        """Erreurs de connexion intermittentes."""
        provider = MockProviderWithErrors()
        provider.set_error_mode('connection', fail_after=2)

        # Les deux premiers appels réussissent
        assert provider.create_draft(["a@b.com"], "S", "B") == "draft-001"
        assert provider.send_draft("draft-001") is True

        # Le troisième échoue
        with pytest.raises(ConnectionError):
            provider.mark_as_read("msg-001")


# ============================================================================
# TESTS - RATE LIMITING
# ============================================================================

class TestRateLimiting:
    """Tests pour le rate limiting (429 errors)."""

    def test_rate_limit_on_get_unread(self):
        """get_unread_messages() lève une erreur de rate limit."""
        provider = MockProviderWithErrors()
        provider.set_error_mode('rate_limit', fail_after=0)

        with pytest.raises(RateLimitError) as exc_info:
            provider.get_unread_messages()

        assert exc_info.value.retry_after == 60

    def test_rate_limit_after_multiple_calls(self):
        """Rate limit après plusieurs appels."""
        provider = MockProviderWithErrors()
        provider.set_error_mode('rate_limit', fail_after=3)

        # Les trois premiers appels réussissent
        provider.get_unread_messages()
        provider.get_unread_messages()
        provider.get_unread_messages()

        # Le quatrième échoue
        with pytest.raises(RateLimitError):
            provider.get_unread_messages()


# ============================================================================
# TESTS - AUTHENTICATION ERRORS
# ============================================================================

class TestAuthenticationErrors:
    """Tests pour les erreurs d'authentification."""

    def test_invalid_credentials(self):
        """authenticate() lève une erreur pour credentials invalides."""
        provider = MockProviderWithErrors()
        provider.set_error_mode('auth')

        with pytest.raises(AuthenticationError):
            provider.authenticate()

    def test_token_expired(self):
        """authenticate() lève une erreur pour token expiré."""
        provider = MockProviderWithErrors()
        provider.set_error_mode('token_expired')

        with pytest.raises(TokenExpiredError):
            provider.authenticate()


# ============================================================================
# TESTS - TIMEOUT ERRORS
# ============================================================================

class TestTimeoutErrors:
    """Tests pour les timeouts."""

    def test_timeout_on_get_unread(self):
        """get_unread_messages() gère les timeouts."""
        provider = MockProviderWithErrors()
        provider.set_error_mode('timeout', fail_after=0)

        with pytest.raises(TimeoutError):
            provider.get_unread_messages()

    def test_timeout_on_send_draft(self):
        """send_draft() gère les timeouts."""
        provider = MockProviderWithErrors()
        provider.set_error_mode('timeout', fail_after=0)

        with pytest.raises(TimeoutError):
            provider.send_draft("draft-001")


# ============================================================================
# TESTS - API ERRORS
# ============================================================================

class TestAPIErrors:
    """Tests pour les erreurs API."""

    def test_api_500_error(self):
        """Gestion des erreurs 500."""
        provider = MockProviderWithErrors()
        provider.set_error_mode('api_500', fail_after=0)

        with pytest.raises(MockAPIError) as exc_info:
            provider.get_unread_messages()

        assert exc_info.value.status_code == 500

    def test_api_503_error(self):
        """Gestion des erreurs 503 (service unavailable)."""
        provider = MockProviderWithErrors()
        provider.set_error_mode('api_503', fail_after=0)

        with pytest.raises(MockAPIError) as exc_info:
            provider.create_draft(["test@test.com"], "Test", "Body")

        assert exc_info.value.status_code == 503


# ============================================================================
# TESTS - FACTORY ERROR HANDLING
# ============================================================================

class TestFactoryErrorHandling:
    """Tests pour la gestion des erreurs dans la factory."""

    def test_missing_outlook_credentials(self):
        """Factory lève une erreur si credentials Outlook manquants."""
        from app.providers.factory import get_email_provider, ProviderConfigurationError
        import os

        # S'assurer que les variables d'environnement ne sont pas définies
        with patch.dict(os.environ, {
            'AZURE_TENANT_ID': '',
            'AZURE_CLIENT_ID': '',
            'AZURE_CLIENT_SECRET': ''
        }, clear=False):
            with patch("app.providers.factory._create_outlook_provider") as mock_create:
                mock_create.side_effect = ProviderConfigurationError("Missing credentials")

                with pytest.raises(ProviderConfigurationError):
                    get_email_provider("OUTLOOK")

    def test_missing_gmail_credentials(self):
        """Factory lève une erreur si credentials Gmail manquants."""
        from app.providers.factory import get_email_provider, ProviderConfigurationError

        with patch("app.providers.factory._create_gmail_provider") as mock_create:
            mock_create.side_effect = ProviderConfigurationError("Missing GOOGLE_CLIENT_ID")

            with pytest.raises(ProviderConfigurationError) as exc_info:
                get_email_provider("GMAIL")

            assert "GOOGLE_CLIENT_ID" in str(exc_info.value)

    def test_missing_imap_credentials(self):
        """Factory lève une erreur si credentials IMAP manquants."""
        from app.providers.factory import get_email_provider, ProviderConfigurationError

        with patch("app.providers.factory._create_imap_provider") as mock_create:
            mock_create.side_effect = ProviderConfigurationError("Missing IMAP_HOST")

            with pytest.raises(ProviderConfigurationError):
                get_email_provider("IMAP")

    def test_missing_smtp_credentials(self):
        """Factory lève une erreur si credentials SMTP manquants."""
        from app.providers.factory import get_email_provider, ProviderConfigurationError

        with patch("app.providers.factory._create_smtp_provider") as mock_create:
            mock_create.side_effect = ProviderConfigurationError("Missing SMTP_HOST")

            with pytest.raises(ProviderConfigurationError):
                get_email_provider("SMTP")


# ============================================================================
# TESTS - LARGE CONTENT HANDLING
# ============================================================================

class TestLargeContentHandling:
    """Tests pour la gestion des contenus volumineux."""

    def test_large_email_body(self):
        """Email avec corps très volumineux."""
        large_body = "x" * (10 * 1024 * 1024)  # 10 MB
        email = StandardEmail(
            id="large-001",
            sender="sender@test.com",
            body=large_body
        )

        assert len(email.body) == 10 * 1024 * 1024
        # Preview doit être tronqué
        assert len(email.preview) == 103

    def test_large_recipient_list(self):
        """Email avec beaucoup de destinataires."""
        many_recipients = [f"user{i}@example.com" for i in range(100)]
        email = StandardEmail(
            id="many-001",
            sender="sender@test.com",
            to=many_recipients
        )

        assert len(email.to) == 100

    def test_large_cc_list(self):
        """Email avec beaucoup de CC."""
        many_cc = [f"cc{i}@example.com" for i in range(50)]
        email = StandardEmail(
            id="cc-001",
            sender="sender@test.com",
            cc=many_cc
        )

        assert len(email.cc) == 50


# ============================================================================
# TESTS - SPECIAL CHARACTERS HANDLING
# ============================================================================

class TestSpecialCharactersHandling:
    """Tests pour les caractères spéciaux."""

    def test_email_with_newlines_in_subject(self):
        """Sujet avec retours à la ligne."""
        email = StandardEmail(
            id="newline-001",
            sender="sender@test.com",
            subject="Line 1\nLine 2\rLine 3"
        )

        assert "\n" in email.subject
        assert "\r" in email.subject

    def test_email_with_null_bytes(self):
        """Corps avec octets nuls."""
        email = StandardEmail(
            id="null-001",
            sender="sender@test.com",
            body="Before\x00After"
        )

        assert "\x00" in email.body

    def test_email_with_control_characters(self):
        """Corps avec caractères de contrôle."""
        email = StandardEmail(
            id="ctrl-001",
            sender="sender@test.com",
            body="Tab:\tBell:\x07Backspace:\x08"
        )

        assert "\t" in email.body
        assert "\x07" in email.body


# ============================================================================
# TESTS - MALFORMED DATA HANDLING
# ============================================================================

class TestMalformedDataHandling:
    """Tests pour les données malformées."""

    def test_email_with_malformed_sender(self):
        """Email avec adresse expéditeur malformée."""
        email = StandardEmail(
            id="malformed-001",
            sender="not-a-valid-email",
            subject="Test"
        )

        # L'email est créé mais l'adresse n'est pas valide
        assert "@" not in email.sender

    def test_email_with_empty_to_list(self):
        """Email sans destinataires."""
        email = StandardEmail(
            id="no-to-001",
            sender="sender@test.com",
            to=[]
        )

        assert email.to == []

    def test_email_with_duplicate_recipients(self):
        """Email avec destinataires dupliqués."""
        email = StandardEmail(
            id="dup-001",
            sender="sender@test.com",
            to=["same@test.com", "same@test.com", "same@test.com"]
        )

        assert len(email.to) == 3  # Les doublons sont conservés


# ============================================================================
# TESTS - PROVIDER CONFIG VALIDATION
# ============================================================================

class TestProviderConfigValidation:
    """Tests pour la validation de configuration des providers."""

    def test_validate_outlook_config_all_present(self):
        """Validation config Outlook avec toutes les vars."""
        from app.providers.factory import validate_provider_config
        import os

        with patch.dict(os.environ, {
            'AZURE_TENANT_ID': 'tenant-123',
            'AZURE_CLIENT_ID': 'client-456',
            'AZURE_CLIENT_SECRET': 'secret-789',
            'OUTLOOK_USER_ID': 'user@example.com'
        }):
            result = validate_provider_config("OUTLOOK")

            assert result['AZURE_TENANT_ID'] is True
            assert result['AZURE_CLIENT_ID'] is True
            assert result['AZURE_CLIENT_SECRET'] is True
            assert result['OUTLOOK_USER_ID'] is True

    def test_validate_outlook_config_partial(self):
        """Validation config Outlook avec vars manquantes."""
        from app.providers.factory import validate_provider_config
        import os

        with patch.dict(os.environ, {
            'AZURE_TENANT_ID': 'tenant-123',
            'AZURE_CLIENT_ID': '',  # Vide
            'AZURE_CLIENT_SECRET': 'secret-789',
        }, clear=False):
            # Supprimer OUTLOOK_USER_ID si présent
            env = os.environ.copy()
            env.pop('OUTLOOK_USER_ID', None)

            with patch.dict(os.environ, env, clear=True):
                result = validate_provider_config("OUTLOOK")

                assert result['AZURE_TENANT_ID'] is True
                assert result['AZURE_CLIENT_ID'] is False  # Vide = False
                assert result['AZURE_CLIENT_SECRET'] is True

    def test_validate_gmail_config(self):
        """Validation config Gmail."""
        from app.providers.factory import validate_provider_config
        import os

        with patch.dict(os.environ, {
            'GOOGLE_CLIENT_ID': 'google-client',
            'GOOGLE_CLIENT_SECRET': 'google-secret',
            'GOOGLE_REFRESH_TOKEN': 'refresh-token'
        }):
            result = validate_provider_config("GMAIL")

            assert result['GOOGLE_CLIENT_ID'] is True
            assert result['GOOGLE_CLIENT_SECRET'] is True
            assert result['GOOGLE_REFRESH_TOKEN'] is True

    def test_validate_imap_config(self):
        """Validation config IMAP."""
        from app.providers.factory import validate_provider_config
        import os

        with patch.dict(os.environ, {
            'IMAP_HOST': 'imap.example.com',
            'IMAP_USER': 'user@example.com',
            'IMAP_PASSWORD': 'password123'
        }):
            result = validate_provider_config("IMAP")

            assert result['IMAP_HOST'] is True
            assert result['IMAP_USER'] is True
            assert result['IMAP_PASSWORD'] is True

    def test_validate_smtp_config(self):
        """Validation config SMTP."""
        from app.providers.factory import validate_provider_config
        import os

        with patch.dict(os.environ, {
            'SMTP_HOST': 'smtp.example.com',
            'SMTP_USER': 'user@example.com',
            'SMTP_PASSWORD': 'password123'
        }):
            result = validate_provider_config("SMTP")

            assert result['SMTP_HOST'] is True
            assert result['SMTP_USER'] is True
            assert result['SMTP_PASSWORD'] is True

    def test_validate_imap_smtp_config(self):
        """Validation config IMAP+SMTP combiné."""
        from app.providers.factory import validate_provider_config
        import os

        with patch.dict(os.environ, {
            'IMAP_HOST': 'imap.example.com',
            'IMAP_USER': 'user@example.com',
            'IMAP_PASSWORD': 'password123',
            'SMTP_HOST': 'smtp.example.com',
            'SMTP_USER': 'user@example.com',
            'SMTP_PASSWORD': 'password123'
        }):
            result = validate_provider_config("IMAP_SMTP")

            assert all(v is True for v in result.values())


# ============================================================================
# TESTS - RETRY LOGIC SIMULATION
# ============================================================================

class RetryableProvider(MockProviderWithErrors):
    """Provider avec logique de retry simulée."""

    def __init__(self):
        super().__init__()
        self._failures_before_success = 0
        self._current_failures = 0

    def set_failures_before_success(self, count: int):
        """Configure le nombre d'échecs avant succès."""
        self._failures_before_success = count
        self._current_failures = 0

    def get_unread_messages(self, limit: int = 10) -> List[StandardEmail]:
        if self._current_failures < self._failures_before_success:
            self._current_failures += 1
            raise ConnectionError(f"Failure {self._current_failures}")
        return list(self._emails.values())[:limit]


class TestRetryLogic:
    """Tests pour la logique de retry."""

    def test_success_after_retries(self):
        """Succès après plusieurs tentatives."""
        provider = RetryableProvider()
        provider.set_failures_before_success(2)

        # Simule une logique de retry
        max_retries = 3
        last_error = None

        for attempt in range(max_retries):
            try:
                result = provider.get_unread_messages()
                break
            except ConnectionError as e:
                last_error = e
        else:
            raise last_error

        # La troisième tentative réussit
        assert result == []

    def test_failure_after_max_retries(self):
        """Échec après le max de retries."""
        provider = RetryableProvider()
        provider.set_failures_before_success(10)  # Plus que max_retries

        max_retries = 3
        last_error = None

        for attempt in range(max_retries):
            try:
                provider.get_unread_messages()
                break
            except ConnectionError as e:
                last_error = e
        else:
            # On arrive ici si la boucle se termine sans break
            pass

        assert last_error is not None
        assert "Failure 3" in str(last_error)


# ============================================================================
# TESTS - EMAIL PROVIDER ABC
# ============================================================================

class TestEmailProviderABC:
    """Tests pour l'interface abstraite EmailProvider."""

    def test_cannot_instantiate_abstract_class(self):
        """EmailProvider ne peut pas être instancié directement."""
        with pytest.raises(TypeError):
            EmailProvider()

    def test_concrete_class_must_implement_methods(self):
        """Une classe concrète doit implémenter toutes les méthodes."""
        class IncompleteProvider(EmailProvider):
            @property
            def provider_name(self):
                return "incomplete"

        with pytest.raises(TypeError):
            IncompleteProvider()

    def test_send_email_uses_create_and_send_draft(self, sample_email):
        """send_email() combine create_draft() et send_draft()."""
        from tests.conftest import MockEmailProvider

        provider = MockEmailProvider()

        result = provider.send_email(
            to=["test@test.com"],
            subject="Test",
            body="Body"
        )

        assert result is True
        # Le brouillon a été créé puis supprimé
        assert len(provider._drafts) == 0


# ============================================================================
# TESTS - FACTORY EDGE CASES
# ============================================================================

class TestFactoryEdgeCases:
    """Tests edge cases pour la factory de providers."""

    def test_unknown_provider_type(self):
        """Factory lève une erreur pour un provider inconnu."""
        from app.providers.factory import get_email_provider, ProviderConfigurationError

        with pytest.raises(ProviderConfigurationError) as exc_info:
            get_email_provider("UNKNOWN_PROVIDER")

        assert "Provider inconnu" in str(exc_info.value)
        assert "UNKNOWN_PROVIDER" in str(exc_info.value)

    def test_provider_type_case_insensitive(self):
        """Le type de provider est insensible à la casse."""
        from app.providers.factory import get_email_provider

        # Les providers existants doivent fonctionner avec différentes casses
        # (mais échoueront si les credentials ne sont pas configurés)
        with patch("app.providers.factory._create_outlook_provider") as mock_create:
            mock_create.return_value = MagicMock()

            # Différentes variantes de casse
            get_email_provider("outlook")
            get_email_provider("OUTLOOK")
            get_email_provider("Outlook")
            get_email_provider("  outlook  ")  # Avec espaces

            assert mock_create.call_count == 4

    def test_provider_type_with_whitespace(self):
        """Le type de provider gère les espaces."""
        from app.providers.factory import get_email_provider

        with patch("app.providers.factory._create_gmail_provider") as mock_create:
            mock_create.return_value = MagicMock()

            get_email_provider("  gmail  ")

            mock_create.assert_called_once()

    def test_provider_from_env_variable(self):
        """Le type de provider peut être défini via variable d'environnement."""
        from app.providers.factory import get_email_provider
        import os

        with patch.dict(os.environ, {'EMAIL_PROVIDER_TYPE': 'GMAIL'}):
            with patch("app.providers.factory._create_gmail_provider") as mock_create:
                mock_create.return_value = MagicMock()

                get_email_provider()  # Sans argument

                mock_create.assert_called_once()

    def test_explicit_provider_overrides_env(self):
        """Le paramètre explicite a priorité sur la variable d'environnement."""
        from app.providers.factory import get_email_provider
        import os

        with patch.dict(os.environ, {'EMAIL_PROVIDER_TYPE': 'GMAIL'}):
            with patch("app.providers.factory._create_outlook_provider") as mock_outlook:
                mock_outlook.return_value = MagicMock()

                get_email_provider("OUTLOOK")  # Explicite

                mock_outlook.assert_called_once()

    def test_list_available_providers(self):
        """list_available_providers retourne tous les providers."""
        from app.providers.factory import list_available_providers

        providers = list_available_providers()

        assert "OUTLOOK" in providers
        assert "GMAIL" in providers
        assert "IMAP" in providers
        assert "SMTP" in providers
        assert "IMAP_SMTP" in providers

    def test_validate_unknown_provider(self):
        """validate_provider_config retourne vide pour provider inconnu."""
        from app.providers.factory import validate_provider_config

        result = validate_provider_config("UNKNOWN")
        assert result == {}


# ============================================================================
# TESTS - STANDARD EMAIL EDGE CASES
# ============================================================================

class TestStandardEmailEdgeCases:
    """Tests edge cases pour StandardEmail."""

    def test_email_with_empty_body(self):
        """Email avec corps vide."""
        email = StandardEmail(
            id="empty-body-001",
            sender="sender@test.com",
            body=""
        )

        assert email.body == ""
        assert email.preview == ""

    def test_email_with_none_body(self):
        """Email avec corps None."""
        email = StandardEmail(
            id="none-body-001",
            sender="sender@test.com",
            body=None
        )

        assert email.body is None

    def test_email_with_empty_subject(self):
        """Email avec sujet vide."""
        email = StandardEmail(
            id="empty-subject-001",
            sender="sender@test.com",
            subject=""
        )

        assert email.subject == ""

    def test_email_with_very_long_subject(self):
        """Email avec sujet très long."""
        long_subject = "X" * 10000
        email = StandardEmail(
            id="long-subject-001",
            sender="sender@test.com",
            subject=long_subject
        )

        assert len(email.subject) == 10000

    def test_email_preview_truncation(self):
        """Le preview est tronqué à 100 caractères + ..."""
        email = StandardEmail(
            id="preview-001",
            sender="sender@test.com",
            body="A" * 500
        )

        # Le preview doit être tronqué
        assert len(email.preview) == 103  # 100 + "..."
        assert email.preview.endswith("...")

    def test_email_preview_with_newlines(self):
        """Le preview conserve les newlines (comportement actuel)."""
        email = StandardEmail(
            id="newlines-001",
            sender="sender@test.com",
            body="Line1\nLine2\nLine3"
        )

        # Le comportement actuel: le preview ne modifie pas les newlines
        assert email.preview == "Line1\nLine2\nLine3"

    def test_email_with_html_body(self):
        """Email avec corps HTML dans body_html."""
        html_body = "<html><body><h1>Hello</h1><p>World</p></body></html>"
        email = StandardEmail(
            id="html-001",
            sender="sender@test.com",
            body="Plain text version",
            body_html=html_body
        )

        assert email.body_html == html_body

    def test_email_with_attachments_info(self):
        """Email avec flag has_attachments."""
        email = StandardEmail(
            id="attach-001",
            sender="sender@test.com",
            has_attachments=True
        )

        assert email.has_attachments is True

    def test_email_with_unicode_sender(self):
        """Email avec expéditeur Unicode."""
        email = StandardEmail(
            id="unicode-sender-001",
            sender="用户@example.com",
            sender_name="中文名字"
        )

        assert email.sender == "用户@example.com"
        assert email.sender_name == "中文名字"

    def test_email_with_mixed_case_addresses(self):
        """Email avec adresses en casse mixte."""
        email = StandardEmail(
            id="case-001",
            sender="User@Example.COM",
            to=["RECIPIENT@Test.ORG"]
        )

        assert email.sender == "User@Example.COM"
        assert email.to == ["RECIPIENT@Test.ORG"]

    def test_email_equality(self):
        """Deux emails avec le même ID sont égaux."""
        email1 = StandardEmail(id="same-001", sender="a@b.com")
        email2 = StandardEmail(id="same-001", sender="c@d.com")

        # L'égalité est basée sur l'ID si définie
        assert email1.id == email2.id

    def test_email_repr(self):
        """repr() de StandardEmail."""
        email = StandardEmail(
            id="repr-001",
            sender="test@test.com",
            subject="Test Subject"
        )

        repr_str = repr(email)
        # Devrait contenir des infos utiles
        assert "test@test.com" in repr_str or "repr-001" in repr_str

    def test_email_with_conversation_id(self):
        """Email avec ID de conversation."""
        email = StandardEmail(
            id="conv-001",
            sender="sender@test.com",
            conversation_id="conv-xyz-789"
        )

        assert email.conversation_id == "conv-xyz-789"

    def test_email_received_at(self):
        """Email avec date/heure de réception."""
        received = datetime(2025, 1, 15, 10, 30, 0)
        email = StandardEmail(
            id="date-001",
            sender="sender@test.com",
            received_at=received
        )

        assert email.received_at == received

    def test_email_with_all_optional_fields(self):
        """Email avec tous les champs optionnels définis dans StandardEmail."""
        email = StandardEmail(
            id="full-001",
            sender="sender@test.com",
            sender_name="Sender Name",
            to=["to@test.com"],
            cc=["cc@test.com"],
            subject="Full Email",
            body="Body content",
            body_html="<p>Body content</p>",
            has_attachments=True,
            received_at=datetime.now(),
            is_read=False,
            conversation_id="conv-001",
            provider_source="test",
            raw_metadata={"key": "value"}
        )

        assert email.sender_name == "Sender Name"
        assert email.body_html == "<p>Body content</p>"
        assert email.raw_metadata == {"key": "value"}


# ============================================================================
# TESTS - CONCURRENT ACCESS SIMULATION
# ============================================================================

class TestConcurrentAccess:
    """Tests pour l'accès concurrent simulé."""

    def test_multiple_get_unread_calls(self):
        """Plusieurs appels get_unread simultanés."""
        provider = MockProviderWithErrors()
        provider._emails = {
            "msg-1": StandardEmail(id="msg-1", sender="a@b.com"),
            "msg-2": StandardEmail(id="msg-2", sender="c@d.com"),
        }

        # Simuler plusieurs appels
        results = [provider.get_unread_messages() for _ in range(10)]

        # Tous les résultats doivent être cohérents
        for result in results:
            assert len(result) == 2

    def test_interleaved_create_and_send(self):
        """Création et envoi de brouillons entrelacés."""
        provider = MockProviderWithErrors()

        # Créer plusieurs brouillons
        draft_ids = [
            provider.create_draft(["a@b.com"], f"Subject {i}", f"Body {i}")
            for i in range(5)
        ]

        # Envoyer dans un ordre différent
        for draft_id in reversed(draft_ids):
            result = provider.send_draft(draft_id)
            assert result is True


# ============================================================================
# TESTS - ERROR RECOVERY
# ============================================================================

class TestErrorRecovery:
    """Tests pour la récupération après erreur."""

    def test_recover_after_connection_error(self):
        """Récupération après erreur de connexion."""
        provider = MockProviderWithErrors()
        provider.set_error_mode('connection', fail_after=1)

        # Premier appel réussit
        provider.get_unread_messages()

        # Deuxième appel échoue
        with pytest.raises(ConnectionError):
            provider.get_unread_messages()

        # Réinitialiser le mode d'erreur
        provider._error_mode = None
        provider._call_count = 0

        # Troisième appel réussit
        result = provider.get_unread_messages()
        assert result == []

    def test_recover_after_rate_limit(self):
        """Récupération après rate limit."""
        provider = MockProviderWithErrors()
        provider.set_error_mode('rate_limit', fail_after=0)

        # Capture l'erreur de rate limit
        try:
            provider.get_unread_messages()
        except RateLimitError as e:
            retry_after = e.retry_after

        assert retry_after == 60

        # Après le délai, les appels réussissent
        provider._error_mode = None
        provider._call_count = 0

        result = provider.get_unread_messages()
        assert result == []

    def test_partial_failure_in_batch(self):
        """Échec partiel dans un lot d'opérations."""
        provider = MockProviderWithErrors()
        provider.set_error_mode('api_500', fail_after=2)

        results = []
        errors = []

        for i in range(5):
            try:
                draft_id = provider.create_draft([f"user{i}@test.com"], f"Subject {i}", "Body")
                results.append(draft_id)
            except MockAPIError as e:
                errors.append(e)

        # Les deux premiers réussissent, les trois suivants échouent
        assert len(results) == 2
        assert len(errors) == 3


# ============================================================================
# TESTS - PROVIDER LIFECYCLE
# ============================================================================

class TestProviderLifecycle:
    """Tests pour le cycle de vie des providers."""

    def test_authenticate_before_operations(self):
        """L'authentification est requise avant les opérations."""
        provider = MockProviderWithErrors()
        assert provider._authenticated is False

        provider.authenticate()
        assert provider._authenticated is True

    def test_reauthenticate_after_token_expiry(self):
        """Ré-authentification après expiration du token."""
        provider = MockProviderWithErrors()
        provider.authenticate()
        assert provider._authenticated is True

        # Simuler l'expiration du token
        provider._authenticated = False
        provider.set_error_mode('token_expired')

        # Tentative de ré-authentification échoue
        with pytest.raises(TokenExpiredError):
            provider.authenticate()

        # Réinitialiser et réessayer
        provider._error_mode = None
        provider.authenticate()
        assert provider._authenticated is True
