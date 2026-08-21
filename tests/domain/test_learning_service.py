# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour app.domain.services.learning_service."""

from unittest.mock import MagicMock

from app.domain.entities.learning import (
    LearningInsights,
    LearnedPattern,
    PromptAdjustment,
    ReviewRequirement,
)
from app.domain.services.learning_service import LearningService


def _make_service(**overrides) -> LearningService:
    """Factory pour créer un LearningService avec des mocks."""
    defaults = dict(
        analyze_use_case=MagicMock(),
        extract_use_case=MagicMock(),
        should_review_use_case=MagicMock(),
        generate_adjustment_use_case=MagicMock(),
        stats_use_case=MagicMock(),
        enhance_prompt_use_case=MagicMock(),
        get_active_adjustments_use_case=None,
    )
    defaults.update(overrides)
    return LearningService(**defaults)


# ── analyze_feedback ─────────────────────────────────────────────────────────

class TestAnalyzeFeedback:
    def test_returns_dict_from_insights(self):
        insights = LearningInsights(
            total_with_feedback=10,
            good_count=7,
            bad_count=2,
            neutral_count=1,
            v1_good_rate=0.6,
            v2_good_rate=0.8,
            common_issues=["trop long"],
            strengths=["bon ton"],
        )
        mock_analyze = MagicMock()
        mock_analyze.execute.return_value = insights

        service = _make_service(analyze_use_case=mock_analyze)
        result = service.analyze_feedback()

        assert result["total_with_feedback"] == 10
        assert result["good_count"] == 7
        assert result["bad_count"] == 2
        assert result["neutral_count"] == 1
        assert result["v1_good_rate"] == 0.6
        assert result["v2_good_rate"] == 0.8
        assert result["common_issues"] == ["trop long"]
        assert result["strengths"] == ["bon ton"]
        mock_analyze.execute.assert_called_once()


# ── extract_patterns_from_feedback ───────────────────────────────────────────

class TestExtractPatterns:
    def test_delegates_to_use_case(self):
        patterns = [MagicMock(spec=LearnedPattern)]
        mock_extract = MagicMock()
        mock_extract.execute.return_value = patterns

        service = _make_service(extract_use_case=mock_extract)
        result = service.extract_patterns_from_feedback()

        assert result == patterns
        mock_extract.execute.assert_called_once()


# ── generate_prompt_adjustment ───────────────────────────────────────────────

class TestGeneratePromptAdjustment:
    def test_returns_adjustment(self):
        adj = MagicMock(spec=PromptAdjustment)
        mock_gen = MagicMock()
        mock_gen.execute.return_value = adj

        service = _make_service(generate_adjustment_use_case=mock_gen)
        result = service.generate_prompt_adjustment()

        assert result is adj

    def test_returns_none_when_no_adjustment(self):
        mock_gen = MagicMock()
        mock_gen.execute.return_value = None

        service = _make_service(generate_adjustment_use_case=mock_gen)
        assert service.generate_prompt_adjustment() is None


# ── should_require_review ────────────────────────────────────────────────────

class TestShouldRequireReview:
    def test_returns_true_when_review_needed(self):
        req = ReviewRequirement(needs_review=True, reasons=["high priority"])
        mock_review = MagicMock()
        mock_review.execute.return_value = req

        service = _make_service(should_review_use_case=mock_review)
        assert service.should_require_review("content", 90) is True
        mock_review.execute.assert_called_once_with(
            email_content="content", priority_score=90
        )

    def test_returns_false_when_no_review_needed(self):
        req = ReviewRequirement(needs_review=False, reasons=[])
        mock_review = MagicMock()
        mock_review.execute.return_value = req

        service = _make_service(should_review_use_case=mock_review)
        assert service.should_require_review("content", 10) is False


# ── get_review_requirement ───────────────────────────────────────────────────

class TestGetReviewRequirement:
    def test_returns_full_requirement(self):
        req = ReviewRequirement(needs_review=True, reasons=["sensitive topic"])
        mock_review = MagicMock()
        mock_review.execute.return_value = req

        service = _make_service(should_review_use_case=mock_review)
        result = service.get_review_requirement("body", 50)

        assert result.needs_review is True
        assert "sensitive topic" in result.reasons


# ── get_active_adjustments ───────────────────────────────────────────────────

class TestGetActiveAdjustments:
    def test_with_dedicated_use_case(self):
        mock_active = MagicMock()
        mock_active.execute.return_value = ["rule1", "rule2"]

        service = _make_service(get_active_adjustments_use_case=mock_active)
        result = service.get_active_adjustments()

        assert result == ["rule1", "rule2"]
        mock_active.execute.assert_called_once()

    def test_fallback_parses_enhanced_prompt(self):
        mock_enhance = MagicMock()
        mock_enhance.execute.return_value = "- Toujours vouvoyer\n- Rester concis"

        service = _make_service(enhance_prompt_use_case=mock_enhance)
        result = service.get_active_adjustments()

        assert "Toujours vouvoyer" in result
        assert "Rester concis" in result

    def test_fallback_empty_prompt(self):
        mock_enhance = MagicMock()
        mock_enhance.execute.return_value = ""

        service = _make_service(enhance_prompt_use_case=mock_enhance)
        result = service.get_active_adjustments()

        assert result == []


# ── get_stats ────────────────────────────────────────────────────────────────

class TestGetStats:
    def test_delegates(self):
        mock_stats = MagicMock()
        mock_stats.execute.return_value = {"total": 42}

        service = _make_service(stats_use_case=mock_stats)
        assert service.get_stats() == {"total": 42}


# ── enhance_prompt ───────────────────────────────────────────────────────────

class TestEnhancePrompt:
    def test_enhances_base_prompt(self):
        mock_enhance = MagicMock()
        mock_enhance.execute.return_value = "base + learned rules"

        service = _make_service(enhance_prompt_use_case=mock_enhance)
        result = service.enhance_prompt("base")

        assert result == "base + learned rules"
        mock_enhance.execute.assert_called_once_with("base")
