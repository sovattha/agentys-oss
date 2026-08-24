# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Regression: streaming chunks and final draft_complete stay in sync.

User-reported incident (2026-05-13): `/process` streamed a good draft from
the LLM chunks, then emitted a much shorter `draft_complete` payload:

    Bonjour,

    Super merci pour le test,

    Cordialement,

The missing sentence came from the user's notes ("dispo tous les soirs").
The source email itself was short, so the post-LLM short-body truncation
heuristic must stay disabled whenever `instructions` contains user-authored
notes.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.smart_routing import SmartRouter


class _FakeChunk:
    def __init__(self, text: str, is_final: bool = False) -> None:
        self.text = text
        self.is_final = is_final


class _FakeLLM:
    def __init__(self, chunks: list[str]) -> None:
        self._chunks = chunks

    def stream(self, system: str, user: str, max_tokens: int, temperature: float):
        for chunk in self._chunks:
            yield _FakeChunk(chunk)
        yield _FakeChunk("", is_final=True)


def test_streaming_draft_complete_keeps_expanded_user_notes():
    """`draft_complete` must include content grounded only in instructions."""
    raw_chunks = [
        "Bonjour,\n\nSuper",
        " merci pour le test,\n\nJe suis disponible tous les soirs pour cette ré",
        "union Agentys. N'hésite pas à me propos",
        "er un créneau qui te convient et je confirmerai.\n\nA+,",
    ]
    container = MagicMock()
    container.get_writing_style_profile.return_value = None
    container.llm_drafting = _FakeLLM(raw_chunks)
    container.llm_drafting_smart = container.llm_drafting

    completed: list[dict] = []
    chunks: list[dict] = []

    router = SmartRouter()
    router._account_id = 4

    with patch("app.infrastructure.container.get_container", return_value=container), \
         patch("app.prompts.get_standard_draft_prompts", return_value=("sys", "usr")), \
         patch("app.prompts.load_knowledge_base", return_value=""), \
         patch("app.prompts.analyze_email_formality", return_value=4), \
         patch("app.prompts.formality_to_temperature", return_value=0.2), \
         patch("app.prompts._detect_language", return_value="FRENCH"), \
         patch("app.prompts._compute_greeting_hint", return_value="Bonjour,"), \
         patch("app.config.SONNET_ROUTING_ENABLED", False), \
         patch("app.draft_correction.get_correction_manager") as correction_manager, \
         patch("app.api.websocket.emit_draft_stage"), \
         patch("app.api.websocket.emit_draft_chunk", side_effect=lambda **kw: chunks.append(kw)), \
         patch("app.api.websocket.emit_draft_complete", side_effect=lambda **kw: completed.append(kw)), \
         patch("app.smart_routing.capture_if_enabled"):
        correction_manager.return_value.apply_learned_corrections.side_effect = (
            lambda draft, context=None: (draft, [])
        )

        returned = router._generate_standard_streaming(
            email_id="19e03be636ebc13d",
            email_content="Subject: Réunion Agentys\n\nmerci pour le test",
            sender="contact@example.com",
            subject="Réunion Agentys",
            body="merci pour le test",
            instructions=(
                "Write a complete and professional reply by expanding these notes:\n\n"
                "dispo tous les soirs"
            ),
            sender_name="",
        )

    assert chunks, "expected streaming chunks before completion"
    assert completed, "expected draft_complete emission"
    final_payload = completed[-1]["draft_content"]

    assert "disponible tous les soirs" in final_payload
    assert "créneau" in final_payload
    assert final_payload == returned


def test_user_triggered_reply_keeps_greeting_for_very_casual_source():
    """ReplyComposer sends explicit instructions; that must not become
    "no greeting" just because the source email looks like a chat message."""
    raw_chunks = ["Je confirme pour vendredi."]
    container = MagicMock()
    container.get_writing_style_profile.return_value = None
    container.llm_drafting = _FakeLLM(raw_chunks)
    container.llm_drafting_smart = container.llm_drafting

    completed: list[dict] = []

    router = SmartRouter()
    router._account_id = 4

    with patch("app.infrastructure.container.get_container", return_value=container), \
         patch("app.prompts.get_standard_draft_prompts", return_value=("sys", "usr")), \
         patch("app.prompts.load_knowledge_base", return_value=""), \
         patch("app.prompts.analyze_email_formality", return_value=1), \
         patch("app.prompts.formality_to_temperature", return_value=0.4), \
         patch("app.prompts._detect_language", return_value="FRENCH"), \
         patch("app.config.SONNET_ROUTING_ENABLED", False), \
         patch("app.draft_correction.get_correction_manager") as correction_manager, \
         patch("app.api.websocket.emit_draft_stage"), \
         patch("app.api.websocket.emit_draft_chunk"), \
         patch("app.api.websocket.emit_draft_complete", side_effect=lambda **kw: completed.append(kw)), \
         patch("app.smart_routing.capture_if_enabled"):
        correction_manager.return_value.apply_learned_corrections.side_effect = (
            lambda draft, context=None: (draft, [])
        )

        returned = router._generate_standard_streaming(
            email_id="reply-casual-1",
            email_content="Subject: vendredi\n\nTu confirmes pour vendredi ?",
            sender="alexandre@example.com",
            subject="vendredi",
            body="Tu confirmes pour vendredi ?",
            instructions="Reply appropriately to this email.",
            sender_name="Alexandre",
        )

    assert completed, "expected draft_complete emission"
    assert returned.startswith("Salut Alexandre,\n\n")
    assert completed[-1]["draft_content"].startswith("Salut Alexandre,\n\n")
