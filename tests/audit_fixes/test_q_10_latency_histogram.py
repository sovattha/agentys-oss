# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Q-10 — Draft latency histogram (audit 2026-05-06).

Pre-fix: no production latency data — every speed claim was theoretical.

Post-fix: ``record_draft_latency(tier, seconds)`` appends to a bounded
rolling buffer per tier. ``get_draft_latency_stats()`` returns
percentiles (p50/p95/p99/max) for each tier — backs the admin dashboard
gauge and the future Sentinel L3 alarm on p95 regressions.
"""
from __future__ import annotations


def test_empty_state_returns_zeros():
    from app.smart_routing import _latency_samples, get_draft_latency_stats
    # Reset to empty for a deterministic check.
    for k in list(_latency_samples.keys()):
        _latency_samples[k].clear()
    stats = get_draft_latency_stats()
    assert "standard" in stats
    assert stats["standard"]["count"] == 0
    assert stats["standard"]["p50"] == 0.0
    assert stats["standard"]["p95"] == 0.0


def test_record_and_percentiles():
    from app.smart_routing import (
        record_draft_latency, get_draft_latency_stats, _latency_samples,
    )
    # Reset.
    for k in list(_latency_samples.keys()):
        _latency_samples[k].clear()
    for v in (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0):
        record_draft_latency("standard", v)
    stats = get_draft_latency_stats()["standard"]
    assert stats["count"] == 10
    # With 10 samples, p50 ≈ 5.5, p95 ≈ 9.55, p99 ≈ 9.91 (linear interp).
    assert 5.0 <= stats["p50"] <= 6.0
    assert 9.0 <= stats["p95"] <= 10.0
    assert stats["max"] == 10.0


def test_unknown_tier_lands_in_other():
    from app.smart_routing import (
        record_draft_latency, get_draft_latency_stats, _latency_samples,
    )
    for k in list(_latency_samples.keys()):
        _latency_samples[k].clear()
    record_draft_latency("MYSTERY", 2.0)
    stats = get_draft_latency_stats()
    assert stats["other"]["count"] == 1


def test_negative_or_nan_dropped():
    from app.smart_routing import (
        record_draft_latency, _latency_samples,
    )
    for k in list(_latency_samples.keys()):
        _latency_samples[k].clear()
    record_draft_latency("simple", -1.0)
    record_draft_latency("simple", float("nan"))
    record_draft_latency("simple", None)  # type: ignore[arg-type]
    assert len(_latency_samples["simple"]) == 0
