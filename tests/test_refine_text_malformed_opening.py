# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Regression tests for refine-text malformed-opening detection
(user report 2026-05-12: dictated notes produced "Je ne peux pas mais Je,
demain..." with no greeting at all).

Two helpers under test:
- ``_strip_malformed_opening``  — surgical strip of "Je [verb] mais Je,"
- ``_ensure_starts_with_greeting`` — prepend mandatory_opening when missing
"""

import os
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-dummy")

from app.smart_routing import (
    _ensure_starts_with_greeting,
    _strip_malformed_opening,
)


# --------------------------------------------------------------------------- #
# _strip_malformed_opening
# --------------------------------------------------------------------------- #

class TestStripMalformedOpening:
    def test_strips_exact_reported_pattern(self):
        """The user-reported bad draft starts with this exact prefix."""
        bad = (
            "Je ne peux pas mais Je, demain je ne suis pas disponible pour "
            "une rencontre. Si tu veux discuter de sujets pour Agentys, je "
            "peux te proposer quelques créneaux."
        )
        out = _strip_malformed_opening(bad)
        assert out.startswith("Demain je ne suis pas disponible")
        assert "Je ne peux pas mais Je," not in out

    def test_strips_dois_mais_je_variant(self):
        bad = "Je dois mais Je, demain je suis occupé."
        out = _strip_malformed_opening(bad)
        assert out.startswith("Demain je suis occupé")

    def test_english_variant(self):
        bad = "I cannot but I, tomorrow I am not available for a meeting."
        out = _strip_malformed_opening(bad)
        assert out.startswith("Tomorrow I am not available")

    def test_leaves_normal_je_sentence_alone(self):
        """`Je ne peux pas` appearing legitimately in prose must NOT be
        touched — only the double-pronoun + trailing-comma anti-pattern
        matters."""
        clean = "Bonjour Alexandre,\n\nJe ne peux pas venir demain. À bientôt,"
        assert _strip_malformed_opening(clean) == clean

    def test_leaves_normal_greeting_alone(self):
        clean = "Bonjour Alex,\n\nDemain je suis dispo. À bientôt,"
        assert _strip_malformed_opening(clean) == clean

    def test_handles_empty_string(self):
        assert _strip_malformed_opening("") == ""

    def test_handles_none_safe(self):
        # Defensive: callers may pass None during early-return paths.
        assert _strip_malformed_opening(None) is None  # type: ignore[arg-type]

    def test_only_strips_first_occurrence(self):
        bad = (
            "Je ne peux pas mais Je, demain je suis occupé. Plus tard, "
            "Je dois mais Je, faire autre chose."
        )
        out = _strip_malformed_opening(bad)
        # Only the leading instance gets stripped; mid-paragraph
        # legitimate "Je dois mais Je," (rare but possible in prose) is
        # left for human review.
        assert out.startswith("Demain je suis occupé")
        assert "Je dois mais Je," in out


# --------------------------------------------------------------------------- #
# _ensure_starts_with_greeting
# --------------------------------------------------------------------------- #

class TestEnsureStartsWithGreeting:
    def test_prepends_when_no_greeting(self):
        body = (
            "Demain je ne suis pas disponible pour une rencontre. Si tu "
            "veux discuter de sujets pour Agentys, je peux te proposer "
            "quelques créneaux.\n\nÀ bientôt,"
        )
        out = _ensure_starts_with_greeting(body, "Bonjour Alexandre,")
        assert out.startswith("Bonjour Alexandre,\n\nDemain je ne suis pas")

    def test_does_nothing_when_greeting_already_present(self):
        body = "Bonjour Alex,\n\nDemain je suis dispo. À bientôt,"
        assert _ensure_starts_with_greeting(body, "Bonjour Alexandre,") == body

    def test_recognises_salut(self):
        body = "Salut Alex,\n\nDispo demain. À bientôt,"
        # Should NOT replace Salut with Bonjour — the LLM chose informal,
        # respect it.
        assert _ensure_starts_with_greeting(body, "Bonjour Alexandre,") == body

    def test_recognises_english_hi(self):
        body = "Hi Alex,\n\nFree tomorrow. Cheers,"
        assert _ensure_starts_with_greeting(body, "Hello Alex,") == body

    def test_recognises_formal_monsieur(self):
        body = "Monsieur Simon,\n\nJe vous écris. Cordialement,"
        assert _ensure_starts_with_greeting(body, "Bonjour Alexandre,") == body

    def test_no_op_when_no_mandatory_opening(self):
        body = "Demain je suis pas dispo."
        # No opening hint to prepend — leave the draft as-is.
        assert _ensure_starts_with_greeting(body, None) == body
        assert _ensure_starts_with_greeting(body, "") == body

    def test_no_op_on_empty_draft(self):
        assert _ensure_starts_with_greeting("", "Bonjour Alex,") == ""

    def test_inserts_one_blank_line_between_greeting_and_body(self):
        body = "Demain je suis pas dispo."
        out = _ensure_starts_with_greeting(body, "Bonjour Alex,")
        # exact shape: greeting, blank line, body
        assert out == "Bonjour Alex,\n\nDemain je suis pas dispo."

    def test_handles_leading_blank_lines_in_input(self):
        body = "\n\nDemain je suis pas dispo."
        out = _ensure_starts_with_greeting(body, "Bonjour Alex,")
        # Leading blanks collapsed when prepending so we don't accumulate
        # 4+ \n in the final output.
        assert out == "Bonjour Alex,\n\nDemain je suis pas dispo."
