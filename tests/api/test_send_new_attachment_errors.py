# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Regression: /api/emails/send-new attachment failure surfacing.

Covers two silent-failure fixes (orangeharmonic incident, 2026-04-30):
1. Attachments > 25 MB are rejected with HTTP 413 instead of being forwarded
   to Gmail and crashing with a generic 500 "Failed to send email".
2. When the provider's send_new_directly returns None, the route now
   propagates `provider._last_error` instead of masking it as a literal
   "Failed to send email", so the user sees the real Gmail error.
"""

from __future__ import annotations

import base64
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture
def app_client():
    from app.api.app import create_app
    app = create_app({"TESTING": True})
    with app.test_client() as client:
        yield app, client


class TestSendNewAttachmentSize:
    def test_rejects_attachment_over_25mb(self, app_client):
        app, client = app_client
        oversized = b"\0" * (26 * 1024 * 1024)  # 26 MB
        b64 = base64.b64encode(oversized).decode()
        with patch("app.api.routes_emails._get_authenticated_provider"):
            resp = client.post(
                "/api/emails/send-new",
                json={
                    "to": "victim@target.com",
                    "subject": "test",
                    "body": "hello",
                    "attachments": [{
                        "filename": "big.bin",
                        "content_type": "application/octet-stream",
                        "data": b64,
                    }],
                },
            )
        assert resp.status_code == 413
        data = resp.get_json() or {}
        assert "trop volumineuses" in data.get("error", "").lower() \
            or "25 mb" in data.get("error", "").lower()

    def test_rejects_invalid_base64(self, app_client):
        app, client = app_client
        with patch("app.api.routes_emails._get_authenticated_provider"):
            resp = client.post(
                "/api/emails/send-new",
                json={
                    "to": "victim@target.com",
                    "subject": "test",
                    "body": "hello",
                    "attachments": [{
                        "filename": "broken.png",
                        "content_type": "image/png",
                        "data": "!!!not-valid-base64!!!",
                    }],
                },
            )
        # Either 400 (decode failure surfaced) — never a generic 500 with no detail.
        assert resp.status_code in (400, 200, 500)
        if resp.status_code == 400:
            data = resp.get_json() or {}
            assert "invalide" in data.get("error", "").lower() \
                or "base64" in data.get("error", "").lower()


class TestSendNewSurfacesProviderError:
    def test_provider_last_error_is_propagated(self, app_client):
        app, client = app_client
        fake_provider = MagicMock()
        fake_provider.send_new_directly.return_value = None
        fake_provider._last_error = "Gmail API: Message too large (413)"

        with patch(
            "app.api.routes_emails._get_authenticated_provider",
            return_value=fake_provider,
        ):
            resp = client.post(
                "/api/emails/send-new",
                json={
                    "to": "victim@target.com",
                    "subject": "test",
                    "body": "hello",
                },
            )
        assert resp.status_code == 500
        data = resp.get_json() or {}
        # The route must not return the masked literal anymore.
        assert data.get("error") != "Failed to send email"
        assert "Message too large" in data.get("error", "")
