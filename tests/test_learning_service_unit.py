# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour LearningService."""

from unittest.mock import MagicMock
from app.domain.services.learning_service import LearningService
from app.domain.entities.learning import (
    LearningInsights,
    LearnedPattern,
    PromptAdjustment,
    ReviewRequirement,
)


def _make_service(**kwargs):
    """Helper pour créer un LearningService avec des mocks."""
    defaults = {
        "analyze_use_case": MagicMock(),
        "extract_use_case": MagicMock(),
        "should_review_use_case": MagicMock(),
        "generate_adjustment_use_case": MagicMock(),
        "stats_use_case": MagicMock(),
        "enhance_prompt_use_case": MagicMock(),
    }
    defaults.update(kwargs)
    return LearningService(**defaults)


class TestAnalyzeFeedback:
    """Tests pour analyze_feedback."""

    def test_returns_dict_with_all_keys(self):
        insights = LearningInsights(
            total_with_feedback=100,
            good_count=70,
            bad_count=20,
            neutral_count=10,
            v1_good_rate=0.6,
            v2_good_rate=0.8,
            common_issues=["tone"],
            strengths=["clarity"],
        )
        analyze = MagicMock()
        analyze.execute.return_value = insights
        service = _make_service(analyze_use_case=analyze)

        result = service.analyze_feedback()

        assert result["total_with_feedback"] == 100
        assert result["good_count"] == 70
        assert result["bad_count"] == 20
        assert result["neutral_count"] == 10
        assert result["v1_good_rate"] == 0.6
        assert result["v2_good_rate"] == 0.8
        assert result["common_issues"] == ["tone"]
        assert result["strengths"] == ["clarity"]

    def test_calls_execute(self):
        analyze = MagicMock()
        analyze.execute.return_value = LearningInsights(
            total_with_feedback=0, good_count=0, bad_count=0,
            neutral_count=0, v1_good_rate=0, v2_good_rate=0,
            common_issues=[], strengths=[],
        )
        service = _make_service(analyze_use_case=analyze)

        service.analyze_feedback()

        analyze.execute.assert_called_once()


class TestExtractPatterns:
    """Tests pour extract_patterns_from_feedback."""

    def test_returns_patterns(self):
        patterns = [MagicMock(spec=LearnedPattern)]
        extract = MagicMock()
        extract.execute.return_value = patterns
        service = _make_service(extract_use_case=extract)

        result = service.extract_patterns_from_feedback()

        assert result == patterns
        extract.execute.assert_called_once()


class TestGeneratePromptAdjustment:
    """Tests pour generate_prompt_adjustment."""

    def test_returns_adjustment(self):
        adj = MagicMock(spec=PromptAdjustment)
        gen = MagicMock()
        gen.execute.return_value = adj
        service = _make_service(generate_adjustment_use_case=gen)

        result = service.generate_prompt_adjustment()

        assert result == adj

    def test_returns_none_when_no_adjustment(self):
        gen = MagicMock()
        gen.execute.return_value = None
        service = _make_service(generate_adjustment_use_case=gen)

        result = service.generate_prompt_adjustment()

        assert result is None


class TestShouldRequireReview:
    """Tests pour should_require_review."""

    def test_returns_true(self):
        req = ReviewRequirement(needs_review=True, reasons=["high priority"])
        review_uc = MagicMock()
        review_uc.execute.return_value = req
        service = _make_service(should_review_use_case=review_uc)

        result = service.should_require_review("email content", 90)

        assert result is True
        review_uc.execute.assert_called_once_with(
            email_content="email content",
            priority_score=90,
        )

    def test_returns_false(self):
        req = ReviewRequirement(needs_review=False, reasons=[])
        review_uc = MagicMock()
        review_uc.execute.return_value = req
        service = _make_service(should_review_use_case=review_uc)

        result = service.should_require_review("normal email", 30)

        assert result is False


class TestGetReviewRequirement:
    """Tests pour get_review_requirement."""

    def test_returns_full_requirement(self):
        req = ReviewRequirement(needs_review=True, reasons=["sensitive", "high priority"])
        review_uc = MagicMock()
        review_uc.execute.return_value = req
        service = _make_service(should_review_use_case=review_uc)

        result = service.get_review_requirement("email", 85)

        assert result.needs_review is True
        assert len(result.reasons) == 2


class TestGetActiveAdjustments:
    """Tests pour get_active_adjustments."""

    def test_with_dedicated_use_case(self):
        active_uc = MagicMock()
        active_uc.execute.return_value = ["rule1", "rule2"]
        service = _make_service(get_active_adjustments_use_case=active_uc)

        result = service.get_active_adjustments()

        assert result == ["rule1", "rule2"]
        active_uc.execute.assert_called_once()

    def test_fallback_to_enhance_prompt_empty(self):
        enhance = MagicMock()
        enhance.execute.return_value = ""
        service = _make_service(enhance_prompt_use_case=enhance)

        result = service.get_active_adjustments()

        assert result == []

    def test_fallback_to_enhance_prompt_with_lines(self):
        enhance = MagicMock()
        enhance.execute.return_value = "- Use formal tone\n- Always greet"
        service = _make_service(enhance_prompt_use_case=enhance)

        result = service.get_active_adjustments()

        assert "Use formal tone" in result
        assert "Always greet" in result


class TestGetStats:
    """Tests pour get_stats."""

    def test_returns_stats(self):
        stats_uc = MagicMock()
        stats_uc.execute.return_value = {"total": 100, "good": 80}
        service = _make_service(stats_use_case=stats_uc)

        result = service.get_stats()

        assert result == {"total": 100, "good": 80}


class TestEnhancePrompt:
    """Tests pour enhance_prompt."""

    def test_enhances_prompt(self):
        enhance = MagicMock()
        enhance.execute.return_value = "Base prompt + learned rules"
        service = _make_service(enhance_prompt_use_case=enhance)

        result = service.enhance_prompt("Base prompt")

        assert result == "Base prompt + learned rules"
        enhance.execute.assert_called_once_with("Base prompt")

    def test_empty_base_prompt(self):
        enhance = MagicMock()
        enhance.execute.return_value = ""
        service = _make_service(enhance_prompt_use_case=enhance)

        result = service.enhance_prompt("")

        assert result == ""
