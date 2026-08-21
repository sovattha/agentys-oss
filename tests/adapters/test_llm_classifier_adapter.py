# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour LLMClassifierAdapter."""

import pytest
from unittest.mock import MagicMock

from app.adapters.classification.llm_classifier_adapter import LLMClassifierAdapter
from app.domain.entities import Email, Classification, EmailCategory, TokenUsage
from app.domain.ports import LLMPort, LLMResponse
from app.domain.exceptions import LLMRateLimitError, LLMAuthenticationError


def _make_email(**overrides) -> Email:
    defaults = dict(
        id="email-1",
        subject="Demande d'info",
        body="Bonjour, je souhaite obtenir des informations.",
        sender="client@example.com",
    )
    defaults.update(overrides)
    return Email(**defaults)


def _make_llm_response(content: str, **kwargs) -> LLMResponse:
    defaults = dict(input_tokens=10, output_tokens=5, model="mock")
    defaults.update(kwargs)
    return LLMResponse(content=content, **defaults)


class TestLLMClassifierAdapterClassify:
    """Tests de la classification."""

    def test_classify_normal_email(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.return_value = _make_llm_response(
            '{"category": "NORMAL", "confidence": 0.85, "reason": "Standard request"}'
        )

        adapter = LLMClassifierAdapter(llm=llm)
        result = adapter.classify(_make_email())

        assert isinstance(result, Classification)
        assert result.category == EmailCategory.NORMAL
        assert result.confidence == 0.85
        assert result.reason == "Standard request"

    def test_classify_urgent_email(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.return_value = _make_llm_response(
            '{"category": "URGENT", "confidence": 0.95, "reason": "Demande urgente"}'
        )

        adapter = LLMClassifierAdapter(llm=llm)
        result = adapter.classify(_make_email())

        assert result.category == EmailCategory.URGENT
        assert result.confidence == 0.95

    def test_classify_spam(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.return_value = _make_llm_response(
            '{"category": "SPAM", "confidence": 0.99, "reason": "Obvious spam"}'
        )

        adapter = LLMClassifierAdapter(llm=llm)
        result = adapter.classify(_make_email())

        assert result.category == EmailCategory.SPAM

    def test_classify_with_markdown_wrapper(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.return_value = _make_llm_response(
            '```json\n{"category": "IMPORTANT", "confidence": 0.8, "reason": "Business"}\n```'
        )

        adapter = LLMClassifierAdapter(llm=llm)
        result = adapter.classify(_make_email())

        assert result.category == EmailCategory.IMPORTANT

    def test_classify_unknown_category_defaults_to_normal(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.return_value = _make_llm_response(
            '{"category": "UNKNOWN_CATEGORY", "confidence": 0.5, "reason": "test"}'
        )

        adapter = LLMClassifierAdapter(llm=llm)
        result = adapter.classify(_make_email())

        assert result.category == EmailCategory.NORMAL

    def test_classify_invalid_json_returns_default(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.return_value = _make_llm_response("This is not JSON at all")

        adapter = LLMClassifierAdapter(llm=llm)
        result = adapter.classify(_make_email())

        assert result.category == EmailCategory.NORMAL
        assert result.confidence == 0.5

    def test_classify_clamps_confidence(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.return_value = _make_llm_response(
            '{"category": "NORMAL", "confidence": 1.5, "reason": "test"}'
        )

        adapter = LLMClassifierAdapter(llm=llm)
        result = adapter.classify(_make_email())

        assert result.confidence == 1.0

    def test_classify_clamps_negative_confidence(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.return_value = _make_llm_response(
            '{"category": "NORMAL", "confidence": -0.5, "reason": "test"}'
        )

        adapter = LLMClassifierAdapter(llm=llm)
        result = adapter.classify(_make_email())

        assert result.confidence == 0.0


class TestLLMClassifierAdapterContext:
    """Tests de construction du contexte."""

    def test_context_includes_cc_marker(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.return_value = _make_llm_response(
            '{"category": "CC_ONLY", "confidence": 0.9, "reason": "cc"}'
        )

        adapter = LLMClassifierAdapter(llm=llm)
        adapter.classify(_make_email(), is_cc=True)

        user_arg = llm.complete.call_args.kwargs["user"]
        assert "COPIE" in user_arg

    def test_context_excludes_cc_marker_when_not_cc(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.return_value = _make_llm_response(
            '{"category": "NORMAL", "confidence": 0.8, "reason": "normal"}'
        )

        adapter = LLMClassifierAdapter(llm=llm)
        adapter.classify(_make_email(), is_cc=False)

        user_arg = llm.complete.call_args.kwargs["user"]
        assert "COPIE" not in user_arg

    def test_context_includes_sender_and_subject(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.return_value = _make_llm_response(
            '{"category": "NORMAL", "confidence": 0.8, "reason": "test"}'
        )

        adapter = LLMClassifierAdapter(llm=llm)
        adapter.classify(_make_email(sender="vip@corp.com", subject="Partnership"))

        user_arg = llm.complete.call_args.kwargs["user"]
        assert "vip@corp.com" in user_arg
        assert "Partnership" in user_arg

    def test_body_truncated_at_2000_chars(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.return_value = _make_llm_response(
            '{"category": "NORMAL", "confidence": 0.5, "reason": "long"}'
        )

        long_body = "A" * 5000
        adapter = LLMClassifierAdapter(llm=llm)
        adapter.classify(_make_email(body=long_body))

        user_arg = llm.complete.call_args.kwargs["user"]
        # Body should be limited to 2000 chars
        assert "A" * 2000 in user_arg
        assert "A" * 2001 not in user_arg


class TestLLMClassifierAdapterTokenTracking:
    """Tests du suivi des tokens."""

    def test_tracks_tokens_when_usage_provided(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.return_value = _make_llm_response(
            '{"category": "NORMAL", "confidence": 0.8, "reason": "test"}',
            input_tokens=50,
            output_tokens=20,
        )

        tu = TokenUsage()
        adapter = LLMClassifierAdapter(llm=llm, token_usage=tu)
        adapter.classify(_make_email())

        assert tu.input_tokens == 50
        assert tu.output_tokens == 20

    def test_no_error_when_usage_is_none(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.return_value = _make_llm_response(
            '{"category": "NORMAL", "confidence": 0.8, "reason": "test"}'
        )

        adapter = LLMClassifierAdapter(llm=llm, token_usage=None)
        result = adapter.classify(_make_email())

        assert result.category == EmailCategory.NORMAL


class TestLLMClassifierAdapterErrorHandling:
    """Tests de gestion des erreurs."""

    def test_llm_error_propagates(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.side_effect = LLMRateLimitError(provider="claude")

        adapter = LLMClassifierAdapter(llm=llm)

        with pytest.raises(LLMRateLimitError):
            adapter.classify(_make_email())

    def test_auth_error_propagates(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.side_effect = LLMAuthenticationError(provider="claude")

        adapter = LLMClassifierAdapter(llm=llm)

        with pytest.raises(LLMAuthenticationError):
            adapter.classify(_make_email())

    def test_generic_exception_returns_default(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.return_value = _make_llm_response("valid json but ...")
        # Simulate a parsing error by making _parse_response raise
        llm.complete.side_effect = TypeError("unexpected")

        adapter = LLMClassifierAdapter(llm=llm)
        result = adapter.classify(_make_email())

        assert result.category == EmailCategory.NORMAL
        assert result.confidence == 0.5
