# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Q-02 — Critic-skip stats counter (2026-05-05).

The audit claimed the heuristic skip-gate at smart_routing.py:1869 bypasses
~70% of drafts, but no observability existed to verify that. Without a
counter, a regression in `_draft_passes_quality_gate` (e.g. an over-strict
new rule) would silently push every draft through the LLM critic, doubling
latency and cost without anyone noticing.

This test pins the counter API so future refactors don't quietly drop it.
"""
from __future__ import annotations


def test_skip_stats_module_api_exists():
    """get_critic_skip_stats() returns the documented snapshot shape."""
    from app.smart_routing import get_critic_skip_stats
    snap = get_critic_skip_stats()
    assert isinstance(snap, dict)
    for key in ("total", "skipped", "full", "skip_rate"):
        assert key in snap, f"snapshot missing key={key} — broken telemetry"
    assert snap["total"] == snap["skipped"] + snap["full"], (
        "skipped + full must sum to total — counter invariant"
    )
    assert 0.0 <= snap["skip_rate"] <= 1.0


def test_record_critic_outcome_increments_counters():
    """Calling _record_critic_outcome moves the right counter."""
    from app.smart_routing import _record_critic_outcome, get_critic_skip_stats

    before = get_critic_skip_stats()
    _record_critic_outcome(skipped=True)
    _record_critic_outcome(skipped=True)
    _record_critic_outcome(skipped=False)
    after = get_critic_skip_stats()

    assert after["skipped"] - before["skipped"] == 2
    assert after["full"] - before["full"] == 1
    assert after["total"] - before["total"] == 3
