"""Tests for the contact avatar API route."""
from __future__ import annotations

from flask import Flask
import pytest


@pytest.fixture
def client(monkeypatch):
    from app.api.routes_helpers import api_bp
    from app.api import routes_contacts

    monkeypatch.setattr(routes_contacts, "_resolve_account_id_cached", lambda: 7)
    monkeypatch.setattr(
        routes_contacts._rh,
        "_get_authenticated_provider",
        lambda: object(),
    )
    monkeypatch.setattr(
        "app.services.oauth_scope_check.has_contacts_scope",
        lambda provider, account_id: True,
    )

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(api_bp, url_prefix="/api")
    return app.test_client()


def test_avatar_no_photo_returns_204_without_error_status(client, monkeypatch):
    monkeypatch.setattr(
        "app.services.contact_avatar_service.get_contact_avatar",
        lambda provider, email, account_id: None,
    )

    resp = client.get("/api/contacts/avatar?email=reply%40news.mondovino.ch")

    assert resp.status_code == 204
    assert resp.data == b""
    assert resp.headers["Cache-Control"] == "public, max-age=3600"


def test_avatar_success_returns_image_bytes(client, monkeypatch):
    monkeypatch.setattr(
        "app.services.contact_avatar_service.get_contact_avatar",
        lambda provider, email, account_id: (b"png-bytes", "image/png"),
    )

    resp = client.get("/api/contacts/avatar?email=alice%40example.com")

    assert resp.status_code == 200
    assert resp.data == b"png-bytes"
    assert resp.content_type == "image/png"


def test_avatar_invalid_email_is_empty_not_network_error(client):
    resp = client.get("/api/contacts/avatar?email=not-an-email")

    assert resp.status_code == 204
    assert resp.data == b""


def test_avatar_status_hides_gmail_reconnect_cta(client, monkeypatch):
    from app.api import routes_contacts

    class GmailProvider:
        provider_name = "gmail"

    monkeypatch.setattr(
        routes_contacts._rh,
        "_get_authenticated_provider",
        lambda: GmailProvider(),
    )

    def fail_if_called(provider, account_id):
        raise AssertionError("Gmail contact scopes should not be probed")

    monkeypatch.setattr(
        "app.services.oauth_scope_check.has_contacts_scope",
        fail_if_called,
    )

    resp = client.get("/api/contacts/avatar-status")

    assert resp.status_code == 200
    assert resp.json == {
        "granted": False,
        "provider": "",
        "reason": "gmail_contact_scopes_not_requested",
    }
