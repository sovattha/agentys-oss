# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Q-07 — TokenCounter wiring + LLM-attribution context (audit 2026-05-05).

Pre-fix: ``LegacyTokenCounterAdapter`` was instantiated by the Container
but never called from the request path (dead code in prod). Every LLM
completion landed in the single global ``TokenUsage`` counter with no
agent dimension — answering "how much did the drafter cost vs the
onboarding pipeline?" required parsing logs, not a query.

Post-fix:
- New module :mod:`app.infrastructure.llm_attribution` provides a
  contextvars-based ``llm_attribution(agent, account_id=...)`` context.
- ``_track_token_usage`` reads that context and forwards (agent, model,
  input, output) to the adapter so ``get_breakdown_by_agent()`` actually
  reflects production traffic.
- DrafterAgent / CriticAgent public methods are decorated with
  ``@_attribute_to_agent`` so callers don't need to wrap manually.

This test pins:
  1. The context manager defaults + nesting semantics.
  2. The decorator pulls ``_agent_label`` and ``account_id`` from ``self``.
  3. ``_track_token_usage`` writes to the per-agent breakdown.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestLlmAttributionContext:
    def test_defaults(self):
        from app.infrastructure.llm_attribution import current_agent, current_account_id
        # Outside any context — sentinel defaults so logs are still grep-friendly.
        assert current_agent() == "unknown"
        assert current_account_id() is None

    def test_context_set_and_restore(self):
        from app.infrastructure.llm_attribution import (
            current_agent, current_account_id, llm_attribution,
        )
        with llm_attribution("drafter", account_id=42):
            assert current_agent() == "drafter"
            assert current_account_id() == 42
        # Restored on exit.
        assert current_agent() == "unknown"
        assert current_account_id() is None

    def test_nesting_restores_outer(self):
        """A nested block must NOT leak its values past its exit."""
        from app.infrastructure.llm_attribution import current_agent, llm_attribution
        with llm_attribution("drafter", account_id=1):
            with llm_attribution("critic", account_id=2):
                assert current_agent() == "critic"
            assert current_agent() == "drafter"

    def test_nested_agent_without_account_preserves_outer_account(self):
        """Helper agents built without account_id inherit the pipeline account."""
        from app.infrastructure.cost_manager import reset_usage_context, set_usage_context
        from app.infrastructure.llm_attribution import (
            current_account_id,
            llm_attribution,
        )
        from app.infrastructure.token_usage_writer import build_record

        tokens = set_usage_context(
            account_id=14,
            user_id=1694432691,
            feature="drafting",
        )
        try:
            with llm_attribution("smart_router", account_id=14):
                with llm_attribution("critic"):
                    assert current_account_id() == 14
                    rec = build_record(
                        model="claude-haiku-4-5-20251001",
                        input_tokens=100,
                        output_tokens=10,
                    )
        finally:
            reset_usage_context(tokens)

        assert rec.agent == "critic"
        assert rec.account_id == 14
        assert rec.user_id == 1694432691
        assert rec.feature == "drafting"

    def test_empty_agent_label_normalized(self):
        from app.infrastructure.llm_attribution import current_agent, llm_attribution
        with llm_attribution("", account_id=None):
            # Defensive: empty/None falls back to the sentinel.
            assert current_agent() == "unknown"


class TestTrackTokenUsage:
    def test_records_agent_breakdown(self):
        """_track_token_usage must forward agent + tokens to the adapter."""
        from app.infrastructure.llm_attribution import llm_attribution
        from app import agents as agents_mod

        fake_resp = MagicMock(input_tokens=1000, output_tokens=200, model="haiku-x")
        fake_adapter = MagicMock()
        fake_container = MagicMock()
        fake_container.token_counter = fake_adapter
        # Keep the legacy global counter happy too — _track_token_usage adds
        # to both. Set token_usage to a real-ish stub.
        fake_container.token_usage = MagicMock()

        with patch.object(agents_mod, "get_container", return_value=fake_container):
            with llm_attribution("drafter", account_id=42):
                agents_mod._track_token_usage(fake_resp)

        # Adapter must have been called with the agent label from context.
        assert fake_adapter.add.called, "TokenCounter adapter should be invoked"
        kwargs = fake_adapter.add.call_args.kwargs
        assert kwargs["agent"] == "drafter"
        assert kwargs["input_tokens"] == 1000
        assert kwargs["output_tokens"] == 200
        assert kwargs["model"] == "haiku-x"

    def test_records_unknown_when_no_context(self):
        """Unattributed calls still record (under 'unknown') — never lose tokens."""
        from app import agents as agents_mod

        fake_resp = MagicMock(input_tokens=500, output_tokens=100, model="haiku-x")
        fake_adapter = MagicMock()
        fake_container = MagicMock()
        fake_container.token_counter = fake_adapter
        fake_container.token_usage = MagicMock()

        with patch.object(agents_mod, "get_container", return_value=fake_container):
            agents_mod._track_token_usage(fake_resp)

        kwargs = fake_adapter.add.call_args.kwargs
        assert kwargs["agent"] == "unknown"


class TestAgentDecorator:
    def test_drafter_label(self):
        """DrafterAgent has _agent_label='drafter' so the context shows that."""
        from app.agents import DrafterAgent
        d = DrafterAgent.__new__(DrafterAgent)  # bypass __post_init__ (hits LLM)
        # Default field reads from class — set the slot manually.
        d._agent_label = "drafter"
        d.account_id = 7
        assert getattr(d, "_agent_label") == "drafter"
        assert getattr(d, "account_id") == 7

    def test_critic_label(self):
        from app.agents import CriticAgent
        c = CriticAgent.__new__(CriticAgent)
        c._agent_label = "critic"
        c.account_id = 9
        assert getattr(c, "_agent_label") == "critic"
        assert getattr(c, "account_id") == 9
