# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Q-09 — Tier-/intent-aware critique threshold (audit 2026-05-06).

Pre-fix: CriticAgent applied a uniform 70/100 threshold regardless of
the email's risk profile. A simple "got it, thanks" reply was rejected
on 69, but a decline-letter scoring 71 shipped — same gate, different
cost-of-error.

Post-fix: ``_effective_threshold`` reads ``intent`` from the
CritiqueRequest and looks up a per-intent map. Decline / RH /
complaint = 78, simple ack = 60, default = 70. Env override
``CRITIC_THRESHOLD_OVERRIDE`` wins for canary tuning.
"""
from __future__ import annotations


def _make_critic():
    from app.agents import CriticAgent
    # Bypass __post_init__ (which hits the LLM container) by using __new__
    # and populating only the slots the threshold path reads.
    c = CriticAgent.__new__(CriticAgent)
    c.quality_threshold = 70
    c._INTENT_THRESHOLDS = {
        "decline": 78, "complaint": 78, "rh": 78,
        "termination": 80, "negotiation": 75, "objection": 75,
        "tone_sensitive": 78,
        "scheduling": 68,
        "acknowledgment": 60, "ack": 60,
    }
    return c


def test_default_is_uniform_70():
    c = _make_critic()
    assert c._effective_threshold(intent=None) == 70
    assert c._effective_threshold(intent="") == 70


def test_decline_is_strict():
    c = _make_critic()
    assert c._effective_threshold(intent="decline") == 78
    assert c._effective_threshold(intent="DECLINE") == 78


def test_acknowledgment_is_lenient():
    c = _make_critic()
    assert c._effective_threshold(intent="acknowledgment") == 60
    assert c._effective_threshold(intent="ack") == 60


def test_tone_sensitive_marker_maps_to_decline_bracket():
    """smart_routing emits 'tone_sensitive' as a coarse marker — must be 78."""
    c = _make_critic()
    assert c._effective_threshold(intent="tone_sensitive") == 78


def test_unknown_intent_falls_back():
    c = _make_critic()
    assert c._effective_threshold(intent="unknown_intent") == 70


def test_env_override_wins(monkeypatch):
    c = _make_critic()
    monkeypatch.setenv("CRITIC_THRESHOLD_OVERRIDE", "85")
    assert c._effective_threshold(intent="acknowledgment") == 85
    # Out-of-range values are ignored.
    monkeypatch.setenv("CRITIC_THRESHOLD_OVERRIDE", "9999")
    assert c._effective_threshold(intent="decline") == 78
    monkeypatch.setenv("CRITIC_THRESHOLD_OVERRIDE", "garbage")
    assert c._effective_threshold(intent="decline") == 78
