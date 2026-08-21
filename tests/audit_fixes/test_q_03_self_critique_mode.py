# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Q-03 — SELF_CRITIQUE_MODE alias (2026-05-05).

Existing knob `SELF_CRITIQUE_SAMPLE_RATE` (0.0–1.0) is correct but opaque
to ops. New env var `SELF_CRITIQUE_MODE` provides the off / shadow / active
vocabulary documented in tasks/draft-pipeline-optimization-2026-05-03.md
without breaking the explicit-rate override that ops can use for partial
rollouts (e.g. 0.25 during canary).
"""
from __future__ import annotations


def test_default_is_shadow(monkeypatch):
    monkeypatch.delenv("SELF_CRITIQUE_SAMPLE_RATE", raising=False)
    monkeypatch.delenv("SELF_CRITIQUE_MODE", raising=False)
    from app.application.services._compose_path import _get_sample_rate
    assert _get_sample_rate() == 0.10, "Default mode (no envs) must be shadow @ 10%"


def test_mode_off(monkeypatch):
    monkeypatch.delenv("SELF_CRITIQUE_SAMPLE_RATE", raising=False)
    monkeypatch.setenv("SELF_CRITIQUE_MODE", "off")
    from app.application.services._compose_path import _get_sample_rate
    assert _get_sample_rate() == 0.0


def test_mode_active(monkeypatch):
    monkeypatch.delenv("SELF_CRITIQUE_SAMPLE_RATE", raising=False)
    monkeypatch.setenv("SELF_CRITIQUE_MODE", "active")
    from app.application.services._compose_path import _get_sample_rate
    assert _get_sample_rate() == 1.0


def test_explicit_rate_overrides_mode(monkeypatch):
    """When ops pin a specific rate (canary), MODE must not override it."""
    monkeypatch.setenv("SELF_CRITIQUE_MODE", "off")
    monkeypatch.setenv("SELF_CRITIQUE_SAMPLE_RATE", "0.25")
    from app.application.services._compose_path import _get_sample_rate
    assert _get_sample_rate() == 0.25, (
        "Explicit SELF_CRITIQUE_SAMPLE_RATE must win — used during canary "
        "rollouts where MODE alone is too coarse."
    )


def test_unknown_mode_defaults_to_shadow(monkeypatch):
    monkeypatch.delenv("SELF_CRITIQUE_SAMPLE_RATE", raising=False)
    monkeypatch.setenv("SELF_CRITIQUE_MODE", "garbage")
    from app.application.services._compose_path import _get_sample_rate
    assert _get_sample_rate() == 0.10
