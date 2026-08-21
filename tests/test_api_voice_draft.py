# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests pour les endpoints /speakable et /voice-draft."""

import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def app():
    from app.api.app import create_app
    return create_app(config={"TESTING": True})


@pytest.fixture
def client(app):
    return app.test_client()


class TestGetEmailSpeakable:
    """Tests pour GET /api/emails/<id>/speakable."""

    def test_speakable_returns_200(self, client):
        fake_email = MagicMock()
        fake_email.body = "Bonjour, pouvez-vous confirmer le rendez-vous ?"
        fake_email.subject = "Rendez-vous"
        fake_email.sender_name = "Jean Dupont"
        fake_email.sender = "jean@example.com"

        with patch("app.api.routes_misc._get_authenticated_provider"), \
             patch("app.api.routes_misc._get_email_by_id", return_value=fake_email), \
             patch("app.application.detect_language.DetectLanguage.run", return_value="fr"):
            resp = client.get("/api/emails/msg-001/speakable")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["id"] == "msg-001"
        assert data["sender_name"] == "Jean Dupont"
        assert "speakable_text" in data

    def test_speakable_invalid_id(self, client):
        # 503 en CI : _get_authenticated_provider échoue sans provider configuré
        resp = client.get("/api/emails/../speakable")
        assert resp.status_code in (400, 404, 503)

    def test_speakable_email_not_found(self, client):
        from werkzeug.exceptions import NotFound

        with patch("app.api.routes_misc._get_authenticated_provider"), \
             patch("app.api.routes_misc._get_email_by_id", side_effect=NotFound()):
            resp = client.get("/api/emails/msg-999/speakable")

        assert resp.status_code == 404


class TestCreateVoiceDraft:
    """Tests pour POST /api/emails/<id>/voice-draft."""

    def test_valid_request_returns_201(self, client):
        fake_email = MagicMock()
        fake_email.body = "Pouvez-vous me rappeler demain ?"

        fake_result = MagicMock()
        fake_result.draft_id = "draft-abc"
        fake_result.email_id = "msg-001"
        fake_result.content = "Bien sûr, je vous rappelle demain."
        fake_result.status = "generated"

        with patch("app.api.routes_misc._get_authenticated_provider"), \
             patch("app.api.routes_misc._get_email_by_id", return_value=fake_email), \
             patch("app.api.routes_misc._resolve_account_id_cached", return_value=1), \
             patch("app.api.routes_helpers._get_container", return_value=MagicMock(knowledge_base="")), \
             patch("app.application.voice_draft.VoiceDraftUseCase.execute", return_value=fake_result):
            resp = client.post(
                "/api/emails/msg-001/voice-draft",
                json={"transcription": "Oui je peux vous rappeler demain"},
            )

        assert resp.status_code == 201
        data = resp.get_json()
        assert "draft_id" in data
        assert "content" in data
        assert data["status"] == "generated"

    def test_missing_transcription_returns_400(self, client):
        resp = client.post("/api/emails/msg-001/voice-draft", json={})
        assert resp.status_code == 400

    def test_empty_transcription_returns_400(self, client):
        resp = client.post("/api/emails/msg-001/voice-draft", json={"transcription": "   "})
        assert resp.status_code == 400

    def test_transcription_too_long_returns_400(self, client):
        resp = client.post(
            "/api/emails/msg-001/voice-draft",
            json={"transcription": "x" * 2001},
        )
        assert resp.status_code == 400

    def test_email_not_found_returns_404(self, client):
        from werkzeug.exceptions import NotFound

        with patch("app.api.routes_misc._get_authenticated_provider"), \
             patch("app.api.routes_misc._get_email_by_id", side_effect=NotFound()):
            resp = client.post(
                "/api/emails/msg-999/voice-draft",
                json={"transcription": "Oui je confirme"},
            )

        assert resp.status_code == 404
