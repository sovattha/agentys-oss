# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests du proxy streaming STT (app/api/stt_stream.py).

Le proxy relaie des frames PCM16 du mobile vers Deepgram live et renvoie
les transcripts au fil de l'eau. On teste les parties pures (URL builder,
parseur de messages Deepgram, registry/caps) et le cycle de vie du reader
thread avec un faux WS — aucun réseau réel.

Run: pytest tests/test_stt_stream.py -v
"""

from __future__ import annotations

import json
import threading
import time

from app.api.stt_stream import (
    INACTIVITY_TIMEOUT_SECONDS,
    MAX_STREAMS_GLOBAL,
    MAX_STREAMS_PER_ACCOUNT,
    StreamRegistry,
    StreamState,
    _reader_loop,
    build_deepgram_url,
    parse_deepgram_message,
)


# --------------------------------------------------------------------------- #
# build_deepgram_url
# --------------------------------------------------------------------------- #


class TestBuildDeepgramUrl:
    def test_base_params(self):
        url = build_deepgram_url("fr", 16000, 300, 1000)
        assert url.startswith("wss://api.deepgram.com/v1/listen?")
        assert "model=nova-3" in url
        assert "encoding=linear16" in url
        assert "sample_rate=16000" in url
        assert "interim_results=true" in url
        assert "vad_events=true" in url
        assert "endpointing=300" in url
        assert "utterance_end_ms=1000" in url
        assert "language=fr" in url

    def test_no_lang_defaults_to_multi(self):
        # Deepgram live n'a PAS d'auto-détection : sans `language`, il décode en
        # anglais. On envoie donc toujours `language`, "multi" par défaut.
        url = build_deepgram_url(None, 16000, 300, 1000)
        assert "language=multi" in url

    def test_explicit_lang_overrides_multi(self):
        url = build_deepgram_url("fr", 16000, 300, 1000)
        assert "language=fr" in url
        assert "language=multi" not in url

    def test_keyterms_capped_by_char_budget(self):
        # 60 termes de 20 chars = 1200 chars > budget 400 → tronqué bien avant 50.
        terms = [f"term-{i:03d}-padded-xx" for i in range(60)] + ["", "  "]
        url = build_deepgram_url("en", 16000, 300, 1000, keyterms=terms)
        count = url.count("keyterm=")
        assert 0 < count < 50  # budget caractères mord avant le cap de 50

    def test_keyterms_url_encoded(self):
        url = build_deepgram_url("fr", 16000, 300, 1000, keyterms=["RAG status"])
        assert "keyterm=RAG+status" in url


# --------------------------------------------------------------------------- #
# parse_deepgram_message
# --------------------------------------------------------------------------- #


def _dg_results(text: str, is_final: bool, speech_final: bool = False) -> str:
    return json.dumps({
        "type": "Results",
        "is_final": is_final,
        "speech_final": speech_final,
        "channel": {"alternatives": [{"transcript": text, "confidence": 0.98}]},
    })


class TestParseDeepgramMessage:
    def test_interim_transcript(self):
        events = parse_deepgram_message(_dg_results("bonjour je", is_final=False))
        assert events == [("stt_partial", {"text": "bonjour je"})]

    def test_final_segment(self):
        events = parse_deepgram_message(
            _dg_results("bonjour je serai là", is_final=True, speech_final=True)
        )
        assert events == [("stt_final", {"text": "bonjour je serai là", "speech_final": True})]

    def test_final_without_speech_final(self):
        events = parse_deepgram_message(_dg_results("segment", is_final=True))
        assert events == [("stt_final", {"text": "segment", "speech_final": False})]

    def test_empty_interim_is_noise(self):
        assert parse_deepgram_message(_dg_results("", is_final=False)) == []

    def test_empty_final_with_speech_final_propagates(self):
        """Un final vide portant speech_final doit résoudre le tour mobile."""
        events = parse_deepgram_message(_dg_results("", is_final=True, speech_final=True))
        assert events == [("stt_final", {"text": "", "speech_final": True})]

    def test_speech_started_event(self):
        events = parse_deepgram_message(json.dumps({"type": "SpeechStarted"}))
        assert events == [("stt_speech_started", {})]

    def test_utterance_end_event(self):
        events = parse_deepgram_message(json.dumps({"type": "UtteranceEnd"}))
        assert events == [("stt_utterance_end", {})]

    def test_metadata_ignored(self):
        assert parse_deepgram_message(json.dumps({"type": "Metadata"})) == []

    def test_garbage_ignored(self):
        assert parse_deepgram_message("not json {{{") == []
        assert parse_deepgram_message(json.dumps([1, 2])) == []
        assert parse_deepgram_message(json.dumps({"type": "Results"})) == []


# --------------------------------------------------------------------------- #
# StreamRegistry — caps
# --------------------------------------------------------------------------- #


def _stream(sid: str, account_id=None) -> StreamState:
    return StreamState(sid=sid, account_id=account_id, user_id=None, sample_rate=16000)


class TestStreamRegistry:
    def test_reserve_is_atomic_insert(self):
        reg = StreamRegistry()
        ok, _ = reg.try_reserve(_stream("sid1"))
        assert ok
        # déjà réservé → refus
        ok, reason = reg.try_reserve(_stream("sid1"))
        assert not ok and reason == "already_streaming"

    def test_per_account_cap(self):
        reg = StreamRegistry()
        for i in range(MAX_STREAMS_PER_ACCOUNT):
            assert reg.try_reserve(_stream(f"sid{i}", account_id=42))[0]
        ok, reason = reg.try_reserve(_stream("new-sid", account_id=42))
        assert not ok and reason == "account_limit"
        # Un AUTRE compte n'est pas affecté
        assert reg.try_reserve(_stream("other-sid", account_id=43))[0]

    def test_global_cap(self):
        reg = StreamRegistry()
        for i in range(MAX_STREAMS_GLOBAL):
            assert reg.try_reserve(_stream(f"sid{i}"))[0]
        ok, reason = reg.try_reserve(_stream("overflow"))
        assert not ok and reason == "server_busy"

    def test_remove_frees_slot(self):
        reg = StreamRegistry()
        reg.try_reserve(_stream("sid1", account_id=1))
        reg.remove("sid1")
        ok, _ = reg.try_reserve(_stream("sid1", account_id=1))
        assert ok

    def test_audio_seconds_from_bytes(self):
        s = _stream("sid1")
        s.bytes_received = 16000 * 2 * 7  # 7 s de PCM16 mono 16 kHz
        assert s.audio_seconds == 7


# --------------------------------------------------------------------------- #
# _reader_loop — cycle de vie avec un faux WS Deepgram
# --------------------------------------------------------------------------- #


class _FakeDeepgramWs:
    """Faux websocket-client : rejoue une séquence de messages puis simule
    une fermeture (recv lève)."""

    def __init__(self, messages: list[str]):
        self._messages = list(messages)
        self.connected = True
        self.closed = False

    def recv(self) -> str:
        if self._messages:
            return self._messages.pop(0)
        self.connected = False
        raise ConnectionResetError("closed")

    def close(self) -> None:
        self.closed = True
        self.connected = False


class TestReaderLoop:
    def _run(self, messages: list[str], stream: StreamState | None = None):
        from app.api import stt_stream as mod

        stream = stream or _stream("test-sid")
        stream.dg_ws = _FakeDeepgramWs(messages)
        mod._registry.try_reserve(stream)
        emitted: list[tuple[str, dict]] = []

        def emit(event: str, payload: dict) -> None:
            emitted.append((event, payload))

        t = threading.Thread(target=_reader_loop, args=(stream, emit), daemon=True)
        t.start()
        t.join(timeout=5)
        assert not t.is_alive(), "reader loop did not terminate"
        return emitted, stream

    def test_relays_then_closes(self):
        emitted, stream = self._run([
            json.dumps({"type": "SpeechStarted"}),
            _dg_results("bonjour", is_final=False),
            _dg_results("bonjour à tous", is_final=True, speech_final=True),
            json.dumps({"type": "UtteranceEnd"}),
        ])
        kinds = [e for e, _ in emitted]
        assert kinds == [
            "stt_speech_started",
            "stt_partial",
            "stt_final",
            "stt_utterance_end",
            "stt_stream_closed",
        ]
        assert emitted[-1][1]["reason"] == "deepgram_closed"
        assert stream.closed.is_set()
        assert stream.dg_ws.closed

    def test_stream_removed_from_registry_on_close(self):
        from app.api import stt_stream as mod

        _, stream = self._run([])
        assert mod._registry.get(stream.sid) is None

    def test_max_duration_enforced(self):
        stream = _stream("dur-sid")
        stream.started_at = time.monotonic() - 10_000  # démarré il y a longtemps
        emitted, _ = self._run([_dg_results("x", is_final=False)] * 3, stream=stream)
        assert emitted[-1] == ("stt_stream_closed", {"reason": "max_duration"})

    def test_inactivity_enforced(self):
        stream = _stream("idle-sid")
        stream.last_chunk_at = time.monotonic() - INACTIVITY_TIMEOUT_SECONDS - 5
        emitted, _ = self._run([_dg_results("x", is_final=False)] * 3, stream=stream)
        assert emitted[-1] == ("stt_stream_closed", {"reason": "inactivity"})
