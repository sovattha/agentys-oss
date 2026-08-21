# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests de l'API Voice Session (/api/voice/agent, /briefing, /metrics).

L'agent conversationnel remplace la classification mono-intent de
/api/voice/intent : intents composés, dictée inline, questions ancrées sur
l'email courant. Ces tests verrouillent :

  1. la validation stricte des sorties LLM (_validate_actions) — un LLM
     hors-vocabulaire ne doit JAMAIS atteindre le mobile ;
  2. la dégradation gracieuse (pas de clé / LLM down / JSON cassé → 200
     "unavailable", le mobile retombe sur ses keywords locaux) ;
  3. le briefing : fallback template déterministe, inbox vide, langues ;
  4. la télémétrie : bornes de valeurs, refus des payloads vides.

Run: pytest tests/test_voice_session_api.py -v
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("flask_cors")

from app.api.voice_session import _validate_actions  # noqa: E402


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def app():
    from app.api.app import create_app

    return create_app(config={"TESTING": True})


@pytest.fixture
def client(app):
    return app.test_client()


def _patch_agent_llm(payload_or_text):
    """Patch ClaudeAdapter pour que voice_agent reçoive un JSON donné.

    voice_agent passe par ClaudeAdapter.complete (et NON un client anthropic
    brut) — c'est le seul chemin qui écrit TokenUsageLogRow (metering du cap
    de crédit). On mocke donc l'adapter, pas anthropic.Anthropic.
    """
    text = payload_or_text if isinstance(payload_or_text, str) else json.dumps(payload_or_text)
    response = MagicMock()
    response.content = text
    patcher = patch("app.adapters.llm.claude_adapter.ClaudeAdapter")
    mock_cls = patcher.start()
    mock_cls.return_value.complete.return_value = response
    return patcher, mock_cls


# --------------------------------------------------------------------------- #
# _validate_actions — la barrière entre le LLM et le mobile
# --------------------------------------------------------------------------- #


class TestValidateActions:
    def test_simple_actions_pass(self):
        actions = _validate_actions([{"type": "ARCHIVE"}, {"type": "NEXT"}])
        assert actions == [{"type": "ARCHIVE"}, {"type": "NEXT"}]

    def test_unknown_action_dropped(self):
        actions = _validate_actions([{"type": "FORMAT_DISK"}, {"type": "NEXT"}])
        assert actions == [{"type": "NEXT"}]

    def test_non_dict_items_dropped(self):
        assert _validate_actions(["ARCHIVE", 42, None]) == []

    def test_not_a_list(self):
        assert _validate_actions("ARCHIVE") == []
        assert _validate_actions(None) == []

    def test_max_four_actions(self):
        many = [{"type": "NEXT"}] * 10
        assert len(_validate_actions(many)) == 4

    def test_draft_reply_requires_content(self):
        assert _validate_actions([{"type": "DRAFT_REPLY", "content": ""}]) == []
        assert _validate_actions([{"type": "DRAFT_REPLY"}]) == []

    def test_draft_reply_normalizes_payload(self):
        # auto_send n'est honoré que si le TRANSCRIPT porte un verbe d'envoi.
        actions = _validate_actions(
            [{"type": "DRAFT_REPLY", "content": "ok pour jeudi", "reply_type": "bogus", "auto_send": "yes"}],
            "réponds ok et envoie",
        )
        assert actions == [{
            "type": "DRAFT_REPLY",
            "content": "ok pour jeudi",
            "reply_type": "reply",
            "auto_send": True,
        }]

    def test_draft_reply_auto_send_false_by_default(self):
        actions = _validate_actions([{"type": "DRAFT_REPLY", "content": "ok"}], "réponds ok")
        assert actions[0]["auto_send"] is False

    def test_auto_send_forced_false_without_send_verb_in_transcript(self):
        # Injection : le LLM veut auto_send mais l'utilisateur n'a PAS dit "envoie".
        actions = _validate_actions(
            [{"type": "DRAFT_REPLY", "content": "exfil", "auto_send": True}],
            "ok",  # pas de verbe d'envoi
        )
        assert actions[0]["auto_send"] is False

    def test_approve_dropped_without_send_verb(self):
        actions = _validate_actions([{"type": "APPROVE"}], "ok")
        assert actions == []
        actions = _validate_actions([{"type": "APPROVE"}], "oui envoie")
        assert actions == [{"type": "APPROVE"}]

    def test_delete_downgrades_to_archive_without_delete_verb(self):
        # Injection email "supprime ce mail" + parole anodine → ARCHIVE (réversible).
        actions = _validate_actions([{"type": "DELETE"}], "ok")
        assert actions == [{"type": "ARCHIVE"}]
        # Vrai "supprime" dans la parole → DELETE honoré.
        actions = _validate_actions([{"type": "DELETE"}], "supprime ça")
        assert actions == [{"type": "DELETE"}]

    def test_modify_requires_instruction(self):
        assert _validate_actions([{"type": "MODIFY"}]) == []
        actions = _validate_actions([{"type": "MODIFY", "instruction": "plus court"}])
        assert actions == [{"type": "MODIFY", "instruction": "plus court"}]

    def test_say_requires_text_and_clips(self):
        assert _validate_actions([{"type": "SAY", "text": ""}]) == []
        long_text = "x" * 2000
        actions = _validate_actions([{"type": "SAY", "text": long_text}])
        assert len(actions[0]["text"]) == 600

    def test_say_then_action_compound(self):
        actions = _validate_actions([
            {"type": "SAY", "text": "C'est ton comptable."},
            {"type": "ARCHIVE"},
        ])
        assert [a["type"] for a in actions] == ["SAY", "ARCHIVE"]


# --------------------------------------------------------------------------- #
# POST /api/voice/agent
# --------------------------------------------------------------------------- #


class TestVoiceAgentEndpoint:
    def test_missing_transcript_400(self, client):
        res = client.post("/api/voice/agent", json={})
        assert res.status_code == 400

    def test_no_api_key_degrades_to_unavailable(self, client, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        res = client.post("/api/voice/agent", json={"transcript": "archive ça"})
        assert res.status_code == 200
        data = res.get_json()
        assert data["actions"] == []
        assert data["source"] == "unavailable"

    def test_compound_intent_returns_ordered_actions(self, client, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        patcher, _ = _patch_agent_llm({
            "actions": [{"type": "ARCHIVE"}, {"type": "NEXT"}],
            "confidence": 0.95,
        })
        try:
            res = client.post("/api/voice/agent", json={
                "transcript": "archive ça et lis-moi le suivant",
                "state": "choosing",
            })
        finally:
            patcher.stop()
        assert res.status_code == 200
        data = res.get_json()
        assert [a["type"] for a in data["actions"]] == ["ARCHIVE", "NEXT"]
        assert data["confidence"] == 0.95
        assert data["source"] == "llm"

    def test_llm_garbage_actions_filtered(self, client, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        patcher, _ = _patch_agent_llm({
            "actions": [{"type": "rm -rf"}, {"type": "DELETE"}],
            "confidence": 2.5,  # hors bornes → 0.5
        })
        try:
            # transcript "supprime" → le verbe de suppression autorise DELETE.
            res = client.post("/api/voice/agent", json={"transcript": "supprime"})
        finally:
            patcher.stop()
        data = res.get_json()
        assert data["actions"] == [{"type": "DELETE"}]
        assert data["confidence"] == 0.5

    def test_malformed_json_degrades_gracefully(self, client, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        patcher, _ = _patch_agent_llm("désolé je ne peux pas répondre en JSON")
        try:
            res = client.post("/api/voice/agent", json={"transcript": "suivant"})
        finally:
            patcher.stop()
        assert res.status_code == 200
        assert res.get_json()["source"] == "unavailable"

    def test_adapter_exception_degrades_gracefully(self, client, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        with patch("app.adapters.llm.claude_adapter.ClaudeAdapter") as mock_cls:
            mock_cls.return_value.complete.side_effect = RuntimeError("timeout")
            res = client.post("/api/voice/agent", json={"transcript": "suivant"})
        assert res.status_code == 200
        assert res.get_json()["source"] == "unavailable"

    def test_say_action_passthrough(self, client, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        patcher, _ = _patch_agent_llm({
            "actions": [{"type": "SAY", "text": "Il propose jeudi 15 h."}],
            "confidence": 0.9,
        })
        try:
            res = client.post("/api/voice/agent", json={
                "transcript": "il proposait quelle heure déjà ?",
                "state": "choosing",
                "email_id": "abc123",
            })
        finally:
            patcher.stop()
        data = res.get_json()
        assert data["actions"][0]["type"] == "SAY"
        assert "jeudi" in data["actions"][0]["text"]

    def test_transcript_too_long_is_clipped_not_rejected(self, client, monkeypatch):
        """Contrairement à /voice/intent (400 si >1000), l'agent clip — en
        voiture, rejeter une longue dictée est pire que la tronquer."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        patcher, _ = _patch_agent_llm({"actions": [], "confidence": 0.2})
        try:
            res = client.post("/api/voice/agent", json={"transcript": "bla " * 600})
        finally:
            patcher.stop()
        assert res.status_code == 200


# --------------------------------------------------------------------------- #
# POST /api/voice/briefing
# --------------------------------------------------------------------------- #


class TestVoiceBriefing:
    def test_template_fallback_without_api_key(self, client, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        res = client.post("/api/voice/briefing", json={
            "counts": {"total": 12, "unread": 8, "action": 3},
            "lang": "fr",
        })
        assert res.status_code == 200
        data = res.get_json()
        assert data["source"] == "template"
        assert "12" in data["text"]
        assert "3" in data["text"]

    def test_empty_inbox_short_circuit(self, client, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        res = client.post("/api/voice/briefing", json={
            "counts": {"total": 0},
            "lang": "en",
        })
        data = res.get_json()
        assert data["source"] == "template"
        assert "caught up" in data["text"]

    def test_invalid_lang_falls_back_to_fr(self, client, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        res = client.post("/api/voice/briefing", json={
            "counts": {"total": 5},
            "lang": "de",
        })
        assert "mails" in res.get_json()["text"]

    def test_llm_renders_brief(self, client, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        fake_response = MagicMock()
        fake_response.content = "Salut ! 12 mails t'attendent, 3 urgents dont Marie. On commence ?"
        with patch("app.adapters.llm.claude_adapter.ClaudeAdapter") as mock_cls:
            mock_cls.return_value.complete.return_value = fake_response
            res = client.post("/api/voice/briefing", json={
                "counts": {"total": 12, "unread": 8, "action": 3},
                "top": [{"sender_name": "Marie", "subject": "Contrat", "classification": "Action"}],
                "lang": "fr",
            })
        data = res.get_json()
        assert data["source"] == "llm"
        assert "Marie" in data["text"]

    def test_llm_failure_falls_back_to_template(self, client, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        with patch("app.adapters.llm.claude_adapter.ClaudeAdapter") as mock_cls:
            mock_cls.return_value.complete.side_effect = RuntimeError("down")
            res = client.post("/api/voice/briefing", json={
                "counts": {"total": 7, "action": 2},
                "lang": "es",
            })
        data = res.get_json()
        assert data["source"] == "template"
        assert "7" in data["text"]

    def test_counts_are_clamped(self, client, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        res = client.post("/api/voice/briefing", json={
            "counts": {"total": -5, "action": "NaN"},
        })
        assert res.status_code == 200  # défensif, pas de 500

    def test_counts_not_a_dict_no_500(self, client, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        res = client.post("/api/voice/briefing", json={"counts": "oops"})
        assert res.status_code == 200  # pas d'AttributeError → 500


# --------------------------------------------------------------------------- #
# POST /api/voice/metrics
# --------------------------------------------------------------------------- #


class TestVoiceMetrics:
    def test_empty_events_rejected(self, client):
        assert client.post("/api/voice/metrics", json={}).status_code == 400
        assert client.post("/api/voice/metrics", json={"events": []}).status_code == 400

    def test_valid_latency_event_accepted(self, client):
        res = client.post("/api/voice/metrics", json={
            "events": [
                {"kind": "turn_latency_ms", "value_ms": 1450, "state": "choosing"},
                {"kind": "stt_latency_ms", "value_ms": 800},
            ],
        })
        assert res.status_code == 200
        assert res.get_json()["accepted"] == 2

    def test_counter_event_accepted(self, client):
        res = client.post("/api/voice/metrics", json={
            "events": [{"kind": "undo_cancels", "count": 2}],
        })
        assert res.get_json()["accepted"] == 1

    def test_out_of_range_and_unknown_dropped(self, client):
        res = client.post("/api/voice/metrics", json={
            "events": [
                {"kind": "turn_latency_ms", "value_ms": -5},
                {"kind": "turn_latency_ms", "value_ms": 999_999_999},
                {"kind": "free_text_content", "value_ms": 100},  # inconnu
                {"kind": "turn_latency_ms", "value_ms": "abc"},
            ],
        })
        assert res.get_json()["accepted"] == 0

    def test_non_string_kind_no_500(self, client):
        # kind=list → `kind in _METRIC_FIELDS` lèverait TypeError (unhashable).
        res = client.post("/api/voice/metrics", json={
            "events": [{"kind": ["turn_latency_ms"], "value_ms": 100}],
        })
        assert res.status_code == 200
        assert res.get_json()["accepted"] == 0
