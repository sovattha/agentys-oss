# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests for UnifiedEmailAnalyzerAgent (P0.1 fusion).

Locks the _sanitize defensive parsing — the surface that absorbs malformed
or hallucinated LLM output. The LLM call itself is not exercised here
(tested at integration level once daemon.py wires the agent in).
"""

from __future__ import annotations

import pytest

from app.agents import UnifiedEmailAnalyzerAgent


@pytest.fixture
def agent():
    # Use __new__ to skip __post_init__ (which calls Container) — we only
    # exercise the pure-function _sanitize / adapter helpers here.
    a = UnifiedEmailAnalyzerAgent.__new__(UnifiedEmailAnalyzerAgent)
    a.max_tokens = 1024
    a._llm = None  # not used in these tests
    return a


class TestSanitizeClosedVocabulary:
    def test_unknown_category_falls_back_to_normal(self, agent):
        out = agent._sanitize({"category": "BANANA"})
        assert out["category"] == "NORMAL"

    def test_unknown_intent_falls_back_to_other(self, agent):
        out = agent._sanitize({"intent": "BOGUS"})
        assert out["intent"] == "OTHER"

    @pytest.mark.parametrize("cat", [
        "URGENT", "IMPORTANT", "NORMAL", "NEWSLETTER", "PROMO", "CC_ONLY", "SPAM",
    ])
    def test_known_categories_pass_through(self, agent, cat):
        out = agent._sanitize({"category": cat})
        assert out["category"] == cat

    @pytest.mark.parametrize("intent", [
        "INQUIRY", "NEGOTIATION", "FOLLOW_UP", "OBJECTION",
        "ESCALATION", "INFORMATIONAL", "OTHER",
    ])
    def test_known_intents_pass_through(self, agent, intent):
        out = agent._sanitize({"intent": intent})
        assert out["intent"] == intent


class TestSanitizeNumericClamps:
    def test_urgency_clamped_high(self, agent):
        assert agent._sanitize({"urgency": 200})["urgency"] == 100

    def test_vip_clamped_low(self, agent):
        assert agent._sanitize({"vip": -10})["vip"] == 0

    def test_sentiment_clamped(self, agent):
        assert agent._sanitize({"sentiment": 5.0})["sentiment"] == 1.0
        assert agent._sanitize({"sentiment": -5.0})["sentiment"] == -1.0

    def test_priority_score_clamped(self, agent):
        assert agent._sanitize({"priority_score": 999})["priority_score"] == 100

    def test_invalid_numeric_falls_back(self, agent):
        out = agent._sanitize({
            "urgency": "abc",
            "vip": None,
            "sentiment": "high",
            "priority_score": [],
        })
        assert out["urgency"] == 50
        assert out["vip"] == 50
        assert out["sentiment"] == 0.0
        assert out["priority_score"] == 50


class TestSanitizeTasks:
    def test_drops_non_dict_entries(self, agent):
        out = agent._sanitize({"tasks": [
            "not a dict",
            42,
            None,
            {"title": "Valid task", "priority": "high"},
        ]})
        assert len(out["tasks"]) == 1
        assert out["tasks"][0]["title"] == "Valid task"

    def test_drops_empty_titles(self, agent):
        out = agent._sanitize({"tasks": [
            {"title": "", "priority": "high"},
            {"title": "   ", "priority": "high"},
            {"title": "Real", "priority": "low"},
        ]})
        assert len(out["tasks"]) == 1
        assert out["tasks"][0]["title"] == "Real"

    def test_caps_at_five_tasks(self, agent):
        out = agent._sanitize({"tasks": [
            {"title": f"Task {i}", "priority": "medium"} for i in range(20)
        ]})
        assert len(out["tasks"]) == 5

    def test_truncates_title_to_50_chars(self, agent):
        out = agent._sanitize({"tasks": [
            {"title": "X" * 100, "priority": "medium"},
        ]})
        assert len(out["tasks"][0]["title"]) == 50

    def test_normalizes_unknown_priority_to_medium(self, agent):
        out = agent._sanitize({"tasks": [
            {"title": "T", "priority": "WEIRD"},
        ]})
        assert out["tasks"][0]["priority"] == "medium"

    def test_non_list_tasks_falls_back_to_empty(self, agent):
        out = agent._sanitize({"tasks": "not a list"})
        assert out["tasks"] == []

    def test_invalid_deadline_becomes_none(self, agent):
        out = agent._sanitize({"tasks": [
            {"title": "T", "deadline": 12345, "priority": "low"},
        ]})
        assert out["tasks"][0]["deadline"] is None


class TestSanitizeDefensive:
    def test_none_input_returns_defaults(self, agent):
        out = agent._sanitize(None)
        assert out["category"] == "NORMAL"
        assert out["intent"] == "OTHER"
        assert out["tasks"] == []

    def test_non_dict_input_returns_defaults(self, agent):
        out = agent._sanitize("not a dict")
        assert out["category"] == "NORMAL"

    def test_deadline_string_passes_through(self, agent):
        out = agent._sanitize({"deadline": "2026-05-10"})
        assert out["deadline"] == "2026-05-10"

    def test_deadline_non_string_becomes_none(self, agent):
        out = agent._sanitize({"deadline": 12345})
        assert out["deadline"] is None


class TestAdapters:
    def test_to_classification_shape(self, agent):
        result = {
            "category": "URGENT",
            "category_confidence": 0.9,
            "urgency": 80,
        }
        out = agent.to_classification(result)
        assert out == {
            "category": "URGENT",
            "confidence": 0.9,
            "reason": "unified analyzer",
        }

    def test_to_priority_shape(self, agent):
        result = {
            "urgency": 70,
            "vip": 80,
            "sentiment": -0.5,
            "deadline": "2026-05-10",
            "priority_score": 75,
        }
        out = agent.to_priority(result)
        assert out["urgency"] == 70
        assert out["vip"] == 80
        assert out["sentiment"] == -0.5
        assert out["deadline"] == "2026-05-10"
        assert out["priority_score"] == 75

    def test_to_tasks_returns_list(self, agent):
        result = {"tasks": [{"title": "X", "priority": "high"}]}
        out = agent.to_tasks(result)
        assert isinstance(out, list)
        assert len(out) == 1

    def test_to_tasks_handles_missing_key(self, agent):
        out = agent.to_tasks({})
        assert out == []
