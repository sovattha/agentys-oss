# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests for the P1.5 FAQ matcher+generator fusion.

Covers the early-return paths of `match_and_generate_faq_with_llm` (no LLM
call needed) and the fallback wiring in `process_faq_email`. The LLM-driven
path is exercised by mocking the container's LLM port.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


from app.faq_agent import (
    match_and_generate_faq_with_llm,
)


class TestEarlyReturnPaths:
    def test_empty_entries_returns_none(self):
        m, b = match_and_generate_faq_with_llm(
            email_body="body",
            email_subject="subj",
            sender_name="Sender",
            faq_entries=[],
            tone="professional",
            threshold=80.0,
        )
        assert m is None and b is None

    def test_empty_email_returns_none(self):
        m, b = match_and_generate_faq_with_llm(
            email_body="",
            email_subject="",
            sender_name="Sender",
            faq_entries=[{"id": "x", "title": "t", "content": "c"}],
            tone="professional",
            threshold=80.0,
        )
        assert m is None and b is None


class _FakeLLMResponse:
    def __init__(self, content: str):
        self.content = content
        self.input_tokens = 100
        self.output_tokens = 50
        self.model = "fake-haiku"


class TestLLMDrivenPaths:
    def _patch_llm(self, response_content: str):
        """Helper to patch the container's llm_background.complete()."""
        fake_llm = MagicMock()
        fake_llm.complete.return_value = _FakeLLMResponse(response_content)
        return patch(
            "app.infrastructure.container.get_container",
            return_value=MagicMock(llm_background=fake_llm),
        )

    def test_match_with_response_returned(self):
        with self._patch_llm(
            '{"faq_index": 1, "confidence": 0.95, "response": "Voici la réponse."}'
        ):
            m, b = match_and_generate_faq_with_llm(
                email_body="Question simple",
                email_subject="Question",
                sender_name="Alex",
                faq_entries=[
                    {"id": "faq-1", "title": "Comment ?", "content": "Réponse 1"},
                ],
                tone="professional",
                threshold=80.0,
            )
        assert m is not None
        assert m.entry_id == "faq-1"
        assert m.score == 95.0
        assert b == "Voici la réponse."

    def test_match_generate_records_usage_attribution(self):
        captured = []

        class _UsageRecordingLLM:
            def complete(self, **_kwargs):
                from app.infrastructure.token_usage_writer import record_usage

                record_usage(
                    model="claude-haiku-4-5-20251001",
                    input_tokens=100,
                    output_tokens=12,
                )
                return _FakeLLMResponse(
                    '{"faq_index": 1, "confidence": 0.95, "response": "Réponse FAQ."}'
                )

        from app.infrastructure.llm_attribution import llm_attribution

        with patch(
            "app.infrastructure.container.get_container",
            return_value=MagicMock(llm_background=_UsageRecordingLLM()),
        ):
            with patch(
                "app.infrastructure.token_usage_writer.enqueue",
                side_effect=lambda record: captured.append(record),
            ):
                with llm_attribution(
                    "faq_agent",
                    account_id=14,
                    user_id=1694432691,
                    feature="faq_auto_reply",
                ):
                    m, b = match_and_generate_faq_with_llm(
                        email_body="Question simple",
                        email_subject="Question",
                        sender_name="Alex",
                        faq_entries=[
                            {"id": "faq-1", "title": "Comment ?", "content": "Réponse 1"},
                        ],
                        tone="professional",
                        threshold=80.0,
                    )

        assert m is not None
        assert b == "Réponse FAQ."
        assert len(captured) == 1
        row = captured[0]
        assert row.agent == "faq_match_generate"
        assert row.account_id == 14
        assert row.user_id == 1694432691
        assert row.feature == "faq_auto_reply"

    def test_no_match_returns_none(self):
        with self._patch_llm(
            '{"faq_index": 0, "confidence": 0.0, "response": ""}'
        ):
            m, b = match_and_generate_faq_with_llm(
                email_body="Off-topic",
                email_subject="Random",
                sender_name="Alex",
                faq_entries=[
                    {"id": "faq-1", "title": "X", "content": "Y"},
                ],
                tone="professional",
                threshold=80.0,
            )
        assert m is None and b is None

    def test_below_threshold_returns_none(self):
        # LLM returns a match but with low confidence — below threshold,
        # so we treat it as no-match (consistent with the legacy 2-call path).
        with self._patch_llm(
            '{"faq_index": 1, "confidence": 0.50, "response": "Maybe"}'
        ):
            m, b = match_and_generate_faq_with_llm(
                email_body="Question",
                email_subject="Q",
                sender_name="Alex",
                faq_entries=[
                    {"id": "faq-1", "title": "X", "content": "Y"},
                ],
                tone="professional",
                threshold=80.0,
            )
        assert m is None and b is None

    def test_out_of_range_index_returns_none(self):
        with self._patch_llm(
            '{"faq_index": 99, "confidence": 0.95, "response": "..."}'
        ):
            m, b = match_and_generate_faq_with_llm(
                email_body="Q",
                email_subject="Q",
                sender_name="Alex",
                faq_entries=[
                    {"id": "faq-1", "title": "X", "content": "Y"},
                ],
                tone="professional",
                threshold=80.0,
            )
        assert m is None and b is None

    def test_empty_response_falls_back_to_faq_content(self):
        # LLM matched but didn't write a body — defensive fallback to raw FAQ
        # content keeps the auto-reply functional.
        with self._patch_llm(
            '{"faq_index": 1, "confidence": 0.95, "response": ""}'
        ):
            m, b = match_and_generate_faq_with_llm(
                email_body="Q",
                email_subject="Q",
                sender_name="Alex",
                faq_entries=[
                    {"id": "faq-1", "title": "X", "content": "Raw FAQ content"},
                ],
                tone="professional",
                threshold=80.0,
            )
        assert m is not None
        assert b == "Raw FAQ content"

    def test_llm_exception_returns_none(self):
        # LLM 5xx / network failure → fall back to (None, None) so the caller
        # routes to the word-overlap fallback path in process_faq_email.
        fake_llm = MagicMock()
        fake_llm.complete.side_effect = RuntimeError("provider down")
        with patch(
            "app.infrastructure.container.get_container",
            return_value=MagicMock(llm_background=fake_llm),
        ):
            m, b = match_and_generate_faq_with_llm(
                email_body="Q",
                email_subject="Q",
                sender_name="Alex",
                faq_entries=[
                    {"id": "faq-1", "title": "X", "content": "Y"},
                ],
                tone="professional",
                threshold=80.0,
            )
        assert m is None and b is None

    def test_garbage_json_returns_none(self):
        with self._patch_llm("not valid json {"):
            m, b = match_and_generate_faq_with_llm(
                email_body="Q",
                email_subject="Q",
                sender_name="Alex",
                faq_entries=[
                    {"id": "faq-1", "title": "X", "content": "Y"},
                ],
                tone="professional",
                threshold=80.0,
            )
        # extract_json_from_response will return the default (faq_index=0),
        # which short-circuits to None.
        assert m is None and b is None


class TestConfidenceClamp:
    def _patch_llm(self, response_content: str):
        fake_llm = MagicMock()
        fake_llm.complete.return_value = _FakeLLMResponse(response_content)
        return patch(
            "app.infrastructure.container.get_container",
            return_value=MagicMock(llm_background=fake_llm),
        )

    def test_confidence_above_one_clamped(self):
        # Defensive: LLM hallucinates confidence=2.5
        with self._patch_llm(
            '{"faq_index": 1, "confidence": 2.5, "response": "X"}'
        ):
            m, _ = match_and_generate_faq_with_llm(
                email_body="Q", email_subject="Q", sender_name="A",
                faq_entries=[{"id": "f", "title": "T", "content": "C"}],
                tone="professional", threshold=80.0,
            )
        assert m is not None
        assert m.score == 100.0

    def test_confidence_below_zero_clamped(self):
        with self._patch_llm(
            '{"faq_index": 1, "confidence": -0.5, "response": "X"}'
        ):
            m, _ = match_and_generate_faq_with_llm(
                email_body="Q", email_subject="Q", sender_name="A",
                faq_entries=[{"id": "f", "title": "T", "content": "C"}],
                tone="professional", threshold=0.0,  # threshold=0 to surface clamp
            )
        assert m is not None
        assert m.score == 0.0
