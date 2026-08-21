# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
F-04 (audit 2026-05-19): a Spanish refine/compose draft must receive a SPANISH
closing, never a leaked French/English one.

Regression context: refine-text mapped detected_lang "es" -> drafter language
"FRENCH", and _compute_closing_hint had no SPANISH branch, so a French closing
("Cordialement," / "À bientôt,") was actively appended to Spanish drafts. The
fix maps es -> SPANISH end-to-end; these tests pin the SPANISH branch of
_compute_closing_hint (the closing-hint source of truth) so the regression
cannot silently come back.
"""
import pytest

from app.prompts.identity import _compute_closing_hint


class TestComputeClosingHintSpanish:
    """SPANISH formality defaults (the F-04 fix surface)."""

    @pytest.mark.parametrize("formality", [4, 5])
    def test_spanish_formal_returns_atentamente(self, formality):
        assert _compute_closing_hint(formality, "SPANISH") == "Atentamente,"

    def test_spanish_mid_returns_saludos_cordiales(self):
        assert _compute_closing_hint(3, "SPANISH") == "Saludos cordiales,"

    def test_spanish_casual_returns_un_saludo(self):
        assert _compute_closing_hint(2, "SPANISH") == "Un saludo,"

    def test_spanish_very_casual_returns_no_closing(self):
        # Formality 1 = texting-a-friend register: no closing in any language.
        assert _compute_closing_hint(1, "SPANISH") == ""

    def test_spanish_never_returns_french_default(self):
        # The exact regression: a Spanish draft must not end with «À bientôt,»
        # / «Cordialement,» (the French formality defaults).
        for formality in (2, 3, 4, 5):
            out = _compute_closing_hint(formality, "SPANISH")
            assert "bientôt" not in out.lower()
            assert "cordialement" not in out.lower()


class TestComputeClosingHintSpanishSkipsLeakedClosing:
    """A French user's stored closing must not leak onto a Spanish draft."""

    def test_skips_leaked_french_preferred_closing(self):
        out = _compute_closing_hint(4, "SPANISH", ["Cordialement,"])
        assert out == "Atentamente,"

    def test_skips_leaked_english_preferred_closing(self):
        out = _compute_closing_hint(3, "SPANISH", ["Best,"])
        assert out == "Saludos cordiales,"

    def test_keeps_genuine_spanish_preferred_closing(self):
        # If the user genuinely prefers a Spanish closing, honour it verbatim.
        out = _compute_closing_hint(4, "SPANISH", ["Un abrazo,"])
        assert "abrazo" in out.lower()
        assert out != "Atentamente,"
