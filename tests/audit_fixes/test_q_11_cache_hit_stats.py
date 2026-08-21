# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Q-11 — Cache hit-rate counter (audit 2026-05-06).

Pre-fix: ``[USAGE_STATS]`` log line was emitted but never aggregated —
operators could not answer "what is our current cache hit rate?"
without scraping logs.

Post-fix: claude_adapter._record_cache_stats updates a module-level
rolling+lifetime counter. ``get_cache_hit_stats`` returns the snapshot
the admin dashboard / sentinel consumes.
"""
from __future__ import annotations


def test_snapshot_shape():
    from app.adapters.llm.claude_adapter import get_cache_hit_stats
    snap = get_cache_hit_stats()
    assert "rolling" in snap and "lifetime" in snap
    for w in ("rolling", "lifetime"):
        for key in (
            "calls", "input_tokens", "cache_write_tokens",
            "cache_read_tokens", "output_tokens", "cache_hit_rate",
        ):
            assert key in snap[w], f"snapshot[{w}] missing key={key}"


def test_record_increments_counters():
    from app.adapters.llm.claude_adapter import (
        _record_cache_stats, get_cache_hit_stats,
    )
    before = get_cache_hit_stats()
    _record_cache_stats(in_tok=100, cache_w=50, cache_r=200, out_tok=80)
    after = get_cache_hit_stats()
    # Lifetime totals must move by exactly the input we passed.
    assert after["lifetime"]["input_tokens"] - before["lifetime"]["input_tokens"] == 100
    assert after["lifetime"]["cache_read_tokens"] - before["lifetime"]["cache_read_tokens"] == 200
    # Hit rate = read / (read + write + non-cached input). Across the
    # entire lifetime so a single call won't dominate; we only check
    # that it stays in a sensible range.
    assert 0.0 <= after["lifetime"]["cache_hit_rate"] <= 1.0
