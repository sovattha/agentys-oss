# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour LLMPrioritizationAdapter."""

import pytest
from unittest.mock import MagicMock

from app.adapters.classification.llm_prioritization_adapter import LLMPrioritizationAdapter
from app.domain.entities import Email, Priority, TokenUsage
from app.domain.ports import LLMPort, LLMResponse
from app.domain.exceptions import LLMRateLimitError


def _make_email(**overrides) -> Email:
    defaults = dict(
        id="email-1",
        subject="Réunion urgente",
        body="Nous devons nous réunir demain matin.",
        sender="boss@example.com",
    )
    defaults.update(overrides)
    return Email(**defaults)


def _make_llm_response(content: str, **kwargs) -> LLMResponse:
    defaults = dict(input_tokens=10, output_tokens=5, model="mock")
    defaults.update(kwargs)
    return LLMResponse(content=content, **defaults)


class TestLLMPrioritizationAdapterAnalyze:
    """Tests de l'analyse de priorité."""

    def test_analyze_with_all_fields(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.return_value = _make_llm_response(
            '{"urgency": 80, "vip": 60, "sentiment": 0.2, "deadline": "2025-03-01", "priority_score": 75}'
        )

        adapter = LLMPrioritizationAdapter(llm=llm)
        result = adapter.analyze(_make_email())

        assert isinstance(result, Priority)
        assert result.urgency == 80
        assert result.vip == 60
        assert result.sentiment == 0.2
        assert result.deadline == "2025-03-01"
        assert result.priority_score == 75

    def test_analyze_without_priority_score_computes_it(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.return_value = _make_llm_response(
            '{"urgency": 80, "vip": 60, "sentiment": 0.0, "deadline": null}'
        )

        adapter = LLMPrioritizationAdapter(llm=llm)
        result = adapter.analyze(_make_email())

        # from_components: 80*0.4 + 60*0.3 + (0+1)*15 = 32 + 18 + 15 = 65
        assert result.priority_score == 65

    def test_analyze_with_null_deadline(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.return_value = _make_llm_response(
            '{"urgency": 50, "vip": 50, "sentiment": 0, "deadline": null, "priority_score": 50}'
        )

        adapter = LLMPrioritizationAdapter(llm=llm)
        result = adapter.analyze(_make_email())

        assert result.deadline is None

    def test_analyze_clamps_urgency(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.return_value = _make_llm_response(
            '{"urgency": 150, "vip": 50, "sentiment": 0, "deadline": null, "priority_score": 50}'
        )

        adapter = LLMPrioritizationAdapter(llm=llm)
        result = adapter.analyze(_make_email())

        assert result.urgency == 100

    def test_analyze_clamps_vip(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.return_value = _make_llm_response(
            '{"urgency": 50, "vip": -10, "sentiment": 0, "deadline": null, "priority_score": 50}'
        )

        adapter = LLMPrioritizationAdapter(llm=llm)
        result = adapter.analyze(_make_email())

        assert result.vip == 0

    def test_analyze_clamps_sentiment(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.return_value = _make_llm_response(
            '{"urgency": 50, "vip": 50, "sentiment": 2.5, "deadline": null, "priority_score": 50}'
        )

        adapter = LLMPrioritizationAdapter(llm=llm)
        result = adapter.analyze(_make_email())

        assert result.sentiment == 1.0

    def test_analyze_clamps_priority_score(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.return_value = _make_llm_response(
            '{"urgency": 50, "vip": 50, "sentiment": 0, "deadline": null, "priority_score": 120}'
        )

        adapter = LLMPrioritizationAdapter(llm=llm)
        result = adapter.analyze(_make_email())

        assert result.priority_score == 100

    def test_analyze_with_markdown_wrapper(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.return_value = _make_llm_response(
            '```json\n{"urgency": 70, "vip": 40, "sentiment": -0.5, "deadline": null, "priority_score": 55}\n```'
        )

        adapter = LLMPrioritizationAdapter(llm=llm)
        result = adapter.analyze(_make_email())

        assert result.urgency == 70
        assert result.sentiment == -0.5


class TestLLMPrioritizationAdapterParseErrors:
    """Tests de parsing d'erreurs."""

    def test_invalid_json_returns_default(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.return_value = _make_llm_response("Not valid JSON")

        adapter = LLMPrioritizationAdapter(llm=llm)
        result = adapter.analyze(_make_email())

        assert result.urgency == 50
        assert result.vip == 50
        assert result.priority_score == 50

    def test_missing_fields_use_defaults(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.return_value = _make_llm_response('{"urgency": 90}')

        adapter = LLMPrioritizationAdapter(llm=llm)
        result = adapter.analyze(_make_email())

        assert result.urgency == 90
        assert result.vip == 50  # default
        assert result.sentiment == 0  # default


class TestLLMPrioritizationAdapterContext:
    """Tests de construction du contexte."""

    def test_context_includes_sender_subject_body(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.return_value = _make_llm_response(
            '{"urgency": 50, "vip": 50, "sentiment": 0, "deadline": null, "priority_score": 50}'
        )

        adapter = LLMPrioritizationAdapter(llm=llm)
        adapter.analyze(_make_email(sender="ceo@corp.com", subject="ASAP"))

        user_arg = llm.complete.call_args.kwargs["user"]
        assert "ceo@corp.com" in user_arg
        assert "ASAP" in user_arg

    def test_body_truncated_at_2000(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.return_value = _make_llm_response(
            '{"urgency": 50, "vip": 50, "sentiment": 0, "deadline": null, "priority_score": 50}'
        )

        adapter = LLMPrioritizationAdapter(llm=llm)
        adapter.analyze(_make_email(body="X" * 5000))

        user_arg = llm.complete.call_args.kwargs["user"]
        assert "X" * 2000 in user_arg
        assert "X" * 2001 not in user_arg


class TestLLMPrioritizationAdapterTokenTracking:
    """Tests du suivi des tokens."""

    def test_tracks_tokens(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.return_value = _make_llm_response(
            '{"urgency": 50, "vip": 50, "sentiment": 0, "deadline": null, "priority_score": 50}',
            input_tokens=80,
            output_tokens=30,
        )

        tu = TokenUsage()
        adapter = LLMPrioritizationAdapter(llm=llm, token_usage=tu)
        adapter.analyze(_make_email())

        assert tu.input_tokens == 80
        assert tu.output_tokens == 30

    def test_no_error_when_usage_is_none(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.return_value = _make_llm_response(
            '{"urgency": 50, "vip": 50, "sentiment": 0, "deadline": null, "priority_score": 50}'
        )

        adapter = LLMPrioritizationAdapter(llm=llm, token_usage=None)
        result = adapter.analyze(_make_email())

        assert result.urgency == 50


class TestLLMPrioritizationAdapterErrorHandling:
    """Tests de gestion des erreurs."""

    def test_llm_error_propagates(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.side_effect = LLMRateLimitError(provider="claude")

        adapter = LLMPrioritizationAdapter(llm=llm)

        with pytest.raises(LLMRateLimitError):
            adapter.analyze(_make_email())

    def test_generic_exception_returns_default(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.side_effect = TypeError("unexpected")

        adapter = LLMPrioritizationAdapter(llm=llm)
        result = adapter.analyze(_make_email())

        assert result.priority_score == 50
