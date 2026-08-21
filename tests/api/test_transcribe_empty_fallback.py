# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Fallback Whisper quand Deepgram renvoie un transcript VIDE sur un audio réel.

Cas de prod (2026-06-11 16:26:27) : dictée de 23 s / 88 KB en français, badge
langue resté sur « En » → Deepgram nova-3 épinglé `language=en` répond 200 avec
0 caractère → le backend renvoyait `{"text": ""}` tel quel (le fallback OpenAI
ne se déclenchait que sur exception) → rien n'apparaît dans l'éditeur, en
silence. Contrat verrouillé ici :

  - transcript vide + audio substantiel (>= 2 s) + OpenAI configuré
      → retry via Whisper SANS épingler la langue (auto-détection),
        usage crédité au provider réellement utilisé (openai) ;
  - transcript vide + audio court (< 2 s : vrai silence / mis-tap)
      → texte vide direct, AUCUN appel OpenAI ;
  - transcript vide + audio substantiel mais PAS d'OPENAI_API_KEY
      → texte vide direct (pas de 503) ;
  - transcript non vide → comportement inchangé (pas de fallback).
"""

from __future__ import annotations

import io
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def app_client(monkeypatch):
    """Client Flask isolé (même recette que test_2026_04_25_core_features)."""
    monkeypatch.setenv("FLASK_ENV", "testing")
    from cryptography.fernet import Fernet
    monkeypatch.setenv("OAUTH_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    from app.api.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def _post_audio(client, *, duration_seconds: str, audio_bytes: bytes = b"\x00" * 4096):
    data = {
        "audio": (io.BytesIO(audio_bytes), "dictation.webm"),
        "lang": "en",
    }
    if duration_seconds:
        data["duration_seconds"] = duration_seconds
    return client.post(
        "/api/transcribe",
        data=data,
        content_type="multipart/form-data",
        # Loopback = bypass auth (on teste le fallback, pas l'auth).
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )


def _openai_client_returning(text: str) -> MagicMock:
    client = MagicMock()
    client.audio.transcriptions.create.return_value = SimpleNamespace(text=text)
    return client


class TestEmptyTranscriptFallback:
    def test_empty_deepgram_substantial_audio_falls_back_to_whisper_autodetect(
        self, app_client, monkeypatch,
    ):
        monkeypatch.setenv("DEEPGRAM_API_KEY", "dg_test")
        monkeypatch.setenv("OPENAI_API_KEY", "sk_test")
        from app.api import routes_misc

        oai = _openai_client_returning("Bonjour, voici ma dictée en français.")
        usage_calls = []
        with patch.object(routes_misc, "_call_deepgram", return_value="") as dg, \
             patch.object(routes_misc, "_get_openai_client", return_value=oai), \
             patch.object(routes_misc, "_record_dictation_usage",
                          side_effect=lambda aid, provider, dur: usage_calls.append(provider)):
            resp = _post_audio(app_client, duration_seconds="23")

        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert resp.get_json()["text"] == "Bonjour, voici ma dictée en français."
        assert dg.called
        # Le retry Whisper ne doit PAS ré-épingler la langue erronée : pas de
        # kwarg `language` → auto-détection (c'est elle qui sauve le français).
        _, kwargs = oai.audio.transcriptions.create.call_args
        assert "language" not in kwargs, kwargs
        # Usage crédité au provider qui a réellement transcrit.
        assert usage_calls == ["openai"]

    def test_empty_deepgram_short_audio_returns_empty_without_openai_call(
        self, app_client, monkeypatch,
    ):
        monkeypatch.setenv("DEEPGRAM_API_KEY", "dg_test")
        monkeypatch.setenv("OPENAI_API_KEY", "sk_test")
        from app.api import routes_misc

        oai = _openai_client_returning("ne doit pas être appelé")
        with patch.object(routes_misc, "_call_deepgram", return_value=""), \
             patch.object(routes_misc, "_get_openai_client", return_value=oai), \
             patch.object(routes_misc, "_record_dictation_usage"):
            resp = _post_audio(app_client, duration_seconds="1")

        assert resp.status_code == 200
        assert resp.get_json()["text"] == ""
        assert not oai.audio.transcriptions.create.called

    def test_empty_deepgram_without_openai_key_returns_empty_not_503(
        self, app_client, monkeypatch,
    ):
        monkeypatch.setenv("DEEPGRAM_API_KEY", "dg_test")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from app.api import routes_misc

        with patch.object(routes_misc, "_call_deepgram", return_value=""), \
             patch.object(routes_misc, "_record_dictation_usage"):
            resp = _post_audio(app_client, duration_seconds="23")

        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert resp.get_json()["text"] == ""

    def test_boundary_two_seconds_triggers_fallback(self, app_client, monkeypatch):
        # Le contrat est « >= 2 s » : la borne exacte doit déclencher le retry.
        monkeypatch.setenv("DEEPGRAM_API_KEY", "dg_test")
        monkeypatch.setenv("OPENAI_API_KEY", "sk_test")
        from app.api import routes_misc

        oai = _openai_client_returning("borne deux secondes")
        with patch.object(routes_misc, "_call_deepgram", return_value=""), \
             patch.object(routes_misc, "_get_openai_client", return_value=oai), \
             patch.object(routes_misc, "_record_dictation_usage"):
            resp = _post_audio(app_client, duration_seconds="2")

        assert resp.status_code == 200
        assert resp.get_json()["text"] == "borne deux secondes"

    def test_missing_duration_with_big_blob_uses_size_proxy(self, app_client, monkeypatch):
        # Le client mobile n'envoie pas duration_seconds : un blob substantiel
        # (>= 16 KB) doit suffire à déclencher le retry.
        monkeypatch.setenv("DEEPGRAM_API_KEY", "dg_test")
        monkeypatch.setenv("OPENAI_API_KEY", "sk_test")
        from app.api import routes_misc

        oai = _openai_client_returning("dictée mobile sans durée")
        with patch.object(routes_misc, "_call_deepgram", return_value=""), \
             patch.object(routes_misc, "_get_openai_client", return_value=oai), \
             patch.object(routes_misc, "_record_dictation_usage"):
            resp = _post_audio(
                app_client, duration_seconds="", audio_bytes=b"\x00" * (100 * 1024),
            )

        assert resp.status_code == 200
        assert resp.get_json()["text"] == "dictée mobile sans durée"

    def test_missing_duration_with_small_blob_no_fallback(self, app_client, monkeypatch):
        monkeypatch.setenv("DEEPGRAM_API_KEY", "dg_test")
        monkeypatch.setenv("OPENAI_API_KEY", "sk_test")
        from app.api import routes_misc

        oai = _openai_client_returning("ne doit pas être appelé")
        with patch.object(routes_misc, "_call_deepgram", return_value=""), \
             patch.object(routes_misc, "_get_openai_client", return_value=oai), \
             patch.object(routes_misc, "_record_dictation_usage"):
            resp = _post_audio(app_client, duration_seconds="")

        assert resp.status_code == 200
        assert resp.get_json()["text"] == ""
        assert not oai.audio.transcriptions.create.called

    def test_whisper_failure_after_empty_retry_returns_empty_not_500(
        self, app_client, monkeypatch,
    ):
        # Si le retry Whisper échoue, on rend le contrat d'avant ({"text": ""})
        # — un 500 relancerait les retries silencieux du frontend.
        monkeypatch.setenv("DEEPGRAM_API_KEY", "dg_test")
        monkeypatch.setenv("OPENAI_API_KEY", "sk_test")
        from app.api import routes_misc

        oai = MagicMock()
        oai.audio.transcriptions.create.side_effect = RuntimeError("whisper down")
        with patch.object(routes_misc, "_call_deepgram", return_value=""), \
             patch.object(routes_misc, "_get_openai_client", return_value=oai), \
             patch.object(routes_misc, "_record_dictation_usage"):
            resp = _post_audio(app_client, duration_seconds="23")

        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert resp.get_json()["text"] == ""

    def test_non_empty_deepgram_unchanged_no_fallback(self, app_client, monkeypatch):
        monkeypatch.setenv("DEEPGRAM_API_KEY", "dg_test")
        monkeypatch.setenv("OPENAI_API_KEY", "sk_test")
        from app.api import routes_misc

        oai = _openai_client_returning("ne doit pas être appelé")
        usage_calls = []
        with patch.object(routes_misc, "_call_deepgram", return_value="Hello there"), \
             patch.object(routes_misc, "_get_openai_client", return_value=oai), \
             patch.object(routes_misc, "_record_dictation_usage",
                          side_effect=lambda aid, provider, dur: usage_calls.append(provider)):
            resp = _post_audio(app_client, duration_seconds="23")

        assert resp.status_code == 200
        assert resp.get_json()["text"] == "Hello there"
        assert not oai.audio.transcriptions.create.called
        assert usage_calls == ["deepgram"]
