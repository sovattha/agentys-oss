# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests for the Async-Critic callbacks on DraftOrchestrator.

Audit 2026-05-04 (Async Critic backend) : the orchestrator gained 3 new
optional callbacks (``on_draft_ready``, ``on_critique_complete``,
``on_revision_ready``) so the HTTP handler can emit the corresponding
WebSocket events at the right time — letting the frontend show V1
immediately while the Critic runs in the background.

These tests pin :
  1. Each callback fires at the correct point in the loop
  2. Each receives the correct arguments
  3. Callbacks default to None (full backward compat)
  4. An exception in any callback does NOT interrupt the orchestration
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from app.agents import CriticAgent, DrafterAgent
from app.domain.entities.critique import (
    CritiqueDecision,
    CritiqueResult,
    CritiqueScores,
    CritiqueStatus,
)
from app.domain.entities.draft_generation import DraftResult, DraftStatus
from app.domain.entities.orchestration import OrchestrationRequest, OrchestrationStatus
from app.services.draft_orchestrator import DraftOrchestrator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _draft_v1() -> DraftResult:
    return DraftResult(
        content="Bonjour Alice,\n\nC'est noté. À demain.",
        confidence=0.9,
        status=DraftStatus.COMPLETED,
        tokens_used=80,
    )


def _draft_v2() -> DraftResult:
    return DraftResult(
        content="Bonjour Alice,\n\nC'est confirmé. Je serai là demain à 10h.",
        confidence=0.92,
        status=DraftStatus.COMPLETED,
        tokens_used=95,
    )


def _critique_valid() -> CritiqueResult:
    return CritiqueResult(
        scores=CritiqueScores(85, 80, 82, 90, 85, 80, 82),
        decision=CritiqueDecision.VALID,
        suggestions=[],
        explanation="Ok",
        status=CritiqueStatus.COMPLETED,
    )


def _critique_reject() -> CritiqueResult:
    return CritiqueResult(
        scores=CritiqueScores(60, 70, 50, 80, 75, 70, 70),
        decision=CritiqueDecision.REJECT,
        suggestions=["plus précis"],
        explanation="incomplet",
        status=CritiqueStatus.COMPLETED,
    )


@pytest.fixture
def mock_drafter_v1():
    """Drafter that returns V1 then V2 on revision."""
    drafter = MagicMock(spec=DrafterAgent)
    drafter.draft_with_retry.return_value = _draft_v1()
    drafter.revise_with_critique_and_retry.return_value = _draft_v2()
    return drafter


@pytest.fixture
def mock_critic_valid():
    """Critic that always validates."""
    critic = MagicMock(spec=CriticAgent)
    critic.evaluate_draft_with_retry.return_value = _critique_valid()
    return critic


@pytest.fixture
def mock_critic_reject_then_valid():
    """Critic that rejects V1, validates V2 — exercises the revision path."""
    critic = MagicMock(spec=CriticAgent)
    critic.evaluate_draft_with_retry.side_effect = [
        _critique_reject(), _critique_valid(),
    ]
    return critic


@pytest.fixture
def sample_request():
    return OrchestrationRequest(
        email_content="Tu peux confirmer pour demain ?",
        email_id="test-async-1",
    )


# ---------------------------------------------------------------------------
# Backward compat — callbacks default to None
# ---------------------------------------------------------------------------


class TestBackwardCompat:
    """Existing callers without the new callbacks must see no behaviour change."""

    def test_no_callbacks_orchestrate_unchanged(
        self, mock_drafter_v1, mock_critic_valid, sample_request,
    ):
        orchestrator = DraftOrchestrator(
            drafter=mock_drafter_v1, critic=mock_critic_valid,
        )
        result = orchestrator.orchestrate(sample_request)
        assert result.status == OrchestrationStatus.COMPLETED
        assert len(result.iterations) == 1


# ---------------------------------------------------------------------------
# on_draft_ready — fires when V1 is generated, before Critic runs
# ---------------------------------------------------------------------------


class TestOnDraftReady:
    def test_fires_after_v1_generation_before_critic(
        self, mock_drafter_v1, mock_critic_valid, sample_request,
    ):
        """Pin the timing : on_draft_ready must fire BEFORE the Critic call."""
        events: list[str] = []
        on_draft_ready = MagicMock(side_effect=lambda d: events.append("draft_ready"))

        # Wrap the critic to record when it ran relative to the callback.
        def critic_with_marker(*args, **kwargs):
            events.append("critic_called")
            return _critique_valid()

        mock_critic_valid.evaluate_draft_with_retry.side_effect = critic_with_marker

        orchestrator = DraftOrchestrator(
            drafter=mock_drafter_v1, critic=mock_critic_valid,
        )
        orchestrator.orchestrate(sample_request, on_draft_ready=on_draft_ready)

        assert events == ["draft_ready", "critic_called"], (
            f"on_draft_ready must fire BEFORE the Critic call. Got: {events}"
        )
        on_draft_ready.assert_called_once()

    def test_passes_v1_draft_result_to_callback(
        self, mock_drafter_v1, mock_critic_valid, sample_request,
    ):
        captured: list = []
        orchestrator = DraftOrchestrator(
            drafter=mock_drafter_v1, critic=mock_critic_valid,
        )
        orchestrator.orchestrate(
            sample_request, on_draft_ready=lambda d: captured.append(d),
        )
        assert len(captured) == 1
        assert captured[0].content == _draft_v1().content
        assert captured[0].is_successful()

    def test_does_not_fire_on_revision_iteration(
        self, mock_drafter_v1, mock_critic_reject_then_valid, sample_request,
    ):
        """V2 is a revision, not a fresh draft → on_draft_ready fires once only."""
        on_draft_ready = MagicMock()
        orchestrator = DraftOrchestrator(
            drafter=mock_drafter_v1, critic=mock_critic_reject_then_valid,
        )
        orchestrator.orchestrate(sample_request, on_draft_ready=on_draft_ready)
        assert on_draft_ready.call_count == 1, (
            "on_draft_ready must fire exactly once (for V1, not V2)"
        )

    def test_callback_exception_does_not_break_orchestration(
        self, mock_drafter_v1, mock_critic_valid, sample_request,
    ):
        """A bug in the callback must NEVER fail the draft generation."""
        def boom(d):
            raise RuntimeError("intentional callback explosion")
        orchestrator = DraftOrchestrator(
            drafter=mock_drafter_v1, critic=mock_critic_valid,
        )
        result = orchestrator.orchestrate(
            sample_request, on_draft_ready=boom,
        )
        assert result.status == OrchestrationStatus.COMPLETED


# ---------------------------------------------------------------------------
# on_critique_complete — fires after every Critic verdict
# ---------------------------------------------------------------------------


class TestOnCritiqueComplete:
    def test_fires_after_critic_with_correct_args(
        self, mock_drafter_v1, mock_critic_valid, sample_request,
    ):
        captured: list = []
        orchestrator = DraftOrchestrator(
            drafter=mock_drafter_v1, critic=mock_critic_valid,
        )
        orchestrator.orchestrate(
            sample_request,
            on_critique_complete=lambda crit, draft, it: captured.append((crit, draft, it)),
        )
        assert len(captured) == 1
        crit, draft, it = captured[0]
        assert crit.decision == CritiqueDecision.VALID
        assert draft.content == _draft_v1().content
        assert it == 1

    def test_fires_twice_on_v1_reject_then_v2_valid(
        self, mock_drafter_v1, mock_critic_reject_then_valid, sample_request,
    ):
        """V1 critique + V2 critique → callback fires twice with correct iterations."""
        captured: list = []
        orchestrator = DraftOrchestrator(
            drafter=mock_drafter_v1, critic=mock_critic_reject_then_valid,
        )
        orchestrator.orchestrate(
            sample_request,
            on_critique_complete=lambda crit, draft, it: captured.append((crit.decision.value, it)),
        )
        assert captured == [("reject", 1), ("valid", 2)], captured

    def test_callback_exception_does_not_break_orchestration(
        self, mock_drafter_v1, mock_critic_valid, sample_request,
    ):
        def boom(crit, draft, it):
            raise RuntimeError("boom")
        orchestrator = DraftOrchestrator(
            drafter=mock_drafter_v1, critic=mock_critic_valid,
        )
        result = orchestrator.orchestrate(
            sample_request, on_critique_complete=boom,
        )
        assert result.status == OrchestrationStatus.COMPLETED


# ---------------------------------------------------------------------------
# on_revision_ready — fires only when V2 is generated after a V1 reject
# ---------------------------------------------------------------------------


class TestOnRevisionReady:
    def test_does_not_fire_when_v1_validates(
        self, mock_drafter_v1, mock_critic_valid, sample_request,
    ):
        """No revision → callback never fires."""
        on_revision_ready = MagicMock()
        orchestrator = DraftOrchestrator(
            drafter=mock_drafter_v1, critic=mock_critic_valid,
        )
        orchestrator.orchestrate(sample_request, on_revision_ready=on_revision_ready)
        on_revision_ready.assert_not_called()

    def test_fires_with_v1_v2_and_critique_when_revision_happens(
        self, mock_drafter_v1, mock_critic_reject_then_valid, sample_request,
    ):
        captured: list = []
        orchestrator = DraftOrchestrator(
            drafter=mock_drafter_v1, critic=mock_critic_reject_then_valid,
        )
        orchestrator.orchestrate(
            sample_request,
            on_revision_ready=lambda new, prev, crit: captured.append(
                (new.content, prev.content, crit.decision.value)
            ),
        )
        assert len(captured) == 1
        new_content, prev_content, decision = captured[0]
        assert new_content == _draft_v2().content
        assert prev_content == _draft_v1().content
        assert decision == "reject"

    def test_callback_exception_does_not_break_orchestration(
        self, mock_drafter_v1, mock_critic_reject_then_valid, sample_request,
    ):
        def boom(new, prev, crit):
            raise RuntimeError("boom")
        orchestrator = DraftOrchestrator(
            drafter=mock_drafter_v1, critic=mock_critic_reject_then_valid,
        )
        result = orchestrator.orchestrate(
            sample_request, on_revision_ready=boom,
        )
        # Revision still produces a result even though callback exploded.
        assert result.status == OrchestrationStatus.COMPLETED


# ---------------------------------------------------------------------------
# All-callbacks-together — end-to-end ordering on the V1-reject-then-V2 path
# ---------------------------------------------------------------------------


class TestCallbackOrdering:
    """The 3 new callbacks combined with the existing iteration callbacks
    must produce a stable, predictable event timeline. This is the contract
    the HTTP handler relies on to map callbacks → WebSocket events."""

    def test_full_event_timeline_on_v1_reject_v2_valid(
        self, mock_drafter_v1, mock_critic_reject_then_valid, sample_request,
    ):
        events: list[str] = []
        orchestrator = DraftOrchestrator(
            drafter=mock_drafter_v1, critic=mock_critic_reject_then_valid,
        )

        # Wrap the critic so we can pin its position in the event timeline
        # against the new callbacks. ``responses`` exhausts the V1-reject /
        # V2-valid pair in order.
        responses = iter([_critique_reject(), _critique_valid()])

        def critic_marker(*args, **kwargs):
            events.append("critic_called")
            return next(responses)

        mock_critic_reject_then_valid.evaluate_draft_with_retry.side_effect = critic_marker

        orchestrator.orchestrate(
            sample_request,
            on_iteration_start=lambda eid, it: events.append(f"it_start_{it}"),
            on_iteration_complete=lambda eid, it, score, dec: events.append(f"it_complete_{it}_{dec}"),
            on_draft_ready=lambda d: events.append("draft_ready"),
            on_critique_complete=lambda crit, draft, it: events.append(f"critique_complete_{it}_{crit.decision.value}"),
            on_revision_ready=lambda new, prev, crit: events.append("revision_ready"),
        )

        # The critical orderings:
        # 1. on_draft_ready fires AFTER it_start_1 but BEFORE critic_called
        # 2. critique_complete fires AFTER critic_called (each iteration)
        # 3. revision_ready fires BEFORE the V2 critic call
        # 4. on_iteration_complete fires last for each iteration
        assert events.index("it_start_1") < events.index("draft_ready") < events.index("critic_called")
        assert events.index("critic_called") < events.index("critique_complete_1_reject")
        assert events.index("critique_complete_1_reject") < events.index("it_complete_1_reject")
        assert events.index("it_complete_1_reject") < events.index("it_start_2")
        # revision_ready fires BEFORE the V2 critic call
        critic_calls = [i for i, e in enumerate(events) if e == "critic_called"]
        assert events.index("revision_ready") < critic_calls[1]
        assert events.index("revision_ready") < events.index("critique_complete_2_valid")
