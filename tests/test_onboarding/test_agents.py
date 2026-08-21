# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests for the onboarding analysis agents (with mocked LLM)."""

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.domain.ports.llm_port import LLMResponse
from app.onboarding.loader import FixtureLoader, OnboardingEmail
from app.onboarding.indexer import EmailIndexer
from app.onboarding.schemas import EmailDirection
from app.onboarding.agents.profile_agent import ProfileAgent
from app.onboarding.agents.knowledge_agent import KnowledgeAgent
from app.onboarding.agents.style_agent import StyleAgent

FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "test_emails.json"
GROUND_TRUTH_PATH = Path(__file__).parent.parent / "fixtures" / "ground_truth.json"


@pytest.fixture
def indexed():
    """Load and index fixture emails."""
    loader = FixtureLoader(FIXTURE_PATH)
    emails, metadata = loader.load()
    indexer = EmailIndexer(metadata["user_email"])
    return indexer.index(emails)


@pytest.fixture
def ground_truth():
    """Load ground truth expectations."""
    with open(GROUND_TRUTH_PATH) as f:
        return json.load(f)


@pytest.fixture
def mock_llm():
    """Create a mock LLM that returns pre-configured responses."""
    mock = MagicMock()
    mock.name = "mock-llm"
    mock.model = "mock-model"
    return mock


class TestProfileAgent:
    """Tests for ProfileAgent."""

    def test_analyse_returns_profile_dict(self, indexed, mock_llm):
        mock_response = LLMResponse(
            content=json.dumps({
                "user_email": "sophie.martin@techcorp.fr",
                "user_name": "Sophie Martin",
                "profession": "cheffe de projet informatique",
                "signature": {"full_text": "Sophie Martin\nChef de projet", "name": "Sophie Martin"},
                "tone": {"default_tone": "semi-formal"},
                "languages": ["fr", "en"],
            }),
            input_tokens=100,
            output_tokens=50,
            model="mock",
        )
        mock_llm.complete.return_value = mock_response

        with patch("app.onboarding.agents.profile_agent.get_container") as mock_container:
            mock_container.return_value.llm_onboarding_worker = mock_llm
            agent = ProfileAgent()
            result = agent.analyse(indexed)

        assert result["user_email"] == "sophie.martin@techcorp.fr"
        assert result["user_name"] == "Sophie Martin"
        assert result["profession"] == "cheffe de projet informatique"
        assert result["profession_confirmed"] is False
        assert "signature" in result
        assert "fr" in result["languages"]

    def test_analyse_handles_malformed_llm_response(self, indexed, mock_llm):
        mock_llm.complete.return_value = LLMResponse(
            content="Not valid JSON at all",
            input_tokens=10, output_tokens=5, model="mock",
        )

        with patch("app.onboarding.agents.profile_agent.get_container") as mock_container:
            mock_container.return_value.llm_onboarding_worker = mock_llm
            agent = ProfileAgent()
            result = agent.analyse(indexed)

        # Should return defaults, not crash
        assert result["user_email"] == "sophie.martin@techcorp.fr"
        assert result["profession"] == ""
        assert result["profession_confirmed"] is False
        assert "languages" in result

    def test_sample_selection_limits_emails(self, indexed):
        with patch("app.onboarding.agents.profile_agent.get_container") as mock_container:
            mock_container.return_value.llm_onboarding_worker = MagicMock()
            agent = ProfileAgent()
            sample = agent._select_sample(indexed)
            assert len(sample) <= 30


class TestKnowledgeAgent:
    """Tests for KnowledgeAgent."""

    def test_analyse_returns_knowledge_dict(self, indexed, mock_llm):
        # "projects", "terminology" and "faq" are deliberately NOT part of
        # the allowed schema — KnowledgeAgent filters them out (see
        # _FORBIDDEN_KEYS). The mock still returns them to assert that
        # the stripping behaviour holds.
        mock_response = LLMResponse(
            content=json.dumps({
                "contacts": [
                    {"email": "pierre.durand@techcorp.fr", "name": "Pierre Durand", "type": "colleague"},
                ],
                "projects": [
                    {"name": "Alpha", "description": "Main project", "status": "active"},
                ],
                "terminology": {"Sprint": "Dev iteration"},
                "faq": [{"question": "q", "answer": "a"}],
            }),
            input_tokens=200, output_tokens=80, model="mock",
        )
        mock_llm.complete.return_value = mock_response

        with patch("app.onboarding.agents.knowledge_agent.get_container") as mock_container:
            mock_container.return_value.llm_onboarding_worker = mock_llm
            agent = KnowledgeAgent()
            result = agent.analyse(indexed)

        assert len(result["contacts"]) >= 1
        # Hallucinated keys must be stripped — the user-supplied FAQ is
        # injected later by the orchestrator, not produced by this agent.
        assert "projects" not in result
        assert "terminology" not in result
        assert "faq" not in result

    def test_analyse_handles_empty_response(self, indexed, mock_llm):
        mock_llm.complete.return_value = LLMResponse(
            content="", input_tokens=10, output_tokens=0, model="mock",
        )

        with patch("app.onboarding.agents.knowledge_agent.get_container") as mock_container:
            mock_container.return_value.llm_onboarding_worker = mock_llm
            agent = KnowledgeAgent()
            result = agent.analyse(indexed)

        assert result["contacts"] == []
        assert "projects" not in result

    def test_prompt_omits_recv_bodies(self, indexed, mock_llm):
        """RECV bodies must be hidden from the LLM so terminology can
        never leak from third-party senders into the user's knowledge base.
        """
        with patch("app.onboarding.agents.knowledge_agent.get_container") as mock_container:
            mock_container.return_value.llm_onboarding_worker = mock_llm
            agent = KnowledgeAgent()
            prompt = agent._build_prompt(indexed)

        # No RECV body should ever appear in the prompt.
        for email in indexed.received_emails:
            if email.body and len(email.body) > 50:
                # A real RECV body of this length must not be leaked verbatim.
                assert email.body[:200] not in prompt, (
                    f"RECV body leaked to knowledge prompt: {email.body[:100]}"
                )
        # And the isolation marker must be present.
        assert "body omitted" in prompt

    def test_prompt_ranks_sent_heavy_contacts_first(self, mock_llm):
        """Contact metrics are ranked by how much the USER writes (sent_count),
        consistent with the VIP suggestion endpoint. A contact the user emails a
        lot (sent-heavy) must rank ABOVE a contact who mostly emails the user
        (received-heavy): the old bidirectional/total-volume key did the
        opposite and over-weighted an unreliable inbound signal.
        """
        user = "u@x.com"

        def _mk(eid, sender, recipients, direction):
            return OnboardingEmail(
                id=eid, sender_email=sender, sender_name=None,
                recipients=recipients, cc=[], subject="s",
                body="this is a sufficiently long body for indexing purposes",
                date=datetime(2026, 5, 1, tzinfo=timezone.utc), direction=direction,
            )

        emails = []
        # writer@x.com: the user wrote to them 5× (sent-heavy, no inbound cached).
        for i in range(5):
            emails.append(_mk(f"s{i}", user, ["writer@x.com"], EmailDirection.SENT))
        # pinger@x.com: mostly emails the user (5 received) + 1 reply → bidirectional
        # and higher TOTAL volume, but a weaker authorship signal.
        emails.append(_mk("s5", user, ["pinger@x.com"], EmailDirection.SENT))
        for i in range(5):
            emails.append(_mk(f"r{i}", "pinger@x.com", [user], EmailDirection.RECEIVED))

        indexed = EmailIndexer(user).index(emails)

        with patch("app.onboarding.agents.knowledge_agent.get_container") as mock_container:
            mock_container.return_value.llm_onboarding_worker = mock_llm
            prompt = KnowledgeAgent()._build_prompt(indexed)

        metrics = prompt.split("=== CONTACT METRICS ===")[1].split("=== USER SENT SAMPLE")[0]
        assert "writer@x.com" in metrics and "pinger@x.com" in metrics
        assert metrics.index("writer@x.com") < metrics.index("pinger@x.com"), (
            "sent-heavy contact must rank above received-heavy contact"
        )


class TestKnowledgeContactSignatures:
    """#960 — fenêtre bornée sur les signatures des contacts.

    title/company d'un contact vivent dans SA signature (emails REÇUS) que la
    règle d'isolation masque. Le prompt expose désormais des extraits de
    signature étiquetés tiers — et UNIQUEMENT eux : jamais un corps reçu.
    """

    USER = "u@x.com"

    def _mk(self, eid, sender, recipients, direction, body="x", signature=None,
            day=1):
        return OnboardingEmail(
            id=eid, sender_email=sender, sender_name=None,
            recipients=recipients, cc=[], subject="s", body=body,
            date=datetime(2026, 5, day, tzinfo=timezone.utc),
            direction=direction, signature=signature,
        )

    def _indexed(self, emails):
        # Au moins un SENT pour que le contact existe côté métriques.
        return EmailIndexer(self.USER).index(emails)

    def _prompt(self, indexed, mock_llm):
        with patch("app.onboarding.agents.knowledge_agent.get_container") as mc:
            mc.return_value.llm_onboarding_worker = mock_llm
            return KnowledgeAgent()._build_prompt(indexed)

    def test_prompt_includes_signature_section_with_title(self, mock_llm):
        emails = [
            self._mk("s0", self.USER, ["marcus@vc.com"], EmailDirection.SENT),
            self._mk(
                "r0", "marcus@vc.com", [self.USER], EmailDirection.RECEIVED,
                body="Quick responses below.\n\nBest,\nMarcus",
                signature="Marcus Chen\nPartner, Sequoia Capital\nmarcus@vc.com",
            ),
        ]
        prompt = self._prompt(self._indexed(emails), mock_llm)
        assert "=== CONTACT SIGNATURES" in prompt
        assert "Partner, Sequoia Capital" in prompt
        # Le corps reçu reste masqué.
        assert "Quick responses below." not in prompt

    def test_excerpt_prefers_explicit_signature_field(self):
        emails = [
            self._mk("s0", self.USER, ["a@x.com"], EmailDirection.SENT),
            self._mk(
                "r0", "a@x.com", [self.USER], EmailDirection.RECEIVED,
                body="Long prose here.\n--\nAlice\nCTO, Foo",
                signature="Alice Dupont\nVP Engineering, BarCorp",
            ),
        ]
        excerpt = KnowledgeAgent._contact_signature_excerpt(
            self._indexed(emails), "a@x.com"
        )
        assert excerpt == "Alice Dupont\nVP Engineering, BarCorp"

    def test_excerpt_tail_heuristic_drops_prose_lines(self):
        prose = (
            "I think we are ready to move to the definitive documents on this "
            "round, shall we aim for the end of February together?"
        )
        emails = [
            self._mk("s0", self.USER, ["b@x.com"], EmailDirection.SENT),
            self._mk(
                "r0", "b@x.com", [self.USER], EmailDirection.RECEIVED,
                body=f"Hello,\n\n{prose}\n\nBest,\nBob Martin\nManaging Partner, BazVC",
            ),
        ]
        excerpt = KnowledgeAgent._contact_signature_excerpt(
            self._indexed(emails), "b@x.com"
        )
        assert "Managing Partner, BazVC" in excerpt
        assert prose not in excerpt

    def test_excerpt_never_returns_whole_short_body(self):
        emails = [
            self._mk("s0", self.USER, ["c@x.com"], EmailDirection.SENT),
            self._mk(
                "r0", "c@x.com", [self.USER], EmailDirection.RECEIVED,
                body="Salut,\nOK pour demain\nTom",
            ),
        ]
        excerpt = KnowledgeAgent._contact_signature_excerpt(
            self._indexed(emails), "c@x.com"
        )
        assert excerpt == ""

    def test_excerpt_empty_when_no_received(self):
        emails = [self._mk("s0", self.USER, ["d@x.com"], EmailDirection.SENT)]
        excerpt = KnowledgeAgent._contact_signature_excerpt(
            self._indexed(emails), "d@x.com"
        )
        assert excerpt == ""

    def test_excerpt_capped(self):
        emails = [
            self._mk("s0", self.USER, ["e@x.com"], EmailDirection.SENT),
            self._mk(
                "r0", "e@x.com", [self.USER], EmailDirection.RECEIVED,
                body="hello", signature="Z\n" * 400,
            ),
        ]
        excerpt = KnowledgeAgent._contact_signature_excerpt(
            self._indexed(emails), "e@x.com"
        )
        assert len(excerpt) <= 350


class TestStyleAgent:
    """Tests for StyleAgent."""

    def test_analyse_returns_rules_dict(self, indexed, mock_llm):
        mock_response = LLMResponse(
            content=json.dumps({
                "contact_rules": [
                    {
                        "contact_email": "pierre.durand@techcorp.fr",
                        "tone": "casual",
                        "language": "fr",
                        "greeting": "Pierre,",
                        "closing": "Sophie",
                    },
                ],
                "general_rules": [
                    {
                        "name": "formal_external",
                        "description": "Use formal tone",
                        "trigger": "External contact",
                        "action": "Use vous",
                    },
                ],
                "forbidden_phrases": [],
            }),
            input_tokens=150, output_tokens=60, model="mock",
        )
        mock_llm.complete.return_value = mock_response

        with patch("app.onboarding.agents.style_agent.get_container") as mock_container:
            mock_container.return_value.llm_onboarding_worker = mock_llm
            agent = StyleAgent()
            result = agent.analyse(indexed)

        assert len(result["contact_rules"]) >= 1
        assert len(result["general_rules"]) >= 1
        assert isinstance(result["forbidden_phrases"], list)

    def test_analyse_handles_json_in_markdown(self, indexed, mock_llm):
        content = '```json\n{"contact_rules": [], "general_rules": [], "forbidden_phrases": []}\n```'
        mock_llm.complete.return_value = LLMResponse(
            content=content, input_tokens=10, output_tokens=5, model="mock",
        )

        with patch("app.onboarding.agents.style_agent.get_container") as mock_container:
            mock_container.return_value.llm_onboarding_worker = mock_llm
            agent = StyleAgent()
            result = agent.analyse(indexed)

        assert isinstance(result["contact_rules"], list)
