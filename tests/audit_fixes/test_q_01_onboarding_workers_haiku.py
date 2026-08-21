# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Q-01 — Onboarding worker agents migrated from Sonnet to Haiku (2026-05-05).

Audit finding: ProfileAgent / KnowledgeAgent / StyleAgent / LabelAgent were
hardcoded to `Container.llm_onboarding` (tier="smart" / Sonnet) — a ~22×
cost premium per onboarding versus Haiku, contradicting the user's
"Haiku-first partout" routing principle.

Migration: those 4 agents now resolve `Container.llm_onboarding_worker`,
which defaults to tier="label" (Haiku) and respects ONBOARDING_WORKER_TIER
as a kill-switch back to Sonnet.

EvaluationAgent intentionally stays on `llm_onboarding` (Sonnet) so the
judge model differs from the writer model — see lesson 52524115.
"""
from __future__ import annotations

import importlib


def _reset_container(monkeypatch):
    """Force the singleton to rebuild with the current env."""
    monkeypatch.setenv("LLM_PROVIDER", "claude-code")
    import app.infrastructure.container as container_module
    container_module._container = None
    importlib.reload(container_module)
    return container_module


def _get_tier(llm_port) -> str:
    """Best-effort introspection of the tier the LLM was created with.

    The categorized factory writes the model name into the port. We rely on
    the Haiku model name containing 'haiku' and Sonnet containing 'sonnet'.
    """
    model = (getattr(llm_port, "model", "") or "").lower()
    if "haiku" in model:
        return "label"
    if "sonnet" in model:
        return "smart"
    return "unknown"


def test_default_worker_tier_is_haiku(monkeypatch):
    monkeypatch.delenv("ONBOARDING_WORKER_TIER", raising=False)
    cm = _reset_container(monkeypatch)
    c = cm.get_container()
    assert _get_tier(c.llm_onboarding_worker) == "label", (
        "Default ONBOARDING_WORKER_TIER must resolve to Haiku (label tier). "
        "Migration 2026-05-05 — see container.py:llm_onboarding_worker."
    )


def test_kill_switch_rolls_back_to_sonnet(monkeypatch):
    """Setting ONBOARDING_WORKER_TIER=smart must restore Sonnet (rollback path)."""
    monkeypatch.setenv("ONBOARDING_WORKER_TIER", "smart")
    cm = _reset_container(monkeypatch)
    c = cm.get_container()
    assert _get_tier(c.llm_onboarding_worker) == "smart", (
        "ONBOARDING_WORKER_TIER=smart must roll back to Sonnet. "
        "Without this kill-switch we cannot recover from a quality regression "
        "without a redeploy."
    )


def test_invalid_tier_falls_back_to_label(monkeypatch):
    monkeypatch.setenv("ONBOARDING_WORKER_TIER", "garbage")
    cm = _reset_container(monkeypatch)
    c = cm.get_container()
    assert _get_tier(c.llm_onboarding_worker) == "label", (
        "Unknown tier values must default to Haiku (label) — fail-cheap, "
        "not fail-expensive."
    )


def test_judge_stays_on_sonnet(monkeypatch):
    """EvaluationAgent must keep `llm_onboarding` (Sonnet) so judge ≠ writer.

    Same-model self-eval added +5–8 pts of false positives in the eval
    harness (lesson 52524115). Migrating the judge to Haiku would silently
    re-introduce that bias.
    """
    cm = _reset_container(monkeypatch)
    c = cm.get_container()
    assert _get_tier(c.llm_onboarding) == "smart", (
        "Container.llm_onboarding must remain Sonnet — used by EvaluationAgent "
        "as the LLM-as-judge. Switching it to Haiku reintroduces the writer=judge "
        "confound documented in tasks/lessons.md."
    )


def test_worker_agents_resolve_worker_property():
    """Static check: each of the 4 workers references llm_onboarding_worker."""
    import inspect
    from app.onboarding.agents import (
        profile_agent,
        knowledge_agent,
        style_agent,
        label_agent,
    )
    for module in (profile_agent, knowledge_agent, style_agent, label_agent):
        src = inspect.getsource(module)
        assert "llm_onboarding_worker" in src, (
            f"{module.__name__} must use Container.llm_onboarding_worker — "
            "found a stale reference to llm_onboarding (Sonnet)."
        )
        # Belt-and-braces: forbid the bare `llm_onboarding` attribute access
        # in worker modules so a future refactor doesn't silently regress.
        assert "container().llm_onboarding\n" not in src, (
            f"{module.__name__} still has a bare `llm_onboarding` resolution. "
            "Use `llm_onboarding_worker` instead."
        )
