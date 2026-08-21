# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests for the onboarding per-agent LLM usage telemetry helper."""

from types import SimpleNamespace

import pytest

from app.onboarding.agents import _usage_telemetry as tel


def _resp(output_tokens=100, input_tokens=2000, stop_reason="end_turn",
          model="claude-haiku-4-5-20251001", cache_read_input_tokens=0):
    """Minimal duck-typed stand-in for LLMResponse."""
    return SimpleNamespace(
        output_tokens=output_tokens,
        input_tokens=input_tokens,
        stop_reason=stop_reason,
        model=model,
        cache_read_input_tokens=cache_read_input_tokens,
    )


@pytest.fixture(autouse=True)
def _isolate_capture():
    """Each test starts and ends with capture disabled."""
    tel.reset_capture()
    yield
    tel.reset_capture()


def test_capture_disabled_by_default():
    # No enable_capture() call → recording logs but captures nothing.
    tel.record_agent_usage("profile", _resp(), max_tokens=4096, duration_ms=1200, attempts=1)
    assert tel.get_capture() == []


def test_capture_records_when_enabled():
    tel.enable_capture()
    tel.record_agent_usage("style", _resp(output_tokens=512), max_tokens=8192, duration_ms=3400, attempts=1)
    captured = tel.get_capture()
    assert len(captured) == 1
    rec = captured[0]
    assert rec["agent"] == "style"
    assert rec["output_tokens"] == 512
    assert rec["max_tokens"] == 8192
    assert rec["duration_ms"] == 3400


def test_used_pct_math():
    tel.enable_capture()
    # 2048 / 8192 = 25.0%
    tel.record_agent_usage("knowledge", _resp(output_tokens=2048), max_tokens=8192, duration_ms=100)
    assert tel.get_capture()[0]["used_pct"] == 25.0


def test_used_pct_zero_when_max_tokens_zero():
    tel.enable_capture()
    tel.record_agent_usage("label", _resp(output_tokens=10), max_tokens=0, duration_ms=10)
    assert tel.get_capture()[0]["used_pct"] == 0.0


def test_truncated_detected_on_max_tokens_stop():
    tel.enable_capture()
    tel.record_agent_usage(
        "style", _resp(output_tokens=8192, stop_reason="max_tokens"),
        max_tokens=8192, duration_ms=5000,
    )
    rec = tel.get_capture()[0]
    assert rec["truncated"] is True
    assert rec["stop_reason"] == "max_tokens"


def test_not_truncated_on_end_turn():
    tel.enable_capture()
    tel.record_agent_usage("profile", _resp(stop_reason="end_turn"), max_tokens=4096, duration_ms=900)
    assert tel.get_capture()[0]["truncated"] is False


def test_reset_capture_clears_buffer():
    tel.enable_capture()
    tel.record_agent_usage("profile", _resp(), max_tokens=4096, duration_ms=900)
    assert len(tel.get_capture()) == 1
    tel.reset_capture()
    assert tel.get_capture() == []


def test_never_raises_on_malformed_response():
    tel.enable_capture()
    # None response, and an object missing all attributes — the contract is
    # "never raises". Missing attributes fall back to safe defaults (0 tokens,
    # stop="?") rather than crashing the analysis pipeline.
    tel.record_agent_usage("profile", None, max_tokens=4096, duration_ms=10)
    tel.record_agent_usage("style", object(), max_tokens=8192, duration_ms=10)
    caps = tel.get_capture()
    assert len(caps) == 2
    for rec in caps:
        assert rec["output_tokens"] == 0
        assert rec["stop_reason"] == "?"


def test_attempts_default_and_explicit():
    tel.enable_capture()
    tel.record_agent_usage("knowledge", _resp(), max_tokens=8192, duration_ms=100)
    tel.record_agent_usage("knowledge", _resp(), max_tokens=8192, duration_ms=100, attempts=2)
    caps = tel.get_capture()
    assert caps[0]["attempts"] == 1
    assert caps[1]["attempts"] == 2
