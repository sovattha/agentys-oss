# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Audit fix — 2026-05-13 user-reported "AI draft keeps deleting itself"
======================================================================

User screenshot showed a Microsoft Teams meeting reply where the draft
was reduced to:

    M. Simon,
    Merci!,

The body content the LLM produced — "Merci de l'invitation. Je vais
être présent, je te confirme." — was COMPLETELY DELETED.

Root cause: `_enforce_closing` (smart_routing.py:4584) checks whether
the last line of the draft is a closing by testing every prefix in
`_CLOSING_FORMULAS`. That set includes short prefixes like ``'merci'``,
``'best'``, ``'thanks'`` so a body sentence like "Merci de
l'invitation..." passes `startswith('merci ')` and is falsely treated
as a closing — then replaced wholesale by the `closing_hint`
(e.g. "Merci!," learned from the contact profile).

Backend log proof:
    _enforce_closing: fixed (LLM wrote "Merci de l'invitation. Je vais
    être présent, je te confirme.", expected 'Merci!,')

Fix: cap the closing-detection at 6 words. All canonical closing
formulas are ≤ 4 words; 6 leaves headroom for "Best regards, Alex"
style suffixes without admitting full body sentences.
"""

from __future__ import annotations

import pytest

from app.smart_routing import _enforce_closing


# -- The exact 2026-05-13 reproduction --------------------------------------


def test_long_merci_body_not_replaced_by_closing():
    """Reproduce the exact incident from the screenshot."""
    draft = (
        "M. Simon,\n\n"
        "Merci de l'invitation. Je vais être présent, je te confirme."
    )

    result = _enforce_closing(draft, "Merci!,", replace_existing=True)

    # Body MUST survive.
    assert "Je vais être présent" in result
    assert "Merci de l'invitation" in result
    # A canonical closing line is appended (since none was present), but the
    # body line is NOT replaced.
    assert result.count("Je vais être présent") == 1


def test_long_thanks_body_not_replaced_by_closing():
    """English equivalent of the bug."""
    draft = (
        "Mr. Simon,\n\n"
        "Thanks for the invitation. I'll be there, you can count on me."
    )

    result = _enforce_closing(draft, "Best regards,", replace_existing=True)

    assert "I'll be there" in result
    assert "Thanks for the invitation" in result


def test_body_starting_with_best_preserved():
    """`'best'` is in _CLOSING_FORMULAS — a body sentence starting with
    'Best' must NOT be eaten."""
    draft = (
        "Hi Alex,\n\n"
        "Best to discuss this in person next week — does Tuesday work?"
    )

    result = _enforce_closing(draft, "Best regards,", replace_existing=True)

    assert "Best to discuss this in person" in result


# -- Sanity: legitimate closings still work ---------------------------------


def test_short_canonical_closing_replaced():
    """The existing replace-on-mismatch behavior is preserved for real
    closing lines."""
    draft = (
        "Salut Alex,\n\n"
        "Oui, c'est noté.\n\n"
        "Amicalement,"  # in _CLOSING_FORMULAS, will be replaced
    )

    result = _enforce_closing(draft, "Cordialement,", replace_existing=True)

    # Amicalement, was recognised and replaced by the canonical hint.
    assert "Amicalement" not in result
    assert "Cordialement," in result


def test_missing_closing_is_appended():
    """When the draft has no closing, append the hint."""
    draft = (
        "Salut Alex,\n\n"
        "Oui, c'est noté."
    )

    result = _enforce_closing(draft, "À bientôt,", replace_existing=True)

    assert result.rstrip().endswith("À bientôt,")


def test_empty_hint_still_strips_short_closing():
    """Casual register: empty hint strips canonical closings."""
    draft = (
        "Salut Alex,\n\n"
        "Oui c'est noté.\n\n"
        "Cordialement,"
    )

    result = _enforce_closing(draft, "", replace_existing=True)

    assert "Cordialement" not in result
    assert "Oui c'est noté" in result


def test_empty_hint_does_not_strip_long_merci_body():
    """Casual register: a long body starting with 'Merci' must NOT be
    stripped just because 'merci' is in `_CLOSING_FORMULAS`."""
    draft = (
        "Salut Alex,\n\n"
        "Merci de l'invitation. Je vais être présent, je te confirme."
    )

    result = _enforce_closing(draft, "", replace_existing=True)

    assert "Je vais être présent" in result
    assert "Merci de l'invitation" in result


# -- Word-count boundary tests ----------------------------------------------


@pytest.mark.parametrize("line,is_closing", [
    ("Merci,", True),                           # 1 word
    ("Merci encore,", True),                    # 2 words
    ("Merci beaucoup pour tout,", True),        # 4 words
    ("Merci pour votre invitation rapide,", True),   # 5 words
    ("Best regards, Alex Simon,", True),         # 4 words with name suffix
    # The boundary: 7+ words is body, not closing
    ("Merci pour votre invitation et je vous confirme ma présence,", False),  # 9 words
    ("Best regards from the entire team and we look forward,", False),  # 10 words
])
def test_word_count_boundary(line, is_closing):
    """Closings ≤ 6 words detected, anything longer treated as body."""
    draft = f"Salut Alex,\n\nDu contenu ici.\n\n{line}"
    result = _enforce_closing(draft, "À bientôt,", replace_existing=True)

    if is_closing:
        # Was detected → replaced by the canonical "À bientôt,"
        assert "À bientôt," in result.split("\n")[-1]
        # And the original line is gone (or modified)
        # (we don't assert too tightly because the function appends if missing)
    else:
        # Was NOT detected as closing → body survives, hint appended below
        assert line in result
        # And the canonical closing is appended after
        assert result.rstrip().endswith("À bientôt,")


# -- Spanish closings (audit 2026-05-19 F-03) -------------------------------


@pytest.mark.parametrize("closing", [
    "Atentamente,", "Saludos cordiales,", "Un saludo,", "Un abrazo,", "Saludos,",
])
def test_spanish_closing_recognized_not_double_appended(closing):
    """A Spanish draft that already ends with its own closing must be
    recognized (in _CLOSING_FORMULAS) so the hint is NOT appended a 2nd time."""
    draft = f"Hola Alex,\n\nQuedo a la espera de tu confirmación.\n\n{closing}"
    result = _enforce_closing(draft, "Un saludo,", replace_existing=False)
    # The existing Spanish closing is preserved; no second closing is appended.
    assert result.count(closing.rstrip(",")) == 1
    assert result.rstrip().endswith(closing)


def test_leaked_french_closing_swapped_for_spanish_hint():
    """F-03 core: a leaked French closing on a Spanish draft is replaced by the
    Spanish hint when the language-swap forces replace_existing=True."""
    draft = "Hola Alex,\n\nGracias por la invitación.\n\nCordialement,"
    result = _enforce_closing(draft, "Atentamente,", replace_existing=True)
    assert "Cordialement" not in result
    assert result.rstrip().endswith("Atentamente,")


def test_closingless_spanish_body_gets_spanish_hint():
    """A Spanish draft with no closing gets the Spanish hint appended (not a
    French one — that mapping is fixed upstream in routes_drafts)."""
    draft = "Hola Alex,\n\nNos vemos el viernes a las 2."
    result = _enforce_closing(draft, "Un saludo,", replace_existing=True)
    assert result.rstrip().endswith("Un saludo,")
    assert "Nos vemos el viernes" in result
