# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests for the EvaluationAgent."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.domain.ports.llm_port import LLMResponse
from app.onboarding.agents.evaluation_agent import EvaluationAgent, EvaluationResult

GROUND_TRUTH_PATH = Path(__file__).parent.parent / "fixtures" / "ground_truth.json"


@pytest.fixture
def ground_truth():
    with open(GROUND_TRUTH_PATH) as f:
        return json.load(f)


@pytest.fixture
def mock_analysis_output():
    """Simulated analysis output matching ground truth."""
    return {
        "profile": {
            "user_email": "sophie.martin@techcorp.fr",
            "user_name": "Sophie Martin",
            "languages": ["fr", "en"],
        },
        "knowledge": {
            "contacts": [
                {"email": "pierre.durand@techcorp.fr", "name": "Pierre Durand", "type": "colleague"},
                {"email": "lucas.bernard@techcorp.fr", "name": "Lucas Bernard", "type": "direct_report"},
                {"email": "marie.leclerc@clientcorp.com", "name": "Marie Leclerc", "type": "client"},
            ],
            "projects": [
                {"name": "Alpha", "description": "Main project", "status": "active"},
            ],
        },
        "rules": {
            "contact_rules": [
                {"contact_email": "pierre.durand@techcorp.fr", "tone": "casual", "language": "fr", "greeting": "Pierre,", "closing": "Sophie"},
                {"contact_email": "marie.leclerc@clientcorp.com", "tone": "formal", "language": "fr", "greeting": "Bonjour Madame Leclerc,", "closing": "Cordialement,"},
            ],
            "general_rules": [],
        },
    }


class TestEvaluationAgentHeuristic:
    """Tests for the heuristic (no-LLM) evaluation."""

    def test_evaluate_without_llm(self, mock_analysis_output, ground_truth):
        with patch("app.onboarding.agents.evaluation_agent.get_container"):
            agent = EvaluationAgent()
        result = agent.evaluate_without_llm(mock_analysis_output, ground_truth)

        assert isinstance(result, EvaluationResult)
        # Profile should score well since name and email match
        assert result.profile_score.overall > 50
        # Knowledge should have partial recall (3 out of 13 contacts)
        assert result.knowledge_score.completeness > 0
        assert result.overall_score >= 0

    def test_empty_output_scores_zero(self, ground_truth):
        with patch("app.onboarding.agents.evaluation_agent.get_container"):
            agent = EvaluationAgent()
        result = agent.evaluate_without_llm({}, ground_truth)

        assert result.profile_score.overall == 0
        assert result.knowledge_score.overall == 0
        assert result.rules_score.overall == 0

    def test_perfect_output_scores_high(self, ground_truth):
        """Construct output that matches ground truth perfectly."""
        perfect_output = {
            "profile": {
                "user_email": "sophie.martin@techcorp.fr",
                "user_name": "Sophie Martin",
                "languages": ["fr", "en"],
            },
            "knowledge": {
                "contacts": ground_truth["expected_contacts"],
            },
            "rules": ground_truth["expected_rules"],
        }
        with patch("app.onboarding.agents.evaluation_agent.get_container"):
            agent = EvaluationAgent()
        result = agent.evaluate_without_llm(perfect_output, ground_truth)

        assert result.profile_score.overall == 100
        assert result.knowledge_score.overall == 100
        assert result.rules_score.overall == 100
        assert result.overall_score == 100

    def test_missing_contacts_listed(self, mock_analysis_output, ground_truth):
        with patch("app.onboarding.agents.evaluation_agent.get_container"):
            agent = EvaluationAgent()
        result = agent.evaluate_without_llm(mock_analysis_output, ground_truth)

        # Should list missing contacts
        assert len(result.knowledge_score.missing) > 0
        assert "camille.roux@techcorp.fr" in result.knowledge_score.missing


class TestEvaluationAgentLLM:
    """Tests for the LLM-based evaluation (with mocked LLM)."""

    def test_evaluate_with_llm(self, mock_analysis_output, ground_truth):
        mock_llm = MagicMock()
        eval_response = json.dumps({
            "completeness": 70,
            "precision": 85,
            "usefulness": 80,
            "overall": 78,
            "details": "Good coverage of main contacts",
            "missing": ["camille.roux@techcorp.fr"],
            "incorrect": [],
        })
        mock_llm.complete.return_value = LLMResponse(
            content=eval_response, input_tokens=100, output_tokens=50, model="mock",
        )

        with patch("app.onboarding.agents.evaluation_agent.get_container") as mock_c:
            mock_c.return_value.llm_onboarding = mock_llm
            agent = EvaluationAgent()
            result = agent.evaluate(mock_analysis_output, ground_truth)

        assert isinstance(result, EvaluationResult)
        # LLM is called 3 times (profile, knowledge, rules)
        assert mock_llm.complete.call_count == 3
        assert result.overall_score > 0
