# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests for the [USAGE_STATS] log emitter in claude_adapter.

Audit 2026-05-04: this log line is the basis for cache-hit-rate sentinel
analysis. If its format drifts, the sentinel that scrapes it stops
working silently. Test pins:

1. The line's grep-friendly format (parseable key=value pairs)
2. cache_hit_rate computation = cache_r / (in + cache_w + cache_r)
3. Tolerance against missing/None usage fields (Anthropic SDK has
   reported these as `None` in past versions when caching is unused)
"""

from __future__ import annotations

import logging
from unittest.mock import patch

from app.adapters.llm.claude_adapter import _log_usage


class _FakeUsage:
    """Minimal stand-in for `anthropic.types.Usage`."""

    def __init__(self, input_tokens=0, output_tokens=0,
                 cache_creation_input_tokens=0, cache_read_input_tokens=0):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_creation_input_tokens = cache_creation_input_tokens
        self.cache_read_input_tokens = cache_read_input_tokens


def test_log_usage_emits_grep_friendly_line(caplog):
    caplog.set_level(logging.INFO, logger="app.adapters.llm.claude_adapter")
    usage = _FakeUsage(input_tokens=100, cache_creation_input_tokens=0,
                        cache_read_input_tokens=900, output_tokens=50)
    _log_usage("claude-haiku-4-5-20251001", usage, kind="complete")

    assert any("[USAGE_STATS]" in r.message for r in caplog.records)
    msg = next(r.message for r in caplog.records if "[USAGE_STATS]" in r.message)
    # Spot-check every key. Order matters less than presence.
    assert "model=claude-haiku-4-5-20251001" in msg
    assert "kind=complete" in msg
    assert "in=100" in msg
    assert "cache_w=0" in msg
    assert "cache_r=900" in msg
    assert "out=50" in msg
    assert "cache_hit_rate=0.900" in msg


def test_log_usage_zero_input_no_division_by_zero(caplog):
    """All-zero usage (e.g. timeout before request sent) must not crash."""
    caplog.set_level(logging.INFO, logger="app.adapters.llm.claude_adapter")
    _log_usage("claude-haiku-4-5-20251001", _FakeUsage(), kind="stream")
    msg = next(r.message for r in caplog.records if "[USAGE_STATS]" in r.message)
    assert "cache_hit_rate=0.000" in msg


def test_log_usage_handles_none_cache_fields(caplog):
    """Anthropic SDK can return cache fields as None; treat as 0."""
    caplog.set_level(logging.INFO, logger="app.adapters.llm.claude_adapter")
    u = _FakeUsage(input_tokens=200, output_tokens=30)
    u.cache_creation_input_tokens = None
    u.cache_read_input_tokens = None
    _log_usage("claude-sonnet-4-20250514", u, kind="complete")
    msg = next(r.message for r in caplog.records if "[USAGE_STATS]" in r.message)
    assert "cache_w=0" in msg
    assert "cache_r=0" in msg
    assert "in=200" in msg


def test_log_usage_silent_on_none_usage(caplog):
    """A None usage object (some error paths) must not raise — telemetry
    failure must never surface as a draft generation failure."""
    caplog.set_level(logging.INFO, logger="app.adapters.llm.claude_adapter")
    _log_usage("claude-haiku-4-5-20251001", None, kind="complete")
    assert not any("[USAGE_STATS]" in r.message for r in caplog.records)


def test_log_usage_swallows_exceptions(caplog):
    """A malformed usage object (e.g. attribute access raises) must not
    propagate — telemetry is best-effort by design."""
    caplog.set_level(logging.INFO, logger="app.adapters.llm.claude_adapter")

    class _Broken:
        @property
        def input_tokens(self):
            raise RuntimeError("boom")

    # Must not raise.
    _log_usage("claude-haiku-4-5-20251001", _Broken(), kind="complete")
    # And must not have emitted a usage line.
    assert not any("[USAGE_STATS]" in r.message for r in caplog.records)


def test_log_usage_cache_hit_rate_partial(caplog):
    """A mix of cache-write + cache-read + fresh input."""
    caplog.set_level(logging.INFO, logger="app.adapters.llm.claude_adapter")
    # 100 fresh + 200 cached-write + 700 cached-read = 1000 total input
    usage = _FakeUsage(input_tokens=100, cache_creation_input_tokens=200,
                        cache_read_input_tokens=700, output_tokens=80)
    _log_usage("claude-haiku-4-5-20251001", usage, kind="complete")
    msg = next(r.message for r in caplog.records if "[USAGE_STATS]" in r.message)
    # cache_r=700 / total=1000 = 0.700
    assert "cache_hit_rate=0.700" in msg


def test_log_usage_enqueues_admin_token_usage_row():
    """Claude adapter usage must reach token_usage_log for agentys-admin."""
    from app.infrastructure.llm_attribution import llm_attribution

    captured = []
    usage = _FakeUsage(
        input_tokens=100,
        cache_creation_input_tokens=200,
        cache_read_input_tokens=700,
        output_tokens=80,
    )

    with patch(
        "app.infrastructure.token_usage_writer.enqueue",
        side_effect=lambda record: captured.append(record),
    ):
        with llm_attribution("drafter", account_id=42):
            recorded = _log_usage("claude-haiku-4-5-20251001", usage, kind="complete")

    assert recorded is True
    assert len(captured) == 1
    row = captured[0]
    assert row.account_id == 42
    assert row.agent == "drafter"
    assert row.model == "claude-haiku-4-5-20251001"
    assert row.input_tokens == 100
    assert row.cache_creation_input_tokens == 200
    assert row.cache_read_input_tokens == 700
    assert row.output_tokens == 80
    assert row.cost_usd > 0


def test_log_usage_uses_usage_context_for_direct_calls():
    """Direct ClaudeAdapter calls must keep account/user/feature attribution."""
    from app.infrastructure.cost_manager import reset_usage_context, set_usage_context

    captured = []
    usage = _FakeUsage(input_tokens=133, output_tokens=1)
    tokens = set_usage_context(
        account_id=14,
        user_id=1694432691,
        feature="learning_refresh_full",
    )
    try:
        with patch(
            "app.infrastructure.token_usage_writer.enqueue",
            side_effect=lambda record: captured.append(record),
        ):
            recorded = _log_usage("claude-haiku-4-5-20251001", usage, kind="complete")
    finally:
        reset_usage_context(tokens)

    assert recorded is True
    assert len(captured) == 1
    row = captured[0]
    assert row.account_id == 14
    assert row.user_id == 1694432691
    assert row.feature == "learning_refresh_full"
    assert row.agent == "claude_complete"
