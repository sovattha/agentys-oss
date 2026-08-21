# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Issue #682 — CriticAgent wiring contract.

The Critic must pass a `list[SystemSegment]` (not a `str`) to the LLM port so
the Anthropic adapter can place a cache breakpoint on the byte-stable
rubric+KB prefix. Sending a string still works (single-block path) but
collapses the per-contact learned-rules block into the cached prefix → cache
miss on every cross-contact critique. This test pins the contract.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domain.entities.critique import CritiqueRequest
from app.domain.ports.llm_port import SystemSegment


def _build_mock_llm_response(content: str = '{"coherence": 80, "tone": 80, '
                                            '"completeness": 80, "errors": 80, '
                                            '"conciseness": 80, '
                                            '"over_commitment": 80, '
                                            '"emotional_intelligence": 80, '
                                            '"decision": "valid", '
                                            '"suggestions": [], '
                                            '"explanation": ""}'):
    """Build a mock LLM response that the Critic JSON parser accepts."""
    response = MagicMock()
    response.content = content
    response.input_tokens = 100
    response.output_tokens = 50
    response.model = "claude-haiku-4-5-20251001"
    response.stop_reason = "end_turn"
    response.cache_read_input_tokens = 0
    response.cache_creation_input_tokens = 0
    return response


def test_critic_passes_segments_to_llm():
    """CriticAgent.evaluate_draft must pass `system=list[SystemSegment]`.

    Pre-#682, the call was `system=get_critic_structured_system_prompt(...)`
    which returned a `str`. The adapter wrapped that single string in one
    cache_control block, so the per-contact learned-rules block (appended
    inside the builder) sat INSIDE the cached prefix → cache miss whenever
    contact changed. Post-#682 the call uses `…_segments(...)` returning a
    list with rubric+KB cacheable and learned rules non-cacheable.
    """
    from app.agents import CriticAgent

    # Bypass the container — supply a hand-rolled mock LLM directly so we
    # can inspect the `complete` arguments without booting the wider DI graph.
    agent = CriticAgent(knowledge_base="Test KB", account_id=1)
    agent._llm = MagicMock()
    agent._llm.complete.return_value = _build_mock_llm_response()

    request = CritiqueRequest(
        email_id="test-1",
        original_email="Hello, can you confirm?",
        draft_content="Yes, confirmed.",
        context=None,
    )
    # The Critic reads `contact` via `getattr(request, 'contact', '')` so the
    # field is dynamically attached on the call site (it is not part of
    # `CritiqueRequest.__init__`). Mirror that behavior in the test.
    request.contact = "alice@example.com"
    agent.evaluate_draft(request)

    call_kwargs = agent._llm.complete.call_args.kwargs
    system_arg = call_kwargs["system"]
    assert isinstance(system_arg, list), (
        f"CriticAgent must pass `system` as a list of SystemSegment to enable "
        f"prompt-cache breakpoints. Got {type(system_arg).__name__}."
    )
    assert all(isinstance(s, SystemSegment) for s in system_arg), (
        "All elements of `system` must be SystemSegment instances."
    )
    assert len(system_arg) >= 1
    # First segment is the cacheable rubric+KB. Without this the adapter
    # would not place any cache_control marker on the request.
    assert system_arg[0].cacheable is True


def test_critic_segments_first_block_is_byte_stable_across_contacts():
    """End-to-end version of the builder-level invariant — exercises the
    actual agent code path. Two critiques for different contacts of the
    same account must send a byte-identical segment 0 to the LLM, so the
    Anthropic cache key for that prefix matches across calls.
    """
    from app.agents import CriticAgent

    captured_systems: list = []

    def _capture_and_respond(**kwargs):
        captured_systems.append(kwargs["system"])
        return _build_mock_llm_response()

    agent = CriticAgent(knowledge_base="Same KB for both", account_id=42)
    agent._llm = MagicMock()
    agent._llm.complete.side_effect = _capture_and_respond

    # Stub the learning store to deterministically return DIFFERENT rules
    # per contact — this is exactly the situation that used to bust the
    # cache prefix on the legacy single-string path.
    with patch("app.draft_learning.get_draft_learning_store") as factory:
        store = factory.return_value
        store.get_rules_for_prompt.side_effect = [
            "Rule for alice: prefers short replies",
            "Rule for bob: tutoiement only",
        ]

        req_a = CritiqueRequest(
            email_id="e1", original_email="Q1?", draft_content="A1.", context=None,
        )
        req_a.contact = "alice@example.com"
        agent.evaluate_draft(req_a)

        req_b = CritiqueRequest(
            email_id="e2", original_email="Q2?", draft_content="A2.", context=None,
        )
        req_b.contact = "bob@example.com"
        agent.evaluate_draft(req_b)

    assert len(captured_systems) == 2
    sys_a, sys_b = captured_systems
    assert sys_a[0].text == sys_b[0].text, (
        "Segment 0 (cacheable rubric+KB) MUST be identical across contacts. "
        "If this regresses, the per-contact learned-rules block has leaked "
        "back into the cached prefix — cross-contact cache reuse is dead."
    )
    # And of course segment 1 (the per-contact rules) MUST differ — that's
    # the whole reason we split.
    assert len(sys_a) == 2 and len(sys_b) == 2
    assert sys_a[1].text != sys_b[1].text
    assert sys_a[1].cacheable is False
    assert sys_b[1].cacheable is False
