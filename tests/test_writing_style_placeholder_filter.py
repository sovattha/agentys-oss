# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Writing-style "no signal" placeholders must never reach a draft."""

import pytest

from app.prompts.identity import (
    _compute_closing_hint,
    _compute_greeting_hint,
    is_placeholder_style_value,
)


@pytest.mark.parametrize("value", [
    "Unknown",
    "Unknown (forwarded content)",
    "Unknown (empty bodies)",
    "Salut Unknown",
    "Inconnu",
    "Inconnue",
    "None",
    "null",
    "N/A",
    "undefined",
    "(forwarded content)",
    "(empty bodies)",
])
def test_placeholder_detected(value):
    assert is_placeholder_style_value(value) is True


@pytest.mark.parametrize("value", [
    "Bonjour",
    "Salut",
    "À bientôt",
    "Cordialement",
    "Salut Émilie",
    "Best regards",
    "",
    "   ",
])
def test_real_value_not_flagged(value):
    assert is_placeholder_style_value(value) is False


def test_greeting_unknown_name_generic_fr_casual():
    assert _compute_greeting_hint("Unknown", formality=2, language="FRENCH") == "Salut,"


def test_greeting_real_name_preserved():
    out = _compute_greeting_hint("Émilie Gauthier", formality=2, language="FRENCH")
    assert "émilie" in out.lower()
    assert "unknown" not in out.lower()


def test_closing_skips_placeholder_uses_fr_default():
    out = _compute_closing_hint(3, "FRENCH", preferred_closings=["Unknown (forwarded content)"])
    assert out == "Sincèrement,"
    assert "Unknown" not in out


def test_closing_prefers_real_over_placeholder():
    out = _compute_closing_hint(
        3,
        "FRENCH",
        preferred_closings=["Unknown (forwarded content)", "Cordialement"],
    )
    assert out == "Cordialement,"


def test_analyzer_build_profile_drops_placeholders():
    from app.adapters.style.writing_style_analyzer_adapter import WritingStyleAnalyzerAdapter

    adapter = WritingStyleAnalyzerAdapter.__new__(WritingStyleAnalyzerAdapter)
    profile = adapter._build_profile(
        account_id=1,
        email_count=5,
        avg_email_length=100,
        llm_result={
            "formality_level": "casual",
            "preferred_greetings": ["Salut Unknown", "Bonjour"],
            "preferred_closings": ["Unknown (forwarded content)", "À bientôt"],
        },
        analysis_duration_ms=10,
    )

    assert profile.preferred_greetings == ["Bonjour"]
    assert profile.preferred_closings == ["À bientôt"]
