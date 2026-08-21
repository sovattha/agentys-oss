# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests for issue #684 — wiring UnifiedEmailAnalyzerAgent into the pipeline.

These tests verify that:
  - `LLMEmailAnalyzerAdapter(unified=...)` takes precedence over the
    legacy 2-call classifier+prioritizer path.
  - `AnalyzeEmailUseCase(analyzer=...)` delegates to the port and does
    NOT invoke classifier+prioritizer (which would mean 2 LLM calls).
  - Container wires the unified analyzer by default, exposing 50% fewer
    Haiku calls on the analyze pipeline.
  - Edge cases : invalid deadline drops to None, unknown category falls
    back to NORMAL, the legacy 2-call path still works for tests that
    inject classifier+prioritizer directly.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from app.adapters.classification import LLMEmailAnalyzerAdapter
from app.application.analyze_email import AnalyzeEmailUseCase
from app.domain.entities import (
    Classification,
    Email,
    EmailAnalysis,
    EmailCategory,
    Priority,
)
from app.domain.ports import ClassifierPort, EmailAnalyzerPort, PrioritizationPort


def _make_email() -> Email:
    return Email(
        id="email-684",
        sender="vip@client.com",
        subject="Urgent — facture",
        body="Pourriez-vous régler la facture #1234 avant demain ?",
        recipients=["support@agentys.io"],
    )


def _unified_result(**overrides) -> dict:
    """Build a sanitized result dict like UnifiedEmailAnalyzerAgent.analyze()."""
    base = {
        "category": "URGENT",
        "category_confidence": 0.92,
        "intent": "INQUIRY",
        "intent_confidence": 0.8,
        "urgency": 85,
        "vip": 75,
        "sentiment": -0.2,
        "deadline": "2026-05-17",
        "priority_score": 80,
        "tasks": [],
    }
    base.update(overrides)
    return base


def _make_unified_mock(result: dict) -> Mock:
    """Build a Mock that quacks like UnifiedEmailAnalyzerAgent."""
    agent = Mock()
    agent.analyze.return_value = result
    return agent


# ----------------------------------------------------------------------------
# LLMEmailAnalyzerAdapter — unified path
# ----------------------------------------------------------------------------


class TestAdapterUnifiedPath:
    def test_unified_path_used_when_injected(self):
        """When `unified` is set, the 2-call path is NOT taken."""
        classifier = Mock(spec=ClassifierPort)
        prioritizer = Mock(spec=PrioritizationPort)
        unified = _make_unified_mock(_unified_result())

        adapter = LLMEmailAnalyzerAdapter(
            classifier=classifier,
            prioritizer=prioritizer,
            unified=unified,
        )
        adapter.analyze(_make_email())

        unified.analyze.assert_called_once()
        # Critical: legacy ports are NOT invoked → -50% LLM calls
        classifier.classify.assert_not_called()
        prioritizer.analyze.assert_not_called()

    def test_unified_path_builds_email_analysis(self):
        unified = _make_unified_mock(_unified_result())
        adapter = LLMEmailAnalyzerAdapter(unified=unified)

        result = adapter.analyze(_make_email())

        assert isinstance(result, EmailAnalysis)
        assert result.email_id == "email-684"
        assert result.classification.category == EmailCategory.URGENT
        assert result.classification.confidence == 0.92
        assert result.classification.reason == "unified analyzer"
        assert result.priority.urgency == 85
        assert result.priority.vip == 75
        assert result.priority.sentiment == -0.2
        assert result.priority.deadline == "2026-05-17"
        assert result.priority.priority_score == 80

    def test_unified_path_propagates_is_cc(self):
        unified = _make_unified_mock(_unified_result())
        adapter = LLMEmailAnalyzerAdapter(unified=unified)

        adapter.analyze(_make_email(), is_cc=True)

        call_kwargs = unified.analyze.call_args.kwargs
        assert call_kwargs.get("is_cc") is True

    def test_unified_path_passes_sender(self):
        unified = _make_unified_mock(_unified_result())
        adapter = LLMEmailAnalyzerAdapter(unified=unified)

        adapter.analyze(_make_email())

        call_kwargs = unified.analyze.call_args.kwargs
        assert call_kwargs["sender"] == "vip@client.com"

    def test_unknown_category_falls_back_to_normal(self):
        unified = _make_unified_mock(_unified_result(category="BANANA"))
        adapter = LLMEmailAnalyzerAdapter(unified=unified)

        result = adapter.analyze(_make_email())

        assert result.classification.category == EmailCategory.NORMAL

    def test_invalid_deadline_dropped_to_none(self):
        """LLM-returned non-ISO deadlines (e.g. "demain") must not crash
        Priority.__post_init__ — the adapter drops them to None."""
        unified = _make_unified_mock(_unified_result(deadline="demain"))
        adapter = LLMEmailAnalyzerAdapter(unified=unified)

        result = adapter.analyze(_make_email())

        assert result.priority.deadline is None

    def test_iso_deadline_with_timezone_passes_through(self):
        unified = _make_unified_mock(_unified_result(deadline="2026-05-17T18:00:00Z"))
        adapter = LLMEmailAnalyzerAdapter(unified=unified)

        result = adapter.analyze(_make_email())

        assert result.priority.deadline == "2026-05-17T18:00:00Z"

    def test_out_of_range_numbers_are_clamped(self):
        unified = _make_unified_mock(_unified_result(
            urgency=200,  # > 100
            vip=-10,       # < 0
            sentiment=5.0,  # > 1
            priority_score=999,  # > 100
        ))
        adapter = LLMEmailAnalyzerAdapter(unified=unified)

        result = adapter.analyze(_make_email())

        assert result.priority.urgency == 100
        assert result.priority.vip == 0
        assert result.priority.sentiment == 1.0
        assert result.priority.priority_score == 100

    def test_confidence_clamped(self):
        unified = _make_unified_mock(_unified_result(category_confidence=2.5))
        adapter = LLMEmailAnalyzerAdapter(unified=unified)

        result = adapter.analyze(_make_email())

        assert result.classification.confidence == 1.0

    def test_garbage_confidence_falls_back_to_default(self):
        unified = _make_unified_mock(_unified_result(category_confidence="bogus"))
        adapter = LLMEmailAnalyzerAdapter(unified=unified)

        result = adapter.analyze(_make_email())

        assert result.classification.confidence == 0.5


# ----------------------------------------------------------------------------
# LLMEmailAnalyzerAdapter — legacy 2-call path (backward compat)
# ----------------------------------------------------------------------------


class TestAdapterLegacyPath:
    """Legacy 2-call path: tests still passing classifier+prioritizer keep
    working. Verifies we didn't break existing call sites/tests."""

    def test_legacy_path_calls_both_ports(self):
        classifier = Mock(spec=ClassifierPort)
        classifier.classify.return_value = Classification(
            category=EmailCategory.NORMAL, confidence=0.7, reason="ok"
        )
        prioritizer = Mock(spec=PrioritizationPort)
        prioritizer.analyze.return_value = Priority.default()

        adapter = LLMEmailAnalyzerAdapter(
            classifier=classifier, prioritizer=prioritizer
        )

        adapter.analyze(_make_email())

        classifier.classify.assert_called_once()
        prioritizer.analyze.assert_called_once()

    def test_missing_ports_raises_when_unified_is_none(self):
        """Bare adapter with no ports & no unified must fail loudly so we
        don't silently default to a broken state."""
        adapter = LLMEmailAnalyzerAdapter()
        with pytest.raises(ValueError, match="unified.*classifier.*prioritizer"):
            adapter.analyze(_make_email())


# ----------------------------------------------------------------------------
# AnalyzeEmailUseCase — analyzer port delegation
# ----------------------------------------------------------------------------


class TestAnalyzeUseCaseUnifiedPath:
    def test_analyzer_port_takes_precedence(self):
        """When `analyzer` is set, classifier+prioritizer are not invoked
        (this is the #684 win: 2 LLM calls → 1 LLM call)."""
        classifier = Mock(spec=ClassifierPort)
        prioritizer = Mock(spec=PrioritizationPort)
        analyzer = Mock(spec=EmailAnalyzerPort)
        expected = EmailAnalysis(
            email_id="email-684",
            classification=Classification(
                category=EmailCategory.URGENT, confidence=0.9, reason="x"
            ),
            priority=Priority.default(),
        )
        analyzer.analyze.return_value = expected

        use_case = AnalyzeEmailUseCase(
            classifier=classifier,
            prioritizer=prioritizer,
            analyzer=analyzer,
        )

        result = use_case.execute(_make_email())

        assert result is expected
        analyzer.analyze.assert_called_once_with(_make_email(), False)
        classifier.classify.assert_not_called()
        prioritizer.analyze.assert_not_called()

    def test_analyzer_only_construction_works(self):
        """The Container should be free to construct
        AnalyzeEmailUseCase(analyzer=...) without classifier+prioritizer."""
        analyzer = Mock(spec=EmailAnalyzerPort)
        analyzer.analyze.return_value = EmailAnalysis(
            email_id="email-684",
            classification=Classification.default(),
            priority=Priority.default(),
        )

        use_case = AnalyzeEmailUseCase(analyzer=analyzer)
        result = use_case.execute(_make_email(), is_cc=True)

        assert isinstance(result, EmailAnalysis)
        analyzer.analyze.assert_called_once_with(_make_email(), True)

    def test_legacy_construction_still_works(self):
        """Tests that don't know about analyzer keep working with
        classifier+prioritizer (regression guard for existing test suite)."""
        classifier = Mock(spec=ClassifierPort)
        classifier.classify.return_value = Classification.default()
        prioritizer = Mock(spec=PrioritizationPort)
        prioritizer.analyze.return_value = Priority.default()

        use_case = AnalyzeEmailUseCase(
            classifier=classifier, prioritizer=prioritizer
        )

        result = use_case.execute(_make_email())

        assert isinstance(result, EmailAnalysis)
        classifier.classify.assert_called_once()
        prioritizer.analyze.assert_called_once()

    def test_no_ports_raises(self):
        use_case = AnalyzeEmailUseCase()
        with pytest.raises(ValueError, match="analyzer.*classifier.*prioritizer"):
            use_case.execute(_make_email())


# ----------------------------------------------------------------------------
# Container wiring — verifies #684 is enabled by default
# ----------------------------------------------------------------------------


class TestContainerWiresUnified:
    @pytest.fixture(autouse=True)
    def reset(self):
        from app.infrastructure.container import reset_container
        reset_container()
        yield
        reset_container()

    def test_email_analyzer_has_unified_set(self):
        """Container.get_email_analyzer() must wire `unified` so the
        single-call path is taken in production."""
        from app.infrastructure.container import Container

        container = Container()
        analyzer = container.get_email_analyzer()

        assert isinstance(analyzer, LLMEmailAnalyzerAdapter)
        assert analyzer.unified is not None, (
            "Container must wire UnifiedEmailAnalyzerAgent (issue #684) — "
            "otherwise the Ollama branch still pays 2 Haiku calls per analyze."
        )

    def test_analyze_use_case_delegates_to_unified_analyzer(self):
        """Container.get_analyze_email_use_case() must route through the
        analyzer port — not directly through classifier+prioritizer."""
        from app.infrastructure.container import Container

        container = Container()
        use_case = container.get_analyze_email_use_case()

        assert use_case.analyzer is not None, (
            "Container must wire analyzer port (issue #684) so the use "
            "case fans out to 1 Haiku call instead of 2."
        )

    def test_analyzer_is_singleton(self):
        """Re-fetching get_email_analyzer() returns the same instance —
        we don't want to spawn a fresh UnifiedEmailAnalyzerAgent on every
        analyze request (would invalidate Anthropic prompt cache hints)."""
        from app.infrastructure.container import Container

        container = Container()
        a1 = container.get_email_analyzer()
        a2 = container.get_email_analyzer()

        assert a1 is a2
