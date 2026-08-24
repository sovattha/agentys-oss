# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests du blueprint /api/tts (proxy ElevenLabs)."""

from __future__ import annotations

import io
from unittest.mock import patch

import pytest
from flask import Flask

from app.adapters.elevenlabs_adapter import ElevenLabsError, Voice
from app.api import tts as tts_module


@pytest.fixture(autouse=True)
def _isolate_cache(tmp_path, monkeypatch):
    """Isole le cache TTS dans tmp_path pour chaque test."""
    from app.infrastructure import tts_cache as cache_mod

    monkeypatch.setattr(cache_mod, "TTS_CACHE_DIR", tmp_path / "tts_cache")
    monkeypatch.setattr(cache_mod, "_DB_PATH", tmp_path / "tts_cache" / "tts_cache.db")
    monkeypatch.setattr(cache_mod, "_schema_ready", False)
    yield


@pytest.fixture(autouse=True)
def _reset_voices_cache():
    tts_module._voices_cache["voices"] = None
    tts_module._voices_cache["fetched_at"] = 0.0
    yield


@pytest.fixture(autouse=True)
def _fake_api_key(monkeypatch):
    """Un ELEVENLABS_API_KEY est requis par le constructeur de l'adapter."""
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key-xxxxx")


@pytest.fixture
def app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(tts_module.tts_bp, url_prefix="/api/tts")
    return app


@pytest.fixture
def client(app):
    return app.test_client()


class TestSpeak:
    def test_speak_requires_text(self, client):
        resp = client.post("/api/tts/speak", json={"voice_id": "v1"})
        assert resp.status_code == 400
        assert "text" in (resp.get_json() or {}).get("error", "").lower()

    def test_speak_requires_voice_id(self, client):
        resp = client.post("/api/tts/speak", json={"text": "hello"})
        assert resp.status_code == 400
        assert "voice_id" in (resp.get_json() or {}).get("error", "").lower()

    @patch("app.api.tts.ElevenLabsAdapter")
    def test_speak_cache_miss_calls_elevenlabs_and_stores(self, adapter_cls, client):
        fake = adapter_cls.return_value
        fake.synthesize.return_value = b"ID3" + b"\x00" * 500  # fake MP3 > 200 bytes

        resp = client.post(
            "/api/tts/speak",
            json={"text": "Bonjour test", "voice_id": "voice-abc", "clean": False},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["cached"] is False
        assert body["audio_url"].startswith("/api/tts/audio/")
        assert body["audio_url"].endswith(".mp3")
        assert body["chars"] == len("Bonjour test")
        fake.synthesize.assert_called_once()

    @patch("app.api.tts.ElevenLabsAdapter")
    def test_speak_cache_hit_skips_elevenlabs(self, adapter_cls, client):
        fake = adapter_cls.return_value
        fake.synthesize.return_value = b"ID3" + b"\x00" * 500

        # 1er call : miss
        r1 = client.post(
            "/api/tts/speak",
            json={"text": "Hello world", "voice_id": "voice-xyz", "clean": False},
        )
        assert r1.status_code == 200
        assert r1.get_json()["cached"] is False

        # 2e call identique : hit (synthesize PAS rappelé)
        r2 = client.post(
            "/api/tts/speak",
            json={"text": "Hello world", "voice_id": "voice-xyz", "clean": False},
        )
        assert r2.status_code == 200
        assert r2.get_json()["cached"] is True
        assert r2.get_json()["audio_url"] == r1.get_json()["audio_url"]
        assert fake.synthesize.call_count == 1

    @patch("app.api.tts.ElevenLabsAdapter")
    def test_speak_maps_elevenlabs_error(self, adapter_cls, client):
        fake = adapter_cls.return_value
        fake.synthesize.side_effect = ElevenLabsError("quota dépassé", status_code=429)

        resp = client.post(
            "/api/tts/speak",
            json={"text": "hello", "voice_id": "v1", "clean": False},
        )
        assert resp.status_code == 429
        assert "quota" in resp.get_json()["error"]

    @patch("app.api.tts.ElevenLabsAdapter")
    def test_speak_truncates_long_text(self, adapter_cls, client):
        fake = adapter_cls.return_value
        fake.synthesize.return_value = b"ID3" + b"\x00" * 500

        long_text = "Phrase. " * 500  # >2500 chars
        resp = client.post(
            "/api/tts/speak",
            json={"text": long_text, "voice_id": "v1", "clean": False},
        )
        assert resp.status_code == 200
        # Vérifier que synthesize a reçu du texte tronqué
        call_args = fake.synthesize.call_args
        sent_text = call_args.args[0] if call_args.args else call_args.kwargs.get("text")
        assert len(sent_text) <= 2600  # 2500 + suffixe " (…)"


class TestServeAudio:
    def test_serve_rejects_bad_hash(self, client):
        resp = client.get("/api/tts/audio/notahash.mp3")
        assert resp.status_code == 400

    def test_serve_rejects_wrong_extension(self, client):
        # route catches path:hash_filename, so we check .mp3 requirement
        resp_mp3 = client.get("/api/tts/audio/" + "a" * 64 + ".wav")
        assert resp_mp3.status_code == 400

    def test_serve_returns_404_for_unknown(self, client):
        resp = client.get("/api/tts/audio/" + "a" * 64 + ".mp3")
        assert resp.status_code == 404

    @patch("app.api.tts.ElevenLabsAdapter")
    def test_serve_returns_mp3_after_synth(self, adapter_cls, client):
        fake_bytes = b"ID3" + b"\x00" * 500
        fake = adapter_cls.return_value
        fake.synthesize.return_value = fake_bytes

        post = client.post(
            "/api/tts/speak",
            json={"text": "hi", "voice_id": "v1", "clean": False},
        )
        audio_url = post.get_json()["audio_url"]
        resp = client.get(audio_url)
        assert resp.status_code == 200
        assert resp.mimetype == "audio/mpeg"
        assert resp.data == fake_bytes


class TestListVoices:
    @patch("app.api.tts.ElevenLabsAdapter")
    def test_list_voices_success(self, adapter_cls, client):
        fake = adapter_cls.return_value
        fake.list_voices.return_value = [
            Voice(
                voice_id="v1",
                name="Rachel",
                category="premade",
                preview_url="https://x/rachel.mp3",
                labels={"accent": "american"},
                language=None,
            ),
            Voice(
                voice_id="v2",
                name="Ma Voix",
                category="cloned",
                preview_url=None,
                labels=None,
                language="fr",
            ),
        ]
        resp = client.get("/api/tts/voices")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["voices"]) == 2
        assert data["voices"][0]["name"] == "Rachel"
        assert data["voices"][1]["category"] == "cloned"

    @patch("app.api.tts.ElevenLabsAdapter")
    def test_list_voices_uses_cache(self, adapter_cls, client):
        fake = adapter_cls.return_value
        fake.list_voices.return_value = []
        client.get("/api/tts/voices")
        client.get("/api/tts/voices")
        assert fake.list_voices.call_count == 1


class TestClone:
    def test_clone_requires_name(self, client):
        data = {
            "files": (io.BytesIO(b"\x00\x00\x00\x00"), "s.m4a", "audio/m4a"),
        }
        resp = client.post(
            "/api/tts/clone", data=data, content_type="multipart/form-data"
        )
        assert resp.status_code == 400

    def test_clone_requires_files(self, client):
        resp = client.post(
            "/api/tts/clone",
            data={"name": "Alex"},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400

    def test_clone_rejects_non_audio_mime(self, client):
        data = {
            "name": "Alex",
            "files": (io.BytesIO(b"\x00\x00\x00\x00"), "s.txt", "text/plain"),
        }
        resp = client.post(
            "/api/tts/clone", data=data, content_type="multipart/form-data"
        )
        assert resp.status_code == 400

    @patch("app.api.tts.ElevenLabsAdapter")
    def test_clone_happy_path(self, adapter_cls, client):
        fake = adapter_cls.return_value
        fake.clone_voice.return_value = "new-voice-123"
        data = {
            "name": "Alex",
            "description": "Ma voix personnelle",
            "files": (
                io.BytesIO(b"\x00" * 1024),
                "sample.m4a",
                "audio/m4a",
            ),
        }
        resp = client.post(
            "/api/tts/clone", data=data, content_type="multipart/form-data"
        )
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["voice_id"] == "new-voice-123"
        assert body["name"] == "Alex"
        fake.clone_voice.assert_called_once()


class TestDeleteVoice:
    @patch("app.api.tts.ElevenLabsAdapter")
    def test_delete_happy(self, adapter_cls, client):
        fake = adapter_cls.return_value
        fake.delete_voice.return_value = None
        resp = client.delete("/api/tts/voices/voice-abc-123")
        assert resp.status_code == 204
        fake.delete_voice.assert_called_once_with("voice-abc-123")

    def test_delete_rejects_invalid_id(self, client):
        resp = client.delete("/api/tts/voices/../etc/passwd")
        assert resp.status_code in (400, 404)  # 404 si le router ne matche pas
