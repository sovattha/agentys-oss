# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests for the P1.4 + P2.8 self-critique sampling + regen helpers.

Covers the pure functions in app/application/services/_compose_path.py that
gained behaviour in the 2026-05-04 audit. Wiring through DraftService is
already covered by tests/application/services/test_draft_service_compose.py.
"""

from __future__ import annotations

import os

import pytest

from app.application.services._compose_path import (
    SELF_CRITIQUE_REGEN_THRESHOLD,
    _get_sample_rate,
    build_regen_user_prompt,
    should_regen_from_critique,
)
from app.domain.entities.self_critique import SelfCritique


class TestGetSampleRate:
    def teardown_method(self):
        os.environ.pop("SELF_CRITIQUE_SAMPLE_RATE", None)

    def test_default_is_ten_percent(self):
        os.environ.pop("SELF_CRITIQUE_SAMPLE_RATE", None)
        assert _get_sample_rate() == pytest.approx(0.10)

    def test_invalid_env_falls_back_to_default(self):
        os.environ["SELF_CRITIQUE_SAMPLE_RATE"] = "not-a-number"
        assert _get_sample_rate() == pytest.approx(0.10)

    def test_clamped_above_one(self):
        os.environ["SELF_CRITIQUE_SAMPLE_RATE"] = "5.0"
        assert _get_sample_rate() == 1.0

    def test_clamped_below_zero(self):
        os.environ["SELF_CRITIQUE_SAMPLE_RATE"] = "-0.5"
        assert _get_sample_rate() == 0.0

    def test_zero_disables_sampling(self):
        os.environ["SELF_CRITIQUE_SAMPLE_RATE"] = "0"
        assert _get_sample_rate() == 0.0


class TestShouldRegenFromCritique:
    def test_none_critique_does_not_regen(self):
        # Most common case: 90% of composes (not sampled) → critique=None
        assert should_regen_from_critique(None) is False

    def test_failed_evaluation_does_not_regen(self):
        # LLM/parse/IO failure on critique itself — don't regen on a non-signal
        crit = SelfCritique.create_failed(reason="json_parse_failed")
        assert should_regen_from_critique(crit) is False

    def test_high_score_does_not_regen(self):
        crit = SelfCritique(self_score=85, risks=("placeholder",))
        assert should_regen_from_critique(crit) is False

    def test_threshold_boundary(self):
        # Exactly at the threshold = no regen (strict <)
        crit = SelfCritique(
            self_score=SELF_CRITIQUE_REGEN_THRESHOLD,
            risks=("placeholder",),
        )
        assert should_regen_from_critique(crit) is False
        crit_below = SelfCritique(
            self_score=SELF_CRITIQUE_REGEN_THRESHOLD - 1,
            risks=("placeholder",),
        )
        assert should_regen_from_critique(crit_below) is True

    def test_low_score_no_risks_does_not_regen(self):
        # Score is just a number — without an actionable risk, regen has
        # nothing to fix. This avoids regen-loops on "low confidence" verdicts.
        crit = SelfCritique(self_score=40, risks=())
        assert should_regen_from_critique(crit) is False

    def test_low_score_filler_only_does_not_regen(self):
        # filler is stylistic, not actionable — leave to the user.
        crit = SelfCritique(self_score=40, risks=("filler",))
        assert should_regen_from_critique(crit) is False

    def test_low_score_length_excessive_only_does_not_regen(self):
        # length_excessive is stylistic.
        crit = SelfCritique(self_score=40, risks=("length_excessive",))
        assert should_regen_from_critique(crit) is False

    @pytest.mark.parametrize("risk", [
        "hallucination",
        "placeholder",
        "tone_mismatch",
        "off_topic",
        "language_drift",
        "signature_doubled",
    ])
    def test_actionable_risks_trigger_regen(self, risk):
        crit = SelfCritique(self_score=40, risks=(risk,))
        assert should_regen_from_critique(crit) is True

    def test_mixed_risks_with_one_actionable_triggers_regen(self):
        crit = SelfCritique(
            self_score=40,
            risks=("filler", "placeholder", "length_excessive"),
        )
        assert should_regen_from_critique(crit) is True


class TestBuildRegenUserPrompt:
    def test_appends_corrective_block(self):
        crit = SelfCritique(
            self_score=45,
            risks=("placeholder", "tone_mismatch"),
        )
        out = build_regen_user_prompt(
            "Original prompt body.",
            crit,
            mandatory_opening=None,
        )
        assert out.startswith("Original prompt body.")
        assert "RÉVISION OBLIGATOIRE" in out
        assert "45/100" in out
        assert "placeholder" in out
        assert "tone_mismatch" in out

    def test_includes_mandatory_opening_when_set(self):
        crit = SelfCritique(self_score=30, risks=("placeholder",))
        out = build_regen_user_prompt(
            "Prompt.",
            crit,
            mandatory_opening="Salut Alex,",
        )
        # The mandatory opening must be quoted explicitly so the LLM does not
        # drop it on the V2 pass — the regen instruction reasserts it.
        assert "«Salut Alex,»" in out

    def test_no_risks_falls_back_to_generic_message(self):
        # Defensive: should_regen_from_critique blocks empty risks, but the
        # builder must still produce a sane prompt if called with risks=().
        crit = SelfCritique(self_score=30, risks=())
        out = build_regen_user_prompt("Prompt.", crit, mandatory_opening=None)
        assert "qualité globale insuffisante" in out

    def test_anti_placeholder_directive_is_present(self):
        # The corrective block must explicitly forbid re-introducing
        # placeholders (the most common regen-loop trap).
        crit = SelfCritique(self_score=30, risks=("placeholder",))
        out = build_regen_user_prompt("Prompt.", crit, mandatory_opening=None)
        assert "[À confirmer]" in out or "[TBD]" in out
