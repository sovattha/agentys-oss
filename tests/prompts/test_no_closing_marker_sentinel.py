# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Bug fix regression — onboarding sentinel "(no closing or just name)"
must not leak into LLM-rendered email bodies (2026-05-11).

Source: live-audit screenshot showed a generated reply ending with the
literal string `(no closing or just name),` — the sentinel that
ProfileAgent stores in `tone.closing_styles.casual_fr` to indicate
"this user uses no closing in casual register". The onboarding manager
flattens all closing_styles values into WritingStyleProfile.preferred_closings,
which is then read by _compute_closing_hint (and style_guidance for
per-contact overrides). Both consumers used to pass the sentinel through
verbatim.

Run: pytest tests/prompts/test_no_closing_marker_sentinel.py -v
"""

from __future__ import annotations

import pytest

from app.prompts.identity import (
    _compute_closing_hint,
    _is_no_closing_marker,
)


class TestSentinelDetection:
    @pytest.mark.parametrize("s", [
        "(no closing or just name)",
        "no closing or just name",
        "No Closing",
        "  just name  ",
        "JUST NAME",
        "(no closing)",
    ])
    def test_detects_sentinel_variants(self, s):
        assert _is_no_closing_marker(s) is True

    @pytest.mark.parametrize("s", [
        "Cordialement",
        "Best regards",
        "Merci",
        "Cheers",
        "",
        None,
    ])
    def test_does_not_flag_real_closings(self, s):
        assert _is_no_closing_marker(s) is False


class TestComputeClosingHint:
    def test_sentinel_only_returns_empty(self):
        """When the only preferred closing is the sentinel, return '' so
        the LLM gets no closing instruction (matches the user's stated
        preference)."""
        result = _compute_closing_hint(
            formality=2,
            language="FRENCH",
            preferred_closings=["(no closing or just name)"],
        )
        assert result == "", (
            f"Sentinel leaked through as {result!r} — would render as "
            f"`(no closing or just name),` in the email body."
        )

    def test_sentinel_falls_through_to_real_closing(self):
        """If preferred_closings contains both the sentinel (casual_*) and
        a real closing (semi_formal_*), the real closing wins."""
        result = _compute_closing_hint(
            formality=3,
            language="FRENCH",
            preferred_closings=["(no closing or just name)", "Merci,"],
        )
        assert result == "Merci,"

    def test_sentinel_with_only_real_closings(self):
        """Regression guard: real closings still take priority."""
        result = _compute_closing_hint(
            formality=3,
            language="FRENCH",
            preferred_closings=["Cordialement", "Bien à vous"],
        )
        assert result == "Cordialement,"

    def test_no_preferred_falls_back_to_formality_default(self):
        """Empty preferred_closings → formality default."""
        result = _compute_closing_hint(
            formality=3,
            language="ENGLISH",
            preferred_closings=[],
        )
        assert result == "Best,"

    def test_sentinel_does_not_override_default_when_other_sources_silent(self):
        """Edge case: only sentinel present + formality 3 → return ""
        because the user has explicitly signalled "no closing". Better
        to omit than to fabricate a default that contradicts the stated
        preference."""
        result = _compute_closing_hint(
            formality=3,
            language="ENGLISH",
            preferred_closings=["(no closing or just name)"],
        )
        assert result == ""

    def test_english_translation_still_works(self):
        """Regression guard for the pre-existing French→English translation
        path — the sentinel filter must not break it."""
        result = _compute_closing_hint(
            formality=3,
            language="ENGLISH",
            preferred_closings=["Cordialement"],
        )
        # Expected to translate to a sensible English equivalent.
        assert "Cordialement" not in result
        assert result.endswith(",")

    @pytest.mark.parametrize("closing", ["Best regards", "Thank you"])
    def test_english_preferred_closing_is_not_used_for_french_reply(self, closing):
        result = _compute_closing_hint(
            formality=3,
            language="FRENCH",
            preferred_closings=[closing],
        )
        assert result == "Sincèrement,"


class TestSpanishClosingHint:
    """Audit 2026-05-19 F-03: detected Spanish used to map to FRENCH, so a
    Spanish refine-text draft got a French closing ("Cordialement,").
    _compute_closing_hint now has a real SPANISH branch and refuses to leak a
    French/English preferred closing onto a Spanish draft."""

    @pytest.mark.parametrize("formality,expected", [
        (5, "Atentamente,"),
        (4, "Atentamente,"),
        (3, "Saludos cordiales,"),
        (2, "Un saludo,"),
        (1, ""),  # very casual — no closing, like FR/EN
    ])
    def test_spanish_formality_defaults(self, formality, expected):
        result = _compute_closing_hint(
            formality=formality,
            language="SPANISH",
            preferred_closings=[],
        )
        assert result == expected

    @pytest.mark.parametrize("closing", ["Cordialement", "Bien à vous", "À bientôt"])
    def test_french_preferred_closing_not_leaked_into_spanish(self, closing):
        """A French user's preferred closing must NOT appear on a Spanish draft —
        fall through to the Spanish formality default instead."""
        result = _compute_closing_hint(
            formality=4,
            language="SPANISH",
            preferred_closings=[closing],
        )
        assert result == "Atentamente,"

    @pytest.mark.parametrize("closing", ["Best regards", "Thank you", "Cheers"])
    def test_english_preferred_closing_not_leaked_into_spanish(self, closing):
        result = _compute_closing_hint(
            formality=3,
            language="SPANISH",
            preferred_closings=[closing],
        )
        assert result == "Saludos cordiales,"

    def test_spanish_never_returns_a_french_closing(self):
        """The core F-03 guarantee: no SPANISH formality produces a FR closing."""
        french = {"Cordialement,", "Sincèrement,", "À bientôt,", "Bien à vous,"}
        for formality in range(1, 6):
            result = _compute_closing_hint(formality, "SPANISH", [])
            assert result not in french, (
                f"formality={formality} produced FR closing {result!r} on a Spanish draft"
            )
