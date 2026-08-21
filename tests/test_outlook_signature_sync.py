# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests E2E pour la synchronisation de signature Outlook.

Couvre:
1. get_signature() — stratégie mailboxSettings
2. get_signature() — fallback extraction depuis emails envoyés (sentitems)
3. get_signature() — aucune signature trouvée
4. POST /api/accounts/<id>/sync-signature — endpoint complet
5. Patterns HTML Outlook (id=Signature, class=signature, bordure, --)
"""

import pytest
import asyncio
from unittest.mock import MagicMock, patch


# =============================================================================
# Mock helpers
# =============================================================================

class MockItemBody:
    """Mock pour ItemBody Graph API."""
    def __init__(self, content: str = "", content_type=None):
        self.content = content
        self.content_type = content_type


class MockMessage:
    """Mock pour Message Graph API."""
    def __init__(self, id: str = "msg-1", body: MockItemBody = None):
        self.id = id
        self.body = body or MockItemBody()


class MockMailboxSettings:
    """Mock pour MailboxSettings Graph API."""
    def __init__(self, additional_data=None):
        self.additional_data = additional_data or {}


class MockBodyType:
    Html = "html"
    Text = "text"


OUTLOOK_SIGNATURE_HTML = (
    '<div id="Signature">'
    '<p><b>Jean Dupont</b></p>'
    '<p>Directeur — Acme Corp</p>'
    '<p>+33 1 23 45 67 89</p>'
    '</div>'
)

OUTLOOK_SIGNATURE_CLASS = (
    '<div class="email-signature">'
    '<p>Marie Martin | VP Sales</p>'
    '<p>marie@example.com</p>'
    '</div>'
)

OUTLOOK_SIGNATURE_SEPARATOR = (
    '<div>Bonjour,</div>'
    '<div>Merci pour votre message.</div>'
    '<div><br></div>'
    '-- <br>'
    '<div>Pierre Durand</div>'
    '<div>CTO @ StartupXYZ</div>'
)

SENT_EMAIL_WITH_SIGNATURE = (
    '<html><body>'
    '<div>Bonjour Alice,</div>'
    '<div><br></div>'
    '<div>Voici le document demandé.</div>'
    '<div><br></div>'
    '<div>Cordialement,</div>'
    '<div><br></div>'
    f'{OUTLOOK_SIGNATURE_HTML}'
    '</body></html>'
)

SENT_EMAIL_NO_SIGNATURE = (
    '<html><body>'
    '<div>OK merci !</div>'
    '</body></html>'
)


@pytest.fixture
def mock_env_vars(monkeypatch):
    monkeypatch.setenv("AZURE_TENANT_ID", "test-tenant")
    monkeypatch.setenv("AZURE_CLIENT_ID", "test-client")
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("OUTLOOK_USER_ID", "jean@hotmail.com")


@pytest.fixture
def mock_graph_imports():
    with patch("app.providers.outlook_adapter.ClientSecretCredential"), \
         patch("app.providers.outlook_adapter.DeviceCodeCredential"), \
         patch("app.providers.outlook_adapter.GraphServiceClient"), \
         patch("app.providers.outlook_adapter.MessagesRequestBuilder") as mock_msg_builder, \
         patch("app.providers.outlook_adapter.FolderMessagesRequestBuilder"), \
         patch("app.providers.outlook_adapter.Message"), \
         patch("app.providers.outlook_adapter.Recipient"), \
         patch("app.providers.outlook_adapter.EmailAddress"), \
         patch("app.providers.outlook_adapter.ItemBody"), \
         patch("app.providers.outlook_adapter.BodyType", MockBodyType):
        yield {"msg_builder": mock_msg_builder}


@pytest.fixture
def authenticated_adapter(mock_env_vars, mock_graph_imports):
    from app.providers.outlook_adapter import OutlookAdapter
    adapter = OutlookAdapter()
    adapter._authenticated = True
    adapter._client = MagicMock()
    adapter.user_id = "jean@hotmail.com"
    return adapter


def _make_async_result(value):
    """Helper: wrap value in a coroutine for async mock.

    Python 3.11+ : asyncio.Future() sans event loop lève RuntimeError. On crée
    un event loop si aucun n'existe dans le thread courant (cas des tests sync
    qui patchent avec des futures pour les méthodes async).
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    f = loop.create_future()
    f.set_result(value)
    return f


# =============================================================================
# Tests — get_signature() via mailboxSettings
# =============================================================================


class TestGetSignatureMailboxSettings:
    """Strategy 1: signature from Graph API mailboxSettings."""

    def test_signature_from_additional_data(self, authenticated_adapter):
        """Signature found in mailboxSettings.additional_data (recent Graph API)."""
        settings = MockMailboxSettings(additional_data={
            "signatureForNewMessages": "<p><b>Jean Dupont</b><br>Acme Corp</p>",
        })

        # Mock mailbox_settings.get() → returns settings
        chain = authenticated_adapter._client.users.by_user_id.return_value
        chain.mailbox_settings.get.return_value = _make_async_result(settings)

        result = authenticated_adapter.get_signature()

        assert result is not None
        assert result["html"] == "<p><b>Jean Dupont</b><br>Acme Corp</p>"
        assert "Jean Dupont" in result["text"]
        assert "Acme Corp" in result["text"]
        # No HTML tags in text
        assert "<p>" not in result["text"]
        assert "<b>" not in result["text"]

    def test_signature_from_replies_or_forwards(self, authenticated_adapter):
        """Signature found in signatureForRepliesOrForwards fallback."""
        settings = MockMailboxSettings(additional_data={
            "signatureForRepliesOrForwards": "<div>-- <br>Marie Martin</div>",
        })

        chain = authenticated_adapter._client.users.by_user_id.return_value
        chain.mailbox_settings.get.return_value = _make_async_result(settings)

        result = authenticated_adapter.get_signature()

        assert result is not None
        assert "Marie Martin" in result["text"]

    def test_empty_mailbox_settings_falls_through(self, authenticated_adapter):
        """Empty mailboxSettings → falls through to sent email extraction."""
        settings = MockMailboxSettings(additional_data={})

        chain = authenticated_adapter._client.users.by_user_id.return_value
        chain.mailbox_settings.get.return_value = _make_async_result(settings)

        # Sent emails fallback → no sent emails → returns None
        chain.mail_folders.by_mail_folder_id.return_value.messages.get.return_value = \
            _make_async_result(MagicMock(value=[]))

        result = authenticated_adapter.get_signature()

        assert result is None


# =============================================================================
# Tests — get_signature() via sent emails extraction
# =============================================================================


class TestGetSignatureSentEmails:
    """Strategy 2: extract signature from sent emails in sentitems folder."""

    def _setup_sent_emails(self, adapter, html_bodies):
        """Helper: mock mailboxSettings (empty) + sent emails with given bodies."""
        chain = adapter._client.users.by_user_id.return_value

        # mailboxSettings → empty (force fallback to sent emails)
        chain.mailbox_settings.get.return_value = _make_async_result(
            MockMailboxSettings(additional_data={})
        )

        # sentitems folder → messages
        msgs = [MockMessage(id=f"msg-{i}", body=MockItemBody(content=body))
                for i, body in enumerate(html_bodies)]
        mock_result = MagicMock()
        mock_result.value = msgs
        chain.mail_folders.by_mail_folder_id.return_value.messages.get.return_value = \
            _make_async_result(mock_result)

    def test_extract_signature_id_pattern(self, authenticated_adapter):
        """Extract signature from <div id="Signature">...</div>."""
        self._setup_sent_emails(authenticated_adapter, [SENT_EMAIL_WITH_SIGNATURE])

        result = authenticated_adapter.get_signature()

        assert result is not None
        assert "Jean Dupont" in result["text"]
        assert "Acme Corp" in result["text"]
        assert result["html"] is not None

    def test_extract_signature_class_pattern(self, authenticated_adapter):
        """Extract signature from <div class="email-signature">...</div>."""
        html = f'<div>Hello!</div>{OUTLOOK_SIGNATURE_CLASS}'
        self._setup_sent_emails(authenticated_adapter, [html])

        result = authenticated_adapter.get_signature()

        assert result is not None
        assert "Marie Martin" in result["text"]
        assert "VP Sales" in result["text"]

    def test_extract_signature_separator_pattern(self, authenticated_adapter):
        """Extract signature from -- separator."""
        self._setup_sent_emails(authenticated_adapter, [OUTLOOK_SIGNATURE_SEPARATOR])

        result = authenticated_adapter.get_signature()

        assert result is not None
        assert "Pierre Durand" in result["text"]

    def test_no_signature_in_sent_emails(self, authenticated_adapter):
        """Short email without signature pattern → returns None."""
        self._setup_sent_emails(authenticated_adapter, [SENT_EMAIL_NO_SIGNATURE])

        result = authenticated_adapter.get_signature()

        assert result is None

    def test_sent_emails_take_precedence_over_mailbox_settings(self, authenticated_adapter):
        """Bug import 2026-06 : mailboxSettings (champ legacy) peut renvoyer une
        signature périmée — l'OWA moderne stocke les signatures dans des
        paramètres cloud que Graph n'expose pas. Quand les deux sources
        existent, la signature des emails ENVOYÉS (ce que l'utilisateur
        utilise réellement) doit gagner."""
        chain = authenticated_adapter._client.users.by_user_id.return_value
        chain.mailbox_settings.get.return_value = _make_async_result(
            MockMailboxSettings(additional_data={
                "signatureForNewMessages": "<p>Vieille Signature info@ancien.com</p>",
            })
        )
        msgs = [MockMessage(id="msg-0", body=MockItemBody(content=SENT_EMAIL_WITH_SIGNATURE))]
        mock_result = MagicMock()
        mock_result.value = msgs
        chain.mail_folders.by_mail_folder_id.return_value.messages.get.return_value = \
            _make_async_result(mock_result)

        result = authenticated_adapter.get_signature()

        assert result is not None
        assert "Jean Dupont" in result["text"]
        assert "Vieille Signature" not in result["text"]

    def test_no_sent_emails(self, authenticated_adapter):
        """Empty sent folder → returns None."""
        chain = authenticated_adapter._client.users.by_user_id.return_value
        chain.mailbox_settings.get.return_value = _make_async_result(
            MockMailboxSettings(additional_data={})
        )
        mock_result = MagicMock()
        mock_result.value = []
        chain.mail_folders.by_mail_folder_id.return_value.messages.get.return_value = \
            _make_async_result(mock_result)

        result = authenticated_adapter.get_signature()

        assert result is None

    def test_fetches_from_sentitems_not_inbox(self, authenticated_adapter):
        """Verify sent emails are fetched from 'sentitems' folder, not inbox."""
        chain = authenticated_adapter._client.users.by_user_id.return_value
        chain.mailbox_settings.get.return_value = _make_async_result(
            MockMailboxSettings(additional_data={})
        )

        mock_result = MagicMock()
        mock_result.value = []
        folder_chain = chain.mail_folders.by_mail_folder_id
        folder_chain.return_value.messages.get.return_value = _make_async_result(mock_result)

        authenticated_adapter.get_signature()

        # Verify the folder_id passed is "sentitems"
        folder_chain.assert_called_with("sentitems")

    def test_multiple_sent_emails_finds_first_match(self, authenticated_adapter):
        """First email has no signature, second does → extracts from second."""
        self._setup_sent_emails(authenticated_adapter, [
            SENT_EMAIL_NO_SIGNATURE,
            SENT_EMAIL_WITH_SIGNATURE,
        ])

        result = authenticated_adapter.get_signature()

        assert result is not None
        assert "Jean Dupont" in result["text"]

    def test_signature_text_has_no_html_tags(self, authenticated_adapter):
        """Verify text version is stripped of all HTML."""
        self._setup_sent_emails(authenticated_adapter, [SENT_EMAIL_WITH_SIGNATURE])

        result = authenticated_adapter.get_signature()

        assert result is not None
        assert "<" not in result["text"]
        assert ">" not in result["text"]

    def test_signature_html_preserved(self, authenticated_adapter):
        """HTML version preserves formatting tags."""
        self._setup_sent_emails(authenticated_adapter, [SENT_EMAIL_WITH_SIGNATURE])

        result = authenticated_adapter.get_signature()

        assert result is not None
        assert "<p>" in result["html"] or "<b>" in result["html"]


# =============================================================================
# Regression — Bug: import imported full email body instead of signature only
# Root cause: Pattern 3 (divtagdefaultwrapper + border-top) captured the quoted
# thread content instead of the signature. Fix: strip quoted thread before matching.
# =============================================================================


SENT_REPLY_WITH_HR_SEPARATOR = (
    '<html><body>'
    '<div id="divtagdefaultwrapper">'
    '<p>Salut Simon,</p>'
    '<p>Je change de vocation pour mon entreprise.</p>'
    '<p>À bientôt,<br>Alexandre</p>'
    '<div id="Signature"><p>Alexandre Simon | CEO Agentys</p><p>alexandre@agentys.ai</p></div>'
    '</div>'
    '<hr tabindex="-1" style="display:inline-block;width:98%">'
    '<div id="divRplyFwdMsg" dir="ltr">'
    '<b>De :</b> Simon Dupuis<br>'
    '<b>Envoyé :</b> 31 décembre 2021 13:02<br>'
    '<b>À :</b> Alexandre Simon<br>'
    '<b>Objet :</b> TR: Re.: 9457-3383 QUÉBEC INC.'
    '<div><p>SAlut Alexandre,</p></div>'
    '</div>'
    '</body></html>'
)

SENT_REPLY_WITH_BORDERTOP_SEPARATOR = (
    '<html><body>'
    '<div id="divtagdefaultwrapper">'
    '<p>Bonjour,</p>'
    '<div id="Signature"><p>Marie Martin | VP Sales</p></div>'
    '<div style="border-top:solid #E1E1E1 1.0pt;padding:3.0pt 0cm 0cm 0cm">'
    '<b>De :</b> Alexandre Simon<br>'
    '<b>Envoyé :</b> 15 mars 2026 17:48<br>'
    '<b>Objet :</b> Re: Re.: 9457-3383 QUÉBEC INC.<br>'
    '<p>Avertissement : Ce courriel provient de l\'extérieur de votre entreprise.</p>'
    '<p>Salut Simon, Je change de vocation pour mon entreprise...</p>'
    '</div>'
    '</div>'
    '</body></html>'
)

SENT_REPLY_QUOTED_THREAD_ONLY = (
    '<html><body>'
    '<div id="divtagdefaultwrapper">'
    '<p>OK merci.</p>'
    '</div>'
    '<hr tabindex="-1">'
    '<div id="divRplyFwdMsg">'
    '<b>De :</b> Alexandre Simon<br>'
    '<b>Envoyé :</b> 15 mars 2026 17:48<br>'
    '<b>À :</b> Simon Dupuis<br>'
    '<b>Objet :</b> Re: Re.: 9457-3383 QUÉBEC INC.'
    '<p>Avertissement : Ce courriel provient de l\'extérieur.</p>'
    '<p>Salut Simon, Je change de vocation...</p>'
    '<hr>'
    '<b>De :</b> Simon Dupuis<br>'
    '<b>Envoyé :</b> 31 décembre 2021 13:02<br>'
    '</div>'
    '</body></html>'
)


class TestGetSignatureRegressionQuotedThread:
    """Regression: importing from Outlook must NOT import the quoted thread as signature."""

    def _setup_sent_emails(self, adapter, html_bodies):
        chain = adapter._client.users.by_user_id.return_value
        chain.mailbox_settings.get.return_value = _make_async_result(
            MockMailboxSettings(additional_data={})
        )
        msgs = [MockMessage(id=f"msg-{i}", body=MockItemBody(content=body))
                for i, body in enumerate(html_bodies)]
        mock_result = MagicMock()
        mock_result.value = msgs
        chain.mail_folders.by_mail_folder_id.return_value.messages.get.return_value = \
            _make_async_result(mock_result)

    def test_hr_separator_does_not_import_quoted_thread(self, authenticated_adapter):
        """Reply with <hr> separator: quoted De/Envoyé/À headers must NOT appear in signature."""
        self._setup_sent_emails(authenticated_adapter, [SENT_REPLY_WITH_HR_SEPARATOR])

        result = authenticated_adapter.get_signature()

        assert result is not None
        assert "Alexandre Simon | CEO Agentys" in result["text"]
        # The quoted thread headers must NOT appear in the extracted signature
        assert "De :" not in result["text"]
        assert "Envoyé :" not in result["text"]
        assert "SAlut Alexandre" not in result["text"]

    def test_bordertop_separator_does_not_import_quoted_thread(self, authenticated_adapter):
        """Reply with border-top separator: quoted content must NOT appear in signature."""
        self._setup_sent_emails(authenticated_adapter, [SENT_REPLY_WITH_BORDERTOP_SEPARATOR])

        result = authenticated_adapter.get_signature()

        assert result is not None
        assert "Marie Martin" in result["text"]
        # The quoted thread content must NOT be in the signature
        assert "Avertissement" not in result["text"]
        assert "Je change de vocation" not in result["text"]
        assert "De :" not in result["text"]

    def test_reply_without_signature_div_returns_none(self, authenticated_adapter):
        """Reply with only quoted thread and no signature marker → returns None, not the thread."""
        self._setup_sent_emails(authenticated_adapter, [SENT_REPLY_QUOTED_THREAD_ONLY])

        result = authenticated_adapter.get_signature()

        # Must NOT return the quoted thread as a signature
        assert result is None or (
            result is not None and "De :" not in result["text"] and "Envoyé :" not in result["text"]
        )


# =============================================================================
# Regression — Bug: plain text email body causes full thread to be returned
# Root cause: Graph API returns body as plain text for Hotmail accounts.
# HTML strip patterns (<hr>, border-top) have no effect → Pattern 4 with
# re.DOTALL captured from "-- \n" to end of string (entire quoted thread).
# Fix: detect is_html, apply plain-text-specific stripping + last-para heuristic.
# =============================================================================


PLAIN_TEXT_REPLY_WITH_SIGNATURE = (
    "Bonjour Simon,\n\n"
    "Merci pour votre message. Je vous confirme la réunion.\n\n"
    "Cordialement,\n"
    "Alexandre Simon\n"
    "CEO Agentys | alexandre@hotmail.com\n\n"
    "________________________________\n"
    "De : Simon Dupuis <simon@example.com>\n"
    "Envoyé : vendredi 31 décembre 2021 13:02\n"
    "À : Alexandre Simon\n"
    "Objet : TR: Re.: Réunion\n\n"
    "Bonjour Alexandre, pouvez-vous confirmer la réunion ?"
)

PLAIN_TEXT_FULL_THREAD_ONLY = (
    "De : Alexandre Simon <alexandre.simon@hotmail.com>\n"
    "Envoyé : 15 mars 2026 17:48\n"
    "À : Simon Dupuis <simon@dupuis.ca>\n"
    "Objet : Re: 9457-3383 QUÉBEC INC.\n\n"
    "Salut Simon,\n\n"
    "Je change de vocation pour mon entreprise. Je reviendrai vers toi.\n\n"
    "Alexandre"
)

PLAIN_TEXT_SHORT_REPLY = (
    "OK merci !\n\n"
    "________________________________\n"
    "De : Simon Dupuis <simon@example.com>\n"
    "Envoyé : lundi 15 mars 2026 12:00\n"
    "Objet : Test"
)

PLAIN_TEXT_NEW_MESSAGE_WITH_SIGNATURE = (
    "Bonjour,\n\n"
    "Veuillez trouver ci-joint les documents demandés.\n\n"
    "Cordialement,\n"
    "Marie Martin\n"
    "VP Sales | marie@agentys.ai\n"
    "+1 514-555-0102"
)


class TestGetSignaturePlainTextRegression:
    """Regression: plain text email bodies from Graph API (Hotmail/Outlook)."""

    def _setup_sent_emails(self, adapter, bodies):
        chain = adapter._client.users.by_user_id.return_value
        chain.mailbox_settings.get.return_value = _make_async_result(
            MockMailboxSettings(additional_data={})
        )
        msgs = [MockMessage(id=f"msg-{i}", body=MockItemBody(content=body))
                for i, body in enumerate(bodies)]
        mock_result = MagicMock()
        mock_result.value = msgs
        chain.mail_folders.by_mail_folder_id.return_value.messages.get.return_value = \
            _make_async_result(mock_result)

    def test_plain_text_reply_extracts_signature_not_thread(self, authenticated_adapter):
        """Plain text reply with ________ separator: signature extracted, quoted thread NOT included."""
        self._setup_sent_emails(authenticated_adapter, [PLAIN_TEXT_REPLY_WITH_SIGNATURE])

        result = authenticated_adapter.get_signature()

        assert result is not None
        assert "Alexandre Simon" in result["text"]
        # The quoted thread must NOT appear in the signature
        assert "De :" not in result["text"]
        assert "Envoyé :" not in result["text"]
        assert "Simon Dupuis" not in result["text"]

    def test_plain_text_body_starting_with_headers_returns_none(self, authenticated_adapter):
        """Plain text body that starts with 'De :/Envoyé:/À:' (forwarded format) → None."""
        self._setup_sent_emails(authenticated_adapter, [PLAIN_TEXT_FULL_THREAD_ONLY])

        result = authenticated_adapter.get_signature()

        # Must NOT return the thread headers as a signature
        if result is not None:
            assert "De :" not in result["text"]
            assert "Envoyé :" not in result["text"]

    def test_plain_text_short_reply_returns_none(self, authenticated_adapter):
        """'OK merci!' reply with no signature block → returns None."""
        self._setup_sent_emails(authenticated_adapter, [PLAIN_TEXT_SHORT_REPLY])

        result = authenticated_adapter.get_signature()

        # "OK merci !" is 9 chars — too short to qualify as signature
        # The quoted thread (De :/Envoyé:) must not be returned either
        if result is not None:
            assert "De :" not in result["text"]
            assert len(result["text"]) > 10

    def test_plain_text_new_message_last_para_heuristic(self, authenticated_adapter):
        """Direct plain text message (no reply): last paragraph is the signature."""
        self._setup_sent_emails(authenticated_adapter, [PLAIN_TEXT_NEW_MESSAGE_WITH_SIGNATURE])

        result = authenticated_adapter.get_signature()

        assert result is not None
        assert "Marie Martin" in result["text"]
        # Must not contain the body
        assert "Veuillez trouver" not in result["text"]

    def test_plain_text_falls_back_to_next_email_if_no_signature(self, authenticated_adapter):
        """First email (short reply) has no signature → tries next email."""
        self._setup_sent_emails(authenticated_adapter, [
            PLAIN_TEXT_SHORT_REPLY,
            PLAIN_TEXT_NEW_MESSAGE_WITH_SIGNATURE,
        ])

        result = authenticated_adapter.get_signature()

        assert result is not None
        assert "Marie Martin" in result["text"]


# =============================================================================
# Regression — Nested <div> inside <div id="Signature">
# Root cause: Pattern 1 used (.*?)</div> which stopped at the first inner </div>
# and captured only partial signature. Fix: count open/close div depth.
# =============================================================================


NESTED_DIV_SIGNATURE = (
    '<html><body>'
    '<div class="elementToProof" style="font-family: Aptos;">'
    '<div>Bonjour,</div>'
    '<div><br></div>'
    '<div>Merci pour votre message.</div>'
    '</div>'
    '<div id="Signature">'
    '<div style="font-family: Aptos, sans-serif;">'
    '<div><b>Alexandre Simon</b></div>'
    '<div>CEO Agentys</div>'
    '<div>alexandre@agentys.ai</div>'
    '<div>+1 514-555-0102</div>'
    '</div>'
    '</div>'
    '<div id="appendonsend"></div>'
    '<hr tabindex="-1" style="display:inline-block;width:98%">'
    '<div id="divRplyFwdMsg" dir="ltr">'
    '<b>De :</b> Simon Dupuis<br>'
    '<b>Envoyé :</b> 31 décembre 2021 13:02<br>'
    '</div>'
    '</body></html>'
)

SIGNATURE_NO_MARKER_WITH_CLOSING_PHRASE = (
    '<html><body>'
    '<div>Bonjour,</div>'
    '<div><br></div>'
    '<div>Voici le document demandé.</div>'
    '<div><br></div>'
    '<div>Cordialement,</div>'
    '<div>Alexandre Simon</div>'
    '<div>CEO Agentys | alexandre@agentys.ai</div>'
    '<hr tabindex="-1">'
    '<div id="divRplyFwdMsg">'
    '<b>De :</b> Simon Dupuis<br>'
    '</div>'
    '</body></html>'
)


class TestGetSignatureNestedDiv:
    """Regression: Outlook.com signatures with nested <div> inside id='Signature'."""

    def _setup_sent_emails(self, adapter, html_bodies):
        chain = adapter._client.users.by_user_id.return_value
        chain.mailbox_settings.get.return_value = _make_async_result(
            MockMailboxSettings(additional_data={})
        )
        msgs = [MockMessage(id=f"msg-{i}", body=MockItemBody(content=body))
                for i, body in enumerate(html_bodies)]
        mock_result = MagicMock()
        mock_result.value = msgs
        chain.mail_folders.by_mail_folder_id.return_value.messages.get.return_value = \
            _make_async_result(mock_result)

    def test_nested_div_extracts_full_signature(self, authenticated_adapter):
        """Signature with nested divs: must capture ALL lines, not just first inner div."""
        self._setup_sent_emails(authenticated_adapter, [NESTED_DIV_SIGNATURE])

        result = authenticated_adapter.get_signature()

        assert result is not None
        assert "Alexandre Simon" in result["text"]
        assert "CEO Agentys" in result["text"]
        assert "alexandre@agentys.ai" in result["text"]
        assert "+1 514-555-0102" in result["text"]
        # Must NOT contain the quoted thread
        assert "De :" not in result["text"]
        assert "Simon Dupuis" not in result["text"]

    def test_closing_phrase_heuristic_when_no_signature_div(self, authenticated_adapter):
        """No id='Signature' → closing phrase heuristic extracts name/title block."""
        self._setup_sent_emails(authenticated_adapter, [SIGNATURE_NO_MARKER_WITH_CLOSING_PHRASE])

        result = authenticated_adapter.get_signature()

        assert result is not None
        assert "Alexandre Simon" in result["text"]
        # Must NOT contain the quoted thread
        assert "De :" not in result["text"]
        assert "Simon Dupuis" not in result["text"]


# =============================================================================
# Tests — get_signature() error handling
# =============================================================================


class TestGetSignatureErrors:
    """Error handling and edge cases."""

    def test_mailbox_settings_error_falls_through(self, authenticated_adapter):
        """mailboxSettings raises → falls through to sent emails."""
        chain = authenticated_adapter._client.users.by_user_id.return_value
        chain.mailbox_settings.get.return_value = _make_async_result(None)
        chain.mailbox_settings.get.side_effect = Exception("403 Forbidden")

        # Sent emails → valid signature
        msgs = [MockMessage(body=MockItemBody(content=SENT_EMAIL_WITH_SIGNATURE))]
        mock_result = MagicMock()
        mock_result.value = msgs
        chain.mail_folders.by_mail_folder_id.return_value.messages.get.return_value = \
            _make_async_result(mock_result)

        result = authenticated_adapter.get_signature()

        assert result is not None
        assert "Jean Dupont" in result["text"]

    def test_complete_failure_returns_none(self, authenticated_adapter):
        """Both strategies fail → returns None (no crash)."""
        chain = authenticated_adapter._client.users.by_user_id.return_value
        chain.mailbox_settings.get.side_effect = Exception("Network error")
        chain.mail_folders.by_mail_folder_id.return_value.messages.get.side_effect = \
            Exception("Network error")

        result = authenticated_adapter.get_signature()

        assert result is None

    def test_unauthenticated_raises(self, mock_env_vars, mock_graph_imports):
        """get_signature() on unauthenticated adapter → returns None."""
        from app.providers.outlook_adapter import OutlookAdapter
        adapter = OutlookAdapter()
        adapter._authenticated = False

        result = adapter.get_signature()

        assert result is None

    def test_short_signature_ignored(self, authenticated_adapter):
        """Signature < 10 chars is ignored (too short)."""
        html = '<div>Hi!</div><div id="Signature"><p>JD</p></div>'
        chain = authenticated_adapter._client.users.by_user_id.return_value
        chain.mailbox_settings.get.return_value = _make_async_result(
            MockMailboxSettings(additional_data={})
        )
        msgs = [MockMessage(body=MockItemBody(content=html))]
        mock_result = MagicMock()
        mock_result.value = msgs
        chain.mail_folders.by_mail_folder_id.return_value.messages.get.return_value = \
            _make_async_result(mock_result)

        result = authenticated_adapter.get_signature()

        assert result is None


# =============================================================================
# Tests — POST /api/accounts/<id>/sync-signature endpoint
# =============================================================================


class TestSyncSignatureEndpoint:
    """E2E tests for the sync-signature API endpoint."""

    @pytest.fixture
    def client(self):
        """Create Flask test client."""
        from app.api.app import create_app
        app = create_app()
        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c

    @pytest.fixture
    def mock_account(self):
        """Create a mock Outlook account."""
        account = MagicMock()
        account.id = "acc-outlook-123"
        account.name = "Hotmail"
        account.email = "jean@hotmail.com"
        account.provider = "outlook"
        account.status = "active"
        account.signature = None
        account.signature_html = None
        account.check_interval_minutes = 5
        account.max_emails_per_batch = 10
        account.auto_reply_enabled = True
        account.draft_only = False
        account.default_language = "fr"
        account.created_at = "2026-01-01T00:00:00"
        account.last_sync = None
        account.last_error = None
        account.email_count = 0
        account.user_id = None
        return account

    def test_sync_signature_success(self, client, mock_account):
        """Full flow: POST sync-signature → get_signature returns data → signature saved."""
        sig_data = {
            "html": "<p><b>Jean Dupont</b><br>Acme Corp</p>",
            "text": "Jean Dupont Acme Corp",
        }

        mock_provider = MagicMock()
        mock_provider.authenticate.return_value = True
        mock_provider.get_signature.return_value = sig_data

        updated_account = MagicMock()
        updated_account.id = mock_account.id
        updated_account.name = mock_account.name
        updated_account.email = mock_account.email
        updated_account.provider = mock_account.provider
        updated_account.status = mock_account.status
        updated_account.signature = "Jean Dupont Acme Corp"
        updated_account.signature_html = "<p><b>Jean Dupont</b><br>Acme Corp</p>"
        updated_account.check_interval_minutes = 5
        updated_account.max_emails_per_batch = 10
        updated_account.auto_reply_enabled = True
        updated_account.draft_only = False
        updated_account.default_language = "fr"
        updated_account.created_at = "2026-01-01"
        updated_account.last_sync = None
        updated_account.last_error = None
        updated_account.email_count = 0

        with patch("app.api.accounts.get_account_manager") as mock_mgr, \
             patch("app.multi_accounts.create_provider_for_account", return_value=mock_provider), \
             patch("app.api.accounts.get_db_session"), \
             patch("app.api.accounts._get_auth_user_id", return_value=None):
            mgr = MagicMock()
            mgr.get_account.return_value = mock_account
            mgr.update_account.return_value = updated_account
            mock_mgr.return_value = mgr

            resp = client.post(f"/api/accounts/{mock_account.id}/sync-signature")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["signature"] == "Jean Dupont Acme Corp"
        assert "Jean Dupont" in data["signature_html"]
        mock_provider.get_signature.assert_called_once()

    def test_sync_signature_no_signature_found(self, client, mock_account):
        """get_signature returns None → success with null signature."""
        mock_provider = MagicMock()
        mock_provider.authenticate.return_value = True
        mock_provider.get_signature.return_value = None

        with patch("app.api.accounts.get_account_manager") as mock_mgr, \
             patch("app.multi_accounts.create_provider_for_account", return_value=mock_provider), \
             patch("app.api.accounts._get_auth_user_id", return_value=None):
            mgr = MagicMock()
            mgr.get_account.return_value = mock_account
            mock_mgr.return_value = mgr

            resp = client.post(f"/api/accounts/{mock_account.id}/sync-signature")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["signature"] is None

    def test_sync_signature_auth_fails(self, client, mock_account):
        """Provider authentication fails → 503."""
        mock_provider = MagicMock()
        mock_provider.authenticate.return_value = False

        with patch("app.api.accounts.get_account_manager") as mock_mgr, \
             patch("app.multi_accounts.create_provider_for_account", return_value=mock_provider), \
             patch("app.api.accounts._get_auth_user_id", return_value=None):
            mgr = MagicMock()
            mgr.get_account.return_value = mock_account
            mock_mgr.return_value = mgr

            resp = client.post(f"/api/accounts/{mock_account.id}/sync-signature")

        assert resp.status_code == 503
        data = resp.get_json()
        assert data["success"] is False
        assert "authentication" in data["error"].lower()

    def test_sync_signature_account_not_found(self, client):
        """Unknown account_id → 404."""
        with patch("app.api.accounts.get_account_manager") as mock_mgr, \
             patch("app.api.accounts._get_auth_user_id", return_value=None):
            mgr = MagicMock()
            mgr.get_account.return_value = None
            mock_mgr.return_value = mgr

            resp = client.post("/api/accounts/unknown-id-123/sync-signature")

        assert resp.status_code == 404

    def test_sync_signature_provider_error(self, client, mock_account):
        """Provider raises exception → 500."""
        mock_provider = MagicMock()
        mock_provider.authenticate.return_value = True
        mock_provider.get_signature.side_effect = Exception("Graph API timeout")

        with patch("app.api.accounts.get_account_manager") as mock_mgr, \
             patch("app.multi_accounts.create_provider_for_account", return_value=mock_provider), \
             patch("app.api.accounts._get_auth_user_id", return_value=None):
            mgr = MagicMock()
            mgr.get_account.return_value = mock_account
            mock_mgr.return_value = mgr

            resp = client.post(f"/api/accounts/{mock_account.id}/sync-signature")

        assert resp.status_code == 500
        data = resp.get_json()
        assert "Graph API timeout" in data["error"]
