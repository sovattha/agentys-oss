# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests for the onboarding orchestrator (full pipeline with mocked LLM)."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.domain.ports.llm_port import LLMResponse
from app.onboarding.loader import FixtureLoader
from app.onboarding.indexer import EmailIndexer
from app.onboarding.orchestrator import OnboardingOrchestrator, OnboardingResult

FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "test_emails.json"


@pytest.fixture
def indexed():
    """Load and index fixture emails."""
    loader = FixtureLoader(FIXTURE_PATH)
    emails, metadata = loader.load()
    indexer = EmailIndexer(metadata["user_email"])
    return indexer.index(emails)


def _make_mock_responses():
    """Create 4 mock LLM responses for the 4 agents (profile, knowledge, style, label)."""
    return [
        LLMResponse(
            content=json.dumps({
                "user_email": "sophie.martin@techcorp.fr",
                "user_name": "Sophie Martin",
                "languages": ["fr", "en"],
            }),
            input_tokens=100, output_tokens=50, model="mock",
        ),
        LLMResponse(
            content=json.dumps({
                "contacts": [{"email": "pierre@test.com", "name": "Pierre", "type": "colleague"}],
                "projects": [{"name": "Alpha", "description": "Main", "status": "active"}],
                "terminology": {},
            }),
            input_tokens=200, output_tokens=80, model="mock",
        ),
        LLMResponse(
            content=json.dumps({
                "contact_rules": [{"contact_email": "pierre@test.com", "tone": "casual", "language": "fr", "greeting": "Pierre,", "closing": "Sophie"}],
                "general_rules": [],
                "forbidden_phrases": [],
            }),
            input_tokens=150, output_tokens=60, model="mock",
        ),
        LLMResponse(
            content=json.dumps({
                "default_label_rules": [{"label_name": "Action", "condition_type": "needs_reply", "confidence": 0.9}],
                "suggested_labels": [],
                "custom_label_rules": [],
            }),
            input_tokens=100, output_tokens=40, model="mock",
        ),
    ]


def _mock_worker(response: LLMResponse) -> MagicMock:
    """Create an isolated worker mock for one parallel onboarding agent."""
    worker = MagicMock()
    worker.complete.return_value = response
    return worker


class TestOnboardingOrchestrator:
    """Tests for OnboardingOrchestrator."""

    def test_run_completes_successfully(self, indexed):
        profile, knowledge, style, label = _make_mock_responses()

        with patch("app.onboarding.agents.profile_agent.get_container") as p1, \
             patch("app.onboarding.agents.knowledge_agent.get_container") as p2, \
             patch("app.onboarding.agents.style_agent.get_container") as p3, \
             patch("app.onboarding.agents.label_agent.get_container") as p4:
            p1.return_value.llm_onboarding_worker = _mock_worker(profile)
            p2.return_value.llm_onboarding_worker = _mock_worker(knowledge)
            p3.return_value.llm_onboarding_worker = _mock_worker(style)
            p4.return_value.llm_onboarding_worker = _mock_worker(label)

            orchestrator = OnboardingOrchestrator()
            result = orchestrator.run(indexed)

        assert isinstance(result, OnboardingResult)
        assert result.status == "completed"
        assert result.emails_analysed == 100
        assert result.profile["user_name"] == "Sophie Martin"
        assert len(result.knowledge["contacts"]) >= 1
        assert len(result.style["contact_rules"]) >= 1

    def test_progress_events_emitted(self, indexed):
        profile, knowledge, style, label = _make_mock_responses()

        events = []

        with patch("app.onboarding.agents.profile_agent.get_container") as p1, \
             patch("app.onboarding.agents.knowledge_agent.get_container") as p2, \
             patch("app.onboarding.agents.style_agent.get_container") as p3, \
             patch("app.onboarding.agents.label_agent.get_container") as p4:
            p1.return_value.llm_onboarding_worker = _mock_worker(profile)
            p2.return_value.llm_onboarding_worker = _mock_worker(knowledge)
            p3.return_value.llm_onboarding_worker = _mock_worker(style)
            p4.return_value.llm_onboarding_worker = _mock_worker(label)

            orchestrator = OnboardingOrchestrator(on_progress=lambda p: events.append(p))
            orchestrator.run(indexed)

        # 9 events: 1 initial + (running + completed) for each of the 4 agents
        assert len(events) == 9
        steps = [e.step for e in events]
        assert steps[0] == "all"  # initial parallel launch event
        assert steps.count("profile") == 2
        assert steps.count("knowledge") == 2
        assert steps.count("style") == 2
        assert steps.count("label") == 2
        # Final event should be 100%
        assert events[-1].progress == 100

    def test_handles_agent_failure(self, indexed):
        mock_llm = MagicMock()
        mock_llm.complete.side_effect = Exception("LLM unavailable")

        events = []

        with patch("app.onboarding.agents.profile_agent.get_container") as p1, \
             patch("app.onboarding.agents.knowledge_agent.get_container") as p2, \
             patch("app.onboarding.agents.style_agent.get_container") as p3, \
             patch("app.onboarding.agents.label_agent.get_container") as p4:
            p1.return_value.llm_onboarding_worker = mock_llm
            p2.return_value.llm_onboarding_worker = mock_llm
            p3.return_value.llm_onboarding_worker = mock_llm
            p4.return_value.llm_onboarding_worker = mock_llm

            orchestrator = OnboardingOrchestrator(on_progress=lambda p: events.append(p))
            result = orchestrator.run(indexed)

        assert result.status == "failed"
        assert result.error is not None

    def test_duration_tracked(self, indexed):
        profile, knowledge, style, label = _make_mock_responses()

        with patch("app.onboarding.agents.profile_agent.get_container") as p1, \
             patch("app.onboarding.agents.knowledge_agent.get_container") as p2, \
             patch("app.onboarding.agents.style_agent.get_container") as p3, \
             patch("app.onboarding.agents.label_agent.get_container") as p4:
            p1.return_value.llm_onboarding_worker = _mock_worker(profile)
            p2.return_value.llm_onboarding_worker = _mock_worker(knowledge)
            p3.return_value.llm_onboarding_worker = _mock_worker(style)
            p4.return_value.llm_onboarding_worker = _mock_worker(label)

            orchestrator = OnboardingOrchestrator()
            result = orchestrator.run(indexed)

        assert result.duration_seconds >= 0.0
