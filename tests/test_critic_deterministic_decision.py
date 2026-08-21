# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests for the deterministic decision rule in CriticAgent.

Audit 2026-05-04 (ground-truth eval) : we measured Haiku Critic emit
``decision: reject`` on drafts with ``overall=87, no dim<50`` because of
stylistic preferences ("ajouter signature complète"). The fix : compute
the decision DETERMINISTICALLY in code from the scores + placeholder
presence, ignoring the LLM's own ``decision`` field.

These tests pin the contract :

- placeholder in draft → REJECT (regardless of scores or LLM verdict)
- any score < 50 → REJECT (cliff edge, with sub50 dim listed in suggestion)
- mean score < quality_threshold → REJECT
- else → VALID, even if the LLM emitted ``decision: reject``

Eval result : 60-case ground truth went from 31 % FP / 33 % FN to
22 % FP / 0 % FN with this rule live.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.agents import CriticAgent, _PLACEHOLDER_MARKERS, _draft_has_placeholder
from app.domain.entities import TokenUsage as TokenCounter
from app.domain.entities.critique import (
    CritiqueDecision,
    CritiqueRequest,
)
from app.domain.ports import LLMResponse


@pytest.fixture
def mock_container():
    container = MagicMock()
    container.token_usage = TokenCounter()
    container.llm = MagicMock()
    container.llm_label = container.llm
    container.llm_drafting = container.llm
    container.llm_background = container.llm
    return container


def _llm_says(scores: dict, decision: str = "valid", suggestions: list | None = None) -> str:
    """Build a JSON response mimicking what the LLM emits."""
    payload = {**scores, "decision": decision, "suggestions": suggestions or [],
               "explanation": "test"}
    return json.dumps(payload)


def _good_scores() -> dict:
    """All seven dimensions at 85 → mean 85, no sub50, should be VALID by rule."""
    return {
        "coherence": 85, "tone": 85, "completeness": 85, "errors": 85,
        "conciseness": 85, "over_commitment": 85, "emotional_intelligence": 85,
    }


# ---------------------------------------------------------------------------
# _draft_has_placeholder — pure function
# ---------------------------------------------------------------------------


class TestPlaceholderDetector:
    def test_detects_a_confirmer_uppercase(self):
        assert _draft_has_placeholder("Le RDV est [À confirmer] mardi.") is True

    def test_detects_a_confirmer_lowercase(self):
        assert _draft_has_placeholder("Le RDV est [à confirmer] mardi.") is True

    def test_detects_tbd(self):
        assert _draft_has_placeholder("Price: [TBD]. Will update.") is True

    def test_detects_a_valider(self):
        assert _draft_has_placeholder("Quote [à valider] avant signature.") is True

    def test_detects_placeholder_prefix(self):
        assert _draft_has_placeholder("Send to [placeholder_name].") is True

    def test_detects_x_marker(self):
        assert _draft_has_placeholder("Available [X] hours per week.") is True

    def test_clean_draft_passes(self):
        assert _draft_has_placeholder("Bonjour Alice, c'est confirmé.") is False

    def test_empty_draft_returns_false(self):
        assert _draft_has_placeholder("") is False
        assert _draft_has_placeholder(None) is False  # type: ignore[arg-type]

    def test_marker_inventory_covers_canonical_forms(self):
        """The module-level allow-list should cover the most common French and
        English placeholder shapes. If any are missing, the FN safety hole reopens.
        """
        canonical = ("[À confirmer]", "[à confirmer]", "[TBD]", "[à valider]")
        for m in canonical:
            assert m in _PLACEHOLDER_MARKERS, f"missing canonical marker {m!r}"


# ---------------------------------------------------------------------------
# CriticAgent decision logic — ignores LLM `decision` field, deterministic
# ---------------------------------------------------------------------------


class TestDeterministicDecision:
    """Pin the rule : ``decision`` comes from scores + placeholder, not LLM."""

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_llm_says_reject_but_scores_clean_yields_valid(
        self, mock_kb, mock_get_container, mock_container,
    ):
        """The dominant fix : LLM says reject with high scores → override to VALID.

        The 2026-05-04 ground-truth eval observed the LLM emit
        ``decision: reject`` with overall=87 and no dim<50 because it
        wanted to suggest "ajouter signature complète". The deterministic
        rule must trump the LLM here.
        """
        mock_kb.return_value = "KB"
        mock_container.llm.complete.return_value = LLMResponse(
            content=_llm_says(_good_scores(), decision="reject",
                              suggestions=["Ajouter signature complète"]),
            input_tokens=300, output_tokens=50, model="haiku",
        )
        mock_get_character = mock_get_container
        mock_get_character.return_value = mock_container

        agent = CriticAgent()
        result = agent.evaluate_draft(CritiqueRequest(
            draft_content="Bonjour Alice, c'est confirmé. À demain.",
            original_email="Tu confirmes pour mardi ?",
        ))
        assert result.decision == CritiqueDecision.VALID

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_placeholder_in_draft_overrides_high_scores(
        self, mock_kb, mock_get_container, mock_container,
    ):
        """A draft with `[À confirmer]` must REJECT even if scores are perfect.

        This was the safety hole : 5/15 bad drafts (all containing
        placeholders) were validated by Haiku Critic with overall ≥ 77.
        """
        mock_kb.return_value = "KB"
        mock_container.llm.complete.return_value = LLMResponse(
            content=_llm_says(_good_scores(), decision="valid"),
            input_tokens=300, output_tokens=50, model="haiku",
        )
        mock_get_container.return_value = mock_container

        agent = CriticAgent()
        result = agent.evaluate_draft(CritiqueRequest(
            draft_content="Le RDV est [À confirmer] avec Alice.",
            original_email="Quand est le RDV ?",
        ))
        assert result.decision == CritiqueDecision.REJECT
        # The suggestions must explain why so V2 has actionable feedback.
        assert any("placeholder" in s.lower() or "à confirmer" in s.lower()
                   for s in result.suggestions), result.suggestions

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_sub50_dimension_forces_reject(
        self, mock_kb, mock_get_container, mock_container,
    ):
        """Cliff-edge rule preserved : a single dim < 50 → REJECT.

        The LLM emits ``decision: valid`` but the deterministic rule must
        catch the sub-50 dim.
        """
        scores = _good_scores()
        scores["tone"] = 35  # one dim below the cliff
        mock_kb.return_value = "KB"
        mock_container.llm.complete.return_value = LLMResponse(
            content=_llm_says(scores, decision="valid"),
            input_tokens=300, output_tokens=50, model="haiku",
        )
        mock_get_container.return_value = mock_container

        agent = CriticAgent()
        result = agent.evaluate_draft(CritiqueRequest(
            draft_content="Casual draft with tone issue.",
            original_email="Hi",
        ))
        assert result.decision == CritiqueDecision.REJECT
        assert any("tone" in s.lower() or "seuil" in s.lower() or "score" in s.lower()
                   for s in result.suggestions), result.suggestions

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_overall_below_threshold_yields_reject(
        self, mock_kb, mock_get_container, mock_container,
    ):
        """No sub50, no placeholder, but mean below threshold → REJECT."""
        scores = {
            "coherence": 65, "tone": 65, "completeness": 65, "errors": 65,
            "conciseness": 65, "over_commitment": 65, "emotional_intelligence": 65,
        }  # overall = 65 < 70
        mock_kb.return_value = "KB"
        mock_container.llm.complete.return_value = LLMResponse(
            content=_llm_says(scores, decision="valid"),
            input_tokens=300, output_tokens=50, model="haiku",
        )
        mock_get_container.return_value = mock_container

        agent = CriticAgent()  # default threshold 70
        result = agent.evaluate_draft(CritiqueRequest(
            draft_content="Mediocre draft.",
            original_email="Question",
        ))
        assert result.decision == CritiqueDecision.REJECT
        assert any("seuil" in s.lower() or "score" in s.lower()
                   for s in result.suggestions), result.suggestions

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_clean_high_scores_yields_valid_even_if_llm_says_reject(
        self, mock_kb, mock_get_container, mock_container,
    ):
        """End-to-end : the most important contract — clean draft + good
        scores + LLM disagreeing → still VALID."""
        mock_kb.return_value = "KB"
        mock_container.llm.complete.return_value = LLMResponse(
            content=_llm_says(_good_scores(), decision="reject",
                              suggestions=["Stylistic nitpick"]),
            input_tokens=300, output_tokens=50, model="haiku",
        )
        mock_get_container.return_value = mock_container

        agent = CriticAgent()
        result = agent.evaluate_draft(CritiqueRequest(
            draft_content="Bonjour, c'est confirmé. À demain.",
            original_email="Confirmes-tu ?",
        ))
        assert result.decision == CritiqueDecision.VALID
        # Suggestions still surfaced as informational hints — they just don't
        # promote to REJECT.
        assert "Stylistic nitpick" in result.suggestions
