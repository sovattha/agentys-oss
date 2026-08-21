# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests for the inline-closing-duplicate safety net inside
`_strip_trailing_signature` — protects bug #G-DoubleClosing.

Bug: the LLM glued a closing exclamation to the end of a body sentence
("...vendredi à 10h. À très bientôt!") AND also produced a standalone
closing line ("À bientôt,"), yielding two sign-offs in the rendered
draft. The safety net detects both being present and strips the inline
one — the standalone line is authoritative because the user's signature
template re-appends only one closing.
"""

from __future__ import annotations

from app.api.routes_drafts import _strip_trailing_signature


def test_strips_inline_closing_when_standalone_closing_present():
    body = (
        "Bonjour Alexandra,\n\n"
        "Parfait! J'ai accepté l'invitation et je te confirme ma présence "
        "vendredi à 10h. À très bientôt!\n\n"
        "À bientôt,"
    )
    out = _strip_trailing_signature(body)
    # The inline "À très bientôt!" must be stripped; the standalone closing stays.
    assert "À très bientôt" not in out.replace("À bientôt", "")
    assert out.rstrip().endswith("À bientôt,")
    # Body sentence remains intact otherwise.
    assert "vendredi à 10h." in out


def test_keeps_inline_phrase_when_no_standalone_closing():
    """When the LLM produced ONLY one closing (the inline one), we keep it.
    This is the "don't over-strip" guard — the safety net is opt-in to
    cases where two closings are clearly present.
    """
    body = (
        "Salut Alex,\n\n"
        "Tout est OK pour vendredi. À très bientôt!"
    )
    out = _strip_trailing_signature(body)
    assert "À très bientôt" in out


def test_keeps_legitimate_body_phrase_without_punctuation_anchor():
    """The regex requires a sentence-ending punctuation BEFORE the inline
    closing. A standalone "Merci" mid-sentence must NOT be stripped.
    """
    body = (
        "Bonjour,\n\n"
        "J'ai bien reçu et merci pour le suivi.\n\n"
        "Cordialement,"
    )
    out = _strip_trailing_signature(body)
    # `merci` mid-sentence is not anchored after a period — keep it.
    assert "merci pour le suivi" in out
    assert out.rstrip().endswith("Cordialement,")


def test_preserves_non_closing_sentence_endings():
    """Body ending with a normal exclamation that is NOT a closing phrase
    must be preserved (e.g. "C'est parfait!"). Only canonical closing
    phrases are stripped.
    """
    body = (
        "Hi Sarah,\n\n"
        "That's perfect!\n\n"
        "Best,"
    )
    out = _strip_trailing_signature(body)
    assert "That's perfect!" in out
    assert out.rstrip().endswith("Best,")


def test_strips_inline_a_bientot_with_standalone_cordialement():
    """Cross-form duplicate: inline "à bientôt!" + standalone "Cordialement,"."""
    body = (
        "Bonjour,\n\n"
        "C'est noté. à bientôt!\n\n"
        "Cordialement,"
    )
    out = _strip_trailing_signature(body)
    # Only "Cordialement," remains as closing.
    assert out.count("bientôt") == 0
    assert out.rstrip().endswith("Cordialement,")


def test_strips_inline_talk_soon_with_standalone_best():
    body = (
        "Hi Sam,\n\n"
        "Confirmed for Friday. Talk soon!\n\n"
        "Best,"
    )
    out = _strip_trailing_signature(body)
    assert "Talk soon" not in out
    assert out.rstrip().endswith("Best,")


def test_idempotent_on_already_clean_body():
    body = (
        "Bonjour Alexandra,\n\n"
        "Vendredi 10h c'est confirmé.\n\n"
        "À bientôt,"
    )
    out = _strip_trailing_signature(body)
    assert out.strip() == body.strip()
