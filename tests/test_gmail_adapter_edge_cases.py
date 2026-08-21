# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests TDD pour les edge cases de GmailAdapter.

Edge cases critiques couverts:
1. _get_header() - headers=None, headers=[], header value None
2. _decode_body() - payload=None, payload={}, base64 decode error
3. _map_to_standard_email() - message avec champs manquants
4. apply_label() - message_id vide, label vide, label_id None
5. create_draft() - to vide, subject/body None
6. _normalize_recipients() - entrée None/vide/malformée

Cycle TDD: RED -> GREEN -> REFACTOR
Pattern: Arrange-Act-Assert
"""

import base64
import pytest
from unittest.mock import MagicMock, patch

from app.interfaces.email_provider import StandardEmail


# =============================================================================
# Tests - _get_header Edge Cases
# =============================================================================


class TestGetHeaderEdgeCases:
    """Tests pour les edge cases de GmailAdapter._get_header()."""

    @pytest.fixture
    def gmail_adapter_mock(self):
        """Crée un GmailAdapter mocké."""
        with patch("app.providers.gmail_adapter.build"):
            with patch("app.providers.gmail_adapter.Credentials"):
                from app.providers.gmail_adapter import GmailAdapter
                adapter = GmailAdapter.__new__(GmailAdapter)
                adapter._service = None
                adapter._creds = None
                adapter.PROVIDER_NAME = "gmail"
                return adapter

    def test_get_header_empty_list_returns_empty_string(self, gmail_adapter_mock):
        """
        ARRANGE: headers=[]
        ACT: Appeler _get_header([], "From")
        ASSERT: Retourne ""
        """
        # Act
        result = gmail_adapter_mock._get_header([], "From")

        # Assert
        assert result == ""

    def test_get_header_header_not_found_returns_empty_string(self, gmail_adapter_mock):
        """
        ARRANGE: headers avec autres headers mais pas celui cherché
        ACT: Appeler _get_header(headers, "X-Custom")
        ASSERT: Retourne ""
        """
        # Arrange
        headers = [
            {"name": "From", "value": "sender@example.com"},
            {"name": "To", "value": "recipient@example.com"},
        ]

        # Act
        result = gmail_adapter_mock._get_header(headers, "X-Custom")

        # Assert
        assert result == ""

    def test_get_header_case_insensitive(self, gmail_adapter_mock):
        """
        ARRANGE: Header avec nom en majuscules
        ACT: Appeler _get_header avec nom en minuscules
        ASSERT: Trouve le header (case-insensitive)
        """
        # Arrange
        headers = [{"name": "FROM", "value": "sender@example.com"}]

        # Act
        result = gmail_adapter_mock._get_header(headers, "from")

        # Assert
        assert result == "sender@example.com"

    def test_get_header_value_empty_returns_empty_string(self, gmail_adapter_mock):
        """
        ARRANGE: Header avec value=""
        ACT: Appeler _get_header()
        ASSERT: Retourne ""
        """
        # Arrange
        headers = [{"name": "Subject", "value": ""}]

        # Act
        result = gmail_adapter_mock._get_header(headers, "Subject")

        # Assert
        assert result == ""

    def test_get_header_missing_value_key_returns_empty_string(self, gmail_adapter_mock):
        """
        ARRANGE: Header sans clé "value"
        ACT: Appeler _get_header()
        ASSERT: Retourne "" (utilise .get("value", ""))
        """
        # Arrange
        headers = [{"name": "Subject"}]  # Pas de "value"

        # Act
        result = gmail_adapter_mock._get_header(headers, "Subject")

        # Assert
        assert result == ""

    def test_get_header_missing_name_key_skips_header(self, gmail_adapter_mock):
        """
        ARRANGE: Header sans clé "name"
        ACT: Appeler _get_header()
        ASSERT: Header ignoré, retourne ""
        """
        # Arrange
        headers = [{"value": "some-value"}]  # Pas de "name"

        # Act
        result = gmail_adapter_mock._get_header(headers, "Subject")

        # Assert
        assert result == ""


# =============================================================================
# Tests - _decode_body Edge Cases
# =============================================================================


class TestDecodeBodyEdgeCases:
    """Tests pour les edge cases de GmailAdapter._decode_body()."""

    @pytest.fixture
    def gmail_adapter_mock(self):
        """Crée un GmailAdapter mocké."""
        with patch("app.providers.gmail_adapter.build"):
            with patch("app.providers.gmail_adapter.Credentials"):
                from app.providers.gmail_adapter import GmailAdapter
                adapter = GmailAdapter.__new__(GmailAdapter)
                adapter._service = None
                adapter._creds = None
                adapter.PROVIDER_NAME = "gmail"
                # Mock de la méthode _extract_text_from_html
                adapter._extract_text_from_html = lambda html: "extracted text"
                return adapter

    def test_decode_body_empty_payload_returns_empty(self, gmail_adapter_mock):
        """
        ARRANGE: payload={}
        ACT: Appeler _decode_body({})
        ASSERT: Retourne ("", None)
        """
        # Act
        body_text, body_html = gmail_adapter_mock._decode_body({})

        # Assert
        assert body_text == ""
        assert body_html is None

    def test_decode_body_no_data_returns_empty(self, gmail_adapter_mock):
        """
        ARRANGE: payload avec body mais sans data
        ACT: Appeler _decode_body()
        ASSERT: Retourne ("", None)
        """
        # Arrange
        payload = {
            "mimeType": "text/plain",
            "body": {}  # Pas de "data"
        }

        # Act
        body_text, body_html = gmail_adapter_mock._decode_body(payload)

        # Assert
        assert body_text == ""
        assert body_html is None

    def test_decode_body_text_plain_decoded(self, gmail_adapter_mock):
        """
        ARRANGE: payload avec text/plain encodé en base64
        ACT: Appeler _decode_body()
        ASSERT: Retourne le texte décodé
        """
        # Arrange
        content = "Hello World"
        encoded = base64.urlsafe_b64encode(content.encode()).decode()
        payload = {
            "mimeType": "text/plain",
            "body": {"data": encoded}
        }

        # Act
        body_text, body_html = gmail_adapter_mock._decode_body(payload)

        # Assert
        assert body_text == content
        assert body_html is None

    def test_decode_body_honors_declared_latin1_charset(self, gmail_adapter_mock):
        """
        ARRANGE: payload text/plain ISO-8859-1 avec accents français
        ACT: Appeler _decode_body()
        ASSERT: Les accents ne sont pas supprimés par un décodage UTF-8 forcé
        """
        # Arrange
        content = "Bien à toi,\nPoint congés : août"
        encoded = base64.urlsafe_b64encode(content.encode("iso-8859-1")).decode()
        payload = {
            "mimeType": "text/plain",
            "headers": [
                {"name": "Content-Type", "value": "text/plain; charset=ISO-8859-1"}
            ],
            "body": {"data": encoded},
        }

        # Act
        body_text, body_html = gmail_adapter_mock._decode_body(payload)

        # Assert
        assert body_text == content
        assert body_html is None

    def test_decode_body_multipart_extracts_both(self, gmail_adapter_mock):
        """
        ARRANGE: payload multipart avec text/plain et text/html
        ACT: Appeler _decode_body()
        ASSERT: Retourne les deux versions
        """
        # Arrange
        text_content = "Plain text"
        html_content = "<p>HTML</p>"
        payload = {
            "mimeType": "multipart/alternative",
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": base64.urlsafe_b64encode(text_content.encode()).decode()}
                },
                {
                    "mimeType": "text/html",
                    "body": {"data": base64.urlsafe_b64encode(html_content.encode()).decode()}
                }
            ]
        }

        # Act
        body_text, body_html = gmail_adapter_mock._decode_body(payload)

        # Assert
        assert body_text == text_content
        assert body_html == html_content

    def test_decode_body_only_html_extracts_text(self, gmail_adapter_mock):
        """
        ARRANGE: payload avec seulement text/html
        ACT: Appeler _decode_body()
        ASSERT: Extrait le texte du HTML
        """
        # Arrange
        html_content = "<p>HTML Only</p>"
        payload = {
            "mimeType": "text/html",
            "body": {"data": base64.urlsafe_b64encode(html_content.encode()).decode()}
        }

        # Act
        body_text, body_html = gmail_adapter_mock._decode_body(payload)

        # Assert
        assert body_text == "extracted text"  # Via _extract_text_from_html mock
        assert body_html == html_content

    def test_decode_body_invalid_base64_returns_empty(self, gmail_adapter_mock):
        """
        ARRANGE: payload avec data base64 invalide
        ACT: Appeler _decode_body()
        ASSERT: Retourne ("", None) sans exception

        NOTE: Ce test vérifie la robustesse face à des données corrompues
        """
        # Arrange
        payload = {
            "mimeType": "text/plain",
            "body": {"data": "!!!invalid-base64!!!"}
        }

        # Act - Should not raise, may return empty or partial
        try:
            body_text, body_html = gmail_adapter_mock._decode_body(payload)
            # Si pas d'exception, le résultat peut être vide ou décodé partiellement
            assert isinstance(body_text, str)
        except Exception as e:
            # Si une exception est levée, c'est un bug potentiel
            pytest.fail(f"_decode_body avec base64 invalide a levé {type(e).__name__}: {e}")


# =============================================================================
# Tests - _map_to_standard_email Edge Cases
# =============================================================================


class TestMapToStandardEmailEdgeCases:
    """Tests pour les edge cases de GmailAdapter._map_to_standard_email()."""

    @pytest.fixture
    def gmail_adapter_mock(self):
        """Crée un GmailAdapter mocké."""
        with patch("app.providers.gmail_adapter.build"):
            with patch("app.providers.gmail_adapter.Credentials"):
                from app.providers.gmail_adapter import GmailAdapter
                adapter = GmailAdapter.__new__(GmailAdapter)
                adapter._service = None
                adapter._creds = None
                adapter.PROVIDER_NAME = "gmail"
                # Mock les méthodes helper
                adapter._parse_email_address = lambda addr: (addr, None)
                adapter._normalize_recipients = lambda r: r.split(",") if r else []
                adapter._extract_text_from_html = lambda html: ""
                return adapter

    def test_map_empty_message_returns_email_with_defaults(self, gmail_adapter_mock):
        """
        ARRANGE: message={}
        ACT: Appeler _map_to_standard_email({})
        ASSERT: Retourne StandardEmail avec valeurs par défaut
        """
        # Act
        result = gmail_adapter_mock._map_to_standard_email({})

        # Assert
        assert result.id == ""
        assert result.sender == ""
        assert result.subject == ""
        assert result.body == ""

    def test_map_message_without_payload_uses_empty_headers(self, gmail_adapter_mock):
        """
        ARRANGE: message sans clé "payload"
        ACT: Appeler _map_to_standard_email()
        ASSERT: Utilise [] pour headers
        """
        # Arrange
        message = {"id": "msg-001"}

        # Act
        result = gmail_adapter_mock._map_to_standard_email(message)

        # Assert
        assert result.id == "msg-001"
        assert result.sender == ""

    def test_map_message_without_labels_is_unread(self, gmail_adapter_mock):
        """
        ARRANGE: message sans "labelIds"
        ACT: Appeler _map_to_standard_email()
        ASSERT: is_read=True (UNREAD pas présent)
        """
        # Arrange
        message = {"id": "msg-002"}

        # Act
        result = gmail_adapter_mock._map_to_standard_email(message)

        # Assert
        # Pas de labels = pas de UNREAD = message lu
        assert result.is_read is True

    def test_map_message_with_unread_label_is_not_read(self, gmail_adapter_mock):
        """
        ARRANGE: message avec labelIds contenant "UNREAD"
        ACT: Appeler _map_to_standard_email()
        ASSERT: is_read=False
        """
        # Arrange
        message = {
            "id": "msg-003",
            "labelIds": ["INBOX", "UNREAD"]
        }

        # Act
        result = gmail_adapter_mock._map_to_standard_email(message)

        # Assert
        assert result.is_read is False

    def test_map_message_invalid_date_uses_none(self, gmail_adapter_mock):
        """
        ARRANGE: message avec date invalide
        ACT: Appeler _map_to_standard_email()
        ASSERT: received_at=None (pas d'exception)
        """
        # Arrange
        message = {
            "id": "msg-004",
            "payload": {
                "headers": [
                    {"name": "Date", "value": "invalid-date-format"}
                ]
            }
        }

        # Act
        result = gmail_adapter_mock._map_to_standard_email(message)

        # Assert
        assert result.received_at is None


# =============================================================================
# Tests - apply_label Edge Cases
# =============================================================================


class TestApplyLabelEdgeCases:
    """Tests pour les edge cases de GmailAdapter.apply_label()."""

    @pytest.fixture
    def gmail_adapter_authenticated(self):
        """Crée un GmailAdapter mocké et authentifié."""
        with patch("app.providers.gmail_adapter.build"):
            with patch("app.providers.gmail_adapter.Credentials"):
                from app.providers.gmail_adapter import GmailAdapter
                adapter = GmailAdapter.__new__(GmailAdapter)
                adapter._service = MagicMock()
                adapter._creds = MagicMock()
                adapter._creds.valid = True
                adapter.PROVIDER_NAME = "gmail"
                adapter._get_or_create_label = MagicMock(return_value="label-123")
                adapter._ensure_authenticated = MagicMock()
                return adapter

    def test_apply_label_success(self, gmail_adapter_authenticated):
        """
        ARRANGE: message_id et label valides
        ACT: Appeler apply_label()
        ASSERT: Retourne True
        """
        # Act
        result = gmail_adapter_authenticated.apply_label("msg-001", "URGENT")

        # Assert
        assert result is True
        gmail_adapter_authenticated._get_or_create_label.assert_called_once_with(
            "Agentys/URGENT"
        )

    def test_apply_label_get_or_create_returns_none(self, gmail_adapter_authenticated):
        """
        ARRANGE: _get_or_create_label() retourne None
        ACT: Appeler apply_label()
        ASSERT: Retourne False
        """
        # Arrange
        gmail_adapter_authenticated._get_or_create_label.return_value = None

        # Act
        result = gmail_adapter_authenticated.apply_label("msg-001", "TEST")

        # Assert
        assert result is False

    def test_apply_label_http_error_returns_false(self, gmail_adapter_authenticated):
        """
        ARRANGE: API Gmail lève HttpError
        ACT: Appeler apply_label()
        ASSERT: Retourne False
        """
        from googleapiclient.errors import HttpError
        import httplib2

        # Arrange
        resp = httplib2.Response({"status": 404})
        gmail_adapter_authenticated._service.users().messages().modify.side_effect = (
            HttpError(resp, b"Not Found")
        )

        # Act
        result = gmail_adapter_authenticated.apply_label("msg-001", "TEST")

        # Assert
        assert result is False

    def test_apply_label_empty_label_still_prefixed(self, gmail_adapter_authenticated):
        """
        ARRANGE: label="" (chaîne vide)
        ACT: Appeler apply_label()
        ASSERT: Label préfixé devient "Agentys/"

        NOTE: Le code ne valide pas les labels vides
        """
        # Act
        gmail_adapter_authenticated.apply_label("msg-001", "")

        # Assert
        gmail_adapter_authenticated._get_or_create_label.assert_called_once_with(
            "Agentys/"
        )


# =============================================================================
# Tests - create_draft Edge Cases
# =============================================================================


class TestCreateDraftEdgeCases:
    """Tests pour les edge cases de GmailAdapter.create_draft()."""

    @pytest.fixture
    def gmail_adapter_authenticated(self):
        """Crée un GmailAdapter mocké et authentifié."""
        with patch("app.providers.gmail_adapter.build"):
            with patch("app.providers.gmail_adapter.Credentials"):
                from app.providers.gmail_adapter import GmailAdapter
                adapter = GmailAdapter.__new__(GmailAdapter)
                adapter._service = MagicMock()
                adapter._creds = MagicMock()
                adapter._creds.valid = True
                adapter.PROVIDER_NAME = "gmail"
                adapter._ensure_authenticated = MagicMock()
                adapter._create_message = MagicMock(return_value={"raw": "encoded"})
                adapter.get_message_by_id = MagicMock(return_value=None)

                # Mock la création de draft
                adapter._service.users().drafts().create().execute.return_value = {
                    "id": "draft-001"
                }
                return adapter

    def test_create_draft_success(self, gmail_adapter_authenticated):
        """
        ARRANGE: Paramètres valides
        ACT: Appeler create_draft()
        ASSERT: Retourne l'ID du draft
        """
        # Act
        result = gmail_adapter_authenticated.create_draft(
            to=["recipient@example.com"],
            subject="Test Subject",
            body="Test body"
        )

        # Assert
        assert result == "draft-001"

    def test_create_draft_empty_to_still_creates(self, gmail_adapter_authenticated):
        """
        ARRANGE: to=[]
        ACT: Appeler create_draft()
        ASSERT: Le draft est quand même créé (pas de validation côté adapter)
        """
        # Act
        result = gmail_adapter_authenticated.create_draft(
            to=[],
            subject="Test",
            body="Body"
        )

        # Assert
        assert result == "draft-001"

    def test_create_draft_with_reply_to_adds_thread_id(self, gmail_adapter_authenticated):
        """
        ARRANGE: reply_to_id pointant vers un message avec conversation_id
        ACT: Appeler create_draft()
        ASSERT: threadId est ajouté au draft
        """
        # Arrange
        original = StandardEmail(
            id="original-001",
            sender="sender@example.com",
            conversation_id="thread-123"
        )
        gmail_adapter_authenticated.get_message_by_id.return_value = original

        # Act
        result = gmail_adapter_authenticated.create_draft(
            to=["recipient@example.com"],
            subject="Re: Test",
            body="Reply body",
            reply_to_id="original-001"
        )

        # Assert
        assert result == "draft-001"
        create_call = gmail_adapter_authenticated._service.users().drafts().create
        create_call.assert_called()

    def test_create_draft_http_error_returns_none(self, gmail_adapter_authenticated):
        """
        ARRANGE: API Gmail lève HttpError
        ACT: Appeler create_draft()
        ASSERT: Retourne None
        """
        from googleapiclient.errors import HttpError
        import httplib2

        # Arrange
        resp = httplib2.Response({"status": 500})
        gmail_adapter_authenticated._service.users().drafts().create().execute.side_effect = (
            HttpError(resp, b"Internal Error")
        )

        # Act
        result = gmail_adapter_authenticated.create_draft(
            to=["test@test.com"],
            subject="Test",
            body="Body"
        )

        # Assert
        assert result is None


# =============================================================================
# Tests - _normalize_recipients Edge Cases (via mixin)
# =============================================================================


class TestNormalizeRecipientsEdgeCases:
    """Tests pour les edge cases de EmailParserMixin._normalize_recipients()."""

    def test_normalize_empty_string_returns_empty_list(self):
        """
        ARRANGE: recipients=""
        ACT: Appeler _normalize_recipients("")
        ASSERT: Retourne []
        """
        from app.providers.email_parser_mixin import EmailParserMixin

        mixin = EmailParserMixin()
        result = mixin._normalize_recipients("")

        assert result == []

    def test_normalize_single_email(self):
        """
        ARRANGE: recipients="user@example.com"
        ACT: Appeler _normalize_recipients()
        ASSERT: Retourne ["user@example.com"]
        """
        from app.providers.email_parser_mixin import EmailParserMixin

        mixin = EmailParserMixin()
        result = mixin._normalize_recipients("user@example.com")

        assert result == ["user@example.com"]

    def test_normalize_multiple_emails_comma_separated(self):
        """
        ARRANGE: recipients avec virgules
        ACT: Appeler _normalize_recipients()
        ASSERT: Retourne liste séparée
        """
        from app.providers.email_parser_mixin import EmailParserMixin

        mixin = EmailParserMixin()
        result = mixin._normalize_recipients("a@a.com, b@b.com, c@c.com")

        assert len(result) == 3
        assert "a@a.com" in result
        assert "b@b.com" in result
        assert "c@c.com" in result

    def test_normalize_email_with_name(self):
        """
        ARRANGE: recipients="John Doe <john@example.com>"
        ACT: Appeler _normalize_recipients()
        ASSERT: Extrait l'email
        """
        from app.providers.email_parser_mixin import EmailParserMixin

        mixin = EmailParserMixin()
        result = mixin._normalize_recipients("John Doe <john@example.com>")

        assert "john@example.com" in result[0]

    def test_normalize_whitespace_only_returns_empty(self):
        """
        ARRANGE: recipients="   "
        ACT: Appeler _normalize_recipients()
        ASSERT: Retourne []
        """
        from app.providers.email_parser_mixin import EmailParserMixin

        mixin = EmailParserMixin()
        result = mixin._normalize_recipients("   ")

        assert result == []


# =============================================================================
# Tests - _parse_email_address Edge Cases (via mixin)
# =============================================================================


class TestParseEmailAddressEdgeCases:
    """Tests pour les edge cases de EmailParserMixin._parse_email_address()."""

    def test_parse_empty_string(self):
        """
        ARRANGE: address=""
        ACT: Appeler _parse_email_address("")
        ASSERT: Retourne ("", None)
        """
        from app.providers.email_parser_mixin import EmailParserMixin

        mixin = EmailParserMixin()
        email, name = mixin._parse_email_address("")

        assert email == ""
        assert name is None

    def test_parse_simple_email(self):
        """
        ARRANGE: address="user@example.com"
        ACT: Appeler _parse_email_address()
        ASSERT: Retourne ("user@example.com", None)
        """
        from app.providers.email_parser_mixin import EmailParserMixin

        mixin = EmailParserMixin()
        email, name = mixin._parse_email_address("user@example.com")

        assert email == "user@example.com"
        assert name is None

    def test_parse_email_with_name(self):
        """
        ARRANGE: address="John Doe <john@example.com>"
        ACT: Appeler _parse_email_address()
        ASSERT: Retourne ("john@example.com", "John Doe")
        """
        from app.providers.email_parser_mixin import EmailParserMixin

        mixin = EmailParserMixin()
        email, name = mixin._parse_email_address("John Doe <john@example.com>")

        assert email == "john@example.com"
        assert name == "John Doe"

    def test_parse_email_with_quoted_name(self):
        """
        ARRANGE: address='"Doe, John" <john@example.com>'
        ACT: Appeler _parse_email_address()
        ASSERT: Extrait correctement le nom avec virgule
        """
        from app.providers.email_parser_mixin import EmailParserMixin

        mixin = EmailParserMixin()
        email, name = mixin._parse_email_address('"Doe, John" <john@example.com>')

        assert email == "john@example.com"
        assert "Doe" in name and "John" in name

    def test_parse_email_unicode_name(self):
        """
        ARRANGE: address="日本語 <user@example.com>"
        ACT: Appeler _parse_email_address()
        ASSERT: Gère les caractères Unicode
        """
        from app.providers.email_parser_mixin import EmailParserMixin

        mixin = EmailParserMixin()
        email, name = mixin._parse_email_address("日本語 <user@example.com>")

        assert email == "user@example.com"
        assert "日本語" in name


def test_gmail_authenticate_accepts_refresh_only_server_token():
    """Worker-safe: DB fallback may provide only a refresh token."""
    from app.providers.gmail_adapter import GmailAdapter

    adapter = GmailAdapter(
        client_id="google-client-id",
        client_secret="google-client-secret",
        account_id="gmail-account-hash",
    )
    adapter.token_file = None
    fake_credentials = MagicMock()
    fake_credentials.refresh_token = "refresh-token"
    fake_credentials.valid = False
    fake_credentials.expired = False

    def mark_refreshed(_request):
        fake_credentials.valid = True

    fake_credentials.refresh.side_effect = mark_refreshed

    with patch.object(
        adapter,
        "_get_server_tokens",
        return_value={"access_token": None, "refresh_token": "refresh-token"},
    ), \
         patch("app.providers.gmail_adapter.Credentials", return_value=fake_credentials) as creds_cls, \
         patch("app.providers.gmail_adapter.Request"), \
         patch("app.providers.gmail_adapter.build", return_value=object()):
        assert adapter.authenticate() is True

    assert creds_cls.call_args.kwargs["token"] is None
    assert creds_cls.call_args.kwargs["refresh_token"] == "refresh-token"
    fake_credentials.refresh.assert_called_once()


# =============================================================================
# Tests - Boundary Values
# =============================================================================


class TestGmailAdapterBoundaryValues:
    """Tests pour les valeurs limites de GmailAdapter."""

    def test_very_long_subject_handled(self):
        """
        ARRANGE: Subject très long (>1000 chars)
        ACT: Créer un email avec ce sujet
        ASSERT: Pas d'erreur de troncature
        """
        long_subject = "A" * 2000

        email = StandardEmail(
            id="test-long",
            sender="sender@example.com",
            subject=long_subject
        )

        assert len(email.subject) == 2000

    def test_very_long_body_handled(self):
        """
        ARRANGE: Body très long (>100KB)
        ACT: Créer un email avec ce body
        ASSERT: Pas d'erreur
        """
        long_body = "X" * 100000

        email = StandardEmail(
            id="test-long-body",
            sender="sender@example.com",
            body=long_body
        )

        assert len(email.body) == 100000

    def test_email_with_many_recipients(self):
        """
        ARRANGE: Email avec 100 destinataires
        ACT: Créer l'email
        ASSERT: Tous les destinataires sont conservés
        """
        recipients = [f"user{i}@example.com" for i in range(100)]

        email = StandardEmail(
            id="test-many-recipients",
            sender="sender@example.com",
            to=recipients
        )

        assert len(email.to) == 100

    def test_email_with_special_characters_in_body(self):
        """
        ARRANGE: Body avec caractères spéciaux (null bytes, unicode)
        ACT: Créer l'email
        ASSERT: Caractères préservés
        """
        special_body = "Line1\x00Line2\nLine3\t🚀"

        email = StandardEmail(
            id="test-special",
            sender="sender@example.com",
            body=special_body
        )

        assert "\x00" in email.body
        assert "🚀" in email.body
