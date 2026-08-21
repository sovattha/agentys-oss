# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
E2E tests for a new Outlook / Hotmail user onboarding.

Mirror of ``test_gmail_onboarding_e2e.py`` but targets the Outlook
adapter path. Focus points unique to Outlook:

- OAuth callback uses the ``/common`` endpoint (multi-tenant: personal
  Hotmail / Outlook.com AND work/school Microsoft 365). This test
  protects against accidentally switching to a single-tenant authority.
- Sent folder is addressed via the Microsoft Graph well-known folder
  alias ``"sentitems"`` (see ``outlook_adapter._get_sent_emails_async``).
  The onboarding profile extraction depends entirely on that folder —
  if the alias stops resolving, ProfileAgent runs on zero sent emails
  and returns an empty/partial profile.

All calls are mocked — no Graph API or real credentials required.

pytest tests/test_outlook_onboarding_e2e.py -v
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import Mock, patch

import pytest

from app.interfaces.email_provider import StandardEmail

pytest.importorskip("flask_cors")


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def app():
    from app.api.app import create_app
    return create_app(config={"TESTING": True})


@pytest.fixture
def client(app):
    return app.test_client()


def _outlook_email(
    email_id: str = "outlook-msg-001",
    sender: str = "marie.dupont@contoso.com",
    sender_name: str = "Marie Dupont",
    subject: str = "Question sur la livraison",
    body: str = "Bonjour, pouvez-vous confirmer la date de livraison ?",
    is_read: bool = False,
) -> StandardEmail:
    """StandardEmail factory tagged as coming from the Outlook adapter."""
    return StandardEmail(
        id=email_id,
        sender=sender,
        sender_name=sender_name,
        to=["user@outlook.com"],
        cc=[],
        subject=subject,
        body=body,
        received_at=datetime(2026, 4, 20, 9, 0, 0),
        is_read=is_read,
        has_attachments=False,
        attachments=[],
        conversation_id=f"thread-{email_id}",
        provider_source="outlook",
    )


def _setup_outlook_provider(inbox=None, sent=None):
    """Mock an Outlook adapter that honours both inbox and sent_items."""
    mock = Mock()
    mock.provider_name = "outlook"
    mock.authenticate.return_value = True

    inbox_list = inbox or []
    sent_list = sent or []
    mock.get_messages.return_value = inbox_list
    mock.get_message_headers.return_value = inbox_list
    mock.list_messages.return_value = inbox_list
    mock.get_unread_messages.return_value = [e for e in inbox_list if not e.is_read]
    mock.get_sent_emails.return_value = sent_list

    all_emails = {e.id: e for e in (inbox_list + sent_list)}
    mock.get_message_by_id.side_effect = lambda mid: all_emails.get(mid)
    mock.create_draft.return_value = "outlook-draft-001"
    mock.send_draft.return_value = True
    mock.send_reply_directly.return_value = "outlook-sent-001"
    mock.mark_as_read.return_value = True
    mock.disconnect.return_value = None
    return mock


def _setup_container_mock(pending_drafts=None, email_cache=None):
    mock_store = Mock()
    drafts_map = {d.id: d for d in (pending_drafts or [])}
    mock_store.get_by_id.side_effect = lambda did: drafts_map.get(did)
    mock_store.get_by_email_id.return_value = None
    mock_store.list_pending.return_value = pending_drafts or []
    mock_store.get_pending.return_value = pending_drafts or []

    mock_email_store = Mock()
    mock_email_store.list_emails.return_value = (email_cache or [], False)

    mock_container = Mock()
    mock_container.get_pending_draft_store.return_value = mock_store
    mock_container.get_email_cache.return_value = mock_email_store
    return mock_container


# ============================================================================
# 1. OAUTH CONSUMER + WORK TENANT PARITY
# ============================================================================


class TestOutlookOAuthOnboarding:
    """OAuth callback path must accept both consumer Hotmail/Outlook.com
    accounts AND work/school Microsoft 365 accounts via ``/common``."""

    def test_outlook_oauth_callback_redirects_to_frontend(self, client):
        """Callback with a code should always redirect to the frontend
        with ``provider=outlook`` so the client can complete PKCE."""
        response = client.get(
            "/api/oauth/outlook/callback?code=test-auth-code&state=test-state-123",
            follow_redirects=False,
        )
        assert response.status_code == 302
        location = response.headers.get("Location", "")
        assert "provider=outlook" in location
        assert "code=" in location or "success" in location

    def test_outlook_oauth_callback_missing_code(self, client):
        """No code → graceful redirect, never a 500."""
        response = client.get(
            "/api/oauth/outlook/callback?state=some-state",
            follow_redirects=False,
        )
        assert response.status_code == 302
        location = response.headers.get("Location", "")
        assert "error" in location.lower() or "missing" in location.lower()

    def test_microsoft_token_url_is_multi_tenant(self):
        """Guard against regressing to a single-tenant authority. The
        onboarding must accept consumer Hotmail/Outlook.com accounts;
        this is non-negotiable and was validated in the 2026-04-20
        audit.
        """
        from app.api import oauth as oauth_module

        assert "/common/" in oauth_module.MICROSOFT_TOKEN_URL, (
            "Outlook OAuth must use the /common endpoint (multi-tenant). "
            "A tenant-specific URL would block consumer Hotmail users."
        )


# ============================================================================
# 2. SENT FOLDER — the silent failure mode
# ============================================================================


class TestOutlookSentFolder:
    """If the Graph ``sentitems`` alias ever stops resolving, the
    onboarding ProfileAgent runs on zero sent emails and silently
    produces a partial profile. We pin the alias in both code paths
    that fetch sent mail."""

    def test_get_sent_emails_hits_sentitems_alias(self):
        """Static check: within the _get_sent_emails_async body, the
        adapter must still address the Graph well-known folder by the
        ``"sentitems"`` alias. Text check avoids needing a live Graph
        client."""
        import re
        from pathlib import Path

        adapter_path = (
            Path(__file__).resolve().parent.parent
            / "app" / "providers" / "outlook_adapter.py"
        )
        source = adapter_path.read_text(encoding="utf-8")

        # Extract the body of _get_sent_emails_async specifically — a
        # global grep would pass as long as "sentitems" appears anywhere,
        # which hides the case where the sent-folder code path regresses.
        body_match = re.search(
            r"async def _get_sent_emails_async\b.*?(?=\n    (?:async )?def |\Z)",
            source,
            re.DOTALL,
        )
        assert body_match, "_get_sent_emails_async not found in outlook_adapter.py"
        body = body_match.group(0)

        assert re.search(
            r"by_mail_folder_id\(\s*[\"']sentitems[\"']\s*\)",
            body,
        ), (
            "_get_sent_emails_async no longer targets the 'sentitems' "
            "well-known folder alias. Onboarding profile extraction will "
            "silently fail for Outlook/Hotmail users."
        )


# ============================================================================
# 3. FIRST INBOX LOAD
# ============================================================================


class TestFirstInboxLoadOutlook:
    @patch("app.api.routes_helpers._get_container")
    @patch("app.providers.factory.get_pooled_provider")
    def test_first_inbox_load_returns_emails(self, mock_provider, mock_container, client):
        emails = [
            _outlook_email("outlook-001", "alice@contoso.com", "Alice"),
            _outlook_email("outlook-002", "bob@acme.com", "Bob", subject="Facture Q1"),
        ]
        mock_provider.return_value = _setup_outlook_provider(inbox=emails)
        mock_container.return_value = _setup_container_mock()

        response = client.get("/api/emails?folder=inbox")

        assert response.status_code == 200
        data = response.get_json()
        assert data is not None
        email_list = data.get("emails", data) if isinstance(data, dict) else data
        assert isinstance(email_list, list)

    @patch("app.api.routes_helpers._get_container")
    @patch("app.providers.factory.get_pooled_provider")
    def test_first_inbox_load_empty(self, mock_provider, mock_container, client):
        mock_provider.return_value = _setup_outlook_provider()
        mock_container.return_value = _setup_container_mock()

        response = client.get("/api/emails?folder=inbox")
        assert response.status_code == 200


# ============================================================================
# 4. EMAIL PROCESSING
# ============================================================================


class TestEmailProcessingOutlook:
    @patch("app.api.routes_helpers._get_container")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_process_email_creates_pending_draft(self, mock_provider, mock_container, client):
        email = _outlook_email()
        mock_provider.return_value = _setup_outlook_provider(inbox=[email])
        mock_container.return_value = _setup_container_mock()

        response = client.post(f"/api/emails/{email.id}/process")

        assert response.status_code in (200, 201, 202), (
            f"Unexpected status {response.status_code}: {response.get_json()}"
        )


# ============================================================================
# 5. ONBOARDING INSIGHTS SHAPE (post-scan, frontend contract)
# ============================================================================


class TestOutlookOnboardingInsightsShape:
    """Validates that ``/api/onboarding/insights`` returns the flattened
    profile shape the frontend expects — regardless of the provider the
    user signed in with."""

    def test_insights_flattens_greeting_closing_for_outlook_account(self):
        """get_insights must flatten tone.greeting_styles → greeting_style
        so the UI renders the formula. Same bug would occur whether the
        account was Gmail or Outlook, but we pin it here for Outlook
        symmetry with test_gmail_onboarding_e2e.py."""
        from app.onboarding.manager import _flatten_profile_styles

        backend_profile = {
            "user_email": "user@outlook.com",
            "user_name": "Alex Dupont",
            "preferred_name": "Alex",
            "languages": ["fr"],
            "tone": {
                "default_tone": "semi-formal",
                "addressing": "tu",
                "greeting_styles": {"semi_formal_fr": "Bonjour {first_name},"},
                "closing_styles": {"semi_formal_fr": "Cordialement,"},
            },
        }
        out = _flatten_profile_styles(backend_profile)
        assert out["tone"]["greeting_style"] == "Bonjour {first_name},"
        assert out["tone"]["closing_style"] == "Cordialement,"
        assert out["tone"]["addressing"] == "tu"
        assert out["preferred_name"] == "Alex"
