# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour POST /api/emails/send-new — envoi pièce jointe + visibilité immédiate dans Envoyés.

pytest tests/test_send_new_email_e2e.py -v
"""

import base64
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def app():
    from app.api.app import create_app
    return create_app(config={"TESTING": True})


@pytest.fixture
def client(app):
    return app.test_client()


def _make_mock_provider(send_return=True):
    mock = MagicMock()
    mock.authenticate.return_value = True
    mock.send_new_directly.return_value = "msg-id-123" if send_return else None
    mock._email = "me@example.com"
    mock._account_id = "acc-1"
    return mock


# ---------------------------------------------------------------------------
# Test 1 : la pièce jointe est bien transmise au provider
# ---------------------------------------------------------------------------

def test_send_new_email_with_attachment_passes_to_provider(client):
    """Vérifie que la pièce jointe est transmise au provider avec le bon format."""
    pdf_data = base64.b64encode(b"fake-pdf-content").decode()
    payload = {
        "to": "karine.morel@gmail.com",
        "subject": "Test PJ",
        "body": "Bonjour",
        "attachments": [{"filename": "doc.pdf", "data": pdf_data, "content_type": "application/pdf"}],
    }
    mock_provider = _make_mock_provider()

    with patch("app.api.routes_emails._get_authenticated_provider", return_value=mock_provider), \
         patch("app.api.routes_emails._resolve_account_id_cached", return_value=1), \
         patch("app.api.routes_helpers.get_db_session"), \
         patch("app.api.routes_emails._invalidate_folder_cache"), \
         patch("app.api.routes_helpers.submit_background"), \
         patch("app.api.routes_emails._refresh_sent_cache_bg"):

        r = client.post("/api/emails/send-new", json=payload)

    assert r.status_code == 200
    data = r.get_json()
    assert data.get("success") is True

    assert mock_provider.send_new_directly.called
    kwargs = mock_provider.send_new_directly.call_args.kwargs
    attachments = kwargs.get("attachments")
    assert attachments is not None and len(attachments) == 1
    filename, file_bytes, content_type = attachments[0]
    assert filename == "doc.pdf"
    assert file_bytes == b"fake-pdf-content"
    assert content_type == "application/pdf"


# ---------------------------------------------------------------------------
# Test 2 : envoi sans pièce jointe fonctionne toujours
# ---------------------------------------------------------------------------

def test_send_new_email_without_attachment(client):
    """Vérifie qu'un envoi sans pièce jointe réussit normalement."""
    payload = {
        "to": "bob@example.com",
        "subject": "Bonjour",
        "body": "Corps du message",
    }
    mock_provider = _make_mock_provider()

    with patch("app.api.routes_emails._get_authenticated_provider", return_value=mock_provider), \
         patch("app.api.routes_emails._resolve_account_id_cached", return_value=1), \
         patch("app.api.routes_helpers.get_db_session"), \
         patch("app.api.routes_emails._invalidate_folder_cache"), \
         patch("app.api.routes_helpers.submit_background"), \
         patch("app.api.routes_emails._refresh_sent_cache_bg"):

        r = client.post("/api/emails/send-new", json=payload)

    assert r.status_code == 200
    kwargs = mock_provider.send_new_directly.call_args.kwargs
    assert kwargs.get("attachments") is None


# ---------------------------------------------------------------------------
# Test 3 : SQLite insert + invalidation sont synchrones (avant la réponse HTTP)
# ---------------------------------------------------------------------------

def test_sent_email_inserted_in_sqlite_synchronously(client):
    """Vérifie que l'insert SQLite et l'invalidation du cache se font dans le thread principal."""
    payload = {
        "to": "karine.morel@gmail.com",
        "subject": "Sync test",
        "body": "Corps",
    }
    mock_provider = _make_mock_provider()
    invalidate_calls = []

    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    def track_invalidate(folder):
        invalidate_calls.append(folder)

    with patch("app.api.routes_emails._get_authenticated_provider", return_value=mock_provider), \
         patch("app.api.routes_emails._resolve_account_id_cached", return_value=1), \
         patch("app.api.routes_helpers.get_db_session", return_value=mock_session), \
         patch("app.api.routes_helpers.EmailRepository"), \
         patch("app.api.routes_emails.Email"), \
         patch("app.api.routes_emails._invalidate_folder_cache", side_effect=track_invalidate), \
         patch("app.api.routes_helpers.submit_background"), \
         patch("app.api.routes_emails._refresh_sent_cache_bg"):

        r = client.post("/api/emails/send-new", json=payload)

    assert r.status_code == 200
    # L'invalidation doit avoir eu lieu (synchrone, avant la réponse)
    assert "sent" in invalidate_calls, "Le cache 'sent' doit être invalidé avant la réponse HTTP"


def test_send_new_email_uses_client_send_id_for_sent_cache(client):
    """Le cache Envoyés doit utiliser l'ID synthétique ouvert par le frontend."""
    payload = {
        "to": "karine.morel@gmail.com",
        "subject": "Client ID test",
        "body": "Corps",
        "client_send_id": "compose-client-123",
    }
    mock_provider = _make_mock_provider()

    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    with patch("app.api.routes_emails._get_authenticated_provider", return_value=mock_provider), \
         patch("app.api.routes_emails._resolve_account_id_cached", return_value=1), \
         patch("app.api.routes_helpers.get_db_session", return_value=mock_session), \
         patch("app.api.routes_helpers.EmailRepository"), \
         patch("app.api.routes_emails.Email") as email_model, \
         patch("app.api.routes_emails._invalidate_folder_cache"), \
         patch("app.api.routes_helpers.submit_background"), \
         patch("app.api.routes_emails._refresh_sent_cache_bg"):

        r = client.post("/api/emails/send-new", json=payload)

    assert r.status_code == 200
    assert email_model.call_args.kwargs["email_id"] == "compose-client-123"
